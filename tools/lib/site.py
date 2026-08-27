"""Static site rendering shared by build_preview.py and publish_site.py.

The generator is deliberately tiny: read content/posts/*.json, render one page
each with the Jinja templates in templates/, plus an index and an RSS feed, into
<repo>/public/. No SSG framework, no front-matter parsing - a post is a JSON
object with Markdown string fields.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markdown_it import MarkdownIt

from lib.common import PROJECT_CONFIG, ROOT, load_json_config

TEMPLATES = ROOT / "templates"
_MD = MarkdownIt("commonmark", {"html": False, "linkify": True, "typographer": False})


def md(text: str | None) -> str:
    return _MD.render(text or "").strip()


def env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def load_style() -> tuple[dict, str]:
    style = load_json_config(PROJECT_CONFIG / "style.json")
    css = env().get_template("_style.css.j2").render(style=style)
    return style, css


def _rfc822(date_iso: str) -> str:
    d = dt.datetime.fromisoformat(date_iso[:10]).replace(tzinfo=dt.timezone.utc)
    return d.strftime("%a, %d %b %Y %H:%M:%S +0000")


def post_context(post_json: dict, resolve_src) -> dict:
    """Turn a stored post JSON into the context the post template expects.

    `resolve_src(image_dict) -> str` decides how an image is referenced
    (relative filename for the site, data: URI for the email preview).
    """
    images = post_json.get("images", [])
    hero_i = post_json.get("hero_index", 0)

    def wire(img: dict | None) -> dict | None:
        if not img:
            return None
        return {
            "src": resolve_src(img),
            "alt": img.get("alt") or "",
            "attribution_html": img.get("attribution_html") or "",
            "filename": img.get("filename"),
        }

    hero_img = next((im for im in images if im.get("role") == "hero"), None)
    if hero_img is None and images:
        hero_img = images[hero_i] if hero_i < len(images) else images[0]
    hero = wire(hero_img)

    blurb_pool = [im for im in images if im.get("role") == "blurb"]
    # positional fallback: any non-hero, non-deepdive image without an explicit role
    if not blurb_pool:
        blurb_pool = [im for im in images if im is not hero_img and im.get("role") != "deepdive"]
    deepdive_img = next((im for im in images if im.get("role") == "deepdive"), None)

    blurbs = []
    for i, b in enumerate(post_json.get("film_blurbs", [])):
        blurbs.append(
            {
                "title": b.get("title", ""),
                "body_html": md(b.get("body_md")),
                "image": wire(blurb_pool[i]) if i < len(blurb_pool) else None,
            }
        )

    dd = post_json.get("horror_deepdive", {})
    return {
        "title": post_json.get("title", ""),
        "subtitle": post_json.get("subtitle", ""),
        "slug": post_json.get("slug", ""),
        "excerpt": post_json.get("excerpt", ""),
        "date": post_json.get("date", ""),
        "tags": post_json.get("tags", []),
        "hero": hero,
        "intro_html": md(post_json.get("intro_md")),
        "blurbs": blurbs,
        "deepdive": {
            "title": dd.get("title", "Horror Corner"),
            "body_html": md(dd.get("body_md")),
            "image": wire(deepdive_img),
        },
        "closing_html": md(post_json.get("closing_md")),
        "sources": post_json.get("sources", []),
    }


def render_post_page(post_ctx: dict, site_cfg: dict, style_css: str) -> str:
    return env().get_template("post.html.j2").render(post=post_ctx, site=site_cfg, style_css=style_css)


def build(repo_path: Path, site_cfg: dict | None = None) -> dict:
    """Render <repo>/content/posts/*.json into <repo>/public/. Returns a summary."""
    site_cfg = site_cfg or load_json_config(PROJECT_CONFIG / "site.json")
    _, style_css = load_style()
    e = env()

    posts_dir = repo_path / site_cfg.get("posts_dir", "content/posts")
    out_dir = repo_path / site_cfg.get("output_dir", "public")
    if not posts_dir.exists():
        raise FileNotFoundError(f"No posts directory at {posts_dir}")

    out_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for pj in sorted(posts_dir.glob("*.json")):
        data = json.loads(pj.read_text(encoding="utf-8"))
        slug = data.get("slug") or pj.stem
        src_img_dir = posts_dir / slug
        dst_post_dir = out_dir / "posts" / slug
        dst_post_dir.mkdir(parents=True, exist_ok=True)
        if src_img_dir.is_dir():
            for f in src_img_dir.iterdir():
                if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                    shutil.copy2(f, dst_post_dir / f.name)

        ctx = post_context(data, resolve_src=lambda img: img.get("filename") or "")
        (dst_post_dir / "index.html").write_text(
            render_post_page(ctx, site_cfg, style_css), encoding="utf-8"
        )
        entries.append(
            {
                "slug": slug,
                "title": data.get("title", slug),
                "excerpt": data.get("excerpt", ""),
                "date": data.get("date", ""),
                "tags": data.get("tags", []),
                "rfc822": _rfc822(data.get("date") or dt.date.today().isoformat()),
            }
        )

    entries.sort(key=lambda p: p["date"], reverse=True)
    build_date = _rfc822(dt.datetime.now(dt.timezone.utc).isoformat())

    (out_dir / "index.html").write_text(
        e.get_template("index.html.j2").render(posts=entries, site=site_cfg, style_css=style_css),
        encoding="utf-8",
    )
    (out_dir / "rss.xml").write_text(
        e.get_template("rss.xml.j2").render(posts=entries, site=site_cfg, build_date=build_date),
        encoding="utf-8",
    )
    return {"posts": len(entries), "output_dir": str(out_dir)}
