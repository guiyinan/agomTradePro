# Web → TUI M3 Risk Center Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-risk-center-w25`；覆盖集中风控中心 1 个 staff route template。
- 复核确认既有 Risk Center runtime bundle 的 12 个 action 已覆盖 Classic 页面：
  全局底线、风险模板、账户策略、有效策略、例外、交易前预览、投后检查、日报与历史，
  以及底线/账户策略/例外三类确认写入。
- actions 通过 canonical IA 归入 `macro-regime.strategy`；Classic 页面发布
  `risk-center.effective-policy` 精确 deep link。
- 页面原有 staff-only 边界保持不变。TUI 读任务仍由 owner API 按账户范围授权，
  全局配置写入继续由后端限制管理员并要求理由；没有复制 Classic 的手写 JSON
  渲染和导出脚本。

## 验证与风险

- Risk Center page、runtime action 与自动投顾 UI 契约：`7 passed`。
- 既有 owner API 集成契约继续作为矩阵 API 证据；本 wave 未修改 API 或 Domain。
- migration inventory 与 TUI static contract 在本 wave 收口命令中复核。
- 真实 live-server 账户选择→有效策略→交易前/投后检查→确认写入→日报导出 UAT
  尚未执行；Classic 路由删除仍受 M5 稳定期、访问量和回滚门槛约束。
