# Alpha / Workspace Consistency Guardrail

> Added: 2026-06-05

## Purpose

The decision workspace must not silently show stale recommendations while the Alpha ranking has newer tickets. This guardrail compares the persisted Alpha ranking snapshot with the latest workspace recommendations and reports freshness, overlap, candidate origin, and runtime Qlib provider status.

## Runtime Check

The readiness payload includes:

```text
alpha_workspace_consistency
```

It is exposed through:

```text
GET /api/ready/
python manage.py healthcheck --json
```

The check returns `warning` instead of failing readiness when recommendations are stale. Operators should refresh the workspace recommendation chain, but the site can keep serving traffic.

## Checked Signals

- Latest Alpha ranking trade date and top codes from `alpha_score_cache`
- Latest workspace recommendation update time and codes from `decision_unified_recommendation`
- Alpha rank candidate origin via `source_candidate_ids` prefix `alpha_rank:`
- Runtime Alpha provider health from `AlphaService.get_provider_status()`

## Warning Codes

- `alpha_ranking_empty`: no persisted Alpha ranking is available.
- `workspace_recommendations_empty`: workspace has no recommendations for the inspected account.
- `workspace_recommendations_stale`: workspace latest update lags Alpha latest trade date beyond the allowed window.
- `workspace_alpha_overlap_low`: workspace recommendations do not overlap enough with current Alpha top ranks.
- `workspace_missing_alpha_rank_origin`: workspace recommendations lack Alpha ranking candidate provenance.
- `alpha_qlib_provider_missing`: runtime Alpha provider status does not include `qlib`.
- `alpha_qlib_provider_degraded`: Qlib is degraded/unavailable, so rankings may be coming from cache fallback.

## CI Coverage

The logic is covered by:

```text
tests/guardrails/test_alpha_workspace_consistency_guardrail.py
tests/unit/decision_rhythm/test_alpha_workspace_consistency.py
tests/unit/test_alpha_workspace_consistency_snapshots.py
```

`scripts/select_tests.py` includes these tests for `decision_rhythm` changes, and the guardrail test is part of the core Logic Guardrails fallback set.
