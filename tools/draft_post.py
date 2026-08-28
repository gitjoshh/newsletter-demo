"""Draft a weekly Run For Your Life blog post from the parsed Rushes digest.

Inputs:
  --source   rushes.json (from parse_rushes_email.py)
  --horror   horror_angle.json (from find_horror_angle.py)
  --revision free-text revision notes (optional)
  --personal Josh's own stories / thoughts to fold in, replacing invented anecdotes (optional)
  --prev     the previous draft.json (required with --revision or --personal)

Output: draft.json - a structured post ready for build_preview.py / publish_site.py.
The first pass also produces `questions`: 3-4 specific prompts for Josh's real input.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from lib.common import PROJECT_CONFIG, emit, fail, load_json_config, tmp_path
from lib.llm import MODEL, complete_json

SCHEMA = """{
  "title": "punchy, specific post title. MUST NOT contain a colon. Not clickbait.",
  "subtitle": "one-line standfirst (a colon here is fine but avoid it)",
  "slug": "kebab-case-url-slug",
  "excerpt": "2-3 sentence summary for the site index and RSS",
  "tags": ["horror", "boxing", "running"],
  "intro_md": "opening section in Markdown - personal, frames the week, names the boxing/running + horror lens",
  "film_blurbs": [
    {"title": "Film (Year)", "body_md": "2-4 short paragraphs in Josh's own voice about a film he is engaging with this week; work in a boxing or running/endurance thread where it fits"}
  ],
  "horror_deepdive": {"title": "section heading (no colon)", "body_md": "the longer horror-angle piece built from horror_angle.json; grounded, cites facts inline as Markdown links; ties explicitly to boxing / rounds / going the distance / running / endurance"},
  "closing_md": "short sign-off in the style of the reference post",
  "sources": [{"text": "what it supports", "url": "https://..."}],
  "image_queries": ["1-2 stock-photo search phrases for the deep-dive's MOOD photo. Draw from boxing / roadwork / running / sweat / the grind of training: e.g. 'boxer wrapping hands in a dim gym', 'lone runner on an empty road at dawn', 'heavy bag and sweat under gym lights', 'fighter resting on the ropes between rounds'. Concrete and evocative, horizontal framing, NOT film scenes (film stills come from TMDB). If the revision notes or personal input name a photo the author wants, make that the first query."],
  "questions": ["3-4 specific questions for Josh, each pointing at a spot in the draft where his OWN real training memory, opinion, or story would make it land. Reference the actual films / the horror angle. e.g. 'The intro leans on a dawn-run beat - do you have a real early session from this week that fits, or a different way in?'"]
}"""


def system_prompt(cfg: dict, mode: str) -> str:
    voice = cfg.get("voice", {})
    structure = cfg.get("structure", {})
    notes = "\n".join(f"- {n}" for n in voice.get("notes", []))
    lo, hi = structure.get("target_words", [900, 1500])
    n_films = structure.get("roundup_film_count", 4)
    base = f"""You write "Run For Your Life", a weekly personal newsletter by Joshua Laurie \
about the intersection of combat/endurance training - mainly BOXING, which he does every \
day, with running/cardio as the constant adjacent thread - and horror movies. You are \
writing this week's blog post: a handful of films Josh is engaging with this week, plus one \
deeper horror-angle deep-dive.

SOURCING RULE (critical): the film list comes from a third-party service, invisible to the \
reader. NEVER mention Letterboxd, "Rushes", a digest, "popular reviews", other users' star \
ratings, "the community", or any hint this was scraped or aggregated. Do not quote or \
attribute other people's reviews. Reviewer names/excerpts are private mood signal only. \
Every take is Josh's own.

TITLE RULE: the title MUST NOT contain a colon. If you would write "X: Y", write "X" and \
put "Y" in the subtitle, or join them plainly. Section headings: no colons either. Colons \
in body prose are fine but use them sparingly.

ANECDOTE RULE: Josh will supply his own real stories separately. On the FIRST pass, keep \
first-person anecdotes SHORT and lightly sketched - a sentence or two, plausible and \
grounded in real training, never a vivid confident "memory" of something specific that may \
not have happened. Leave room for his real material to slot in.

Voice:
{notes}

Structure:
- Personal intro framing the week through the boxing + running + horror lens. Open with a \
concrete training texture (bag work, footwork, a dawn run, the walk to the gym) kept brief.
- About {n_films} short film blurbs, each on a film Josh is engaging with this week, in his \
voice; thread a boxing or running observation where it fits.
- One "horror_deepdive" - the longest section, in the style of the reference notes: \
grounded, specific, real facts as inline Markdown links, tied explicitly to boxing / rounds \
/ taking punishment / going the distance / the journeyman grind (or running/endurance).
- A short sign-off.
- Target {lo}-{hi} words. Markdown only in the *_md fields. No headings inside intro_md or \
blurb bodies. Consistent spelling. NEVER use em dashes."""

    if mode == "revision":
        return base + "\n\nApply the revision notes precisely to the previous draft and " \
            "return the FULL revised object. Keep everything the notes do not touch.\n\n" \
            f"Respond with ONLY a ```json fenced object matching this schema:\n{SCHEMA}"
    if mode == "personal":
        return base + "\n\nJosh has sent his own stories / thoughts. REWRITE the draft so " \
            "his real material replaces the sketched first-person anecdotes and shapes the " \
            "relevant sections - his words and details lead, the film analysis and structure " \
            "stay. Do not invent around his input; if a section has no matching input, leave " \
            "its light sketch as is. Return the FULL updated object. You may drop or shorten " \
            "the 'questions' list now.\n\n" \
            f"Respond with ONLY a ```json fenced object matching this schema:\n{SCHEMA}"
    return base + "\n\nWrite this week's first-pass draft, including the `questions` list.\n\n" \
        f"Respond with ONLY a ```json fenced object matching this schema:\n{SCHEMA}"


def user_prompt(rushes, horror, revision, personal, prev):
    parts = [
        "INTERNAL SIGNAL for this week (never surface this framing or attribute anything to "
        "anyone - it only says which films to write about and the mood around them):",
        json.dumps(
            {
                "week_of": rushes.get("week_of"),
                "films_in_play": rushes.get("popular_films", []),
                "mood_notes": [
                    {"title": r.get("title"), "year": r.get("year"), "gist": r.get("excerpt")}
                    for r in rushes.get("popular_reviews", [])
                ],
                "adjacent_lists": [
                    {k: l.get(k) for k in ("title", "excerpt", "sample_films")}
                    for l in rushes.get("popular_lists", [])
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
        "\nHORROR ANGLE FOR THE DEEP-DIVE:",
        json.dumps(horror, indent=2, ensure_ascii=False),
    ]
    if prev is not None:
        parts += ["\nPREVIOUS DRAFT:", json.dumps(prev, indent=2, ensure_ascii=False)]
    if revision:
        parts += ["\nREVISION NOTES (apply precisely):", revision]
    if personal:
        parts += ["\nJOSH'S OWN STORIES / THOUGHTS (fold these in, his words lead):", personal]
    return "\n".join(parts)


def strip_title_colon(title: str) -> str:
    if ":" not in title:
        return title
    head = title.split(":", 1)[0].strip()
    return head or title.replace(":", "").strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True)
    ap.add_argument("--horror", required=True)
    ap.add_argument("--revision", default=None, help="Revision notes")
    ap.add_argument("--personal", default=None, help="Josh's own stories/thoughts to fold in")
    ap.add_argument("--prev", default=None, help="Previous draft.json (required with --revision/--personal)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    rushes = json.loads(Path(args.source).read_text(encoding="utf-8"))
    horror = json.loads(Path(args.horror).read_text(encoding="utf-8"))

    mode = "revision" if args.revision else "personal" if args.personal else "first"
    prev = None
    if mode != "first":
        if not args.prev:
            fail(f"--{mode} requires --prev <previous draft.json>")
        prev = json.loads(Path(args.prev).read_text(encoding="utf-8"))

    cfg = load_json_config(PROJECT_CONFIG / "newsletter.json")

    result = complete_json(
        system_prompt(cfg, mode),
        user_prompt(rushes, horror, args.revision, args.personal, prev),
        max_tokens=16000,
        effort="high",
    )
    draft = result["data"]
    required = {"title", "slug", "intro_md", "film_blurbs", "horror_deepdive", "closing_md"}
    missing = required - set(draft)
    if missing:
        fail(f"Draft is missing required fields: {sorted(missing)}")

    draft["title"] = strip_title_colon(str(draft.get("title", "")).strip())
    if isinstance(draft.get("horror_deepdive"), dict) and draft["horror_deepdive"].get("title"):
        draft["horror_deepdive"]["title"] = strip_title_colon(draft["horror_deepdive"]["title"].strip())
    draft.setdefault("tags", [])
    draft.setdefault("questions", [])
    draft["_model"] = MODEL
    draft["_mode"] = mode

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
            "questions": draft.get("questions", []),
            "image_queries": draft.get("image_queries", []),
            "mode": mode,
        }
    )


if __name__ == "__main__":
    main()
