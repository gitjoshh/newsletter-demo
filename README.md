# newsletter-demo

A WAT-framework project (Workflows, Agents, Tools) that turns the weekly Letterboxd
**Rushes** digest email into a published *Run For Your Life* blog post (a multi-film
roundup plus one horror deep-dive, running thread throughout), gated by an email
approval, and hands back a ready-to-post social teaser + photo.

No mailing list, no paid platform. The blog is a static site on your own domain
(Cloudflare Pages). Facebook/Threads posting stays manual — the pipeline just gives you
the finished teaser and the photo.

## Layout

```
CLAUDE.md              # WAT operating contract
workflows/
  generate_newsletter.md   # the SOP the scheduled routine follows
tools/                  # deterministic Python steps
  lib/common.py         # env, paths, JSON I/O
  lib/llm.py            # Anthropic Messages wrapper (model id, web search, JSON extract)
  lib/images.py         # Openverse -> Pexels -> Unsplash stock-photo adapters
  lib/site.py           # tiny static-site generator (post pages, index, RSS)
templates/              # Jinja: post / index / rss / two email templates / shared CSS
config/
  newsletter.json       # voice, structure, revision cap, Gmail label
  site.json             # site title, base URL, git remote/branch
  style.json            # colour + type tokens (site pages and the email preview)
state/                  # per-issue working files + approval tracking (gitignored)
samples/                # a real Rushes .eml, a past blog post, the old Sonnet prompt
.env                    # secrets (gitignored) — copy from .env.example
```

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in keys
```

`.env` needs: `ANTHROPIC_API_KEY`, `TMDB_API_KEY` (film scene stills),
`PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY` (stock / mood photos), and `SITE_REPO_PATH`
(a plain local folder — not a git repo). `OPENVERSE_CLIENT_ID/SECRET` optional (higher
rate limit). Set `ANTHROPIC_MODEL=claude-sonnet-5` to lower per-run cost.

Images: film blurbs + the hero use **TMDB scene stills** (editorial use of studio press
material, credited to TMDB — not a free licence). Stock/CC photos are used only for the
deep-dive's running/mood shot and as the teaser photo posted to social.

## One-time prerequisites

1. **Hosting** — no GitHub needed. Make a folder for the site, put its path in
   `SITE_REPO_PATH`. Create a Cloudflare Pages project (free) named to match
   `config/site.json` -> `cf_project`, then either run `npx wrangler login` once or set
   `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` in `.env`. Put the project's public
   URL (`https://<project>.pages.dev`, or a custom domain later) in `config/site.json` ->
   `base_url`.
2. Get a free TMDB API key (themoviedb.org), plus Pexels + Unsplash keys.
3. Confirm the Gmail filter that labels the Rushes email; set the label name in
   `config/newsletter.json` -> `workflow.letterboxd_gmail_label`.
4. Create the scheduled Claude Code routine (`/schedule`) pointed at
   `workflows/generate_newsletter.md`, with the Gmail connector available to it.
5. Keep the old Make scenario running until one full cycle succeeds here, then disable it.

## Run a tool directly

```bash
python tools/<name>.py --help
```

## Verify the pipeline (offline-ish, using the sample email)

```bash
python tools/parse_rushes_email.py --eml "samples/Letterboxd Rushes for joshualaurie.eml" --out .tmp/rushes.json
python tools/find_horror_angle.py --source .tmp/rushes.json --out .tmp/horror_angle.json      # Anthropic + web search
python tools/draft_post.py --source .tmp/rushes.json --horror .tmp/horror_angle.json --out .tmp/draft.json
python tools/draft_teaser.py --draft .tmp/draft.json --out .tmp/teaser.json
python tools/fetch_images.py --draft .tmp/draft.json --horror .tmp/horror_angle.json --out .tmp/images.json
python tools/build_preview.py --draft .tmp/draft.json --images .tmp/images.json --out .tmp/preview.html
# open .tmp/preview.html, then (use a scratch folder for --repo):
python tools/publish_site.py --draft .tmp/draft.json --images .tmp/images.json --teaser .tmp/teaser.json --repo .tmp/site
python tools/render_ready_email.py --teaser .tmp/teaser.json --images .tmp/images.json \
  --url "https://run-for-your-life.pages.dev/posts/<slug>/" --title "<title>"
```

Steps 2-5 need API keys. `parse_rushes_email`, `build_preview`, `publish_site` (without
`--deploy`), and `render_ready_email` run with no network. Add `--deploy wrangler` to
`publish_site.py` for the real deploy.
