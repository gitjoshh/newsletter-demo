# tools/

Deterministic Python scripts. One script = one job. No reasoning here.

## Conventions

- **Runnable from project root:** `python tools/<name>.py --flag value`
- **Args via `argparse`**, never interactive prompts.
- **Output contract:** on success, print one JSON object to stdout and exit 0.
  On failure, write `ERROR: ...` to stderr and exit non-zero.
- **Secrets** come from `.env` via `tools/lib/common.py` (`require_env`), never
  hardcoded, never passed on the command line.
- **Temp/intermediate files** go in `.tmp/` via `common.tmp_path(...)`.
- **Idempotent where possible.** Re-running should not double-send or corrupt.

## Shared helpers

`tools/lib/common.py` provides: `load_env`, `require_env`, `tmp_path`,
`emit(dict)`, `fail(msg)`, and `ROOT` / `TMP` / `WORKFLOWS` paths.

## Template

```python
"""One-line description of what this tool does."""
import argparse
from lib.common import require_env, emit, fail, tmp_path  # noqa: F401

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    args = ap.parse_args()

    # ... do the deterministic work ...

    emit({"status": "ok", "result": "..."})

if __name__ == "__main__":
    main()
```

Running `python tools/<name>.py` puts `tools/` on `sys.path`, so
`from lib.common import ...` resolves. Always invoke tools that way from the
project root.
