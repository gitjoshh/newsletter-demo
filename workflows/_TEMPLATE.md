# Workflow: <name>

## Objective
What this workflow produces and why. One or two sentences.

## Trigger
When the agent should run this (a request phrasing, a schedule, an upstream event).

## Inputs
| Input | Source | Required | Notes |
|-------|--------|----------|-------|
| e.g. topic | user | yes | free text |

## Tools used
List in execution order. Link to the script and note what it returns.
1. `tools/<script>.py` — what it does, key args, output shape.

## Steps
1. ...
2. ...
3. ...

## Output
Where the deliverable lands (cloud service + location) and its format.
Intermediates in `.tmp/` and what they are.

## Edge cases & failure handling
- Condition -> what to do.
- Known rate limits / timing quirks.

## Change log
- YYYY-MM-DD: created.
