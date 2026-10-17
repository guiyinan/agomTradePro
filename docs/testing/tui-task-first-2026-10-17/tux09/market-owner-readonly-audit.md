# TUX09 market-context owner read-only audit

## Scope

This note only compares the current operator owner payload with the TUX09 market-context projector and records the evidence kept by `browser-final-07`. No source, test, metadata, fixture, database, or generated file was changed for this audit, and no Django/pytest/browser command was run.

## Owner contract and projector compatibility

The live action is `today-focus.market-context`, registered at `apps/terminal/infrastructure/tui_metadata_runtime_injection_task_focus.py:19-30` with endpoint `/api/tui/operator/home/market_context/` and read-only GET semantics. The TUI action transport wraps it in the normal action-run request; the saved browser request artifacts therefore show a POST to `/api/tui/actions/today-focus.market-context/run/` with an empty `params` object.

`TuiOperatorHomeSectionView.get` at `apps/terminal/interface/api_views.py:707-725` calls `build_operator_home_section_payload`. The owner builder at `apps/terminal/application/tui_operator_services.py:194-207` returns `_section_payload(_operator_home_section_rows(...))`. `_market_context_rows` at `:394-401` supplies four rows: regime, policy, pulse, and decision data.

The owner envelope is:

```text
{
  rows: list[object],
  total: int,
  status: highest row severity,
  badge: {blocked_count: int, warning_count: int},
}
```

The concrete row shapes are source-backed:

- `_regime_market_row` (`tui_operator_services.py:424-469`) includes `area`, `status`, `summary`, `freshness`, `reliability`, `must_not_use_for_decision`, `blocking_reason`, `observed_at`, and `severity` (plus owner navigation/machine fields).
- `_policy_market_row` (`:472-490`) includes `area`, `status`, `summary`, `freshness`, `reliability`, `observed_at`, and `severity`. It does not publish a separate `must_not_use_for_decision` or `blocking_reason` key.
- `_pulse_market_row` (`:493-539`) includes the freshness/reliability/observation fields and publishes the restriction fields; its no-snapshot branch is explicitly blocked.
- `_decision_data_market_row` (`:542-561`) includes `area`, `status`, `summary`, `freshness`, `reliability`, `observed_at`, and `severity`. Its owner blocked reason is folded into `summary` and it does not publish the separate restriction fields.

`project_today_focus_market_context_payload` at `apps/terminal/application/tui_task_focus_result.py:358-493` requires only an object with a list `rows`, an integer `total` equal to the row count (maximum 12), and per-row `area` and `status`. Freshness, reliability, summary, observation time, blocking reason, severity, and `must_not_use_for_decision` are consumed as optional fields. Consequently the actual `_section_payload` shape is structurally compatible: all required keys are present and the four owner rows satisfy the required row keys.

The owner envelope has no `success` or canonical `outcome`. The projector intentionally accepts that for this action (`_owner_gate(..., require_success=False)` at `tui_task_focus_result.py:136-169`), preserves the owner `status` as `owner_status`, and leaves `outcome` absent rather than inventing `success`. A top-level owner `status` of `blocked` therefore remains owner status; row `severity` and explicit restriction fields provide the visible limitations. This is compatible with the existing missing-outcome contract and does not prove financial readiness.

Two disclosure limitations remain in the existing shape, but neither is a parser mismatch: policy and decision-data rows may render `must_not_use_for_decision` and `blocking_reason` as unavailable because those keys are not emitted separately. Decision-data `summary` still carries the first owner blocked reason. The projector preview also exposes only the first four rows and does not put `blocking_reason` in its compact preview; the full nested section retains the row columns. This is a presentation limitation to verify separately from the transport failure.

## Browser-final-07 evidence

`browser-final-07.json` records an exit code of `0` and stdout `7 passed in 133.21s`; its SHA-256 is `CFD0BCD0D133D9444F6B61E15C2F2D14FD3EA9A5D7C71EE84912A56AF0896D69`. `browser-final-07.log` contains only the seven-pass stdout and has SHA-256 `258EA32D0FC7E16D9B13D462238DCBFD524E389AF114D4D7005AA0C761AD2463`; it contains no stderr stream. The saved `today-1440-52-selector.json` request artifact (SHA-256 `8FC5AE7A47230AEFF5843CC0E326459435EAFADAD36787E737C481AF7FF0867A`) records the market action request but does not store response status or response body.

The corresponding `today-1440-52-selector.png` and `today-390-52-selector.png` show the market panel in the bounded unavailable state: “服务正在恢复” / “市场环境读取失败，请稍后重试”, with a retry control. The browser test deliberately accepts the unavailable branch (`tests/component/test_tui_task_focus_browser.py:911-924` accepts owner statuses `200/403/404/502/503` and only inspects the projected model when status is `200`). Therefore the final seven-pass result proves the bounded UI behavior, not a successful owner 2xx market payload.

The final JSON does not include the market response status, so it is not possible to attribute that exact final request to a numeric 503 from `browser-final-07` alone. The same feature-run evidence does contain the direct cause for the readiness failure: `browser-02.log`, `browser-03.log`, and `browser-05.log` record `Trading calendar unavailable: SystemAuditCompositionUnavailable`, `MARKET_CALENDAR_UNAVAILABLE - Exchange trading calendar is unavailable`, and `GET /api/tui/operator/governance-queue/ - 503`. Those logs are predecessor run artifacts in the same isolated browser fixture lineage, not a re-run performed here.

The source causal chain is concrete. `apps/data_center/application/market_calendar.py:100-123` turns missing/stale calendar coverage or `SystemAuditCompositionUnavailable` into an empty session result. `market_thermometer_dates.py:33-44` then raises `DataFetchError(code="MARKET_CALENDAR_UNAVAILABLE")` when no safe session can be resolved. `get_decision_data_readiness_payload` calls `build_current_payload(auto_calculate=False)` at `apps/data_center/application/interface_services_decision_sync.py:213-215`; `market_thermometer_calculate.py:184-193` resolves the current date when no explicit date is supplied. `_decision_data_market_row` is one of the four rows built by `_market_context_rows`, and `TuiOperatorHomeSectionView.get` has no catch beyond unknown section (`api_views.py:712-725`). Thus missing calendar readiness is sufficient to produce a bounded server-unavailable response through the normal exception mapping. This supports “fixture calendar/readiness coverage is missing” as the cause indicated by the sibling logs; the final artifact does not separately prove a distinct governance-config omission.

## Boundary and next verification

No normal-owner-success payload was observed in these artifacts. A future narrow acceptance must seed or otherwise provide the required calendar/readiness evidence, capture the actual `/api/tui/operator/home/market_context/` response status/body, and exercise a 2xx envelope through the existing action executor. It should then assert the four-row owner shape above, preservation of each row's own `observed_at`, and the missing `success/outcome` behavior without upgrading it to a fabricated success. The current unavailable screenshots and pass result must remain recorded as a valid bounded recovery case, not as evidence that the owner market facts were successfully read.
