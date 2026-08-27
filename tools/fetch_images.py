"""Fetch images for the week's post.

Hybrid sourcing:
  - hero  : a TMDB scene still for the horror deep-dive film
  - blurb : a TMDB scene still per film blurb (skipped if TMDB has none)
  - mood  : 1+ cleanly-licensed stock photos (Openverse -> Pexels -> Unsplash)
            for the running / endurance deep-dive, from draft.image_queries

Writes images.json. The teaser photo is a stock/CC image where possible (safer to
post to Facebook than a studio still), else the hero.
"""
from __future__ import annotations

import argparse
import io
import json
import re
from pathlib import Path

import requests

from lib.common import emit, fail, load_env, tmp_path
from lib import images as images_mod
from lib import tmdb as tmdb_mod
from lib.images import find_image, ping_unsplash_download
from lib.tmdb import find_still


def _source_errors() -> list[str]:
    """De-duplicated diagnostics collected by the image adapters this run."""
    seen: dict[str, None] = {}
    for e in tmdb_mod.ERRORS + images_mod.ERRORS:
        seen.setdefault(e, None)
    return list(seen)

MAX_WIDTH = 1600
UA = "run-for-your-life-newsletter/1.0"


def slugify(text: str, n: int = 48) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:n] or "img"


def download_and_normalise(url: str, dest: Path) -> dict:
    from PIL import Image

    r = requests.get(url, timeout=30, headers={"User-Agent": UA})
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content)).convert("RGB")
    if im.width > MAX_WIDTH:
        im = im.resize((MAX_WIDTH, round(im.height * MAX_WIDTH / im.width)))
    dest = dest.with_suffix(".jpg")
    im.save(dest, "JPEG", quality=85, optimize=True)
    return {"width": im.width, "height": im.height, "bytes": dest.stat().st_size}


def record(hit: dict, role: str, kind: str, dest: Path, meta: dict, for_: str | None = None) -> dict:
    return {
        "role": role,
        "kind": kind,
        "for": for_,
        "query": hit.get("query"),
        "local_path": str(dest.with_suffix(".jpg")),
        "filename": dest.with_suffix(".jpg").name,
        "source": hit["source"],
        "page_url": hit.get("page_url"),
        "photographer": hit.get("photographer"),
        "photographer_url": hit.get("photographer_url"),
        "license": hit.get("license"),
        "license_url": hit.get("license_url"),
        "attribution_html": hit.get("attribution_html"),
        "alt": hit.get("alt"),
        **meta,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True, help="Path to draft.json")
    ap.add_argument("--horror", default=None, help="Path to horror_angle.json (for the hero still)")
    ap.add_argument("--mood-count", type=int, default=1, help="Stock photos for the deep-dive")
    ap.add_argument("--no-tmdb", action="store_true", help="Skip TMDB, use stock only")
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    load_env()
    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    horror = json.loads(Path(args.horror).read_text(encoding="utf-8")) if args.horror else {}
    mood_queries = draft.get("image_queries", [])
    blurbs = draft.get("film_blurbs", [])

    out_dir = Path(args.out_dir) if args.out_dir else tmp_path("images")
    out_dir.mkdir(parents=True, exist_ok=True)

    images: list[dict] = []
    warnings: list[str] = []
    seen_pages: set[str] = set()

    def take(hit, role, kind, name, for_=None) -> bool:
        if not hit or not hit.get("image_url"):
            return False
        if hit.get("page_url") and hit["page_url"] in seen_pages:
            return False
        dest = out_dir / f"{len(images):02d}-{slugify(name)}"
        try:
            meta = download_and_normalise(hit["image_url"], dest)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"download failed ({role}, {hit['source']}, {name!r}): {e}")
            return False
        if hit["source"] == "unsplash" and hit.get("download_location"):
            ping_unsplash_download(hit["download_location"])
        if hit.get("page_url"):
            seen_pages.add(hit["page_url"])
        images.append(record(hit, role, kind, dest, meta, for_))
        return True

    # 1) hero - TMDB still for the deep-dive film, else first stock mood phrase
    hero_done = False
    if not args.no_tmdb and horror.get("film"):
        hero_done = take(
            find_still(horror["film"], str(horror.get("year") or "") or None),
            "hero", "still", f"hero-{horror['film']}",
        )
    if not hero_done and mood_queries:
        hero_done = take(find_image(mood_queries[0]), "hero", "stock", f"hero-{mood_queries[0]}")
    if not hero_done:
        warnings.append("no hero image could be sourced")

    # 2) one TMDB still per film blurb
    for b in blurbs:
        title = b.get("title", "")
        if not title:
            continue
        if args.no_tmdb:
            break
        if not take(find_still(title), "blurb", "still", title, for_=title):
            warnings.append(f"no TMDB still for blurb: {title!r}")

    # 3) stock mood photo(s) for the deep-dive
    mood_taken = 0
    for q in mood_queries:
        if mood_taken >= max(0, args.mood_count):
            break
        if take(find_image(q), "deepdive", "stock", f"mood-{q}"):
            mood_taken += 1
    if mood_queries and mood_taken == 0:
        warnings.append("no stock mood photo found for the deep-dive")

    if not images:
        diag = _source_errors()
        detail = "\n  - " + "\n  - ".join(diag) if diag else " (no diagnostics captured)"
        fail("Could not source any images. Per-source reasons:" + detail)

    hero_index = next((i for i, im in enumerate(images) if im["role"] == "hero"), 0)
    teaser_index = next(
        (i for i, im in enumerate(images) if im["kind"] == "stock"), hero_index
    )

    manifest = {
        "images": images,
        "hero_index": hero_index,
        "teaser_index": teaser_index,
        "warnings": warnings,
    }
    out_path = Path(args.out) if args.out else tmp_path("images.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "fetched": len(images),
            "by_role": {r: sum(1 for i in images if i["role"] == r) for r in {i["role"] for i in images}},
            "by_source": {s: sum(1 for i in images if i["source"] == s) for s in {i["source"] for i in images}},
            "teaser_is_stock": images[teaser_index]["kind"] == "stock",
            "warnings": warnings,
            "source_notes": _source_errors(),
        }
    )


if __name__ == "__main__":
    main()
