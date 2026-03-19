# AgomSAAF AI 中台 Agent Runtime 重构实施方案

## Summary

本方案用于解决当前 AI 中台“机械调用 AI API，无法将系统数据与模型推理闭环融合”的问题，并给出一份可直接实施的重构方案。

当前仓库的真实现状是：

- `apps/terminal` 仍以“字符串替换 + 单次模型调用”为主
- `apps/strategy` 虽然会准备 `macro/regime/asset_pool/portfolio/signals` 上下文，但只是把数据包直接塞给 prompt 占位符
- `apps/prompt` 已存在 placeholder、chain、tool registry、tool-calling 概念，但执行层没有真正完成 tool schema 下发、工具执行、结果回灌、二轮推理
- `apps/ai_provider` 目前统一接口仍停留在 `messages -> content`，没有把 tools、tool_choice、结构化输出、tool_calls 暴露给上层

因此问题的本质不是“系统里没有数据”，而是“系统数据没有进入一个受控、可追踪、可复用的 Agent Runtime”。

本方案采用以下默认方向：

- 目标：将现有 `apps/prompt + apps/ai_provider` 升级为统一 Agent Runtime
- 范围：优先覆盖通用 AI 中台，再平移接入 `terminal` 与 `strategy`
- 方法：保留现有 PromptTemplate / ChainConfig 资产，优先重构执行层，而不是先推翻数据模型
- 优先级：先做只读型工具和问答/分析能力，不做写操作和交易执行类工具
- MCP 关系：显式复用仓库内置 MCP，MCP 作为 Runtime 的外部工具/资源暴露层，而不是另起一套平行 AI 工具体系

---

## 1. 目标与边界

## 1.1 本期目标

本期必须完成：

- 统一 Agent Runtime 执行入口
- 标准化上下文构建层 `ContextBundle`
- 标准化工具注册和工具执行闭环
- AI Provider tools / tool_calls 接口打通
- `apps/prompt` 真正支持 `TOOL_CALLING` / `HYBRID`
- `terminal` 与 `strategy` 切到统一 Runtime
- 执行日志增加上下文、工具轨迹、轮次追踪

本期不做：

- 多 Agent 协同调度
- 长期记忆系统
- 向量库 / RAG 平台
- 写操作型工具开放给模型
- 通用 workflow DSL

## 1.2 成功标准

重构完成后，系统应满足：

- AI 回答可以基于系统实时数据，而不是仅依赖静态 prompt
- 模型需要额外数据时，可发起工具调用，而不是把所有原始数据直接塞进首轮 prompt
- 同一套 Runtime 同时服务 `terminal` 与 `strategy`
- 同一套 Runtime 能同时服务 Django 内部调用和 MCP 外部调用
- 每次执行都能追踪：
  - 用了哪些上下文域
  - 调了哪些工具
  - 每轮模型输入输出摘要
  - token、耗时、错误

## 1.3 非目标

本方案不试图把现有系统一步改造成通用 autonomous agent 平台；它的目标是先把“AI 能安全、稳定、低 token 成本地利用系统内结构化数据”这件事做扎实。

---

## 2. 当前实现诊断

## 2.1 `apps/terminal` 的问题

当前 `apps/terminal/application/services.py` 中，`execute_prompt_command()` 的行为是：

- 从 `user_prompt_template` 做简单占位符替换
- 拼出 `system` 和 `user` 两条消息
- 直接调用 `ai_client.chat_completion()`

这意味着：

- terminal 无法按问题动态拉取系统数据
- 无法按需访问 portfolio / regime / macro 等域
- 所有数据都只能在 prompt 编写阶段硬编码
- 无法进行多轮工具执行

## 2.2 `apps/strategy` 的问题

当前 `apps/strategy/application/ai_strategy_executor.py` 已经有 `_prepare_context()`，会聚合：

- `macro`
- `regime`
- `asset_pool`
- `portfolio`
- `signals`

但后续只是：

- `ExecutePromptRequest(..., placeholder_values=context)`
- 或 `ExecuteChainRequest(..., placeholder_values=context)`

这意味着：

- 数据虽然被收集了，但没有做摘要压缩和结构约束
- 数据是否真正进入 prompt 取决于模板里是否写了对应占位符
- 原始对象可能过大、不可控、不可追踪
- 模型无法按需查询更细粒度的数据

## 2.3 `apps/prompt` 的问题

`apps/prompt/application/use_cases.py` 的问题更核心：

- `ExecutePromptUseCase.execute()` 仍是“加载模板 -> 解析 placeholder -> render -> 单次模型调用”
- `_resolve_placeholders()` 只支持用户值、宏观、Regime、函数型 placeholder
- `ExecuteChainUseCase` 里的 `PARALLEL`、`TOOL_CALLING`、`HYBRID` 目前都退化为串行执行
- `available_tools` 只是配置资产，没有真正进入 AI provider 请求

结论：

- prompt 模块现在本质上是“模板管理 + 单轮调用器”
- 还不是一个真正的 agent 执行引擎

## 2.4 `apps/ai_provider` 的问题

`apps/ai_provider/infrastructure/adapters.py` 已支持 Responses API 和 chat.completions 双路径，但统一接口仍缺失：

- `tools`
- `tool_choice`
- `response_format`
- `tool_calls`
- `raw_response`

结果是：

- 即使底层 SDK 支持 tools，上层也用不上
- prompt 模块无法实现真正的工具执行循环
- 结构化输出和工具输出都无法标准化

---

## 3. 目标架构

## 3.1 目标拓扑

建议将 AI 执行链路收敛为以下结构：

`terminal / strategy / future modules`

-> `Agent Runtime`

-> `Context Providers + Internal Tool Registry`

-> `AI Provider Adapter`

-> `OpenAI-compatible models`

-> `Execution Trace / Logs`

同时对外保留：

`Agent Runtime`

-> `Facade / SDK`

-> `MCP tools / MCP resources / MCP prompts`

## 3.2 核心原则

重构必须遵守：

- 首轮 prompt 只注入必要摘要，不注入整包原始数据
- 详细数据通过工具调用按需获取
- 工具接口比 ORM 更窄，禁止模型自由拼接内部查询
- 所有执行环节都有 trace
- Runtime 负责执行闭环，业务模块只负责声明意图和上下文范围
- 保持 `API -> SDK -> MCP` 既有分层，不让 Agent Runtime 直接绕开既有 MCP/SDK 契约

## 3.4 MCP 融合原则

仓库已经有内置 MCP，且目录结构完整：

- `sdk/agomsaaf_mcp/tools`
- `sdk/agomsaaf_mcp/resources`
- `sdk/agomsaaf_mcp/prompts`

因此本次重构不应把 Runtime 和 MCP 拆成两套能力，而应采用：

- Django 内部调用走 `Agent Runtime -> internal tools/context providers`
- 外部 Agent 调用走 `MCP -> SDK/Facade -> Agent Runtime`

需要明确的边界是：

- Agent Runtime 是“内部执行内核”
- MCP 是“对外协议层和产品化暴露层”
- Runtime 不直接依赖 MCP transport
- MCP 不自己实现一套独立推理/上下文/工具闭环

换句话说，MCP 应复用 Runtime，而不是和 Runtime 各做一套工具系统。

## 3.3 运行时标准流程

标准执行流程固定为：

1. 业务模块构造任务请求
2. Runtime 根据 scope 构建 `ContextBundle`
3. Runtime 生成消息和 tools schema
4. 模型首轮回答
5. 若产生 tool calls，则执行工具并记录结果
6. 把工具结果回灌给模型继续推理
7. 得到最终答案或结构化输出
8. 写入执行日志与 trace

---

## 4. 新增核心能力设计

## 4.1 Agent Runtime

建议新增一个统一应用层能力，例如：

- `apps/prompt/application/agent_runtime.py`

主要对象：

- `AgentExecutionRequest`
- `AgentExecutionResponse`
- `AgentRuntime`
- `AgentTurnResult`
- `ToolCallRecord`

### `AgentExecutionRequest`

建议字段：

- `task_type`
- `user_input`
- `provider_ref`
- `model`
- `temperature`
- `max_tokens`
- `context_scope`
- `context_params`
- `tool_names`
- `response_schema`
- `max_rounds`
- `session_id`
- `metadata`

### `AgentExecutionResponse`

建议字段：

- `success`
- `final_answer`
- `structured_output`
- `used_context`
- `tool_calls`
- `turn_count`
- `provider_used`
- `model_used`
- `total_tokens`
- `estimated_cost`
- `error_message`

### `AgentRuntime` 职责

- 构造 messages
- 获取 tools schema
- 调用 AI provider
- 解析 tool calls
- 执行工具
- 拼接 tool result messages
- 控制回合次数和终止条件
- 记录完整 trace

## 4.2 ContextBundle

建议新增：

- `ContextBundle`
- `ContextScope`
- `ContextSection`

`ContextBundle` 必须同时包含：

- `summary`
- `raw_data`
- `references`
- `generated_at`

其中：

- `summary` 用于首轮 prompt
- `raw_data` 供工具查询和审计
- `references` 记录数据来自哪个 provider / repo / snapshot

### 支持的上下文域

首批固定支持：

- `macro`
- `regime`
- `portfolio`
- `signals`
- `asset_pool`

### 上下文策略

增加可配置策略：

- `summary_only`
- `summary_plus_selected_raw`
- `tool_only`

默认使用：

- `summary_plus_selected_raw`

即：

- 首轮给摘要和少量关键字段
- 详细对象通过工具查

## 4.3 Context Provider

建议新增标准接口：

- `MacroContextProvider`
- `RegimeContextProvider`
- `PortfolioContextProvider`
- `SignalContextProvider`
- `AssetPoolContextProvider`

统一方法建议：

- `build_summary(params) -> dict | str`
- `build_raw_data(params) -> dict`
- `build_section(params) -> ContextSection`

约束：

- Provider 内部负责查询仓储、序列化和必要裁剪
- 业务模块不再手工组装大 `context` 字典

## 4.4 Tool Registry

现有 `function_registry.py` 可保留，但需升级为真正的运行时工具注册层。

需要支持：

- 工具白名单
- 工具 schema 输出
- 工具执行
- 工具错误标准化
- 工具权限域
- 工具成本级别

首批工具建议：

- `get_macro_summary`
- `get_macro_indicator`
- `get_macro_series`
- `get_regime_status`
- `get_regime_distribution`
- `get_portfolio_snapshot`
- `get_portfolio_positions`
- `get_portfolio_cash`
- `get_valid_signals`
- `get_asset_pool`

这些工具要分成两层：

- Internal tools：供 Runtime 在 Django 内部直接执行
- MCP-exposed tools：对外暴露的 MCP 工具，优先复用 SDK/Facade，必要时调用 Runtime 任务接口

### 工具设计原则

- 参数必须显式且窄化
- 返回结构必须稳定且 JSON 可序列化
- 不允许暴露任意 SQL / ORM / filter 表达式给模型
- 所有工具都必须是只读

## 4.5 Tool Call Loop

Runtime 必须实现真正的多轮循环：

1. 下发 messages + tools
2. 模型返回：
   - 直接答案
   - 或 tool calls
3. 若为 tool calls：
   - 校验工具名
   - 校验参数
   - 执行工具
   - 生成 tool result messages
4. 继续下一轮

终止条件固定：

- 得到最终文本答案
- 或得到符合 schema 的结构化输出
- 或达到 `max_rounds`
- 或发生不可恢复错误

默认 `max_rounds` 建议为 `4`

---

## 5. 对现有模块的重构方案

## 5.1 `apps/ai_provider`

### 目标

把 AI provider 从“文本聊天适配器”升级为“Agent 运行时模型适配器”。

### 必改内容

扩展统一接口，支持：

- `messages`
- `tools`
- `tool_choice`
- `response_format`
- `metadata`

返回结构新增：

- `tool_calls`
- `raw_response`
- `request_type`
- `finish_reason`

### Responses API 路径

实现：

- tools 下发
- 原生 tool call 提取
- 文本输出提取
- 使用量统计统一

### chat.completions 回退路径

实现：

- tools 下发
- tool calls 提取
- 与 Responses API 返回结构统一

### 兼容策略

如果某 provider 不支持原生 tools：

- 先尝试原生调用
- 失败后按 provider 能力决定是否回退
- 最后才允许走协议式 `<tool_call>` 文本解析

文本协议解析只作为兼容，不作为主流程。

## 5.2 `apps/prompt`

### `ExecutePromptUseCase`

从单轮执行器升级为可复用的底层 building block：

- 保留模板读取和 placeholder 解析能力
- 但不再直接承担所有 AI 执行逻辑

建议拆分为：

- `PromptPreparationService`
- `AgentRuntime`
- `PromptExecutionLogger`

### `ExecuteChainUseCase`

保留链配置模型，但补齐真实执行语义：

- `SERIAL`：逐步执行
- `PARALLEL`：至少支持并行组调度
- `TOOL_CALLING`：进入 agent tool loop
- `HYBRID`：首步或中间步允许工具调用

当前退化逻辑必须删除：

- `_execute_parallel -> _execute_serial`
- `_execute_tool_calling -> _execute_serial`
- `_execute_hybrid -> _execute_serial`

### PromptTemplate 的定位调整

重构后 PromptTemplate 应主要负责：

- system prompt
- task instruction
- output contract
- context requirements
- tool whitelist

而不再负责：

- 搬运整包业务数据
- 作为唯一数据接入方式

### 建议新增模板元数据

建议扩展模板/链配置，增加：

- `context_requirements`
- `context_policy`
- `toolset`
- `answer_contract`

如果暂时不想改数据库模型，可先放入 JSON 字段或 `extra_config`。

## 5.3 MCP / SDK 融合

### 重构目标

把仓库内置 MCP 变成 Agent Runtime 的标准外部入口，而不是独立旁路。

### 建议分层

- Django app 内部领域能力
- Facade / UseCase 聚合层
- SDK
- MCP tools/resources/prompts

对 Runtime 的接法建议是：

- 新增面向 AI 任务的 facade 或 API
- SDK 提供稳定方法
- MCP tools 只做协议映射、参数接收、结果返回

### MCP 应承担的角色

MCP 更适合承载：

- task-oriented tools
- context resources
- workflow prompts
- RBAC 和审计接入点

而不是承担：

- 模型多轮推理控制
- 上下文构建核心逻辑
- 数据聚合核心逻辑

### 与 Runtime 的最佳结合方式

建议新增一类 MCP 能力：

- `run_agent_task`
- `get_agent_context_snapshot`
- `explain_agent_trace`

它们底层不自己拼数据，而是调用统一 Runtime 或 facade。

### MCP 复用策略

已有 MCP tools/resources/prompts 可按以下方式接入：

- 已有只读数据工具继续保留
- 能映射为 Runtime internal tool 的，抽取公共 facade，MCP 和 Runtime 共用
- 需要 Agent 问答/分析的，新增 task-oriented MCP tools，而不是在 MCP 端再写一份 prompt 逻辑

### 必须避免

- Runtime 一套 tools，MCP 再复制一套 tools
- MCP resources 自己聚合一份上下文，Runtime 再聚合一份
- MCP prompts 和 Django prompt template 各写各的任务契约

目标应该是“一个内核，多种入口”。

## 5.4 `apps/terminal`

### 重构目标

把 terminal 从“prompt 命令执行器”改为“Agent 问系统入口”。

### 新行为

terminal 接到用户自然语言问题后：

- 构造 `AgentExecutionRequest`
- 指定允许的上下文域和工具白名单
- 调用 Runtime
- 返回答案和 trace 摘要

### 推荐接入能力

首批 terminal 问答支持：

- 当前 regime
- 当前组合仓位
- 最新宏观摘要
- 当前有效信号
- 组合风险暴露解释

### 需要避免

- terminal 自己再拼一份 system data 文本
- terminal 自己维护工具执行逻辑

## 5.5 `apps/strategy`

### 重构目标

把 strategy 中的 AI 策略执行从“模板绑定数据”升级为“任务驱动分析”。

### 改造点

`_prepare_context()` 不再直接生成一个大字典给 placeholder 使用，而改为：

- 生成 `context_scope`
- 生成 `context_params`
- 交给 Runtime 统一构建 `ContextBundle`

### AI 策略模板职责

策略模板改为描述：

- 任务目标
- 输出格式
- 可用工具
- 风险约束

不再要求模板显式列出所有原始字段。

### 输出要求

最终输出仍应保持为标准化信号列表，例如：

- `asset_code`
- `direction`
- `confidence`
- `reason`
- `risk_notes`

建议后续把 `AIResponseParser` 逐步替换为 schema-based parser，但本期可以先保留。

---

## 6. 目录与代码组织建议

建议新增或调整如下位置：

- `apps/prompt/application/agent_runtime.py`
- `apps/prompt/application/context_builders.py`
- `apps/prompt/application/tool_execution.py`
- `apps/prompt/application/trace_logging.py`
- `apps/prompt/domain/agent_entities.py`
- `apps/prompt/domain/context_entities.py`

建议保留并演进：

- `apps/prompt/application/use_cases.py`
- `apps/prompt/infrastructure/adapters/function_registry.py`
- `apps/ai_provider/infrastructure/adapters.py`

MCP/SDK 相关重点位置：

- `sdk/agomsaaf_mcp/tools`
- `sdk/agomsaaf_mcp/resources`
- `sdk/agomsaaf_mcp/prompts`

接入方改造重点：

- `apps/terminal/application/services.py`
- `apps/strategy/application/ai_strategy_executor.py`

---

## 7. 分阶段实施计划

## 7.1 Phase 1：Runtime 基础设施

目标：

- 建立 `AgentExecutionRequest/Response`
- 建立 `AgentRuntime`
- 扩展 AI provider tools 接口

交付件：

- Runtime 基础类
- provider adapter 扩展
- 单轮 + 工具回合闭环最小实现

验收标准：

- 可以用 mock tool 完成 1 次工具调用 + 1 次最终回答

## 7.2 Phase 2：Context 层落地

目标：

- 实现 `ContextBundle`
- 接入宏观、Regime、组合、信号、资产池 provider

交付件：

- 5 个 context providers
- summary/raw_data 双层输出
- scope/params 构建能力

验收标准：

- 同一任务请求可按 scope 生成稳定上下文摘要
- 不需要业务方手写大 context 字典

## 7.3 Phase 3：Tool Registry 落地

目标：

- 把现有 function registry 升级为真正可执行工具体系

交付件：

- 只读工具白名单
- schema 校验
- 错误标准化
- trace 记录

验收标准：

- 模型可以主动请求宏观、Regime、portfolio、signal 类数据

## 7.4 Phase 4：MCP 融合落地

目标：

- 让内置 MCP 显式复用 Agent Runtime，而不是继续做旁路工具层

交付件：

- Runtime 对外 facade/API
- task-oriented MCP tools
- context MCP resources 与 Runtime ContextBundle 对齐
- MCP prompt 与 Runtime task contract 对齐

验收标准：

- 外部 Agent 可通过 MCP 调用统一 Runtime 能力
- MCP tools/resources 不再复制 Django 内部聚合逻辑

## 7.5 Phase 5：Prompt/Chain 执行语义升级

目标：

- 修复 `TOOL_CALLING / HYBRID / PARALLEL` 的空壳实现

交付件：

- 真正的 tool-calling chain
- 基础并行组执行框架
- 链中步骤上下文和工具调用兼容

验收标准：

- `execution_mode=TOOL_CALLING` 的 chain 不再退化为 serial

## 7.6 Phase 6：Terminal 接入

目标：

- 把 terminal 迁移到 Agent Runtime

交付件：

- terminal 问答入口改造
- trace 展示基础字段

验收标准：

- terminal 能回答“基于系统数据”的问题，而不是纯模板回答

## 7.7 Phase 7：Strategy 接入

目标：

- 把 AI strategy 迁移到 Agent Runtime

交付件：

- AI 策略上下文接入改造
- 输出 schema 约束
- 策略回归测试

验收标准：

- AI 策略能按需查询组合/信号/宏观/Regime 数据，输出稳定信号结果

---

## 8. 数据模型与接口细化

## 8.1 Runtime 请求接口

建议统一接口如下：

```python
@dataclass
class AgentExecutionRequest:
    task_type: str
    user_input: str
    provider_ref: Any | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    context_scope: list[str] | None = None
    context_params: dict[str, Any] | None = None
    tool_names: list[str] | None = None
    response_schema: dict[str, Any] | None = None
    max_rounds: int = 4
    session_id: str | None = None
    metadata: dict[str, Any] | None = None
```

## 8.2 Tool Call Record

```python
@dataclass
class ToolCallRecord:
    tool_name: str
    arguments: dict[str, Any]
    success: bool
    result: Any
    error_message: str | None = None
    duration_ms: int = 0
```

## 8.3 Context Section

```python
@dataclass
class ContextSection:
    name: str
    summary: Any
    raw_data: Any
    references: dict[str, Any]
```

---

## 9. 日志、审计与可观测性

## 9.1 执行日志新增字段

建议在 prompt 执行日志或新增 agent 日志表中记录：

- `execution_id`
- `task_type`
- `session_id`
- `provider_used`
- `model_used`
- `turn_count`
- `used_context`
- `tool_calls`
- `final_answer`
- `structured_output`
- `total_tokens`
- `estimated_cost`
- `response_time_ms`
- `status`
- `error_message`

## 9.2 Trace 粒度

每轮至少记录：

- 输入消息摘要
- 是否携带 tools
- 模型输出摘要
- 是否包含 tool calls
- 工具执行结果摘要

## 9.3 风险控制

默认风险控制：

- 只允许只读工具
- 最大工具轮次限制
- 单次执行工具数量限制
- 工具超时
- provider 错误统一降级

---

## 10. 测试计划

## 10.1 单元测试

必须覆盖：

- Runtime 无工具调用时直接返回答案
- Runtime 单工具调用闭环
- Runtime 多工具调用闭环
- 工具异常时的错误记录和继续策略
- Context provider summary/raw_data 构建
- AI provider Responses API tool call 提取
- AI provider chat.completions tool call 提取

## 10.2 集成测试

必须覆盖：

- terminal 提问当前 regime 和组合暴露，系统返回基于工具调用的答案
- strategy 执行 AI 策略，模型按需查询 portfolio/signals/macro/regime
- `TOOL_CALLING` chain 真正走工具执行

## 10.3 回归测试

必须确认：

- 旧的普通 prompt 模板仍能执行
- 不使用 tools 的调用路径不回归
- provider fallback 机制保持可用

---

## 11. 实施顺序建议

建议按以下顺序推进，不要并行乱改：

1. 先扩 `apps/ai_provider` 接口
2. 再建 `AgentRuntime`
3. 再做 `ContextBundle` 和 providers
4. 再把 tool registry 执行闭环接上
5. 再补 MCP 与 Runtime 对齐层
6. 再修 `apps/prompt` 的 tool-calling / hybrid 语义
7. 最后接 terminal
8. 最后接 strategy

原因：

- provider 接口不先升级，Runtime 没法闭环
- Runtime 不先稳定，terminal/strategy 接入只会重复返工
- MCP 不先和 Runtime 对齐，后面会出现两套工具体系
- strategy 依赖上下文最复杂，必须后置

---

## 12. 验收清单

满足以下条件才能认为本方案交付完成：

- AI 中台存在统一 Runtime，而不是各模块各自拼 prompt
- Runtime 支持至少一轮真实 tool calling
- terminal 问答可基于系统数据回答
- strategy AI 分析可按需读取 portfolio/signals/macro/regime
- prompt chain 的 `TOOL_CALLING` 和 `HYBRID` 不再是空壳
- 每次执行都可追踪 context 和 tool trace
- 无工具场景下旧功能不回归

---

## 13. 默认实现决策

本方案默认锁定以下实现决策，后续实施不再重复讨论：

- 继续保留 `apps/prompt` 作为统一 AI 中台宿主
- 继续保留 `PromptTemplate / ChainConfig`，优先升级执行层
- 首期不引入向量库
- 首期只做只读工具
- 首期统一使用 `ContextBundle`，禁止业务模块直接向模型注入整包系统对象
- `terminal` 与 `strategy` 为第一批接入方
- `max_rounds` 默认 `4`
- tool calling 优先走 provider 原生能力，文本协议仅作兼容回退
- 内置 MCP 为一等集成对象，必须复用 Runtime 与 ContextBundle，不单独复制 AI 执行逻辑

---

## 14. 下一步建议

如果按本方案进入实施，建议下一步直接拆成 3 个执行包：

- 包 A：`ai_provider + agent_runtime`
- 包 B：`context providers + tool registry`
- 包 C：`terminal + strategy` 接入和回归测试

这样可以保证基础能力先稳定，再做业务接入，不会出现边接入边返工 Runtime 的情况。
