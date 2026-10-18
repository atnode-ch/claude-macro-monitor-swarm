# From Hyperagent to Claude Code: assessment and migration

Source: the Hyperagent backup of "A - Macro Strategist" and its 7 domain agents (the `migration/agent.<slug>/` folders, also on Drive under `agent.hyperagent.talfco/`, snapshot 2026-10-07). This repo replaces it.

## Verdict on the original architecture

The design holds. The implementation drifted.

**Kept as is**
- 3 tiers: domain = analytical lens, report = timing, orchestrator = synthesis. Domain-first beats geography-first because the leads/lags playbook is organised by domain.
- Blackboard coordination, no agent-to-agent messaging.
- Collectors touch the internet; the strategist reasons over logged data only. This boundary is the best rule in the original design.
- Deterministic scripts for the mechanical work (digest/health, BLS/BEA/FRED checks).
- Market Watch as its own domain, and "classify by what it measures, not by who publishes it".

**What had gone wrong**
1. **Numbers passed through LLMs.** The blackboard was a free-text doc that agents rewrote. 4 Inflation rows were mis-transcribed (June/July CPI and PPI, one with the sign flipped), the Growth section was wiped and restored, and a self-heal step walked 20 doc versions back. The doc had grown to 145 KB.
2. **Collectors had drifted to Friday-only.** Morning checks were paused and the remaining check set to `BYDAY=FR` for Inflation, Labor and Market Watch. A Tuesday CPI was logged on Friday; the "tier-1 instant alert" no longer existed. Growth still ran 10 times a week.
3. **Every quiet run booted a full agent** just to stamp a heartbeat line.
4. **Two skill bugs were flagged for weeks and never fixed.**
   - PPI headline used `WPSFD49207/WPUFD49207`, which is Finished Goods. Final Demand is `WPSFD4/WPUFD4`. Verified live on 2026-10-07: the old series gives +0.88% m/m for August 2026, the correct one +0.40%, matching the official print.
   - The BEA PCE parser matched the line text exactly and broke when BEA relabelled it, so `is_new` returned a false negative for August PCE.
5. **Config drift:** three model families (Opus, Sonnet, GLM), Labor Watch with no web or document tools enabled, Market Watch with a null execution mode.
6. **Week-ahead came from a memorised calendar.** That's how Jackson Hole landed on a Saturday in W35, and why an LLM self-audit plus rubric page was bolted on. (The memorised calendar also had the September FOMC as 16 to 17 Sep; the Fed's own page says 15 to 16.)
7. **The Friday prompt was about 9 KB of procedure**: template fetching, HTML editing, insert markers. Code pretending to be a prompt.

## What replaced what

| Hyperagent | Here |
|---|---|
| 7 domain agents on schedules | `collectors/engine.py` driven by `config/domains.json`, run by a free GitHub Action 3 times each weekday |
| Per-agent "release check" skills | One engine: FRED CSV (keyless), BLS, Fed/ECB/BoE pages; `web` reports flagged due by calendar rule |
| Domain agent LLM work | `domain-analyst` subagent, only for a release that actually landed: consensus, one-line read, stance |
| Blackboard doc | `data/` JSON as source of truth; `blackboard/BLACKBOARD.md` rendered from it |
| Heartbeat lines + 36h staleness parsing | `data/state.json` written by the collector; `tools/store.health()` |
| Self-heal from doc versions | git history |
| Memorised release calendar | `collectors/calendar.py`: Fed, ECB, BoE, BEA official calendars + estimates flagged as such |
| LLM self-audit + rubric | `tools/synthesis.py audit`: weekday/date checks, week-ahead vs calendar, every quoted figure vs data, KPI refs |
| Saturday/Friday HTML editing by the LLM | `tools/build_site.py` fills pages from `data/synthesis/<week>.json` |
| 15 memories | `CLAUDE.md`, lenses, `config/*.json`, skills (all in git, portable) |
| agentweb site | `docs/macro-monitor/` here, published to `atnode-agent-pages/docs/macro-monitor/` (GitHub Pages) |

## Token economy

| | Hyperagent (as configured) | Here |
|---|---|---|
| Quiet weekday | up to 7+ agent runs (system prompt, section read, often web search) | 0 tokens (Action only); release routine exits after one command |
| Release day | 1 agent run per domain per check | 1 Sonnet session, 1 small subagent per release (packet of about 2 KB, one search) |
| Figures | typed by the LLM, then corrected by the LLM | written by code; LLM writes consensus, read, stance |
| Friday | Opus with a 9 KB procedure, HTML editing in context, LLM audit | Opus with a < 10 KB digest; writes about 700 words of prose into a JSON draft; code builds, audits, publishes |
| Week-ahead | from memory, then LLM-audited | from `data/calendar.json`; dates and weekdays filled by code |

Expectation (to confirm in the parallel run): a quiet week goes from 40+ agent runs to one Opus session plus a handful of near-empty Sonnet sessions; a busy week adds roughly one short Sonnet session per release day.

## Data sources (all keyless)

- FRED `fredgraph.csv` for every US series, plus ECB deposit rate, euro-area HICP and GDP. FRED stalls requests that send a browser User-Agent, so the code uses Python's default.
- BLS API kept as an option; its keyless quota is 25 requests a day, which a shared GitHub runner can exhaust. CPI and PPI therefore read FRED's mirrors of the same BLS series (identical values, checked).
- Fed FOMC calendar page, ECB Governing Council calendar, BoE MPC dates page (also the current Bank Rate).
- BEA iCal feed for GDP, PCE and trade dates. With `FRED_API_KEY` the official FRED release calendar is added.
- `web` reports (ISM, Conference Board, Ifo, UK labour market, CARTS) have no free API: the collector flags them due by calendar rule and the analyst fetches figures, marking single-source figures unconfirmed.

## Migration status

- [x] Repo, collectors for all 7 domains, calendar, tools, tests, skills, routines, Action.
- [x] Baseline seeded from live data on 2026-10-07 (August CPI/PPI/PCE match the official prints).
- [ ] Merge to the default branch; enable Actions and Pages.
- [ ] Attach the Slack connector; run `/swarm-setup` to create the routines.
- [ ] 2-week parallel run against Hyperagent; compare figures, alerts, Friday narrative, spend.
- [ ] Portability dry run: set up from a clean clone in a second account using only the README.
- [ ] Pause the Hyperagent schedules; redirect the old agentweb page.

Not migrated on purpose: the historical consensus/read text from the old blackboard. Figures are re-derived from official APIs instead, and stances start fresh with the first analysed release per domain.
