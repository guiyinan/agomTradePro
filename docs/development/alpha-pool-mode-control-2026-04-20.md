# Alpha Pool Mode Control

## 背景

- 首页 Alpha 候选池此前固定使用“最新有效估值覆盖池”。
- 当本地 `ValuationModel` 覆盖不足时，首页会退化成极小集合，用户无法自行切换。
- 这会造成“Alpha 只有几只股票可选”的观感，但根因其实是池子定义被写死。

## 本次改动

- 新增系统级默认配置：
  - `SystemSettingsModel.alpha_pool_mode`
- 新增三种可选池子模式：
  - `strict_valuation`
  - `market`
  - `price_covered`
- 首页 Alpha 面板新增“股票池模式”下拉框，当前用户可直接切换。
- 实时刷新接口会把当前选中的 `pool_mode` 一起传给 Qlib 推理任务。
- `PortfolioAlphaPoolResolver` 改为按模式解析股票池，而不是固定使用估值交集。

## 模式说明

- `strict_valuation`
  - 当前市场内，且具备最新有效估值覆盖的股票集合。
- `market`
  - 当前市场内、资产主数据已登记的股票集合。
- `price_covered`
  - 当前市场内、本地统一价格库已有覆盖的股票集合。

## 当前本地实测

- `strict_valuation`: `1` 只
- `market`: `287` 只
- `price_covered`: `42` 只

说明当前首页 Alpha 不再只能固定落在 `1` 只股票上；用户可按研究偏好主动切换池子定义。

## SDK / MCP 同步

- SDK:
  - `client.dashboard.alpha_stocks(..., pool_mode=...)`
  - `client.dashboard.alpha_refresh(..., pool_mode=...)`
- MCP:
  - `get_dashboard_alpha_candidates(..., pool_mode=...)`
  - `trigger_dashboard_alpha_refresh(..., pool_mode=...)`
- 文档已同步更新：
  - `docs/sdk/api_reference.md`
  - `docs/sdk/quickstart.md`
  - `docs/mcp/mcp_guide.md`
  - `sdk/README.md`
