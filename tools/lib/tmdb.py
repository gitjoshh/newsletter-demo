"""TMDB adapter: find a textless scene still (backdrop) for a film.

Returns a hit dict shaped like the ones in lib/images.py so fetch_images.py can
treat all image sources the same way.

Auth: TMDB_API_KEY (v3 key, simplest) or TMDB_READ_TOKEN (v4 bearer). Get one free
at https://www.themoviedb.org/settings/api

Note on rights: TMDB backdrops are studio press/publicity material (© the studio),
used here under editorial/"fair use" custom, not a free licence. Credit goes to
TMDB and the film.
"""
from __future__ import annotations

import os
import re

import requests

TIMEOUT = 20
API = "https://api.themoviedb.org/3"
IMG_BASE = "https://image.tmdb.org/t/p/w1280"

# Diagnostics: find_still appends a one-line reason here when it returns nothing.
ERRORS: list[str] = []


def _note(msg: str) -> None:
    ERRORS.append(f"tmdb: {msg}")


def _auth() -> tuple[dict, dict]:
    """Return (params, headers) for whichever credential is set."""
    token = os.getenv("TMDB_READ_TOKEN")
    if token:
        return {}, {"Authorization": f"Bearer {token}"}
    key = os.getenv("TMDB_API_KEY")
    if key:
        return {"api_key": key}, {}
    return {}, {}


def _enabled() -> bool:
    return bool(os.getenv("TMDB_READ_TOKEN") or os.getenv("TMDB_API_KEY"))


def trending_week(limit: int = 12) -> list[dict]:
    """This week's trending films from TMDB - a clean-JSON stand-in for the
    Letterboxd popular list when that page is behind a Cloudflare challenge.
    Returns [{rank, title, year, slug, url}, ...]; [] if TMDB is unavailable."""
    if not _enabled():
        _note("no TMDB credential for trending fallback")
        return []
    params_auth, headers = _auth()
    try:
        r = requests.get(f"{API}/trending/movie/week", params=params_auth,
                         headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        rows = r.json().get("results", [])
    except (requests.RequestException, ValueError) as e:
        _note(f"trending fetch failed: {e}")
        return []
    out: list[dict] = []
    for m in rows:
        title = m.get("title") or m.get("original_title") or ""
        if not title:
            continue
        rd = str(m.get("release_date") or "")
        out.append({
            "rank": len(out) + 1,
            "title": title,
            "year": int(rd[:4]) if rd[:4].isdigit() else None,
            "slug": None,
            "url": f"https://www.themoviedb.org/movie/{m.get('id')}",
        })
        if len(out) >= limit:
            break
    return out


def _parse_title_year(text: str) -> tuple[str, str | None]:
    m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", text.strip())
    if m:
        return m.group(1).strip(), m.group(2)
    return text.strip(), None


def find_still(title_or_titleyear: str, year: str | None = None) -> dict | None:
    if not _enabled():
        _note("TMDB_API_KEY / TMDB_READ_TOKEN not set")
        return None
    params_auth, headers = _auth()
    title, y2 = _parse_title_year(title_or_titleyear)
    year = year or y2

    try:
        sp = {"query": title, "include_adult": "false", **params_auth}
        if year:
            sp["year"] = year
        r = requests.get(f"{API}/search/movie", params=sp, headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            _note(f"no film match for {title!r}")
            return None
        movie = results[0]
        mid = movie["id"]

        ri = requests.get(
            f"{API}/movie/{mid}/images",
            params={"include_image_language": "en,null", **params_auth},
            headers=headers,
            timeout=TIMEOUT,
        )
        ri.raise_for_status()
        backdrops = ri.json().get("backdrops", [])
    except requests.HTTPError as e:
        _note(f"HTTP {e.response.status_code} for {title!r} ({e.response.text[:120]})")
        return None
    except requests.RequestException as e:
        _note(f"request failed for {title!r} ({type(e).__name__}: {e})")
        return None
    except (ValueError, KeyError) as e:
        _note(f"bad response for {title!r} ({e})")
        return None

    if not backdrops:
        _note(f"no backdrops for {title!r}")
        return None

    # Prefer textless (iso_639_1 is None), then higher rating, then wider.
    backdrops.sort(
        key=lambda b: (
            0 if b.get("iso_639_1") in (None, "null") else 1,
            -(b.get("vote_average") or 0),
            -(b.get("width") or 0),
        )
    )
    chosen = backdrops[0]
    file_path = chosen.get("file_path")
    if not file_path:
        return None

    disp_year = (movie.get("release_date") or "")[:4] or year
    label = f"{movie.get('title', title)}" + (f" ({disp_year})" if disp_year else "")
    movie_url = f"https://www.themoviedb.org/movie/{mid}"
    return {
        "source": "tmdb",
        "query": title_or_titleyear,
        "image_url": IMG_BASE + file_path,
        "page_url": movie_url,
        "photographer": None,
        "photographer_url": None,
        "license": "Editorial use - film still (studio copyright), via TMDB",
        "license_url": "https://www.themoviedb.org/",
        "attribution_html": (
            f'Still from <a href="{movie_url}">{label}</a> &middot; '
            f'image via <a href="https://www.themoviedb.org/">TMDB</a>'
        ),
        "alt": f"Scene still from {label}",
        "download_location": None,
    }
