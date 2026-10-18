"""Offline tests: no network. Run: python -m unittest discover -s tests -v"""
import json
import shutil
import tempfile
import unittest
from datetime import date
from pathlib import Path

from collectors import common as C
from collectors import engine as E
from collectors import calendar as CAL


def monthly(start_y, start_m, values):
    out, d = [], date(start_y, start_m, 1)
    for v in values:
        out.append((d, v))
        d = C.add_months(d, 1)
    return out


class TempData(unittest.TestCase):
    """Point collectors.common.DATA (and modules that captured paths) at a temp dir."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = C.DATA
        C.DATA = self.tmp
        import tools.pending as P
        import tools.synthesis as S
        self._saved = (E.STATE, E.PENDING, E.MARKETS_LATEST, E.CALENDAR, P.PENDING, P.OUTBOX, S.SYN_DIR)
        E.STATE, E.PENDING = self.tmp / "state.json", self.tmp / "pending.json"
        E.MARKETS_LATEST, E.CALENDAR = self.tmp / "markets_latest.json", self.tmp / "calendar.json"
        P.PENDING, P.OUTBOX = self.tmp / "pending.json", self.tmp / "outbox.json"
        S.SYN_DIR = self.tmp / "synthesis"

    def tearDown(self):
        import tools.pending as P
        import tools.synthesis as S
        C.DATA = self._orig
        (E.STATE, E.PENDING, E.MARKETS_LATEST, E.CALENDAR, P.PENDING, P.OUTBOX, S.SYN_DIR) = self._saved
        shutil.rmtree(self.tmp)


class MetricTests(unittest.TestCase):
    def test_mom_yoy_and_prior(self):
        sa = monthly(2025, 1, [100 + i for i in range(20)])  # through 2026-08
        rep = {"freq": "monthly", "parts": {"headline": {"id": "SA", "yoy_id": "NSA", "transforms": ["chg_pct", "yoy_pct"]}}}
        ref, m, prior = E.compute_series_report(rep, {"SA": sa, "NSA": sa})
        self.assertEqual(ref, date(2026, 8, 1))
        self.assertAlmostEqual(m["headline.chg_pct"], round((119 / 118 - 1) * 100, 3))
        self.assertAlmostEqual(m["headline.yoy_pct"], round((119 / 107 - 1) * 100, 3))
        self.assertAlmostEqual(prior["headline.chg_pct"], round((118 / 117 - 1) * 100, 3))

    def test_diff_with_scale(self):
        s = monthly(2026, 1, [1000, 1100, 1250])
        rep = {"freq": "monthly", "parts": {"p_k": {"id": "X", "scale": 0.001, "transforms": ["diff", "level"]}}}
        _, m, _ = E.compute_series_report(rep, {"X": s})
        self.assertAlmostEqual(m["p_k.diff"], 0.15)
        self.assertAlmostEqual(m["p_k.level"], 1.25)

    def test_ref_period(self):
        self.assertEqual(C.ref_period(date(2026, 4, 1), "quarterly"), "2026-Q2")
        self.assertEqual(C.ref_period(date(2026, 4, 1), "monthly"), "2026-04")


class ConfigTests(unittest.TestCase):
    def test_ppi_uses_final_demand(self):
        _, ppi = C.report_index()["ppi"]
        ids = {p["id"] for p in ppi["parts"].values()} | {p.get("yoy_id") for p in ppi["parts"].values()}
        self.assertNotIn("WPSFD49207", ids)  # Finished Goods, the Hyperagent bug
        self.assertIn("PPIFIS", ids)          # = BLS WPSFD4, Final Demand SA

    def test_every_report_has_threshold_or_is_exempt(self):
        thr = C.thresholds()["surprise"]
        for rid, (_, rep) in C.report_index().items():
            if rep["type"] in ("series", "web") and rid not in ("nfci", "sloos", "carts"):
                self.assertIn(rid, thr, rid)

    def test_no_account_ids_outside_deployment(self):
        root = C.ROOT
        offenders = []
        for p in list((root / "collectors").glob("*.py")) + list((root / "tools").glob("*.py")) + \
                list((root / ".claude").rglob("*.md")) + [root / "CLAUDE.md"]:
            if p.exists() and ("C0B8B76L7NH" in p.read_text() or "atnode-ai" in p.read_text()):
                offenders.append(str(p))
        self.assertEqual(offenders, [])


class DueRuleTests(unittest.TestCase):
    def test_rules(self):
        self.assertEqual(E.due_date({"rule": "nth_business_day", "n": 1}, 2026, 11), date(2026, 11, 2))
        self.assertEqual(E.due_date({"rule": "nth_business_day", "n": 3}, 2026, 10), date(2026, 10, 5))
        self.assertEqual(E.due_date({"rule": "last_weekday", "weekday": 1}, 2026, 10), date(2026, 10, 27))
        self.assertEqual(E.due_date({"rule": "nth_weekday", "weekday": 4, "n": 1}, 2026, 11), date(2026, 11, 6))
        self.assertEqual(E.due_date({"rule": "day_of_month", "day": 24}, 2026, 10), date(2026, 10, 26))  # Sat -> Mon


class CalendarParseTests(unittest.TestCase):
    def test_fomc(self):
        h = ('<h4><a id="1">2026 FOMC Meetings</a></h4>'
             '<div class="fomc-meeting__month col"><strong>January</strong></div><div class="fomc-meeting__date col">27-28</div>'
             '<div class="fomc-meeting__month col"><strong>September</strong></div><div class="fomc-meeting__date col">15-16*</div>'
             '<div class="fomc-meeting__month col"><strong>Apr/May</strong></div><div class="fomc-meeting__date col">30-1</div>')
        self.assertEqual(CAL.parse_fomc(h), ["2026-01-28", "2026-05-01", "2026-09-16"])

    def test_boe(self):
        t = "2026 confirmed dates Thursday 5 November November MPC Thursday&nbsp;17 December December MPC 2027 confirmed dates Thursday 4 February"
        self.assertEqual(CAL.parse_boe(t), ["2026-11-05", "2026-12-17", "2027-02-04"])

    def test_ecb(self):
        h = "29/10/2026 Governing Council of the ECB: monetary policy meeting in Frankfurt (Day 2), followed by press conference"
        self.assertEqual(CAL.parse_ecb(h), ["2026-10-29"])


class PipelineTests(TempData):
    def _series_report(self, seed, now, data):
        dom, rep = C.report_index()["cpi"]
        orig = E.fetch_series_map
        E.fetch_series_map = lambda r, n: data
        try:
            rstate = {}
            if not seed:
                rstate["last_ref"] = "2026-07"
            return E.collect_series(dom, rep, now, rstate, seed)
        finally:
            E.fetch_series_map = orig

    def test_series_dedup(self):
        s = monthly(2025, 1, [100 + i * 0.3 for i in range(20)])
        data = {"CPIAUCSL": s, "CPIAUCNS": s, "CPILFESL": s, "CPILFENS": s}
        now = C.now_et("2026-09-11 09:00")
        rec = self._series_report(False, now, data)
        self.assertEqual(rec["ref"], "2026-08")
        dom, rep = C.report_index()["cpi"]
        orig = E.fetch_series_map
        E.fetch_series_map = lambda r, n: data
        try:
            self.assertIsNone(E.collect_series(dom, rep, now, {"last_ref": "2026-08"}, False))
        finally:
            E.fetch_series_map = orig

    def test_apply_validates_and_computes_surprise(self):
        import tools.pending as P
        rec = {"domain": "inflation", "report": "cpi", "name": "CPI", "ref": "2026-09", "tier": 1,
               "metrics": {"core.chg_pct": 0.4, "headline.chg_pct": 0.3}, "status": "pending_analysis"}
        path = self.tmp / "releases/inflation/cpi/2026-09.json"
        C.save_json(path, rec)
        rel = Path("data") / "releases/inflation/cpi/2026-09.json"
        C.save_json(P.PENDING, {"items": [{"domain": "inflation", "report": "cpi", "ref": "2026-09",
                                           "path": str(rel), "needs_fetch": False, "tier": 1}]})
        orig_root = C.ROOT
        C.ROOT = self.tmp.parent / "_root"
        (C.ROOT).mkdir(exist_ok=True)
        try:
            (C.ROOT / "data").symlink_to(self.tmp, target_is_directory=True) if not (C.ROOT / "data").exists() else None
            bad = self.tmp / "inbox/bad.json"
            C.save_json(bad, {"report": "cpi", "ref": "2026-09", "consensus": {"core.chg_pct": "0.3"}, "read": "x"})
            self.assertEqual(P.cmd_apply(bad), 1)
            good = self.tmp / "inbox/good.json"
            C.save_json(good, {"report": "cpi", "ref": "2026-09", "consensus": {"core.chg_pct": 0.3},
                               "consensus_source": "test", "read": "Hot core.", "stance": "Re-accelerating."})
            self.assertEqual(P.cmd_apply(good), 0)
            out = C.load_json(path)
            self.assertAlmostEqual(out["surprise"]["core.chg_pct"], 0.1)
            self.assertTrue(out["alert"]["alert"])
            self.assertEqual(C.load_json(P.PENDING)["items"], [])
            self.assertEqual(C.load_json(self.tmp / "stances/inflation.json")["stance"], "Re-accelerating.")
        finally:
            shutil.rmtree(C.ROOT)
            C.ROOT = orig_root


class AlertGateTests(unittest.TestCase):
    def test_threshold(self):
        from tools.alert_gate import evaluate
        r = evaluate({"report": "retail", "tier": 2, "metrics": {"headline.chg_pct": 1.0},
                      "consensus": {"headline.chg_pct": 0.3}})
        self.assertTrue(r["material"] and r["alert"])
        r = evaluate({"report": "retail", "tier": 2, "metrics": {"headline.chg_pct": 0.4},
                      "consensus": {"headline.chg_pct": 0.3}})
        self.assertFalse(r["alert"])

    def test_rate_change_alerts(self):
        from tools.alert_gate import evaluate
        r = evaluate({"report": "ecb", "tier": 2, "metrics": {"rate.level": 2.25, "rate.change_bp": -25}})
        self.assertTrue(r["alert"])


class AuditTests(TempData):
    def test_weekday_and_weekend(self):
        from tools.synthesis import audit
        draft = {"executive_summary": "Jackson Hole on Sat 21 Aug, CPI on Tue 13 Oct.", "narrative": [],
                 "week_ahead": [], "kpis": [], "regime_watch": "", "slack_summary": ""}
        issues = audit(draft, C.now_et("2026-10-09 17:00"))["issues"]
        texts = [i["problem"] for i in issues if i["type"] == "date"]
        self.assertTrue(any("is a Fri" in t for t in texts))     # 21 Aug 2026 is a Friday
        self.assertFalse(any("Tue 13 Oct" in i["text"] for i in issues if i["type"] == "date"))


class PublishPagesTests(unittest.TestCase):
    def test_mirror_into_slug_only(self):
        import subprocess
        from tools import publish_pages
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        src, repo = tmp / "site", tmp / "pages"
        (src / "reports").mkdir(parents=True)
        (src / "index.html").write_text("new")
        (src / "reports" / "w.html").write_text("r")
        g = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                      check=True, capture_output=True)
        repo.mkdir()
        g("init", "-q")
        slug = publish_pages.cfg()["slug"]
        (repo / "docs" / slug).mkdir(parents=True)
        (repo / "docs" / "CNAME").write_text("x")
        (repo / "docs" / slug / "stale.html").write_text("old")
        g("add", "-A"); g("commit", "-qm", "init")
        orig = publish_pages.git
        publish_pages.git = lambda r, *a, check=True: orig(r, "-c", "user.name=t", "-c", "user.email=t@t", *a, check=check)
        self.addCleanup(setattr, publish_pages, "git", orig)
        r = publish_pages.publish(pages_dir=repo, src=src)
        self.assertTrue(r["committed"])
        self.assertFalse((repo / "docs" / slug / "stale.html").exists())
        self.assertEqual((repo / "docs" / slug / "reports" / "w.html").read_text(), "r")
        self.assertTrue((repo / "docs" / "CNAME").exists())
        self.assertFalse(publish_pages.publish(pages_dir=repo, src=src)["committed"])


if __name__ == "__main__":
    unittest.main()
