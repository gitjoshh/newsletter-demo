"""Render the "ready to post" email after the post is live.

teaser.json + images.json + --url -> ready_email.html + the finalised teaser text.
The teaser photo is referenced by its live CDN URL (it ships with the post), shown
inline and linked for one-tap save - nothing is attached to the email.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import emit, fail, load_json_config, PROJECT_CONFIG, tmp_path
from lib.site import env, load_style


def teaser_text(teaser: dict, url: str) -> str:
    b = teaser.get("blog", teaser)  # tolerate old flat shape
    cta = b.get("cta", "").replace("{url}", url).strip()
    return "\n\n".join(x for x in (b.get("para1", "").strip(), b.get("para2", "").strip(), cta) if x)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--teaser", required=True)
    ap.add_argument("--images", required=True)
    ap.add_argument("--url", required=True, help="Live post URL")
    ap.add_argument("--title", default=None, help="Post title (for the email heading)")
    ap.add_argument("--out", default=None, help="Where to write ready_email.html (default .tmp/)")
    args = ap.parse_args()

    teaser = json.loads(Path(args.teaser).read_text(encoding="utf-8"))
    images = json.loads(Path(args.images).read_text(encoding="utf-8"))
    site_cfg = load_json_config(PROJECT_CONFIG / "site.json")
    _, style_css = load_style()

    imgs = images.get("images", [])
    t_idx = images.get("teaser_index", 0)
    t_img = imgs[t_idx] if 0 <= t_idx < len(imgs) else (imgs[0] if imgs else None)

    text = teaser_text(teaser, args.url)
    teaser_image = None
    image_cdn_url = None
    if t_img:
        fname = t_img.get("filename") or Path(t_img.get("local_path", "img.jpg")).name
        image_cdn_url = args.url.rstrip("/") + "/" + fname  # ships alongside the post
        teaser_image = {
            "src": image_cdn_url,
            "url": image_cdn_url,
            "alt": t_img.get("alt", ""),
            "filename": fname,
            "attribution_html": t_img.get("attribution_html", ""),
        }

    htmldoc = env().get_template("ready_email.html.j2").render(
        site=site_cfg,
        style_css=style_css,
        post_title=args.title or teaser.get("_title") or "This week's issue",
        post_url=args.url,
        teaser_text=text,
        film_posts=teaser.get("films", []),
        teaser_image=teaser_image,
    )

    out_path = Path(args.out) if args.out else tmp_path("ready_email.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(htmldoc, encoding="utf-8")

    txt_path = out_path.with_name("teaser_final.txt")
    txt_path.write_text(text, encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "teaser_text_file": str(txt_path),
            "teaser_text": text,
            "teaser_image_url": image_cdn_url,
        }
    )


if __name__ == "__main__":
    main()
