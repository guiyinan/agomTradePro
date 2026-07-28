# Web → TUI M3 Terminal Config Retirement Wave 证据（2026-07-26）

## 范围与结论

- Wave：`M3-terminal-config-w23`；覆盖旧终端命令配置 1 个 staff route template。
- 核对确认 Classic 表单调用的 `/api/terminal/commands/*` 已被 Terminal owner
  正式退役，所有操作稳定返回 410，并明确要求使用 MCP/Agents 驱动的 Terminal。
- 因此本 wave 不在 TUI 中复活终端命令 CRUD，也不把 410 API 包装成新 action。
  `/terminal/config/` 保持原 staff 权限后，精确 302 到
  `ai-ops.terminal + terminal.agent_chat`。
- 物理模板作为回滚工件保留到 M5；当前 resolver 不再渲染其中已经失效的命令表单。

## 验证与风险

- 6 个 legacy command API 410 契约与 1 个 staff redirect 契约：`7 passed`。
- ruff 通过；`apps/terminal/interface/views.py` 同步补齐类型标注，增量 mypy 为
  `0 regressions`、`0 legacy errors`。
- 非 staff 用户继续得到 403，不会借重定向绕过原管理员边界。
- 真实浏览器 staff 跳转→Agent chat UAT 尚未执行；物理模板删除仍受 M5 稳定期和
  回滚门槛约束。
