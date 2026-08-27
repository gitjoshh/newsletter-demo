"""Stock-photo search adapters: Openverse -> Pexels -> Unsplash.

Each `search_*` returns a normalised dict (a "hit") or None:

    {
      "source": "openverse|pexels|unsplash",
      "query": "<the query>",
      "image_url": "<direct image file URL to download>",
      "page_url": "<human landing page for the photo>",
      "photographer": "<name or None>",
      "photographer_url": "<url or None>",
      "license": "<short label, e.g. 'CC BY 2.0' / 'Pexels License' / 'Unsplash License'>",
      "license_url": "<url or None>",
      "attribution_html": "<ready-to-render credit line>",
      "alt": "<alt text>",
      "download_location": "<Unsplash only: URL to ping on use, else None>",
    }

fetch_images.py tries the sources in order and takes the first hit. Openverse is
first because its results carry explicit, machine-readable reuse licences.
"""
from __future__ import annotations

import os
import html as _html

import requests

TIMEOUT = 20
UA = "run-for-your-life-newsletter/1.0 (+https://letterboxd.com/joshualaurie)"

# Diagnostics: each search_* appends a one-line reason here when it comes back empty.
ERRORS: list[str] = []


def _note(src: str, msg: str) -> None:
    ERRORS.append(f"{src}: {msg}")


def _get(url: str, **kw) -> requests.Response:
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", UA)
    return requests.get(url, headers=headers, timeout=TIMEOUT, **kw)


def _esc(s: str | None) -> str:
    return _html.escape(s or "")


# --------------------------------------------------------------------------- Openverse
_OPENVERSE_TOKEN: str | None = None


def _openverse_token() -> str | None:
    """Optional: exchange client creds for a bearer token (raises rate limits)."""
    global _OPENVERSE_TOKEN
    if _OPENVERSE_TOKEN is not None:
        return _OPENVERSE_TOKEN or None
    cid, secret = os.getenv("OPENVERSE_CLIENT_ID"), os.getenv("OPENVERSE_CLIENT_SECRET")
    if not (cid and secret):
        _OPENVERSE_TOKEN = ""
        return None
    try:
        r = requests.post(
            "https://api.openverse.org/v1/auth_tokens/token/",
            data={"grant_type": "client_credentials", "client_id": cid, "client_secret": secret},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        _OPENVERSE_TOKEN = r.json().get("access_token", "") or ""
    except requests.RequestException:
        _OPENVERSE_TOKEN = ""
    return _OPENVERSE_TOKEN or None


def search_openverse(query: str) -> dict | None:
    headers = {}
    tok = _openverse_token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        r = _get(
            "https://api.openverse.org/v1/images/",
            params={
                "q": query,
                "aspect_ratio": "wide",
                "size": "large",
                "mature": "false",
                "page_size": 8,
            },
            headers=headers,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    except requests.RequestException as e:
        _note("openverse", f"request failed ({type(e).__name__}: {e})")
        return None
    except ValueError as e:
        _note("openverse", f"bad JSON ({e})")
        return None

    if not results:
        _note("openverse", f"0 results for {query!r}")
    for it in results:
        img = it.get("url")
        if not img:
            continue
        lic = it.get("license", "").upper()
        ver = it.get("license_version", "")
        label = f"CC {lic} {ver}".strip() if lic and lic not in ("CC0", "PDM") else (lic or "CC")
        creator = it.get("creator")
        attr = it.get("attribution") or (
            f'"{it.get("title") or query}" by {creator or "Unknown"} '
            f'is licensed under {label}.'
        )
        return {
            "source": "openverse",
            "query": query,
            "image_url": img,
            "page_url": it.get("foreign_landing_url") or it.get("url"),
            "photographer": creator,
            "photographer_url": it.get("creator_url"),
            "license": label,
            "license_url": it.get("license_url"),
            "attribution_html": _esc(attr) if not it.get("attribution") else attr,
            "alt": it.get("title") or query,
            "download_location": None,
        }
    return None


# ----------------------------------------------------------------------------- Pexels
def search_pexels(query: str) -> dict | None:
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        _note("pexels", "PEXELS_API_KEY not set")
        return None
    try:
        r = _get(
            "https://api.pexels.com/v1/search",
            params={"query": query, "orientation": "landscape", "per_page": 5},
            headers={"Authorization": key},
        )
        r.raise_for_status()
        photos = r.json().get("photos", [])
    except requests.HTTPError as e:
        _note("pexels", f"HTTP {e.response.status_code} ({e.response.text[:120]})")
        return None
    except requests.RequestException as e:
        _note("pexels", f"request failed ({type(e).__name__}: {e})")
        return None
    except ValueError as e:
        _note("pexels", f"bad JSON ({e})")
        return None
    if not photos:
        _note("pexels", f"0 results for {query!r}")
        return None
    p = photos[0]
    src = p.get("src", {})
    name = p.get("photographer")
    page = p.get("url")
    return {
        "source": "pexels",
        "query": query,
        "image_url": src.get("large2x") or src.get("large") or src.get("original"),
        "page_url": page,
        "photographer": name,
        "photographer_url": p.get("photographer_url"),
        "license": "Pexels License",
        "license_url": "https://www.pexels.com/license/",
        "attribution_html": f'Photo by <a href="{_esc(p.get("photographer_url"))}">{_esc(name)}</a> on '
        f'<a href="{_esc(page)}">Pexels</a>',
        "alt": p.get("alt") or query,
        "download_location": None,
    }


# --------------------------------------------------------------------------- Unsplash
def search_unsplash(query: str) -> dict | None:
    key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not key:
        _note("unsplash", "UNSPLASH_ACCESS_KEY not set")
        return None
    try:
        r = _get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "orientation": "landscape", "per_page": 5},
            headers={"Authorization": f"Client-ID {key}"},
        )
        r.raise_for_status()
        results = r.json().get("results", [])
    except requests.HTTPError as e:
        _note("unsplash", f"HTTP {e.response.status_code} ({e.response.text[:120]})")
        return None
    except requests.RequestException as e:
        _note("unsplash", f"request failed ({type(e).__name__}: {e})")
        return None
    except ValueError as e:
        _note("unsplash", f"bad JSON ({e})")
        return None
    if not results:
        _note("unsplash", f"0 results for {query!r}")
        return None
    p = results[0]
    urls, links, user = p.get("urls", {}), p.get("links", {}), p.get("user", {})
    uname = user.get("name")
    uhtml = (user.get("links", {}) or {}).get("html")
    photo_html = links.get("html")
    return {
        "source": "unsplash",
        "query": query,
        "image_url": urls.get("regular") or urls.get("full") or urls.get("raw"),
        "page_url": photo_html,
        "photographer": uname,
        "photographer_url": uhtml,
        "license": "Unsplash License",
        "license_url": "https://unsplash.com/license",
        "attribution_html": f'Photo by <a href="{_esc(uhtml)}?utm_source=run_for_your_life&utm_medium=referral">'
        f"{_esc(uname)}</a> on "
        f'<a href="https://unsplash.com/?utm_source=run_for_your_life&utm_medium=referral">Unsplash</a>',
        "alt": p.get("description") or p.get("alt_description") or query,
        "download_location": links.get("download_location"),
    }


SOURCES = [search_openverse, search_pexels, search_unsplash]


def ping_unsplash_download(download_location: str) -> None:
    """Unsplash ToS: trigger a download event when a photo is actually used."""
    key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not (download_location and key):
        return
    try:
        _get(download_location, headers={"Authorization": f"Client-ID {key}"})
    except requests.RequestException:
        pass


def find_image(query: str, order=None) -> dict | None:
    """Try each source in order; return the first hit."""
    for fn in order or SOURCES:
        hit = fn(query)
        if hit and hit.get("image_url"):
            return hit
    return None
