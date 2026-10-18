---
name: macro-strategist
description: Weekly macro synthesis (Friday). Reads the compact digest, applies the cross-indicator chain, writes the weekly synthesis draft, fact-checks it with code, builds the static site and publishes it to the shared pages repo (docs/<slug>), posts one Slack summary (plus a health alert when a collector is stale), and commits. Used by the macro-strategist routine.
---

# macro-strategist

You are the swarm's judgment layer. You synthesise; you do not collect and you do not browse. Every figure you mention must already be in the digest.

Read `config/deployment.json` (branch, Slack channel, `site.base_url`) and `config/cross_indicator.md`.

## 0. Sync and drain

```bash
git fetch origin <branch> && git checkout <branch> && git pull --ff-only origin <branch>
python -m tools.pending list
```

If items are pending, run the `macro-release` skill first so the week is complete.

## 1. Digest (never read data/ wholesale)

```bash
python -m tools.synthesis digest
```

It holds: health, releases detected this week, each domain's stance and latest prints, market levels with 5-day changes, next week's calendar, last week's regime line. If a domain has no stance or is stale, say so in the text.

## 2. Draft

Write `data/inbox/synthesis-draft.json`:

```json
{
  "regime": "one-line regime headline",
  "executive_summary": "120-180 words",
  "narrative": [
    {"title": "Inflation and policy", "body": "..."},
    {"title": "Labour", "body": "..."},
    {"title": "Growth, housing and sentiment", "body": "..."},
    {"title": "Financial conditions", "body": "..."}
  ],
  "domain_scorecard": [{"domain": "Inflation", "signal": "firm|cooling|steady|weakening|strong|n/a", "note": "<= 15 words"}],
  "regime_watch": "what would confirm or deny a regime change",
  "week_ahead": [{"report": "<report id from next_week_calendar>", "why": "<= 20 words"}],
  "kpis": [{"label": "Core PCE y/y", "ref": "inflation/pce/2026-08:core.yoy_pct", "unit": "%"}],
  "slack_summary": "3 lines max: regime headline, the week's key prints, what to watch next week"
}
```

Rules:
- 7 scorecard rows, one per domain. 4 to 6 KPIs, chosen by you, values filled by code from `ref`.
- `week_ahead` uses report ids from `next_week_calendar`; code fills date, weekday and time. Don't write weekdays or dates for upcoming events in the prose.
- Body copy around 650 to 700 words in total. Plain business language, standard abbreviations (CPI, PPI, PCE, NFP, ISM, FOMC, ECB, BoE).
- A single surprise is noise; multi-domain alignment is signal. Name alignments.

## 3. Finalize and fact-check

```bash
python -m tools.synthesis finalize data/inbox/synthesis-draft.json
```

If `audit.issues` is non-empty: fix the draft (drop or correct the flagged figure, date or reference) and finalize again. At most 2 rounds; anything left stays listed on the public fact-check page. Then delete the draft file.

## 4. Publish

```bash
python -m tools.render_blackboard
python -m tools.build_site
git add data blackboard docs
git commit -m "weekly synthesis <week>"
git push origin <branch>
```

If the session assigned a different working branch, push there too, then fast-forward the deployment branch with `git push origin HEAD:<branch>` (standing permission, see CLAUDE.md). The run is not published until `<branch>` has the commit.

Then publish the site to the pages repo (`pages` in deployment.json; GitHub Pages serves `<pages.repo>/<pages.dir>/`, so the site lands at `<pages.dir>/<pages.slug>/`):

```bash
python -m tools.publish_pages --message "<slug>: weekly synthesis <week>"
cd ../<pages.repo>
git push origin HEAD:<pages.branch>
```

`publish_pages` uses the checkout at `../<pages.repo>` (cloning it if absent), replaces only `<dir>/<slug>/` and commits. If the session assigned a working branch for the pages repo, push there first (`git push -u origin <working branch>`), then fast-forward `<pages.branch>` the same way as above: same standing permission, rebase onto `origin/<pages.branch>` and retry once if rejected, never force-push. The site is not live until `<pages.branch>` has the commit.

## 5. Slack

One message to `channel_id`: the `slack_summary` plus the link `<site.base_url>reports/<week>.html`.
If `health.all_ok` is false, post the `alert_text` from the digest as a **separate** message. This always fires, even on a quiet week.

If Slack or the push is blocked, start the final answer with `WRITE BLOCKED` and include the exact texts.

## Final answer

Regime headline, audit result (issues found/fixed), link, health line.
