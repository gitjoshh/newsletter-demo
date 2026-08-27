"""Classify Josh's reply to an approval email.

Input: --thread-text <path> - the plain text of his latest reply (the routine
strips quoted history before calling this).

Output: {"intent": "approve" | "revise" | "unclear", "revision_notes": "..."}.

- approve: he is happy to publish as-is.
- revise: he wants changes. revision_notes = the actionable changes, verbatim where
  possible, with quoting/history removed. An "approve" that also lists changes is a
  "revise" (apply the changes first).
- unclear: anything else (a question, ambiguous, empty).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from lib.common import emit, fail, tmp_path
from lib.llm import complete_json

SYSTEM = """You classify a single email reply about a draft blog post.

Return ONLY a JSON object in a ```json fenced block:
{"intent": "approve" | "revise" | "unclear", "revision_notes": "string"}

Rules:
- "approve": the reply clearly says to publish / ship / post it, with no requested changes.
- "revise": the reply asks for any change, even small. Put the requested changes in \
"revision_notes" as clear instructions. If the reply says "approve" but also asks for \
changes, intent is "revise".
- "unclear": a question, an out-of-office, empty, or you genuinely cannot tell.
- "revision_notes" is "" unless intent is "revise"."""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--thread-text", required=True, help="Path to the reply text")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    p = Path(args.thread_text)
    if not p.exists():
        fail(f"Reply text not found: {p}")
    reply = p.read_text(encoding="utf-8").strip()
    if not reply:
        result = {"data": {"intent": "unclear", "revision_notes": ""}}
    else:
        result = complete_json(
            SYSTEM,
            f"The reply:\n\n{reply}\n\nClassify it.",
            max_tokens=1000,
            no_thinking=True,
        )

    data = result["data"]
    intent = data.get("intent")
    if intent not in ("approve", "revise", "unclear"):
        fail(f"Model returned an invalid intent: {intent!r}")
    data["revision_notes"] = data.get("revision_notes", "") if intent == "revise" else ""

    out_path = Path(args.out) if args.out else tmp_path("reply_intent.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(__import__("json").dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    emit({"status": "ok", "out": str(out_path), **data})


if __name__ == "__main__":
    main()
