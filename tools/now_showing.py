"""What is actually watchable at the local cinema this week.

Pulls the ClickTheCity theater feed (the JSON API behind
clickthecity.com/movies/theaters/<slug>) for the next few days, merges the
films and showtimes, enriches each with TMDB (year, genres, synopsis) and
flags the ones that suit the horror + boxing/running lens.

Writes:
  --out <path>   source JSON. It also carries `popular_films`, so the existing
                 find_horror_angle.py / draft_post.py accept it as --source.
  state/now_showing/<YYYY-MM-DD>.json   weekly snapshot (to mark NEW titles)

--telegram prints a plain-text shortlist (for Hermes cron delivery to Penny)
instead of the JSON result.

No LLM calls. Showtimes are advisory: always "verify before leaving".
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from pathlib import Path

import requests

from lib.common import PROJECT_CONFIG, STATE, emit, fail, load_env, load_json_config

CTC_API = "https://www.clickthecity.com/api/movies/theater/{slug}"
CTC_WEB = "https://www.clickthecity.com"
TMDB = "https://api.themoviedb.org/3"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"
MANILA = dt.timezone(dt.timedelta(hours=8))
HORRORISH = {"Horror", "Thriller", "Mystery"}
LENS_WORDS = re.compile(r"\b(box|boxing|boxer|fight|fighter|run|running|runner|chase|hunt|"
                        r"survive|survival|escape|marathon|athlete|train|ring)\w*", re.I)


def _get(url: str, **params) -> dict:
    r = requests.get(url, params=params, headers={"User-Agent": UA}, timeout=25)
    r.raise_for_status()
    return r.json()


def fetch_theater(slug: str, days: int) -> tuple[dict, dict]:
    """Return (theater_info, films_by_id) merged across `days` days from today (Manila)."""
    today = dt.datetime.now(MANILA).date()
    theater: dict = {}
    films: dict[int, dict] = {}
    for i in range(days):
        day = (today + dt.timedelta(days=i)).isoformat()
        try:
            data = _get(CTC_API.format(slug=slug), date=day)
        except (requests.RequestException, ValueError) as e:
            if i == 0:
                fail(f"ClickTheCity feed failed for {slug}: {e}")
            continue
        theater = theater or data.get("theater") or {}
        for m in data.get("now_showing") or []:
            mid = m.get("movieId") or m.get("id")
            f = films.setdefault(mid, {
                "ctc_id": mid,
                "title": (m.get("title") or "").strip(),
                "mtrcb": m.get("mtrcb_rating"),
                "running_time": m.get("running_time"),
                "poster": m.get("poster"),
                "ctc_url": None,
                "showtimes": {},
            })
            if m.get("hash") and f["title"]:
                s = re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", f["title"].lower()))
                f["ctc_url"] = f"{CTC_WEB}/movies/title/{m['hash']}/{s}/showtimes"
        for sch in data.get("schedules") or []:
            f = films.get(sch.get("movieId"))
            if f is not None:
                key = f"{sch.get('date')} {sch.get('theaterName')}"
                f["showtimes"][key] = sch.get("showtimes") or []
    return theater, films


def _search_title(title: str) -> str:
    # ClickTheCity titles carry event suffixes TMDB does not ("... Encore", "(Re-run)").
    t = re.sub(r"\s*\((?:re-?run|re-?release|imax|3d)\)\s*$", "", title, flags=re.I)
    return re.sub(r"\s+(encore|re-?release)$", "", t, flags=re.I).strip()


def tmdb_enrich(films: dict) -> list[str]:
    key, token = os.getenv("TMDB_API_KEY"), os.getenv("TMDB_READ_TOKEN")
    if not (key or token):
        return ["TMDB_API_KEY not set: no genres/synopsis"]
    params = {} if token else {"api_key": key}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    warnings: list[str] = []
    try:
        r = requests.get(f"{TMDB}/genre/movie/list", params=params, headers=headers, timeout=20)
        genre_names = {g["id"]: g["name"] for g in r.json().get("genres", [])}
    except (requests.RequestException, ValueError):
        genre_names = {}
    for f in films.values():
        q = _search_title(f["title"])
        try:
            r = requests.get(f"{TMDB}/search/movie", headers=headers, timeout=20,
                             params={"query": q, "include_adult": "false", **params})
            results = r.json().get("results", [])
        except (requests.RequestException, ValueError) as e:
            warnings.append(f"TMDB lookup failed for {q!r}: {e}")
            continue
        if not results:
            warnings.append(f"no TMDB match for {q!r}")
            continue
        # Prefer the most recent close title match (cinemas show current releases).
        exact = [m for m in results if (m.get("title") or "").lower() == q.lower()] or results[:3]
        m = max(exact, key=lambda x: (x.get("release_date") or "", x.get("popularity") or 0))
        rd = m.get("release_date") or ""
        f.update({
            "tmdb_id": m.get("id"),
            "year": rd[:4] or None,
            "genres": [genre_names.get(g, str(g)) for g in m.get("genre_ids", [])],
            "overview": " ".join((m.get("overview") or "").split()) or None,
            "url": f"https://www.themoviedb.org/movie/{m.get('id')}",
        })
    return warnings


def score(f: dict) -> tuple[int, list[str]]:
    why: list[str] = []
    s = 0
    g = set(f.get("genres") or [])
    if "Horror" in g:
        s += 3
        why.append("horror")
    elif g & HORRORISH:
        s += 2
        why.append("thriller/mystery")
    if LENS_WORDS.search(f.get("overview") or ""):
        s += 1
        why.append("training lens")
    if f.get("is_new"):
        s += 1
        why.append("new this week")
    return s, why


def telegram_text(theater: dict, films: list[dict], label: str) -> str:
    today = dt.datetime.now(MANILA).date()
    lines = [f"Penny here. Now showing at {label}, week of {today:%b %d}.",
             "Showtimes are advisory from ClickTheCity, verify before leaving.", ""]
    for i, f in enumerate(films, 1):
        g = ", ".join(f.get("genres") or []) or "genre unknown"
        tag = " [NEW]" if f.get("is_new") else ""
        star = " *" if f.get("fit_score", 0) >= 2 else ""
        yr = f" ({f['year']})" if f.get("year") else ""
        lines.append(f"{i}. {f['title']}{yr}{tag}{star}")
        lines.append(f"   {g} | {f.get('mtrcb') or '?'} | {f.get('running_time') or '?'}")
        first = next(iter(sorted(f.get("showtimes", {}).items())), None)
        if first:
            lines.append(f"   {first[0]}: {', '.join(first[1][:4])}")
        if f.get("overview"):
            ov = f["overview"]
            lines.append(f"   {ov[:160]}{'...' if len(ov) > 160 else ''}")
        lines.append("")
    lines += ["* = fits the horror / training lens.",
              "Reply with what you will watch, or a film you have already seen and one line "
              "on what stuck with you. A voice note is fine. Nothing gets drafted until you do."]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", default=None, help="ClickTheCity theater slug (default from config)")
    ap.add_argument("--days", type=int, default=None, help="Days ahead to merge (default from config)")
    ap.add_argument("--out", default=None, help="Write the source JSON here")
    ap.add_argument("--no-snapshot", action="store_true", help="Do not write state/now_showing/")
    ap.add_argument("--telegram", action="store_true", help="Print the Telegram shortlist text instead of JSON")
    args = ap.parse_args()

    load_env()
    disc = load_json_config(PROJECT_CONFIG / "newsletter.json").get("discovery", {})
    slug = args.slug or disc.get("theater_slug", "sm-city-baguio")
    days = args.days or int(disc.get("days_ahead", 7))
    label = disc.get("theater_label", "SM City Baguio")

    theater, by_id = fetch_theater(slug, days)
    warnings = tmdb_enrich(by_id)

    snap_dir = STATE / "now_showing"
    today_name = f"{dt.datetime.now(MANILA).date().isoformat()}.json"
    prev = sorted(p for p in snap_dir.glob("*.json") if p.name != today_name)
    prev_titles: set[str] = set()
    if prev:
        try:
            prev_titles = {f["title"] for f in json.loads(prev[-1].read_text(encoding="utf-8"))["films"]}
        except (ValueError, KeyError):
            pass
    films = list(by_id.values())
    for f in films:
        f["is_new"] = bool(prev_titles) and f["title"] not in prev_titles
        f["fit_score"], f["fit_reasons"] = score(f)
    films.sort(key=lambda f: (-f["fit_score"], f["title"]))

    today = dt.datetime.now(MANILA).date().isoformat()
    result = {
        "source": "clickthecity",
        "theater": {k: theater.get(k) for k in ("name", "slug", "city", "address")},
        "label": label,
        "fetched_at": dt.datetime.now(MANILA).isoformat(timespec="minutes"),
        "week_of": today,
        "advisory": "Showtimes from ClickTheCity, verify before leaving.",
        "films": films,
        # Compatibility with find_horror_angle.py / draft_post.py (--source).
        "popular_films": [{"title": f["title"], "year": f.get("year"), "slug": None,
                           "url": f.get("url") or f.get("ctc_url")} for f in films],
        "popular_reviews": [],
        "popular_lists": [],
        "warnings": warnings,
    }
    if not args.no_snapshot:
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / f"{today}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.telegram:
        print(telegram_text(theater, films, label))
        return
    emit({"out": args.out, "film_count": len(films),
          "titles": [f["title"] for f in films], "warnings": warnings})


if __name__ == "__main__":
    main()
