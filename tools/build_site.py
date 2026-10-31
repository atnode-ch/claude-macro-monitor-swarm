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

CSS = """/* ThoughtNode "Tactile Archival". Tokens from tn-skill-brand-thoughtnode. Fonts: self-host woff2 beside this file for exact match; system serif/sans fallbacks otherwise. */
:root{--vellum:#F9F6F0;--linen:#F1ECE2;--card:#FFFDF9;--ink:#1C2321;--ink2:#4A524E;--dim:#646A65;--rule:rgba(28,35,33,.12);
--oxblood:#7A2E2A;--brass:#A8813A;--sage:#56654A;--cloth:#1C2321;--cloth-ink:#EEE9DF;--cloth-brass:#D2AE68;
--serif:Newsreader,"Iowan Old Style",Georgia,"Times New Roman",serif;--sans:"Source Sans 3","Source Sans Pro",system-ui,-apple-system,"Segoe UI",sans-serif;--mono:"IBM Plex Mono",ui-monospace,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--vellum:#161C1A;--linen:#1D2421;--card:#222A27;--ink:#EEE9DF;--ink2:#C3C1B7;--dim:#A0A59E;--rule:rgba(238,233,223,.14);--oxblood:#D9857D;--brass:#D2AE68;--sage:#A9B99A;--cloth:#0F1413}}
*{box-sizing:border-box}
body{margin:0;background:var(--vellum);color:var(--ink);font:18px/1.65 var(--sans)}
main{max-width:920px;margin:0 auto;padding:0 20px 72px}
header.mast{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;padding:22px 0 14px;border-bottom:1px solid var(--rule);margin-bottom:36px}
.brand{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink);font:400 24px/1 var(--serif)}
.brand svg{width:22px;height:22px;flex:none}.brand em{font-style:normal;color:var(--dim);font-size:15px;font-family:var(--sans);letter-spacing:.02em;margin-left:4px}
nav{display:flex;gap:6px;font-size:14px;font-weight:600}
nav a{padding:6px 14px;border:1px solid var(--rule);border-bottom-color:var(--brass);border-radius:6px 6px 0 0;text-decoration:none;color:var(--ink2);background:var(--linen)}
nav a:hover{color:var(--oxblood)}
a{color:var(--oxblood);text-underline-offset:3px}
h1{font:400 40px/1.15 var(--serif);margin:4px 0 8px;letter-spacing:-.01em}
h2{font:500 24px/1.25 var(--serif);margin:44px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--rule)}
h3{font:500 19px/1.3 var(--serif);margin:24px 0 4px}
p{margin:0 0 14px}
.muted{color:var(--dim);font-size:15px}
.muted:first-child{font-family:var(--mono);font-size:13px;letter-spacing:.04em;text-transform:uppercase}
.banner{background:var(--card);border:1px solid var(--rule);border-left:4px solid var(--oxblood);border-radius:4px;padding:16px 20px;margin:20px 0;font:italic 400 22px/1.4 var(--serif);box-shadow:0 1px 3px rgba(28,35,33,.08)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px;margin:20px 0}
.kpi{background:var(--card);border:1px solid var(--rule);border-top:3px solid var(--brass);border-radius:4px;padding:14px 16px;box-shadow:0 1px 3px rgba(28,35,33,.08)}
.kpi .v{font:400 30px/1.1 var(--mono);color:var(--ink)}.kpi .l{font-size:14px;color:var(--dim);margin-top:4px}
.table-wrap{overflow-x:auto;border:1px solid var(--rule);border-radius:4px;background:var(--card)}
table{border-collapse:collapse;width:100%;font-size:15px;line-height:1.5}
th,td{border-bottom:1px solid var(--rule);padding:9px 12px;text-align:left;vertical-align:top}
tr:last-child td{border-bottom:0}
th{background:var(--linen);font:600 12px/1.3 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink2);border-bottom:2px solid var(--brass)}
td:first-child{font-weight:600}
.bars{display:flex;gap:16px;align-items:flex-end;height:190px;border-bottom:1px solid var(--ink2);padding:8px 0;margin:14px 0}
.bar{flex:1;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;height:100%}
.bar .b{width:56%;background:var(--brass);border-radius:2px 2px 0 0}
.bar .t{font:400 14px var(--mono);margin-bottom:4px}.bar .n{font-size:13px;color:var(--dim);margin-top:6px;text-align:center}
.row{display:flex;justify-content:space-between;align-items:center;gap:16px;padding:14px 0;border-bottom:1px solid var(--rule)}
.row strong{font:500 18px var(--mono);color:var(--oxblood);margin-right:6px}
.row div:last-child{white-space:nowrap;font-size:15px}
.qa{display:inline-block;font:600 11px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--sage);border:1.5px solid var(--sage);border-radius:3px;padding:4px 7px;margin-right:12px;transform:rotate(-2deg)}
.qa.open{color:var(--oxblood);border-color:var(--oxblood)}
@media (max-width:640px){body{font-size:17px}h1{font-size:32px}.row{flex-direction:column;align-items:flex-start;gap:8px}.row div:last-child{white-space:normal}}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--rule);font-size:14px;color:var(--dim)}
footer .tag{font:italic 400 16px var(--serif);color:var(--ink2);display:block;margin-bottom:4px}
"""


def page(title, body, depth=1):
    dep = C.deployment()
    up = "../" * depth
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><link rel="stylesheet" href="{up}style.css"></head><body><main>
<header class="mast"><a class="brand" href="{up}index.html"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="none" stroke="#A8813A" stroke-opacity=".22" stroke-width="2"/><circle cx="12" cy="12" r="5" fill="#A8813A"/></svg>ThoughtNode<em>Macro Monitor</em></a><nav><a href="{up}index.html">Editions</a></nav></header>
{body}
<footer><span class="tag">Master the machine. Multiply the mind.</span>{html.escape(dep['site'].get('footer', ''))}</footer></main></body></html>
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
                    f'<div><span class="qa{" open" if n else ""}">{"Verified" if not n else f"{n} open"}</span>'
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
