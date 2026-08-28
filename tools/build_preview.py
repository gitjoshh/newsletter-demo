"""Render the draft preview for the approval email.

Emits TWO files:
  --out       preview.html        full standalone page, images embedded as data:
                                  URIs. This is what gets ATTACHED to the email
                                  (open in a browser) and mirrors the live post.
  --email-out preview_email.html  lightweight, text-only, no images, small enough
                                  that Gmail will not clip it. This is the email
                                  BODY. Needs --teaser for the teaser block.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import mimetypes
from pathlib import Path

from lib.common import emit, load_json_config, PROJECT_CONFIG, tmp_path
from lib.site import env, load_style, post_context, render_post_page


def data_uri(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


def assemble_post(draft: dict, images: dict) -> dict:
    post = dict(draft)
    post["date"] = dt.date.today().isoformat()
    post["images"] = images.get("images", [])
    post["hero_index"] = images.get("hero_index", 0)
    return post


def teaser_block(teaser: dict) -> str:
    parts = [teaser.get("para1", ""), teaser.get("para2", ""), teaser.get("cta", "")]
    return "\n\n".join(p.strip() for p in parts if p.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--teaser", default=None, help="teaser.json (for the email body's teaser block)")
    ap.add_argument("--out", default=None, help="full preview.html (default .tmp/preview.html)")
    ap.add_argument("--email-out", default=None, help="lightweight body (default alongside --out)")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    images = json.loads(Path(args.images).read_text(encoding="utf-8"))
    site_cfg = load_json_config(PROJECT_CONFIG / "site.json")
    _, style_css = load_style()

    post = assemble_post(draft, images)

    # 1) full standalone page (data-URI images) -> attachment
    full_ctx = post_context(post, resolve_src=lambda img: data_uri(img.get("local_path", "")))
    full_html = render_post_page(full_ctx, site_cfg, style_css)
    out_path = Path(args.out) if args.out else tmp_path("preview.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(full_html, encoding="utf-8")

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
        warnings=images.get("warnings", []),
        interpretation=bool(json.loads(Path(args.draft).read_text(encoding="utf-8")).get("_interpretation")),
        image_list=image_list,
    )
    email_out = Path(args.email_out) if args.email_out else out_path.with_name("preview_email.html")
    email_out.write_text(email_html, encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "email_out": str(email_out),
            "full_bytes": out_path.stat().st_size,
            "email_bytes": email_out.stat().st_size,
            "title": draft.get("title"),
        }
    )


if __name__ == "__main__":
    main()
