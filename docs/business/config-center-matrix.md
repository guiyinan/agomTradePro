# 配置中心能力矩阵

## Summary

本表定义第一期“配置中心收口”覆盖的核心配置项，统一说明前端入口、API、SDK/MCP 能力、权限和生效方式。

## Matrix

| Key | 配置域 | 前端入口 | API | SDK/MCP | 权限 | 生效方式 | 备注 |
|---|---|---|---|---|---|---|---|
| `account_settings` | 账户设置 | `/account/settings/` | 无统一只读 API | 前端查看；与账户 API 协作 | 登录用户 | 保存后立即生效 | 个人资料、风险偏好、密码、MCP/SDK Token |
| `system_settings` | 系统设置 | `/account/admin/settings/` | 无统一只读 API | 无统一 SDK/MCP，前端查看 | `staff` | 保存后立即生效 | 审批策略、默认 MCP、协议文案、市场颜色约定 |
| `data_center_providers` | 数据中台 Provider 配置 | `/data-center/providers/` | `/api/data-center/providers/` | `client.data_center` + MCP config-center 工具 | `staff` | 保存后立即生效；刷新 data_center registry | Tushare Token / HTTP URL、AKShare、EastMoney、QMT、FRED 等统一在这里维护 |
| `data_center_runtime` | 数据中台运行状态 | `/data-center/monitor/` | `/api/data-center/providers/status/` | `client.data_center` + MCP data-center 工具 | `staff` | 状态实时读取 | 查看 Provider 健康状态、熔断和能力覆盖，不再保留旧 market_data 入口 |
| `beta_gate` | Beta Gate 配置 | `/beta-gate/config/` | `/api/beta-gate/configs/` | `client.beta_gate` + `beta_gate_tools` | `staff` | 激活配置后生效 | 支持版本与回滚 |
| `valuation_repair` | 估值修复配置 | `/equity/valuation-repair/config/` | `/api/equity/config/valuation-repair/active/` | `client.equity` + `equity_tools` | `staff` | DB/Settings 配置，运行时读取 | 已支持版本与回滚 |
| `ai_provider` | AI Provider 配置 | `/ai/` | `/api/ai/providers/` | `client.ai_provider` + `ai_provider_tools` | `staff` | 保存后新请求生效 | 支持启停和优先级 |
| `trading_cost` | 交易费率配置 | `/account/settings/` | `/api/account/trading-cost-configs/` | `client.account` + `account_tools` | 登录用户/相关账户 | 保存后立即生效 | 账户级配置 |

## Config Center APIs

- `GET /api/system/config-center/`
- `GET /api/system/config-capabilities/`

## MCP Tools

- `list_config_capabilities`
- `get_config_center_snapshot`
- `list_data_center_providers`
- `create_data_center_provider`
- `update_data_center_provider`
- `test_data_center_provider_connection`
- `get_data_center_provider_status`

## Notes

- 配置中心继续负责“发现、摘要、跳转”，但数据源相关入口已经彻底收口到 `data_center`。
- `account_settings`、`system_settings`、`data_center_providers`、`data_center_runtime` 均通过“设置中心”统一进入。
- `data_center_providers` 是“配置页”，`data_center_runtime` 是“状态页”；顶部导航与页面文案保持这个区分。
- 2026-04-05 起，旧 `/macro/datasources/` 与旧 `market_data` 对外入口全部下线，不再保留兼容层。
- 权限、审计、版本控制仍由原模块负责。
- 2026-03-23 起，`system_settings` 增加 `market_color_convention`，用于统一控制全站 `rise/fall/inflow/outflow` 的语义颜色映射；基础模板通过全局 CSS token 下发。
- 自定义系统配置页 `/account/admin/settings/` 与 Django Admin 已同步提供该开关，管理员无需手改 JSON 或模板。
- 2026-03-28 起，Provider 配置支持 `http_url`，用于给 Tushare Pro client 注入 `pro._DataApi__http_url`，适配第三方 Tushare 代理源。
- 2026-03-28 起，Provider 配置支持 `qmt` 条目，`extra_config` 可承载本地 XtQuant/QMT 参数。
