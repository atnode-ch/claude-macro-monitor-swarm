# Macro Monitor swarm

A macro-monitoring swarm: 7 domain collectors (code), a domain-analyst subagent (LLM, per release) and a weekly strategist (LLM). Port of a Hyperagent swarm; see `migration/README.md` for the original backup and `MIGRATION.md` for the mapping.

## How it runs

1. **GitHub Action** (`.github/workflows/collect.yml`, weekdays) runs `collectors.calendar` and `collectors.engine`. Official data lands in `data/releases/**`; anything new is queued in `data/pending.json`. No LLM, no tokens.
2. **macro-release routine** (skill `macro-release`) drains the queue: one `domain-analyst` subagent per release adds consensus, a one-line read and the domain stance; `tools.pending` validates, computes surprise and decides alerts; alerts go to Slack.
3. **macro-strategist routine** (skill `macro-strategist`, Friday) reads `tools.synthesis digest`, writes the weekly synthesis, fact-checks it, builds the site in `docs/`, posts one Slack summary.

## Hard rules

- **Never type a figure that a collector owns.** For API-backed reports the numbers in `data/releases/**` are the truth. The LLM writes only: consensus (with its source), the read, the stance, qualitative fields, and figures for `web` reports that have no API.
- **Write data only through the tools.** Analysts write `data/inbox/<report>-<ref>.json`; `python -m tools.pending apply` merges it. The strategist writes a draft JSON; `python -m tools.synthesis finalize` saves it. Never hand-edit `data/releases/**`, `data/state.json` or `blackboard/BLACKBOARD.md` (it is rendered).
- **Ground every claim** in `data/` or `data/calendar.json`. If a domain is stale or empty, say so. Never backfill from memory. Mark anything you could not confirm as `unconfirmed`.
- **The strategist does not browse.** Fan-in reasons over logged data only. Web access is for analysts (consensus, web-only reports) and for ad-hoc questions.
- **Dates come from `data/calendar.json`**, never from memory. Don't attach a weekday to a date you didn't take from there.
- **Stay in lane.** Classify an indicator by what it measures, not by who publishes it (Chicago Fed: NFCI is markets, CARTS is growth). A new indicator that only previews a tracked series is logged as a preview; alert only on divergence or multi-source confirmation.
- **Alert discipline.** Only `tools.pending alerts` output and the Friday summary go to Slack. Quiet run, no Slack. A health alert always goes out, even on a quiet week.
- **Publish to the deployment branch.** The owner has standing permission for every routine run to push its commit to `github.branch` in `config/deployment.json` (`main`), even when the session was assigned a different working branch. Push to the working branch as the session requires, then fast-forward the deployment branch: `git push origin HEAD:<branch>`. If that is rejected, rebase onto `origin/<branch>` and retry once. Never force-push it.
- **Blocked writes are loud.** If a commit, push or Slack post fails or is not permitted, start your final answer with `WRITE BLOCKED` and list exactly what was not written.

## Account-specific values

All of them live in `config/deployment.json` (Slack channel, GitHub owner, site URL, routine names). Read them from there; never hardcode them in skills or code.

## Commands

```bash
python -m unittest discover -s tests -t .      # offline tests
python -m collectors.calendar                  # refresh release calendar
python -m collectors.engine [--seed] [--domain X] [--dry-run]
python -m tools.pending list|brief|apply|alerts
python -m tools.synthesis digest|audit|finalize
python -m tools.render_blackboard
python -m tools.build_site
```

Stdlib Python 3.11+ only; no installs needed.

## Writing style for reads, stances and the weekly report

Plain, specific, quantitative. Numbers as digits. Short paragraphs. No hype words, no em dashes, no "it's not X, it's Y" constructions. Say what the data shows and what would change the view.
