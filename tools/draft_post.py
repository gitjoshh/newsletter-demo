"""Draft a weekly Run For Your Life blog post from the parsed Rushes digest.

Inputs:
  --source   rushes.json (from parse_rushes_email.py)
  --horror   horror_angle.json (from find_horror_angle.py)
  --revision free-text revision notes (optional)
  --prev     the previous draft.json to revise (required with --revision)

Output: draft.json - a structured post ready for build_preview.py / publish_site.py.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import PROJECT_CONFIG, emit, fail, load_json_config, tmp_path
from lib.llm import MODEL, complete_json

SCHEMA = """{
  "title": "post title - punchy, specific, not clickbait",
  "subtitle": "one-line standfirst",
  "slug": "kebab-case-url-slug",
  "excerpt": "2-3 sentence summary for the site index and RSS",
  "tags": ["horror", "running", "roundup"],
  "intro_md": "opening section in Markdown - personal, sets up the week, names the running+horror lens",
  "film_blurbs": [
    {"title": "Film (Year)", "body_md": "2-4 short paragraphs in Josh's voice; may reference the tone of the Letterboxd reviews without quoting them; work in a running or endurance thread where it fits"}
  ],
  "horror_deepdive": {"title": "section heading", "body_md": "the longer horror-angle piece built from horror_angle.json; grounded, cites facts inline as Markdown links; ties explicitly to running/endurance/escape"},
  "closing_md": "short sign-off in the style of the reference post (e.g. 'See you next Friday')",
  "sources": [{"text": "what it supports", "url": "https://..."}],
  "image_queries": ["1-2 stock-photo phrases for the deep-dive's running/endurance MOOD photo only - concrete, evocative, NOT film scenes (e.g. 'runner on a dark forest trail at dusk'). Film scene stills are sourced separately from TMDB."]
}"""


def system_prompt(cfg: dict) -> str:
    voice = cfg.get("voice", {})
    structure = cfg.get("structure", {})
    notes = "\n".join(f"- {n}" for n in voice.get("notes", []))
    lo, hi = structure.get("target_words", [900, 1500])
    n_films = structure.get("roundup_film_count", 4)
    return f"""You write "Run For Your Life", a weekly personal newsletter by Joshua Laurie \
about the intersection of combat/endurance training - mainly BOXING, which he does every \
day - and horror movies. You are writing this week's blog post as a roundup of the week's \
popular films on Letterboxd, plus one deeper horror-angle deep-dive.

Voice:
{notes}

Structure:
- Personal intro that frames the week through the boxing (or running/cardio) + horror lens. \
Open with a specific, lived training detail - a round on the bag, footwork drills, a \
sparring session, the walk to the gym.
- About {n_films} short film blurbs drawn from the week's popular films / popular reviews. \
Where it fits naturally, thread a boxing or training observation through a blurb.
- One "horror_deepdive" section built from the supplied horror angle - the longest section, \
in the style of the reference notes: grounded, specific, cites real facts as inline Markdown \
links, and ties explicitly back to boxing / rounds / taking punishment / going the distance \
/ the journeyman grind (or running/endurance where that is the stronger fit).
- A short sign-off.
- Target {lo}-{hi} words total. Markdown only in the *_md fields. No headings inside \
intro_md or blurb bodies (the site template adds them). Be consistent in spelling. \
NEVER use em dashes.

When given revision notes, apply them precisely to the previous draft and return the full \
revised object - keep everything the notes do not touch.

Respond with ONLY a JSON object in a ```json fenced block matching this schema:
{SCHEMA}"""


def user_prompt(rushes: dict, horror: dict, revision: str | None, prev: dict | None) -> str:
    parts = [
        "PARSED RUSHES DIGEST:",
        json.dumps(
            {
                "week_of": rushes.get("week_of"),
                "popular_films": rushes.get("popular_films", []),
                "popular_reviews": rushes.get("popular_reviews", []),
                "popular_lists": [
                    {k: l.get(k) for k in ("title", "curator", "excerpt", "sample_films")}
                    for l in rushes.get("popular_lists", [])
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        "\nHORROR ANGLE FOR THE DEEP-DIVE:",
        json.dumps(horror, indent=2, ensure_ascii=False),
    ]
    if revision:
        parts += [
            "\nPREVIOUS DRAFT (revise this):",
            json.dumps(prev, indent=2, ensure_ascii=False),
            "\nREVISION NOTES (apply precisely):",
            revision,
        ]
    else:
        parts.append("\nWrite this week's post now.")
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="Path to rushes.json")
    ap.add_argument("--horror", required=True, help="Path to horror_angle.json")
    ap.add_argument("--revision", default=None, help="Revision notes")
    ap.add_argument("--prev", default=None, help="Previous draft.json (required with --revision)")
    ap.add_argument("--out", default=None, help="Where to write draft.json (default .tmp/)")
    args = ap.parse_args()

    rushes = json.loads(Path(args.source).read_text(encoding="utf-8"))
    horror = json.loads(Path(args.horror).read_text(encoding="utf-8"))

    prev = None
    if args.revision:
        if not args.prev:
            fail("--revision requires --prev <previous draft.json>")
        prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))

    cfg = load_json_config(PROJECT_CONFIG / "newsletter.json")

    result = complete_json(
        system_prompt(cfg),
        user_prompt(rushes, horror, args.revision, prev),
        max_tokens=16000,
        effort="high",
    )
    draft = result["data"]
    required = {"title", "slug", "intro_md", "film_blurbs", "horror_deepdive", "closing_md"}
    missing = required - set(draft)
    if missing:
        fail(f"Draft is missing required fields: {sorted(missing)}")

    draft.setdefault("tags", [])
    draft["_model"] = MODEL
    draft["_revision_of"] = args.prev if args.revision else None

    out_path = Path(args.out) if args.out else tmp_path("draft.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "title": draft.get("title"),
            "slug": draft.get("slug"),
            "film_blurbs": len(draft.get("film_blurbs", [])),
            "image_queries": draft.get("image_queries", []),
            "revised": bool(args.revision),
        }
    )


if __name__ == "__main__":
    main()
