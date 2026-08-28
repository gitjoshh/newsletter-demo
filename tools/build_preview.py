"""Render the draft preview for the approval email.

Emits:
  --out       preview.html        full standalone page, images embedded as data: URIs.
  --email-out preview_email.html  lightweight text-only email BODY (Gmail won't clip it).
  --deploy-preview                also push preview.html to draft.<project>.pages.dev so
                                  the email can LINK the styled draft (Gmail attachments
                                  via the connector are unreliable).
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import mimetypes
import re
import shutil
import subprocess
from pathlib import Path

from lib.common import emit, load_json_config, PROJECT_CONFIG, tmp_path
from lib.site import env, load_style, post_context, render_post_page


def deploy_preview(preview_html: Path, project: str) -> str | None:
    """Serve the self-contained preview.html at draft.<project>.pages.dev."""
    stage = tmp_path("draft_preview")
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copy2(preview_html, stage / "index.html")
    cp = subprocess.run(
        ["npx", "--yes", "wrangler", "pages", "deploy", str(stage),
         "--project-name", project, "--branch", "draft", "--commit-dirty=true"],
        capture_output=True, text=True,
    )
    urls = re.findall(r"https://[a-z0-9.\-]+\.pages\.dev\S*", cp.stdout + "\n" + cp.stderr)
    for u in urls:
        if u.startswith("https://draft."):
            return u
    return urls[-1] if urls else None


def resolve_image(img: dict, images_dir: Path) -> Path | None:
    """local_path can be stale after the issue dir is renamed - also look next to images.json."""
    fname = img.get("filename") or Path(img.get("local_path", "")).name
    for cand in (
        Path(img.get("local_path", "")),
        images_dir / "images" / fname,
        images_dir / fname,
    ):
        if fname and cand.is_file():
            return cand
    return None


def data_uri(path: Path | None) -> str:
    if not path or not path.is_file():
        return ""
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def assemble_post(draft: dict, images: dict) -> dict:
    post = dict(draft)
    post["date"] = dt.date.today().isoformat()
    post["images"] = images.get("images", [])
    post["hero_index"] = images.get("hero_index", 0)
    return post


def teaser_block(teaser: dict) -> str:
    b = teaser.get("blog", teaser)  # tolerate old flat shape
    parts = [b.get("para1", ""), b.get("para2", ""), b.get("cta", "")]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def film_blocks(teaser: dict, link_line: str) -> list[dict]:
    """Assemble each film post: hook + lifted excerpt + link line."""
    out = []
    for f in teaser.get("films", []):
        parts = [f.get("hook", "").strip(), f.get("excerpt", "").strip(), link_line]
        out.append({"title": f.get("title", ""), "text": "\n\n".join(p for p in parts if p)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--teaser", default=None, help="teaser.json (for the email body's teaser block)")
    ap.add_argument("--out", default=None, help="full preview.html (default .tmp/preview.html)")
    ap.add_argument("--email-out", default=None, help="lightweight body (default alongside --out)")
    ap.add_argument("--deploy-preview", action="store_true", help="serve preview at draft.<project>.pages.dev")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    images_dir = Path(args.images).parent
    images = json.loads(Path(args.images).read_text(encoding="utf-8"))
    site_cfg = load_json_config(PROJECT_CONFIG / "site.json")
    _, style_css = load_style()

    post = assemble_post(draft, images)

    # 1) full standalone page (data-URI images) -> attachment
    full_ctx = post_context(post, resolve_src=lambda img: data_uri(resolve_image(img, images_dir)))
    full_html = render_post_page(full_ctx, site_cfg, style_css)
    out_path = Path(args.out) if args.out else tmp_path("preview.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_html, encoding="utf-8")

    # 1b) optionally serve it so the email can link the styled draft
    preview_url = None
    if args.deploy_preview:
        preview_url = deploy_preview(out_path, site_cfg.get("cf_project", "run-for-your-life"))

    # 2) lightweight text-only body (no images) -> email body
    light_post = dict(post)
    light_post["images"] = []  # drop all figures
    light_ctx = post_context(light_post, resolve_src=lambda _img: "")
    teaser = json.loads(Path(args.teaser).read_text(encoding="utf-8")) if args.teaser else {}
    image_list = [
        (im.get("for") or im.get("alt") or im.get("filename") or "image")
        for im in images.get("images", [])
    ]
    email_html = env().get_template("preview_email.html.j2").render(
        post=light_ctx,
        teaser_text=teaser_block(teaser),
        film_posts=film_blocks(teaser, "(the post link is added when this publishes)"),
        warnings=images.get("warnings", []),
        interpretation=bool(draft.get("_interpretation")),
        image_list=image_list,
        questions=draft.get("questions", []),
        preview_url=preview_url,
    )
    email_out = Path(args.email_out) if args.email_out else out_path.with_name("preview_email.html")
    email_out.write_text(email_html, encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "email_out": str(email_out),
            "preview_url": preview_url,
            "full_bytes": out_path.stat().st_size,
            "email_bytes": email_out.stat().st_size,
            "title": draft.get("title"),
        }
    )


if __name__ == "__main__":
    main()
