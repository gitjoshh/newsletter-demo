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

from lib.common import fail, load_env

load_env()
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5")

# Server tool version for web search. Opus 5 / Sonnet 5 support the dynamic-filter
# variant; older models/accounts need web_search_20250305. Override via env if the
# API rejects the default with a 400 about the tool type.
WEB_SEARCH_TOOL = {
    "type": os.getenv("ANTHROPIC_WEB_SEARCH_TOOL", "web_search_20260209"),
    "name": "web_search",
}


def _client():
    try:
        import anthropic
    except ImportError:
        fail("The 'anthropic' package is not installed (pip install -r requirements.txt)")
    load_env()
    # Cloud routine environments strip a var named exactly ANTHROPIC_API_KEY, so
    # accept several fallback names (and a couple of likely typos).
    key = next(
        (
            v
            for v in (
                os.getenv(n)
                for n in (
                    "ANTHROPIC_API_KEY",
                    "RFYL_ANTHROPIC_KEY",
                    "RYFL_ANTHROPIC_KEY",
                    "RFYL_ANTHROPIC_API_KEY",
                    "ANTHROPIC_KEY",
                    "LLM_API_KEY",
                )
            )
            if v
        ),
        None,
    )
    if key:
        return anthropic.Anthropic(api_key=key)
    # No explicit key: let the SDK resolve ambient credentials (e.g. an
    # ANTHROPIC_AUTH_TOKEN or OAuth profile in a Claude Code session).
    try:
        return anthropic.Anthropic()
    except Exception:  # noqa: BLE001
        fail(
            "No Anthropic credential found. Set ANTHROPIC_API_KEY (local .env) or "
            "RFYL_ANTHROPIC_KEY (cloud environment)."
        )


# Backend selection. "claude_cli" runs `claude -p` (Claude Code CLI), which bills
# the logged-in Claude subscription (Pro/Max) instead of a pay-per-token API key.
# "api" is the original Anthropic Messages API path (needs ANTHROPIC_API_KEY).
BACKEND = os.getenv("LLM_BACKEND", "claude_cli").strip().lower()

# Env vars that would make the CLI bill an API key instead of the subscription.
_API_CRED_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                  "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX")
_WIN_ARG_BUDGET = 20000  # stay well under the Windows 32k command-line limit


def _complete_cli(system: str, user: str, *, web_search: bool, max_web_uses: int,
                  effort: str | None) -> dict:
    """One-shot completion through the Claude Code CLI on the subscription login."""
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("claude") or shutil.which("claude.cmd")
    if not exe:
        fail("Claude Code CLI not found on PATH (needed for LLM_BACKEND=claude_cli)")

    env = {k: v for k, v in os.environ.items() if k not in _API_CRED_VARS}
    prompt = user
    if web_search:
        prompt += (f"\n\n(You may use WebSearch up to {max_web_uses} times. Put every URL "
                   "you rely on into the JSON as the schema asks.)")
    # Agentic CLI runs (esp. with web search) drift from the output schema; restate it last.
    schema_at = max(system.rfind("Respond with"), system.rfind("Return ONLY"), system.rfind("Output ONLY"), system.rfind("Return a ```json"))
    if schema_at >= 0:
        prompt += ("\n\nFINAL OUTPUT RULE: your final reply must be ONLY the JSON described "
                   "below, with exactly those keys, inside one ```json fenced block. No prose "
                   "before or after it.\n\n" + system[schema_at:])
    cmd = [exe, "-p", "--model", MODEL, "--output-format", "json",
           "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
           "--setting-sources", ""]
    if web_search:
        cmd += ["--tools", "WebSearch", "--allowedTools", "WebSearch"]
    else:
        cmd += ["--tools", ""]
    if effort:
        cmd += ["--effort", effort]
    if len(system) <= _WIN_ARG_BUDGET:
        cmd += ["--system-prompt", system]
    else:  # too long for argv on Windows: carry it in the prompt instead
        cmd += ["--system-prompt", "Follow the INSTRUCTIONS block exactly."]
        prompt = f"<INSTRUCTIONS>\n{system}\n</INSTRUCTIONS>\n\n{prompt}"

    # Neutral cwd so the repo's CLAUDE.md (operator contract) is not auto-loaded.
    with tempfile.TemporaryDirectory(prefix="rfyl-llm-") as cwd:
        try:
            proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", env=env, cwd=cwd,
                                  timeout=int(os.getenv("LLM_TIMEOUT_S", "900")))
        except subprocess.TimeoutExpired:
            fail("Claude CLI timed out")
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out[out.find("{"):]) if "{" in out else {}
    except json.JSONDecodeError:
        data = {}
    if proc.returncode != 0 or not data or data.get("is_error"):
        detail = data.get("result") or (proc.stderr or out)[-800:]
        fail(f"Claude CLI call failed (exit {proc.returncode}): {detail}")
    models = list((data.get("modelUsage") or {}).keys())
    return {"text": (data.get("result") or "").strip(), "sources": [],
            "stop_reason": data.get("stop_reason"), "models": models}


def _complete_hermes(system: str, user: str, *, web_search: bool, max_web_uses: int,
                     effort: str | None) -> dict:
    """One-shot completion through `hermes chat` (ChatGPT subscription via openai-codex).

    LLM_BACKEND=hermes_cli. Model/provider from HERMES_LLM_MODEL / HERMES_LLM_PROVIDER
    (default gpt-5.6-terra / openai-codex). Hermes' own fallback chain applies on failure.
    """
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("hermes") or os.path.expanduser("~/.local/bin/hermes")
    prompt = f"<INSTRUCTIONS>\n{system}\n</INSTRUCTIONS>\n\n{user}"
    if web_search:
        prompt += (f"\n\n(You may use web search up to {max_web_uses} times. Put every URL "
                   "you rely on into the JSON as the schema asks.)")
    schema_at = max(system.rfind("Respond with"), system.rfind("Return ONLY"),
                    system.rfind("Output ONLY"), system.rfind("Return a ```json"))
    if schema_at >= 0:
        prompt += ("\n\nFINAL OUTPUT RULE: your final reply must be ONLY the JSON described "
                   "below, with exactly those keys, inside one ```json fenced block. No prose "
                   "before or after it.\n\n" + system[schema_at:])
    model = os.getenv("HERMES_LLM_MODEL", "gpt-5.6-terra")
    provider = os.getenv("HERMES_LLM_PROVIDER", "openai-codex")
    with tempfile.TemporaryDirectory(prefix="rfyl-llm-") as cwd:
        qf = os.path.join(cwd, "prompt.txt")
        with open(qf, "w", encoding="utf-8") as f:
            f.write(prompt)
        cmd = [exe, "chat", "-Q", "--oneshot", "--query-file", qf, "--provider", provider,
               "-m", model, "--ignore-rules", "--source", "rfyl", "--max-turns",
               str(max_web_uses + 3 if web_search else 2),
               "-t", "web" if web_search else "todo"]
        if effort:
            cmd += ["--reasoning", effort]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", cwd=cwd,
                                  timeout=int(os.getenv("LLM_TIMEOUT_S", "900")))
        except subprocess.TimeoutExpired:
            fail("hermes chat timed out")
    out = "\n".join(l for l in (proc.stdout or "").splitlines()
                    if not l.strip().startswith("session_id:")).strip()
    if proc.returncode != 0 or not out:
        fail(f"hermes chat failed (exit {proc.returncode}): {((proc.stderr or '') + out)[-800:]}")
    urls = sorted(set(re.findall(r"https?://[^\s\)\]\"'>,`]+", out)))
    return {"text": out, "sources": [{"url": u, "title": ""} for u in urls],
            "stop_reason": "end_turn", "models": [f"{provider}/{model}"]}


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
    """Run one completion. Returns {text, sources, stop_reason}.

    `sources` is a de-duplicated list of {url, title} harvested from any
    web_search results (API backend only), so callers can cross-check the
    model's citations.

    `no_thinking=True` disables adaptive thinking - use it for pure JSON
    extraction so thinking tokens don't eat into `max_tokens` and truncate
    the output.
    """
    if BACKEND == "hermes_cli":
        return _complete_hermes(system, user, web_search=web_search,
                                max_web_uses=max_web_uses, effort=effort)
    if BACKEND == "claude_cli":
        return _complete_cli(system, user, web_search=web_search,
                             max_web_uses=max_web_uses, effort=effort)
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
