# workflows/

Plain-language SOPs. One file per repeatable job. The agent reads these,
then orchestrates the tools in `tools/`.

## Rules

- Don't create or overwrite a workflow without asking first.
- Keep them current: when you learn a constraint, rate limit, or better
  method, update the relevant workflow (with permission).
- Every workflow follows `_TEMPLATE.md`.

## Index

- [`generate_newsletter.md`](generate_newsletter.md) — weekly Letterboxd Rushes email
  -> Run For Your Life blog post (roundup + horror deep-dive) -> email approval -> publish
  to the static site + hand Josh a social teaser.
