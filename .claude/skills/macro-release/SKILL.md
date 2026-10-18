---
name: macro-release
description: Drain the macro release queue. For each newly collected release, run a domain-analyst subagent, validate and merge its output, re-render the blackboard, post the alerts that pass the gate to Slack, and commit. Used by the macro-release routine; safe to run by hand.
---

# macro-release

Read `config/deployment.json` first: `github.branch`, `slack.channel_id`.

## 0. Sync

```bash
git fetch origin <branch> && git checkout <branch> && git pull --ff-only origin <branch>
python -m tools.pending list
```

If `count` is 0: answer `Quiet: nothing pending.` and stop. No commit, no Slack. This is the common case and must stay cheap.

## 1. Analyse (one subagent per release, in parallel)

For each pending item:

```bash
python -m tools.pending brief <report> <ref>
```

Spawn the `domain-analyst` subagent with that JSON packet as its prompt (prefix: "Context packet:"). Run up to 7 in parallel. Each writes `data/inbox/<report>-<ref>.json`.

## 2. Merge

For each inbox file:

```bash
python -m tools.pending apply data/inbox/<report>-<ref>.json
```

If it returns `ok: false`, send the errors back to the same analyst once and apply again. If it still fails, leave the item pending (the next run retries) and mention it in your final answer. Never edit release files yourself.

A `web` report whose release isn't out yet produces no inbox file; leave it pending.

## 3. Render

```bash
python -m tools.render_blackboard
```

## 4. Alert

```bash
python -m tools.pending alerts
```

Post each entry of `messages` as its own message to `channel_id` with the Slack connector's send-message tool. Text verbatim. If the Slack connector isn't attached or the post fails, don't retry in a loop: keep the outbox (skip step 5's `--clear`) and report `WRITE BLOCKED` with the exact texts.

When all posts succeeded:

```bash
python -m tools.pending alerts --clear
```

## 5. Commit

```bash
git add data blackboard
git commit -m "release: <report ref, ...>"
git push origin <branch>
```

If the session assigned a different working branch, push there too, then fast-forward the deployment branch with `git push origin HEAD:<branch>` (standing permission, see CLAUDE.md). The run is not published until `<branch>` has the commit.

If the push is rejected because the Action committed meanwhile: `git pull --rebase origin <branch>` and push again (data files don't overlap). If pushing isn't permitted at all, report `WRITE BLOCKED` and list the files.

## Final answer

Two to five lines: what was analysed, what alerted, anything left pending and why.
