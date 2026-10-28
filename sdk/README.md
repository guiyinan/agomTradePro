# AgomTradePro SDK & MCP Server

Python SDK and MCP (Model Context Protocol) Server for AgomTradePro - Macro Environment Admission System.

## Overview

AgomTradePro SDK provides two ways to interact with the AgomTradePro system:

1. **Python SDK** - Full-featured Python client for complete system access
2. **MCP Server** - AI-native tools for Claude Code and other AI agents

Regional data egress configuration is available through the default governed
MCP capabilities and `client.data_center` SDK methods. See the
[egress configuration guide](../docs/development/data-egress-mcp-configuration.md)
for discovery, confirmation, credentials and diagnostics.

## Optional integration package

Browser/TUI users and ordinary CLI callers do **not** install this package or
any local Agent/model runtime. They use the AgomTradePro B/S application and
the server-owned Agent Runtime directly. The commands below are only for a
developer or managed integration that intentionally needs the typed remote
SDK/MCP transport; they never install or run a provider-backed Agent locally.

```bash
# From the AgomTradePro project
cd D:/githv/agomTradePro/sdk

# Optional: install the thin remote API/MCP transport for an integration host
pip install -e .

# Optional integration-test dependencies
pip install -e ".[dev]"

# Optional client-side dataframe helpers (not an Agent runtime)
pip install -e ".[pandas]"
```

## Compatibility

- Python: `>=3.11`
- MCP Python SDK: `mcp>=1.20,<2`

Verify installed versions:

```bash
python -m pip show agomtradepro-sdk mcp
```

## Server-side Agent/CLI boundary

AgomTradePro is a B/S system. User requests must reach the server-side Agent
runtime through the authenticated web/API/TUI boundary; the model provider,
MCP orchestration, confirmation and audit flow stay on the server. The SDK is
only a typed client library. It does not publish a provider-backed local
`agomtradepro-agent` executable, a local model-key setup, or a local venv
installer. The queued server route remains fail-closed until its runtime gate
is explicitly enabled.

Any future command-line wrapper must be a thin server API client: it may carry a
scoped API token, but it must never accept, store, or forward a provider key on
the user's workstation. This is a contract decision, not production/UAT
evidence; no VPS deployment is required for the local SDK tests.

## Authentication

AgomTradePro backend uses DRF Token authentication.

- Header format: `Authorization: Token <your_token>`
- SDK `api_token` can be either raw token or prefixed form (`Token ...` / `Bearer ...`).
- Token now supports two scopes:
  - `read_only`: only `GET/HEAD/OPTIONS`
  - `read_write`: allows write requests, but still cannot bypass backend role checks such as `staff` read / `superuser` write for Qlib config-center

Recommended:

- Give Codex / Claude Desktop / automation scripts a dedicated `read_only` token by default
- Only mint `read_write` tokens for workflows that really need mutation APIs

Generate a token for an existing user (example: `admin`):

```bash
cd D:/githv/agomTradePro
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from apps.account.infrastructure.models import UserAccessTokenModel; u=User.objects.get(username='admin'); t,key=UserAccessTokenModel.create_token(user=u, name='sdk-readme'); print(key)"
```

If you want a read-only token instead:

```bash
cd D:/githv/agomTradePro
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from apps.account.infrastructure.models import UserAccessTokenModel; u=User.objects.get(username='admin'); t,key=UserAccessTokenModel.create_token(user=u, name='sdk-readonly', access_level=UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY); print(key)"
```

## Quick Start

### Python SDK

```python
from agomtradepro import AgomTradeProClient

# Initialize client
client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# Get current regime
regime = client.regime.get_current()
print(f"Current regime: {regime.dominant_regime}")

# Check signal eligibility
eligibility = client.signal.check_eligibility(
    asset_code="000001.SH",
    logic_desc="PMI rising, economic recovery"
)

# Create signal
if eligibility["is_eligible"]:
    signal = client.signal.create(
        asset_code="000001.SH",
        logic_desc="PMI rising, economic recovery",
        invalidation_logic="PMI falls below 50",
        invalidation_threshold=49.5
    )
    print(f"Signal created: {signal.id}")
```

### MCP Server

Configure in `~/.config/claude-code/mcp_servers.json`:

```json
{
  "mcpServers": {
    "agomtradepro_local": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp.server"],
      "cwd": "D:/githv/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://127.0.0.1:8000",
        "AGOMTRADEPRO_API_BASE_URL": "http://127.0.0.1:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token_here",
        "AGOMTRADEPRO_DEFAULT_ACCOUNT_ID": "1"
      }
    }
  }
}
```

MCP audit writes automatically use the same `AGOMTRADEPRO_BASE_URL` origin and
`AGOMTRADEPRO_API_TOKEN`. A `read_only` token may write only its own audit
metadata; the backend binds `user_id` and `username` to the authenticated token.
Set `AGOMTRADEPRO_AUDIT_URL` only when audit ingest is hosted separately. Keep
`AUDIT_INTERNAL_SECRET_KEY` private to trusted service-to-service deployments.

You can also start MCP manually (for smoke testing):

```bash
agomtradepro-mcp
```

The core MCP surface includes `agom_get_agent_contract` and `agom_get_workflow_playbook`. Their versioned configuration is shipped at `agomtradepro_mcp/prompts/agent_contracts.json`; deployments may override it with `AGOMTRADEPRO_MCP_AGENT_CONTRACT_PATH`. The contract requires a structured `decision_summary` and explicitly forbids requesting or exposing hidden chain-of-thought. Server-side RBAC, Schema validation, confirmation and simulated-execution boundaries remain authoritative.

Recommended:

- repo `.mcp.json`: keep only `agomtradepro_local`
- client global config: split `agomtradepro_local` and `agomtradepro_prod`
- do not switch environments by editing one shared server entry

If your environment has a global proxy, set local bypass for loopback:

```bash
set NO_PROXY=127.0.0.1,localhost
set no_proxy=127.0.0.1,localhost
```

Then use directly in Claude Code:

```
User: What's the current macro regime?
Claude: [calls get_current_regime tool]
       Current regime: Recovery (growth up, inflation down)
```

## Configuration

Three methods (priority order):

1. **Constructor parameters**
2. **Environment variables**:
   - `AGOMTRADEPRO_BASE_URL`
   - `AGOMTRADEPRO_API_BASE_URL` (legacy alias, still supported)
   - `AGOMTRADEPRO_API_TOKEN`
   - `AGOMTRADEPRO_USERNAME`
   - `AGOMTRADEPRO_PASSWORD`
3. **Config files**:
   - `.agomtradepro.json` (current directory)
   - `~/.agomtradepro/config.json` (user directory)

## SDK Modules

| Module | Description |
|--------|-------------|
| `client.regime` | Regime determination - get current regime, calculate regime, history |
| `client.signal` | Investment signals - create, approve, check eligibility |
| `client.data_center` | Unified data center - provider status, indicator governance, macro/price/fund/news facts |
| `client.policy` | Policy events - status, event management, **workbench operations** |
| `client.backtest` | Backtesting - run, get results, equity curve, manual decision replay |
| `client.account` | Unified account management - accounts, positions, performance, broker trade import; old portfolio APIs remain compatibility-only |
| `client.simulated_trading` | Unified account trading/execution module; module name retained for compatibility |
| `client.equity` | Stock analysis - scoring, recommendations, financials |
| `client.fund` | Fund research - rank, screen, detail, NAV, style, holdings, performance |
| `client.sector` | Sector analysis - scoring, hot sectors, comparison |
| `client.strategy` | Strategy management - create/execute strategy, bind/unbind portfolio strategy, AI strategy config, DB-driven position rules |
| `client.realtime` | Real-time prices - market data, alerts, top movers |
| `client.rotation` | Rotation - recommendations, templates, per-account regime allocation configs |
| `client.alpha` | Alpha scoring + ops console bridges - scores, provider status, universes, health, factor exposure, inference/data ops |
| `client.dashboard` | Dashboard account view - auto-advisor console/query/weekly report outputs, Alpha candidates, history, async refresh status, and recommendation contract |
| `client.decision_workflow` | **Decision workflow (V3.4+)** - precheck, workspace recommendation bridge, transition plans, execution preview, funnel context |
| `client.pulse` | **Pulse + Navigator** - pulse snapshot/history, regime navigator, action recommendation |
| `client.decision_rhythm` | **Decision rhythm (V3.4+)** - submit, execute, cancel, get decision requests |
| `client.config_center` | **Config center** - unified config snapshot, Qlib runtime config, training profiles, training runs, trigger |

## MCP Tools

Dynamic MCP governance counts are not maintained in this guide. The machine source of truth is
[`governance/governance_baseline.json`](../governance/governance_baseline.json); field meanings
and verification commands are documented in
[`docs/governance/SYSTEM_BASELINE.md`](../docs/governance/SYSTEM_BASELINE.md).

Canonical API routing for SDK/MCP is documented in:

- [`docs/development/api-mcp-sdk-alignment-2026-03-14.md`](../docs/development/api-mcp-sdk-alignment-2026-03-14.md)

### Core Tools
- **Regime**: `get_current_regime`, `calculate_regime`, `get_regime_history`, `explain_regime`
- **Signal**: `list_signals`, `create_signal`, `check_signal_eligibility`, `approve_signal`
- **Data Center Macro**: `data_center_list_indicators`, `data_center_get_macro_series`, `data_center_sync_macro`
- **Backtest**: `run_backtest`, `get_backtest_result`, `get_backtest_equity_curve`, `run_decision_replay_backtest`
- **Policy**: `get_policy_status`, `get_policy_events`, `create_policy_event`
- **Alpha Trigger**: `list_alpha_candidates`, `get_alpha_candidate`, `update_alpha_candidate_status`
- **Auto Advisor**: `get_auto_advisor_decision_sheet`, `get_auto_advisor_console`, `ask_auto_advisor`, `get_auto_advisor_weekly_report`, `create_auto_advisor_weekly_report`, `list_auto_advisor_weekly_report_history`, `list_auto_advisor_notifications`

### Auto Advisor SDK/MCP

Personal auto-advisor is exposed through both Python SDK methods and native MCP tools:

- `client.decision_rhythm.advisor_sheet(account_id)` -> `/api/decision/advisor/sheet/`
- `client.dashboard.auto_advisor_console(account_id)` -> `/api/dashboard/auto-advisor-console/`
- `client.dashboard.auto_advisor_query(account_id, question)` -> `/api/dashboard/auto-advisor-query/`
- `client.dashboard.auto_advisor_weekly_report(account_id, as_of=None)` -> `/api/dashboard/auto-advisor-weekly-report/`
- `client.dashboard.create_auto_advisor_weekly_report(account_id, as_of=None)` -> generates and persists the weekly report
- `client.dashboard.auto_advisor_weekly_report_history(account_id=None, limit=20)` -> persisted weekly reports
- `client.dashboard.auto_advisor_notifications(account_id=None, limit=20)` -> persisted notification/output records

The matching MCP tools expose advisor sheet, dashboard console, natural-language Q&A, weekly report creation, persisted diary history, and notification output without adding any real trade execution path.

### Macro Governance Contract

Current macro governance contract after the 2026-05-03 repair:

- runtime truth source = `IndicatorCatalog` + `IndicatorUnitRule` + `data_center_macro_fact`
- staff governance console = `/data-center/governance/`
- MCP/SDK should still read/write only through canonical data-center APIs and tools
- runtime schedule / publication / period override metadata now begins to live in `IndicatorCatalog.extra`

High-risk code semantics that callers must now treat as canonical:

- `CN_GDP` = quarterly cumulative level
- `CN_GDP_YOY` = GDP YoY rate
- `CN_FIXED_INVESTMENT` = fixed investment cumulative level
- `CN_FAI_YOY` = fixed investment cumulative YoY rate
- `CN_SOCIAL_FINANCING` = monthly social financing flow
- `CN_SOCIAL_FINANCING_YOY` = monthly social financing flow YoY rate
- `CN_EXPORTS` = monthly export amount, display unit `亿美元`
- `CN_EXPORT_YOY` = monthly export amount YoY rate
- `CN_IMPORTS` = monthly import amount, display unit `亿美元`
- `CN_IMPORT_YOY` = monthly import amount YoY rate

Compatibility note:

- `CN_CPI_YOY` is retained only as a compatibility alias code. Canonical lookup should prefer `CN_CPI_NATIONAL_YOY`.
- callers should interpret macro runtime metadata in this priority order:
  - `series_semantics` / `paired_indicator_code` for meaning
  - `schedule_frequency` / `schedule_day_of_month` / `schedule_release_months` for cadence
  - `publication_lag_days` for freshness expectation
  - `orm_period_type_override` / `domain_period_type_override` for storage/runtime period semantics
- do not infer macro meaning or cadence solely from code suffixes such as `_YOY` / `_MOM` / `GDP`.

### Dashboard Alpha Contract

`client.dashboard.alpha_stocks(...)` and MCP `get_dashboard_alpha_candidates(...)` include a `contract` object. Agents should only treat the response as a recommendation when `contract.recommendation_ready=true`; `contract.async_refresh_queued=true` means scoped Qlib inference is still running, and `contract.must_not_treat_as_recommendation=true` means pending requests or refresh status must not be shown as current Alpha picks.

`client.dashboard.alpha_refresh(...)` and MCP `trigger_dashboard_alpha_refresh(...)` only queue backend inference for the account-driven pool. They never return recommendations directly.

Dashboard Alpha caller-controlled pool selection:

- `client.dashboard.alpha_stocks(..., pool_mode="strict_valuation" | "market" | "price_covered")`
- `client.dashboard.alpha_refresh(..., pool_mode="strict_valuation" | "market" | "price_covered")`
- MCP `get_dashboard_alpha_candidates(..., pool_mode=...)`
- MCP `trigger_dashboard_alpha_refresh(..., pool_mode=...)`

This keeps SDK/MCP behavior aligned with the dashboard UI: callers can explicitly choose the Alpha screening universe instead of relying only on the backend default.

### Alpha Ops Console

The Alpha ops console is also exposed through SDK/MCP for operator workflows:

- `client.alpha.get_ops_inference_overview()`
- `client.alpha.trigger_ops_inference(...)`
- `client.alpha.get_ops_qlib_data_overview()`
- `client.alpha.refresh_ops_qlib_data(...)`
- MCP `get_alpha_ops_inference_overview`
- MCP `trigger_alpha_ops_inference`
- MCP `get_alpha_ops_qlib_data_overview`
- MCP `refresh_alpha_qlib_data`

These calls mirror the staff/superuser web console:

- overview calls are read-only operational snapshots
- trigger / refresh calls only queue backend jobs
- duplicate in-flight work may return the backend conflict payload instead of a fresh task

### Workbench Tools (New)
- **Workbench**: `get_workbench_summary`, `get_workbench_items`
- **Review**: `approve_workbench_event`, `reject_workbench_event`, `rollback_workbench_event`, `override_workbench_event`
- **Gate**: `get_sentiment_gate_state`

### Extended Tools
- **Unified Accounts**: `list_accounts`, `get_account`, `create_account`, `get_account_positions`, `get_account_performance`
- **Manual Trade Import**: `preview_broker_trades_csv`, `import_broker_trades_csv`, `preview_broker_trades_json`, `import_broker_trades_json`
- **Simulated Trading Compat**: `list_simulated_accounts`, `execute_simulated_trade`, `get_simulated_performance`, `run_simulated_auto_trading`, `run_simulated_daily_inspection`, `list_simulated_daily_inspections`
- **Equity**: `get_stock_score`, `list_stocks`, `get_stock_recommendations`
- **Fund**: `rank_funds`, `screen_funds`, `get_fund_score`, `list_funds`, `get_fund_detail`, `get_fund_nav_history`, `analyze_fund`, `get_fund_holdings`, `get_fund_performance`
- **Sector**: `list_sectors`, `get_hot_sectors`, `compare_sectors`
- **Strategy**: `list_strategies`, `create_strategy`, `execute_strategy`, `list_ai_strategy_configs`, `get_strategy_ai_config`, `create_ai_strategy_config`, `update_ai_strategy_config`, `list_position_rules`, `create_position_rule`, `update_position_rule`
- **Rotation**: `list_rotation_regimes`, `list_rotation_templates`, `list_account_rotation_configs`, `get_account_rotation_config`, `create_account_rotation_config`, `update_account_rotation_config`, `apply_rotation_template_to_account_config`
- **Strategy Assignment**: `bind_portfolio_strategy`, `unbind_portfolio_strategy`
- **Decision Rhythm**: `submit_decision_request`, `list_decision_requests`, `decision_execute_request`, `decision_cancel_request`, `get_decision_request`
- **Decision Workflow (V3.4+)**: `decision_workflow_precheck`, `decision_workflow_list_recommendations`, `decision_workflow_refresh_recommendations`, `decision_workflow_apply_recommendation_action`, `decision_workflow_generate_transition_plan`, `decision_workflow_get_transition_plan`, `decision_workflow_update_transition_plan`, `decision_workflow_preview_execution`, `decision_workflow_get_funnel_context`
- **Pulse + Navigator**: `get_pulse_current`, `get_pulse_history`, `get_regime_navigator`, `get_action_recommendation`
- **Realtime**: `get_realtime_price`, `get_market_summary`, `create_price_alert`
- **Config Center**: `list_config_capabilities`, `get_config_center_snapshot`, `get_qlib_runtime_config`, `update_qlib_runtime_config`, `list_qlib_training_profiles`, `save_qlib_training_profile`, `list_qlib_training_runs`, `get_qlib_training_run_detail`, `trigger_qlib_training`

### Qlib Config Center Contract

`client.config_center` now exposes the full Qlib config/train center contract:

- `client.config_center.get_qlib_runtime()`
- `client.config_center.update_qlib_runtime(payload)`
- `client.config_center.list_qlib_training_profiles()`
- `client.config_center.save_qlib_training_profile(payload)`
- `client.config_center.list_qlib_training_runs(limit=20)`
- `client.config_center.get_qlib_training_run_detail(run_id)`
- `client.config_center.trigger_qlib_training(payload)`

Web entry:

- `/settings/config-center/qlib/`

API entry:

- `GET/POST /api/system/config-center/qlib/runtime/`
- `GET/POST /api/system/config-center/qlib/training-profiles/`
- `GET /api/system/config-center/qlib/training-runs/`
- `GET /api/system/config-center/qlib/training-runs/<run_id>/`
- `POST /api/system/config-center/qlib/training-runs/trigger/`

Decision workflow note:

- `decision_workflow_get_funnel_context` now exposes Step 3 freshness metadata in `step3_sectors`: `rotation_data_source`, `rotation_is_stale`, `rotation_warning_message`, `rotation_signal_date`.
- `client.decision_workflow.generate_transition_plan()` and MCP `decision_workflow_generate_transition_plan` expose Step 5 transition orders with the backend decision contract: `thesis`, `risk_summary`, `reward_risk`, and `data_asof`.
- `client.decision_workflow.update_transition_plan()` and MCP `decision_workflow_update_transition_plan` accept price/risk-rule order patches and rely on the backend to recalculate `reward_risk`.
- `client.decision_workflow.preview_execution()` and MCP `decision_workflow_preview_execution` preview plan/recommendation execution and can create approval requests when `create_request=true`.

## Rotation Account Config Examples

```python
from agomtradepro import AgomTradeProClient

client = AgomTradeProClient(
    base_url="http://localhost:8000",
    api_token="your_token_here",
)

templates = client.rotation.list_templates()
regimes = client.rotation.list_regimes()

config = client.rotation.get_account_config_by_account(308)

updated = client.rotation.update_account_config(
    config["id"],
    {
        "risk_tolerance": "moderate",
        "is_enabled": True,
        "regime_allocations": config["regime_allocations"],
    },
)

client.rotation.apply_template_to_account_config(updated["id"], "moderate")
```

## Documentation

| Document | Description |
|----------|-------------|
| [Quick Start Guide](../docs/sdk/quickstart.md) | Getting started with the SDK |
| [MCP Guide](../docs/mcp/mcp_guide.md) | MCP server setup and usage |
| [MCP Agent Contract](../docs/mcp/mcp-agent-contract-and-playbook.md) | Versioned Agent contract, Playbooks, rollout and rollback |
| [Smoke Test Guide](../docs/sdk/smoke_test.md) | End-to-end local smoke checklist |
| [API Reference](../docs/sdk/api_reference.md) | Complete API documentation |
| [Implementation Plan](../docs/plans/sdk-mcp-implementation.md) | Implementation status and plan |

## Migration Guide (V3.5)

### API Route Migration

Starting from V3.5, AgomTradePro uses unified API route format: `/api/{module}/{resource}/`

**SDK users**: No code changes required! Simply upgrade to the latest SDK version:

```bash
pip install --upgrade agomtradepro-sdk
```

The SDK automatically uses the new routes while maintaining backward compatibility.

**What changed**:

| Old Route | New Route |
|-----------|-----------|
| `/regime/api/current/` | `/api/regime/current/` |
| `/signal/api/` | `/api/signal/` |
| `/account/api/portfolios/` | `/api/account/portfolios/` |
| `/macro/api/supported-indicators/` | `/api/data-center/indicators/` |
| `/filter/api/` | `/api/filter/` |
| `/backtest/api/backtests/` | `/api/backtest/backtests/` |
| `/ai/api/providers/` | `/api/ai/providers/` |
| `/prompt/api/templates/` | `/api/prompt/templates/` |
| `/macro/api/indicator-data/` | `/api/data-center/macro/series/` |
| `/policy/api/events/` | `/api/policy/events/` |
| `/factor/api/` | `/api/factor/` |

For detailed migration information, see:
- [API Route Migration Guide](../docs/migration/route-migration-guide.md) - Complete migration guide
- [Migration Quick Reference](../docs/migration/migration-quick-reference.md) - Quick lookup table

**Important dates**:
- 2026-03-04: New routes released, old routes marked deprecated
- 2026-04-01: Old routes enter read-only mode (GET only)
- 2026-06-01: Old routes will be removed

## Examples

| Example | Description |
|---------|-------------|
| [basic_usage.py](../docs/sdk/examples/basic_usage.py) | Basic SDK operations |
| [backtesting.py](../docs/sdk/examples/backtesting.py) | Running and analyzing backtests |
| [data_analysis.py](../docs/sdk/examples/data_analysis.py) | Data analysis with pandas |
| [simulated_trading.py](../docs/sdk/examples/simulated_trading.py) | Simulated trading workflow |
| [equity_fund_analysis.py](../docs/sdk/examples/equity_fund_analysis.py) | Stock and fund analysis |
| [fund_research_workflow.py](../docs/sdk/examples/fund_research_workflow.py) | Canonical fund research workflow |
| [realtime_strategy.py](../docs/sdk/examples/realtime_strategy.py) | Real-time monitoring and strategies |

## Notes

- `client.backtest.list()` is the preferred SDK list method. `client.backtest.list_backtests()` remains supported as a compatibility alias.
- Fund research callers should prepare local `fund_info` + NAV + `fund_performance` data first. Recommended command:
  `python manage.py prepare_fund_research_data --start-date 2024-01-01 --end-date 2024-12-31`
- Fund canonical payloads: `info -> fund`, `nav -> nav_data`, `holding -> holdings`; `style` and `holding` prefer `report_date` over `as_of_date`.
- `tests/integration/test_realtime_monitoring_flow.py` is a live-market integration test. It is skipped by default unless `AGOMTRADEPRO_RUN_LIVE_REALTIME_TESTS=1` is set.

## Simulated trade fee corrections

`client.simulated_trading.fee_corrections` exposes the server's owner-scoped,
source-backed correction workflow. It returns frozen typed results with aware
timestamps. It does not change the original trade or its simulated slippage.
This workflow is separate from the legacy transaction importer below.

| Method | Effect |
| --- | --- |
| `get_policy(account_id)` | Read the current material policy; missing policy is disabled at version 0. |
| `set_policy(account_id, ...)` | Explicitly change the policy using its expected version; never called automatically. |
| `get_head(account_id, trade_id, idempotency_key=...)` | Read the validated revision and, when a key is supplied, that request's correction receipt. |
| `discover_recovery(account_id, trade_id, limit=20, cursor=None)` | Read a bounded page of stored material states for this owner and trade. |
| `get_recovery_head(account_id, trade_id, source_locator=...)` | Read the exact material's receipt without the original request key. |
| `upload_evidence(account_id, trade_id, ...)` | Save operator-attested CSV material; no cash or position posting. |
| `apply(account_id, trade_id, ...)` | Submit the stored material for atomic server validation and correction. |

The current active simulated-account owner must explicitly enable the existing
material policy before uploading. `set_policy` requires `expected_version`,
`enabled`, `allow_operator_attested_upload`, `ledger_currency`, `valid_from`,
`valid_until`, and `attestation_acknowledged`. Dates are offset-bearing ISO text
or `None`. Operator attestation does not establish broker or issuer authenticity.
Server ownership, policy, source, revision and complete-history checks still apply.

For an interrupted workflow, call `discover_recovery` before preparing another
correction. Its frozen page retains each material's original `stored_at`, hashes,
revision, predecessor and policy versions. `unresolved` needs explicit recovery;
`unknown` remains blocked; `completed` has a validated historical receipt.
`fenced` means valid original material was superseded by a strictly newer account
policy version. It is not a single-trade cancellation or permission to write.
An empty page or a missing receipt is not proof that an earlier write had no effect.

Use `next_cursor` for an explicit next-page read while `has_more` is true. A
single page need not contain every unresolved material. Keep the selected
`source_locator` and call `get_recovery_head` to recover its exact receipt; this
method sends no idempotency key. A `partial` response returns a head with
`request_receipt=None`; it does not retry a write. Unknown states, mismatched
account/trade identities and malformed paging or timestamp data are rejected.
Neither read method uploads material, changes policy or confirms a correction.
Browser recovery preview and confirmation retain the existing live-session,
CSRF and explicit-confirmation requirements.

Read `get_head` before preparing a new correction. Retain one caller-generated
`idempotency_key` for both upload and apply, together with the exact original
UTF-8 CSV bytes and the returned material locator. Upload takes
`expected_revision=head.revision`,
`expected_predecessor_id=head.expected_predecessor_id`, `original_filename`,
`csv_text`, and `attestation_acknowledged=True`. After reviewing the correction,
call `apply` with that same key, `source_locator=upload.evidence.source_locator`
and the same expected revision. The SDK never enables, applies or retries these
writes implicitly. Do not normalize CSV line endings when decoding the bytes.

The single-row CSV uses this exact header and schema value
`operator-fee-evidence.v2`:

```csv
schema_version,currency_code,source_account_ref,source_trade_ref,asset_code,side,quantity,price,amount,execution_at,source_observed_at,commission,transfer_fee,stamp_duty
```

Use actual source references, observation/execution times and exact decimal
lexemes. Blank fees remain unknown and cannot authorize a correction. The
filename must be a CSV basename and the UTF-8 material is limited to 1 MiB.
The SDK preserves the supplied text and checks its returned content hash;
financial matching and source qualification belong to the server.

The default HTTP transport sends each write once and rejects redirects. Custom
injected transports must enforce their own retry and redirect policy. Catch
`FeeCorrectionOutcomeUnknownError` from
`agomtradepro.modules.simulated_fee_corrections` when a write response cannot be
verified; its `effects_indeterminate` and `recovery_required` flags are true.
Keep the original request identity and recover according to the operation:

- Policy: read `get_policy` and review the current version before deciding on
  another change.
- Upload: retain the same key and bytes for an explicit replay while the policy
  remains valid. A correction head cannot prove whether an upload was stored.
- Apply: call `get_head(..., idempotency_key=original_key)` to read the original
  receipt. `request_receipt=None` means no receipt was found at that read; it
  does not prove that the write failed or had no effects.

Known server rejections such as permission, revision conflict and invalid
source retain their API errors. A pre-write `FEE_CORRECTION_READ_UNAVAILABLE`
response remains a read failure. No new key or successful receipt is fabricated
after an uncertain result.

## Transaction fees in MCP imports and exports

For transaction JSON/CSV imports, the actual fee fields are `commission`,
`slippage`, `stamp_duty`, and `transfer_fee`. Omitted, null, or blank fees stay
uncollected; an explicit zero is a collected zero. Client-supplied `*_known`
flags and estimated costs cannot set the server's actual-fee availability.

Provide exact amounts as decimal strings, for example `"commission": "1.25"`.
The transport preserves decimal values as strings and the server validates its
supported precision and range. Numeric JSON tokens may already have lost precision
when decoded to a float; converting that float later cannot recover the original
text. A successful local preview does not certify server acceptance. Inspect the
import result's `success` and row errors, including after a confirmed call: the
current dispatcher can still report outer `completed` for a failed nested result.

CSV export keeps its original first eleven columns and appends `slippage`,
`stamp_duty`, `transfer_fee`, then the four matching `*_known` columns. A fee
amount is emitted only when its flag is exactly true, preserving known zero.
False flags export as `False`; null or absent historical flags export blank.
Reimport creates new records rather than restoring historical provenance.

Use append imports. This MCP transaction-import tool rejects every mode other than
`append` locally and cannot delete or replace historical trades. Authorized transaction-fee corrections
remain available through the existing Admin workflow; this importer does not correct
trade prices or share quantities and does not provide full trade reversal.

SDK transaction and capital-flow reads apply the requested portfolio filter before
the result limit, preserving API order. Each fetched page validates count, next,
results, row identifiers and ledger portfolio identifiers; duplicate or inconsistent
pages fail explicitly. Requests stay on the SDK-owned endpoint and never follow a
server-supplied next URL. A scan is capped at 1000 pages; sparse or larger histories
can reach that cap and fail rather than return partial output. The standard 20-row
page size still supports existing unscoped 5000-row reads within this cap.

Capital-flow JSON/CSV imports also accept only append. Registered JSON, its CSV
delegate, and the owner-fallback JSON entry reject every other mode before constructing
a client; append, preview and locally invalid batches do not pre-read or delete history.
The existing authorized single-record capital-flow API deletion remains available.
The JSON transaction
and capital-flow tools accept `idempotency_key` as dispatcher metadata; this does
not add durable server-side deduplication.

These reads and exports are bounded results, not complete histories or PIT
snapshots; concurrent changes can preserve counts and escape the client-side
consistency checks.

## Import delivery and uncertain results

Transaction and capital-flow import writes use `client.post_once`. For the built-in
HTTP transport, this disables automatic retries and rejects redirects using a
temporary session that closes after each request. An injected `RequestTransport`
controls its own retry and redirect behavior; the SDK makes one call to it.

A timeout or server error can happen after a record is committed. The current
import result can therefore report `success=false` while a row exists; its legacy
counts do not prove that nothing was stored. Reconcile the target ledger before
resubmitting. MCP confirmation keys only cache results in the current dispatcher
process and do not provide durable server-side deduplication. Ordinary `post` and
existing requests with idempotency keys retain their current transport behavior.

## Development

```bash
# Run tests
pytest tests/ -v

# Format code
black agomtradepro/ agomtradepro_mcp/
isort agomtradepro/ agomtradepro_mcp/

# Type check
mypy agomtradepro/

# Run MCP server
agomtradepro-mcp
```

## Project Status

- **Version**: See [`pyproject.toml`](../pyproject.toml) and [`core/version.py`](../core/version.py)
- **App Modules / MCP Tools / Static Tests**: See [`governance/governance_baseline.json`](../governance/governance_baseline.json)
- **SDK Modules**: Derived from `sdk/agomtradepro/modules/`; this guide does not maintain a dynamic count
- **Test Coverage**: Core modules covered
- **Documentation**: Complete
- **Governance Verification**: `python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text`

## License

Apache License 2.0 - see [LICENSE](../LICENSE) for details.

## Account ledger import results

The MCP capabilities `account.import.transactions` and
`account.import.capital_flows` append rows; their preview does not write. In a
preview summary, `planned_create_count` is the number of normalized candidate
rows and `create_count` remains zero. After confirmation, `create_count` and
`succeeded_count` count only rows with a matching create response. The nested
`outcome` distinguishes `success`, `partial`, `failed`, `unknown`, and `noop`.

Transaction receipt matching compares traded_at as an ISO 8601 instant. Supply
an explicit UTC offset or Z to allow confirmation; equivalent offsets are
accepted. A timezone-naive timestamp is sent unchanged but cannot be matched to
an instant, so a successful POST is reported as unknown and later rows are not
sent. The importer does not infer a timezone.

For each transaction fee explicitly sent in a row, the create receipt must include
a finite, nonnegative Decimal-equal amount and its matching `*_known` flag must be
exactly `true`. Explicit zero is valid. A missing/null value, a mismatch, or any
known flag other than `true` makes that POST unknown and stops later rows. For a
fee not sent, the receipt may omit the value or return null, and may omit its flag
or return false/null; a non-null fee value or `true` flag is not credited as a
fact about the request. Receipt validation follows the existing create serializer
and does not require an id or position.

If a POST may have reached the server but its result cannot be confirmed, the
import returns `outcome: unknown`, sets `stored_count` to null, and stops before
sending later rows. Check the ledger before starting another import. Dispatcher
idempotency protects replay only within the current process; it is not a
server-side or restart-safe deduplication guarantee. Capital-flow amounts
continue to use the existing float normalizer, so these counters do not promise
exact decimal preservation.
