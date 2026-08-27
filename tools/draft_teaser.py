"""Draft one short social teaser for the week's post.

Reads draft.json, writes teaser.json: {para1, para2, cta}. Two short paragraphs
plus a call to action. The live post URL is injected later by finalize (the CTA
here ends with a "{url}" placeholder).

Adapted from Josh's existing Letterboxd social-post prompt: witty, film-literate,
lightly irreverent, no snark. Hook -> body -> CTA, ~120-180 words total.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import PROJECT_CONFIG, emit, fail, load_json_config, tmp_path
from lib.llm import MODEL, complete_json

SYSTEM = """You are a social media content editor writing one short, standalone teaser \
post for a weekly newsletter called "Run For Your Life" (fitness running + horror movies).

You do NOT write essays or summaries. You produce one discrete, publishable teaser.

The JSON object MUST have EXACTLY these three string keys, all required:
- "para1": hook - 1-3 punchy sentences that make someone stop scrolling. Lean on the \
week's horror angle.
- "para2": body - what this week's issue covers (the roundup + the deep-dive), referencing \
the tone of the films without quoting reviews. Do not generalise about "the week" or \
"the community".
- "cta": ONE short sentence inviting people to read. It MUST end with the literal token \
{url} (the real link is substituted in later). Never omit this key. Example: \
"Read this week's issue: {url}"

Tone: witty, film-literate, slightly irreverent. Light on sarcasm, no snark. No horny \
jokes unless the material clearly implies it. NEVER use em dashes.

Length: 120-180 words across para1 + para2 (hard max 200). "cta" is separate and short.

Respond with ONLY a JSON object in a ```json fenced block, with all three keys present:
{"para1": "...", "para2": "...", "cta": "Read this week's issue: {url}"}"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--draft", required=True, help="Path to draft.json")
    ap.add_argument("--out", default=None, help="Where to write teaser.json (default .tmp/)")
    args = ap.parse_args()

    draft = json.loads(Path(args.draft).read_text(encoding="utf-8"))
    cfg = load_json_config(PROJECT_CONFIG / "newsletter.json").get("social", {})
    lo, hi = cfg.get("teaser_words", [120, 180])
    hard = cfg.get("teaser_max_words", 200)

    user = (
        f"Word target: {lo}-{hi}, hard max {hard}.\n\n"
        "THIS WEEK'S POST (JSON):\n"
        + json.dumps(
            {
                "title": draft.get("title"),
                "subtitle": draft.get("subtitle"),
                "excerpt": draft.get("excerpt"),
                "film_blurbs": [b.get("title") for b in draft.get("film_blurbs", [])],
                "horror_deepdive": draft.get("horror_deepdive", {}),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n\nWrite the teaser now."
    )

    result = complete_json(SYSTEM, user, max_tokens=3000, no_thinking=True)
    teaser = result["data"]
    if isinstance(teaser, dict) and "para1" not in teaser:
        # unwrap a nested {"teaser": {...}} / {"data": {...}} if the model added one
        for wrap in ("teaser", "data", "post", "result"):
            if isinstance(teaser.get(wrap), dict):
                teaser = teaser[wrap]
                break
    if not (isinstance(teaser, dict) and teaser.get("para1") and teaser.get("para2")):
        raw = tmp_path("teaser_raw.txt")
        raw.write_text(result["text"], encoding="utf-8")
        fail(f"Teaser missing para1/para2. Raw model output saved to {raw}")
    if not teaser.get("cta"):
        teaser["cta"] = "Read this week's issue: {url}"
    if "{url}" not in teaser["cta"]:
        teaser["cta"] = teaser["cta"].rstrip() + " {url}"

    wc = len((teaser["para1"] + " " + teaser["para2"]).split())
    teaser["_word_count"] = wc
    teaser["_model"] = MODEL

    out_path = Path(args.out) if args.out else tmp_path("teaser.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(teaser, indent=2, ensure_ascii=False), encoding="utf-8")

    warnings = [] if wc <= hard else [f"teaser is {wc} words (hard max {hard})"]
    emit({"status": "ok", "out": str(out_path), "word_count": wc, "warnings": warnings})


if __name__ == "__main__":
    main()
