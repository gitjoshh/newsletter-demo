"""Persist state/ back to the git repo so the next scheduled cloud run sees it.

state/ is gitignored for local use, but a cloud routine gets a fresh checkout each
run, so the approval-tracking files must be committed. This force-adds the small
tracker files plus any in-flight per-issue directories, commits, and pushes.

  python tools/state_sync.py -m "issue <id>: awaiting approval"
  python tools/state_sync.py -m "issue <id>: done" --done <issue_id>

--done also removes that issue's working directory (it is no longer needed once
published, and keeps the repo small).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from lib.common import ROOT, STATE, emit, fail, load_json_config, PROJECT_CONFIG


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if check and cp.returncode != 0:
        fail(f"git {' '.join(args)} failed: {cp.stderr.strip() or cp.stdout.strip()}")
    return cp


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-m", "--message", required=True, help="commit message")
    ap.add_argument("--done", default=None, help="issue id whose working dir to drop")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()

    cfg = load_json_config(PROJECT_CONFIG / "site.json")
    name = cfg.get("commit_author_name", "newsletter-bot")
    mail = cfg.get("commit_author_email", "bot@example.com")

    if args.done:
        d = STATE / "issues" / args.done
        git("rm", "-r", "--cached", "--ignore-unmatch", f"state/issues/{args.done}", check=False)
        if d.is_dir():
            shutil.rmtree(d)

    for f in ("state/issues.json", "state/last_processed.json"):
        if (ROOT / f).exists():
            git("add", "-f", f)
    if (STATE / "issues").is_dir():
        git("add", "-f", "state/issues")

    staged = git("status", "--porcelain").stdout.strip()
    if not staged:
        emit({"status": "ok", "committed": False, "note": "nothing to sync"})
        return

    git("-c", f"user.name={name}", "-c", f"user.email={mail}", "commit", "-m", args.message)
    pushed = False
    push_note = None
    if not args.no_push:
        branch = cfg.get("git_branch", "main")
        # Push HEAD explicitly so this works even in a detached-HEAD checkout.
        cp = git("push", "origin", f"HEAD:refs/heads/{branch}", check=False)
        pushed = cp.returncode == 0
        if not pushed:
            push_note = (cp.stderr.strip() or cp.stdout.strip())[:400]

    emit({"status": "ok", "committed": True, "pushed": pushed, "push_note": push_note, "message": args.message})


if __name__ == "__main__":
    main()
