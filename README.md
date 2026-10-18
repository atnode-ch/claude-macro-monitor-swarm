# Macro Monitor swarm (Claude Code)

A macro-monitoring swarm for 7 domains (inflation, labour, growth, housing, sentiment, central banks, financial conditions). Free GitHub Actions collect official data every weekday; Claude routines analyse new releases and write a weekly synthesis; a static site is built in `docs/<slug>/` and published to a shared GitHub Pages repo (`pages` in `config/deployment.json`, here `atnode-agent-pages/docs/macro-monitor/`).

Ported from a Hyperagent swarm. Why it's built this way: [MIGRATION.md](MIGRATION.md).

```
GitHub Action (weekdays, free)        Claude routines
collectors -> data/releases/**  ───▶  macro-release (sonnet): analyst per release -> Slack alerts
           -> data/pending.json       macro-strategist (opus, Fri): synthesis -> site -> pages repo -> Slack
```

## Set it up in any Claude Code account

1. **Fork or copy** this repo into your GitHub account or org.
2. **Configure:** copy `config/deployment.example.json` to `config/deployment.json` and fill in GitHub owner/repo/branch, Pages URL, Slack channel ID. That file holds every account-specific value; nothing else needs editing.
3. **GitHub:** enable Actions with read/write workflow permissions (Settings > Actions > General) In the pages repo named by `pages`, enable Pages from `docs/` on `pages.branch` (Settings > Pages); the site goes to `docs/<pages.slug>/` there.
4. **Secrets (all optional):** `FRED_API_KEY` adds the official FRED release calendar; `BLS_API_KEY` is unused by default. Data sources work without keys. Add them as Actions secrets.
5. **Claude:** open the repo in Claude Code on the web (claude.ai/code) with an environment that can reach the internet, attach the **Slack** connector, then run:

   ```
   /swarm-setup
   ```

   It checks prerequisites, seeds the data baseline, and creates the two routines from `routines/*.json` (or prints them for you to create in the Routines UI).
6. **Smoke test:** run the `collect` workflow once from the Actions tab.

Moving to another account later is the same 6 steps; routine IDs live in the untracked `config/routines.local.json`.

## Where the pages are published

The site is not served from this repo. `tools.publish_pages` mirrors the staging copy in `docs/macro-monitor/` into a separate repo, **[atnode-ch/atnode-agent-pages](https://github.com/atnode-ch/atnode-agent-pages)**, under `docs/macro-monitor/`, and commits it. The `macro-strategist` routine then pushes that commit to `main` of the pages repo.

`atnode-agent-pages` is the shared GitHub Pages repo for all of Felix's agents. It is connected to the custom domain **agents.atnode.ch**, which serves the repo's `docs/` folder. Each agent publishes into its own `docs/<slug>/` folder, so this swarm's site is live at:

**https://agents.atnode.ch/macro-monitor/**

```
this repo                          atnode-ch/atnode-agent-pages            agents.atnode.ch
docs/macro-monitor/  ──publish──▶  docs/macro-monitor/  ──GitHub Pages──▶  /macro-monitor/
```

The values come from `pages` and `site.base_url` in `config/deployment.json` (`owner`, `repo`, `branch`, `dir`, `slug`). To publish elsewhere, change them there and nothing else.

## Day to day

| When | What | Cost |
|---|---|---|
| Weekdays 3×, 09:00 / 10:45 / 16:15 ET (summer) | `collect` Action: calendar + collectors, commit data | free |
| Weekdays 11:07 and 17:07 ET | `macro-release` routine: exits in one command if nothing is pending; otherwise one Sonnet analyst per release, Slack alerts | small |
| Friday 17:47 ET | `macro-strategist` routine (Opus): synthesis, fact-check, site, one Slack post | one session |

## Layout

```
config/            domains.json (reports + series), thresholds.json (alert policy), deployment.json,
                   lenses/<domain>.md, cross_indicator.md
collectors/        engine.py (fetch, dedup, queue), calendar.py (Fed/ECB/BoE/BEA calendars), common.py
tools/             pending.py (analyst I/O + validation), alert_gate.py, synthesis.py (digest, audit, finalize),
                   render_blackboard.py, build_site.py, publish_pages.py, store.py
data/              releases/<domain>/<report>/<ref>.json, stances/, synthesis/, state.json, pending.json, calendar.json
blackboard/        BLACKBOARD.md (rendered, read-only)
docs/macro-monitor site staging copy (published to the pages repo by tools/publish_pages.py)
.claude/           agents/domain-analyst.md, skills/{macro-release,macro-strategist,swarm-setup}
routines/          declarative routine specs
```

## Local commands

```bash
python -m unittest discover -s tests -t .
python -m collectors.calendar
python -m collectors.engine --dry-run
python -m tools.pending list
python -m tools.synthesis digest
python -m tools.render_blackboard && python -m tools.build_site
```

Python 3.11+, stdlib only.

## Adding a report

Add an entry to `config/domains.json` (FRED or BLS series, or a `web` report with a due-date rule), a threshold in `config/thresholds.json`, and run the tests. No prompt changes needed.
