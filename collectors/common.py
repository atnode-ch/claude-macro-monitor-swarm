"""Shared plumbing for collectors and tools. Stdlib only, so the GitHub Action
and a Claude routine can both run it without installing anything."""
import csv
import io
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = None

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
DATA = ROOT / "data"
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


# ---------- files ----------

def load_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    tmp.replace(p)


def domains_config():
    return load_json(CONFIG / "domains.json")["domains"]


def thresholds():
    return load_json(CONFIG / "thresholds.json")


def deployment():
    """config/deployment.json, falling back to the example so tests and a fresh
    clone still run."""
    return load_json(CONFIG / "deployment.json") or load_json(CONFIG / "deployment.example.json")


def report_index():
    """{report_id: (domain_cfg, report_cfg)}"""
    out = {}
    for d in domains_config():
        for r in d["reports"]:
            out[r["id"]] = (d, r)
    return out


# ---------- time ----------

def now_et(override=None):
    if override:
        dt = datetime.strptime(override, "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=ET) if ET else dt
    return datetime.now(ET) if ET else datetime.now()


def fmt_et(dt):
    return dt.strftime("%Y-%m-%d %H:%M ET")


def parse_et(s):
    if not s:
        return None
    dt = datetime.strptime(s.replace(" ET", ""), "%Y-%m-%d %H:%M")
    return dt.replace(tzinfo=ET) if ET else dt


def iso_week(d):
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ---------- http ----------

def http_get(url, timeout=40, retries=3, data=None, headers=None, browser_ua=True):
    """GET (or POST when data is given). urllib honours HTTPS_PROXY.
    browser_ua=False keeps Python's default User-Agent: FRED's CDN stalls
    requests that claim to be a browser but don't behave like one."""
    hdrs = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"} if browser_ua else {}
    hdrs.update(headers or {})
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def fred_csv(series_id, text=None, years=4):
    """[(date, float)] ascending, from FRED's keyless CSV endpoint (last
    `years` years). Missing values ('.' or blank) are skipped."""
    if text is None:
        start = date(date.today().year - years, 1, 1).isoformat()
        text = http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}",
                        timeout=30, browser_ua=False)
    if text.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
        # FRED serves its maintenance page as HTTP 200 HTML
        raise RuntimeError(f"FRED returned HTML, not CSV, for {series_id} (site maintenance?)")
    rows = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)
    for rec in reader:
        if len(rec) < 2:
            continue
        try:
            rows.append((date.fromisoformat(rec[0]), float(rec[1])))
        except ValueError:
            continue
    return rows


def bls_series(series_ids, start_year, end_year, payload_override=None):
    """{series_id: [(date, float)] ascending} from the BLS public API v2."""
    payload = {"seriesid": list(series_ids), "startyear": str(start_year), "endyear": str(end_year)}
    key = os.environ.get("BLS_API_KEY")
    if key:
        payload["registrationkey"] = key
    if payload_override is not None:
        data = payload_override
    else:
        body = http_get("https://api.bls.gov/publicAPI/v2/timeseries/data/",
                        data=json.dumps(payload).encode(),
                        headers={"Content-Type": "application/json"}, browser_ua=False)
        data = json.loads(body)
    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS error: {data.get('message')}")
    out = {}
    for s in data["Results"]["series"]:
        pts = []
        for d in s["data"]:
            per = d.get("period", "")
            if not per.startswith("M") or per == "M13":
                continue
            val = (d.get("value") or "").replace(",", "").strip()
            try:
                pts.append((date(int(d["year"]), int(per[1:]), 1), float(val)))
            except ValueError:
                continue
        out[s["seriesID"]] = sorted(pts)
    return out


# ---------- periods ----------

def ref_period(d, freq):
    if freq == "monthly":
        return f"{d.year:04d}-{d.month:02d}"
    if freq == "quarterly":
        return f"{d.year:04d}-Q{(d.month - 1) // 3 + 1}"
    return d.isoformat()


def add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def business_days_in_month(y, m):
    d = date(y, m, 1)
    out = []
    while d.month == m:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out
