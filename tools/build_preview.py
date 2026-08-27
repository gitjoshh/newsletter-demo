"""Render a standalone preview.html for the approval email.

draft.json + images.json -> a single self-contained HTML file (images embedded as
data: URIs so it renders inside an email). Uses the same templates and CSS as the
live site, so what Josh approves is what publishes.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import mimetypes
from pathlib import Path

from lib.common import emit, fail, load_json_config, PROJECT_CONFIG, tmp_path
from lib.site import load_style, post_context, render_post_page


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--out", default=None, help="Where to write preview.html (default .tmp/)")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    images = json.loads(Path(args.images).read_text(encoding="utf-8"))
    site_cfg = load_json_config(PROJECT_CONFIG / "site.json")
    _, style_css = load_style()

    post = assemble_post(draft, images)
    ctx = post_context(post, resolve_src=lambda img: data_uri(img.get("local_path", "")))
    htmldoc = render_post_page(ctx, site_cfg, style_css)

    out_path = Path(args.out) if args.out else tmp_path("preview.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(htmldoc, encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "bytes": out_path.stat().st_size,
            "title": draft.get("title"),
        }
    )


if __name__ == "__main__":
    main()
