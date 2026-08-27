"""Thin wrapper around the Anthropic Messages API for the newsletter tools.

Centralises: client creation, the model id, an optional server-side web_search
tool, and JSON extraction from the model's reply. Tools that need Claude import
`complete()` / `complete_json()` from here rather than talking to the SDK directly.

Model: defaults to claude-opus-5 (the Anthropic-recommended default). Set
ANTHROPIC_MODEL in .env to override, e.g. claude-sonnet-5 to lower per-run cost.
"""
from __future__ import annotations

import json
import os
import re

from lib.common import fail, require_env

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

# Server tool version for web search. Opus 5 / Sonnet 5 support the dynamic-filter
# variant; older models/accounts need web_search_20250305. Override via env if the
# API rejects the default with a 400 about the tool type.
WEB_SEARCH_TOOL = {
    "type": os.getenv("ANTHROPIC_WEB_SEARCH_TOOL", "web_search_20260209"),
    "name": "web_search",
}


def _client():
    require_env("ANTHROPIC_API_KEY")
    try:
        import anthropic
    except ImportError:
        fail("The 'anthropic' package is not installed (pip install -r requirements.txt)")
    return anthropic.Anthropic()


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 16000,
    web_search: bool = False,
    max_web_uses: int = 5,
    effort: str | None = None,
    no_thinking: bool = False,
) -> dict:
    """Run one Messages request. Returns {text, sources, stop_reason}.

    `sources` is a de-duplicated list of {url, title} harvested from any
    web_search results, so callers can cross-check the model's citations.

    `no_thinking=True` disables adaptive thinking - use it for pure JSON
    extraction so thinking tokens don't eat into `max_tokens` and truncate
    the output.
    """
    client = _client()

    kwargs: dict = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if no_thinking:
        kwargs["thinking"] = {"type": "disabled"}
    if effort:
        kwargs["output_config"] = {"effort": effort}
    if web_search:
        tool = dict(WEB_SEARCH_TOOL)
        tool["max_uses"] = max_web_uses
        kwargs["tools"] = [tool]

    try:
        resp = client.messages.create(**kwargs)
    except Exception as e:  # noqa: BLE001 - surface a clean message to the agent
        fail(f"Anthropic API call failed: {type(e).__name__}: {e}")

    if getattr(resp, "stop_reason", None) == "refusal":
        detail = getattr(resp, "stop_details", None)
        fail(f"Model refused the request ({getattr(detail, 'category', 'unknown')}).")

    text_parts: list[str] = []
    sources: list[dict] = []
    seen: set[str] = set()
    for block in resp.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(block.text)
        elif btype == "web_search_tool_result":
            content = getattr(block, "content", None)
            if isinstance(content, list):
                for r in content:
                    url = getattr(r, "url", None)
                    if url and url not in seen:
                        seen.add(url)
                        sources.append({"url": url, "title": getattr(r, "title", None)})

    return {
        "text": "".join(text_parts).strip(),
        "sources": sources,
        "stop_reason": getattr(resp, "stop_reason", None),
    }


def extract_json(text: str) -> dict | list:
    """Pull a JSON value out of a model reply.

    Accepts a ```json fenced block, a bare fenced block, or the first balanced
    object/array in the text.
    """
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        candidate = fence.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # first balanced {...} or [...]
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
    fail("Could not parse a JSON object from the model reply.")
    return {}  # unreachable


def complete_json(system: str, user: str, **kwargs) -> dict:
    """complete() + extract_json(), returning {data, text, sources}."""
    out = complete(system, user, **kwargs)
    return {"data": extract_json(out["text"]), "text": out["text"], "sources": out["sources"]}
