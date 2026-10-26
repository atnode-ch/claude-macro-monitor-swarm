"""Collector engine: one pass over config/domains.json.

Writes figures to data/releases/**, keeps data/state.json (dedup baseline +
collector health) and queues anything new in data/pending.json for the
macro-release routine. Numbers come from official APIs only; the LLM never
types a figure for an API-backed report.

    python -m collectors.engine                 # normal run
    python -m collectors.engine --seed          # first run: set baselines, queue nothing
    python -m collectors.engine --domain inflation --dry-run
    python -m collectors.engine --now "2026-10-07 09:00"
"""
import argparse
import calendar as cal
import json
import os
import re
import sys
from datetime import date, timedelta

from collectors import common as C

STATE = C.DATA / "state.json"
PENDING = C.DATA / "pending.json"
MARKETS_LATEST = C.DATA / "markets_latest.json"
CALENDAR = C.DATA / "calendar.json"

DECISION_GRACE_MIN = 30  # minutes after the decision time before we look for the new rate


# ---------- metric maths ----------

def _value_at(series, d):
    """Latest observation on or before d."""
    best = None
    for dt, v in series:
        if dt <= d:
            best = (dt, v)
        else:
            break
    return best


def _prev(series, d):
    prior = None
    for dt, v in series:
        if dt >= d:
            break
        prior = (dt, v)
    return prior


def _year_ago(series, d, freq):
    if freq in ("monthly", "quarterly"):
        target = date(d.year - 1, d.month, 1)
        for dt, v in series:
            if dt == target:
                return dt, v
        return None
    return _value_at(series, d - timedelta(days=364))


def _r(x, nd=3):
    return None if x is None else round(x, nd)


def part_metrics(part, main, yoy_series, at, freq):
    """Compute a part's transforms for the observation at date `at`."""
    scale = part.get("scale", 1.0)
    cur = _value_at(main, at)
    if cur is None:
        return {}
    prev = _prev(main, cur[0])
    out = {}
    for t in part["transforms"]:
        if t == "level":
            out[t] = _r(cur[1] * scale)
        elif t == "diff":
            out[t] = _r((cur[1] - prev[1]) * scale) if prev else None
        elif t == "chg_pct":
            out[t] = _r((cur[1] / prev[1] - 1.0) * 100.0) if prev and prev[1] else None
        elif t == "yoy_pct":
            ys = yoy_series or main
            c2 = _value_at(ys, cur[0])
            ya = _year_ago(ys, cur[0], freq)
            out[t] = _r((c2[1] / ya[1] - 1.0) * 100.0) if c2 and ya and ya[1] else None
    return out


def compute_series_report(rep, series_map):
    """-> (ref_date, metrics, prior_metrics). Reference date = latest date of
    the first part's main series."""
    parts = rep["parts"]
    first = next(iter(parts.values()))
    main_first = series_map[first["id"]]
    if not main_first:
        raise RuntimeError(f"no data for {first['id']}")
    ref = main_first[-1][0]
    prev = _prev(main_first, ref)
    metrics, prior = {}, {}
    for name, part in parts.items():
        main = series_map.get(part["id"], [])
        yoy = series_map.get(part.get("yoy_id")) if part.get("yoy_id") else None
        for k, v in part_metrics(part, main, yoy, ref, rep["freq"]).items():
            metrics[f"{name}.{k}"] = v
        if prev:
            for k, v in part_metrics(part, main, yoy, prev[0], rep["freq"]).items():
                prior[f"{name}.{k}"] = v
    return ref, metrics, prior


# ---------- fetchers ----------

def fetch_series_map(rep, now):
    ids = []
    for p in rep["parts"].values():
        ids.append(p["id"])
        if p.get("yoy_id"):
            ids.append(p["yoy_id"])
    if rep["source"] == "bls":
        return C.bls_series(ids, now.year - 2, now.year)
    if rep["source"] == "umich":
        return {i: umich_final(i, rep, now) for i in ids}
    return {i: C.fred_csv(i) for i in ids}


def umich_final(sid, rep, now):
    """'<table>:<col>' from the survey site. The current month only counts once
    its final is due, so a preliminary posting is never logged as the final."""
    table, _, col = sid.partition(":")
    s = C.umich_csv(table, int(col or 1))
    if s and s[-1][0].year == now.year and s[-1][0].month == now.month:
        due = due_date(rep["final_rule"], now.year, now.month)
        if (now.date(), now.hour) < (due, 10):
            s = s[:-1]
    return s


def fetch_boe_rate():
    html = C.http_get("https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates")
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    m = re.search(r"Current Bank Rate\s*([0-9]+(?:\.[0-9]+)?)%", text)
    return float(m.group(1)) if m else None


# ---------- due-date rules for web reports ----------

def due_date(rule, y, m):
    r = rule["rule"]
    if r == "nth_business_day":
        return C.business_days_in_month(y, m)[rule["n"] - 1]
    if r == "nth_weekday":
        days = [date(y, m, d) for d in range(1, cal.monthrange(y, m)[1] + 1)]
        hits = [d for d in days if d.weekday() == rule["weekday"]]
        return hits[rule["n"] - 1]
    if r == "last_weekday":
        last = date(y, m, cal.monthrange(y, m)[1])
        while last.weekday() != rule["weekday"]:
            last -= timedelta(days=1)
        return last
    if r == "day_of_month":
        d = date(y, m, min(rule["day"], cal.monthrange(y, m)[1]))
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d
    raise ValueError(f"unknown due rule {r}")


# ---------- state helpers ----------

def load_state():
    return C.load_json(STATE, {"reports": {}, "collectors": {}})


def load_pending():
    return C.load_json(PENDING, {"items": []})


def release_path(domain_id, report_id, ref):
    return C.DATA / "releases" / domain_id / report_id / f"{ref}.json"


def _queue(pending, item):
    key = (item["report"], item["ref"])
    if any((i["report"], i["ref"]) == key for i in pending["items"]):
        return False
    pending["items"].append(item)
    return True


def _new_release(domain, rep, ref, now, **kw):
    rec = {
        "domain": domain["id"],
        "report": rep["id"],
        "name": rep["name"],
        "ref": ref,
        "tier": rep.get("tier", 3),
        "detected_at": C.fmt_et(now),
        "source": rep.get("source", "web"),
        "source_url": rep.get("release_url"),
        "metrics": {},
        "prior": {},
        "verified": rep.get("type") != "web",
        "consensus": None,
        "consensus_source": None,
        "surprise": None,
        "read": None,
        "status": "pending_analysis",
    }
    rec.update(kw)
    return rec


# ---------- per-type collection ----------

def collect_series(domain, rep, now, rstate, seed):
    smap = fetch_series_map(rep, now)
    ref_d, metrics, prior = compute_series_report(rep, smap)
    ref = C.ref_period(ref_d, rep["freq"])
    last = rstate.get("last_ref")
    if last is not None and ref <= last:
        return None
    rec = _new_release(domain, rep, ref, now, metrics=metrics, prior=prior)
    if seed:
        rec["status"] = "baseline"
    return rec


def collect_decision(domain, rep, now, rstate, seed, cal_data):
    bank = rep["bank"]
    meetings = sorted((cal_data.get("cb_meetings") or {}).get(bank, []))
    today = now.date()
    h, mi = map(int, C.decision_time_et(bank, today).split(":"))
    grace = h + (mi + DECISION_GRACE_MIN) / 60
    held = [m for m in meetings
            if date.fromisoformat(m) < today
            or (date.fromisoformat(m) == today and now.hour + now.minute / 60 >= grace)]
    if not held:
        return None
    meeting = held[-1]
    last = rstate.get("last_ref")
    if last is not None and meeting <= last:
        return None
    md = date.fromisoformat(meeting)
    metrics, prior = {}, {}
    if rep["source"] == "fred":
        s = C.fred_csv(rep["rate_id"])
        after = _value_at(s, md + timedelta(days=1)) or _value_at(s, md)
        before = _value_at(s, md - timedelta(days=1))
        if after and after[0] < md:
            after = None  # series not updated past the meeting yet; retry next run
        if after is None:
            return None
        metrics["rate.level"] = after[1]
        if before:
            prior["rate.level"] = before[1]
            metrics["rate.change_bp"] = _r((after[1] - before[1]) * 100, 1)
        if rep.get("rate_lower_id"):
            lo = _value_at(C.fred_csv(rep["rate_lower_id"]), md + timedelta(days=1))
            if lo:
                metrics["rate_lower.level"] = lo[1]
    elif rep["source"] == "boe_page":
        rate = fetch_boe_rate()
        if rate is None:
            raise RuntimeError("BoE Bank Rate not found on page")
        metrics["rate.level"] = rate
        if rstate.get("last_rate") is not None:
            prior["rate.level"] = rstate["last_rate"]
            metrics["rate.change_bp"] = _r((rate - rstate["last_rate"]) * 100, 1)
        rstate["last_rate"] = rate
    rec = _new_release(domain, rep, meeting, now, metrics=metrics, prior=prior,
                       needs_fetch=rep.get("fields", []))
    if seed:
        rec["status"] = "baseline"
    return rec


def collect_web(domain, rep, now, rstate, seed):
    today = now.date()
    candidates = []
    for back in (1, 0):
        mstart = C.add_months(date(today.year, today.month, 1), -back)
        due = due_date(rep["due_rule"], mstart.year, mstart.month)
        if due <= today:
            ref_d = C.add_months(mstart, -rep.get("ref_lag_months", 1))
            candidates.append((due, C.ref_period(ref_d, "monthly")))
    if not candidates:
        return None
    due, ref = candidates[-1]
    last = rstate.get("last_ref")
    if last is not None and ref <= last:
        return None
    rec = _new_release(domain, rep, ref, now, due_date=due.isoformat(),
                       needs_fetch=rep.get("fields", []))
    if seed:
        rec["status"] = "baseline"
    return rec


CURVE_IDENTITIES = {"curve_10y2y": ("ust_10y", "ust_2y"), "curve_10y3m": ("ust_10y", "ust_3m")}


def snapshot_levels(rep, series, look, lagging_days):
    """One as-of date for every series. FRED posts H.15 yields a day after the
    spreads, curves and VIX; taking each series' own last value mixed two days.
    as_of = the latest date every current series has. A series more than
    `lagging_days` behind the freshest (e.g. the weekly-posted dollar index)
    keeps its own date and is marked lagging. The window is `look` business
    days as calendar weeks, so chg_5d is the same weekday a week earlier."""
    last = {k: s[-1][0] for k, s in series.items()}
    out = {"as_of": None, "series": {}, "issues": []}
    if not last:
        return out
    newest = max(last.values())
    current = [k for k, d in last.items() if (newest - d).days <= lagging_days]
    as_of = min(last[k] for k in current)
    points = set(rep.get("points_series", []))
    for key, s in series.items():
        lagging = key not in current
        cur = _value_at(s, last[key] if lagging else as_of)
        prev1 = _prev(s, cur[0]) or cur
        back = _value_at(s, cur[0] - timedelta(days=round(look * 7 / 5))) or s[0]
        mult = 1 if key in points else 100  # rates move in bp, indices in points
        out["series"][key] = {
            "id": rep["series"][key], "date": cur[0].isoformat(), "level": cur[1],
            "unit": "pts" if key in points else "bp",
            "chg_1d": _r((cur[1] - prev1[1]) * mult, 1),
            f"chg_{look}d": _r((cur[1] - back[1]) * mult, 1),
            f"level_{look}d_ago": back[1],
            "base_date": back[0].isoformat(),
        }
        if lagging:
            out["series"][key]["lagging"] = True
            out["issues"].append(f"{key} lags: last value {last[key].isoformat()}, snapshot as of {as_of.isoformat()}")
    out["as_of"] = as_of.isoformat()
    lv = {k: v["level"] for k, v in out["series"].items()}
    for curve, (long_, short) in CURVE_IDENTITIES.items():
        if all(k in lv for k in (curve, long_, short)) and abs(lv[long_] - lv[short] - lv[curve]) > 0.015:
            out["issues"].append(f"{curve} {lv[curve]:.2f} != {long_} - {short} = {lv[long_] - lv[short]:.2f}: mixed dates")
    return out


def collect_snapshot(domain, rep, now, rstate, seed, thr):
    mt = thr["markets"]
    look = mt["lookback_days"]
    fetched = {key: C.fred_csv(sid, years=1) for key, sid in rep["series"].items()}
    latest = snapshot_levels(rep, {k: s for k, s in fetched.items() if s}, look, mt.get("lagging_days", 4))
    latest["updated_at"] = C.fmt_et(now)
    C.save_json(MARKETS_LATEST, latest)

    signals = []
    for key, bp in mt["move_bp"].items():
        s = latest["series"].get(key)
        if s and abs(s[f"chg_{look}d"] or 0) >= bp:
            signals.append(f"{key} {s[f'chg_{look}d']:+.0f}{s['unit']} over {look}d (level {s['level']:.2f})")
    for key in mt.get("sign_change", []):
        s = latest["series"].get(key)
        if s and (s["level"] > 0) != (s[f"level_{look}d_ago"] > 0):
            signals.append(f"{key} crossed zero ({s[f'level_{look}d_ago']:+.2f} -> {s['level']:+.2f})")
    ref = latest["as_of"]
    fed_key = mt.get("fedwatch_trigger")
    fed_s = latest["series"].get(fed_key, {})
    fedwatch = abs(fed_s.get(f"chg_{look}d") or 0) >= mt["move_bp"].get(fed_key, 999)
    if not signals or seed:
        return None
    # one material-move release per week at most: dedup on ISO week
    week = C.iso_week(date.fromisoformat(ref))
    if rstate.get("last_ref") and rstate["last_ref"] >= week:
        return None
    metrics = {k: v["level"] for k, v in latest["series"].items()}
    return _new_release(domain, rep, week, now, metrics=metrics, signals=signals,
                        fedwatch_check_needed=fedwatch, as_of=ref)


# ---------- main loop ----------

def run(domain_filter=None, seed=False, dry_run=False, now=None):
    now = now or C.now_et()
    thr = C.thresholds()
    state = load_state()
    pending = load_pending()
    cal_data = C.load_json(CALENDAR, {})
    summary = {"run_at": C.fmt_et(now), "new": [], "errors": [], "seed": seed}

    for domain in C.domains_config():
        if domain_filter and domain["id"] != domain_filter:
            continue
        dstate = state["collectors"].setdefault(domain["id"], {})
        dstate["last_run"] = C.fmt_et(now)
        domain_ok = True
        for rep in domain["reports"]:
            rstate = state["reports"].setdefault(rep["id"], {})
            try:
                t = rep["type"]
                if t == "series":
                    rec = collect_series(domain, rep, now, rstate, seed)
                elif t == "decision":
                    rec = collect_decision(domain, rep, now, rstate, seed, cal_data)
                elif t == "web":
                    rec = collect_web(domain, rep, now, rstate, seed)
                elif t == "snapshot":
                    rec = collect_snapshot(domain, rep, now, rstate, seed, thr)
                else:
                    raise ValueError(f"unknown type {t}")
                rstate["last_checked"] = C.fmt_et(now)
                rstate.pop("error", None)
                if rec is None:
                    continue
                path = release_path(domain["id"], rep["id"], rec["ref"])
                if not dry_run:
                    # a seeded web report has no figures yet: keep only the dedup baseline
                    if not path.exists() and not (seed and t == "web"):
                        C.save_json(path, rec)
                    rstate["last_ref"] = rec["ref"]
                    if not seed:
                        _queue(pending, {
                            "domain": domain["id"], "report": rep["id"], "ref": rec["ref"],
                            "path": str(path.relative_to(C.ROOT)),
                            "needs_fetch": bool(rec.get("needs_fetch")),
                            "tier": rec["tier"], "detected_at": rec["detected_at"],
                        })
                summary["new"].append({"report": rep["id"], "ref": rec["ref"], "status": rec["status"]})
            except Exception as e:  # one broken source never stops the run
                domain_ok = False
                rstate["error"] = f"{type(e).__name__}: {e}"[:300]
                summary["errors"].append({"report": rep["id"], "error": rstate["error"]})
        if domain_ok:
            dstate["last_success"] = C.fmt_et(now)
            dstate.pop("error", None)
        else:
            dstate["error"] = "one or more reports failed; see reports[*].error"

    if not dry_run:
        C.save_json(STATE, state)
        C.save_json(PENDING, pending)
    summary["pending_total"] = len(pending["items"])
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--domain")
    ap.add_argument("--seed", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    summary = run(a.domain, a.seed, a.dry_run, C.now_et(a.now) if a.now else None)
    print(json.dumps(summary, indent=2))
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a") as fh:
            fh.write(f"new_count={len([n for n in summary['new'] if n['status'] != 'baseline'])}\n")
            fh.write(f"pending_total={summary['pending_total']}\n")
            fh.write(f"error_count={len(summary['errors'])}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
