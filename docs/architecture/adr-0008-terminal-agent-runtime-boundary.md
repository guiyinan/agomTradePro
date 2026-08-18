# ADR-0008：Terminal Agent 多用户运行时边界

- 状态：已接受（仅 TAR-01 契约冻结）
- 日期：2026-08-18
- 范围：`apps/agent_runtime` 的 Domain/Application 合同
- 依赖：`docs/plans/terminal-agent-multi-user-runtime-plan-2026-08-18.md`

## 决策

Web/TUI 的 Agent 请求必须先成为 owner-scoped、可幂等识别的 queued run，
再由未来的 durable admission/worker 执行。TAR-01 只冻结边界，不把现有同步
`OpenAIAgentsTerminalService` 接到新 API，也不提前创建数据库、Celery、broker 或
生产 route。当前生产 inline 路径继续保留，但由既有单槽和 60 秒闸门保护。

未来 API composition root 的唯一入口是
`TerminalQueuedRunApplicationBoundary` → `SubmitTerminalQueuedRunUseCase` →
`TerminalQueuedSubmissionPort`。任何 queued route 不得 import、构造或调用
`OpenAIAgentsTerminalService`；该服务只能在 TAR-03 的专用 worker composition 中出现。

## 冻结的职责与状态

| 对象/层 | 所有权 | 不负责 |
|---|---|---|
| `AgentTask` | 用户请求、既有 proposal/timeline/approval 关联与业务结果引用 | broker 投递、worker lease、队列顺序 |
| `TerminalAgentRunContract` | run selector、runtime mode、request digest、deadline 与 dispatch 状态 | ORM、Redis、Celery、模型/MCP 调用 |
| `SubmitTerminalQueuedRunUseCase` | 只接受 `web_queued`、校验 owner identity 与 adapter 不可替换性 | 持久化实现、发布、执行 |
| `TerminalQueuedSubmissionPort` | TAR-02 将提供的 durable admission seam | 直接执行 Agent |
| broker envelope | 仅 `run_id` + `task_id` | prompt、token、工具参数、provider secret |

允许的 dispatch 状态与方向由
`apps/agent_runtime/domain/terminal_agent_run_contract.py` 冻结：

```text
accepted -> queued -> claimed -> running
running -> waiting_approval -> queued/resumed -> running
queued/claimed/running/waiting_approval -> cancel_requested -> cancelled
claimed/running -> completed | failed | timed_out | orphaned
```

终态不可再次执行；重复的同一 owner/client request 只能返回同一稳定 run，不能
重新触发 provider、模型或 MCP。

## 幂等、保留与错误边界

- 幂等候选至少绑定 `actor_user_id + client_request_id + request_digest`；
  adapter 不得替换 `run_id`、`task_id`、runtime mode 或 digest。
- `accepted_at`、`deadline_at`、事件时钟必须 timezone-aware；不得用请求重试时间
  覆盖源时钟。
- 原始 prompt、provider key、token、cookie、password、授权头和工具参数不得进入
  broker envelope、普通日志或可恢复事件。若后续审计确实需要上下文，只能由独立
  retention policy 产生最小化、脱敏、可过期的引用；TAR-01 不默认持久化 prompt。
- API/SSE 的公开错误必须使用稳定错误码与 bounded `503/429` 语义，不暴露 ORM、
  Celery、Redis、route 或 provider 异常文本。
- queued 不可用时只能明确暂停/拒绝（`PAUSE`/bounded `503`）；不得静默回退到
  无界同步 Agent 执行。

## 兼容策略

- 新 API 保留 `/api/terminal/runs/` create/detail/events/cancel/queue 的 ID-only
  命名与 `202 Accepted` envelope；SDK、MCP、TUI 复用同一 selector/status/event
  字段，不各自发明第二套 run identity。
- 旧同步 Web/TUI helper 在 TAR-02/TAR-03 完成前继续走 legacy inline 闸门；它不是
  queued API 的 adapter，也不能被新 composition root 隐式复用。
- feature flag 的安全默认固定为 queued intake/worker 关闭、legacy inline 单槽、
  60 秒 timeout、queue unavailable 时 `PAUSE`、emergency stop 关闭；生产配置仍由
  `core/settings/production.py` 与 VPS compose 显式覆盖。

## 证据与未完成项

本 ADR 的机器证据是：

- `terminal_agent_run_contract.py`、`terminal_agent_run_ports.py`、
  `terminal_agent_run_api_contract.py`、`terminal_runtime_queue_policy.py`；
- `TerminalQueuedRunApplicationBoundary` 的 AST guard 与 pure tests；
- TAR-01 focused regression、增量 mypy、architecture guard 和 CI。

这些证据不等于 TAR-01 exit gate 已全部通过。仍缺现状 1/5/10/20 负载基线、
durable PostgreSQL admission、真实 broker/worker、SSE/SDK/TUI 端到端、容量/chaos、
生产 UAT、回滚与观察窗口。因此 TAR-01 保持 `active`，TAR-02/TAR-03 不提前启动。
