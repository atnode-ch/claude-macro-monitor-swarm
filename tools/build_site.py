"""Static site -> docs/<pages.slug>/ (staging copy; tools.publish_pages mirrors it to the pages repo).

    python -m tools.build_site [--week 2026-W41]

Pages per edition: reports/<week>.html (business briefing), blackboard/<week>.html
(full blackboard), audit/<week>.html (automated fact-check). index.html is
regenerated from the files on disk, so there are no insert markers to maintain.
Everything is plain HTML/CSS, no CDN.
"""
import argparse
import html
import re
import sys

from collectors import common as C
from tools import render_blackboard, store

SITE = C.ROOT / "docs" / C.deployment().get("pages", {}).get("slug", "macro-monitor")

CSS = """:root{--bg:#f7f7f4;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;--line:#e2e1dc;--accent:#2f5d8a;--hot:#b4472f;--cool:#2f7a5b}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--muted:#a3a29b;--card:#1e1e1c;--line:#33332f;--accent:#7fa8d1;--hot:#e0866f;--cool:#71c09b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:920px;margin:0 auto;padding:24px 16px 64px}nav{font-size:14px;margin-bottom:24px}nav a{margin-right:16px}
a{color:var(--accent)}h1{font-size:28px;margin:0 0 4px}h2{font-size:20px;margin:32px 0 8px;border-bottom:1px solid var(--line);padding-bottom:4px}
.muted{color:var(--muted);font-size:14px}.banner{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);padding:12px 16px;margin:16px 0;font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:16px 0}.kpi{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:12px}
.kpi .v{font-size:24px;font-weight:700}.kpi .l{font-size:13px;color:var(--muted)}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px;background:var(--card)}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{background:var(--bg)}
.bars{display:flex;gap:16px;align-items:flex-end;height:180px;border-bottom:1px solid var(--line);padding:8px 0;margin:12px 0}
.bar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}.bar .b{width:60%;background:var(--accent);border-radius:3px 3px 0 0}
.bar .t{font-size:13px;margin-bottom:4px}.bar .n{font-size:12px;color:var(--muted);margin-top:6px;text-align:center}
.row{display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}
.qa{font-size:12px;border:1px solid var(--line);border-radius:10px;padding:1px 8px;margin-right:8px}
footer{margin-top:48px;font-size:13px;color:var(--muted)}
"""


def page(title, body, depth=1):
    dep = C.deployment()
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><link rel="stylesheet" href="{up}style.css"></head><body><main>
<nav><a href="{up}index.html">Macro Monitor</a></nav>
{body}
<footer>{html.escape(dep['site'].get('footer', ''))}</footer></main></body></html>
"""


def md_to_html(md):
    """Enough markdown for the blackboard: headings, pipe tables, bold, italics, links, paragraphs."""
    def inline(s):
        s = html.escape(s, quote=False)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w])_([^_]+)_(?![\w])", r"<em>\1</em>", s)
        return s.replace("\\|", "|")
    out, table = [], []

    def flush():
        if not table:
            return
        rows = [re.split(r"(?<!\\)\|", r.strip().strip("|")) for r in table if not re.match(r"^\|[-|: ]+\|$", r.strip())]
        h = "".join(f"<th>{inline(c.strip())}</th>" for c in rows[0])
        b = "".join("<tr>" + "".join(f"<td>{inline(c.strip())}</td>" for c in r) + "</tr>" for r in rows[1:])
        out.append(f'<div class="table-wrap"><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>')
        table.clear()
    for ln in md.splitlines():
        if ln.strip().startswith("|"):
            table.append(ln)
            continue
        flush()
        if ln.startswith("# "):
            out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif ln.startswith("## "):
            out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
    flush()
    return "\n".join(out)


def _fmt_kpi(k):
    v = k.get("value")
    if v is None:
        return "n/a"
    unit = k.get("unit", "")
    return f"{v:,.1f}{unit}" if abs(v) < 1000 else f"{v:,.0f}{unit}"


def inflation_bars():
    bars = []
    for rid, key, label in (("cpi", "headline.yoy_pct", "CPI"), ("cpi", "core.yoy_pct", "Core CPI"),
                            ("pce", "headline.yoy_pct", "PCE"), ("pce", "core.yoy_pct", "Core PCE")):
        latest = store.latest_per_report("inflation").get(rid)
        v = (latest or {}).get("metrics", {}).get(key)
        if v is None:
            continue
        h = max(0.0, min(100.0, v / 8 * 100))
        bars.append(f'<div class="bar"><div class="t">{v:+.1f}%</div><div class="b" style="height:{h:.1f}%"></div>'
                    f'<div class="n">{label}<br>{latest["ref"]}</div></div>')
    if not bars:
        return ""
    return '<h2>Inflation, y/y</h2><div class="bars">' + "".join(bars) + "</div><p class='muted'>Scale 0 to 8%. Fed target: 2% core PCE.</p>"


def report_page(s):
    esc = html.escape
    kpis = "".join(f'<div class="kpi"><div class="v">{_fmt_kpi(k)}</div><div class="l">{esc(k["label"])}</div></div>'
                   for k in s.get("kpis", []))
    score = "".join(f"<tr><td>{esc(d.get('domain', ''))}</td><td>{esc(d.get('signal', ''))}</td><td>{esc(d.get('note', ''))}</td></tr>"
                    for d in s.get("domain_scorecard", []))
    narr = "".join(f"<h3>{esc(p.get('title', ''))}</h3><p>{esc(p.get('body', ''))}</p>" for p in s.get("narrative", []))
    wa = "".join(f"<tr><td>{esc(e.get('weekday') or '')} {esc(e.get('date') or 'tbc')}</td><td>{esc(e.get('time_et') or '')}</td>"
                 f"<td>{esc(e.get('name', ''))}{' (est.)' if e.get('date_source') == 'estimate' else ''}</td><td>{esc(e.get('why', ''))}</td></tr>"
                 for e in s.get("week_ahead", []))
    issues = len(s.get("audit", {}).get("issues", []))
    body = f"""<p class="muted">No. {esc(s['week'])} · week ending {esc(s['week_ending'])}</p>
<h1>Weekly macro briefing</h1>
<div class="banner">{esc(s.get('regime', ''))}</div>
<h2>Executive summary</h2><p>{esc(s.get('executive_summary', ''))}</p>
<div class="kpis">{kpis}</div>
<h2>Domain scorecard</h2><div class="table-wrap"><table><thead><tr><th>Domain</th><th>Signal</th><th>Note</th></tr></thead><tbody>{score}</tbody></table></div>
<h2>What the data is saying</h2>{narr}
{inflation_bars()}
<h2>Regime watch</h2><p>{esc(s.get('regime_watch', ''))}</p>
<h2>Week ahead</h2><div class="table-wrap"><table><thead><tr><th>Date</th><th>ET</th><th>Release</th><th>Why it matters</th></tr></thead><tbody>{wa}</tbody></table></div>
<h2>Monitoring status</h2><p>{esc(s.get('swarm_health', ''))}</p>
<p class="muted">Figures come from official sources (FRED, BLS, BEA, Fed, ECB, BoE) via deterministic collectors.
<a href="../blackboard/{esc(s['week'])}.html">Full blackboard</a> · <a href="../audit/{esc(s['week'])}.html">Automated fact-check ({issues} open issue{'s' if issues != 1 else ''})</a></p>"""
    return page(f"Macro briefing {s['week']}", body)


def audit_page(s):
    a = s.get("audit", {})
    rows = "".join(f"<tr><td>{html.escape(i['type'])}</td><td>{html.escape(str(i.get('text', '')))}</td><td>{html.escape(i['problem'])}</td></tr>"
                   for i in a.get("issues", [])) or "<tr><td colspan=3>No issues found.</td></tr>"
    body = f"""<h1>Fact-check {html.escape(s['week'])}</h1>
<p class="muted">Automated checks run {html.escape(a.get('checked_at', ''))}: weekday/date consistency, week-ahead items against the release calendar,
every quoted figure against the logged data, KPI references. Corrections are applied before publishing; anything left is listed here.</p>
<div class="table-wrap"><table><thead><tr><th>Check</th><th>Item</th><th>Finding</th></tr></thead><tbody>{rows}</tbody></table></div>
<p><a href="../reports/{html.escape(s['week'])}.html">Back to the briefing</a></p>"""
    return page(f"Fact-check {s['week']}", body)


def index_page():
    rows = []
    for p in sorted((SITE / "reports").glob("*.html"), reverse=True):
        wk = p.stem
        s = C.load_json(C.DATA / "synthesis" / f"{wk}.json", {})
        n = len(s.get("audit", {}).get("issues", []))
        rows.append(f'<div class="row"><div><strong>{wk}</strong> · {html.escape(s.get("regime", ""))}</div>'
                    f'<div><span class="qa">{n} open check{"s" if n != 1 else ""}</span>'
                    f'<a href="reports/{wk}.html">Briefing</a> · <a href="blackboard/{wk}.html">Blackboard</a> · '
                    f'<a href="audit/{wk}.html">Fact-check</a></div></div>')
    body = f"""<h1>{html.escape(C.deployment()['site'].get('title', 'Macro Monitor'))}</h1>
<p class="muted">Weekly synthesis of 7 macro domains (inflation, labour, growth, housing, sentiment, central banks, financial conditions).
Collectors pull official data every weekday; an LLM strategist writes the weekly read from that data only.</p>
<h2>Editions</h2>{''.join(rows) or '<p>No editions yet.</p>'}"""
    return page("Macro Monitor", body, depth=0)


def build(week=None):
    files = sorted((C.DATA / "synthesis").glob("*.json"))
    target = C.DATA / "synthesis" / f"{week}.json" if week else (files[-1] if files else None)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "style.css").write_text(CSS, encoding="utf-8")
    written = ["style.css"]
    if target and target.exists():
        s = C.load_json(target)
        wk = s["week"]
        for sub, content in (("reports", report_page(s)), ("audit", audit_page(s)),
                             ("blackboard", page(f"Blackboard {wk}", md_to_html(render_blackboard.render(rows=12))))):
            (SITE / sub).mkdir(exist_ok=True)
            (SITE / sub / f"{wk}.html").write_text(content, encoding="utf-8")
            written.append(f"{sub}/{wk}.html")
    (SITE / "index.html").write_text(index_page(), encoding="utf-8")
    written.append("index.html")
    root_index = C.ROOT / "docs" / "index.html"
    if not root_index.exists():
        root_index.write_text('<!doctype html><meta http-equiv="refresh" content="0; url=macro-monitor/">', encoding="utf-8")
    return written


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--week")
    a = ap.parse_args(argv)
    print("\n".join(build(a.week)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
