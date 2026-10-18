"""Mirror the built site into the shared GitHub Pages repo and commit it.

    python -m tools.publish_pages [--pages-dir PATH] [--message MSG]

Reads `pages` from config/deployment.json: docs/<slug>/ here is copied to
<pages repo>/<dir>/<slug>/ (stale files there are removed; nothing outside the
slug folder is touched). The checkout is --pages-dir, else ../<repo> next to
this repo, else a fresh clone of github.com/<owner>/<repo> on <branch>.
Commits only when something changed. Pushing is left to the caller (see the
macro-strategist skill), so the push rules stay in one place.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from collectors import common as C
from tools import build_site


def cfg():
    p = C.deployment().get("pages")
    if not p or not p.get("repo") or "YOUR_" in json.dumps(p):
        raise SystemExit("config/deployment.json has no usable `pages` block")
    return {"dir": "docs", "branch": "main", **p}


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], check=check, capture_output=True, text=True)


def checkout(p, pages_dir=None):
    repo = Path(pages_dir) if pages_dir else C.ROOT.parent / p["repo"]
    if (repo / ".git").exists():
        return repo
    if pages_dir:
        raise SystemExit(f"{repo} is not a git checkout")
    url = f"https://github.com/{p['owner']}/{p['repo']}.git"
    subprocess.run(["git", "clone", "--branch", p["branch"], url, str(repo)], check=True)
    return repo


def publish(pages_dir=None, message=None, src=None):
    p = cfg()
    src = Path(src) if src else build_site.SITE
    if not (src / "index.html").exists():
        raise SystemExit(f"{src} has no index.html; run python -m tools.build_site first")
    repo = checkout(p, pages_dir)
    rel = Path(p["dir"]) / p["slug"]
    dest = repo / rel
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
    git(repo, "add", "-A", "--", str(rel))
    if git(repo, "diff", "--cached", "--quiet", "--", str(rel), check=False).returncode == 0:
        return {"repo": str(repo), "path": str(rel), "committed": False}
    git(repo, "commit", "-m", message or f"{p['slug']}: publish site", "--", str(rel))
    sha = git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    return {"repo": str(repo), "path": str(rel), "committed": True, "commit": sha, "branch": p["branch"]}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages-dir")
    ap.add_argument("--message")
    a = ap.parse_args(argv)
    print(json.dumps(publish(a.pages_dir, a.message), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
