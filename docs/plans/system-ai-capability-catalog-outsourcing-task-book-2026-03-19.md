# 系统级 AI Capability Catalog 与统一路由外包实施任务书（2026-03-19）

> 生效日期：2026-03-19  
> 文档类型：外包实施规格 + 开发任务书 + 验收清单  
> 适用团队：外包开发团队、外包测试团队、内部技术验收团队  
> 适用范围：系统级 AI 中台、terminal、聊天窗口、MCP/tool registry、内部 API 自动采集、能力目录初始化脚本  
> 环境边界：仅开发/测试环境实现与验收；禁止直接改造生产执行链路权限模型

---

## 1. 背景与目标

当前系统里“AI 应该调用什么能力”是分散的：

1. terminal 有自己的 builtin command 和 router。
2. terminal command 配置在 `apps/terminal`，只对 terminal 生效。
3. prompt/tool calling 使用独立的 function registry。
4. 系统中存在大量 MCP 能力和内部 API，但没有统一、可检索、可审计的能力目录。
5. 不同聊天入口未来会复用 AI 中台，但目前没有系统级 capability catalog。

本任务目标是建设一个**系统级 AI Capability Catalog**，统一承载：

1. builtin commands
2. terminal command 配置
3. 现有 MCP/tool 描述
4. 全站内部 API 自动采集结果

并让 AI routing 统一升级为：

1. 先从 catalog 召回 top-k 候选能力
2. 再由 AI 在候选里做结构化决策
3. 最后按权限、确认、MCP 开关执行

本期必须完成：

1. 新建独立 `ai_capability` app，不把该能力继续塞进 terminal 私域。
2. 将现有 MCP 全量整理并入库。
3. 对全站 API 做自动采集入库。
4. 建立统一 capability catalog 数据模型。
5. 建立初始化脚本和增量同步脚本，支持新环境一键入库。
6. 建立系统级 capability routing service，并接入 terminal。
7. 保证未来聊天窗口可直接复用该能力，而不是再单独造一套。
8. 建立 catalog 管理端和最小可用审计能力。

本期明确不做：

1. embedding / 向量检索。
2. 多人审批流。
3. 自动开放所有采集到的高危接口执行权限。
4. 直接重构所有业务模块为 agent-native 架构。

---

## 2. 核心原则

### 2.1 系统级能力，不属于 terminal

本任务产物是系统级 AI 中台能力，terminal 只是第一个调用方。

实施时必须遵守：

1. capability catalog 不得放在 terminal app 内部作为私有模块。
2. route/registry/execution dispatch 必须设计成可供 terminal、chat、未来 agent/operator 共用。
3. terminal 只负责 UI 和自身交互状态，不负责系统级能力目录定义。

### 2.2 自动采集成立，但必须有安全分层

本任务要求“现有 MCP 全入库 + 全站 API 自动采集”，同时又要求自动采集记录默认可路由。

因此必须同步实现：

1. 自动分层
2. 风险分级
3. unsafe 阻断
4. 写操作确认

否则 catalog 会变成一个会误导 AI 的噪音库。

### 2.3 代码主导，数据库承载

本期采用“代码主导 + 数据库承载”的模式：

1. 能力的真实来源仍然来自代码与现有配置。
2. 数据库中的 capability catalog 负责：
   - 标准化结构化描述
   - 路由检索
   - 运营治理
   - 初始化落库
   - 审计与可视化
3. 禁止把数据库 catalog 设计成完全脱离代码的“任意执行器配置中心”。

---

## 3. 目标态定义

### 3.1 能力来源

系统级 capability catalog 必须覆盖以下四类来源：

1. `builtin`
   - 例如 terminal 内建 `/status`、`/regime`
2. `terminal_command`
   - 来自 `TerminalCommandORM`
3. `mcp_tool`
   - 来自现有 MCP / tool registry / function registry
4. `api`
   - 来自全站 Django URL / DRF endpoint 自动采集

### 3.2 标准能力结构

所有能力最终都必须被标准化为统一结构。至少包含：

1. `capability_key`
2. `source_type`
3. `source_ref`
4. `name`
5. `summary`
6. `description`
7. `category`
8. `tags`
9. `when_to_use`
10. `when_not_to_use`
11. `examples`
12. `input_schema`
13. `execution_kind`
14. `execution_target`
15. `risk_level`
16. `requires_mcp`
17. `requires_confirmation`
18. `enabled_for_routing`
19. `enabled_for_terminal`
20. `enabled_for_chat`
21. `enabled_for_agent`
22. `visibility`
23. `review_status`
24. `priority_weight`

### 3.3 自动采集后的分层

自动采集入库后，所有能力必须自动落入以下路由分组之一：

1. `builtin`
2. `tool`
3. `read_api`
4. `write_api`
5. `unsafe_api`

强制规则：

1. `GET/HEAD/OPTIONS` 默认归类 `read_api`
2. `POST/PUT/PATCH/DELETE` 默认归类 `write_api`
3. 命中敏感语义或高权限端点归类 `unsafe_api`
4. `unsafe_api` 默认 `enabled_for_routing=false`
5. `write_api` 默认 `requires_confirmation=true`
6. `read_api` 默认允许参与路由

### 3.4 路由流程

系统级 AI routing 统一为三段式：

1. `Capability Retrieval`
   - 从 catalog 中按确定性规则召回 top-k 候选
2. `Capability Decision`
   - AI 在候选里返回结构化 JSON 决策
3. `Execution Dispatch`
   - 统一走执行分发器，再进入权限和确认链

禁止保留以下旧模式作为主路由策略：

1. 纯前端关键词匹配
2. terminal 私有固定 intent 分类
3. 直接让 AI 在无候选约束下全量猜测全系统能力

---

## 4. 实施总拆分

建议拆成 7 个任务包，可并行开发，但必须按依赖顺序集成。

### WP-01 新建 ai_capability app 与基础模型

目标：建立系统级 capability catalog 承载层。

任务：

1. 新建 `apps/ai_capability` app。
2. 建立 ORM 模型：
   - `CapabilityCatalogModel`
   - `CapabilityRoutingLogModel`
   - `CapabilitySyncLogModel`
3. 配置 admin、serializer、repository、service 基础骨架。
4. 补齐 migration。

交付物：

1. 数据模型说明文档。
2. migration 脚本。
3. admin 页面截图。

验收标准：

1. `manage.py migrate` 可成功执行。
2. admin 中能查看 capability catalog。
3. 数据模型字段完整覆盖目标态要求。

### WP-02 MCP/tool 自动采集入库

目标：把现有系统 MCP/tool 全量整理入库。

任务：

1. 扫描现有 function registry / tool registry / MCP 描述来源。
2. 统一映射为 `CapabilityDefinition` DTO。
3. 写入 `CapabilityCatalogModel`。
4. 对未补全描述的 MCP 自动生成占位 metadata。
5. 所有现有 MCP 必须全部入库，不允许遗漏。

实现要求：

1. `ToolDefinition` 需要扩展导出能力 metadata 的能力。
2. 若现有 tool 没有 `when_to_use` / `when_not_to_use` / `examples`，需生成自动描述。
3. 自动生成记录必须标记：
   - `auto_collected=true`
   - `review_status=auto`

交付物：

1. MCP 来源清单。
2. MCP -> capability 映射表。
3. 全量入库报告。

验收标准：

1. 当前系统所有 MCP/tool 都能在 catalog 中查到。
2. 每条 MCP capability 都有 `capability_key` 和 `execution_target`。
3. 无描述的 MCP 也能以自动生成形式入库。

### WP-03 全站 API 自动采集入库

目标：扫描全站 API 并入 catalog。

任务：

1. 扫描 Django URL resolver 与 DRF endpoint。
2. 提取：
   - path
   - method
   - view class / action
   - docstring
   - serializer
   - permission classes
3. 生成 API capability 记录并写入 catalog。
4. 自动完成 route_group 分层：
   - `read_api`
   - `write_api`
   - `unsafe_api`
5. 自动识别高危端点并阻断路由。

高危识别最低要求：

1. 路径或名称命中以下语义时，优先判为高危：
   - `delete`
   - `reset`
   - `toggle`
   - `approve`
   - `execute`
   - `admin`
   - `token`
   - `secret`
   - `credential`
   - `bootstrap`
   - `migrate`
2. staff/admin 权限接口优先判为高危或高风险。
3. 无法提取清晰输入 schema 的写接口不得直接进入普通可路由集合。

交付物：

1. API 自动采集脚本。
2. API -> capability 映射统计。
3. route_group 分层报告。

验收标准：

1. 全站 API 能被扫描并入库。
2. 同步命令幂等。
3. `unsafe_api` 默认不参与路由。
4. 写接口默认带确认策略。

### WP-04 初始化脚本与同步脚本

目标：新环境一键落库，已有环境可增量同步。

任务：

1. 新增初始化命令：
   - `python manage.py init_ai_capability_catalog`
2. 新增同步命令：
   - `python manage.py sync_ai_capability_catalog`
3. 新增巡检命令：
   - `python manage.py review_ai_capability_catalog`
4. 接入现有 cold-start/init 流程。

初始化命令要求：

1. 全量扫描 builtin / terminal command / MCP/tool / 全站 API
2. 自动 upsert
3. 记录本次新增、更新、禁用数量

同步命令要求：

1. 同步新增来源
2. 同步已删除或失效来源状态
3. 幂等

交付物：

1. 三个管理命令源码。
2. 使用说明文档。
3. 一次完整初始化报告。

验收标准：

1. 新数据库执行初始化命令后 capability 表非空。
2. 重复执行无重复脏数据。
3. 同步命令能正确标记失效来源。

### WP-05 系统级 Capability Retrieval / Decision / Dispatch

目标：实现统一路由主链路。

任务：

1. 新增 `CapabilityRegistryService`
2. 新增 `CapabilityRetrievalService`
3. 新增 `CapabilityDecisionService`
4. 新增 `CapabilityExecutionDispatcher`

`CapabilityRegistryService` 要求：

1. 读取数据库 catalog
2. 根据入口上下文过滤：
   - terminal
   - chat
   - agent/operator
3. 根据用户状态过滤：
   - role
   - `mcp_enabled`
   - enabled flags

`CapabilityRetrievalService` 要求：

1. 使用确定性召回，不做 embedding
2. 使用以下字段打分：
   - `name`
   - `summary`
   - `description`
   - `tags`
   - `when_to_use`
   - `when_not_to_use`
   - `examples`
   - path/module/category
3. 返回 top-k 候选

`CapabilityDecisionService` 要求：

1. 只把 top-k 候选摘要交给 AI
2. AI 必须返回结构化 JSON：
   - `decision`
   - `selected_capability_key`
   - `confidence`
   - `reason`
   - `rejected_candidates`
   - `filled_params`
   - `missing_params`
3. 不允许外显思维链

`CapabilityExecutionDispatcher` 要求：

1. `builtin` -> builtin executor
2. `terminal_command` -> terminal command use case
3. `mcp_tool` -> tool executor
4. `api` -> internal API executor

验收标准：

1. 能用统一 route service 处理 terminal 输入。
2. top-k 候选可审计。
3. 决策结果可复现。
4. 执行链仍服从权限和确认策略。

### WP-06 接入 terminal，并为后续聊天窗口预留复用接口

目标：terminal 先接入，但接口设计必须支持其他聊天入口复用。

任务：

1. terminal 不再维护私有 capability 路由逻辑。
2. terminal chat 改为调用系统级 route service。
3. terminal 保留自身确认态、参数收集态、渲染态。
4. 设计统一 API 契约，供聊天窗口未来接入。

必须保证：

1. terminal 是第一接入方，不是唯一接入方。
2. route API 不得写成 terminal 专属字段命名。
3. 后续聊天窗口接入时不需要重写路由内核。

交付物：

1. route API 契约文档。
2. terminal 接入说明。
3. 未来聊天窗口接入说明。

验收标准：

1. terminal 输入“目前系统是什么状态”能走 catalog -> retrieval -> decision -> execute。
2. terminal `/status` `/regime` 仍可用。
3. 路由接口可被其他前端复用。

### WP-07 管理端、answer chain 与审计

目标：让 catalog 可运营、可排错、可验收。

任务：

1. 提供 catalog admin 管理页。
2. 支持按以下维度过滤：
   - `source_type`
   - `route_group`
   - `risk_level`
   - `review_status`
   - `enabled_for_routing`
3. 可编辑以下说明性字段：
   - `summary`
   - `description`
   - `when_to_use`
   - `when_not_to_use`
   - `examples`
   - `tags`
   - `priority_weight`
   - `visibility`
4. 接入 answer chain：
   - 非 admin 只能看概括步骤
   - admin 可看候选 capability、选择理由、拒绝理由、执行目标
5. 对非 admin 严禁暴露：
   - 数据库字段名
   - serializer 名称
   - source_ref
   - 内部 view class 名
   - execution_target 细节

验收标准：

1. admin 可在后台查看 catalog。
2. answer chain 在 terminal 中可展开。
3. 非 admin 不可见技术字段。
4. admin 可见排错所需细节。

---

## 5. 数据模型详细要求

### 5.1 CapabilityCatalogModel

建议字段如下：

1. `capability_key: CharField(unique=True)`
2. `source_type: CharField`
3. `source_ref: CharField`
4. `name: CharField`
5. `summary: TextField`
6. `description: TextField`
7. `route_group: CharField`
8. `category: CharField`
9. `tags: JSONField(list)`
10. `when_to_use: JSONField(list)`
11. `when_not_to_use: JSONField(list)`
12. `examples: JSONField(list)`
13. `input_schema: JSONField(dict)`
14. `execution_kind: CharField`
15. `execution_target: JSONField(dict or str)`
16. `risk_level: CharField`
17. `requires_mcp: BooleanField`
18. `requires_confirmation: BooleanField`
19. `enabled_for_routing: BooleanField`
20. `enabled_for_terminal: BooleanField`
21. `enabled_for_chat: BooleanField`
22. `enabled_for_agent: BooleanField`
23. `visibility: CharField`
24. `auto_collected: BooleanField`
25. `review_status: CharField`
26. `priority_weight: IntegerField or FloatField`
27. `created_at`
28. `updated_at`
29. `last_synced_at`

### 5.2 CapabilityRoutingLogModel

至少记录：

1. `entrypoint`
2. `user`
3. `session_id`
4. `raw_message`
5. `retrieved_candidates`
6. `selected_capability_key`
7. `confidence`
8. `decision`
9. `fallback_reason`
10. `execution_result`
11. `created_at`

### 5.3 CapabilitySyncLogModel

至少记录：

1. `sync_type`
2. `started_at`
3. `finished_at`
4. `total_discovered`
5. `created_count`
6. `updated_count`
7. `disabled_count`
8. `error_count`
9. `summary_payload`

---

## 6. 自动采集规则

### 6.1 MCP/tool 自动采集

必须覆盖：

1. prompt function registry
2. 现有 MCP tool 描述来源
3. 任何当前系统里可被 AI/tool calling 调用的工具定义

每个 MCP/tool 至少自动生成：

1. `summary`
2. `description`
3. `input_schema`
4. `tags`
5. `examples`

### 6.2 API 自动采集

必须采集：

1. URL path
2. HTTP method
3. view / action
4. serializer
5. permission classes
6. summary/docstring/description

默认分层：

1. `GET/HEAD/OPTIONS` -> `read_api`
2. `POST/PUT/PATCH/DELETE` -> `write_api`

高危命中规则：

1. staff/admin 权限接口
2. token/secret/credential/auth
3. delete/reset/toggle/approve/execute
4. bootstrap/migrate
5. config-center / system settings / runtime settings 等系统配置类高风险接口

这些接口进入 `unsafe_api`，默认不参与普通路由。

---

## 7. Route API 契约

建议统一接口：

`POST /api/ai-capability/route/`

请求：

```json
{
  "message": "目前系统是什么状态",
  "entrypoint": "terminal",
  "session_id": "xxx",
  "provider_name": "openai-main",
  "model": "gpt-4.1",
  "context": {}
}
```

响应：

```json
{
  "decision": "capability",
  "selected_capability_key": "builtin.system_status",
  "confidence": 0.94,
  "candidate_capabilities": [
    {
      "capability_key": "builtin.system_status",
      "name": "System Status"
    }
  ],
  "requires_confirmation": false,
  "reply": "## System Readiness...",
  "metadata": {
    "route": "capability",
    "provider": "terminal-router",
    "model": "router"
  },
  "answer_chain": {}
}
```

中置信度：

```json
{
  "decision": "ask_confirmation",
  "selected_capability_key": "builtin.system_status",
  "confidence": 0.67,
  "requires_confirmation": true,
  "reply": "检测到你可能想执行系统状态查询。",
  "metadata": {
    "route": "intent_suggestion"
  }
}
```

低置信度普通聊天：

```json
{
  "decision": "chat",
  "selected_capability_key": null,
  "confidence": 0.21,
  "requires_confirmation": false,
  "reply": "普通聊天回答",
  "metadata": {
    "route": "chat"
  }
}
```

---

## 8. 测试与验收要求

### 8.1 自动采集验收

1. 所有现有 MCP/tool 入库。
2. 全站 API 入库。
3. 初始化脚本幂等。
4. 同步脚本幂等。

### 8.2 路由验收

1. `目前系统是什么状态`
   - 正确召回系统状态 capability
2. `当前市场 regime`
   - 正确召回 regime capability
3. 普通闲聊
   - 正确回退 chat
4. 写操作问题
   - 命中写 capability 后仍需确认

### 8.3 安全验收

1. `unsafe_api` 不参与普通路由。
2. `write_api` 默认有确认。
3. `mcp_enabled=false` 时，MCP capability 不执行。
4. 非 admin answer chain 不暴露技术字段。

### 8.4 回归验收

1. terminal 现有 `/status` `/regime` 不回退。
2. terminal 现有 command execute 流程不失效。
3. terminal provider/model 列表不受 catalog 实现影响。

---

## 9. 交付物清单

外包团队必须交付：

1. `apps/ai_capability` 全量源码
2. migration
3. 初始化命令与同步命令
4. MCP 自动采集器
5. 全站 API 自动采集器
6. route service
7. terminal 接入代码
8. admin/catalog 管理端
9. 自动化测试
10. 采集结果报告
11. 风险接口分层报告
12. 最终验收自测清单

---

## 10. 内部验收关注点

内部验收时重点检查：

1. 外包是否真的把该能力做成“系统级 AI 中台”，而不是 terminal 私有模块换壳。
2. 自动采集是否真的覆盖了现有 MCP。
3. API 自动采集是否存在“全量放开路由”的危险实现。
4. route 是否是“top-k 检索 + AI 决策”，而不是继续靠前端/terminal 关键词硬编码。
5. 初始化脚本是否可在新环境一键建库和落库。
6. 非 admin answer chain 是否仍泄露内部字段。
7. catalog 是否能被未来聊天窗口复用，而不仅是 terminal 可调用。

---

## 11. 明确禁止事项

外包团队不得：

1. 将 capability catalog 继续实现成 terminal 私有模块。
2. 用前端关键词匹配替代系统级检索。
3. 让 AI 直接拼接 URL 调用任意内部 API。
4. 将 `unsafe_api` 默认开放给普通路由。
5. 将数据库 catalog 变成可任意写执行目标的万能配置中心。
6. 将 answer chain 技术字段直接暴露给普通用户。
7. 省略初始化脚本，只靠手工后台录入。

