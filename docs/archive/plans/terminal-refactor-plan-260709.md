# Terminal 重构：OpenAI Agents SDK + MCP

> 归档状态（2026-08-12）：仓库实现与验收完成。Terminal 已接入 OpenAI Agents SDK、MCP stdio、SSE、Provider 解析和持久化审批；2026-08-12 定向复核中 Agent Runtime、Terminal Agent、审批及真实装配测试 `427 passed`，生产浏览器证据另见 [`../../plans/web-to-tui-m5-browser-uat-evidence-2026-07-27.md`](../../plans/web-to-tui-m5-browser-uat-evidence-2026-07-27.md)。

## Summary
将 `terminal` 从“自研命令/路由/工具执行后端”改成薄前端入口；真正的 AI 执行迁移到 `agent_runtime`，使用 OpenAI Agents SDK 调 MCP server。当前选择固定为：大幅删除旧 terminal 命令后端、第一版直接支持流式输出、保留现有 `ai_provider` 多 Provider 配置。

参考依据：OpenAI Agents SDK 支持 MCP、streaming、sessions、tracing、multi-provider；当前 PyPI 最新 `openai-agents` 为 `0.18.0`。官方文档见 [Agents SDK](https://openai.github.io/openai-agents-python/)、[MCP](https://openai.github.io/openai-agents-python/mcp/)、[Streaming](https://openai.github.io/openai-agents-python/streaming/)、[MultiProvider](https://openai.github.io/openai-agents-python/ref/models/multi_provider/)。

## Key Changes
- 新增 `openai-agents>=0.18,<0.19` 依赖；保留现有 `mcp>=1.20,<2`。
- 在 `apps/agent_runtime` 新增终端代理服务：
  - 使用 `MCPServerStdio` 启动现有 `sdk/agomtradepro_mcp.server`。
  - 使用 `Runner.run_streamed()` 产出 SSE 事件。
  - MCP 工具开启 `cache_tools_list=True`，`include_server_in_tool_names=True`。
  - 通过动态 tool filter 只暴露当前用户允许的 MCP 工具。
- 保留多 Provider：
  - 从现有 `ai_provider` 读取 provider/base_url/api_key/default_model。
  - OpenAI-compatible provider 通过 Agents SDK `MultiProvider` 或 OpenAI-compatible client 接入。
  - 继续记录现有 usage/quota/fallback 语义。
- `terminal` 后端只保留薄入口：
  - `POST /api/terminal/chat/stream/`：主入口，SSE。
  - `POST /api/terminal/chat/`：非流式兼容入口，调用同一 agent service。
  - `POST /api/terminal/session/`：生成 session id。
  - `GET /api/terminal/audit/`：保留审计读取。
- 废弃旧 command API：
  - `/api/terminal/commands/*` 返回 `410 Gone`，响应说明已迁移到 MCP/Agents。
  - 从 TUI metadata、generated/published graph、前端入口中移除旧 command list/execute/capabilities/by_category 展示。
  - 不删除旧 ORM 表和 migrations，避免破坏历史数据与回滚。

## Frontend/TUI
- 将 `ai-ops.terminal` 和 `cli.terminal` 改成一个自然语言操作台：
  - 输入框、发送按钮、停止按钮、流式消息区、工具调用进度区。
  - 不再展示“终端命令目录/按分类命令/执行命令”。
  - SSE 事件类型固定为：`message_delta`、`tool_called`、`tool_output`、`approval_required`、`final`、`error`。
- TUI action 改为：
  - `terminal.agent_stream` -> `/api/terminal/chat/stream/`
  - `terminal.agent_chat` -> `/api/terminal/chat/`
- 普通用户文案不暴露 `/api/`、method、path placeholder 等实现细节，继续遵守 TUI metadata v3 规则。

## Implementation Notes
- 新 agent service 放在 `apps/agent_runtime/application` 定义 DTO/UseCase/Protocol，OpenAI Agents SDK 和 MCP stdio 连接放在 `apps/agent_runtime/infrastructure`。
- `terminal/interface/api_views.py` 只做认证、序列化、SSE 响应封装，不能直接碰 ORM 或 MCP SDK。
- MCP 默认使用 stdio，因为当前 `sdk/agomtradepro_mcp/server.py` 只暴露 `server.run(transport="stdio")`。
- 审批策略：
  - 只读工具默认直接允许。
  - medium/high/write/admin 风险工具产出 `approval_required` SSE 事件，不自动执行。
  - 后续确认走现有 agent proposal/approval 体系，不复用旧 terminal confirmation token。
- session 存储第一版使用 Agents SDK session 能力或项目内轻量 session repository；session id 继续由 `/api/terminal/session/` 返回。

## Test Plan
- 单元测试：
  - agent service 能构建 stdio MCP server 参数。
  - provider resolver 能从 `ai_provider` 选择个人 provider、系统 fallback、默认模型。
  - tool filter 按用户 MCP/RBAC 权限过滤。
  - 旧 `/api/terminal/commands/*` 返回 `410`。
- API 测试：
  - `/api/terminal/chat/` 返回 `reply/session_id/metadata`。
  - `/api/terminal/chat/stream/` 返回 `text/event-stream`，至少包含 `message_delta` 和 `final`。
  - MCP 工具调用事件能映射为 `tool_called/tool_output`。
  - agent 异常返回 `error` SSE 事件，非流式返回 `502`。
- TUI 测试：
  - terminal screen 默认 action 是新 agent action。
  - catalog 不再展示 terminal command 旧入口。
  - 前端能消费 SSE 并追加消息、工具进度、最终状态。
- 回归测试：
  - `sdk/tests/test_mcp` 和 `tests/acceptance/test_mcp_server.py` 继续通过。
  - `tests/unit/test_tui_workbench.py`、`tests/unit/test_terminal_api.py`、`tests/api/test_terminal_api_edges.py` 按新契约更新。

## Assumptions
- 第一版不新增 Streamable HTTP MCP server；继续用现有 stdio MCP。
- 不删除旧 terminal 数据表和 migrations，只让旧命令 API 从产品面和 active API 面退出。
- 旧 `apps/prompt/application/agent_runtime.py` 暂不全局删除，只从 terminal 路径解绑；其他 prompt/strategy 调用后续单独迁移。
- `ai_capability` 的 MCP 治理目录可以保留，但不再作为 terminal 自然语言执行路由。
