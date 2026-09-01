"""Monday heads-up: this week's popular films, so Josh can watch a couple before
the Wednesday-night Rushes digest lands and write from real viewing.

Primary source is Letterboxd's live "popular this week" list, served behind a CSI
(component) endpoint:  /csi/films/films-browser-list/popular/this/week/
Each film carries  data-item-name="Title (Year)"  and  data-item-link="/film/<slug>/".
Letterboxd sits behind Cloudflare; from a datacenter IP (the cloud routine) the
request often gets a "Just a moment..." challenge instead of the list. When that
happens we fall back to TMDB's trending-this-week feed (clean JSON, no challenge).

Output: heads_up.json  {source, films:[{rank,title,year,slug,url}], ...}
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

from lib.common import PROJECT_CONFIG, emit, fail, load_env, load_json_config, tmp_path
from lib.site import env, load_style
from lib import tmdb

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


class ScrapeBlocked(RuntimeError):
    """Letterboxd was unreachable (Cloudflare challenge, curl error, empty parse)."""


def _fetch(url: str) -> str:
    curl = shutil.which("curl")
    if not curl:
        raise ScrapeBlocked("curl not found on PATH")
    cp = subprocess.run(
        [curl, "-sS", "--compressed", "--max-time", "25",
         "-A", UA, "-H", f"Referer: {HEADERS['Referer']}",
         "-H", f"Accept: {HEADERS['Accept']}", url],
        capture_output=True, text=True,
    )
    if cp.returncode != 0:
        raise ScrapeBlocked(f"curl failed ({cp.returncode}): {cp.stderr.strip()[:200]}")
    if "Just a moment" in cp.stdout[:2000] or "cf-browser-verification" in cp.stdout[:4000]:
        raise ScrapeBlocked("Cloudflare challenge page instead of the film list")
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
        raise ScrapeBlocked("parsed zero films from the CSI fragment (markup may have changed)")
    return films


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=12, help="How many films to keep (default 12)")
    ap.add_argument("--out", default=None, help="Where to write heads_up.json (default .tmp/)")
    ap.add_argument("--email-out", default=None, help="Also render the Monday email body here")
    args = ap.parse_args()
    load_env()

    try:
        films = scrape(args.limit)
        source = "Letterboxd, popular this week"
        source_note = ""
    except ScrapeBlocked as e:
        films = tmdb.trending_week(args.limit)
        source = "TMDB, trending this week"
        source_note = f"Letterboxd was unreachable ({e}); showing TMDB's trending list instead."
        if not films:
            fail(f"Letterboxd blocked ({e}) and TMDB trending fallback returned nothing"
                 + (" [" + "; ".join(tmdb.ERRORS) + "]" if tmdb.ERRORS else ""))

    payload = {"status": "ok", "source": source, "source_note": source_note,
               "count": len(films), "films": films}

    out_path = Path(args.out) if args.out else tmp_path("heads_up.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    payload["out"] = str(out_path)

    if args.email_out:
        site_cfg = load_json_config(PROJECT_CONFIG / "site.json")
        _, style_css = load_style()
        body = env().get_template("heads_up_email.html.j2").render(
            site=site_cfg, style_css=style_css, films=films,
            source=source, source_note=source_note,
        )
        email_out = Path(args.email_out)
        email_out.parent.mkdir(parents=True, exist_ok=True)
        email_out.write_text(body, encoding="utf-8")
        payload["email_out"] = str(email_out)

    emit(payload)


if __name__ == "__main__":
    main()
