"""Pick the week's horror angle for the Run For Your Life newsletter.

Reads a rushes.json (from parse_rushes_email.py), asks Claude - with web search -
to find the strongest horror connection among the week's films/lists, and to tie
it to running / endurance / escape. Writes horror_angle.json.

If no defensible factual horror link exists, the model returns a thematic reading
with "interpretation": true so the draft frames it as opinion, not fact.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import emit, fail, tmp_path
from lib.llm import MODEL, complete_json

SYSTEM = """You are the research assistant for "Run For Your Life", a weekly personal \
newsletter about the intersection of combat/endurance training - mainly BOXING, which the \
author does daily - and horror movies.

Your job: from a Letterboxd "Rushes" weekly digest, choose the SINGLE best horror \
angle for this week's issue and connect it to boxing / rounds / taking punishment / going \
the distance / the journeyman grind (or running / endurance / pursuit where that fits \
better).

Rules:
- Prefer a film that appears in "popular_films" or "popular_reviews". You may instead \
use a film from a list's sample_films, or the theme of a popular list, if that gives a \
stronger horror angle.
- Use web search to verify anything factual: subgenre, director, a real fight/chase/endurance \
scene, awards, production facts, critical reception. Cite what you rely on.
- The "connection" must be specific and grounded, not a vague "this film is scary".
- The "training_tie_in" links the film to boxing or endurance training - the recurring \
lens of this newsletter (the corner, the bell, absorbing damage and continuing, footwork, \
the unglamorous daily grind, not being able to stop).
- If NOTHING in the week has a genuine horror link, pick the closest film and write an \
honest thematic reading, and set "interpretation": true.

Respond with ONLY a JSON object in a ```json fenced block:
{
  "film": "Title",
  "year": "YYYY or null",
  "is_from": "popular_films | popular_reviews | list_sample | list_theme",
  "section_title": "short, evocative section heading for the deep-dive",
  "connection": "2-4 sentences: the specific horror angle, grounded in facts",
  "training_tie_in": "2-3 sentences linking it to boxing / endurance training",
  "supporting_facts": [{"text": "the claim you are relying on", "url": "source URL"}],
  "interpretation": false,
  "candidates_considered": ["Title - one line on why it lost"]
}"""


def build_user_prompt(rushes: dict) -> str:
    return (
        "Here is this week's Letterboxd Rushes digest as JSON:\n\n"
        + json.dumps(
            {
                "week_of": rushes.get("week_of"),
                "popular_films": rushes.get("popular_films", []),
                "popular_reviews": [
                    {k: r.get(k) for k in ("title", "year", "director", "reviewer", "rating", "excerpt")}
                    for r in rushes.get("popular_reviews", [])
                ],
                "popular_lists": [
                    {k: l.get(k) for k in ("title", "curator", "excerpt", "sample_films")}
                    for l in rushes.get("popular_lists", [])
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n\nChoose the horror angle now."
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", required=True, help="Path to rushes.json")
    ap.add_argument("--out", default=None, help="Where to write horror_angle.json (default .tmp/)")
    ap.add_argument("--max-web-uses", type=int, default=6)
    args = ap.parse_args()

    src = Path(args.source)
    if not src.exists():
        fail(f"Source not found: {src}")
    rushes = json.loads(src.read_text(encoding="utf-8"))

    result = complete_json(
        SYSTEM,
        build_user_prompt(rushes),
        max_tokens=8000,
        web_search=True,
        max_web_uses=args.max_web_uses,
        effort="high",
    )
    angle = result["data"]
    if not isinstance(angle, dict) or "film" not in angle:
        fail("Model did not return a usable horror_angle object.")

    angle["_model"] = MODEL
    angle["_web_sources_seen"] = result["sources"]

    out_path = Path(args.out) if args.out else tmp_path("horror_angle.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(angle, indent=2, ensure_ascii=False), encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "film": angle.get("film"),
            "section_title": angle.get("section_title"),
            "interpretation": angle.get("interpretation"),
            "supporting_facts": len(angle.get("supporting_facts", [])),
        }
    )


if __name__ == "__main__":
    main()
