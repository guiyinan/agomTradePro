# AgomTradePro MCP Server Guide

The MCP (Model Context Protocol) Server enables AI agents like Claude Code to interact with AgomTradePro through native tools.

## Welcome Message

When Codex, Claude Code, or another MCP client connects, the server now exposes a standard `instructions` welcome message during MCP initialize.
The current implementation is not just a link hint: the full welcome page content is embedded directly into the startup instructions payload.

The welcome message includes:

- Current MCP role
- Backend base URL
- Suggested first resources and workflow prompts
- Execution guardrails for investment actions

For clients that do not render `instructions`, the same content is available as resource `agomtradepro://welcome`.

Protocol note:

- MCP can strongly inject startup context through `instructions`
- MCP cannot guarantee every third-party client will visually render a page UI
- Therefore AgomTradePro now uses both:
  - inline startup injection in `instructions`
  - mirrored fallback resource at `agomtradepro://welcome`

## Setup

### 1. Install the SDK

```bash
cd sdk
pip install -e .
```

Recommended runtime versions:

- Python `>=3.11`
- `mcp>=1.20,<2`

Verify:

```bash
python -m pip show agomtradepro-sdk mcp
```

### Runtime Environment Variables

MCP server uses SDK credentials to call AgomTradePro backend:

- `AGOMTRADEPRO_BASE_URL` (required)
- `AGOMTRADEPRO_API_TOKEN` (recommended)
- Or `AGOMTRADEPRO_USERNAME` + `AGOMTRADEPRO_PASSWORD`
- `AGOMTRADEPRO_DEFAULT_ACCOUNT_ID` (optional, used by account resources)

Auth format on backend is DRF Token (`Authorization: Token <token>`).

Create token for an existing user:

```bash
cd .
python -c "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','core.settings.development'); import django; django.setup(); from django.contrib.auth.models import User; from apps.account.infrastructure.models import UserAccessTokenModel; u=User.objects.get(username='admin'); t,key=UserAccessTokenModel.create_token(user=u, name='mcp-guide'); print(key)"
```

### Runtime Setup by Platform

#### Windows PowerShell

```powershell
$env:AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
$env:AGOMTRADEPRO_API_TOKEN="your_token_here"
$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
```

#### Linux/macOS (bash)

```bash
export AGOMTRADEPRO_BASE_URL="http://127.0.0.1:8000"
export AGOMTRADEPRO_API_TOKEN="your_token_here"
export NO_PROXY="127.0.0.1,localhost"
export no_proxy="127.0.0.1,localhost"
```

### Admin Token Management Page (Recommended)

If you are a system admin, you can manage DRF tokens in UI instead of shell scripts:

- Path: `/account/admin/tokens/`
- Features:
  - Search users by username/email
  - Filter users without token
  - Generate/rotate token per user
  - Revoke token per user

From the page, click "生成Token" or "重置Token" for target user. The new token will be shown once in success message, then only masked preview is displayed in list.

### User MCP Guide Page (Recommended for Daily Copy/Paste)

For the current logged-in user, the easiest copy/paste entry is:

- Path: `/account/mcp/`
- Purpose:
  - show current user token
  - show Base URL / API endpoints / default account ID
  - show ready-to-copy `mcpServers` JSON
  - show PowerShell / bash environment variable snippets

If the account has no active token yet, the page supports one-click token creation.

### 2. Configure Claude Code

Edit `~/.config/claude-code/mcp_servers.json`:

Windows path example:

```json
{
  "mcpServers": {
    "agomtradepro_local": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp"],
      "cwd": "D:/path/to/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://127.0.0.1:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token_here",
        "AGOMTRADEPRO_MCP_ENFORCE_RBAC": "true",
        "AGOMTRADEPRO_MCP_ROLE": "投资经理"
      }
    }
  }
}
```

Linux/macOS path example:

```json
{
  "mcpServers": {
    "agomtradepro_local": {
      "command": "python",
      "args": ["-m", "agomtradepro_mcp"],
      "cwd": "/path/to/agomTradePro/sdk",
      "env": {
        "AGOMTRADEPRO_BASE_URL": "http://127.0.0.1:8000",
        "AGOMTRADEPRO_API_TOKEN": "your_token_here",
        "AGOMTRADEPRO_MCP_ENFORCE_RBAC": "true",
        "AGOMTRADEPRO_MCP_ROLE": "投资经理"
      }
    }
  }
}
```

## RBAC (Role-Based Access Control)

Enable RBAC:

- `AGOMTRADEPRO_MCP_ENFORCE_RBAC=true`
- 推荐：不设置 `AGOMTRADEPRO_MCP_ROLE`，MCP 会自动从 `/api/account/profile/` 的 `rbac_role` 读取当前用户角色
- 可选覆盖：`AGOMTRADEPRO_MCP_ROLE=<role>`（强制覆盖后端角色）
- 角色来源开关：`AGOMTRADEPRO_MCP_ROLE_SOURCE=backend`（默认）
- 后备角色：`AGOMTRADEPRO_MCP_DEFAULT_ROLE=read_only`

Supported roles (Chinese/English aliases):

- `管理员` / `admin`: full access
- `所有者` / `owner`: full except system-admin operations
- `分析师` / `analyst`: read-only tools
- `投资经理` / `investment_manager`: read all + write on trading/strategy/risk domains
- `交易员` / `trader`: read all + write on trading domain
- `风控` / `risk`: read all + write on risk domain
- `只读用户` / `read_only`: read-only (and stricter prompt limits)

Optional hard overrides:

- `AGOMTRADEPRO_MCP_ALLOWED_TOOLS=tool_a,tool_b`
- `AGOMTRADEPRO_MCP_DENIED_TOOLS=tool_x`
- `AGOMTRADEPRO_MCP_ALLOWED_RESOURCES=agomtradepro://regime/current`
- `AGOMTRADEPRO_MCP_DENIED_RESOURCES=agomtradepro://account/summary`
- `AGOMTRADEPRO_MCP_ALLOWED_PROMPTS=analyze_macro_environment`
- `AGOMTRADEPRO_MCP_DENIED_PROMPTS=check_signal_eligibility`

### 3. Test the Connection

Restart Claude Code and ask:
```
What's the current macro regime?
```

Claude should call the `get_current_regime` tool and respond with the current regime.

Recommended environment split:

- `agomtradepro_local` -> `http://127.0.0.1:8000`
- `agomtradepro_prod` -> your production domain

Do not switch local/prod by editing one shared server entry.

You can validate tool registration locally. Current local snapshot on `2026-05-06`: `326` registered tools.

```bash
python -c "import asyncio; from agomtradepro_mcp.server import server; print(len(asyncio.run(server.list_tools())))"
```

## Recent MCP-Facing Changes

- Data Center 宏观治理台已落地到 `/data-center/governance/`。这是一套 staff 运维页面，不是 MCP tool；Agent 侧仍应通过 `data_center_list_indicators`、`data_center_get_macro_series`、`data_center_sync_macro` 等 canonical tool 访问治理后的事实表。
- 宏观运行配置已开始下沉到 `IndicatorCatalog.extra`，MCP/Agent 对宏观指标的解释与调度判断应优先读取运行时元数据，而不是在 Agent 侧硬编码：
  - `series_semantics`
  - `paired_indicator_code`
  - `chart_policy`
  - `chart_reset_frequency`
  - `chart_segment_basis`
  - `schedule_frequency`
  - `schedule_day_of_month`
  - `schedule_release_months`
  - `publication_lag_days`
  - `orm_period_type_override` / `domain_period_type_override`
- 当前 active 宏观指标已补齐显式 `series_semantics`，并由数据库派生统一 `chart_policy`；对累计值序列还会同步暴露：
  - `chart_reset_frequency`
  - `chart_segment_basis`
  当前 canonical 图表策略为：
  - `continuous_line`
  - `period_bar`
  - `yearly_reset_bar`
- Agent/MCP 不得再按 code suffix、默认周期或页面经验去猜测“是否适合连线”；必须优先消费 catalog metadata。
- 本地或新环境初始化后，建议执行一次：

```bash
python manage.py init_macro_indicator_governance --strict
```

该命令会幂等修复 `series_semantics`、compat alias metadata、`chart_policy` 与 reset-cycle 图表元数据，并在仍有 active 指标缺少显式语义时直接失败。
- 宏观 runtime metadata 现已成为唯一运行真源：
  - 本地已不再维护独立 schedule fallback 表
  - 本地已不再维护独立 publication lag fallback 表
  - 本地已不再维护独立 period override fallback 表
  - 本地已不再维护独立 fetcher unit fallback 表
- 宏观治理台本身也已改成 metadata 驱动：
  - `governance_scope`
  - `governance_sync_supported`
- Data Center 事实表 `source` 现统一存 canonical `source_type`，不再存 provider display name。
- 如需展示或审计 provider 名称，应优先读取 `extra.provider_name` 或同步审计日志，而不是把事实表 `source` 当成 provider 展示名。
- 对 legacy source 的理解也应优先读取事实表 `extra.source_type`，必要时再结合 `ProviderConfig.name -> source_type`；不要在 Agent/MCP 侧再硬编码 provider alias 表。
- 剩余 legacy indicator code alias 也已下沉到 catalog metadata，MCP/SDK 侧不应再自行维护：
  - `CN_PMI_MANUFACTURING -> CN_PMI`
  - `CN_PMI_NON_MANUFACTURING -> CN_NON_MAN_PMI`
  - `CN_CPI_MOY -> CN_CPI_NATIONAL_MOM`
  - `CN_CPI_YOY -> CN_CPI_NATIONAL_YOY`
- 宏观指标治理已补齐以下口径对：
  - `CN_FIXED_INVESTMENT` = 固定资产投资累计值
  - `CN_FAI_YOY` = 固定资产投资累计同比增速
  - `CN_SOCIAL_FINANCING` = 社会融资规模增量
  - `CN_SOCIAL_FINANCING_YOY` = 社会融资规模增量同比增速
- 进出口口径已纠偏，MCP/SDK 不得再把金额和同比混用：
  - `CN_EXPORTS` / `CN_IMPORTS` = 当月金额，display unit 为 `亿美元`
  - `CN_EXPORT_YOY` / `CN_IMPORT_YOY` = 当月金额同比增速，display unit 为 `%`
- `CN_CPI_YOY` 当前只保留为兼容别名代码；治理真源与优先查询代码仍是 `CN_CPI_NATIONAL_YOY`。
- `data_center_get_macro_series(...)` 现会直接返回 provenance contract，Agent 读取宏观数据时必须消费以下字段，而不是自行猜测：
  - `provenance_class`
  - `provenance_label`
  - `publisher`
  - `publisher_code`
  - `publisher_codes`
  - `access_channel`
  - `derivation_method`
  - `upstream_indicator_codes`
  - `is_derived`
  - `decision_grade`
  - `must_not_use_for_decision`
- `run_simulated_daily_inspection(...)` now accepts `auto_create_proposal`; when enabled,
  the API response includes stable `proposal_created` / `proposal_id` fields.
- Strategy / simulated trading tools now expose the full simulated auto-trading path:
  `list_ai_strategy_configs`, `get_strategy_ai_config`, `create_ai_strategy_config`,
  `update_ai_strategy_config`, `update_position_rule`, and `run_simulated_auto_trading`.
  See [strategy-auto-trading-mcp.md](../modules/strategy/strategy-auto-trading-mcp.md).
- Dashboard Alpha 工具现在统一支持 `pool_mode`：`strict_valuation`、`market`、`price_covered`
- `get_dashboard_alpha_candidates(...)` / `trigger_dashboard_alpha_refresh(...)` 返回共享 `contract`，用于区分真实推荐、异步刷新和兜底结果
- `decision_workflow_get_funnel_context(...)` 会附带顶层 `step3_status` / `step3_signal_date` 等摘要字段，便于 Agent 直接消费
- `get_pulse_current()` 继续返回 canonical `/api/pulse/current/` JSON；当当前 Regime 只能解析成 `Unknown` 时，后端会保留最近有效的 Pulse 快照，而不是把 tactical context 覆盖成未知状态
- Fund canonical MCP tools 现已显式补齐：
  - `rank_funds(regime, max_count)`
  - `screen_funds(regime, custom_types, custom_styles, min_scale, limit)`
  - `get_fund_nav_history(fund_code, start_date, end_date, limit)`
  - `analyze_fund(..., report_date=...)` / `get_fund_holdings(..., report_date=...)` 优先使用 `report_date`

## Available Tools

### Config Center Tools

```
list_config_capabilities()
get_config_center_snapshot()
list_data_center_providers()
create_data_center_provider(name, source_type, priority, is_active, api_key, http_url, api_endpoint, api_secret, extra_config, description)
update_data_center_provider(provider_id, ...)
test_data_center_provider_connection(provider_id)
get_data_center_provider_status()
```

Notes:

- `data_center_providers` 是统一财经数据源中台入口，Tushare、AKShare、EastMoney、QMT、FRED 等配置都从这里进入。
- 对于第三方 Tushare 数据源，使用 `http_url` 字段；后端会把它下发到 `pro._DataApi__http_url`。
- 对于 QMT 行情源，使用 `source_type="qmt"`，本地 XtQuant 参数放在 `extra_config`。

### Macro Governance Notes

- MCP 查询宏观数据时，运行时真源固定为 `IndicatorCatalog` + `IndicatorUnitRule` + `data_center_macro_fact`。
- `series_semantics` 是宏观图表策略与 alias 安全回退的一级真源；`chart_policy`、`chart_reset_frequency`、`chart_segment_basis` 是直接面向 UI / MCP consumer 的展示策略真源。
- 对累计值、当期值、利率/同比这三类序列的图表解释，必须读取 catalog metadata，不允许在 Agent prompt 或 SDK wrapper 里复写本地 if/else 表。
- publisher 机构归一真源现补齐为 `PublisherCatalog`：
  - 机构识别、筛选、聚合优先使用 `publisher_code/publisher_codes`
  - `publisher` 只用于展示，不应再被当作稳定主键
- 页面治理入口 `/data-center/governance/` 可以用于人工审计，但 Agent 不应假设该页面是 API 契约的一部分。
- fetcher 层现在没有任何单位 fallback；若 catalog metadata 和 active unit rule 缺失，系统应视为治理缺口并直接失败，而不是返回“看起来能跑”的 mock 单位数据。
- 对抓取节奏、发布时间、period_type 的理解，优先读取 catalog runtime metadata；不要仅凭 code 后缀或历史经验推断。
- 对宏观 series 的解释必须先看 `series_semantics` / `paired_indicator_code`：
  - `monthly_level` / `cumulative_level` / `flow_level` 表示量值口径
  - `yoy_rate` 表示同比增速口径
- 对宏观 series 的可信度必须先看 provenance：
  - `official` = 官方数据，可按 freshness 继续判断是否 decision-safe
  - `authoritative_third_party` = 其他权威数据，可按 freshness 继续判断是否 decision-safe
  - `derived` = 系统衍生数据，默认 `research_only`
- 对季度指标再补一条约束：
  - `schedule_frequency=quarterly` 时，应结合 `schedule_release_months` 解释其发布时间窗口，不能按月频处理
- 典型高风险指标当前正确读法：
  - `CN_GDP` = 季度累计值，不是单季值
  - `CN_GDP_YOY` = GDP 同比增速
  - `CN_RETAIL_SALES` = 社零当月值
  - `CN_RETAIL_SALES_YOY` = 社零同比增速
  - `CN_EXPORTS` = 当月出口额
  - `CN_EXPORT_YOY` = 当月出口额同比增速
  - `CN_IMPORTS` = 当月进口额
  - `CN_IMPORT_YOY` = 当月进口额同比增速
  - `CN_SOCIAL_FINANCING` = 社会融资规模增量，不是余额
  - `CN_SOCIAL_FINANCING_YOY` = 社会融资规模增量同比增速，但它是 `derived`，默认仅供研究
- 数据解读提醒：
  - `CN_EXPORT_YOY` 在低基数月份可能大于 `100%`，例如 `2021-02` 的 `154.9%`，这仍属于官方同比口径，不应被 Agent 擅自修正
  - `CN_SOCIAL_FINANCING_YOY` 已增加 `prior_flow_value > 0` 护栏，若基数非正值则应跳过派生，而不是继续输出极端同比

### Equity Tools

```
get_stock_score(stock_code, as_of_date)
list_stocks(sector, min_score, limit)
get_stock_detail(stock_code)
get_stock_recommendations(regime, limit)
analyze_stock(stock_code, as_of_date)
get_stock_financials(stock_code, report_type, limit)
get_stock_valuation(stock_code, as_of_date)  # 返回完整估值详情
get_valuation_repair_status(stock_code, lookback_days)
get_valuation_repair_history(stock_code, lookback_days)
scan_valuation_repairs(universe, lookback_days, limit)
list_valuation_repairs(universe, phase, limit)
sync_valuation_data(days_back, stock_codes, start_date, end_date, primary_source, fallback_source)
validate_valuation_data(as_of_date, primary_source)
get_valuation_data_freshness()
get_valuation_data_quality_latest()
get_valuation_repair_config()
list_valuation_repair_configs(limit)
create_valuation_repair_config(...)
activate_valuation_repair_config(config_id)
rollback_valuation_repair_config(config_id)
```

Notes:

- `get_stock_valuation` 现在返回完整的股票详情数据，包括基本信息、估值详情和财务数据：
  ```json
  {
    "success": true,
    "stock_code": "000001.SZ",
    "stock_name": "平安银行",
    "sector": "银行",
    "market": "SZ",
    "list_date": "1991-04-03",
    "current_pe": 5.2,
    "pe_percentile": 0.15,
    "current_pb": 0.55,
    "pb_percentile": 0.20,
    "is_undervalued": true,
    "latest_valuation": {
      "pe": 5.2,
      "pb": 0.55,
      "ps": 1.2,
      "total_mv": 250000000000,
      "circ_mv": 250000000000,
      "dividend_yield": 5.5,
      "price": 12.5
    },
    "financial_data": {
      "roe": 10.5,
      "roa": 0.8,
      "revenue": 100000000000,
      "net_profit": 25000000000,
      "revenue_growth": 8.5,
      "net_profit_growth": 12.3,
      "debt_ratio": 95.0
    }
  }
  ```

### Macro Regime Tools

```
get_current_regime()
calculate_regime(as_of_date, growth_indicator, inflation_indicator)
get_regime_history(start_date, end_date)
get_regime_distribution(start_date, end_date)
explain_regime(regime_type)
get_recommended_assets(regime_type)
```

### Fund Tools

```
rank_funds(regime, max_count)
screen_funds(regime, custom_types, custom_styles, min_scale, limit)
get_fund_score(fund_code, as_of_date)
list_funds(fund_type, min_score, limit)
get_fund_detail(fund_code)
get_fund_recommendations(regime, fund_type, limit)
get_fund_nav_history(fund_code, start_date, end_date, limit)
analyze_fund(fund_code, report_date, as_of_date)
get_fund_performance(fund_code, period)
get_fund_holdings(fund_code, report_date, as_of_date)
```

Notes:

- canonical read tools are `rank_funds` and `screen_funds`
- `list_funds` / `get_fund_recommendations` are compatibility wrappers built on top of current rank results
- fund detail payload is already unwrapped to the `fund` object
- NAV history payload is already unwrapped to `nav_data`
- holdings payload is already unwrapped to `holdings`
- `000001.OF` style legacy SDK/MCP input is accepted, but backend requests are normalized to local canonical six-digit fund code

### Dashboard Alpha Tools

```
get_dashboard_alpha_candidates(top_n, portfolio_id, pool_mode)
trigger_dashboard_alpha_refresh(top_n, portfolio_id, pool_mode)
get_dashboard_alpha_history(portfolio_id, trade_date, stock_code, stage, source)
get_dashboard_alpha_history_detail(run_id)
```

`pool_mode` 支持：

- `strict_valuation`：严格估值覆盖池
- `market`：市场可交易池
- `price_covered`：价格覆盖池

使用约束：

- 这组工具面向“账户驱动池”，不是固定指数 universe
- `trigger_dashboard_alpha_refresh(...)` 只排队后台 Alpha 推理，不直接返回推荐
- 读取候选时必须检查返回里的 `contract`
- `contract.recommendation_ready=true`：当前 scoped 结果可被当作真实候选排序读取
- `contract.must_not_treat_as_recommendation=true`：Agent 不得把返回内容解释为当前有效推荐
- `contract.async_refresh_queued=true`：后台推理仍在进行，需等待后再次读取
- `contract.hardcoded_fallback_used=true`：命中了兜底路径，只能作为可用性信号，不应表述为正式推荐

示例：

```python
get_dashboard_alpha_candidates(
    top_n=10,
    portfolio_id=135,
    pool_mode="market",
)

trigger_dashboard_alpha_refresh(
    top_n=10,
    portfolio_id=135,
    pool_mode="price_covered",
)
```

典型 `contract` 片段：

```json
{
  "contract": {
    "recommendation_ready": false,
    "must_not_treat_as_recommendation": true,
    "async_refresh_queued": true,
    "hardcoded_fallback_used": false
  }
}
```

### Signal Tools

```
list_signals(status, asset_code)
get_signal(signal_id)
check_signal_eligibility(asset_code, logic_desc)
create_signal(asset_code, logic_desc, invalidation_logic, threshold)
approve_signal(signal_id)
reject_signal(signal_id, reason)
invalidate_signal(signal_id, reason)
```

### Data Center Macro Tools

```
data_center_list_indicators(active_only)
data_center_list_publishers(active_only)
data_center_get_publisher(publisher_code)
data_center_create_publisher(code, canonical_name, publisher_class, aliases, canonical_name_en, country_code, website, is_active, description)
data_center_update_publisher(publisher_code, canonical_name, publisher_class, aliases, canonical_name_en, country_code, website, is_active, description)
data_center_delete_publisher(publisher_code)
data_center_get_indicator(indicator_code)
data_center_list_indicator_unit_rules(indicator_code)
data_center_get_macro_series(indicator_code, start, end, limit)
data_center_sync_macro(provider_id, indicator_code, start, end)
```

### Backtest Tools

```
run_backtest(strategy_name, start_date, end_date, initial_capital)
get_backtest_result(backtest_id)
list_backtests(strategy_name, status)
get_backtest_equity_curve(backtest_id)
```

### Real-time Tools

```
get_realtime_price(asset_code)
get_multiple_realtime_prices(asset_codes)
get_market_summary()
get_top_movers(direction)
get_sector_realtime_performance()
```

### Rotation Account Config Tools

```
list_rotation_regimes()
list_rotation_templates()
list_account_rotation_configs()
get_account_rotation_config(config_id, account_id)
create_account_rotation_config(account_id, risk_tolerance, is_enabled, regime_allocations)
update_account_rotation_config(config_id, payload, partial)
delete_account_rotation_config(config_id)
apply_rotation_template_to_account_config(config_id, template_key)
```

Notes:

- `get_account_rotation_config` accepts either `config_id` or `account_id`; `config_id` wins if both are provided.
- `template_key` usually uses `conservative`, `moderate`, or `aggressive`.
- `regime_allocations` shape is `{regime_name: {asset_code: weight}}`, and each regime should sum to `1.0` within backend tolerance.

Example:

```json
{
  "account_id": 308,
  "risk_tolerance": "moderate",
  "is_enabled": true,
  "regime_allocations": {
    "Overheat": {
      "510300": 0.4,
      "518880": 0.2,
      "511260": 0.4
    }
  }
}
```

### Alpha Upload And User-Isolation Tools

```
get_alpha_stock_scores(universe, trade_date, top_n, user_id)
upload_alpha_scores(universe_id, asof_date, intended_trade_date, scores, model_id, model_artifact_hash, scope)
get_dashboard_alpha_candidates(top_n, portfolio_id)
get_dashboard_alpha_history(portfolio_id, trade_date, stock_code, stage, source)
get_dashboard_alpha_history_detail(run_id)
trigger_dashboard_alpha_refresh(top_n, portfolio_id)
decision_cancel_request(request_id, reason)
```

Notes:

- `get_alpha_stock_scores` now supports optional `user_id`; only admin-backed tokens should use it to inspect another user's personal cache.
- `get_alpha_stock_scores` is still the universe/research view and remains parameterized by `universe`.
- `get_dashboard_alpha_candidates` is the homepage/account view: it returns the account-driven pool, `Alpha Top 候选/排名`, `可行动候选`, `待执行队列`, cache/realtime metadata, recent history runs, and a stable SDK/MCP `contract`.
- `get_dashboard_alpha_history` / `get_dashboard_alpha_history_detail` expose the new persisted run/snapshot history, including buy reasons, no-buy reasons, invalidation conditions, risk gate status, and suggested sizing.
- `trigger_dashboard_alpha_refresh` triggers a realtime refresh for the current portfolio-driven pool, not a fixed index universe. It returns the Celery task id for `qlib_predict_scores`; the task is routed to the `qlib_infer` queue and the returned `contract.must_not_treat_as_recommendation` remains `true`.
- Pending assets in `get_dashboard_alpha_candidates` are approved decision requests with `execution_status=PENDING/FAILED`; use `decision_cancel_request` to discard a pending request without deleting its audit/history record.
- Dashboard page load is intentionally cache/registry first. Use `trigger_dashboard_alpha_refresh` when an agent wants fresh Qlib inference instead of relying on the lightweight homepage load.
- If the homepage account-scope cache is missing, the backend may auto-queue scoped Qlib inference and return `refresh_status`, `async_task_id`, and `poll_after_ms`; consumers must not treat this as a recommendation until real scoped scores are returned.
- MCP/SDK consumers should read `contract.recommendation_ready`, `contract.must_not_treat_as_recommendation`, `contract.async_refresh_queued`, and `contract.hardcoded_fallback_used` instead of inferring recommendation state from raw `meta`.
- Read priority is `personal > system`.
- `upload_alpha_scores(..., scope="user")` writes personal scores for the token owner.
- `upload_alpha_scores(..., scope="system")` writes system-level scores and requires an admin-capable backend user/token.
- This makes MCP suitable for "local Qlib inference -> upload to VPS -> isolated visibility" workflows.

### Strategy Position Management Tools

```
bind_portfolio_strategy(portfolio_id, strategy_id)
unbind_portfolio_strategy(portfolio_id)
list_position_rules(strategy_id, is_active, limit)
create_position_rule(strategy_id, name, buy_price_expr, sell_price_expr, stop_loss_expr, take_profit_expr, position_size_expr, ...)
get_strategy_position_rule(strategy_id)
evaluate_position_rule(rule_id, context)
evaluate_strategy_position_management(strategy_id, context)
```

`context` is a JSON object with runtime variables (for example `current_price`, `atr`, `account_equity`, `risk_per_trade_pct`).

### Alpha Candidate Tools

```
list_alpha_candidates()
get_alpha_candidate(candidate_id)
update_alpha_candidate_status(candidate_id, status)
```

`status` supports: `WATCH`, `CANDIDATE`, `ACTIONABLE`, `EXECUTED`, `CANCELLED`.

### Decision Workflow Tools

```
decision_workflow_precheck(candidate_id)
decision_workflow_list_recommendations(account_id, status, user_action, security_code, recommendation_id, include_ignored, page, page_size)
decision_workflow_refresh_recommendations(account_id, security_codes, force, async_mode)
decision_workflow_apply_recommendation_action(recommendation_id, action, account_id, note)
decision_workflow_get_funnel_context(trade_id, backtest_id)
get_pulse_current()
get_pulse_history(limit)
get_regime_navigator()
get_action_recommendation()
explain_pulse_dimensions()
```

Notes:

- `decision_workflow_list_recommendations` returns unified recommendation objects from the decision workspace, including `security_name` for UI/agent display.
- `decision_workflow_refresh_recommendations` is the bridge from homepage/equity recommendations into the decision workspace.
- `decision_workflow_apply_recommendation_action` records the user's explicit choice on a recommendation.
- `decision_workflow_get_funnel_context` retrieves the complete end-to-end macro context evaluation spanning steps 1 to 3 (environment, direction, sector) and step 6 (audit/attribution). `backtest_id` should be passed when the agent needs deterministic audit replay instead of latest-backtest fallback.
- `decision_workflow_get_funnel_context` 的 `step3_sectors` 现在包含 `rotation_data_source`、`rotation_is_stale`、`rotation_warning_message`、`rotation_signal_date`；Agent 在输出轮动结论前应先检查这些字段，识别是否为历史 signal 回退结果。
- MCP 工具返回会额外附带顶层便捷摘要：`step3_status`（`current` / `fallback` / `unknown`）、`step3_data_source`、`step3_signal_date`、`step3_warning_message`，便于 agent 直接消费而不必重复解析嵌套字段。
- `get_pulse_current` returns the canonical `/api/pulse/current/` JSON envelope. Read `data.observed_at`, `data.data_source`, `data.is_reliable`, and `data.regime_context`; when the live Regime chain only yields `Unknown`, backend preserves the last valid snapshot instead of overwriting it with an unknown rebuild.
- `get_pulse_history` returns recent pulse history for trend inspection.
- `get_regime_navigator` returns the richer regime navigator output beyond the basic current regime.
- `get_action_recommendation` returns the current top-down allocation recommendation derived from regime + pulse.
- `explain_pulse_dimensions` gives a built-in semantic explanation of the pulse framework for agents.
- `action` supports: `watch`, `adopt`, `ignore`, `pending`.
- MCP / SDK 当前覆盖的是“推荐刷新、读取、用户动作、漏斗上下文”链路；`plans/generate`、`plans/update`、`execute/preview(plan_id)` 仍走 HTTP Decision Workspace API，而不是独立 MCP 工具。
- UI 层已将 `beta_gate` / `alpha_trigger` / `decision_rhythm` 收束到“决策工作台 / 决策模式”；MCP 仍可保留这些模块级工具用于自动化和运维，不代表它们是前台主导航入口。
- MCP 工具管理页的前端入口现为 `/settings/mcp-tools/`，归属“设置中心”。
- `start_ops_task` / `run_ops_workflow` / `agomtradepro://context/ops/current` 属于 Agent Runtime 的 frozen MCP 任务域契约；这里的 `ops` 表示任务域，不是前台页面路由。

Canonical response example for `decision_workflow_get_funnel_context`:

```json
{
  "success": true,
  "step3_status": "fallback",
  "step3_data_source": "stored_signal_fallback",
  "step3_signal_date": "2026-03-30",
  "step3_warning_message": "实时轮动重算失败，当前展示最近一次已落库信号，结果可能滞后。",
  "data": {
    "step1_environment": {
      "regime_name": "Recovery",
      "pulse_composite": 0.72,
      "regime_strength": "strong",
      "policy_level": "正常",
      "overall_verdict": "适合投资 (宏观环境支持)"
    },
    "step2_direction": {
      "action_recommendation": {
        "reasoning": "测试用资产配置建议"
      },
      "asset_weights": {
        "equity": 0.6,
        "bond": 0.2,
        "commodity": 0.1,
        "cash": 0.1
      },
      "risk_budget_pct": 0.7
    },
    "step3_sectors": {
      "sector_recommendations": [
        {
          "name": "红利",
          "score": 55.0,
          "alignment": "high",
          "momentum": "up"
        }
      ],
      "rotation_signals": [
        {
          "sector": "红利ETF",
          "signal": "BUY",
          "strength": 55.0
        }
      ],
      "rotation_data_source": "stored_signal_fallback",
      "rotation_is_stale": true,
      "rotation_warning_message": "实时轮动重算失败，当前展示最近一次已落库信号，结果可能滞后。",
      "rotation_signal_date": "2026-03-30"
    },
    "step6_audit": {
      "attribution_method": "brinson",
      "benchmark_return": 4.2,
      "portfolio_return": 8.0,
      "excess_return": 3.8,
      "allocation_effect": 1.5,
      "selection_effect": 1.8,
      "interaction_effect": 0.5,
      "loss_source": null,
      "lesson_learned": "顺周期资产需要配合更严格的仓位控制。"
    }
  }
}
```

Interpretation rule for agents:

- `rotation_is_stale=false`: Step 3 can be treated as current result, but still cite `rotation_signal_date`.
- `rotation_is_stale=true`: explicitly tell the user the sector/rotation view is a fallback to persisted signal and may lag live market conditions.
- `step3_status=fallback`: MCP caller may short-circuit on the top-level summary, but should still include `step3_signal_date` in user-facing output.

Recommended reading order for agents:

1. `decision_workflow_get_funnel_context(trade_id, backtest_id)` to understand macro context and audit replay.
2. `get_regime_navigator()` to inspect richer strategic guidance.
3. `get_pulse_current()` or `get_pulse_history(limit)` to inspect tactical strength and transition warnings.
4. `get_action_recommendation()` to obtain top-down allocation output.

### Unified Account Tools

```
list_accounts(account_type, status, limit)
get_account(account_id)
create_account(name, initial_capital, account_type)
get_account_positions(account_id)
get_account_performance(account_id, start_date, end_date)
```

`account_type` 是统一账户属性，支持：
- `real`
- `simulated`

### Simulated Trading Inspection Tools

```
list_simulated_accounts(status, limit)
get_simulated_account(account_id)
create_simulated_account(name, initial_capital, start_date)
execute_simulated_trade(account_id, asset_code, side, quantity, price)
get_simulated_positions(account_id)
get_simulated_performance(account_id)
run_simulated_daily_inspection(account_id, strategy_id, inspection_date)
list_simulated_daily_inspections(account_id, limit, inspection_date)
```

以上 `simulated_*` 工具保留兼容；新接入应优先使用统一账户工具。

### Account Position Tools

```
get_positions_detailed(portfolio_id, include_closed)
import_positions_csv(portfolio_id, csv_text, mode, dry_run)
import_positions_json(portfolio_id, positions, mode, dry_run)
export_positions_csv(portfolio_id, include_closed)
export_positions_json(portfolio_id, include_closed)
```

`mode` supports:
- `upsert`: create/update only imported symbols
- `replace`: create/update imported symbols and close non-imported open positions

### Transaction Tools

```
get_transactions_detailed(portfolio_id)
import_transactions_csv(portfolio_id, csv_text, mode, dry_run)
import_transactions_json(portfolio_id, transactions, mode, dry_run)
export_transactions_csv(portfolio_id)
export_transactions_json(portfolio_id)
```

`mode` supports:
- `append`: append imported transactions
- `replace`: delete existing transactions in portfolio and import new ones

### Capital Flow Tools

```
get_capital_flows_detailed(portfolio_id)
import_capital_flows_csv(portfolio_id, csv_text, mode, dry_run)
import_capital_flows_json(portfolio_id, capital_flows, mode, dry_run)
export_capital_flows_csv(portfolio_id)
export_capital_flows_json(portfolio_id)
```

`mode` supports:
- `append`: append imported flows
- `replace`: delete existing flows in portfolio and import new ones

### Account Bundle Tools

```
get_portfolio_statistics(portfolio_id)
export_account_bundle_json(portfolio_id)
export_account_bundle_csv(portfolio_id)
```

Bundle export aggregates:
- portfolio detail
- portfolio statistics
- positions
- transactions
- capital flows

## Example Conversations

### Conversation 1: Macro Analysis

```
User: What's the current macro environment?

Claude: [calls get_current_regime]
       Current Regime: Recovery
       Growth: up, Inflation: down

User: What assets should I invest in?

Claude: [calls get_recommended_assets]
       For Recovery regime, consider: stocks, commodities, real estate
```

### Conversation 2: Signal Creation

```
User: Can I create a signal for 000001.SH?

Claude: [calls check_signal_eligibility]
       Signal is eligible! Current regime matches your target.

User: Create it.

Claude: [calls create_signal]
       Signal created successfully. ID: 123
```

### Conversation 3: Backtesting

```
User: How would a momentum strategy perform?

Claude: [calls run_backtest]
       Running backtest for momentum strategy from 2023-01-01 to 2024-12-31...

       Results:
       - Annual Return: 12.5%
       - Max Drawdown: -15.2%
       - Sharpe Ratio: 1.35
```

## Resources

MCP Resources can be automatically read by AI:

```
agomtradepro://regime/current    # Current regime state
agomtradepro://policy/status     # Current policy status
agomtradepro://account/summary   # Default portfolio summary
agomtradepro://account/positions # Default portfolio position snapshot
agomtradepro://account/recent-transactions # Default portfolio recent trades
```

## Prompts

Built-in prompt templates for common tasks:

```
analyze_macro_environment    # Analyze macro and suggest investments
check_signal_eligibility     # Check if signal is eligible
```

## Troubleshooting

### MCP Server Not Starting

```bash
# Test manually
cd sdk
agomtradepro-mcp
```

If this command fails with MCP API errors, verify `mcp` major version is `1.x`:

```bash
python -m pip show mcp
```

### Connection Errors

1. Check AgomTradePro server is running: `http://127.0.0.1:8000`
2. Verify API token is correct
3. Check firewall settings
4. If proxy is enabled globally, set `NO_PROXY=127.0.0.1,localhost`

### Tool Not Available

1. Restart Claude Code
2. Verify MCP server config is correct
3. Check SDK is installed: `pip show agomtradepro-sdk`
4. Check MCP SDK is installed: `pip show mcp`
5. Confirm tools are registered: `python -c "import asyncio; from agomtradepro_mcp.server import server; print(len(asyncio.run(server.list_tools())))"`
