"""Draft the social posts for the week.

Reads draft.json, writes teaser.json:
{
  "blog":  {"para1", "para2", "cta"}    # 2-3 short lines teasing the post; cta ends "{url}"
  "films": [{"title", "hook", "excerpt"}, ...]   # up to 2; hook = 1 quirky line announcing
                                                 # the blog + the film; excerpt = 2-4 lines
                                                 # LIFTED from that film's blurb in the post
}

The renderers assemble each film post as:  hook  +  excerpt  +  "Read it: <url>".
Nothing here is fresh long-form marketing copy - the excerpt is Josh's own blog text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import PROJECT_CONFIG, emit, fail, load_json_config, tmp_path
from lib.llm import MODEL, complete_json

SYSTEM = """You are a social media editor for "Run For Your Life", Joshua Laurie's weekly \
newsletter on boxing, running, and horror movies.

NEVER mention Letterboxd, a digest, star ratings, other people's reviews, or that the film \
picks came from anywhere. Every take is Josh's own. NEVER use em dashes.

ANTI-AI VOICE: no "not A, but B" contrast structures; no end-of-post summaries; never use \
delve, tapestry, testament, beacon, foster, crucial, pivotal, landscape, realm, vibrant, \
overarching; avoid the rule of three and symmetrical sentences; strong direct declaratives.

Return a ```json fenced object:

{
  "blog": {
    "para1": "the whole newsletter teaser: 2-3 SHORT lines, punchy, lean on the week's horror angle with a boxing or running beat",
    "para2": "",
    "cta": "one short line ending with the literal token {url}"
  },
  "films": [
    {
      "title": "Film (Year)",
      "hook": "ONE quirky line that announces the blog is up and names this film, boxing/running/horror adjacent. e.g. 'The movie blog is live and this week it swung right into Spider-Man's midlife crisis.'",
      "excerpt": "a 2-4 line passage LIFTED from this film's section of the post below, lightly trimmed so it reads standalone. Do NOT write new copy - take Josh's actual words from the blurb."
    }
  ]
}

Include the two most talk-worthy films from the post in "films"."""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True, help="Path to draft.json")
    ap.add_argument("--out", default=None, help="Where to write teaser.json (default .tmp/)")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))

    user = (
        "THIS WEEK'S POST (JSON) - lift the film excerpts verbatim from film_blurbs:\n"
        + json.dumps(
            {
                "title": draft.get("title"),
                "subtitle": draft.get("subtitle"),
                "film_blurbs": draft.get("film_blurbs", []),
                "horror_deepdive": draft.get("horror_deepdive", {}),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n\nWrite the social posts now. Newsletter teaser: 2-3 short lines only."
    )

    teaser = complete_json(SYSTEM, user, max_tokens=3000, no_thinking=True)["data"]

    if "blog" not in teaser and "para1" in teaser:
        teaser = {"blog": {k: teaser.get(k, "") for k in ("para1", "para2", "cta")},
                  "films": teaser.get("films", [])}
    blog = teaser.get("blog", {})
    if not blog.get("para1"):
        raw = tmp_path("teaser_raw.txt")
        raw.write_text(json.dumps(teaser, indent=2), encoding="utf-8")
        fail(f"Teaser missing blog.para1. Raw saved to {raw}")
    if "{url}" not in blog.get("cta", ""):
        blog["cta"] = (blog.get("cta", "") or "Read it:").rstrip() + " {url}"
    teaser["blog"] = blog
    teaser["films"] = [
        {"title": f.get("title", ""), "hook": f.get("hook", ""), "excerpt": f.get("excerpt", "")}
        for f in teaser.get("films", [])
        if f.get("excerpt")
    ][:2]
    teaser["_model"] = MODEL

    out_path = Path(args.out) if args.out else tmp_path("teaser.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(teaser, indent=2, ensure_ascii=False), encoding="utf-8")

    emit({"status": "ok", "out": str(out_path),
          "blog_lines": blog["para1"].count("\n") + 1,
          "film_posts": [f["title"] for f in teaser["films"]]})


if __name__ == "__main__":
    main()
