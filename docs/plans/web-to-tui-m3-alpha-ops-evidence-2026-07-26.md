# Web → TUI M3 Alpha Ops Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-alpha-ops-w27`；覆盖 Alpha 推理与 Qlib 数据运维 2 个 staff route templates。
- `research.signals` 已提供两个 staff 只读 overview，并补齐 superuser 的五种确认式异步任务：
  通用推理、单组合推理、全部启用组合批量推理、Universe 数据刷新、组合范围数据刷新。
- 字段与 owner serializers 对齐，包括日期、候选数量、Universe、组合、回看窗口和资产池口径；
  资产池选项复用 Alpha Application 真源，不在 Terminal 复制业务枚举。
- owner API 继续执行 staff/superuser 权限、输入校验、重复任务 409 和 Celery 异步投递。
  Classic 页面只增加准确 deep link，兼容期内保留。

## 验证与风险

- Alpha owner API + page contracts：`59 passed`。
- TUI metadata + IA：`8 passed`。
- `ruff` 通过；production metadata mypy：0 regressions、0 legacy errors。
- 两页共享 `_tabs.html` 不冒充独立任务，转 M5 `remove_with_consumer`。
- live-server 五种任务的 202/409、任务进度/失败回执和 Celery 实际执行 UAT 尚未完成；
  Classic 删除仍受 M5 量化退出门槛约束。
