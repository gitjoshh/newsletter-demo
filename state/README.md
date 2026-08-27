# state/

Persistent pipeline state. Unlike `.tmp/`, nothing here is disposable — it tracks
which Rushes emails have been processed and where each issue is in the
approve/revise/publish loop. Everything except this file is gitignored.

## Files

### `last_processed.json`
```json
{ "last_rushes_msg_id": "<gmail message id>", "last_rushes_date": "2026-07-23" }
```
Written after an issue reaches `done`. The routine ignores any Rushes email at or
behind this marker.

### `issues.json`
An array of issue records, newest last:
```json
[
  {
    "issue_id": "2026-07-20-running-from-the-odyssey",
    "rushes_msg_id": "<gmail message id>",
    "approval_thread_id": "<gmail thread id>",
    "status": "drafting | awaiting_approval | revising | publishing | done | failed",
    "revision_count": 0,
    "post_url": null,
    "created_at": "2026-07-24T09:00:00Z",
    "updated_at": "2026-07-24T09:12:00Z",
    "paths": {
      "dir": "state/issues/2026-07-20-running-from-the-odyssey",
      "rushes": ".../rushes.json",
      "horror_angle": ".../horror_angle.json",
      "draft": ".../draft.json",
      "teaser": ".../teaser.json",
      "images": ".../images.json",
      "preview": ".../preview.html"
    }
  }
]
```

### `issues/<issue_id>/`
All per-issue working files (the JSON artifacts each tool writes, the saved Rushes
email HTML, fetched images, `preview.html`). Safe to delete once `status` is
`done` and you don't need the record.

## Status transitions

```
(new Rushes email)  -> drafting -> awaiting_approval
awaiting_approval + reply "approve"          -> publishing -> done
awaiting_approval + reply "revise: <notes>"  -> revising   -> awaiting_approval  (revision_count++)
any step throws                              -> failed  (alert email; artifacts kept)
```
