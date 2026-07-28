# Web → TUI M2 Rotation User Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M2-rotation-user-w16`；Classic routes：`/rotation/signals/`、
  `/rotation/account-configs/`。
- TUI 信号任务：列表、最新信号与详情；首屏保留数据质量、新鲜度、
  可执行性和阻断原因，避免用户把过期或低质量信号当成执行依据。
- TUI 账户任务：我的配置列表/详情/按账户查询/创建/更新/删除/应用模板，
  并提供模板列表；写操作均要求登录、显式确认并在写后刷新。
- 所有账户配置查询和 mutation 继续通过 owner API 按
  `request.user` 的账户范围过滤，不允许用路径 ID、请求体 account ID 或模板操作
  越权访问其他用户配置。

## 验证与风险

- TUI 定向 `1 passed`（206 deselected）；IA `6 passed`。
- 跨用户 mutation 隔离定向 `1 passed`；越权创建被验证为 `400/403`，
  越权更新、应用模板和删除均保持不可见语义。
- ruff、增量 mypy、inventory 与 static contract 均通过。
- 真实 live-server 信号筛选→查看质量→账户配置 CRUD→应用模板 UAT 待
  M2 合并前补齐。
- 两个 Classic 页面暂留兼容；后续移除仍受 M5 的 14 日稳定窗口、
  访问量与回滚门槛约束。
