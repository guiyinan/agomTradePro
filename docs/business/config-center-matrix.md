# 配置中心能力矩阵

## Summary

本表定义第一期“配置中心收口”覆盖的核心配置项，统一说明前端入口、API、SDK/MCP 能力、权限和生效方式。

## Matrix

| Key | 配置域 | 前端入口 | API | SDK/MCP | 权限 | 生效方式 | 备注 |
|---|---|---|---|---|---|---|---|
| `system_settings` | 系统设置 | `/account/admin/settings/` | 无统一只读 API | 无统一 SDK/MCP，前端查看 | `staff` | 保存后立即生效 | 审批策略、默认 MCP、协议文案 |
| `macro_datasources` | 宏观数据源配置 | `/macro/datasources/` | 无统一只读 API | 无统一 SDK/MCP，前端查看 | `staff` | 保存后由数据同步链使用 | AKShare/Tushare/FRED 等 |
| `market_data_providers` | 市场数据源状态 | `/market_data/providers/` | 页面/模块现有接口 | `client.market_data` + MCP market-data 工具 | `staff` | 状态实时读取 | 第一期开只读摘要 |
| `beta_gate` | Beta Gate 配置 | `/beta-gate/config/` | `/api/beta-gate/configs/` | `client.beta_gate` + `beta_gate_tools` | `staff` | 激活配置后生效 | 支持版本与回滚 |
| `valuation_repair` | 估值修复配置 | `/equity/valuation-repair/config/` | `/api/equity/config/valuation-repair/active/` | `client.equity` + `equity_tools` | `staff` | DB/Settings 配置，运行时读取 | 已支持版本与回滚 |
| `ai_provider` | AI Provider 配置 | `/ai/` | `/ai/api/providers/` | `client.ai_provider` + `ai_provider_tools` | `staff` | 保存后新请求生效 | 支持启停和优先级 |
| `trading_cost` | 交易费率配置 | `/account/settings/` | `/account/api/trading-cost-configs/` | `client.account` + `account_tools` | 登录用户/相关账户 | 保存后立即生效 | 账户级配置 |

## Config Center APIs

- `GET /api/system/config-center/`
- `GET /api/system/config-capabilities/`

## MCP Tools

- `list_config_capabilities`
- `get_config_center_snapshot`

## Notes

- 配置中心本期只负责“发现、摘要、跳转”，不替代原模块编辑页。
- 权限、审计、版本控制仍由原模块负责。
