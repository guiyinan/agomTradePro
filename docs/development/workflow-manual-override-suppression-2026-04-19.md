# Workflow Manual Override Suppression (2026-04-19)

## Background

Dashboard main workflow previously surfaced long-lived `AlphaCandidate` rows whose source
`AlphaTrigger` was `MANUAL_OVERRIDE`. In local/dev environments this caused old manually
created ideas such as `600519.SH` / `300750.SZ` to keep appearing as if they were current
system-generated workflow candidates.

## Current Rule

- Dashboard automatic workflow candidate list must exclude candidates whose source trigger is
  `MANUAL_OVERRIDE`.
- When a unified recommendation is marked `IGNORED`, its linked source candidates are cancelled.
- The linked source triggers are also soft-cancelled so batch candidate generation does not
  recreate the same ignored workflow prompt.
- The ignore action itself remains recorded on `UnifiedRecommendationModel` through
  `user_action=IGNORED`, `user_action_note`, and `user_action_at`, so later review/replay can
  reconstruct what was ignored and why.

## Why

- `MANUAL_OVERRIDE` represents human-injected ideas, not fresh model/rule output.
- Ignored recommendations should stop prompting downstream workflow surfaces, not merely disappear
  from one list view.
- Review data must remain auditable, so suppression uses status transitions and user-action fields
  rather than hard deletion.
