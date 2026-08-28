"""Draft the social posts for the week.

Reads draft.json, writes teaser.json:
{
  "blog":  {"para1", "para2", "cta"}          # teases the newsletter post; cta ends "{url}"
  "films": [{"title", "post"}, ...]            # up to 2 standalone film posts (no link needed)
}

The blog teaser links the post. Each film post is a self-contained thing Josh can drop
on his profile to tease a single movie. Adapted from Josh's Letterboxd social-post style:
witty, film-literate, lightly irreverent, Hook/Body/CTA, ~120-180 words.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import PROJECT_CONFIG, emit, fail, load_json_config, tmp_path
from lib.llm import MODEL, complete_json

SYSTEM = """You are a social media content editor for "Run For Your Life", Joshua Laurie's \
weekly newsletter on boxing, running, and horror movies.

NEVER mention Letterboxd, a digest, star ratings, other people's reviews, or that the film \
picks came from anywhere. Every take is Josh's own. NEVER use em dashes.

ANTI-AI VOICE: no "not A, but B" contrast structures; no end-of-post summaries; never use \
delve, tapestry, testament, beacon, foster, crucial, pivotal, landscape, realm, vibrant, \
overarching; avoid the rule of three and symmetrical sentences; strong direct declaratives, \
say what a thing IS.

Produce, as a JSON object in a ```json fenced block:

{
  "blog": {
    "para1": "hook - 1-3 punchy sentences leaning on the week's horror angle, ideally with a boxing or running beat",
    "para2": "body - what this week's issue covers (the films + the deep-dive), in Josh's voice; no generalising about 'the week' or 'the community'",
    "cta": "one short line inviting people to read, ending with the literal token {url}"
  },
  "films": [
    {"title": "Film (Year)", "post": "a standalone 120-180 word post (hard max 200) Josh can put on his profile to tease JUST this film: hook, then his take, then a light call to watch / discuss. Witty, film-literate, slightly irreverent, no snark. No link needed."}
  ]
}

blog.para1 + blog.para2 together: 120-180 words (hard max 200). Include 1-2 film posts in \
"films", drawn from the films given, favouring the two most talk-worthy."""


def _blog_words(t: dict) -> int:
    b = t.get("blog", {})
    return len((b.get("para1", "") + " " + b.get("para2", "")).split())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True, help="Path to draft.json")
    ap.add_argument("--out", default=None, help="Where to write teaser.json (default .tmp/)")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    cfg = load_json_config(PROJECT_CONFIG / "newsletter.json").get("social", {})
    lo, hi = cfg.get("teaser_words", [120, 180])

    user = (
        f"Blog teaser word target: {lo}-{hi}.\n\nTHIS WEEK'S POST (JSON):\n"
        + json.dumps(
            {
                "title": draft.get("title"),
                "subtitle": draft.get("subtitle"),
                "excerpt": draft.get("excerpt"),
                "films": [b.get("title") for b in draft.get("film_blurbs", [])],
                "horror_deepdive": draft.get("horror_deepdive", {}),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n\nWrite the social posts now."
    )

    teaser = complete_json(SYSTEM, user, max_tokens=4000, no_thinking=True)["data"]

    # tolerate a flat shape from the model
    if "blog" not in teaser and "para1" in teaser:
        teaser = {"blog": {k: teaser.get(k, "") for k in ("para1", "para2", "cta")},
                  "films": teaser.get("films", [])}
    blog = teaser.get("blog", {})
    if not (blog.get("para1") and blog.get("para2")):
        raw = tmp_path("teaser_raw.txt")
        raw.write_text(json.dumps(teaser, indent=2), encoding="utf-8")
        fail(f"Teaser missing blog.para1/para2. Raw saved to {raw}")
    if "{url}" not in blog.get("cta", ""):
        blog["cta"] = (blog.get("cta", "") or "Read this week's issue:").rstrip() + " {url}"
    teaser["blog"] = blog
    teaser.setdefault("films", [])
    teaser["_word_count"] = _blog_words(teaser)
    teaser["_model"] = MODEL

    out_path = Path(args.out) if args.out else tmp_path("teaser.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(teaser, indent=2, ensure_ascii=False), encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "blog_words": teaser["_word_count"],
            "film_posts": [f.get("title") for f in teaser["films"]],
        }
    )


if __name__ == "__main__":
    main()
