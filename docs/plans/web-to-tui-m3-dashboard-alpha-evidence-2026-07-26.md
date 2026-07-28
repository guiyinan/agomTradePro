# Web → TUI M3 Dashboard Alpha Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-dashboard-alpha-w30`；覆盖 Alpha 完整排名与推荐历史 2 个 route templates。
- canonical screen：`research.signals`。完整排名使用 Dashboard owner 的
  `/api/dashboard/alpha/stocks/?format=json` 契约，支持 general/portfolio scope、组合、
  股票池口径和返回数量，保留原始 rank、新鲜度、阶段、来源与评分日。
- 推荐历史支持组合、交易日、证券、阶段、来源筛选，并以 run ID 查看当前用户范围内的
  快照详情。
- 没有把返回 HTML 的 Dashboard partial 当成 JSON 完成证据；排名 action 固定
  `format=json`。相关 partial 仍由 Dashboard 主页面消费，留待其消费者生命周期收口。
- 两个 Classic 页面均增加准确 TUI deep link，兼容期内保留。

## 验证与风险

- TUI metadata + IA：`7 passed`。
- Dashboard Alpha JSON、历史 list/detail 和两个 Classic 页面契约：`7 passed`。
- `ruff` 通过；production metadata mypy：0 regressions、0 legacy errors。
- live-server scope 切换、组合隔离、空历史、404 详情和大排名分页/性能 UAT 尚未完成；
  Classic 删除仍受 M5 量化退出门槛约束。
