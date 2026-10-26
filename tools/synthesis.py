"""Strategist I/O: compact digest in, validated synthesis out.

    python -m tools.synthesis digest [--now ...]       # < 15 KB JSON for the strategist
    python -m tools.synthesis finalize <draft.json>    # resolve KPIs + week-ahead from data,
                                                       # add swarm health, audit, save
    python -m tools.synthesis audit <draft.json>       # audit only (no save)

The strategist writes prose and picks which figures matter. Code supplies the
figures (KPI tiles, week-ahead dates and weekdays, health), so the published
numbers always equal the logged numbers.
"""
import json
import re
import sys
from datetime import date, timedelta

from collectors import common as C
from tools import store

SYN_DIR = C.DATA / "synthesis"
DRAFT_KEYS = ("regime", "executive_summary", "narrative", "domain_scorecard", "regime_watch",
              "week_ahead", "kpis", "slack_summary")


def _week_bounds(now):
    monday = now.date() - timedelta(days=now.weekday())
    return monday, monday + timedelta(days=4)


def digest(now=None):
    now = now or C.now_et()
    mon, fri = _week_bounds(now)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday() + 3)  # incl. last Fri pm
    domains = []
    for dom in C.domains_config():
        latest = store.latest_per_report(dom["id"])
        idx = {r["id"]: r for r in dom["reports"]}
        domains.append({
            "domain": dom["id"],
            "name": dom["name"],
            "stance": store.stance(dom["id"]).get("stance"),
            "stance_updated": store.stance(dom["id"]).get("updated_at"),
            "latest": [{
                "report": r["report"], "ref": r["ref"],
                "metrics": r.get("metrics"),
                "consensus": r.get("consensus"), "surprise": r.get("surprise"),
                "read": r.get("read"), "status": r.get("status"),
                "freq": idx[r["report"]].get("freq"),
            } for r in latest.values()],
        })
    fresh = [{"domain": r["domain"], "report": r["report"], "ref": r["ref"], "detected_at": r["detected_at"],
              "alert": (r.get("alert") or {}).get("alert")}
             for r in store.detected_between(start, now)]
    cal = C.load_json(C.DATA / "calendar.json", {"events": []})
    next_mon = mon + timedelta(days=7)
    ahead = [e for e in cal["events"] if next_mon.isoformat() <= e["date"] <= (next_mon + timedelta(days=4)).isoformat()]
    prior_files = sorted(SYN_DIR.glob("*.json"))
    prior = C.load_json(prior_files[-1]) if prior_files else None
    m = C.load_json(C.DATA / "markets_latest.json", {})
    pend = C.load_json(C.DATA / "pending.json", {"items": []})["items"]
    return {
        "generated_at": C.fmt_et(now),
        "week": C.iso_week(now.date()),
        "week_ending": fri.isoformat(),
        "health": _compact_health(store.health(now)),
        "fresh_this_week": fresh,
        "unanalysed_pending": [{"report": p["report"], "ref": p["ref"]} for p in pend],
        "domains": domains,
        "markets_as_of": m.get("as_of"),
        "markets_window": "chg_5d = change vs the same weekday one week before markets_as_of",
        "markets_issues": m.get("issues") or [],
        "markets": {k: {"level": v["level"], "date": v.get("date"), "chg_5d": next((x for kk, x in v.items() if kk.startswith("chg_") and kk != "chg_1d"), None),
                        "unit": v.get("unit")} for k, v in (m.get("series") or {}).items()},
        "next_week_calendar": ahead,
        "prior_synthesis": None if not prior else {k: prior.get(k) for k in ("week", "regime", "regime_watch")},
        "kpi_refs_help": "kpis[].ref = '<domain>/<report>/<ref>:<metric_key>' or 'markets:<series>'",
    }


def _compact_health(h):
    return {"all_ok": h["all_ok"], "alert_text": h["alert_text"],
            "problems": [d for d in h["domains"] if d["stale"] or d["errors"]]}


def resolve_ref(ref):
    """'inflation/pce/2026-08:core.yoy_pct' -> value; 'markets:hy_oas' -> level."""
    if ref.startswith("markets:"):
        m = C.load_json(C.DATA / "markets_latest.json", {})
        s = (m.get("series") or {}).get(ref.split(":", 1)[1])
        return None if s is None else s["level"]
    path, _, key = ref.partition(":")
    rec = C.load_json(C.DATA / "releases" / f"{path}.json")
    if rec is None:
        return None
    return (rec.get("metrics") or {}).get(key)


DATE_RE = re.compile(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\b"
                     r"|\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\.?,?\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2})\b")
MON = {m: i for i, m in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
NUM_RE = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?=\s?(?:%|pp|bp|k\b))")


def _known_numbers():
    vals = set()
    for rec in store.releases():
        for blob in (rec.get("metrics"), rec.get("prior"), rec.get("consensus"), rec.get("surprise")):
            for v in (blob or {}).values():
                if isinstance(v, (int, float)):
                    for nd in (0, 1, 2):
                        vals.add(round(abs(v), nd))
    m = C.load_json(C.DATA / "markets_latest.json", {})
    for s in (m.get("series") or {}).values():
        for k, v in s.items():
            if isinstance(v, (int, float)):
                for nd in (0, 1, 2):
                    vals.add(round(abs(v), nd))
    return vals


def audit(draft, now=None):
    """Deterministic checks. Returns {issues: [...], checks: {...}}."""
    now = now or C.now_et()
    issues = []
    text_fields = [draft.get("executive_summary", ""), draft.get("regime_watch", ""), draft.get("slack_summary", "")]
    text_fields += [p.get("body", "") for p in draft.get("narrative", [])]
    text_fields += [e.get("why", "") for e in draft.get("week_ahead", [])]
    blob = "\n".join(text_fields)
    # 1. weekday/date consistency for any "Fri 13 Nov" / "Friday, Nov 13" mention
    for m in DATE_RE.finditer(blob):
        wd = (m.group(1) or m.group(4))[:3]
        day = int(m.group(2) or m.group(6))
        mon = MON[(m.group(3) or m.group(5))[:3]]
        year = now.year + (1 if mon < now.month - 6 else 0)
        try:
            real = date(year, mon, day).strftime("%a")
        except ValueError:
            issues.append({"type": "date", "text": m.group(0), "problem": "invalid date"})
            continue
        if real != wd:
            issues.append({"type": "date", "text": m.group(0), "problem": f"{day} {(m.group(3) or m.group(5))[:3]} {year} is a {real}"})
        if real in ("Sat", "Sun"):
            issues.append({"type": "date", "text": m.group(0), "problem": "weekend date for a release/meeting"})
    # 2. week-ahead items must exist in the calendar
    cal = C.load_json(C.DATA / "calendar.json", {"events": []})
    cal_reports = {e["report"] for e in cal["events"]}
    for e in draft.get("week_ahead", []):
        if e.get("report") not in cal_reports:
            issues.append({"type": "week_ahead", "text": e.get("report"), "problem": "not in data/calendar.json"})
    # 3. numbers quoted with %, pp, bp or k must match a logged value
    known = _known_numbers()
    unknown = []
    for m in NUM_RE.finditer(blob):
        v = abs(float(m.group(0)))
        if v not in known and round(v, 1) not in known and round(v) not in known:
            unknown.append(m.group(0))
    if unknown:
        issues.append({"type": "figure", "text": ", ".join(sorted(set(unknown))[:20]),
                       "problem": "figures not found in data/ (check or remove)"})
    # 4. KPI refs resolve
    for k in draft.get("kpis", []):
        if resolve_ref(k.get("ref", "")) is None:
            issues.append({"type": "kpi", "text": k.get("ref"), "problem": "ref does not resolve"})
    missing = [k for k in DRAFT_KEYS if k not in draft]
    if missing:
        issues.append({"type": "schema", "text": ", ".join(missing), "problem": "missing draft keys"})
    return {"issues": issues, "ok": not issues, "checked_at": C.fmt_et(now)}


def finalize(draft, now=None):
    now = now or C.now_et()
    rep = audit(draft, now)
    cal = {e["report"]: e for e in reversed(C.load_json(C.DATA / "calendar.json", {"events": []})["events"])
           if e["date"] >= now.date().isoformat()}
    names = {rid: r["name"] for rid, (_, r) in C.report_index().items()}
    wa = []
    for e in draft.get("week_ahead", []):
        ev = cal.get(e.get("report"))
        wa.append({"report": e.get("report"), "name": names.get(e.get("report"), e.get("report")),
                   "date": ev["date"] if ev else None, "weekday": ev["weekday"] if ev else None,
                   "time_et": ev.get("time_et") if ev else None,
                   "date_source": ev["source"] if ev else "unknown", "why": e.get("why", "")})
    wa.sort(key=lambda x: (x["date"] or "9999", x["time_et"] or ""))
    kpis = [{"label": k["label"], "ref": k["ref"], "value": resolve_ref(k["ref"]), "unit": k.get("unit", "")}
            for k in draft.get("kpis", [])]
    h = store.health(now)
    health_line = "all domains fresh" if h["all_ok"] else h["alert_text"]
    out = dict(draft)
    _, fri = _week_bounds(now)
    out.update({"week": C.iso_week(now.date()), "week_ending": fri.isoformat(), "week_ahead": wa, "kpis": kpis,
                "swarm_health": health_line, "health": h, "audit": rep, "finalized_at": C.fmt_et(now)})
    C.save_json(SYN_DIR / f"{out['week']}.json", out)
    return out


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    now = None
    if "--now" in argv:
        now = C.now_et(argv[argv.index("--now") + 1])
    if argv[0] == "digest":
        print(json.dumps(digest(now), indent=1, ensure_ascii=False))
    elif argv[0] == "audit":
        print(json.dumps(audit(C.load_json(argv[1]), now), indent=2))
    elif argv[0] == "finalize":
        out = finalize(C.load_json(argv[1]), now)
        print(json.dumps({"saved": f"data/synthesis/{out['week']}.json", "audit": out["audit"],
                          "swarm_health": out["swarm_health"]}, indent=2))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
