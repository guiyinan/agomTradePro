# Web → TUI M2 AI Provider Wave 证据（2026-07-26）

## M2-ai-provider-core-w8

- Owner：`ai_provider`
- Classic route：`/ai/`、`/ai/detail/<provider_id>/`、
  `/ai/detail/<provider_id>/edit/`
- TUI screen：管理员使用 `ai-ops.system-providers`；个人服务商使用
  `ai-ops.providers`
- 兼容策略：三个 Classic 页面保留带任务参数的 scope-aware deep link，
  M5 退出门槛满足前不删除路由或模板。

## 任务闭环

管理员可在 `ai-ops.system-providers` 完成总体状态、列表、详情、创建、
更新、启停、连通性测试、用量检查和删除。普通用户在
`ai-ops.providers` 完成本人服务商的列表、详情、创建、更新、启停和
删除，owner API 继续执行对象归属与管理员权限校验。

本 wave 补齐了 Classic 编辑表单已有但 TUI 未声明的字段：

- 共用：故障切换、说明和结构化扩展配置；
- 系统服务商：每日和每月预算；
- API Key：统一使用 `password` input，不进入 URL 预填或可见 markup。

所有非 GET action 现在发布明确 `effect` 和
`confirmation_required=true`。带完整参数的 GET deep link 可以自动读取；
写入 deep link 只展开、预填非敏感字段并聚焦，不自动提交。

## 验证

- `tests/component/test_ai_provider_page_views.py`：`6 passed`
  - 覆盖管理员入口，以及个人/系统详情与编辑的 scope-aware deep link。
- `tests/api/test_ai_provider_api_edges.py`：`16 passed`
  - 覆盖系统/个人 owner API、对象归属、密钥掩码、配额与连通性。
- `tests/unit/test_tui_workbench.py`：`200 passed`
  - 覆盖 action 可见性、确认契约、完整字段集和密码字段。
- `python scripts/web_template_migration_inventory.py --check`
  - `templates=195 route_pages=117 A=130 B=17 C=41 D=7`
- `python scripts/check_tui_static_contracts.py`
  - `407 rule(s), 5 source(s)`
- `npm run test:tui-js`：`25 passed`。
- AgomTUI 同步、build check、runtime JS `6 passed`、Python `70 passed`。
- `ruff check`：通过。
- 增量 mypy：`0 regressions`。

## 未验证风险与回滚点

- 真实 live-server 的创建、更新、连通性测试与写后刷新 UAT 待 M2 合并前
  与其他 wave 一起执行。
- Classic 页面仍受至少 14 天、稳定版本、旧入口访问量和无 P0/P1 阻断
  门槛约束。
- 回滚单位为 AI Provider runtime metadata、通用 deep-link 行为、三个
  Classic banner 与矩阵记录；owner API 本 wave 未改变。

## M2-ai-provider-access-w9

- Classic route：`/ai/me/`、`/ai/quotas/`、`/ai/logs/`
- TUI screen：`ai-ops.providers`、`ai-ops.user-quotas`、
  `ai-ops.system-providers`
- 兼容策略：三个 Classic 页面保留 role-aware deep link，并把已验证的
  provider、status、limit 筛选参数带入 TUI。

个人服务商页对应 8 个本人 action；配额页对应列表、详情、单用户更新和
批量下发；日志页按角色分别进入 `ai-ops.my-ai-logs` 或新增的
`ai-ops.system-ai-logs`。个人日志 owner API 补上 `provider` 筛选参数，
并继续用当前用户约束查询，因此传入其他用户的 provider ID 只会得到空
结果，不会越权返回数据。

W9 验证：

- owner API + Classic 页面：`26 passed`；
- TUI AI Provider/角色可见性定向用例：`4 passed`（另有 196 deselected）；
- W8 完整 workbench 回归：`200 passed`。
- IA `6 passed`，上游 TUI JS `25 passed`，下游 JS/Python `6/70 passed`。

W9 的 live-server 日志筛选、单用户配额更新和批量下发 UAT 仍待 M2 合并
前统一执行。回滚单位为个人日志筛选参数、系统日志 action/panel、三个
Classic banner 与矩阵记录。
