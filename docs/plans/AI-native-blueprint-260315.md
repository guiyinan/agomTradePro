  # AgomTradePro AI-Native 升级蓝图：从 L3+ 迈向 L4，再到 L5

  ## Summary

  目标是把 AgomTradePro 从“AI 可接入的系统”升级为“以 Agent 为一等公民的系统”。

  - L1 传统系统：只有网页和 API
  - L2 AI-enabled：加了 SDK / 函数调用
  - L3 AI-ready：有 MCP tools/resources/prompts，有权限治理
  - L4 AI-native：任务化工具、上下文包、工作流编排、状态记忆、人机协作闭环
  - L5 Agent-operable system：Agent 可稳定承担日常运营任务

  当前状态可判断为 L3+：

  - 已具备 canonical API + SDK + MCP tools/resources/prompts
  - 已具备基础 RBAC / audit
  - 已具备部分工作流基建，如 decision_rhythm、decision_workflow
  - 仍主要停留在“API 映射给 AI”，缺少真正的任务型工具、上下文包、Agent 状态层和全链路人机协作闭环

  本规划采用你确认的方向：

  - 目标：L4 -> L5 分阶段推进
  - 范围：全域运营
  - 交付形态：产品 + 技术蓝图

  默认分三阶段：

  1. Phase A: L4 Foundation，把系统升级为任务型 AI-native 平台
  2. Phase B: L4.5 Operationalization，让 Agent 能稳定参与跨模块日常协作
  3. Phase C: L5 Agent-Operable，让 Agent 在强治理下承担受控运营职责

  ———

  ## 1. Target Definition

  ### L4 定义

  系统不再只提供底层查询/写工具，而是提供：

  - 任务型工具
  - 面向任务的上下文包
  - 显式工作流状态
  - proposal -> approval -> execute 闭环
  - 面向 Agent 的审计与回放

  ### L5 定义

  系统在满足 L4 的基础上，进一步支持：

  - 多 Agent / 多角色协作
  - 可恢复的任务状态机
  - 明确的人机边界
  - 自动化运营任务
  - 生产级 SLO、回放、治理与风险隔离

  ### L5 达标门槛

  必须同时满足：

  - 80% 以上高频运营场景可由 Agent 通过任务型工具完成
  - 所有高风险动作必须走 proposal/approval gate
  - 100% Agent 调用具备 request_id、actor、resource、decision_trace 审计链
  - 关键任务支持 resume / replay / handoff
  - 至少一条生产业务链路达到“默认 Agent 先处理，人类兜底”的模式

  ———

  ## 2. Current-State Diagnosis

  ### 已有能力

  - API/SDK/MCP canonical 路由已收口
  - MCP server 已支持 tools/resources/prompts
  - SDK 已有较完整模块覆盖
  - MCP 已有 RBAC 和 audit wrapper
  - 后端已有审批、决策节奏、信号、回测、实时监控等业务域
  - 部分资源已经提供只读上下文，如 regime、policy、account summary

  ### 当前缺口

  - MCP tool 多为底层 API 映射，不是任务导向
  - resources 过少，且不是按任务/角色组织
  - prompt 是静态模板，不是 workflow contract
  - 缺少 Agent session / task / memory 数据模型
  - 缺少 proposal artifact、approval artifact、execution artifact 三段式实体
  - 缺少标准化“失败可恢复”机制
  - 缺少任务级 SLA、指标和回放链路
  - 缺少针对多 Agent 协作的编排层

  ———

  ## 3. Architecture Vision

  ## 3.1 目标拓扑

  AI Client / Claude Code / Internal Agents
          │
          ▼
  MCP Gateway Layer
  - tools
  - resources
  - prompts
  - RBAC
  - audit
  - task contracts
          │
          ▼
  Agent Orchestration Layer   ← 新增核心层
  - task registry
  - task state machine
  - handoff / resume
  - policy guardrails
  - approval gates
  - execution planner
          │
          ▼
  Application Facade Layer    ← 新增 facade/use-case 聚合层
  - research facade
  - monitoring facade
  - risk facade
  - execution facade
  - ops facade
          │
          ▼
  Existing Domain Apps
  regime / macro / signal / policy / backtest / realtime / account /
  simulated_trading / strategy / audit / decision_rhythm / decision_workflow / ...
          │
          ▼
  DB / Cache / Celery / External providers

  ## 3.2 分层原则

  - 系统 API 仍是唯一业务真入口
  - SDK 仍是 canonical Python client
  - MCP 不再直接暴露碎片 API，而以任务 contract 为主
  - 新增 Orchestration Layer 作为 Agent-native 核心，不把 workflow 逻辑散落在 MCP 文件中
  - 高风险动作统一在后端闭环，不允许仅靠 prompt 约束

  ———

  ## 4. Product Capability Model

  需要把全域运营拆成 5 类 Agent-native 能力域。

  ## 4.1 Research Domain

  目标：AI 能完成投研、归因、候选生成、决策建议
  核心能力：

  - 宏观环境分析
  - 信号审查
  - 候选资产筛选
  - 回测解释
  - 组合建议生成

  ## 4.2 Monitoring Domain

  目标：AI 能持续巡检并定位问题
  核心能力：

  - 实时价格异常调查
  - 市场状态巡检
  - 风险暴露变化提示
  - 任务运行状态解释
  - 数据新鲜度检查

  ## 4.3 Decision Domain

  目标：AI 能产生结构化 proposal，并被审批
  核心能力：

  - decision request draft
  - proposal explanation
  - approval checklist
  - risk summary
  - rollback recommendation

  ## 4.4 Execution Domain

  目标：AI 在批准后触发受控执行
  核心能力：

  - execute approved plan
  - execution status tracking
  - failure recovery suggestion
  - post-trade summary

  ## 4.5 Operations Domain

  目标：AI 参与系统运营和异常处理
  核心能力：

  - task monitor triage
  - provider health diagnosis
  - config drift summary
  - audit report generation
  - MCP permission diagnosis

  ———

  ## 5. Phase Plan

  ## Phase A: L4 Foundation

  ### 目标

  把系统从“工具集合”升级为“可被 Agent 稳定操作的任务平台”。

  ### 核心交付

  #### A1. 引入 Agent Task Domain

  新增模块建议：

  - apps/agent_runtime/
  - apps/agent_runtime/domain/
  - apps/agent_runtime/application/
  - apps/agent_runtime/interface/
  - apps/agent_runtime/infrastructure/

  新增核心实体：

  - AgentTask
  - AgentTaskStep
  - AgentContextSnapshot
  - AgentProposal
  - AgentExecutionRecord
  - AgentHandoff
  - AgentGuardrailDecision

  建议状态机：

  - draft
  - context_ready
  - proposal_generated
  - awaiting_approval
  - approved
  - rejected
  - executing
  - completed
  - failed
  - needs_human
  - cancelled

  #### A2. 建立任务型 Facade

  新增 facade 层，统一聚合现有 app 能力：

  - research_facade
  - monitoring_facade
  - decision_facade
  - execution_facade
  - ops_facade

  每个 facade 负责：

  - 跨 app 聚合数据
  - 输出稳定 DTO
  - 执行前置校验
  - 生成可审计 artifact

  #### A3. 重构 MCP 为任务优先

  保留现有底层工具，但新增任务型工具作为推荐入口。

  新增第一批任务工具：

  - analyze_macro_and_generate_asset_view
  - review_signal_and_generate_decision_request
  - investigate_realtime_anomaly
  - prepare_rebalance_proposal
  - summarize_portfolio_risk_changes
  - triage_system_health_issues
  - generate_audit_followup_actions

  这些工具必须返回结构化结果，不允许自由文本为主。

  #### A4. 建立任务上下文包 Resource

  新增按角色/任务组织的 MCP resource。

  建议新增：

  - agomtradepro://context/research/current
  - agomtradepro://context/monitoring/current
  - agomtradepro://context/decision/current
  - agomtradepro://context/execution/current
  - agomtradepro://context/ops/current

  每个 resource 输出固定字段：

  - current regime
  - policy status
  - active signals summary
  - open decision requests
  - top risk alerts
  - recent task failures
  - portfolio overview
  - data freshness summary

  #### A5. 把高风险动作统一改为三段式

  所有高风险工具统一收口为：

  1. generate proposal
  2. request approval
  3. execute approved action

  高风险域包括：

  - create/update/delete signal
  - rebalance / execute trade
  - policy event write
  - portfolio mutation
  - config changes
  - system-level replay/reset

  ### A阶段验收标准

  - 至少 10 个任务型 MCP tools 上线
  - 至少 5 个 context resources 上线
  - 高风险写操作全部支持 proposal -> approval -> execute
  - 每个 AgentTask 都有 request_id、actor、tool_trace、resource_trace
  - 至少 3 条端到端任务链路通过自动化验收

  ———

  ## Phase B: L4.5 Operationalization

  ### 目标

  让 Agent 从“能完成任务”提升到“能持续参与运营”。

  ### 核心交付

  #### B1. 引入 Agent Memory / Session Layer

  新增实体：

  - AgentSession
  - AgentWorkingMemory
  - AgentArtifact
  - AgentObservation
  - AgentConclusion

  用途：

  - 保存任务上下文
  - 跨步骤复用中间产物
  - 支持 handoff/resume
  - 支持同一用户多轮工作连续性

  #### B2. 引入 Handoff 机制

  支持以下 handoff：

  - AI -> human
  - human -> AI
  - agent A -> agent B

  handoff artifact 必须包含：

  - current_state
  - completed_steps
  - pending_steps
  - assumptions
  - blocking_issues
  - required_role
  - linked_artifacts

  #### B3. 引入 Policy Guardrails Engine

  新增 guardrail decision 点：

  - write action precheck
  - data quality precheck
  - confidence threshold gate
  - market-hours gate
  - approval requirement gate
  - abnormal exposure gate

  对每次决策输出：

  - allowed
  - blocked
  - needs_human
  - degraded_mode

  #### B4. 标准化异常恢复

  每个任务必须定义：

  - retryable failures
  - non-retryable failures
  - human escalation conditions
  - recovery action suggestions

  #### B5. 引入运营级 KPI / SLO

  对 Agent 系统本身定义指标：

  - task success rate
  - proposal acceptance rate
  - approval turnaround time
  - human escalation rate
  - replay success rate
  - tool latency p50/p95
  - stale-context rate

  ### B阶段验收标准

  - 至少 50% 高频任务支持 resume
  - 至少 30% 任务支持 handoff
  - 所有任务失败结果可归类并有 recovery strategy
  - 审批和执行链路具备完整 artifact trace
  - 有 dashboard 可观察 Agent 运营状态

  ———

  ## Phase C: L5 Agent-Operable

  ### 目标

  让 Agent 成为受控的运营参与者，而非只是一层辅助查询接口。

  ### 核心交付

  #### C1. 多 Agent 角色体系

  定义系统级 Agent 角色：

  - ResearchAgent
  - MonitoringAgent
  - RiskAgent
  - ExecutionAgent
  - OpsAgent

  每类 Agent：

  - 只拥有本域工具
  - 有明确输入输出 contract
  - 有升级/交接规则

  #### C2. Agent Planner / Router

  新增 planner/router 组件：

  - 根据任务类型选择 agent
  - 根据上下文选择所需 resources
  - 根据风险级别决定 approval path
  - 根据失败模式选择 retry / handoff / human

  #### C3. 自动运营任务

  建议首批自动化任务：

  - 每日开盘前研究摘要
  - 盘中实时异常巡检
  - 收盘后风险变化总结
  - 每日 audit follow-up
  - provider health triage
  - decision queue aging cleanup

  #### C4. 生产级治理

  必须补齐：

  - prompt/tool versioning
  - artifact schema versioning
  - replay by version
  - sandbox mode for execution simulation
  - emergency kill switch
  - deny-by-default high-risk tools
  - model/provider fallback policy

  #### C5. 人机协作操作台

  建议新增统一 Agent Ops UI：

  - task queue
  - proposal inbox
  - approval center
  - handoff queue
  - execution timeline
  - replay inspector
  - audit explorer

  ### C阶段验收标准

  - 至少 3 条日常运营链路由 Agent 默认先处理
  - 人工只处理 approval/escalation/exceptions
  - 100% 高风险动作都可追溯到 proposal 和 approval
  - 支持任务回放和审计定位
  - 生产可设置 Agent 运行白名单和停机开关

  ———

  ## 6. Public APIs / Interfaces / Types

  以下是必须新增或收口的公开接口与类型。

  ## 6.1 新增后端 API

  ### Agent Runtime API

  建议新增 canonical root：

  - /api/agent-runtime/

  建议 endpoints：

  - POST /api/agent-runtime/tasks/
  - GET /api/agent-runtime/tasks/
  - GET /api/agent-runtime/tasks/{id}/
  - POST /api/agent-runtime/tasks/{id}/resume/
  - POST /api/agent-runtime/tasks/{id}/cancel/
  - POST /api/agent-runtime/tasks/{id}/handoff/
  - GET /api/agent-runtime/tasks/{id}/artifacts/
  - GET /api/agent-runtime/tasks/{id}/timeline/

  ### Proposal API

  建议新增：

  - POST /api/agent-runtime/proposals/
  - GET /api/agent-runtime/proposals/{id}/
  - POST /api/agent-runtime/proposals/{id}/submit-approval/
  - POST /api/agent-runtime/proposals/{id}/approve/
  - POST /api/agent-runtime/proposals/{id}/reject/
  - POST /api/agent-runtime/proposals/{id}/execute/

  ### Context Snapshot API

  建议新增：

  - GET /api/agent-runtime/context/research/
  - GET /api/agent-runtime/context/monitoring/
  - GET /api/agent-runtime/context/decision/
  - GET /api/agent-runtime/context/execution/
  - GET /api/agent-runtime/context/ops/

  ## 6.2 新增 SDK 模块

  建议新增：

  - client.agent_runtime
  - client.agent_context
  - client.agent_ops

  公开方法建议：

  - create_task()
  - get_task()
  - list_tasks()
  - resume_task()
  - handoff_task()
  - create_proposal()
  - submit_proposal_for_approval()
  - approve_proposal()
  - execute_proposal()
  - get_context_snapshot(domain)

  ## 6.3 MCP 新增接口

  ### Tools

  任务型 tools 建议命名：

  - start_research_task
  - start_monitoring_task
  - start_decision_task
  - start_execution_task
  - start_ops_task
  - resume_agent_task
  - handoff_agent_task
  - approve_agent_proposal
  - reject_agent_proposal
  - execute_agent_proposal

  ### Resources

  - agomtradepro://context/{domain}/current
  - agomtradepro://task/{task_id}/timeline
  - agomtradepro://proposal/{proposal_id}/summary

  ### Prompts

  Prompt 只保留为 workflow guide，不直接承担治理逻辑。建议新增：

  - run_research_workflow
  - run_monitoring_workflow
  - run_decision_review_workflow
  - run_ops_triage_workflow

  ## 6.4 新增核心类型

  建议统一 dataclass / serializer / schema：

  - AgentTaskDTO
  - AgentTaskStepDTO
  - AgentContextSnapshotDTO
  - AgentProposalDTO
  - ApprovalDecisionDTO
  - ExecutionOutcomeDTO
  - AgentArtifactDTO
  - GuardrailResultDTO
  - TaskHandoffDTO
  - TaskTimelineEventDTO

  每个类型都必须有：

  - id
  - request_id
  - schema_version
  - created_at
  - updated_at

  ———

  ## 7. Workflow Specifications

  ## 7.1 Research Workflow

  输入：

  - portfolio_id
  - optional target asset universe
  - optional investment horizon

  步骤：

  1. 拉取 context snapshot
  2. 生成 current market state summary
  3. 列出 candidate signals/assets
  4. 产出 structured research artifact
  5. 如达到阈值，生成 decision proposal

  输出：

  - research artifact
  - recommendation list
  - optional proposal_id

  ## 7.2 Monitoring Workflow

  输入：

  - alert type / asset / portfolio / system domain

  步骤：

  1. 读取 monitoring context
  2. 拉取异常点相关证据
  3. 判断是数据问题、市场问题还是系统问题
  4. 生成 investigation summary
  5. 输出 action recommendation 或 escalation

  输出：

  - anomaly classification
  - evidence bundle
  - recommended next action

  ## 7.3 Decision Workflow

  输入：

  - candidate / research artifact / signal id

  步骤：

  1. 加载 context
  2. 检查 risk/policy/regime/precheck
  3. 生成 proposal
  4. 标记 approval requirement
  5. 路由至 human approval 或自动拒绝

  输出：

  - proposal artifact
  - approval status
  - rejection reason or next step

  ## 7.4 Execution Workflow

  输入：

  - approved proposal_id

  步骤：

  1. 执行 pre-execution guardrail
  2. 检查 market/data/system readiness
  3. 执行系统动作
  4. 记录 outcome
  5. 生成 post-execution summary

  输出：

  - execution record
  - result status
  - rollback suggestion if failed

  ## 7.5 Ops Workflow

  输入：

  - task failure / system issue / provider degradation

  步骤：

  1. 分类故障
  2. 抓取日志/指标/相关任务
  3. 输出 triage summary
  4. 判断 retry / escalate / suppress
  5. 写入 audit trail

  输出：

  - issue summary
  - severity
  - recommended operator action

  ———

  ## 8. Governance Rules

  ## 8.1 权限原则

  - 默认 deny
  - 所有写动作必须显式声明 risk level
  - 所有高风险操作必须 approval gate
  - AI 不可绕过后端 approval

  ## 8.2 审计原则

  每次任务必须记录：

  - actor_type: user / agent / system / approver
  - actor_id
  - task_id
  - proposal_id
  - request_id
  - tool_calls
  - resources_read
  - model_id
  - decision_reason
  - guardrail_result
  - execution_result

  ## 8.3 可恢复原则

  - 每个任务必须可判断是否可恢复
  - 不允许“失败后只能看日志猜”
  - 必须能定位失败在第几步、使用了哪批 context、哪个 guardrail 拦截

  ## 8.4 模型安全原则

  - 不允许模型文本输出直接驱动生产写动作
  - 所有写动作必须走结构化 payload
  - prompt 不承担权限控制
  - 所有高风险动作必须由后端判断，不由 MCP 层单独判断

  ———

  ## 9. Testing Strategy

  ## 9.1 单元测试

  新增测试域：

  - agent_runtime entities
  - task state machine
  - proposal lifecycle
  - guardrail decision matrix
  - handoff/resume logic
  - artifact serializers

  ## 9.2 SDK 测试

  新增：

  - sdk/tests/test_sdk/test_agent_runtime_module.py
  - sdk/tests/test_sdk/test_agent_context_module.py

  覆盖：

  - endpoint contract
  - payload normalization
  - error mapping
  - compatibility behavior

  ## 9.3 MCP 测试

  新增：

  - sdk/tests/test_mcp/test_agent_task_tools.py
  - sdk/tests/test_mcp/test_agent_context_resources.py
  - sdk/tests/test_mcp/test_agent_workflow_prompts.py

  覆盖：

  - tools registration
  - RBAC restrictions
  - structured failure results
  - resource readability
  - prompt availability

  ## 9.4 集成测试

  必须新增以下场景：

  ### Research

  - 能从 context 生成研究报告
  - 能从研究报告生成 proposal
  - 缺数据时返回 degraded mode，而不是异常

  ### Monitoring

  - 实时价格异常可完成调查
  - provider 不可用时能分类为 data-source failure
  - 系统故障时能触发 ops escalation

  ### Decision

  - policy/regime/risk 冲突时 proposal 被阻断
  - proposal 可进入 approval queue
  - approval 后可执行

  ### Execution

  - 执行前 guardrail 阻断
  - 执行成功写入 artifact
  - 执行失败可建议 rollback

  ### Ops

  - 任务失败可 resume
  - 任务失败可 handoff
  - task timeline 可完整回放

  ## 9.5 验收测试

  L4 验收最少应有：

  - 3 条任务型链路自动化通过
  - 100% proposal 有审计
  - 高风险动作无直写绕过
  - MCP/SDK/API 三层契约一致

  L5 验收最少应有：

  - 3 条自动运营任务持续运行
  - 人工审批链路稳定
  - 任务回放稳定
  - 生产治理开关有效

  ———

  ## 10. Rollout Plan

  ## 10.1 第一步：并行引入，不替换旧工具

  - 保留现有底层 MCP tools
  - 新增 task_* / proposal_* / context_* 新能力
  - 文档上把任务型工具标记为推荐入口

  ## 10.2 第二步：高风险写工具收口

  - 旧写工具仍兼容，但默认只返回 proposal 或提示改用 proposal flow
  - 后端强制执行 approval gate

  ## 10.3 第三步：引入 Agent Ops Dashboard


  - 只对白名单业务链开启 Agent auto-run
  - 先 staging，后 limited production，最后 full production

  ———

  ## 11. Implementation Order

  建议严格按以下顺序执行：

  1. 建 agent_runtime domain + models + state machine
  2. 建 proposal / artifact / timeline 数据模型
  3. 建 context snapshot façade
  4. 建 research/monitoring/decision/execution/ops facade
  5. 建后端 API
  6. 建 SDK modules
  7. 建 MCP task tools/resources/prompts
  8. 建 approval / execution guardrails
  9. 建 dashboard / ops UI
  10. 建集成测试与验收基线
  11. staging 灰度
  12. 生产白名单启用

  这个顺序不能反过来。原因：

  - 先做 MCP，不做 runtime，会继续把 workflow 逻辑散落在工具层
  - 先做自动化，不做 approval/guardrails，会把风险放大
  - 先做 UI，不做 task model，只会变成页面壳子

  ———

  ## 12. Assumptions And Defaults

  本方案默认以下前提成立：

  - 默认继续保持 API -> SDK -> MCP 的三层契约，不让 MCP 绕过 SDK 直接打裸 HTTP
  - 默认 canonical API 继续采用 /api/{module}/...
  - 默认高风险动作必须走后端 approval gate，不靠 prompt 或前端限制
  - 默认 L4 优先目标是“任务化 + 上下文包 + proposal 闭环”
  - 默认 L5 优先场景不是全自动交易，而是“受控运营任务 + 人工审批”
  - 默认保留现有底层 MCP tools 作为兼容层，不立即删除
  - 默认新增 Agent runtime 作为独立 app，而不是把状态机散落到现有各业务模块
  - 默认先以全域运营规划，但第一批落地建议仍以 投研 / 监控 / 决策 / 执行 / 运维 五域切分，而不是按现有 app 文件夹切分
