"""Render the "ready to post" email after the post is live.

teaser.json + images.json + --url -> ready_email.html, the finalised teaser text
(with the real URL substituted for {url}), and the path of the photo the routine
should attach to the email.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import emit, fail, load_json_config, PROJECT_CONFIG, tmp_path
from lib.site import env, load_style


def teaser_text(teaser: dict, url: str) -> str:
    cta = teaser.get("cta", "").replace("{url}", url).strip()
    return "\n\n".join(x for x in (teaser.get("para1", "").strip(), teaser.get("para2", "").strip(), cta) if x)


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
    htmldoc = env().get_template("ready_email.html.j2").render(
        site=site_cfg,
        style_css=style_css,
        post_title=args.title or teaser.get("_title") or "This week's issue",
        post_url=args.url,
        teaser_text=text,
        teaser_image={
            "src": Path(t_img["local_path"]).name,
            "alt": t_img.get("alt", ""),
            "filename": Path(t_img["local_path"]).name,
            "attribution_html": t_img.get("attribution_html", ""),
        }
        if t_img
        else None,
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
            "attach_image": t_img["local_path"] if t_img else None,
        }
    )


if __name__ == "__main__":
    main()
