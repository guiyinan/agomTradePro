# API / MCP / SDK 对齐说明（2026-03-14）

## 目的

本文档定义 AgomSAAF 当前对外接入的唯一事实来源，解决以下问题：

- 后端实际 API 路由与 SDK 调用不一致
- MCP 工具仍引用历史路径
- 本地开发与生产环境地址混用
- 本机存在多个 `8000` 进程时，网页、SDK、MCP 命中不同实例

## 一致性规则

1. SDK 与 MCP 只面向 canonical API 路径。
2. canonical API 路径优先使用 `/api/{module}/...`。
3. 若系统保留 `/{module}/api/...` 兼容入口，视为页面/历史兼容，不作为 SDK/MCP 契约。
4. 本地 MCP 与生产 MCP 必须拆成两个 server 名，不允许通过改同一个 server 的 `BASE_URL` 切环境。
5. 本地调试时，`127.0.0.1:8000` 只能保留一套 Django 进程。

## 当前 canonical 路径

| 模块 | canonical API | 说明 |
|------|---------------|------|
| regime | `/api/regime/` | SDK/MCP 使用 V2 current/history/distribution |
| policy | `/api/policy/` | SDK/MCP 不再走 `/policy/...` |
| macro | `/api/macro/` | 旧 `/macro/api/` 已废弃 |
| fund | `/api/fund/` | 读取 `rank/info/nav/holding/style` |
| sector | `/api/sector/` | 当前对外可用入口为 `rotation/` |
| rotation | `/api/rotation/` | recommendation/assets/configs/signals/templates/account-configs |
| hedge | `/api/hedge/` | pairs/alerts/holdings/actions |
| factor | `/api/factor/` | `all-factors/all-configs/top-stocks/create-portfolio/explain-stock` |
| backtest | `/api/backtest/` | `api/backtests/` 与 `api/run/` 为当前挂载结果 |
| equity | `/api/equity/` | valuation repair config 已对齐 |
| market_data | `/api/market-data/` | MCP 外部市场数据链已打通 |

## 已修复的典型错配

- macro SDK: `/macro/api/*` -> `/api/macro/*`
- policy SDK: `/policy/...` -> `/api/policy/...`
- fund SDK: 历史 `funds/*` -> 当前 `rank/info/nav/holding/style`
- sector SDK: 历史 `sectors/*` -> 当前 `rotation/`
- rotation SDK: `rotation/api/*` -> `/api/rotation/*`
- hedge SDK: `hedge/api/*` -> `/api/hedge/*`
- factor SDK: `factor/api/*` -> `/api/factor/*`
- regime SDK: distribution 不再通过 `history(limit=10000)` 侧算，改为 `/api/regime/distribution/`
- backtest SDK: `results/*` -> 当前 `/api/backtest/api/backtests/*`

## Regime V2 口径

Rotation、Sector 等依赖当前 regime 的模块，统一使用：

- Python: `apps.regime.application.current_regime.resolve_current_regime`
- HTTP: `/api/regime/current/`

禁止再引用不存在或过时的：

- `apps.regime.application.services.RegimeService`
- `/regime/api/...` 作为 SDK/MCP 默认入口

## MCP 环境拆分

仓库内 `.mcp.json` 只保留本地开发实例：

- `agomsaaf_local -> http://127.0.0.1:8000`

客户端全局配置建议保留两套：

- `agomsaaf_local -> http://127.0.0.1:8000`
- `agomsaaf_prod -> http://141.11.211.21:8000`

必须同时配置：

- `AGOMSAAF_BASE_URL`
- `AGOMSAAF_API_TOKEN`

兼容历史调用时，也可额外提供：

- `AGOMSAAF_API_BASE_URL`

## 本地运行约束

如果本机同时有多套 `manage.py runserver 8000`，会出现：

- 网页看到的是 A 进程
- MCP/SDK 请求命中的是 B 进程
- 日志来自 C 进程

本地回归前必须先确认：

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*runserver*8000*' } | Select-Object ProcessId, CommandLine
```

预期是只剩 1 条。

## 回归基线

2026-03-14 本地已验证以下链路：

- `get_current_regime`
- `get_policy_status`
- `list_macro_indicators`
- `sync_macro_indicator`
- `list_hedge_pairs`
- `list_rotation_assets`
- `list_backtests`
- `get_regime_distribution`
- `get_valuation_repair_config`
- `get_rotation_recommendation`

说明：

- `get_rotation_recommendation` 当前可返回结果，但若本地未配置 Tushare，会退化为 mock 价格数据。
- `list_sectors`、`list_funds` 若返回空列表，优先看本地数据是否为空，而不是先怀疑路由。
