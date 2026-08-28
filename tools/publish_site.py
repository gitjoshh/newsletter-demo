"""Publish the approved post to the static site.

Writes content/posts/<slug>.json + content/posts/<slug>/<images> into the site
folder ($SITE_REPO_PATH), regenerates public/ with the tiny generator, optionally
commits (local history / rollback), then deploys public/ to Cloudflare Pages.

  --deploy wrangler   run `npx wrangler pages deploy public/` (needs Node + a
                      Cloudflare login or CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID)
  --deploy none       (default) build only, no deploy

Git is used only if the site folder is a git repo; it is never required. Re-running
for the same slug updates that post (no duplicate).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from lib.common import emit, fail, load_env, load_json_config, PROJECT_CONFIG, ROOT
from lib.site import build

IMAGE_KEYS = (
    "filename", "alt", "attribution_html", "source", "page_url",
    "license", "license_url", "role", "kind", "for",
)


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if check and cp.returncode != 0:
        fail(f"{' '.join(cmd[:3])} ... failed: {cp.stderr.strip() or cp.stdout.strip()}")
    return cp


def is_git_repo(path: Path) -> bool:
    """True only if `path` is itself a repo root - not merely nested inside one
    (e.g. a folder under ~/ where a stray ~/.git exists)."""
    if not (path / ".git").exists():
        return False
    cp = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    return cp.returncode == 0 and Path(cp.stdout.strip()).resolve() == path.resolve()


def deploy_wrangler(public_dir: Path, project: str, branch: str) -> dict:
    cmd = [
        "npx", "--yes", "wrangler", "pages", "deploy", str(public_dir),
        "--project-name", project, "--branch", branch, "--commit-dirty=true",
    ]
    cp = run(cmd, check=False)
    out = cp.stdout + "\n" + cp.stderr
    urls = re.findall(r"https://[a-z0-9.\-]+\.pages\.dev\S*", out)
    if cp.returncode != 0:
        fail(f"wrangler pages deploy failed:\n{out.strip()[-1500:]}")
    return {"deploy_url": urls[-1] if urls else None, "all_urls": sorted(set(urls))}


def git_push_current(repo: Path, branch: str) -> tuple[bool, str]:
    """Push whatever HEAD is (works in detached HEAD too) to origin/<branch>.
    Non-fatal: returns (ok, message)."""
    cp = run(
        ["git", "-C", str(repo), "push", "origin", f"HEAD:refs/heads/{branch}"],
        check=False,
    )
    if cp.returncode == 0:
        return True, "pushed"
    return False, (cp.stderr.strip() or cp.stdout.strip())[:400]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--teaser", default=None, help="teaser.json to archive alongside the post")
    ap.add_argument("--repo", default=None, help="Site folder (default $SITE_REPO_PATH, else the project root)")
    ap.add_argument("--date", default=None, help="Publish date YYYY-MM-DD (default today)")
    ap.add_argument("--deploy", choices=["wrangler", "none"], default="none")
    ap.add_argument("--no-git", action="store_true", help="Skip the local commit even if it is a repo")
    ap.add_argument("--push", action="store_true", help="After committing, push content/ to origin (cloud routine)")
    args = ap.parse_args()

    load_env()
    repo = Path(args.repo or os.getenv("SITE_REPO_PATH") or ROOT).expanduser()
    if not repo.is_dir():
        fail(f"Site folder does not exist: {repo}")

    site_cfg = load_json_config(PROJECT_CONFIG / "site.json")
    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    images_path = Path(args.images)
    images = json.loads(images_path.read_text(encoding="utf-8"))

    slug = draft.get("slug")
    if not slug:
        fail("draft.json has no slug")
    date = args.date or dt.date.today().isoformat()

    posts_dir = repo / site_cfg.get("posts_dir", "content/posts")
    img_dir = posts_dir / slug
    posts_dir.mkdir(parents=True, exist_ok=True)
    img_dir.mkdir(parents=True, exist_ok=True)

    def resolve_image(img: dict) -> Path | None:
        """Find the image file. local_path can be stale (issue dir was renamed
        after fetch_images ran), so also look next to images.json."""
        fname = img.get("filename") or Path(img.get("local_path", "")).name
        for cand in (
            Path(img.get("local_path", "")),
            images_path.parent / "images" / fname,
            images_path.parent / fname,
        ):
            if fname and cand.is_file():
                return cand
        return None

    stored_images = []
    missing = []
    for img in images.get("images", []):
        src = resolve_image(img)
        if src:
            shutil.copy2(src, img_dir / (img.get("filename") or src.name))
        else:
            missing.append(img.get("filename") or img.get("local_path"))
        stored_images.append({k: img.get(k) for k in IMAGE_KEYS})
    if missing:
        fail(f"Image file(s) not found (looked next to {images_path}): {missing}")

    post = {
        "slug": slug,
        "date": date,
        "title": draft.get("title"),
        "subtitle": draft.get("subtitle"),
        "excerpt": draft.get("excerpt"),
        "tags": draft.get("tags", []),
        "intro_md": draft.get("intro_md"),
        "film_blurbs": draft.get("film_blurbs", []),
        "horror_deepdive": draft.get("horror_deepdive", {}),
        "closing_md": draft.get("closing_md"),
        "sources": draft.get("sources", []),
        "images": stored_images,
        "hero_index": images.get("hero_index", 0),
    }
    is_update = (posts_dir / f"{slug}.json").exists()
    (posts_dir / f"{slug}.json").write_text(json.dumps(post, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.teaser and Path(args.teaser).exists():
        shutil.copy2(args.teaser, img_dir / "teaser.json")

    summary = build(repo, site_cfg)
    base_url = site_cfg.get("base_url", "").rstrip("/")
    post_url = f"{base_url}/posts/{slug}/"
    branch = site_cfg.get("git_branch", "main")

    # 1) DEPLOY FIRST - this is what makes the post live. Do it before touching git
    #    so a git hiccup can never block publication.
    deploy: dict = {}
    if args.deploy == "wrangler":
        deploy = deploy_wrangler(
            repo / site_cfg.get("output_dir", "public"),
            site_cfg.get("cf_project", "run-for-your-life"),
            branch,
        )

    # 2) Persist content back to git. Push failure is a warning, not fatal - the
    #    post is already live and the next run can re-push.
    committed = pushed = False
    push_note = None
    if not args.no_git and is_git_repo(repo):
        name = site_cfg.get("commit_author_name", "run-for-your-life-bot")
        mail = site_cfg.get("commit_author_email", "bot@example.com")
        posts_rel = site_cfg.get("posts_dir", "content/posts").split("/")[0]  # e.g. "content"
        run(["git", "-C", str(repo), "add", "-A", "--", posts_rel])
        dirty = run(["git", "-C", str(repo), "status", "--porcelain", "--", posts_rel]).stdout.strip()
        if dirty:
            verb = "Update" if is_update else "Publish"
            run([
                "git", "-C", str(repo),
                "-c", f"user.name={name}", "-c", f"user.email={mail}",
                "commit", "-m", f"{verb}: {draft.get('title')} ({slug})",
            ])
            committed = True
        if args.push and committed:
            pushed, push_note = git_push_current(repo, branch)

    emit(
        {
            "status": "ok",
            "post_url": post_url,
            "slug": slug,
            "updated_existing": is_update,
            "committed": committed,
            "pushed": pushed,
            "push_note": push_note,
            "deploy": deploy or None,
            "site": summary,
        }
    )


if __name__ == "__main__":
    main()
