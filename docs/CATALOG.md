# 专题文档目录

> 导航整理：2026-10-14。本页按用途保留较完整的文档入口，不维护完成状态、部署身份或覆盖率基线。
> 首次阅读见 [总索引](INDEX.md)；工作安排见 [计划索引](plans/README.md)；历史状态见 [清理前快照](archive/documentation/docs-index-history-before-2026-10-14.md)。
> 动态治理规模以 [governance/governance_baseline.json](../governance/governance_baseline.json) 为准。

## 治理规范

| 文档 | 用途 |
| --- | --- |
| [data-center-regional-egress-plan-2026-09-09.md](plans/data-center-regional-egress-plan-2026-09-09.md) | **数据中台境内出口与 frp 开发计划（分流规则 / SDK 隔离 / TUI / 部署回滚）** |
| [SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) | **系统基线叙事索引（不复制动态治理数字）** |
| [MODULE_CLASSIFICATION.md](governance/MODULE_CLASSIFICATION.md) | **模块分级表（核心/成熟/试验）** |
| [DEVELOPMENT_BANLIST.md](governance/DEVELOPMENT_BANLIST.md) | **开发禁令（5条核心约束）** |
| [ARCHITECTURE_GUARDRAILS.md](governance/ARCHITECTURE_GUARDRAILS.md) | **架构与治理 CI 护栏说明** |

## 架构设计

| 文档 | 用途 |
| --- | --- |
| [MODULE_DEPENDENCIES.md](architecture/MODULE_DEPENDENCIES.md) | **模块依赖关系文档（拓扑图+改进建议）** |
| [MODULE_MAP.md](architecture/MODULE_MAP.md) | **模块架构地图说明书（governance/module_map.json 生成投影的字段口径与 Debug 用法）** |
| [DATA_DICTIONARY.md](architecture/DATA_DICTIONARY.md) | **ORM 数据字典（governance/data_dictionary.json 生成投影的人读渲染，禁止手改）** |
| [SYSTEM_TOPOLOGY.md](architecture/SYSTEM_TOPOLOGY.md) | **系统模块拓扑图与数据流（已同步 2026-04-26 架构治理结果）** |
| [architecture-remediation-result-2026-04-26.md](architecture/architecture-remediation-result-2026-04-26.md) | **架构整改结果（cycle=0 / audit=0 / MCP 契约未变）** |
| [adr-0001-shared-infrastructure-boundaries.md](architecture/adr-0001-shared-infrastructure-boundaries.md) | **ADR：shared.infrastructure 边界判定** |
| [adr-0006-tui-primary-interface.md](architecture/adr-0006-tui-primary-interface.md) | **ADR：TUI 作为日常任务主界面与 Web 保留清单边界** |
| [adr-0007-evidence-envelope-and-decision-gates.md](architecture/adr-0007-evidence-envelope-and-decision-gates.md) | **ADR：Evidence Envelope、Track Record 与决策硬闸所有权** |
| [adr-0008-terminal-agent-runtime-boundary.md](architecture/adr-0008-terminal-agent-runtime-boundary.md) | **ADR：Terminal Agent 多用户运行时边界与 queued composition contract** |
| [shared-cleanup-program-2026-05-02.md](architecture/shared-cleanup-program-2026-05-02.md) | **shared 残留清理专项** |
| [module-cycle-regression-remediation-2026-05-02.md](architecture/module-cycle-regression-remediation-2026-05-02.md) | **模块依赖回归整改说明（cycle 回归复盘与修复）** |
| [mcp-hosted-transport-and-identity-memo-2026-05-10.md](architecture/mcp-hosted-transport-and-identity-memo-2026-05-10.md) | **MCP 服务化演进备忘录（stdio vs HTTP/SSE、Token vs per-user OAuth）** |
| [share-application-remediation-2026-05-01.md](architecture/share-application-remediation-2026-05-01.md) | **Share 模块 Application 去 ORM 整改说明** |
| [account-portfolio-api-remediation-2026-05-01.md](architecture/account-portfolio-api-remediation-2026-05-01.md) | **Account Portfolio API 去 ORM 整改说明** |
| [application-write-guard-remediation-2026-05-01.md](architecture/application-write-guard-remediation-2026-05-01.md) | **Signal / Events Application 写边界整改说明** |
| [asset_analysis_framework.md](architecture/asset_analysis_framework.md) | 资产分析框架设计 |
| [project_structure.md](architecture/project_structure.md) | 项目结构说明 |
| [ai_module_boundaries.md](architecture/ai_module_boundaries.md) | AI 模块边界与依赖 |
| [ai-capability-architecture-review-2026-03-19.md](architecture/ai-capability-architecture-review-2026-03-19.md) | AI Capability Catalog 架构评估 |
| [simulated_trading_design.md](architecture/simulated_trading_design.md) | 模拟盘交易设计 |
| [strategy_system_design.md](architecture/strategy_system_design.md) | 策略系统设计 |
| [frp-vps-local-runtime-architecture.md](architecture/frp-vps-local-runtime-architecture.md) | 三机架构方案：VPS FRP 转发 + 服务端 AI/Agent 与 B/S 薄客户端；仅 QMT 外部券商桥允许本地执行 |
| [frontend_design_guide.md](architecture/frontend_design_guide.md) | 前端设计指南 |
| [ui_ux_design_tokens_v1.md](architecture/ui_ux_design_tokens_v1.md) | UI/UX 设计 Token 规范 v1.0 |
| [routing_naming_convention.md](architecture/routing_naming_convention.md) | 路由命名规范 |

## 业务逻辑

| 文档 | 用途 |
| --- | --- |
| [AgomTradePro_V3.4.md](business/AgomTradePro_V3.4.md) | 核心业务需求文档 |
| [human-judgment-decision-layering.md](business/human-judgment-decision-layering.md) | **人机协同决策分层：客观底盘、系统解释、个人约束、人工判断与复盘** |
| [strategy-research-capability-roadmap-memo-2026-08-04.md](business/strategy-research-capability-roadmap-memo-2026-08-04.md) | **策略研究长期能力备忘（经营驱动、资金结构、高频宏观因子、宏观风险平价、固收相对价值及启动门禁）** |
| [STRAT-01 R1–R8 业务定义包](business/strategy-research/strat-01/README.md) | **八项策略研究能力的 owner、scope、calendar、sample、qualification、证伪与生命周期定义** |
| [valuation-pricing-engine.md](business/valuation-pricing-engine.md) | **估值定价引擎业务文档** |
| [valuation-repair-config.md](business/valuation-repair-config.md) | **估值修复策略参数配置（在线调参/版本管理/回滚）** |
| [config-center-matrix.md](business/config-center-matrix.md) | **配置中心能力矩阵（前端/API/SDK/MCP/权限）** |
| [risk-center.md](business/risk-center.md) | **集中风控中心（全局底线/模板/账户策略/交易前置风控/API/SDK/MCP）** |
| [alpha-quickstart.md](business/alpha-quickstart.md) | Alpha 模块快速开始指南 |
| [equity-valuation-logic.md](business/equity-valuation-logic.md) | 个股估值逻辑 |
| [regime_calculation_logic.md](business/regime_calculation_logic.md) | Regime 计算逻辑 |
| [signal_and_position.md](business/signal_and_position.md) | 信号与持仓关系 |

## 开发指南

| 文档 | 用途 |
| --- | --- |
| [quick-reference.md](development/quick-reference.md) | 快速参考手册 |
| [s6-stage-environment-contract.md](development/s6-stage-environment-contract.md) | **S6 各阶段文件、编码、出口、身份、资源时间与外部状态统一准入契约** |
| [codex-autonomous-goal-usage.md](development/codex-autonomous-goal-usage.md) | **Codex 自主 Goal 启动、Sol/Luna 调度、worktree、计划回写与恢复备忘** |
| [runbook.md](operations/runbook.md) | **0.8.0 运维 Runbook（task_monitor / readiness / VPS 验收）** |
| [engineering-guardrails.md](development/engineering-guardrails.md) | **工程护栏与 PR Checklist（含 API 改动同步门禁）** |
| [GIT_WORKFLOW.md](GIT_WORKFLOW.md) | **Git 工作流规范（`dev/next-development`、commit、发布合并）** |
| [outsourcing-work-guidelines.md](development/outsourcing-work-guidelines.md) | **外包团队工作指南** |
| [api_structure_guide.md](development/api_structure_guide.md) | API 结构指南 |
| [coding_standards.md](development/coding_standards.md) | 代码规范 |
| [decision-platform.md](development/decision-platform.md) | 决策平台实现 |
| [debug-automation-log-api.md](development/debug-automation-log-api.md) | Codex/Claude 自动化调试日志 API |
| [manual-trade-sync-mvp-2026-05-31.md](development/manual-trade-sync-mvp-2026-05-31.md) | **手动交易同步与决策分支回测 MVP（CSV/Excel 导入、推荐匹配、反事实回放）** |
| [startup-scripts.md](development/startup-scripts.md) | 启动脚本使用指南 |
| [module-ledger.md](development/module-ledger.md) | 模块账本（边界规则/依赖统计） |
| [system-review-report.md](development/system-review-report.md) | 系统审视报告 |
| [regime-chain-unification-2026-03-02.md](development/regime-chain-unification-2026-03-02.md) | Regime 统一计算链路说明 |
| [api-route-consistency.md](development/api-route-consistency.md) | API 路由一致性分析 |
| [frontend-performance-analysis.md](development/frontend-performance-analysis.md) | 前端性能优化分析 |
| [frontend-development-standards.md](development/frontend-development-standards.md) | **前端开发规范（CSS/JS/模板/弹窗/HTMX）** |
| [tui-workbench.md](development/tui-workbench.md) | **经典 UI 平替 TUI Workbench 契约与迁移规则** |
| [tui-metadata-promotion-guide.md](development/tui-metadata-promotion-guide.md) | **TUI metadata 证据审核、批准与发布指南** |
| [error-handling-guide.md](development/error-handling-guide.md) | 错误处理改进指南 |
| [api-mcp-sdk-alignment-2026-03-14.md](development/api-mcp-sdk-alignment-2026-03-14.md) | **API / MCP / SDK 契约对齐说明** |
| [mcp-full-closure-evidence-2026-07-14.md](development/mcp-full-closure-evidence-2026-07-14.md) | **MCP 历史收口验收证据（Nightly / 浏览器 / 回滚）** |
| [mcp-technical-and-development-standard.md](mcp/mcp-technical-and-development-standard.md) | **MCP 技术与开发标准（统一注册 / 统一调用 / 收口治理）** |
| [mcp-agent-contract-and-playbook.md](mcp/mcp-agent-contract-and-playbook.md) | **MCP Agent 运行契约、Playbook、版本发布与回滚** |
| [dashboard-alpha-decision-chain-2026-04-12.md](development/dashboard-alpha-decision-chain-2026-04-12.md) | **Dashboard Alpha 决策链收束说明（含通用/专属拆分、解释面板、API/SDK/MCP）** |
| [alpha-workspace-consistency-guardrail-2026-06-05.md](development/alpha-workspace-consistency-guardrail-2026-06-05.md) | **Alpha 排名 / 决策工作台一致性运行时与 CI 护栏** |
| [alpha-ops-console-v1-2026-04-28.md](development/alpha-ops-console-v1-2026-04-28.md) | **Alpha / Qlib 运维台 V1（推理管理 + 基础数据管理）** |
| [nightly-test-stability-2026-04-28.md](development/nightly-test-stability-2026-04-28.md) | **Nightly 稳定性说明（Alpha stress 离线化与 CI 恢复）** |
| [data-reliability-remediation-checklist-2026-04-21.md](development/data-reliability-remediation-checklist-2026-04-21.md) | **数据可靠性修复清单（macro / quote / pulse / dashboard alpha）** |
| [vps-automated-research-gap-review-2026-07-07.md](development/vps-automated-research-gap-review-2026-07-07.md) | **VPS 自动化投研系统检视报告（UI / TUI / CLI / MCP / 数据治理 / 业务语义）** |
| [unified-financial-datasource-registry.md](development/unified-financial-datasource-registry.md) | **统一财经数据源中台与统一注册表说明** |
| [lint-debt-backlog.md](development/lint-debt-backlog.md) | **Ruff Lint 技术债待办清单（还债优先级）** |
| [decision-unified-workflow.md](development/decision-unified-workflow.md) | **统一工作流技术文档（数据模型/融合算法/状态流转/API）** |
| [decision-workflow-state-diagram.md](development/decision-workflow-state-diagram.md) | **决策工作流状态流转图** |

## 实施计划

活跃计划的归属和执行信息见 [计划索引](plans/README.md) 与 [机器注册表](../governance/active_plan_registry.json)。以下按主题查找；目标位于 `archive/` 的条目只作历史参考。

| 文档 | 用途 |
| --- | --- |
| [scripts、文档与 MCP 治理计划](plans/scripts-docs-mcp-governance-plan-2026-10-14.md) | 文档清理、脚本审计、可靠性修复与 legacy 退役方法 |
| [active_plan_registry.json](../governance/active_plan_registry.json) | **活跃计划与 canonical closure backlog 机器真源（工作流 / owner / 状态 / 依赖 / 唯一退出门 / 文件归属 / 限期审查）** |
| [production-recovery-and-regression-remediation-2026-09-24.md](plans/production-recovery-and-regression-remediation-2026-09-24.md) | **行情、正式发布、决策运行时、Alpha、API/SDK/MCP、只读工作台与生产预演的联合整改计划** |
| [index-dividend-thermometer-plan-2026-09-28.md](plans/index-dividend-thermometer-plan-2026-09-28.md) | **指数温度分析能力开发计划（中证红利 000922，R1 基础版 / R2 完整版）** |
| [release-blocker-closure-execution-plan-2026-08-29.md](plans/release-blocker-closure-execution-plan-2026-08-29.md) | **发布阻塞清零综合实施方案（DATA/AUD/EVID/STRAT/TUI/TAR/AI/QMT 顺序、授权包、回滚点和停止线）** |
| [scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md](plans/scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md) | **情景硬编码治理、动态/参数/宏观情景、AI MCP 受控修改及策略方法 Quick Wins（M0-M6）** |
| [strategy-research-capability-completion-audit-2026-08-05.md](plans/strategy-research-capability-completion-audit-2026-08-05.md) | **策略研究 R1—R8 完成度审计、真实数据阻断与无数据开发队列** |
| [sentiment-awareness-enhancement-plan-2026-07-31.md](archive/plans/sentiment-awareness-enhancement-plan-2026-07-31.md) | **A 股情绪态势感知增强计划（S0-S4，交易行为情绪指标 / Pulse sentiment 维度 / 文本情绪打通 / TUI 情绪面板）** |
| [web-to-tui-migration-plan-2026-07-25.md](plans/web-to-tui-migration-plan-2026-07-25.md) | **Web 界面 → TUI 整体迁移计划（M0-M5，模板去向矩阵 / 图表样板 / web 保留清单）** |
| [web-to-tui-m0-evidence-2026-07-26.md](archive/plans/web-to-tui-m0-evidence-2026-07-26.md) | **Web → TUI M0/M0-D 证据（冻结模板矩阵与死模板清理、冻结门与双端基线）** |
| [web-to-tui-m1-chart-evidence-2026-07-26.md](archive/plans/web-to-tui-m1-chart-evidence-2026-07-26.md) | **Web → TUI M1 图表样板证据（portable chart 契约、多序列/采样/可访问性、双端门禁）** |
| [web-to-tui-m2-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m2-consolidated-evidence-2026-07-26.md) | **Web → TUI M2 合并证据（W1-W20，15 份原始 wave 记录与 SHA-256 清单）** |
| [web-to-tui-m3-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m3-consolidated-evidence-2026-07-26.md) | **Web → TUI M3 合并证据（W21-W42，22 份原始 wave 记录与 SHA-256 清单）** |
| [web-to-tui-m4-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m4-consolidated-evidence-2026-07-26.md) | **Web → TUI M4 合并证据（W43-W51，9 份原始 wave 记录与 SHA-256 清单）** |
| [web-to-tui-m5-readiness-2026-07-27.md](plans/web-to-tui-m5-readiness-2026-07-27.md) | **Web → TUI M5 Readiness（14 日兼容期、UAT、telemetry 与回滚演练门禁）** |
| [web-to-tui-m5-production-preflight-2026-07-28.md](plans/web-to-tui-m5-production-preflight-2026-07-28.md) | **Web → TUI M5 生产 Preflight（只读健康、release/commit 与候选差异核查）** |
| [web-to-tui-m5-production-preflight-2026-08-13.md](plans/web-to-tui-m5-production-preflight-2026-08-13.md) | **Web → TUI M5 生产 Preflight（公开探针 + release/OCI 核对）** |
| [web-to-tui-m5-rollback-drill-evidence-2026-07-27.md](plans/web-to-tui-m5-rollback-drill-evidence-2026-07-27.md) | **Web → TUI M5 回滚演练（隔离 reverse/restore、旧 graph 兼容与 registry 回滚发布）** |
| [web-to-tui-m5-browser-uat-evidence-2026-07-27.md](plans/web-to-tui-m5-browser-uat-evidence-2026-07-27.md) | **Web → TUI M5 浏览器 UAT（角色边界、矩阵深链、直读/参数读取与生命周期）** |
| [web-to-tui-m5-route-closure-evidence-2026-07-27.md](plans/web-to-tui-m5-route-closure-evidence-2026-07-27.md) | **Web → TUI M5 逐 Route 清理证据（认证边界、兼容目标与状态/回滚范围）** |
| [tui-regime-display-contract-postmortem-2026-07-30.md](archive/plans/tui-regime-display-contract-postmortem-2026-07-30.md) | **TUI Regime 有数据未显示复盘（契约漂移、fail-closed 与跨层回归门禁）** |
| [qmt-live-trading-bridge-plan.md](plans/qmt-live-trading-bridge-plan.md) | **QMT 整体桥开发计划（交易执行 / 行情采集 / TUI / 权限 / 风控 / 对账）** |
| [qmt-integrated-bridge.md](operations/qmt-integrated-bridge.md) | QMT 整体桥用户与运维指南 |
| [tui-usability-and-metadata-governance-plan-2026-08-18.md](plans/tui-usability-and-metadata-governance-plan-2026-08-18.md) | **TUI 可用性与 metadata 治理整改（加载回退 / 三真源合一 / auto action 文案重写 / IA 整理 / 布局收口，TUX-01~05）** |
| [terminal-agent-multi-user-runtime-plan-2026-08-18.md](plans/terminal-agent-multi-user-runtime-plan-2026-08-18.md) | **Terminal Agent 多用户队列、专用 Worker、可恢复事件流与服务端 AI/Agent 薄客户端整改（TAR-01~05）** |
| [adr-0002-qmt-local-execution-bridge.md](architecture/adr-0002-qmt-local-execution-bridge.md) | QMT 本地 Agent + VPS 控制面架构决策 |
| [qmt-agent-runbook.md](operations/qmt-agent-runbook.md) | Windows QMT Agent 安装、分级启用、停止与故障处理 |
| [qmt-agent-local-install-package.md](operations/qmt-agent-local-install-package.md) | 国金普通 QMT `userdata` 本地 Agent ZIP 安装包、DPAPI Token、权限诊断与卸载 |
| [research-integrity-and-decision-reproducibility-2026-07-21.md](plans/research-integrity-and-decision-reproducibility-2026-07-21.md) | **研究可信度、组合构建与决策复算整改（M0-M6）** |
| [qmt-agent-v1.schema.json](api/qmt-agent-v1.schema.json) | QMT Agent v1 请求契约 JSON Schema 文档投影 |
| [tui-ia-consolidation-2026-07-20.md](archive/plans/tui-ia-consolidation-2026-07-20.md) | **TUI 信息架构重构计划（普通用户 13 屏 / 管理员 16 屏，8 步决策流，权限分层）** |
| [agomtui-portability-remediation-2026-07-21.md](plans/agomtui-portability-remediation-2026-07-21.md) | **AgomTUI 可移植性整改方案（Runtime 单向同步、schema 兼容、宿主接入与双端门禁）** |
| [uat-remediation-2026-07-20.md](plans/uat-remediation-2026-07-20.md) | **外部 UAT 复核、代码整改与生产数据恢复边界** |
| [implementation-progress-summary.md](plans/implementation-progress-summary.md) | **总体进度总结（Phase 1-5 完成）** |
| [AI-native-blueprint-260315.md](plans/AI-native-blueprint-260315.md) | **AI Native 升级蓝图** |
| [AI-Native-upgrade-implement-plan-260315.md](plans/AI-Native-upgrade-implement-plan-260315.md) | **AI Native 升级实施计划** |
| [ai-native/README.md](plans/ai-native/README.md) | **AI Native 子项目索引** |
| [ai-native/execution-backlog.md](plans/ai-native/execution-backlog.md) | **AI Native 执行积压** |
| [eastmoney-integration.md](archive/plans/eastmoney-integration.md) | **东方财富数据源集成计划** |
| [production-code-remediation-plan-2026-06-26.md](archive/plans/production-code-remediation-plan-2026-06-26.md) | **投产代码整改方案（数据守门 / 初始化 / UI 闭环）** |
| [0.8.0-release-closure-plan-2026-07-05.md](archive/plans/0.8.0-release-closure-plan-2026-07-05.md) | **0.8.0 收口开发计划（发布 / 运维 / 架构减债 Top 10）** |
| [post-0.8.0-stabilization-priority-2026-07-08.md](archive/plans/post-0.8.0-stabilization-priority-2026-07-08.md) | **0.8.0 发布后两周稳定化实施清单（优先级 / 负责人 / 命令 / 验收）** |
| [evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md](plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md) | **证据治理与决策硬闸改造计划** |
| [system-audit-log-consolidation-plan-2026-08-13.md](plans/system-audit-log-consolidation-plan-2026-08-13.md) | **系统级统一审计日志收口计划（统一事件账本 / 数据可靠性纵向链 / 指标告警 / TUI 观测）** |
| [mcp-consolidation-remediation-plan-2026-07-09.md](archive/plans/mcp-consolidation-remediation-plan-2026-07-09.md) | **MCP 收口整改计划（统一能力注册、统一调用、legacy 退役）** |
| [system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md](archive/plans/system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md) | **系统级 AI Capability Catalog 与统一路由任务书** |
| [terminal-mcp-governance-outsourcing-task-book-2026-03-19.md](archive/plans/terminal-mcp-governance-outsourcing-task-book-2026-03-19.md) | **Terminal MCP 治理与确认机制任务书** |
| [terminal-refactor-plan-260709.md](archive/plans/terminal-refactor-plan-260709.md) | **Terminal Agents SDK + MCP 重构计划** |
| [auto-advisor-prd-2026-06-25.md](archive/plans/auto-advisor-prd-2026-06-25.md) | **账户级自动投顾 PRD（持仓驱动 + 建议订单清单）** |
| [auto-advisor-implementation-2026-06-25.md](archive/plans/auto-advisor-implementation-2026-06-25.md) | **账户级自动投顾实施文档（后端/Classic UI/TUI/测试）** |
| [personal-auto-advisor-roadmap-2026-06-30.md](archive/plans/personal-auto-advisor-roadmap-2026-06-30.md) | **个人自用自动投顾增强路线图（风控 / 数据新鲜度 / 决策卡片 / 复盘）** |
| [macro-sizing-multiplier-outsourcing-2026-03-31.md](archive/plans/macro-sizing-multiplier-outsourcing-2026-03-31.md) | **宏观感知仓位系数模块外包任务书（Regime+Pulse+回撤三因子）** |
| [streamlit-dashboard-upgrade-plan.md](archive/plans/streamlit-dashboard-upgrade-plan.md) | Streamlit 仪表盘交互升级方案（兼容 sidecar 历史计划） |
| [account-performance-260401.md](archive/plans/account-performance-260401.md) | 统一账户业绩与估值历史实施计划 |
| [account-refactor-260327.md](archive/plans/account-refactor-260327.md) | 真实仓/模拟仓统一账本历史实施计划 |
| [admin-settings-closure-260404.md](archive/plans/admin-settings-closure-260404.md) | 设置中心与管理控制台 Classic 收口计划 |
| [alpha-exit-loop-2026-04-30.md](archive/plans/alpha-exit-loop-2026-04-30.md) | Alpha BUY→TRACK→SELL 退出闭环方案 |
| [alpha-homepage-upgrade-260416.md](archive/plans/alpha-homepage-upgrade-260416.md) | 账户驱动 Alpha 首页历史方案 |
| [workflow-upgrade-260326.md](archive/plans/workflow-upgrade-260326.md) | 决策工作台 Transition Plan 历史设计 |
| [architecture-cycle-remediation-2026-04-26.md](archive/plans/architecture-cycle-remediation-2026-04-26.md) | **循环依赖与架构债历史整改方案（CI + AGENTS + 模块归属）** |
| [architecture-cycle-remediation-2026-07-15.md](archive/plans/architecture-cycle-remediation-2026-07-15.md) | **循环依赖回流整改与零循环收口计划** |
| [repository-debt-remediation-closure-2026-07-19.md](archive/plans/repository-debt-remediation-closure-2026-07-19.md) | **仓库架构与治理债务总收口（大文件 / provider / 依赖 / 卫生 / 类型）** |
| [maintainability-refactoring-plan-2026-07-20.md](archive/plans/maintainability-refactoring-plan-2026-07-20.md) | **代码库可维护性定向重构计划（R0-R2）** |
| [testing-improvement-plan-2026-07-24.md](archive/plans/testing-improvement-plan-2026-07-24.md) | **分层测试与 TDD 反馈环提升计划（T0-T5）** |
| [test-coverage-weakness-remediation-progress-2026-07-24.md](plans/test-coverage-weakness-remediation-progress-2026-07-24.md) | **覆盖率薄弱环节整改实施记录（T0-T3A）** |
| [test-coverage-weakness-remediation-2026-07-24.md](plans/test-coverage-weakness-remediation-2026-07-24.md) | **测试覆盖薄弱环节整改计划（统计边界、分支覆盖、风险模块与生产集成）** |
| [maintainability-r2/r2-stage-record-2026-07-20.md](archive/plans/maintainability-r2/r2-stage-record-2026-07-20.md) | **R2 测试收敛阶段记录与回归证据** |
| [maintainability-r3-lite/r3-lite-stage-record-2026-07-20.md](archive/plans/maintainability-r3-lite/r3-lite-stage-record-2026-07-20.md) | **R3-lite 估值 owner 拆分与稳定性收口记录** |
| [maintainability-stability/stability-closeout-2026-07-20.md](archive/plans/maintainability-stability/stability-closeout-2026-07-20.md) | **R2 + R3-lite 集成契约稳定性收口记录** |
| [regime-navigator-pulse-redesign-260323.md](archive/plans/regime-navigator/regime-navigator-pulse-redesign-260323.md) | **系统重新设计：Regime Navigator + Pulse 分层架构** |
| [phase-1-regime-navigator-pulse-mvp.md](archive/plans/regime-navigator/phase-1-regime-navigator-pulse-mvp.md) | Phase 1: Regime Navigator + Pulse MVP + Dashboard 改造 |
| [phase-2-decision-funnel.md](archive/plans/regime-navigator/phase-2-decision-funnel.md) | Phase 2: 决策模式引导漏斗 |
| [phase-3-enrichment-polish.md](archive/plans/regime-navigator/phase-3-enrichment-polish.md) | Phase 3: 增强与打磨（Pulse V2 + 配置化 + 历史回溯） |
| [qlib-local-upload-user-isolation.md](archive/plans/qlib-local-upload-user-isolation.md) | Qlib 本地上传用户隔离方案 |
| [eastmoney-integration.md](archive/plans/eastmoney-integration.md) | **东方财富数据源集成计划（资金流向/新闻情感/实时行情/技术指标）** |

## 测试文档

| 文档 | 用途 |
| --- | --- |
| [master-test-strategy-2026-02.md](testing/master-test-strategy-2026-02.md) | **全面测试策略（L0-L7、关键可靠性、测试分层与覆盖率门禁）** |
| [critical-reliability-test-closure-2026-07-22.md](plans/critical-reliability-test-closure-2026-07-22.md) | **数据到对账关键可靠性测试与发布门禁收口记录** |
| [smart-test-selection.md](development/ci/smart-test-selection.md) | **增量测试映射、未知 App 全量回退与关键集合选择规则** |
| [coverage-governance.md](development/ci/coverage-governance.md) | **多范围行/分支覆盖率真源、报告与 ratchet 规则** |
| [celery-task-contract-guard.md](development/celery-task-contract-guard.md) | **Celery 技术状态、业务 outcome 与关键任务测试契约门禁** |
| [data-freshness-contract-guard.md](development/data-freshness-contract-guard.md) | **当前数据 observation/freshness/failover/决策阻断契约门禁** |
| [postmortem-realtime-stale-market-summary-2026-07-30.md](development/postmortem-realtime-stale-market-summary-2026-07-30.md) | **VPS Terminal 旧行情冒充当前值事故复盘与防复发矩阵** |
| [vps-uat-e2e-findings-2026-07-31.md](development/vps-uat-e2e-findings-2026-07-31.md) | **VPS UAT / E2E / MCP 生产问题清单（先冻结问题，再逐项修复与复测）** |
| [personal-investment-readiness-2026-06-30.md](testing/personal-investment-readiness-2026-06-30.md) | **个人投研系统可用性验收记录（readiness / Qlib / Alpha / 决策数据 / 连续运行证据）** |
| [0.8.0-release-regression-report-2026-07-05.md](testing/0.8.0-release-regression-report-2026-07-05.md) | **0.8.0 发布回归报告（版本 / TUI / 治理 / readiness）** |
| [post-0.8.0-stabilization-checkpoint-2026-07-08.md](testing/post-0.8.0-stabilization-checkpoint-2026-07-08.md) | **0.8.0 发布后稳定化检查点（live health / 回归 / readiness 阻塞项）** |
| [aud04-audit-archive-rehearsal-repository-closure-evidence-2026-08-31.json](testing/aud04-audit-archive-rehearsal-repository-closure-evidence-2026-08-31.json) | **AUD-04 候选绑定归档、append-only artifact 与内存隔离恢复 repository closure 证据** |
| [data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json](testing/data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json) | **DATA-04 PostgreSQL client saturation 只读事实、ASGI 连接生命周期与 SELECT-only preview repository closure 证据** |
| [data05-financial-repository-owner-closure-evidence-2026-08-31.json](testing/data05-financial-repository-owner-closure-evidence-2026-08-31.json) | **DATA-05 Financial availability owner 拆分、结构预算与兼容回归 closure 证据** |
| [data10-nightly-reliability-closure-evidence-2026-09-05.json](testing/data10-nightly-reliability-closure-evidence-2026-09-05.json) | **DATA-10 Nightly 全层回归、PostgreSQL、coverage ratchet、Architecture 与 Playwright closure 证据** |
| [outsourcing-full-regression-plan-2026-02-26.md](archive/process/testing/outsourcing-full-regression-plan-2026-02-26.md) | 外包全量回归执行方案（双环境+分层门禁+证据包）（归档） |
| [outsourcing-acceptance-plan-post-v34-2026-02-26.md](archive/process/testing/outsourcing-acceptance-plan-post-v34-2026-02-26.md) | 外包开发验收方案（V3.4 后续路线图）（归档） |
| [requirements-traceability-matrix-2026-02.md](testing/requirements-traceability-matrix-2026-02.md) | **需求-测试追踪矩阵（含关键可靠性、分层质量与真实 QMT 门禁）** |
| [sdk-mcp-integration-test-plan.md](testing/sdk-mcp-integration-test-plan.md) | SDK & MCP 集成测试计划 |
| [full-integration-test-report.md](testing/full-integration-test-report.md) | 完整集成测试报告 |
| [system_algorithm_evaluation_report.md](testing/system_algorithm_evaluation_report.md) | 系统算法评估 |
| [doc-link-check-report.md](testing/doc-link-check-report.md) | 文档链接校验报告 |
| [bug-report-template.md](testing/bug-report-template.md) | Bug 报告模板 |
| [test-results-template.md](testing/test-results-template.md) | 测试结果模板 |
| [api/API_REFERENCE.md](testing/api/API_REFERENCE.md) | API 参考文档 |
| [api/decision-rhythm-api.md](api/decision-rhythm-api.md) | **决策工作流 API 文档（估值+审批）** |
| [api/decision-workspace-v2.md](api/decision-workspace-v2.md) | **决策工作台 V2 API 草稿（统一推荐/参数）** |
| [decision-workspace-v2-acceptance.md](testing/decision-workspace-v2-acceptance.md) | **决策工作台 V2 验收测试清单（功能/数据/测试/性能/回归）** |

## 部署与运维

| 文档 | 用途 |
| --- | --- |
| [DOCKER_DEPLOYMENT.md](deployment/DOCKER_DEPLOYMENT.md) | Docker 部署指南 |
| [QLIB_TRAIN_RUNTIME_SETUP.md](deployment/QLIB_TRAIN_RUNTIME_SETUP.md) | Qlib 训练运行时搭建与接入指南 |
| [vps-a-frps-nginx-setup.md](deployment/vps-a-frps-nginx-setup.md) | **A 机部署：Linux VPS 上 FRPS + Nginx** |
| [b-local-frpc-docker-setup.md](deployment/b-local-frpc-docker-setup.md) | **B 机部署：Windows + WSL2 + Docker + FRPC** |
| [TEST_PACKAGE_RELEASE_WORKFLOW.md](deployment/TEST_PACKAGE_RELEASE_WORKFLOW.md) | 标准流程：测试->打包->发布->回滚（含门禁） |
| [data01-live-rehearsal-c826f741-baseline.json](deployment/data01-live-rehearsal-c826f741-baseline.json) | DATA-01 sibling restore 的 542 表、72 migration、463 sequence 与 schema/content hash 基线 |
| [data01-live-rehearsal-c826f741-migration-roundtrip.json](deployment/data01-live-rehearsal-c826f741-migration-roundtrip.json) | DATA-01 `0072→0071→0072` 原始迁移往返差异报告 |
| [data01-live-rehearsal-c826f741-migration-classification.json](deployment/data01-live-rehearsal-c826f741-migration-classification.json) | DATA-01 对 `django_migrations` 正常 ledger/sequence 增量的分类证明，业务/schema 一致 |
| [data01-live-rehearsal-c826f741-connection-switch.json](deployment/data01-live-rehearsal-c826f741-connection-switch.json) | DATA-01 真实 Web 连接切换/切回、RTO、关键计数/WAL 与健康检查证据 |
| [VPS_BUNDLE_DEPLOYMENT.md](deployment/VPS_BUNDLE_DEPLOYMENT.md) | VPS Bundle 一体化部署与迁移指南（含 Postgres/Redis 迁移） |
| [M5_OBSERVATION_BINDING_GUIDE.md](deployment/M5_OBSERVATION_BINDING_GUIDE.md) | M5 observation 候选绑定位置、命令、重置规则与验证方法 |
| [personal-project-single-owner-authorization-2026-08-30-80ea002b.json](deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json) | 唯一真人 owner 对 successor remediation、生产验收和同一人多治理角色的生效授权；不豁免技术门 |
| [tui02-production-day0-checkpoint-2026-08-30-80ea002b.json](deployment/tui02-production-day0-checkpoint-2026-08-30-80ea002b.json) | TUI-02 successor deployment、retained source、UAT、cleanup、rollback、registry backup 与 5/10 readiness 的 Day 0 汇总 |
| [tui02-production-observation-checkpoint-2026-09-02-aa7127ff.json](deployment/tui02-production-observation-checkpoint-2026-09-02-aa7127ff.json) | TUI-02 重启前候选/Prometheus 无漂移只读复核、首个 retained raw sample 与精确 14 日 eligible instant |
| [tui02-production-observation-reset-2026-09-02-aa7127ff.json](deployment/tui02-production-observation-reset-2026-09-02-aa7127ff.json) | TUI-02 受控 web-only restart 后的候选绑定、健康探针与 retained window reset 证据 |
| [tar01-public-health-readonly-recheck-2026-09-03.json](deployment/tar01-public-health-readonly-recheck-2026-09-03.json) | 当前公网 health/readiness 只读复核；decision-ready fail-closed，公开端点未暴露候选身份 |
| [vps-deployment-evidence-2026-08-15.md](deployment/vps-deployment-evidence-2026-08-15.md) | 候选部署、provenance、备份与运行复核证据（最新 Web→TUI successor `aa7127ff4…` / `20260901232812`） |
| [web-to-tui-deployment-preflight-20260816223921.json](deployment/web-to-tui-deployment-preflight-20260816223921.json) | `443658d33159` / `20260816223921` 候选 deployment preflight、OCI/source/health/ready 绑定 |
| [vps-runtime-verification-2026-08-16-2258.json](deployment/vps-runtime-verification-2026-08-16-2258.json) | `443658d33159` / `20260816223921` 候选只读 release/health/container/Qlib/Celery 复核 |
| [evid-01-authority-inventory-2026-08-16-2258.json](deployment/evid-01-authority-inventory-2026-08-16-2258.json) | `443658d33159` / `20260816223921` 候选只读 authority migration/zero-seed inventory；EVID-01 guard 动态核对当前 registry/preflight/runtime binding |
| [vps-postgres-backup-verification-2026-08-16-2348.json](deployment/vps-postgres-backup-verification-2026-08-16-2348.json) | `443658d33159` / `20260816223921` 候选 PostgreSQL custom-format 备份下载、尺寸与 SHA-256 复核（未恢复） |
| [evid-01-authority-inventory-2026-08-16.json](deployment/evid-01-authority-inventory-2026-08-16.json) | e167 候选只读 authority migration/zero-seed inventory |
| [evid-01-authority-inventory-snapshot-2026-08-23-0810.json](deployment/evid-01-authority-inventory-snapshot-2026-08-23-0810.json) | 候选 `4cef9040cccc...` 的 PostgreSQL authority 只读快照：0050–0053 已应用、12 张 authority/evidence/root-lock 表全零；经离线 normalizer 生成 content-addressed report `3900c08b9054...` |
| [vps-runtime-verification-2026-08-16-1811.json](deployment/vps-runtime-verification-2026-08-16-1811.json) | `5a13125bb84e` / `20260816181141` 候选只读 release/health/container/Qlib/Celery 复核 |
| [postgres_windows_docker.md](deployment/postgres_windows_docker.md) | Windows PostgreSQL Docker 配置 |
| [database_configuration.md](deployment/database_configuration.md) | 数据库配置 |

## AI 文档

| 文档 | 用途 |
| --- | --- |
| [ai_prompt_system.md](ai/ai_prompt_system.md) | AI 提示词系统使用文档 |
| [ai_provider_requirements.md](ai/ai_provider_requirements.md) | AI 服务商管理需求 |
| [prompt_templates_guide.md](ai/prompt_templates_guide.md) | Prompt 模板指南 |

## 用户指南

| 文档 | 用途 |
| --- | --- |
| [decision-platform-guide.md](user/decision-platform-guide.md) | 决策平台用户指南 |
| [topdown-bottomup-execution-playbook.md](user/topdown-bottomup-execution-playbook.md) | 环境-标的-执行-审计一体化操作手册 |

## 前端体验

| 文档 | 用途 |
| --- | --- |
| [ui-ux-full-page-audit-2026-02-18.md](archive/process/frontend/ui-ux-full-page-audit-2026-02-18.md) | 全站页面 UI/UX 盘点与功能清单（归档） |
| [ux-user-journey-checklist-2026-02-18.md](archive/process/frontend/ux-user-journey-checklist-2026-02-18.md) | 用户旅程式 UX 检查清单（归档） |

## 模块文档

| 文档 | 用途 |
| --- | --- |
| [alpha/alpha-guide.md](modules/alpha/alpha-guide.md) | Alpha 模块指南 |
| [alpha/qlib-model-import-guide.md](modules/alpha/qlib-model-import-guide.md) | Qlib 模型导入说明 |
| [policy/policy-workbench-guide.md](modules/policy/policy-workbench-guide.md) | Policy 工作台指南（双闸机制） |
| [decision/decision-workflow-guide.md](modules/decision/decision-workflow-guide.md) | **决策工作流使用指南（V3.4+）** |
| [audit/audit-module-guide.md](modules/audit/audit-module-guide.md) | Audit 模块指南 |
| [audit/attribution-methodology.md](modules/audit/attribution-methodology.md) | Brinson 归因方法论 |
| [factor/factor-guide.md](modules/factor/factor-guide.md) | Factor 模块指南 |
| [rotation/rotation-guide.md](modules/rotation/rotation-guide.md) | Rotation 模块指南 |
| [data-center-market-thermometer.md](modules/data-center-market-thermometer.md) | **Data Center 市场温度计（输入口径/API/Dashboard/Terminal）** |
| [hedge/hedge-guide.md](modules/hedge/hedge-guide.md) | Hedge 模块指南 |
| [terminal/terminal-guide.md](modules/terminal/terminal-guide.md) | Terminal 模块指南（终端 AI CLI） |
| [ai_capability/ai-capability-guide.md](modules/ai_capability/ai-capability-guide.md) | **AI Capability Catalog 模块指南** |
| [simulated_trading/daily-inspection.md](modules/simulated_trading/daily-inspection.md) | 模拟盘日更巡检 |
| [strategy/position-management.md](modules/strategy/position-management.md) | 策略仓位管理 |
| [strategy/strategy-auto-trading-mcp.md](modules/strategy/strategy-auto-trading-mcp.md) | 策略配置、MCP 与模拟盘自动交易链路 |

## 集成文档

| 文档 | 用途 |
| --- | --- |
| [akshare_realtime_guide.md](integration/akshare_realtime_guide.md) | AKShare 实时数据指南 |
| [how2usersshub.md](integration/how2usersshub.md) | RSSHub 使用指南 |
| [realtime_data_system.md](integration/realtime_data_system.md) | 实时数据系统 |
| [rss_policy_integration.md](integration/rss_policy_integration.md) | RSS 政策集成 |

## 迁移文档

| 文档 | 用途 |
| --- | --- |
| [route-migration-guide.md](migration/route-migration-guide.md) | **API 路由迁移指南（V3.5）** |
| [migration-quick-reference.md](migration/migration-quick-reference.md) | **迁移速查表** |

## 历史归档

| 文档 | 用途 |
| --- | --- |
| [ARCHIVE_INDEX.md](archive/ARCHIVE_INDEX.md) | **归档文档索引** |

## SDK 与 MCP

| 文档 | 用途 |
| --- | --- |
| [../sdk/README.md](../sdk/README.md) | SDK/MCP 总览、安装、认证、工具与模块清单 |
| [testing/sdk-mcp-integration-test-plan.md](testing/sdk-mcp-integration-test-plan.md) | SDK/MCP 集成测试方案 |
