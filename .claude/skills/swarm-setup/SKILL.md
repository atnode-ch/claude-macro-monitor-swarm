---
name: swarm-setup
description: Stand the macro swarm up in the current Claude Code account (or tear it down). Checks prerequisites, seeds the data baseline, and creates the routines declared in routines/*.json. Use when installing the swarm in a new account, after forking the repo, or when asked to (re)create or remove the macro routines.
---

# swarm-setup

Everything account-specific comes from `config/deployment.json`. Routines are declared in `routines/*.json`. Nothing here depends on this account's memory or on any personal files.

## 1. Preflight (report every item as ok / missing)

- `config/deployment.json` exists and has no `YOUR_` placeholders. If missing: copy `config/deployment.example.json`, ask the user for the values, write it, commit it.
- `python -m unittest discover -s tests -t .` passes.
- Slack connector: attached to this environment and able to post to `slack.channel_id`. If not, tell the user to add it (claude.ai connector settings) and continue; alerts will report WRITE BLOCKED until then.
- GitHub: this session can push to `github.branch` of `github.owner/github.repo`.
- GitHub Pages: the site is published to the repo in `pages` (`pages.owner/pages.repo`, folder `<pages.dir>/<pages.slug>/`). Check this session can push to `pages.branch` there, and ask the user to enable Pages from `docs/` on that branch if `site.base_url` doesn't return 200 yet. The strategist routine needs that repo as a second source.
- GitHub Actions: `.github/workflows/collect.yml` exists on the default branch and Actions are enabled with read/write workflow permissions.

## 2. Seed (only when `data/state.json` is missing)

```bash
python -m collectors.calendar
python -m collectors.engine --seed      # records the current period of every report as baseline; queues nothing
python -m tools.render_blackboard
python -m tools.build_site
git add data blackboard docs && git commit -m "seed baseline" && git push origin <branch>
python -m tools.publish_pages && git -C ../<pages.repo> push origin HEAD:<pages.branch>
```

## 3. Create routines

For each file in `routines/*.json`:
- name = value at `name_from` in deployment.json, model = value at `model_from`.
- Skip if `config/routines.local.json` already lists a trigger for that `key` (unless the user asked to recreate).
- Create it with this environment's routine/trigger tool (for example `create_trigger`): the `cron`, the `prompt`, fresh session per firing (`fires_into: new_session`), the listed `connectors`, initiation = human request.
- If no such tool exists in this environment, print the spec as a table so the user can create it in the claude.ai Routines UI, and stop here.
- **Finish each routine in the Routines UI.** A routine created by the tool may come out without a repository source and without connectors (the tool can only pass through connectors the calling session holds, and some organizations disable the `connectors` parameter). Such a routine starts with no checkout and cannot post to Slack. Check the created trigger: if `sources` or `mcp_connections` is empty, create it paused (`enabled: false`) and ask the user to open it in the claude.ai Routines page, add the repository (`github.owner/github.repo`, branch `github.branch`; for the strategist also `pages.owner/pages.repo`) and the Slack connector, then re-enable it. Set the model with the update tool afterwards if the create tool has no model field.
- Routine sessions may only be allowed to push to their own `claude/*` branch. The first run that has something to commit shows it: if the push to `github.branch` is refused, the skills report `WRITE BLOCKED`; then either allow routine pushes to that branch or switch the routines to a data branch that is merged automatically.

Write the returned IDs to `config/routines.local.json` (gitignored; per account):

```json
{"release": {"trigger_id": "trig_...", "name": "macro-release"}, "strategist": {"trigger_id": "trig_...", "name": "macro-strategist"}}
```

## 4. Smoke test

- Ask before firing anything. With consent, fire the release routine once: it should answer "Quiet: nothing pending."
- Trigger the Action once (`workflow_dispatch`) from the GitHub UI and confirm it commits `data/state.json`.

## Teardown

Delete each trigger in `config/routines.local.json` with the environment's delete tool (confirm with the user first), then remove the file. Data and site stay in git.

## Final answer

A checklist: preflight results, seed done or skipped, routines created (names, schedules, IDs), what the user still has to do by hand.
