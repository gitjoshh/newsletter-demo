# Workflow: Penny editorial loop (Telegram)

Replaces the Claude Code cloud routines + Gmail approval loop. Hermes runs it:
a weekly no-agent cron posts the local cinema shortlist to Penny (Telegram), and
Penny (the Hermes gateway agent) runs these tools when Josh replies.

## Billing
- Every LLM call inside `tools/` goes through `tools/lib/llm.py` with
  `LLM_BACKEND=claude_cli` and `ANTHROPIC_MODEL=claude-haiku-5-5` (`.env`). That
  shells out to the Claude Code CLI (`claude -p`), so it uses Josh's **Claude
  subscription** login, not an API key. The wrapper strips `ANTHROPIC_API_KEY`
  from the child env so it cannot silently bill the API.
- Penny's own chat turns use the Hermes default model (OpenRouter), not the
  subscription. Hermes cannot use a Claude Pro login for its own inference.

## Trigger
- Hermes cron `RFYL now showing (SM City Baguio)`: Wednesdays 10:00 PHT,
  script `~/.hermes/scripts/rfyl_now_showing.py`, delivered to Telegram.
- Everything after that is reactive: Josh replies to Penny.

## Rules (from the editorial-content-automation skill)
- Never draft first-person content without at least one real note from Josh
  (text or voice). Save his words verbatim; never invent a viewing or opinion.
- Showtimes are advisory: say "verify before leaving".
- Publishing needs the literal word `approve`. Enthusiasm is not approval.
- No em dashes in anything written for Josh's site or socials.

## Steps (run from the repo root, `F:\Claude Code\Business\newsletter-demo`)
Issue dir `D = state/issues/<YYYY-MM-DD>-<slug or pending>/`.

### 1. Josh replies with picks or notes
Append his words verbatim to `D/notes.md` (create `D` as `<today>-pending`).
Ask at most one short follow-up (what stuck with you, any training link).

### 2. Josh says "draft it" (and notes exist)
```
python tools/now_showing.py --out D/source.json --no-snapshot
python tools/find_horror_angle.py --source D/source.json --out D/horror_angle.json
python tools/draft_post.py --source D/source.json --horror D/horror_angle.json --out D/draft.json
python tools/draft_post.py --source D/source.json --horror D/horror_angle.json --personal "<D/notes.md text>" --prev D/draft.json --out D/draft.json
python tools/draft_teaser.py --draft D/draft.json --out D/teaser.json
python tools/fetch_images.py --draft D/draft.json --horror D/horror_angle.json --mood-count 1 --out-dir D/images --out D/images.json
python tools/build_preview.py --draft D/draft.json --images D/images.json --teaser D/teaser.json --out D/preview.html --email-out D/preview_email.html --deploy-preview
```
Rename `D` to `<date>-<slug from draft.json>`. Send Josh: title, the teaser, the
preview link (or `D/preview.html` as a file if the preview deploy failed), any
`questions` from draft.json, and "Reply approve, revise: <notes>, or photo: <idea>".

### 3. Replies
- `revise: <notes>` -> `draft_post.py --revision "<notes>" --prev D/draft.json --out D/draft.json`, then teaser + preview again. Cap: 2 revisions, then hand it back.
- `photo: <idea>` -> `fetch_images.py ... --mood-query "<idea>"`, then preview again. Does not count as a revision.
- more personal notes -> append to `D/notes.md`, rerun the `--personal` pass.
- `approve` ->
```
python tools/publish_site.py --draft D/draft.json --images D/images.json --teaser D/teaser.json --deploy wrangler --push
python tools/render_ready_email.py --teaser D/teaser.json --images D/images.json --url <post_url> --title "<title>"
python tools/state_sync.py -m "issue <ID>: published"
```
  Verify `post_url` loads, then send Josh the post URL, the teaser text, and the
  teaser photo file for manual Facebook/Threads posting.

### Failure
Any tool exiting non-zero: tell Josh which step failed and the `ERROR:` line.
Keep `D/` intact so the step can be rerun.
