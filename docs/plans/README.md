# 活跃计划索引

> 导航整理：2026-10-16。机器唯一真源：[governance/active_plan_registry.json](../../governance/active_plan_registry.json)。
> 本页提供工作流与文档入口。状态、owner、依赖、排期、审查期限和退出门直接读取机器字段，不维护第二套快照。

## 当前工作流

| ID | 范围 | 文档入口 |
| --- | --- | --- |
| `evidence-hard-gate` | Evidence 与决策硬闸 | [主计划与支撑文档](#evidence-hard-gate) |
| `strategy-research-production` | 策略研究生产验收 | [主计划与支撑文档](#strategy-research-production) |
| `data-production-reliability` | 数据生产可靠性 | [主计划与支撑文档](#data-production-reliability) |
| `system-audit-consolidation` | 系统审计 | [主计划与支撑文档](#system-audit-consolidation) |
| `web-to-tui-m5` | Web → TUI M5；`891c40c57…` / `20260915110952`，`TUI-02=active`，`2/10 DENY`（冻结 cutover 投影） | [主计划与支撑文档](#web-to-tui-m5) |
| `terminal-agent-multi-user-runtime` | Terminal Agent 运行时 | [主计划与支撑文档](#terminal-agent-multi-user-runtime) |
| `ai-native-release` | AI Native 验收 | [主计划与支撑文档](#ai-native-release) |
| `qmt-live-bridge` | QMT 外部实盘桥 | [主计划与支撑文档](#qmt-live-bridge) |
| `tui-usability-governance` | TUI 可用性 | [主计划与支撑文档](#tui-usability-governance) |
| `index-dividend-thermometer` | 指数温度分析 | [主计划与支撑文档](#index-dividend-thermometer) |
| `repository-maintenance-governance` | Scripts / 文档 / MCP 存量治理 | [主计划与支撑文档](#repository-maintenance-governance) |
| `manager-holdings-plan-review` | Manager Holdings 草案审查 | [主计划与支撑文档](#manager-holdings-plan-review) |

状态、owner 与 next gate 读取 `workstreams`；可执行状态读取 `closure_backlog.units`。工作流 active 不等于允许启动其中的 planned 实施。

## 主计划与支撑文档

### evidence-hard-gate

| 角色 | 文档 |
| --- | --- |
| 主计划 | [AgomTradePro 证据治理与决策硬闸改造计划](evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md) |
| 支撑 | [DATA / Evidence / Audit / Runtime 阶段路线](data-evidence-audit-runtime-sprint-route-2026-09-14.md) |
| 支撑 | [Authority V3 Facade 写路径性能整改方案（EVID-09，2026-09-13）](evid08-facade-write-performance-remediation-2026-09-13.md) |
| 支撑 | [研究可信度与决策可复算体系整改计划](research-integrity-and-decision-reproducibility-2026-07-21.md) |
| 证据 | [研究可信度与决策复算 M0 责任及迁移盘点](research-integrity-m0-inventory-2026-07-22.md) |

### strategy-research-production

| 角色 | 文档 |
| --- | --- |
| 主计划 | [R3/R4 宏观因子与宏观风险平价启动门禁及分阶段实施计划](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md) |
| 主计划 | [策略研究能力 R1—R8 完成度审计（2026-08-05）](strategy-research-capability-completion-audit-2026-08-05.md) |
| 主计划 | [策略研究能力路线图 R1—R8 执行状态（2026-08-05）](strategy-research-capability-roadmap-execution-2026-08-05.md) |
| 主计划 | [策略研究真实数据与生产收口跟踪备忘录](strategy-research-production-data-closure-tracking-memo-2026-08-12.md) |
| 主计划 | [R1/R2 策略研究能力启动门整改计划（2026-08-05）](strategy-research-r1-r2-readiness-plan-2026-08-05.md) |
| 主计划 | [策略研究 R5—R8 启动门禁与分阶段实施计划（2026-08-05）](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md) |
| 证据 | [AgomTradePro + Qlib 松耦合深度集成 - 实施进度总结](implementation-progress-summary.md) |
| 支撑 | [R6 简单基准不足证据与高级状态模型分阶段计划（2026-08-05）](r6-simple-baseline-shortfall-and-state-model-staged-delivery-2026-08-05.md) |
| 支撑 | [情景治理与策略研究 Quick Wins 整改计划（2026-08-04）](scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md) |

### data-production-reliability

| 角色 | 文档 |
| --- | --- |
| 主计划 | [关键可靠性测试补齐计划](critical-reliability-test-closure-2026-07-22.md) |
| 主计划 | [数据中台唯一真源与数据可靠性架构重构计划（2026-08-02）](data-center-canonical-architecture-refactor-2026-08-02.md) |
| 主计划 | [生产数据可靠性完整修复与测试计划（2026-08-01）](production-data-reliability-full-remediation-2026-08-01.md) |
| 主计划 | [UAT 整改记录（2026-07-20）](uat-remediation-2026-07-20.md) |
| 支撑 | [数据中台境内出口与 frp 接入规划](data-center-regional-egress-plan-2026-09-09.md) |
| 支撑 | [数据可靠性修复计划](data-chain-repair-plan-260421.md) |
| 证据 | [DATA-02 财报 source-time date-only 精度决策记录（2026-10-04 Owner 决策）](data02-date-only-precision-decision-2026-10-04.md) |
| 支撑 | [DATA-02 财务真实来源时间整改方案（2026-09-13 拟议）](data02-financial-source-time-remediation-2026-09-13.md) |
| 支撑 | [DATA-02 配置供应商原始响应接入](data02-provider-artifact-adoption-2026-09-14.md) |
| 支撑 | [DATA-02 可恢复批次证据整改计划（2026-09-21）](data02-resumable-recovery-remediation-2026-09-21.md) |
| 支撑 | [DataHubCo RDS 数据中台绑定](datahubco-rds-binding-2026-09-09.md) |
| 支撑 | [治理契约存量覆盖缺口备忘录（2026-08-10）](governance-legacy-coverage-gaps-memo-2026-08-10.md) |
| 支撑 | [模型行情经数据中台取数（本地改造，2026-09-09）](model-market-data-center-routing-2026-09-09.md) |
| 支撑 | [生产恢复与系统性防回归整改计划（2026-09-24）](production-recovery-and-regression-remediation-2026-09-24.md) |
| 支撑 | [财务发现与发布能力隔离整改（2026-10-16）](financial-scope-resilience-2026-10-16.md) |
| 支撑 | [发布阻塞清零综合实施方案（2026-08-29）](release-blocker-closure-execution-plan-2026-08-29.md) |
| 支撑 | [测试覆盖薄弱环节整改计划](test-coverage-weakness-remediation-2026-07-24.md) |
| 证据 | [测试覆盖薄弱环节整改实施记录](test-coverage-weakness-remediation-progress-2026-07-24.md) |

### system-audit-consolidation

| 角色 | 文档 |
| --- | --- |
| 主计划 | [AgomTradePro 系统级统一审计日志收口计划](system-audit-log-consolidation-plan-2026-08-13.md) |

### web-to-tui-m5

| 角色 | 文档 |
| --- | --- |
| 主计划 | [Web → TUI M5 Readiness 判定（2026-07-27）](web-to-tui-m5-readiness-2026-07-27.md) |
| 主计划 | [Web 界面 → TUI 整体迁移计划（M0-M5）](web-to-tui-migration-plan-2026-07-25.md) |
| 支撑 | [AgomTUI 可移植性整改方案：TUI IA 跨仓库交付与宿主边界](agomtui-portability-remediation-2026-07-21.md) |
| 支撑 | [VPS Web Liveness Stabilization — 2026-08-18](vps-web-liveness-stabilization-2026-08-18.md) |
| 证据 | [Web → TUI M5 浏览器 UAT 证据（2026-07-27）](web-to-tui-m5-browser-uat-evidence-2026-07-27.md) |
| 证据 | [Web → TUI M5 生产 Preflight（2026-07-28）](web-to-tui-m5-production-preflight-2026-07-28.md) |
| 证据 | [Web → TUI M5 生产 Preflight（2026-08-13）](web-to-tui-m5-production-preflight-2026-08-13.md) |
| 证据 | [Web → TUI M5 回滚演练证据（2026-07-27）](web-to-tui-m5-rollback-drill-evidence-2026-07-27.md) |
| 证据 | [Web → TUI M5 逐 Route 清理证据（2026-07-27）](web-to-tui-m5-route-closure-evidence-2026-07-27.md) |
| 矩阵 | [web-to-tui-migration-matrix-2026-07-25.csv](web-to-tui-migration-matrix-2026-07-25.csv) |


### terminal-agent-multi-user-runtime

| 角色 | 文档 |
| --- | --- |
| 主计划 | [Terminal Agent 多用户队列、Worker 隔离与服务端 CLI 运行整改计划](terminal-agent-multi-user-runtime-plan-2026-08-18.md) |

### ai-native-release

| 角色 | 文档 |
| --- | --- |
| 主计划 | [AgomTradePro AI-Native Milestone Delivery Pack](ai-native/README.md) |
| 支撑 | [AI-Native-upgrade-implement-plan-260315](AI-Native-upgrade-implement-plan-260315.md) |
| 支撑 | [AI-native-blueprint-260315](AI-native-blueprint-260315.md) |
| 支撑 | [AgomTradePro AI 中台 Agent Runtime 重构实施方案](ai-agent-runtime-refactor-plan-260319.md) |
| 支撑 | [AgomTradePro AI-Native Execution Backlog](ai-native/execution-backlog.md) |
| 支撑 | [首页 AI 聊天复用 Terminal 渲染与路由能力外包实施任务书（2026-03-20）](homepage-chat-terminal-reuse-outsourcing-task-book-2026-03-20.md) |

### qmt-live-bridge

| 角色 | 文档 |
| --- | --- |
| 主计划 | [QMT 整体桥开发计划（交易执行与行情采集）](qmt-live-trading-bridge-plan.md) |

### tui-usability-governance

| 角色 | 文档 |
| --- | --- |
| 主计划 | [TUI 可用性与 Metadata 治理整改计划](tui-usability-and-metadata-governance-plan-2026-08-18.md) |
| 支撑 | [TUI 速度、分页与连续操作整改方案](tui-speed-pagination-remediation-2026-09-08.md) |

### index-dividend-thermometer

| 角色 | 文档 |
| --- | --- |
| 主计划 | [指数温度分析能力开发计划（2026-09-28）](index-dividend-thermometer-plan-2026-09-28.md) |

### repository-maintenance-governance

| 角色 | 文档 |
| --- | --- |
| 主计划 | [Scripts、文档与 MCP 存量治理计划](scripts-docs-mcp-governance-plan-2026-10-14.md) |

### manager-holdings-plan-review

| 角色 | 文档 |
| --- | --- |
| 主计划 | [Manager Holdings / Decision Twin Development Plan](manager-holdings-decision-twin-development-plan-2026-09-30.md) |

## 限期审查队列

队列与期限读取 `review_queue`。已过期的 Manager Holdings 草案已转入上列明确工作流和 `MHD-01` 待审查单元；原期限和未批准实施的边界保留在草案与登记说明中。

## 维护规则

- 机器唯一真源是 [`governance/active_plan_registry.json`](../../governance/active_plan_registry.json)；本页是面向人的执行投影，不单独维护另一套状态。
- 注册表中的 `closure_backlog` 是 review queue 与已登记工作流的 canonical 分阶段收口单元；本页只解释其执行顺序，不复制机器状态。
- `docs/plans/`：只允许登记在机器注册表中的主计划、支撑文档、证据或限期审查项。新增未登记文件、重复归属、陈旧路径和无截止日审查项由 CI 直接拒绝。
- `docs/archive/plans/`：仓库范围已实现，或阶段已经验收/被新计划取代；归档文档仅作历史证据，不代表当前运行状态。
- “代码已完成但生产未验收”仍属于活跃计划，不能仅因本地测试通过而归档。
- `active` 表示仍有仓库实施；`production_validation` 表示主缺口已转为真实数据/迁移/观察；`external_validation` 与 `blocked_external` 不得伪装为开发完成。
- `review_required` 不是长期状态，只允许出现在限期审查队列；到期必须合并、归档或转入明确工作流。
- 唯一可执行待办是注册表内的 `closure_backlog.units`。主计划里的历史 `- [ ]` 仅作需求与验收来源，不再直接计数、排期或领取；新增细项必须归入既有 closure unit，或先通过注册表评审新增唯一 unit。
- 注册表中的 `execution_focus` 是唯一 repository 执行锁；只有该 unit 可以处于 `active`。其他工作流只能按允许的 execution mode 收集只读生产或外部证据，不得并行扩展仓库代码边界。
- 同一 closure unit 的测试、文档、生产证据和回滚要求是一个验收包，不能拆成多份 plan 重复计算；依赖未完成的 unit 不得抢跑。
- `production` / `awaiting_production` 描述证据来源和当前阶段，**不是代理停止状态**。在当前任务允许推进该 unit 时，代理必须先完成全部安全的只读采集、候选绑定、报告派生和 collector 缺口实现；只有剩余动作会改变生产状态、产生真实交易/外部费用，或必须由人/外部机构作出决定时，才请求授权或等待。
- 归档时必须同步修正注册表、`docs/INDEX.md` 和活跃计划中的引用，不复制第二份文档。
- 提交前运行 `python scripts/check_active_plan_registry.py`。

## 当前执行焦点

读取机器注册表的 `execution_focus.unit_id`、`allowed_parallel_execution_modes` 与 `policy`，再查对应 `closure_backlog.units` 的依赖和退出门。该字段才是 repository 执行锁；不得沿用历史日志中的“唯一焦点”或从工作流的 active 状态推定执行权。

## 去重后的收口 Backlog

`closure_backlog.units` 是唯一可执行待办。每个 unit 的 `status`、`execution_mode`、`depends_on`、`wave` 与 `exit_gate` 共同决定是否可领取；`closure_backlog.waves` 定义阶段顺序。历史未勾选项目保留为需求来源，不再按文档重复计数。

本轮 scripts、文档与 MCP 治理的工作内容、容量预算、验证与回滚方法见 [详细计划](scripts-docs-mcp-governance-plan-2026-10-14.md)。`GOV-03`～`GOV-07` 的状态只在机器 backlog 登记；本次文档清理不会触发后续脚本重构或 MCP 退役。

## 自主 Goal 调度入口

先读取 `execution_focus` 和目标 unit，确认当前任务授权，再按 [自主 Goal 使用备忘](../development/codex-autonomous-goal-usage.md) 与主计划推进。历史记录中曾读回 active 的应用 Goal、候选部署或旧观察日期不能作为本次调度证据。

## 滚动执行排期

排期由注册表的 `closure_backlog.waves`、依赖和 repository focus 决定。主计划提供实施方法，证据报告证明已完成范围；索引不重复维护候选 SHA、生产数量、测试结果或相对时间承诺。

## 历史记录

本页原有的执行日志、治理数量表、旧工作流状态、backlog 投影及 material checkpoints 已保存到 [清理前历史快照](../archive/documentation/plans-index-history-before-2026-10-14.md)。既有 [生产恢复执行日志](../archive/plans/production-recovery-execution-log-2026-09-24.md) 和正式证据继续保留原路径。

M5 行保留候选一致性测试所需的最小投影，绑定 [canonical cutover](../../config/tui/migration/web_to_tui_cutover_evidence.v1.json)。当前生产版本、观测有效性和 release gate 必须由当前候选的正式证据另行证明。

## 生产证据自动采集纪律

生产证据要求“来自真实生产源且可复核”，不要求人工抄录。机器真源中所有 `production` / `external` closure unit 都必须登记 `evidence_collection`，并分成三类：

- `auto_collect`：默认主动执行。包括只读 API/数据库/指标/CI 查询、候选身份与 manifest 对账、下载已有备份、哈希校验、观察天数计算、缺陷/telemetry 快照派生、隔离恢复或回滚演练、浏览器确定性断言。原始响应、来源时间、候选身份和 hash 必须保留；collector 不接受调用方自报 `passed`。
- `authorization_required`：代理先完成 preflight、dry-run、影响范围和回滚点，只对具体的生产写入、部署/切换、故障注入、备份创建/清理、付费调用或真实交易请求授权。授权动作完成后，后续只读取证继续自动执行。
- `human_or_external_required`：真实审批、业务 UAT 判断、owner/reviewer 双签、券商权限和策略参数由相应主体完成；代理自动准备证据包、校验身份与完整性，但不得代签、补造或把“未回应”当通过。

若某个退出门可机械验证但尚无 collector，缺口归入当前 closure unit 的 repository 工作：先实现幂等、fail-closed、候选绑定的采集器及测试，不能把“缺少采集器”误报成外部阻塞。只读监控任务仍遵守其自身的禁止写入范围，只报告采集结果。

| Units | 默认自动采集 | 只在这里等待授权/人工 |
|---|---|---|
| `EVID-02` | PostgreSQL 并发 harness、current-head/rollback 查询与报告 hash | 生产审批记录写入；真实审批人决定 |
| `AUD-03` | migration 状态、outbox backlog/age、metrics/alert、恢复与 archive 完整性 | 生产 migration/rollback/fault/archive/restore；生产签字 |
| `DATA-01/02/03` | 已有备份下载与 SHA、隔离 restore/RTO、覆盖/freshness/reconciliation、双 readiness、观察计时 | 新建/清理备份、回填/删改、维护态、切换和 live rollback；数据 owner 例外 |
| `STRAT-01/02/03` | owner/policy 缺口盘点、PIT/OOS 时长、receipt/lineage/reconciliation、权限与 consumer 测试 | 生产登记/Promotion/回填；策略 owner 参数与业务 UAT |
| `TUI-01/02` | commit/version/OCI/matrix/graph/runtime 对账、health/ready、角色只读旅程、108 UAT 派生、14 日计时、缺陷、101 telemetry、隔离 rollback | 候选部署、生产写回执、registry backup 创建、cleanup/live rollback；双签 |
| `TAR-06` / `TAR-05` / `AI-01` | 默认无网络校验、已批准 staging 的 load/soak/browser、metrics、event timeline、候选绑定与报告 | 任何生产 load/chaos/canary/cutover、付费模型调用；容量与业务验收 |
| `QMT-01/02` | 获权后的 Phase 0 只读探针、仿真 timeline、callback/reconciliation 报告 | 券商权限、任何真实订单/撤单/live enable；券商与业务 owner 签字 |

当前已有的直接 collector 包括：`check_web_to_tui_cutover_readiness.py --json`、`record_web_to_tui_candidate_evidence.py`、`reset_web_to_tui_observation.py`、`build_web_to_tui_defect_evidence.py`、`build_web_to_tui_production_telemetry.py`、`drill_web_to_tui_rollback.py`、`backup-vps-postgres.py --download-latest`、`verify_postgres_backup_restore.py`、`record_data01_restore_evidence.py`、`record_data02_reconciliation_evidence.py`、`record_data02_successor_checkpoint.py`、`record_data03_readiness_evidence.py`、`record_aud03_operational_observation_evidence.py` 和 `run_terminal_runtime_staging_baseline.py`（默认 validation-only）。执行具体命令时仍以 `--help`、专项计划和当前任务授权范围为准。
