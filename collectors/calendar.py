"""Release calendar -> data/calendar.json.

Sources, best first:
  - Fed FOMC calendar page, ECB Governing Council calendar, BoE MPC dates page (official, scraped)
  - BEA iCal feed (official: GDP, Personal Income & Outlays/PCE, Trade)
  - FRED API releases/dates when FRED_API_KEY is set (official, all US releases)
  - cadence rules for the rest, flagged "estimate"

The Friday strategist writes its Week-ahead line from this file, never from
memory, and tools/audit.py checks every date in the synthesis against it.

    python -m collectors.calendar [--now "YYYY-MM-DD HH:MM"]
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

from collectors import common as C
from collectors.engine import due_date

CALENDAR = C.DATA / "calendar.json"
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def parse_fomc(html):
    """Decision dates (day 2 of each meeting) from federalreserve.gov."""
    out = []
    for ym in re.finditer(r'<h4><a id="\d+">(\d{4}) FOMC Meetings', html):
        year = int(ym.group(1))
        end = html.find("<h4>", ym.end())
        block = html[ym.end(): end if end > 0 else len(html)]
        months = re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>", block)
        days = re.findall(r"fomc-meeting__date[^>]*>\s*([0-9]{1,2}(?:-[0-9]{1,2})?)\*?", block)
        for mon, dy in zip(months, days):
            mon_last = mon.split("/")[-1].strip().lower()
            mon_first = mon.split("/")[0].strip().lower()
            if mon_last not in MONTHS:
                continue
            last_day = int(dy.split("-")[-1])
            # "Apr/May 30-1": day 2 falls in the second month
            month = MONTHS[mon_last] if ("/" in mon and last_day < int(dy.split("-")[0])) else MONTHS.get(mon_first, MONTHS[mon_last])
            try:
                out.append(date(year, month, last_day).isoformat())
            except ValueError:
                continue
    return sorted(set(out))


def parse_ecb(html):
    t = _text(html)
    out = re.findall(r"(\d{2})/(\d{2})/(\d{4}) Governing Council of the ECB: monetary policy meeting[^()]*\(Day 2\)", t)
    return sorted({date(int(y), int(m), int(d)).isoformat() for d, m, y in out})


def parse_boe(html):
    t = _text(html).replace("\xa0", " ").replace("&nbsp;", " ")
    out = []
    for block in re.finditer(r"(\d{4}) confirmed dates(.*?)(?=\d{4} confirmed dates|$)", t):
        year = int(block.group(1))
        for d, mon in re.findall(r"Thursday\s+(\d{1,2})\s+([A-Z][a-z]+)", block.group(2)):
            if mon.lower() in MONTHS:
                out.append(date(year, MONTHS[mon.lower()], int(d)).isoformat())
    return sorted(set(out))


def parse_ics(text):
    """[(date, summary)] from an iCal feed; DTSTART in UTC -> ET date."""
    events, cur = [], {}
    lines = text.replace("\r\n ", "").replace("\n ", "").splitlines()
    for ln in lines:
        if ln.startswith("BEGIN:VEVENT"):
            cur = {}
        elif ln.startswith("DTSTART"):
            cur["dt"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("SUMMARY"):
            cur["summary"] = ln.split(":", 1)[1].replace("\\,", ",").strip()
        elif ln.startswith("END:VEVENT") and "dt" in cur:
            raw = cur["dt"]
            try:
                if raw.endswith("Z"):
                    dt = datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=__import__("datetime").timezone.utc)
                    dt = dt.astimezone(C.ET) if C.ET else dt
                    events.append((dt.date(), dt.strftime("%H:%M"), cur.get("summary", "")))
                else:
                    events.append((datetime.strptime(raw[:8], "%Y%m%d").date(), None, cur.get("summary", "")))
            except ValueError:
                pass
    return events


def fred_api_dates(start, end):
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return []
    url = (f"https://api.stlouisfed.org/fred/releases/dates?api_key={key}&file_type=json"
           f"&realtime_start={start}&realtime_end={end}&include_release_dates_with_no_data=true&limit=1000")
    data = json.loads(C.http_get(url))
    return [(date.fromisoformat(r["date"]), None, r["release_name"]) for r in data.get("release_dates", [])]


def match_report(summary, reports):
    s = summary.lower()
    for rid, rep in reports.items():
        key = rep.get("calendar_match")
        if key and key.lower() in s:
            return rid
    return None


# Cadence rules (ET) for reports without an official machine-readable calendar.
# Source: the Hyperagent release-calendar memory; treat as estimates.
CADENCE = {
    "nfp": ({"rule": "nth_weekday", "weekday": 4, "n": 1}, "08:30"),
    "cpi": ({"rule": "day_of_month", "day": 12}, "08:30"),
    "ppi": ({"rule": "day_of_month", "day": 13}, "08:30"),
    "retail": ({"rule": "day_of_month", "day": 16}, "08:30"),
    "indpro": ({"rule": "day_of_month", "day": 16}, "09:15"),
    "starts": ({"rule": "day_of_month", "day": 17}, "08:30"),
    "existing_home": ({"rule": "day_of_month", "day": 21}, "10:00"),
    "new_home": ({"rule": "day_of_month", "day": 24}, "10:00"),
    "durables": ({"rule": "day_of_month", "day": 26}, "08:30"),
    "jolts": ({"rule": "nth_business_day", "n": 5}, "10:00"),
    "umich": ({"rule": "nth_weekday", "weekday": 4, "n": 4}, "10:00"),  # final, not the preliminary
}


def build(now):
    reports = {rid: rep for rid, (_, rep) in C.report_index().items()}
    today = now.date()
    horizon = today + timedelta(days=45)
    errors, events = [], []
    cb = {}

    for bank, url, parser in (
        ("fed", "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", parse_fomc),
        ("ecb", "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html", parse_ecb),
        ("boe", "https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates", parse_boe),
    ):
        try:
            cb[bank] = parser(C.http_get(url))
            if not cb[bank]:
                raise RuntimeError("parsed zero dates")
        except Exception as e:
            errors.append(f"{bank}: {e}")
    # keep previously known meeting dates (the ECB page only lists upcoming meetings)
    old = C.load_json(CALENDAR, {}) or {}
    for bank, dates in (old.get("cb_meetings") or {}).items():
        cb[bank] = sorted(set(cb.get(bank, [])) | set(dates))

    rid_for_bank = {"fed": "fomc", "ecb": "ecb", "boe": "boe"}
    for bank, dates in cb.items():
        for d in dates:
            dd = date.fromisoformat(d)
            if today - timedelta(days=7) <= dd <= horizon:
                events.append({"date": d, "time_et": C.decision_time_et(bank, dd),
                               "report": rid_for_bank[bank], "name": reports[rid_for_bank[bank]]["name"],
                               "source": "official"})

    official = []
    try:
        official += parse_ics(C.http_get("https://www.bea.gov/news/schedule/ics/online-calendar-subscription.ics"))
    except Exception as e:
        errors.append(f"bea: {e}")
    try:
        official += fred_api_dates(today - timedelta(days=7), horizon)
    except Exception as e:
        errors.append(f"fred_api: {e}")
    covered = set()
    for d, t, summary in official:
        if not (today - timedelta(days=7) <= d <= horizon):
            continue
        rid = match_report(summary, reports)
        if not rid:
            continue
        key = (rid, d.isoformat())
        if key in covered:
            continue
        covered.add(key)
        events.append({"date": d.isoformat(), "time_et": t, "report": rid, "name": reports[rid]["name"],
                       "source": "official", "summary": summary})
    covered_reports_month = {(e["report"], e["date"][:7]) for e in events}

    # cadence estimates and web-report due dates for this month and next
    for mo in (0, 1):
        m0 = C.add_months(date(today.year, today.month, 1), mo)
        for rid, (rule, t) in CADENCE.items():
            if (rid, m0.isoformat()[:7]) in covered_reports_month:
                continue
            d = due_date(rule, m0.year, m0.month)
            events.append({"date": d.isoformat(), "time_et": t, "report": rid, "name": reports[rid]["name"],
                           "source": "estimate"})
        for rid, rep in reports.items():
            if rep.get("type") == "web" and rep.get("due_rule"):
                d = due_date(rep["due_rule"], m0.year, m0.month)
                events.append({"date": d.isoformat(), "time_et": None, "report": rid, "name": rep["name"],
                               "source": "estimate"})
    # weekly claims: every Thursday
    d = today - timedelta(days=7)
    while d <= horizon:
        if d.weekday() == 3:
            events.append({"date": d.isoformat(), "time_et": "08:30", "report": "claims",
                           "name": reports["claims"]["name"], "source": "estimate"})
        d += timedelta(days=1)

    events = [e for e in events if today - timedelta(days=7) <= date.fromisoformat(e["date"]) <= horizon]
    events.sort(key=lambda e: (e["date"], e["time_et"] or "99:99", e["report"]))
    for e in events:
        e["weekday"] = date.fromisoformat(e["date"]).strftime("%a")
    return {"generated_at": C.fmt_et(now), "cb_meetings": cb, "events": events, "errors": errors}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--now")
    a = ap.parse_args(argv)
    out = build(C.now_et(a.now))
    C.save_json(CALENDAR, out)
    print(json.dumps({"events": len(out["events"]), "cb_meetings": {k: len(v) for k, v in out["cb_meetings"].items()},
                      "errors": out["errors"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
