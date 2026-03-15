  # AgomSAAF AI-Native 升级工作实施方案（外包执行版）

  ## Summary

  本方案把上一版 L4/L5 蓝图压缩为一份可直接交给外包团队执行的实施方案，目标是做到：

  - 可执行：每个里程碑都有明确产出、边界、依赖、验收标准
  - 可落地：优先复用现有 API / SDK / MCP / decision_rhythm / decision_workflow / audit / RBAC
  - 可测试验证：每个阶段都有明确测试清单、通过标准和交付件
  - 可管理：适合按周/双周排期、按模块分包、按验收节点付款

  默认执行策略：

  - 先做 L4，不直接做 L5
  - 采用 4 个里程碑 + 1 个验收封板阶段
  - 外包团队只负责实现本方案范围内内容，不自行扩展产品定义
  - 所有设计和接口以本方案为准，实施中不允许再由外包团队临时决定关键行为

  ———

  ## 1. 项目目标与边界

  ## 1.1 本期目标

  本期目标是把 AgomSAAF 从当前 L3+ 升级到稳定可验收的 L4，并为下一阶段 L5 留好接口和数据模型。

  本期必须完成：

  - Agent Runtime 基础设施
  - 任务型 MCP tools
  - 任务上下文资源包
  - proposal -> approval -> execute 三段式闭环
  - 任务状态、时间线、审计、恢复机制
  - 一套可回归的 SDK/MCP/API 自动化测试体系
  - 至少 3 条端到端业务链路可稳定演示和验收

  本期不做：

  - 多 Agent 自动协同调度
  - 全自动生产执行
  - 自主长期记忆推理系统
  - 模型策略实验平台
  - 通用 workflow 编排 DSL

  ## 1.2 交付对象

  交付对象为 3 类：

  1. 后端工程交付
  2. SDK/MCP 工程交付
  3. 测试与文档交付

  ## 1.3 适合外包团队的组织拆分

  建议拆成 3 个工作流并行：

  - Track A 后端 Runtime / API / State Machine
  - Track B SDK / MCP / Resource / Prompt
  - Track C Test / QA / 文档 / 验收脚本

  不建议按业务 app 分包，不建议让不同团队同时改同一条工作流的状态机。

  ———

  ## 2. 实施总排期

  建议总周期：8-10 周

  建议节奏：

  - Milestone 0 启动与冻结：3-5 天
  - Milestone 1 Runtime 基础设施：2 周
  - Milestone 2 Context + Task Tools：2 周
  - Milestone 3 Proposal/Approval/Execution 闭环：2 周
  - Milestone 4 测试、验收、灰度封板：2-3 周

  建议验收门：

  - Gate A 架构与 schema 冻结
  - Gate B Runtime API 冻结
  - Gate C MCP/SDK 契约冻结
  - Gate D E2E/UAT/回归通过后封板

  ———

  ## 3. 工作分解结构（WBS）

  ## 3.1 工作包总览

  ### WP-01 项目启动与基线冻结

  ### WP-02 Agent Runtime 数据模型与状态机

  ### WP-03 Agent Context Snapshot 能力

  ### WP-04 Task Facade 聚合层

  ### WP-05 Task 型 API

  ### WP-06 Proposal / Approval / Execute 闭环

  ### WP-07 SDK 扩展模块

  ### WP-08 MCP Task Tools / Resources / Prompts

  ### WP-09 Guardrails 与审计增强

  ### WP-10 Dashboard / Ops 可视化

  ### WP-11 自动化测试体系

  ### WP-12 验收演示与灰度交付

  ———

  ## 4. Milestone 0：启动与冻结

  ## 4.1 目标

  在编码前冻结实现边界、命名、接口、目录结构、验收方法，防止外包边做边改。

  ## 4.2 范围

  - 建立正式需求基线
  - 冻结实体命名、API 路由、状态机
  - 冻结目录结构和模块归属
  - 冻结测试目录和验收用例清单
  - 冻结编码规范和 PR 规范

  ## 4.3 必交付件

  1. AI-native 实施基线文档
  2. Agent Runtime 实体与状态机说明
  3. API/SDK/MCP 对齐清单
  4. 测试矩阵
  5. 验收脚本清单
  6. 外包开发规范

  ## 4.4 关键冻结项

  ### 目录结构冻结

  建议新增：

  - apps/agent_runtime/
  - sdk/agomsaaf/modules/agent_runtime.py
  - sdk/agomsaaf/modules/agent_context.py
  - sdk/agomsaaf_mcp/tools/agent_task_tools.py
  - sdk/agomsaaf_mcp/resources/ 如果不新增目录，则继续在 server.py 注册

  ### 状态机冻结

  AgentTask.status 固定为：

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

  ### 任务域冻结

  本期只支持 5 个 task domain：

  - research
  - monitoring
  - decision
  - execution
  - ops

  ### 高风险动作冻结

  以下动作必须走 proposal 闭环：

  - portfolio mutation
  - execution / simulated execution with side effects
  - signal write
  - strategy binding/unbinding
  - policy write
  - config write
  - replay/reset/system write

  ## 4.5 验收标准

  - 所有文档归档在固定位置
  - 项目负责人签字确认后才允许进入 M1
  - M1 期间不允许再改状态机和 API 命名

  ———

  ## 5. Milestone 1：Runtime 基础设施

  ## 5.1 目标

  先把 Agent Runtime 后端基础设施搭起来，这是整个项目的地基。

  ## 5.2 范围

  - 新建 agent_runtime app
  - 建任务实体、proposal 实体、artifact 实体、timeline 实体
  - 建状态机与 service
  - 建最小 API
  - 建 repository / serializer / DTO
  - 建最小单测

  ## 5.3 工作包

  ### WP-02 Agent Runtime 数据模型与状态机

  #### 必做实体

  - AgentTaskModel
  - AgentTaskStepModel
  - AgentContextSnapshotModel
  - AgentProposalModel
  - AgentExecutionRecordModel
  - AgentArtifactModel
  - AgentTimelineEventModel
  - AgentHandoffModel
  - AgentGuardrailDecisionModel

  #### 每个实体必须有的基础字段

  - id
  - request_id
  - schema_version
  - created_at
  - updated_at
  - created_by
  - task_domain
  - status

  #### Task 必备字段

  - task_type
  - input_payload
  - current_step
  - last_error
  - requires_human
  - linked_resource_uris
  - linked_artifact_ids

  #### Proposal 必备字段

  - proposal_type
  - proposal_payload
  - risk_level
  - approval_required
  - approval_status
  - approval_reason
  - executability_status

  #### Timeline 必备字段

  - event_type
  - event_source
  - event_payload
  - step_index

  ### WP-05 Task 型 API 第一批

  #### 必做接口

  - POST /api/agent-runtime/tasks/
  - GET /api/agent-runtime/tasks/
  - GET /api/agent-runtime/tasks/{id}/
  - GET /api/agent-runtime/tasks/{id}/timeline/
  - GET /api/agent-runtime/tasks/{id}/artifacts/
  - POST /api/agent-runtime/tasks/{id}/resume/
  - POST /api/agent-runtime/tasks/{id}/cancel/

  #### API 返回格式统一

  所有接口必须遵守：

  - 成功：结构化 JSON
  - 失败：结构化 JSON，不允许直接抛裸 traceback
  - 所有响应包含 request_id

  ### 服务层必须实现

  - CreateTaskUseCase
  - GetTaskUseCase
  - ListTasksUseCase
  - ResumeTaskUseCase
  - CancelTaskUseCase
  - TaskTimelineQueryService

  ## 5.4 非功能要求

  - 所有状态流转必须经 service，不允许 view 直接改状态
  - 所有状态变更必须写 timeline
  - 所有 API 受统一 RBAC 控制
  - 所有 serializer 有 schema version 字段

  ## 5.5 M1 测试要求

  ### 单测

  - 状态流转合法性
  - 非法流转阻断
  - task 创建校验
  - timeline 生成
  - cancel/resume 逻辑

  ### API 测试

  - create/get/list/resume/cancel 契约测试
  - 错误 payload 测试
  - 权限阻断测试

  ## 5.6 M1 验收标准

  - Runtime app 可独立工作
  - 所有 task 状态和 timeline 正常落库
  - API 文档齐全
  - 单测和 API 测试通过率 100%

  ———

  ## 6. Milestone 2：Context + Task Tools

  ## 6.1 目标

  让 Agent 能“有上下文地启动任务”，而不是裸调工具。

  ## 6.2 范围

  - 构建 5 类 context snapshot
  - 构建 facade 聚合层
  - 新增 SDK 模块
  - 新增第一批 task 型 MCP tools
  - 新增 resource

  ## 6.3 工作包

  ### WP-03 Agent Context Snapshot 能力

  #### 必做 context domains

  - research
  - monitoring
  - decision
  - execution
  - ops

  #### 每类 snapshot 固定字段

  - request_id
  - domain
  - generated_at
  - regime_summary
  - policy_summary
  - portfolio_summary
  - active_signals_summary
  - open_decisions_summary
  - risk_alerts_summary
  - task_health_summary
  - data_freshness_summary

  ### WP-04 Task Facade 聚合层

  #### 必做 facade

  - ResearchTaskFacade
  - MonitoringTaskFacade
  - DecisionTaskFacade
  - ExecutionTaskFacade
  - OpsTaskFacade

  #### facade 输入输出要求

  - 输入必须是 DTO，不是裸 dict
  - 输出必须是结构化 DTO
  - facade 内允许调用多个现有 app
  - facade 不直接操作 MCP，不直接依赖 prompt

  ### WP-07 SDK 扩展模块

  #### 新增 SDK 模块

  - client.agent_runtime
  - client.agent_context

  #### 必做 SDK 方法

  - create_task()
  - get_task()
  - list_tasks()
  - resume_task()
  - cancel_task()
  - get_task_timeline()
  - get_context_snapshot(domain)

  ### WP-08 MCP Task Tools / Resources 第一批

  #### 新增 MCP tools

  - start_research_task
  - start_monitoring_task
  - start_decision_task
  - start_execution_task
  - start_ops_task
  - resume_agent_task
  - cancel_agent_task

  #### 新增 MCP resources

  - agomsaaf://context/research/current
  - agomsaaf://context/monitoring/current
  - agomsaaf://context/decision/current
  - agomsaaf://context/execution/current
  - agomsaaf://context/ops/current

  #### prompts 本阶段只新增 workflow guide

  - run_research_workflow
  - run_monitoring_workflow
  - run_decision_workflow
  - run_execution_workflow
  - run_ops_workflow

  ## 6.4 M2 测试要求

  ### 单测

  - context aggregator 数据完整性
  - facade 聚合行为
  - DTO 映射正确性

  ### SDK 测试

  - endpoint 契约
  - payload normalize
  - error mapping

  ### MCP 测试

  - tools 注册
  - resources 可读
  - prompt 可列出
  - RBAC 下行为正确

  ### 集成测试

  - research context 能正常生成
  - monitoring context 能正常生成
  - 从 MCP 创建 task 后能查到 timeline

  ## 6.5 M2 验收标准

  - 5 类 context 都可生成
  - 7 个 task 型 tool 可调用
  - SDK/MCP/API 三层契约一致
  - 至少 2 条任务链可从 MCP 成功启动并可追踪

  ———

  ## 7. Milestone 3：Proposal / Approval / Execute 闭环

  ## 7.1 目标

  把高风险动作从“工具直接写”改为“结构化 proposal + 审批 + 执行”。

  ## 7.2 范围

  - proposal API
  - approval API
  - execute API
  - guardrail precheck
  - execution record
  - 风险动作迁移
  - 审计增强

  ## 7.3 工作包

  ### WP-06 Proposal / Approval / Execute 闭环

  #### 必做接口

  - POST /api/agent-runtime/proposals/
  - GET /api/agent-runtime/proposals/{id}/
  - POST /api/agent-runtime/proposals/{id}/submit-approval/
  - POST /api/agent-runtime/proposals/{id}/approve/
  - POST /api/agent-runtime/proposals/{id}/reject/
  - POST /api/agent-runtime/proposals/{id}/execute/

  #### proposal 生命周期

  - draft
  - generated
  - submitted
  - approved
  - rejected
  - executed
  - execution_failed
  - expired

  ### WP-09 Guardrails 与审计增强

  #### guardrails 必做规则

  - role-based access
  - risk-level gate
  - approval-required gate
  - market-readiness gate
  - data-freshness gate
  - dependency-health gate

  #### 审计必须记录

  - task_id
  - proposal_id
  - actor_type
  - actor_id
  - request_id
  - tool_calls
  - resources_read
  - guardrail_result
  - approval_decision
  - execution_result

  ### 高风险能力迁移清单

  以下现有 MCP/SDK 写能力必须加 proposal 模式：

  - signal create/update/invalidate
  - portfolio rebalance / bind strategy / unbind strategy
  - simulated trading execute / reset
  - policy event create
  - config write
  - replay/reset 类系统操作

  要求：

  - 旧工具保留兼容入口
  - 但默认返回“应改走 proposal flow”或结构化 proposal 指引
  - 不允许继续无审批直写生产高风险动作

  ## 7.4 M3 测试要求

  ### 单测

  - proposal lifecycle
  - approval state transition
  - execute guardrail
  - execution failure path
  - audit trail completeness

  ### SDK/MCP 测试

  - create proposal
  - approve proposal
  - reject proposal
  - execute approved proposal
  - blocked proposal 行为

  ### E2E 测试

  必须完成 3 条主链路：

  #### E2E-01 投研 -> proposal -> approval -> execution

  #### E2E-02 实时异常调查 -> 风险建议 -> proposal

  #### E2E-03 ops triage -> handoff -> human approval

  ## 7.5 M3 验收标准

  - 至少 5 类高风险动作已迁移到 proposal 模式
  - 所有 proposal 都有 timeline 和 audit
  - 未审批 proposal 不可执行
  - 至少 3 条端到端链路通过

  ———

  ## 8. Milestone 4：可视化、恢复能力、测试封板

  ## 8.1 目标

  把系统做成“可演示、可运营、可回归”的交付状态。

  ## 8.2 范围

  - task/proposal dashboard
  - handoff / resume
  - 失败恢复
  - 回归测试
  - 验收脚本
  - 部署与灰度方案

  ## 8.3 工作包

  ### WP-10 Dashboard / Ops 可视化

  建议新增页面或管理台模块，至少包含：

  - Task list
  - Task detail
  - Timeline viewer
  - Proposal inbox
  - Approval panel
  - Execution outcome panel
  - Handoff queue
  - Guardrail decision viewer

  ### WP-11 自动化测试体系

  #### 必做测试目录

  - tests/unit/agent_runtime/
  - tests/integration/agent_runtime/
  - sdk/tests/test_sdk/test_agent_runtime_module.py
  - sdk/tests/test_sdk/test_agent_context_module.py
  - sdk/tests/test_mcp/test_agent_task_tools.py
  - sdk/tests/test_mcp/test_agent_context_resources.py

  #### 必做 CI 门禁

  - Runtime unit
  - Runtime integration
  - SDK contract
  - MCP contract
  - 3 条 E2E 主链路
  - RBAC / audit regression

  ### 恢复能力

  至少实现：

  - resume_task
  - handoff_task
  - mark_needs_human
  - 失败任务分类
  - 重试建议输出

  ### 灰度交付

  - staging 环境先启用
  - task 工具先对白名单角色开放
  - proposal execute 默认只允许测试角色
  - 生产先只开 research/monitoring，不开 execution auto-run

  ## 8.4 M4 测试要求

  ### 验收场景

  - 任务创建后完整可追踪
  - proposal 可以审批和拒绝
  - 执行失败后可恢复或 handoff
  - dashboard 可定位单个任务全链路
  - RBAC 生效
  - 审计日志可追溯到 request_id

  ### 性能要求

  - MCP task tool p95 < 500ms，不含长任务执行
  - context resource p95 < 300ms
  - task detail query p95 < 300ms
  - proposal execute precheck p95 < 500ms

  ## 8.5 M4 验收标准

  - 所有测试通过
  - UAT 脚本通过
  - staging 演示可复现
  - 形成正式交付文档和运维手册

  ———

  ## 9. 交付清单（外包必须提交）

  ## 9.1 代码交付

  - 完整源码 PR
  - migration 文件
  - serializer / DTO / facade / API / SDK / MCP 实现
  - 测试代码
  - 必要的 dashboard 页面

  ## 9.2 文档交付

  - 架构说明
  - 数据模型说明
  - 状态机说明
  - API 文档
  - SDK 文档
  - MCP 工具文档
  - 部署与灰度文档
  - 验收报告模板

  ## 9.3 测试交付

  - 单测报告
  - 集成测试报告
  - MCP/SDK 契约测试报告
  - E2E 录屏或日志
  - UAT 结果

  ———

  ## 10. 角色分工建议

  ## 10.1 外包团队角色

  - Backend Lead
  - Backend Engineer
  - SDK/MCP Engineer
  - QA Engineer
  - PM/交付协调

  ## 10.2 甲方角色

  - 产品/架构 owner
  - 验收 owner
  - 环境 owner
  - 上线审批 owner

  ## 10.3 决策权限边界

  外包团队无权自行决定：

  - 状态机变化
  - proposal 审批规则变化
  - 高风险动作是否可直写
  - canonical API 路径变化
  - MCP 工具命名大改
  - 跨 milestone 范围蔓延

  这些必须由甲方确认。

  ———

  ## 11. 付款/验收节点建议

  建议按里程碑付款：

  ### 节点 1：M0 完成

  支付条件：

  - 基线文档冻结
  - 接口和状态机冻结
  - 评审通过

  ### 节点 2：M1 完成

  支付条件：

  - agent_runtime 可用
  - API 单测通过
  - task/timeline 落库演示通过

  ### 节点 3：M2 完成

  支付条件：

  - context + facade + SDK/MCP 第一批能力完成
  - 可演示启动 task 和读取 context

  ### 节点 4：M3 完成

  支付条件：

  - proposal/approval/execute 闭环完成
  - 3 条主链路 E2E 通过

  ### 节点 5：M4 完成

  支付条件：

  - 测试封板
  - staging 验收通过
  - 文档齐套

  ———

  ## 12. 风险与控制措施

  ## 12.1 典型风险

  - 外包团队把 workflow 逻辑写进 MCP，而不是后端 runtime
  - 外包团队继续做“API 映射工具”，没有任务抽象
  - proposal 流只做接口，不做后端阻断
  - dashboard 先行，后端状态模型没打稳
  - 测试只测 happy path，不测权限和恢复

  ## 12.2 控制措施

  - 每个 milestone 必须做架构评审
  - 每周检查一次 schema 变更
  - MCP PR 必须附对应 SDK/API 变更
  - 高风险动作必须有阻断测试
  - E2E 验收要覆盖失败路径和 handoff

  ———


  - 已实现 agent_runtime 基础设施
  - 已实现 5 个 context domain
  - 已实现任务型 SDK 和 MCP 接口
  - 已实现 proposal -> approval -> execute 三段式闭环
  - 已实现 timeline / artifact / audit 全链路追踪
  - 已实现 resume / handoff 最小可用能力
  - 已通过 SDK/MCP/API 契约测试
  - 已通过至少 3 条端到端业务链路
  - 已有 staging 可演示版本
  - 已交付完整文档和测试报告

  ———

  ## 14. 建议的外包实施顺序

  外包团队必须按以下顺序实施，不允许跳步：

  1. 冻结基线
  2. 建 agent_runtime 数据模型和状态机
  3. 建 runtime API
  4. 建 context snapshot 和 facade
  5. 建 SDK 模块
  6. 建 MCP task tools/resources
  7. 建 proposal/approval/execute
  8. 建 guardrails 和 audit 增强
  9. 建 dashboard
  10. 建 E2E 和验收
  11. staging 灰度

  ———

  ## Assumptions And Defaults

  - 默认本期只交付 L4，不交付完整 L5
  - 默认不做生产自动执行，只做受控 proposal/approval/execute
  - 默认所有任务状态和 proposal 状态均持久化到数据库
  - 默认 SDK 与 MCP 继续建立在 canonical API 上
  - 默认现有低层 MCP tools 保留兼容，不立即删除
  - 默认验收环境为本地 + staging 双环境
  - 默认外包团队不得自行引入新的 workflow 引擎或第三方 Agent 编排平台，除非甲方书面确认
  - 默认高风险动作的最终裁决权始终在后端，不在 prompt 或 MCP 客户端
  - 默认外包团队需提交全部自动化测试与验收脚本，不接受“人工点点能用”作为交付标准