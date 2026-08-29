"""Monday heads-up: scrape Letterboxd's live "popular this week" film ranking.

The Wednesday-night Rushes email is just this ranking, packaged. Pulling it on
Monday gives Josh two or three days to actually watch something before the digest
lands, so his takes come from real viewing.

The list HTML is server-rendered behind a CSI (component) endpoint, not on the
page shell:  /csi/films/films-browser-list/popular/this/week/
Each film carries  data-item-name="Title (Year)"  and  data-item-link="/film/<slug>/".

Output: heads_up.json  {films:[{rank,title,year,slug,url}], ...}
With --email-out, also renders the Monday email body from heads_up_email.html.j2.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import shutil
import subprocess
from pathlib import Path

from lib.common import PROJECT_CONFIG, emit, fail, load_json_config, tmp_path
from lib.site import env, load_style

CSI_URL = "https://letterboxd.com/csi/films/films-browser-list/popular/this/week/?esiAllowFilters=true"
# Letterboxd's CSI endpoints 403 a bare bot UA; a normal browser UA + Referer is fine.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://letterboxd.com/films/popular/this/week/",
    "X-Requested-With": "XMLHttpRequest",
}

_PAIR = re.compile(
    r'data-item-name="(?P<name>[^"]+)"[^>]*?data-item-link="(?P<link>/film/[^"]+/)"'
)
_TITLE_YEAR = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)\s*$")


def _fetch(url: str) -> str:
    """Letterboxd sits behind Cloudflare, which fingerprints and 403s Python's
    TLS stack ("Just a moment..."). curl gets through, so use it."""
    curl = shutil.which("curl")
    if not curl:
        fail("curl not found on PATH (needed - Cloudflare blocks the Python HTTP client)")
    cp = subprocess.run(
        [curl, "-sS", "--compressed", "--max-time", "25",
         "-A", UA, "-H", f"Referer: {HEADERS['Referer']}",
         "-H", f"Accept: {HEADERS['Accept']}", url],
        capture_output=True, text=True,
    )
    if cp.returncode != 0:
        fail(f"curl failed ({cp.returncode}): {cp.stderr.strip()[:300]}")
    if "Just a moment" in cp.stdout[:2000] or "cf-browser-verification" in cp.stdout[:4000]:
        fail("Letterboxd returned a Cloudflare challenge page instead of the film list")
    return cp.stdout


def scrape(limit: int) -> list[dict]:
    text = _fetch(CSI_URL)
    films: list[dict] = []
    seen: set[str] = set()
    for m in _PAIR.finditer(text):
        name = _html.unescape(m.group("name")).strip()
        link = m.group("link")
        if link in seen:
            continue
        seen.add(link)
        ty = _TITLE_YEAR.match(name)
        films.append(
            {
                "rank": len(films) + 1,
                "title": ty.group("title").strip() if ty else name,
                "year": int(ty.group("year")) if ty else None,
                "slug": link.strip("/").split("/")[-1],
                "url": "https://letterboxd.com" + link,
            }
        )
        if len(films) >= limit:
            break
    if not films:
        fail("Parsed zero films from the Letterboxd CSI fragment (markup may have changed)")
    return films


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=12, help="How many films to keep (default 12)")
    ap.add_argument("--out", default=None, help="Where to write heads_up.json (default .tmp/)")
    ap.add_argument("--email-out", default=None, help="Also render the Monday email body here")
    args = ap.parse_args()

    films = scrape(args.limit)
    payload = {"status": "ok", "source": "letterboxd popular/this/week", "count": len(films), "films": films}

    out_path = Path(args.out) if args.out else tmp_path("heads_up.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["out"] = str(out_path)

    if args.email_out:
        site_cfg = load_json_config(PROJECT_CONFIG / "site.json")
        _, style_css = load_style()
        body = env().get_template("heads_up_email.html.j2").render(
            site=site_cfg, style_css=style_css, films=films
        )
        email_out = Path(args.email_out)
        email_out.parent.mkdir(parents=True, exist_ok=True)
        email_out.write_text(body, encoding="utf-8")
        payload["email_out"] = str(email_out)

    emit(payload)


if __name__ == "__main__":
    main()
