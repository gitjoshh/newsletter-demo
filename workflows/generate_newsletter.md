# Workflow: generate_newsletter

## Objective
Turn the weekly Letterboxd "Rushes" digest email into a published *Run For Your Life*
blog post (multi-film roundup + one horror deep-dive, running thread throughout), gated
by an email approval from Josh, then hand Josh a ready-to-post social teaser + photo.

## Trigger
A scheduled Claude Code routine, roughly every 4 hours. There is no push trigger; each
run polls Gmail. The routine does two things per run, in this order:

1. **Advance an open issue.** If `state/issues.json` has an issue with status
   `awaiting_approval`, read its Gmail thread (`approval_thread_id`) for a new reply from
   Josh and act on it.
2. **Start a new issue.** Otherwise, search the Letterboxd Gmail label for a Rushes email
   newer than `state/last_processed.json`. If one exists, run the new-issue path.

If neither applies, do nothing.

## Inputs
| Input | Source | Required | Notes |
|-------|--------|----------|-------|
| Rushes email | Gmail label (`config/newsletter.json` -> `workflow.letterboxd_gmail_label`, from `robot@letterboxd.com`, subject contains "Letterboxd Rushes") | yes | one per week |
| Approval reply | Josh, in the approval email thread | yes (to publish) | `approve` / `revise: <notes>` |
| `config/newsletter.json` | repo | yes | voice, structure, revision cap |
| `config/site.json` | repo | yes | site title, base URL, git remote/branch |
| `.env` | repo | yes | `ANTHROPIC_API_KEY`, `TMDB_API_KEY`, `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY`, `SITE_REPO_PATH` (+ Cloudflare login or `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID`) |

## Tools used
In execution order (all run from the project root, all print one JSON object):

1. `tools/parse_rushes_email.py --eml <saved.html> --out state/issues/<id>/rushes.json`
2. `tools/find_horror_angle.py --source rushes.json --out state/issues/<id>/horror_angle.json` — Anthropic + web search
3. `tools/draft_post.py --source rushes.json --horror horror_angle.json --out .../draft.json` (add `--revision "<notes>" --prev .../draft.json` on a revise)
4. `tools/draft_teaser.py --draft draft.json --out .../teaser.json`
5. `tools/fetch_images.py --draft draft.json --horror horror_angle.json --mood-count 1 --out-dir state/issues/<id>/images --out .../images.json` — TMDB scene stills (hero + one per film blurb) + one stock running/mood photo for the deep-dive
6. `tools/build_preview.py --draft draft.json --images images.json --out .../preview.html`
7. `tools/classify_reply.py --thread-text <reply.txt>` — on an approval reply
8. `tools/publish_site.py --draft draft.json --images images.json --teaser teaser.json --deploy wrangler --push` — on approve; builds the site, `npx wrangler pages deploy public/`, and pushes `content/` so the post survives the next fresh checkout
9. `tools/render_ready_email.py --teaser teaser.json --images images.json --url <post_url> --title "<title>"` — on approve; the teaser photo it names is a stock/CC image (safer to post than a studio still)
10. `tools/state_sync.py -m "<what changed>" [--done <issue_id>]` — after EVERY state change; commits + pushes `state/` so the next scheduled run sees it

Gmail send/read is done by the routine itself through the Gmail connection, not a tool.

## Steps

### A. New issue
1. Fetch the Rushes email; save its HTML body to `state/issues/<id>/rushes_email.html`.
   `<id>` = `<week_of>-<slug once drafted>`; use `<week_of>-pending` until the slug exists.
2. Append an issue record to `state/issues.json` with status `drafting`, `rushes_msg_id`,
   `revision_count: 0`.
3. Run tools 1 -> 2 -> 3 -> 4 -> 5 -> 6. If any tool exits non-zero, go to **Failure**.
4. Rename the issue dir/id to include the real slug from `draft.json`; update `paths`.
5. Compose the approval email:
   - Subject: `Draft: <title> (issue of <week_of>)`
   - Body: the rendered `preview.html` (it is self-contained; inline it as the HTML body).
     Prepend the teaser text and the line: *Reply `approve` to publish, or `revise:` then
     your notes.* Surface any `warnings` from the tool outputs.
   - Send it to Josh. Record the resulting `approval_thread_id`. Set status
     `awaiting_approval`, `updated_at` now.

### B. Reply = approve
1. `publish_site.py ... --deploy wrangler` -> capture `post_url` (and `deploy.deploy_url`).
   If it exits non-zero, go to **Failure** (do not mark done).
2. `render_ready_email.py --url <post_url>` -> capture `teaser_text` and `attach_image`.
3. Send the "ready to post" email to Josh (reply on the same thread): subject
   `Ready to post: <title>`, body = `ready_email.html`, attach the `attach_image` file.
4. Set status `done`. Write `state/last_processed.json` with this Rushes `msg_id` + date.

### C. Reply = revise
1. Save Josh's reply text (strip quoted history) to `state/issues/<id>/reply.txt`.
2. `draft_post.py --revision "<notes>" --prev draft.json` (overwrite `draft.json`), then
   `draft_teaser.py`, `build_preview.py` again.
3. `revision_count += 1`. If it now exceeds `workflow.revision_cap`, email Josh that the
   loop is paused and he should take it from here; leave status `awaiting_approval` and
   stop revising.
4. Otherwise send a fresh approval email on the same thread ("Revised draft (v<n>): ...").
   Keep status `awaiting_approval`.

### D. Reply = unclear
Reply on the thread asking Josh to confirm with `approve` or `revise: <notes>`. Leave
status `awaiting_approval`. Do not re-send the whole draft.

### Failure
Set the issue status to `failed`. Email Josh: which step failed, the tool's stderr, and
the path to the issue dir (all artifacts are kept). Do not advance
`last_processed.json`, so a fixed re-run can pick the issue back up.

## Output
- **Deliverable:** a published post at `<site base_url>/posts/<slug>/` (Cloudflare Pages
  deploys on the `publish_site.py` push) and a "ready to post" email with the teaser +
  photo. The published post is the archive of record.
- **Intermediates:** everything under `state/issues/<id>/` (regenerable from the saved
  Rushes email except for Josh's replies).

## Edge cases & failure handling
- **No Rushes email this week** — no-op; try again next run.
- **`parse_rushes_email` warns "parsed 0 items"** — the email layout changed. Do not send
  a thin draft; email Josh the raw email and stop.
- **Every popular film is non-horror** — `find_horror_angle.py` already falls back to the
  week's lists / list sample films; if it returns `interpretation: true`, the approval
  email flags that the horror link is a thematic reading, not a fact.
- **TMDB has no still for a film blurb** — `fetch_images.py` skips that blurb's image and
  records a warning; the post still has the hero still and the other blurb stills.
- **TMDB has no still for the deep-dive film** — the hero falls back to a stock photo from
  the first `image_queries` phrase.
- **No stock mood photo found** — the deep-dive publishes without its photo (warning only).
- **`fetch_images.py` fails entirely** — usually a missing `TMDB_API_KEY` /
  `PEXELS_API_KEY` / `UNSPLASH_ACCESS_KEY`. Treat as **Failure**.
- **`wrangler pages deploy` fails** — usually not logged in (`npx wrangler login`) or the
  Pages project name in `config/site.json` (`cf_project`) does not exist yet. Treat as
  **Failure**; the post JSON + built `public/` are already on disk, so re-running just
  step B recovers it once the deploy is fixed.
- **Revision loop** — capped by `workflow.revision_cap` (default 3), then handed back to
  Josh.
- **Model refusal / API error** — the tool exits non-zero with the message on stderr;
  treat as **Failure**.
- **Cost** — one issue is a handful of Anthropic calls (draft is the big one). Set
  `ANTHROPIC_MODEL=claude-sonnet-5` in `.env` to cut per-run cost if desired.

## Change log
- 2026-08-27: created. Infographic generation intentionally out of scope; if added later
  it becomes a second visual lane (matplotlib for data charts, HTML-screenshot for concept
  cards) feeding `fetch_images.py`'s slot in the sequence.
- 2026-08-27: images reworked. Stock libraries have no film imagery, so film blurbs and the
  hero now use **TMDB scene stills** (editorial use of studio press material, credited to
  TMDB); stock/CC photos are kept only for the deep-dive's running/mood shot and as the
  teaser photo.
- 2026-08-28: primary personal lens changed from running to **boxing** (running/cardio kept
  as the adjacent thread). `find_horror_angle.py` renamed `running_tie_in` -> `training_tie_in`.
  Hosting is a **public GitHub repo + Cloudflare Pages** deployed by `wrangler` with a
  Cloudflare API token, run by a scheduled cloud routine (see `/schedule`).
- 2026-08-28: cloud-run hardening after first live cycle - `RFYL_ANTHROPIC_KEY` (env strips
  `ANTHROPIC_API_KEY`), network policy **Full**, deploy-before-git + detached-HEAD-safe
  non-fatal push, images resolved next to `images.json`, draft email is a lightweight body
  with `preview.html` attached, teaser photo served from the site CDN (no attachment).
- 2026-08-28: **real stories** step - `draft_post.py` first pass emits `questions` and keeps
  invented anecdotes lightly sketched; `--personal "<prose>"` folds Josh's own material in.
  `classify_reply.py` gains a `personal_input` intent. The draft email leads with the
  questions; Josh replies with a paragraph or two, gets a v2, then approves. Titles never
  contain a colon (`draft_post.py` guard keeps the part before it).
