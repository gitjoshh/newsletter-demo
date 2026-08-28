"""Classify Josh's reply to a draft email.

Input: --thread-text <path> - the plain text of his latest reply (the routine
strips quoted history before calling this).

Output: {"intent": "approve" | "personal_input" | "revise" | "unclear",
         "revision_notes": "...", "personal_text": "..."}

- approve: happy to publish as-is.
- personal_input: he answered the draft's questions / sent his own stories, opinions,
  or paragraphs to weave in. personal_text = his prose, verbatim, history stripped.
- revise: he asked for specific changes/edits (not his own story content).
  revision_notes = the actionable changes. "approve" + changes -> revise.
- unclear: a question, out-of-office, empty, or genuinely can't tell.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from lib.common import emit, fail, tmp_path
from lib.llm import complete_json

SYSTEM = """You classify a single email reply about a draft blog post that was sent with \
a few questions asking the author for his own real stories / thoughts.

Return ONLY a ```json fenced object:
{"intent": "approve" | "personal_input" | "revise" | "unclear",
 "revision_notes": "string", "personal_text": "string"}

Rules:
- "approve": clearly says publish / ship / post it, with nothing else to fold in.
- "personal_input": the reply contains the author's own material to incorporate - answers \
to the questions, a personal anecdote, an opinion, a paragraph or two of prose. Put that \
prose in "personal_text" verbatim (strip greetings/signature/quoted history). If he ALSO \
says approve, still use "personal_input" (fold his material in first, then he approves the \
result).
- "revise": he asks for specific edits/changes to the existing text and does NOT supply \
his own story content. Put the changes in "revision_notes".
- "unclear": a question back, out-of-office, empty, or you cannot tell.
- Unused fields are ""."""


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
        data = {"intent": "unclear", "revision_notes": "", "personal_text": ""}
    else:
        data = complete_json(
            SYSTEM,
            f"The reply:\n\n{reply}\n\nClassify it.",
            max_tokens=2000,
            no_thinking=True,
        )["data"]

    intent = data.get("intent")
    if intent not in ("approve", "personal_input", "revise", "unclear"):
        fail(f"Model returned an invalid intent: {intent!r}")
    data["revision_notes"] = data.get("revision_notes", "") if intent == "revise" else ""
    data["personal_text"] = data.get("personal_text", "") if intent == "personal_input" else ""

    out_path = Path(args.out) if args.out else tmp_path("reply_intent.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    emit({"status": "ok", "out": str(out_path), **data})


if __name__ == "__main__":
    main()
