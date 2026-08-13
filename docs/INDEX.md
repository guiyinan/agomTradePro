# AgomTradePro 文档索引

> **AgomTradePro 0.8.0** - 个人投研平台
> **最后更新**: 2026-08-13
> **项目状态**: 生产就绪
> **版本管理**: [VERSION.md](VERSION.md)

---

## 快速导航

| 角色 | 入口文档 | 说明 |
|------|----------|------|
| **系统概览** | [SYSTEM_SPECIFICATION.md](SYSTEM_SPECIFICATION.md) | **完整系统说明书（技术+功能）** |
| **系统基线** | [governance/SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) | **治理叙事索引；动态数字读取机器基线** |
| **0.8.0 发布说明** | [RELEASE_0.8.0.md](RELEASE_0.8.0.md) | **版本边界、发布摘要、正式生产口径** |
| **新用户** | [QUICK_START.md](QUICK_START.md) | **个人实战上手手册（冷启动版）** |
| **Git 工作流** | [GIT_WORKFLOW.md](GIT_WORKFLOW.md) | **分支命名、commit 规范、main/dev 工作流** |
| 开发人员 | [development/quick-reference.md](development/quick-reference.md) | 命令速查、API端点、模块速查、API 改动同步检查 |
| 新加入者 | [governance/SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) | 系统基线、模块清单、核心链路 |
| AI Agent/集成开发 | [../sdk/README.md](../sdk/README.md) | SDK 与 MCP 服务接入、认证、工具清单 |
| 外包团队 | [development/outsourcing-work-guidelines.md](development/outsourcing-work-guidelines.md) | **外包工作指南、代码规范、自查清单** |
| 产品/业务 | [business/AgomTradePro_V3.4.md](business/AgomTradePro_V3.4.md) | 业务逻辑、金融规则、数据源 |
| 最终用户 | [user/topdown-bottomup-execution-playbook.md](user/topdown-bottomup-execution-playbook.md) | 环境-标的-执行-审计一体化操作手册 |
| 运维人员 | [deployment/VPS_BUNDLE_DEPLOYMENT.md](deployment/VPS_BUNDLE_DEPLOYMENT.md) | VPS Bundle 部署指南 |
| FRP 三机部署 | [architecture/frp-vps-local-runtime-architecture.md](architecture/frp-vps-local-runtime-architecture.md) | VPS 入口 + 本地运行 + C 端 AI Agent/MCP 架构与落地配置 |

---

## 当前收口说明

- 可维护性定向重构的 R0、R1、R2 与 R3-lite 已完成并归档：历史计划与契约矩阵见 [archive/plans/maintainability-refactoring-plan-2026-07-20.md](archive/plans/maintainability-refactoring-plan-2026-07-20.md) 和 [archive/plans/maintainability-r0/r1-stage-record-2026-07-20.md](archive/plans/maintainability-r0/r1-stage-record-2026-07-20.md)。
- 宏观运行时入口已统一收口到 `data_center`：HTTP 走 `/api/data-center/*`，MCP 走 `data_center_*` 工具族。
- 全局运行时配置 owner 已切到 `config_center`：`SystemSettingsModel` 归属 `apps/config_center`，Qlib runtime / 在线训练中心入口见 [business/config-center-matrix.md](business/config-center-matrix.md)。
- 指标目录与量纲规则真源见 [development/macro-data-center-cutover.md](development/macro-data-center-cutover.md)。
- 宏观调度频率、发布时间 lag、period override 已开始下沉到 `IndicatorCatalog.extra`，SDK/MCP/页面解释需优先读取 runtime metadata。
- 宏观治理台已落地到 `/data-center/governance/`；这是人工审计入口，不改变 SDK/MCP canonical 契约。
- 集中风控中心已落地到 `/risk-center/`：配置 owner 为 `risk_center`，账户止盈止损、模拟盘自动买入和策略执行编排已开始读取有效策略；API/SDK/MCP 入口见 [business/risk-center.md](business/risk-center.md)。
- `/tui/` 已定位为独立 DOS/PCTools 风格经典 UI 平替壳：运行时只读取已发布 TUI metadata，不实时扫描源码、模板、SDK、MCP 或 URL resolver；普通操作界面不展示 API endpoint 或裸 JSON。
- 默认用户入口已切到 `/tui/`：根路径 `/`、登录成功后的默认跳转和 Setup Wizard 完成页都先进入 TUI；经典 Dashboard 继续保留在 `/dashboard/` 作为显式入口。
- `0.8.0` 已正式切版：公开版本、系统基线、README、AGENTS、运行手册与回归报告现已统一；正式生产数据库口径明确为 PostgreSQL，本地首跑仍保留 SQLite 轻量路径。

## 文档目录

### 0. 治理文档 (`governance/`) - 新增

| 文档 | 说明 | 状态 |
|------|------|------|
| [SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) | **系统基线叙事索引（不复制动态治理数字）** | ✅ 2026-03-18 新增 |
| [MODULE_CLASSIFICATION.md](governance/MODULE_CLASSIFICATION.md) | **模块分级表（核心/成熟/试验）** | ✅ 2026-03-18 新增 |
| [DEVELOPMENT_BANLIST.md](governance/DEVELOPMENT_BANLIST.md) | **开发禁令（5条核心约束）** | ✅ 2026-03-18 新增 |
| [ARCHITECTURE_GUARDRAILS.md](governance/ARCHITECTURE_GUARDRAILS.md) | **架构与治理 CI 护栏说明** | ✅ 2026-04-24 新增 |

### 1. 架构设计 (`architecture/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [MODULE_DEPENDENCIES.md](architecture/MODULE_DEPENDENCIES.md) | **模块依赖关系文档（拓扑图+改进建议）** | ✅ 2026-03-18 新增 |
| [SYSTEM_TOPOLOGY.md](architecture/SYSTEM_TOPOLOGY.md) | **系统模块拓扑图与数据流（已同步 2026-04-26 架构治理结果）** | ✅ 2026-04-26 更新 |
| [architecture-remediation-result-2026-04-26.md](architecture/architecture-remediation-result-2026-04-26.md) | **架构整改结果（cycle=0 / audit=0 / MCP 契约未变）** | ✅ 2026-04-26 新增 |
| [adr-0001-shared-infrastructure-boundaries.md](architecture/adr-0001-shared-infrastructure-boundaries.md) | **ADR：shared.infrastructure 边界判定** | ✅ 2026-05-02 新增 |
| [adr-0006-tui-primary-interface.md](architecture/adr-0006-tui-primary-interface.md) | **ADR：TUI 作为日常任务主界面与 Web 保留清单边界** | ✅ 2026-07-26 已接受 |
| [adr-0007-evidence-envelope-and-decision-gates.md](architecture/adr-0007-evidence-envelope-and-decision-gates.md) | **ADR：Evidence Envelope、Track Record 与决策硬闸所有权** | 2026-08-12 分阶段实施 |
| [shared-cleanup-program-2026-05-02.md](architecture/shared-cleanup-program-2026-05-02.md) | **shared 残留清理专项** | ✅ 2026-05-02 新增 |
| [module-cycle-regression-remediation-2026-05-02.md](architecture/module-cycle-regression-remediation-2026-05-02.md) | **模块依赖回归整改说明（cycle 回归复盘与修复）** | ✅ 2026-05-02 新增 |
| [mcp-hosted-transport-and-identity-memo-2026-05-10.md](architecture/mcp-hosted-transport-and-identity-memo-2026-05-10.md) | **MCP 服务化演进备忘录（stdio vs HTTP/SSE、Token vs per-user OAuth）** | ✅ 2026-05-10 新增 |
| [share-application-remediation-2026-05-01.md](architecture/share-application-remediation-2026-05-01.md) | **Share 模块 Application 去 ORM 整改说明** | ✅ 2026-05-01 新增 |
| [account-portfolio-api-remediation-2026-05-01.md](architecture/account-portfolio-api-remediation-2026-05-01.md) | **Account Portfolio API 去 ORM 整改说明** | ✅ 2026-05-01 新增 |
| [application-write-guard-remediation-2026-05-01.md](architecture/application-write-guard-remediation-2026-05-01.md) | **Signal / Events Application 写边界整改说明** | ✅ 2026-05-01 新增 |
| [asset_analysis_framework.md](architecture/asset_analysis_framework.md) | 资产分析框架设计 | 完整 |
| [project_structure.md](architecture/project_structure.md) | 项目结构说明 | 完整 |
| [ai_module_boundaries.md](architecture/ai_module_boundaries.md) | AI 模块边界与依赖 | ✅ 2026-03-18 新增 |
| [ai-capability-architecture-review-2026-03-19.md](architecture/ai-capability-architecture-review-2026-03-19.md) | AI Capability Catalog 架构评估 | ✅ 2026-03-19 新增 |
| [simulated_trading_design.md](architecture/simulated_trading_design.md) | 模拟盘交易设计 | 完整 |
| [strategy_system_design.md](architecture/strategy_system_design.md) | 策略系统设计 | 完整 |
| [frp-vps-local-runtime-architecture.md](architecture/frp-vps-local-runtime-architecture.md) | 三机架构方案：VPS FRP 转发 + 本地 Docker + C 端 AI Agent/MCP | ✅ 2026-03-08 新增 |
| [frontend_design_guide.md](architecture/frontend_design_guide.md) | 前端设计指南 | ✅ 2026-02-20 更新 |
| [ui_ux_design_tokens_v1.md](architecture/ui_ux_design_tokens_v1.md) | UI/UX 设计 Token 规范 v1.0 | ✅ 完成验收 |
| [routing_naming_convention.md](architecture/routing_naming_convention.md) | 路由命名规范 | ✅ 完成验收 |

### 2. 业务逻辑 (`business/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [AgomTradePro_V3.4.md](business/AgomTradePro_V3.4.md) | 核心业务需求文档（2650行） | 最新 |
| [human-judgment-decision-layering.md](business/human-judgment-decision-layering.md) | **人机协同决策分层：客观底盘、系统解释、个人约束、人工判断与复盘** | ✅ 2026-04-24 新增 |
| [strategy-research-capability-roadmap-memo-2026-08-04.md](business/strategy-research-capability-roadmap-memo-2026-08-04.md) | **策略研究长期能力备忘（经营驱动、资金结构、高频宏观因子、宏观风险平价、固收相对价值及启动门禁）** | 备忘，按前置条件启动 |
| [valuation-pricing-engine.md](business/valuation-pricing-engine.md) | **估值定价引擎业务文档** | ✅ 2026-07-20 R3-lite owner 更新 |
| [valuation-repair-config.md](business/valuation-repair-config.md) | **估值修复策略参数配置（在线调参/版本管理/回滚）** | ✅ 2026-03-11 新增 |
| [config-center-matrix.md](business/config-center-matrix.md) | **配置中心能力矩阵（前端/API/SDK/MCP/权限）** | ✅ 2026-03-11 新增 |
| [risk-center.md](business/risk-center.md) | **集中风控中心（全局底线/模板/账户策略/交易前置风控/API/SDK/MCP）** | ✅ 2026-06-27 新增 |
| [alpha-quickstart.md](business/alpha-quickstart.md) | Alpha 模块快速开始指南 | 完整 |
| [equity-valuation-logic.md](business/equity-valuation-logic.md) | 个股估值逻辑 | 完整 |
| [regime_calculation_logic.md](business/regime_calculation_logic.md) | Regime 计算逻辑 | 完整 |
| [signal_and_position.md](business/signal_and_position.md) | 信号与持仓关系 | 完整 |

### 3. 开发指南 (`development/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [quick-reference.md](development/quick-reference.md) | 快速参考手册 | ✅ 2026-03-31 更新 |
| [runbook.md](operations/runbook.md) | **0.8.0 运维 Runbook（task_monitor / readiness / VPS 验收）** | ✅ 2026-07-05 更新 |
| [engineering-guardrails.md](development/engineering-guardrails.md) | **工程护栏与 PR Checklist（含 API 改动同步门禁）** | ✅ 2026-03-31 更新 |
| [../GIT_WORKFLOW.md](GIT_WORKFLOW.md) | **Git 工作流规范（`dev/*` 分支、commit、合并流程）** | ✅ 2026-03-23 新增 |
| [outsourcing-work-guidelines.md](development/outsourcing-work-guidelines.md) | **外包团队工作指南** | ✅ 必读 |
| [api_structure_guide.md](development/api_structure_guide.md) | API 结构指南 | 完整 |
| [coding_standards.md](development/coding_standards.md) | 代码规范 | 完整 |
| [decision-platform.md](development/decision-platform.md) | 决策平台实现 | 完整 |
| [debug-automation-log-api.md](development/debug-automation-log-api.md) | Codex/Claude 自动化调试日志 API | 完整 |
| [manual-trade-sync-mvp-2026-05-31.md](development/manual-trade-sync-mvp-2026-05-31.md) | **手动交易同步与决策分支回测 MVP（CSV/Excel 导入、推荐匹配、反事实回放）** | ✅ 2026-05-31 新增 |
| [startup-scripts.md](development/startup-scripts.md) | 启动脚本使用指南 | 完整 |
| [module-ledger.md](development/module-ledger.md) | 模块账本（边界规则/依赖统计） | ✅ 2026-03-18 更新 |
| [system-review-report.md](development/system-review-report.md) | 系统审视报告 | ✅ 2026-03-18 更新 |
| [regime-chain-unification-2026-03-02.md](development/regime-chain-unification-2026-03-02.md) | Regime 统一计算链路说明 | ✅ 2026-03-02 |
| [api-route-consistency.md](development/api-route-consistency.md) | API 路由一致性分析 | ✅ 2026-02-20 |
| [frontend-performance-analysis.md](development/frontend-performance-analysis.md) | 前端性能优化分析 | ✅ 2026-02-20 |
| [frontend-development-standards.md](development/frontend-development-standards.md) | **前端开发规范（CSS/JS/模板/弹窗/HTMX）** | ✅ 2026-03-10 新增 |
| [tui-workbench.md](development/tui-workbench.md) | **经典 UI 平替 TUI Workbench 契约与迁移规则** | ✅ 2026-06-20 更新 |
| [tui-metadata-promotion-guide.md](development/tui-metadata-promotion-guide.md) | **TUI metadata 证据审核、批准与发布指南** | ✅ 2026-06-20 新增 |
| [error-handling-guide.md](development/error-handling-guide.md) | 错误处理改进指南 | ✅ 2026-02-20 |
| [api-mcp-sdk-alignment-2026-03-14.md](development/api-mcp-sdk-alignment-2026-03-14.md) | **API / MCP / SDK 契约对齐说明** | ✅ 2026-03-14 新增 |
| [mcp-full-closure-evidence-2026-07-14.md](development/mcp-full-closure-evidence-2026-07-14.md) | **MCP 全量收口验收证据（13 条标准 / Nightly / 浏览器 / 回滚）** | ✅ 2026-07-14 新增 |
| [mcp-technical-and-development-standard.md](mcp/mcp-technical-and-development-standard.md) | **MCP 技术与开发标准（统一注册 / 统一调用 / 收口治理）** | ✅ 2026-07-09 新增 |
| [mcp-agent-contract-and-playbook.md](mcp/mcp-agent-contract-and-playbook.md) | **MCP Agent 运行契约、Playbook、版本发布与回滚** | ✅ 2026-07-17 新增 |
| [dashboard-alpha-decision-chain-2026-04-12.md](development/dashboard-alpha-decision-chain-2026-04-12.md) | **Dashboard Alpha 决策链收束说明（含通用/专属拆分、解释面板、API/SDK/MCP）** | ✅ 2026-04-22 更新 |
| [alpha-workspace-consistency-guardrail-2026-06-05.md](development/alpha-workspace-consistency-guardrail-2026-06-05.md) | **Alpha 排名 / 决策工作台一致性运行时与 CI 护栏** | ✅ 2026-06-05 新增 |
| [alpha-ops-console-v1-2026-04-28.md](development/alpha-ops-console-v1-2026-04-28.md) | **Alpha / Qlib 运维台 V1（推理管理 + 基础数据管理）** | ✅ 2026-04-28 新增 |
| [nightly-test-stability-2026-04-28.md](development/nightly-test-stability-2026-04-28.md) | **Nightly 稳定性说明（Alpha stress 离线化与 CI 恢复）** | ✅ 2026-04-28 新增 |
| [data-reliability-remediation-checklist-2026-04-21.md](development/data-reliability-remediation-checklist-2026-04-21.md) | **数据可靠性修复清单（macro / quote / pulse / dashboard alpha）** | ✅ 2026-04-21 更新：新增 repair 流水线 |
| [vps-automated-research-gap-review-2026-07-07.md](development/vps-automated-research-gap-review-2026-07-07.md) | **VPS 自动化投研系统检视报告（UI / TUI / CLI / MCP / 数据治理 / 业务语义）** | ✅ 2026-07-07 新增 |
| [unified-financial-datasource-registry.md](development/unified-financial-datasource-registry.md) | **统一财经数据源中台与统一注册表说明** | ✅ 2026-03-28 新增 |
| [lint-debt-backlog.md](development/lint-debt-backlog.md) | **Ruff Lint 技术债待办清单（303 条，含还债优先级）** | ✅ 2026-05-12 新增 |

### 4. 实施计划 (`plans/`)

> **说明**: 大部分计划已完成并归档到 `archive/plans/`，以下为进行中的重要计划

| 文档 | 说明 | 状态 |
|------|------|------|
| [scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md](plans/scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md) | **情景硬编码治理、动态/参数/宏观情景、AI MCP 受控修改及策略方法 Quick Wins（M0-M6）** | 提案，待评审实施 |
| [strategy-research-capability-completion-audit-2026-08-05.md](plans/strategy-research-capability-completion-audit-2026-08-05.md) | **策略研究 R1—R8 完成度审计、真实数据阻断与无数据开发队列** | 实施中；无 P0，剩余 P1 分批收口 |
| [sentiment-awareness-enhancement-plan-2026-07-31.md](archive/plans/sentiment-awareness-enhancement-plan-2026-07-31.md) | **A 股情绪态势感知增强计划（S0-S4，交易行为情绪指标 / Pulse sentiment 维度 / 文本情绪打通 / TUI 情绪面板）** | ✅ 已完成并归档 |
| [web-to-tui-migration-plan-2026-07-25.md](plans/web-to-tui-migration-plan-2026-07-25.md) | **Web 界面 → TUI 整体迁移计划（M0-M5，195 模板去向矩阵 / 图表样板 / web 保留清单）** | 实施中；M0-M4 完成；M5 候选证据与最终库存门禁已加固，真实观察未开始且 final inventory DENY |
| [web-to-tui-m0-evidence-2026-07-26.md](archive/plans/web-to-tui-m0-evidence-2026-07-26.md) | **Web → TUI M0/M0-D 证据（195 模板矩阵、7 个死模板清理、冻结门与双端基线）** | ✅ M0/M0-D 已完成并归档 |
| [web-to-tui-m1-chart-evidence-2026-07-26.md](archive/plans/web-to-tui-m1-chart-evidence-2026-07-26.md) | **Web → TUI M1 图表样板证据（portable chart 契约、多序列/采样/可访问性、双端门禁）** | ✅ M1 已完成并归档 |
| [web-to-tui-m2-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m2-consolidated-evidence-2026-07-26.md) | **Web → TUI M2 合并证据（W1-W20，15 份原始 wave 记录与 SHA-256 清单）** | ✅ M2 已完成并归档 |
| [web-to-tui-m3-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m3-consolidated-evidence-2026-07-26.md) | **Web → TUI M3 合并证据（W21-W42，22 份原始 wave 记录与 SHA-256 清单）** | ✅ M3 已完成并归档 |
| [web-to-tui-m4-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m4-consolidated-evidence-2026-07-26.md) | **Web → TUI M4 合并证据（W43-W51，9 份原始 wave 记录与 SHA-256 清单）** | ✅ M4 已完成并归档 |
| [web-to-tui-m5-readiness-2026-07-27.md](plans/web-to-tui-m5-readiness-2026-07-27.md) | **Web → TUI M5 Readiness（14 日兼容期、UAT、telemetry 与回滚演练门禁）** | ⛔ 当前 DENY；candidate/deployment/M5-B wave recorders 与 guards 已加固；真实候选部署、观察窗口和逐波生产证据待补 |
| [web-to-tui-m5-production-preflight-2026-07-28.md](plans/web-to-tui-m5-production-preflight-2026-07-28.md) | **Web → TUI M5 生产 Preflight（只读健康、release/commit 与候选差异核查）** | 历史只读记录；不代表 2026-08-13 当前线上版本，不计入 cutover gate |
| [web-to-tui-m5-production-preflight-2026-08-13.md](plans/web-to-tui-m5-production-preflight-2026-08-13.md) | **Web → TUI M5 当前生产 Preflight（公开探针 + 只读 release/OCI 核对）** | health/ready 正常；仓库发布 provenance 已修但尚未部署，当前线上仍 revision=`unknown`/无 manifest，观察未开始 |
| [web-to-tui-m5-rollback-drill-evidence-2026-07-27.md](plans/web-to-tui-m5-rollback-drill-evidence-2026-07-27.md) | **Web → TUI M5 回滚演练（隔离 reverse/restore、旧 graph 兼容与 registry 回滚发布）** | 历史记录不再算当前闸门；candidate-bound 本地演练已修复，最终候选/生产备份恢复待验 |
| [web-to-tui-m5-browser-uat-evidence-2026-07-27.md](plans/web-to-tui-m5-browser-uat-evidence-2026-07-27.md) | **Web → TUI M5 浏览器 UAT（角色边界、矩阵深链、直读/参数读取与生命周期）** | 历史自动化 15/15、主任务 108/108；未绑定最终候选，当前 gate FAIL |
| [web-to-tui-m5-route-closure-evidence-2026-07-27.md](plans/web-to-tui-m5-route-closure-evidence-2026-07-27.md) | **Web → TUI M5 逐 Route 清理证据（认证边界、兼容目标与状态/回滚范围）** | ✅ 六类 scope 均为 108/108；不替代生产门禁 |
| [tui-regime-display-contract-postmortem-2026-07-30.md](archive/plans/tui-regime-display-contract-postmortem-2026-07-30.md) | **TUI Regime 有数据未显示复盘（契约漂移、fail-closed 与跨层回归门禁）** | ✅ 整改完成并归档，持续执行门禁 |
| [qmt-live-trading-bridge-plan.md](plans/qmt-live-trading-bridge-plan.md) | **QMT 本地执行桥与 VPS 实盘交易接入计划（Web / TUI / MCP / 权限 / 风控 / 对账）** | 仓库 MVP 已实现；待目标券商 Phase 0 与仿真实测 |
| [adr-0002-qmt-local-execution-bridge.md](architecture/adr-0002-qmt-local-execution-bridge.md) | QMT 本地 Agent + VPS 控制面架构决策 | 已接受 |
| [qmt-agent-runbook.md](operations/qmt-agent-runbook.md) | Windows QMT Agent 安装、分级启用、停止与故障处理 | 可执行 |
| [qmt-agent-local-install-package.md](operations/qmt-agent-local-install-package.md) | 国金普通 QMT `userdata` 本地 Agent ZIP 安装包、DPAPI Token、权限诊断与卸载 | 可执行 |
| [research-integrity-and-decision-reproducibility-2026-07-21.md](plans/research-integrity-and-decision-reproducibility-2026-07-21.md) | **研究可信度、组合构建与决策复算整改（M0-M6）** | 开发中：canonical schema/API 已落地，切换门禁默认关闭 |
| [qmt-agent-v1.schema.json](api/qmt-agent-v1.schema.json) | QMT Agent v1 请求契约 JSON Schema 文档投影 | DRF Serializer 为运行时真源 |
| [tui-ia-consolidation-2026-07-20.md](archive/plans/tui-ia-consolidation-2026-07-20.md) | **TUI 信息架构重构计划（普通用户 13 屏 / 管理员 16 屏，8 步决策流，权限分层）** | ✅ 2026-07-21 已实施并归档 |
| [agomtui-portability-remediation-2026-07-21.md](plans/agomtui-portability-remediation-2026-07-21.md) | **AgomTUI 可移植性整改方案（Runtime 单向同步、schema 兼容、宿主接入与双端门禁）** | 待批准 |
| [uat-remediation-2026-07-20.md](plans/uat-remediation-2026-07-20.md) | **外部 UAT 复核、代码整改与生产数据恢复边界** | 进行中：代码整改完成，待生产发布与数据回填 |
| [implementation-progress-summary.md](plans/implementation-progress-summary.md) | **总体进度总结（Phase 1-5 完成）** | 最新 |
| [AI-native-blueprint-260315.md](plans/AI-native-blueprint-260315.md) | **AI Native 升级蓝图** | 进行中 |
| [AI-Native-upgrade-implement-plan-260315.md](plans/AI-Native-upgrade-implement-plan-260315.md) | **AI Native 升级实施计划** | 进行中 |
| [ai-native/README.md](plans/ai-native/README.md) | **AI Native 子项目索引** | 进行中 |
| [ai-native/execution-backlog.md](plans/ai-native/execution-backlog.md) | **AI Native 执行积压** | 进行中 |
| [eastmoney-integration.md](archive/plans/eastmoney-integration.md) | **东方财富数据源集成计划** | ✅ 已实施并归档 |
| [production-code-remediation-plan-2026-06-26.md](archive/plans/production-code-remediation-plan-2026-06-26.md) | **投产代码整改方案（数据守门 / 初始化 / UI 闭环）** | ✅ 2026-06-26 完成并归档 |
| [0.8.0-release-closure-plan-2026-07-05.md](archive/plans/0.8.0-release-closure-plan-2026-07-05.md) | **0.8.0 收口开发计划（发布 / 运维 / 架构减债 Top 10）** | ✅ 2026-07-05 已执行并归档 |
| [post-0.8.0-stabilization-priority-2026-07-08.md](plans/post-0.8.0-stabilization-priority-2026-07-08.md) | **0.8.0 发布后两周稳定化实施清单（优先级 / 负责人 / 命令 / 验收）** | 进行中 |
| [evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md](plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md) | **证据治理与决策硬闸改造计划** | 第一期 P0：Portfolio/Risk/Broker inactive owner contracts与ledgers、Risk policy workflow以及Broker pre-Risk ID-only scope已分阶段落盘；pre-Risk仍固定inactive，缺跨账户owner binding、Risk adapter、最终issuer/四节点重验与PG/生产证明，所有执行总闸保持关闭，MCP integrated=0 |
| [mcp-consolidation-remediation-plan-2026-07-09.md](archive/plans/mcp-consolidation-remediation-plan-2026-07-09.md) | **MCP 收口整改计划（统一能力注册、统一调用、legacy 退役）** | ✅ 完成并归档；持续状态由机器门禁维护 |
| [system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md](archive/plans/system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md) | **系统级 AI Capability Catalog 与统一路由任务书** | ✅ 代码与自动化验收完成并归档 |
| [terminal-mcp-governance-outsourcing-task-book-2026-03-19.md](archive/plans/terminal-mcp-governance-outsourcing-task-book-2026-03-19.md) | **Terminal MCP 治理与确认机制任务书** | ✅ 已实现并由 AgentProposal 持久审批架构承接 |
| [terminal-refactor-plan-260709.md](archive/plans/terminal-refactor-plan-260709.md) | **Terminal Agents SDK + MCP 重构计划** | ✅ Agents SDK、SSE、MCP 与持久审批完成并归档 |
| [auto-advisor-prd-2026-06-25.md](archive/plans/auto-advisor-prd-2026-06-25.md) | **账户级自动投顾 PRD（持仓驱动 + 建议订单清单）** | ✅ Implemented v1，已归档 |
| [auto-advisor-implementation-2026-06-25.md](archive/plans/auto-advisor-implementation-2026-06-25.md) | **账户级自动投顾实施文档（后端/Classic UI/TUI/测试）** | ✅ Implemented v1，已归档 |
| [personal-auto-advisor-roadmap-2026-06-30.md](archive/plans/personal-auto-advisor-roadmap-2026-06-30.md) | **个人自用自动投顾增强路线图（风控 / 数据新鲜度 / 决策卡片 / 复盘）** | ✅ Implemented v1，已归档 |
| [macro-sizing-multiplier-outsourcing-2026-03-31.md](plans/macro-sizing-multiplier-outsourcing-2026-03-31.md) | **宏观感知仓位系数模块外包任务书（Regime+Pulse+回撤三因子）** | 待开发 |
| [streamlit-dashboard-upgrade-plan.md](plans/streamlit-dashboard-upgrade-plan.md) | Streamlit 仪表盘交互升级实施方案 | 最新 |
| [architecture-cycle-remediation-2026-04-26.md](archive/plans/architecture-cycle-remediation-2026-04-26.md) | **循环依赖与架构债历史整改方案（CI + AGENTS + 模块归属）** | 历史方案，已归档 |
| [architecture-cycle-remediation-2026-07-15.md](archive/plans/architecture-cycle-remediation-2026-07-15.md) | **循环依赖回流整改与零循环收口计划** | ✅ 零双向依赖、零循环组件，已归档 |
| [repository-debt-remediation-closure-2026-07-19.md](archive/plans/repository-debt-remediation-closure-2026-07-19.md) | **仓库架构与治理债务总收口（大文件 / provider / 依赖 / 卫生 / 类型）** | ✅ 2026-07-19 已完成并归档 |
| [maintainability-refactoring-plan-2026-07-20.md](archive/plans/maintainability-refactoring-plan-2026-07-20.md) | **代码库可维护性定向重构计划（R0-R2）** | ✅ R2 已完成并归档 |
| [testing-improvement-plan-2026-07-24.md](archive/plans/testing-improvement-plan-2026-07-24.md) | **分层测试与 TDD 反馈环提升计划（T0-T5）** | ✅ 2026-07-24 已完成并归档 |
| [test-coverage-weakness-remediation-progress-2026-07-24.md](plans/test-coverage-weakness-remediation-progress-2026-07-24.md) | **覆盖率薄弱环节整改实施记录（T0-T3A）** | 进行中：独立分支、branch/multi-scope 基线重采 |
| [test-coverage-weakness-remediation-2026-07-24.md](plans/test-coverage-weakness-remediation-2026-07-24.md) | **测试覆盖薄弱环节整改计划（统计边界、分支覆盖、风险模块与生产集成）** | 已合入 next-development |
| [maintainability-r2/r2-stage-record-2026-07-20.md](archive/plans/maintainability-r2/r2-stage-record-2026-07-20.md) | **R2 测试收敛阶段记录与回归证据** | ✅ 2026-07-20 已完成并归档 |
| [maintainability-r3-lite/r3-lite-stage-record-2026-07-20.md](archive/plans/maintainability-r3-lite/r3-lite-stage-record-2026-07-20.md) | **R3-lite 估值 owner 拆分与稳定性收口记录** | ✅ 2026-07-20 已完成并归档 |
| [maintainability-stability/stability-closeout-2026-07-20.md](archive/plans/maintainability-stability/stability-closeout-2026-07-20.md) | **R2 + R3-lite 集成契约稳定性收口记录** | ✅ 2026-07-20 已完成并归档 |
| [regime-navigator-pulse-redesign-260323.md](archive/plans/regime-navigator/regime-navigator-pulse-redesign-260323.md) | **系统重新设计：Regime Navigator + Pulse 分层架构** | ✅ 已实施并归档 |
| [phase-1-regime-navigator-pulse-mvp.md](archive/plans/regime-navigator/phase-1-regime-navigator-pulse-mvp.md) | Phase 1: Regime Navigator + Pulse MVP + Dashboard 改造 | ✅ 已完成并归档 |
| [phase-2-decision-funnel.md](archive/plans/regime-navigator/phase-2-decision-funnel.md) | Phase 2: 决策模式引导漏斗 | ✅ 已完成并归档 |
| [phase-3-enrichment-polish.md](archive/plans/regime-navigator/phase-3-enrichment-polish.md) | Phase 3: 增强与打磨（Pulse V2 + 配置化 + 历史回溯） | ✅ 已完成并归档 |

### 5. 测试文档 (`testing/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [master-test-strategy-2026-02.md](testing/master-test-strategy-2026-02.md) | **全面测试策略（L0-L7、关键可靠性、测试分层与覆盖率门禁）** | ✅ 2026-07-24 更新 |
| [critical-reliability-test-closure-2026-07-22.md](plans/critical-reliability-test-closure-2026-07-22.md) | **数据到对账关键可靠性测试与发布门禁收口记录** | ✅ 本地收口，等待 PostgreSQL Nightly |
| [smart-test-selection.md](development/ci/smart-test-selection.md) | **增量测试映射、未知 App 全量回退与关键集合选择规则** | ✅ 2026-07-22 更新 |
| [coverage-governance.md](development/ci/coverage-governance.md) | **多范围行/分支覆盖率真源、报告与 ratchet 规则** | ✅ 2026-07-24 新增 |
| [celery-task-contract-guard.md](development/celery-task-contract-guard.md) | **Celery 技术状态、业务 outcome 与关键任务测试契约门禁** | ✅ 已纳入 fast feedback |
| [data-freshness-contract-guard.md](development/data-freshness-contract-guard.md) | **当前数据 observation/freshness/failover/决策阻断契约门禁** | ✅ 已纳入 consistency check |
| [postmortem-realtime-stale-market-summary-2026-07-30.md](development/postmortem-realtime-stale-market-summary-2026-07-30.md) | **VPS Terminal 旧行情冒充当前值事故复盘与防复发矩阵** | ✅ 2026-07-30 完成 |
| [vps-uat-e2e-findings-2026-07-31.md](development/vps-uat-e2e-findings-2026-07-31.md) | **VPS UAT / E2E / MCP 生产问题清单（先冻结问题，再逐项修复与复测）** | ✅ 2026-07-31 完成 |
| [personal-investment-readiness-2026-06-30.md](testing/personal-investment-readiness-2026-06-30.md) | **个人投研系统可用性验收记录（readiness / Qlib / Alpha / 决策数据 / 连续运行证据）** | ✅ 2026-06-30 更新 |
| [0.8.0-release-regression-report-2026-07-05.md](testing/0.8.0-release-regression-report-2026-07-05.md) | **0.8.0 发布回归报告（版本 / TUI / 治理 / readiness）** | ✅ 2026-07-05 新增 |
| [post-0.8.0-stabilization-checkpoint-2026-07-08.md](testing/post-0.8.0-stabilization-checkpoint-2026-07-08.md) | **0.8.0 发布后稳定化检查点（live health / 回归 / readiness 阻塞项）** | ✅ 2026-07-08 新增 |
| [outsourcing-full-regression-plan-2026-02-26.md](archive/process/testing/outsourcing-full-regression-plan-2026-02-26.md) | 外包全量回归执行方案（双环境+分层门禁+证据包）（归档） | ✅ 已归档 |
| [outsourcing-acceptance-plan-post-v34-2026-02-26.md](archive/process/testing/outsourcing-acceptance-plan-post-v34-2026-02-26.md) | 外包开发验收方案（V3.4 后续路线图）（归档） | ✅ 已归档 |
| [requirements-traceability-matrix-2026-02.md](testing/requirements-traceability-matrix-2026-02.md) | **需求-测试追踪矩阵（含关键可靠性、分层质量与真实 QMT 门禁）** | ✅ 2026-07-24 更新 |
| [sdk-mcp-integration-test-plan.md](testing/sdk-mcp-integration-test-plan.md) | SDK & MCP 集成测试计划（1000行） | 完整 |
| [full-integration-test-report.md](testing/full-integration-test-report.md) | 完整集成测试报告 | 完整 |
| [system_algorithm_evaluation_report.md](testing/system_algorithm_evaluation_report.md) | 系统算法评估 | 完整 |
| [doc-link-check-report.md](testing/doc-link-check-report.md) | 文档链接校验报告 | 最新 |
| [bug-report-template.md](testing/bug-report-template.md) | Bug 报告模板 | 完整 |
| [test-results-template.md](testing/test-results-template.md) | 测试结果模板 | 完整 |
| [api/API_REFERENCE.md](testing/api/API_REFERENCE.md) | API 参考文档 | 完整 |
| [api/decision-rhythm-api.md](api/decision-rhythm-api.md) | **决策工作流 API 文档（估值+审批）** | ✅ 2026-03-02 新增 |
| [api/decision-workspace-v2.md](api/decision-workspace-v2.md) | **决策工作台 V2 API 草稿（统一推荐/参数）** | ✅ 2026-03-02 新增 |
| [decision-workspace-v2-acceptance.md](testing/decision-workspace-v2-acceptance.md) | **决策工作台 V2 验收测试清单（功能/数据/测试/性能/回归）** | ✅ 2026-03-03 新增 |

### 3.0 实施计划 (`plans/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [qlib-local-upload-user-isolation.md](archive/plans/qlib-local-upload-user-isolation.md) | Qlib 本地上传用户隔离方案 | 完整 |
| [eastmoney-integration.md](archive/plans/eastmoney-integration.md) | **东方财富数据源集成计划（资金流向/新闻情感/实时行情/技术指标）** | ✅ 已实施并归档 |

### 3.1 开发技术专题 (`development/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [decision-unified-workflow.md](development/decision-unified-workflow.md) | **统一工作流技术文档（数据模型/融合算法/状态流转/API）** | ✅ 2026-03-03 新增 |
| [decision-workflow-state-diagram.md](development/decision-workflow-state-diagram.md) | **决策工作流状态流转图** | ✅ 2026-03-03 新增 |

### 7. 部署与运维专题 (`deployment/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [DOCKER_DEPLOYMENT.md](deployment/DOCKER_DEPLOYMENT.md) | Docker 部署指南 | 完整 |
| [QLIB_TRAIN_RUNTIME_SETUP.md](deployment/QLIB_TRAIN_RUNTIME_SETUP.md) | Qlib 训练运行时搭建与接入指南 | ✅ 2026-03-13 新增 |
| [vps-a-frps-nginx-setup.md](deployment/vps-a-frps-nginx-setup.md) | **A 机部署：Linux VPS 上 FRPS + Nginx** | ✅ 2026-03-08 新增 |
| [b-local-frpc-docker-setup.md](deployment/b-local-frpc-docker-setup.md) | **B 机部署：Windows + WSL2 + Docker + FRPC** | ✅ 2026-03-08 新增 |

### 6. AI 相关 (`ai/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [ai_prompt_system.md](ai/ai_prompt_system.md) | AI 提示词系统使用文档 | 完整 |
| [ai_provider_requirements.md](ai/ai_provider_requirements.md) | AI 服务商管理需求 | 完整 |
| [prompt_templates_guide.md](ai/prompt_templates_guide.md) | Prompt 模板指南 | 完整 |

### 7. 部署文档 (`deployment/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [TEST_PACKAGE_RELEASE_WORKFLOW.md](deployment/TEST_PACKAGE_RELEASE_WORKFLOW.md) | 标准流程：测试->打包->发布->回滚（含门禁） | ✅ 新增 |
| [VPS_BUNDLE_DEPLOYMENT.md](deployment/VPS_BUNDLE_DEPLOYMENT.md) | VPS Bundle 一体化部署与迁移指南（含 Postgres/Redis 迁移） | ✅ 新增 |
| [DOCKER_DEPLOYMENT.md](deployment/DOCKER_DEPLOYMENT.md) | Docker 部署指南 | 完整 |
| [postgres_windows_docker.md](deployment/postgres_windows_docker.md) | Windows PostgreSQL Docker 配置 | 完整 |
| [database_configuration.md](deployment/database_configuration.md) | 数据库配置 | 完整 |

### 8. 用户指南 (`user/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [decision-platform-guide.md](user/decision-platform-guide.md) | 决策平台用户指南（442行） | 完整 |
| [topdown-bottomup-execution-playbook.md](user/topdown-bottomup-execution-playbook.md) | 环境-标的-执行-审计一体化操作手册 | ✅ 最新 |

### 9. 前端体验 (`frontend/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [ui-ux-full-page-audit-2026-02-18.md](archive/process/frontend/ui-ux-full-page-audit-2026-02-18.md) | 全站页面 UI/UX 盘点与功能清单（归档） | ✅ 已归档 |
| [ux-user-journey-checklist-2026-02-18.md](archive/process/frontend/ux-user-journey-checklist-2026-02-18.md) | 用户旅程式 UX 检查清单（归档） | ✅ 已归档 |

### 10. 模块文档 (`modules/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [alpha/alpha-guide.md](modules/alpha/alpha-guide.md) | Alpha 模块指南 | 完整 |
| [alpha/qlib-model-import-guide.md](modules/alpha/qlib-model-import-guide.md) | Qlib 模型导入说明 | ✅ 2026-03-13 新增 |
| [policy/policy-workbench-guide.md](modules/policy/policy-workbench-guide.md) | Policy 工作台指南（双闸机制） | ✅ 2026-02-28 更新 |
| [decision/decision-workflow-guide.md](modules/decision/decision-workflow-guide.md) | **决策工作流使用指南（V3.4+）** | ✅ 2026-03-01 新增 |
| [audit/audit-module-guide.md](modules/audit/audit-module-guide.md) | Audit 模块指南 | ✅ 新增 |
| [audit/attribution-methodology.md](modules/audit/attribution-methodology.md) | Brinson 归因方法论 | ✅ 新增 |
| [factor/factor-guide.md](modules/factor/factor-guide.md) | Factor 模块指南 | 完整 |
| [rotation/rotation-guide.md](modules/rotation/rotation-guide.md) | Rotation 模块指南 | 完整 |
| [data-center-market-thermometer.md](modules/data-center-market-thermometer.md) | **Data Center 市场温度计（输入口径/API/Dashboard/Terminal）** | ✅ 2026-05-19 新增 |
| [hedge/hedge-guide.md](modules/hedge/hedge-guide.md) | Hedge 模块指南 | 完整 |
| [terminal/terminal-guide.md](modules/terminal/terminal-guide.md) | Terminal 模块指南（终端 AI CLI） | ✅ 2026-03-17 新增 |
| [ai_capability/ai-capability-guide.md](modules/ai_capability/ai-capability-guide.md) | **AI Capability Catalog 模块指南** | ✅ 2026-03-19 新增 |
| [simulated_trading/daily-inspection.md](modules/simulated_trading/daily-inspection.md) | 模拟盘日更巡检 | ✅ 新增 |
| [strategy/position-management.md](modules/strategy/position-management.md) | 策略仓位管理 | ✅ 新增 |
| [strategy/strategy-auto-trading-mcp.md](modules/strategy/strategy-auto-trading-mcp.md) | 策略配置、MCP 与模拟盘自动交易链路 | ✅ 2026-04-25 新增 |

### 11. 集成文档 (`integration/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [akshare_realtime_guide.md](integration/akshare_realtime_guide.md) | AKShare 实时数据指南 | 完整 |
| [how2usersshub.md](integration/how2usersshub.md) | RSSHub 使用指南 | 完整 |
| [realtime_data_system.md](integration/realtime_data_system.md) | 实时数据系统 | 完整 |
| [rss_policy_integration.md](integration/rss_policy_integration.md) | RSS 政策集成 | 完整 |

### 12. 迁移文档 (`migration/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [route-migration-guide.md](migration/route-migration-guide.md) | **API 路由迁移指南（V3.5）** | ✅ 2026-03-04 新增 |
| [migration-quick-reference.md](migration/migration-quick-reference.md) | **迁移速查表** | ✅ 2026-03-04 新增 |

### 13. 归档文档 (`archive/`)

| 文档 | 说明 |
|------|------|
| [ARCHIVE_INDEX.md](archive/ARCHIVE_INDEX.md) | **归档文档索引** |

归档内容包括：
- Phase 1-5 实施总结（已整合到 `implementation-progress-summary.md`）
- 修复记录、前端改造清单、UAT 测试报告等过程性文档

### 13. SDK 与 MCP (`../sdk/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [../sdk/README.md](../sdk/README.md) | SDK/MCP 总览、安装、认证、工具与模块清单 | ✅ 2026-02-26 更新 |
| [testing/sdk-mcp-integration-test-plan.md](testing/sdk-mcp-integration-test-plan.md) | SDK/MCP 集成测试方案 | ✅ 最新 |

---

## 项目状态

**系统版本**: AgomTradePro 0.8.0

**系统规模口径**: 机器唯一真源为 [`governance/governance_baseline.json`](../governance/governance_baseline.json)；[governance/SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) 只提供叙事索引和验证入口

**REST API 路径**: OpenAPI 快照

**文档文件**: `docs/` 目录清单

**版本管理**: 参见 [VERSION.md](VERSION.md)

**完成度**: 持续迭代（请以里程碑文档与代码状态为准）

### SDK/MCP 口径（2026-02-26）

- 对外接入层：`sdk/agomtradepro`（Python SDK）+ `sdk/agomtradepro_mcp`（MCP Server）
- 本地 MCP 回归：`98 passed`（tool registration + tool execution + RBAC）
- 说明：测试数字为当日快照，最终以最新 CI/本地执行结果为准

### 导航口径快照（2026-03-24）

- 宏观环境统一入口文案：`政策/情绪/热点工作台`（`/policy/workbench/`）
- 顶部导航按主流程重构：`系统首页 -> 决策工作台 -> 账户与执行 -> 策略研究 -> 系统`
- Dashboard 左侧不再单独暴露 `beta_gate` / `alpha_trigger` / `decision_rhythm`；这些能力统一收束到“决策工作台 / 决策模式”
- 投资管理账户入口文案：`我的投资账户`（替代"我的模拟仓"）
- API 文档入口：仅保留"系统"菜单中的 `/api/docs/`
- 页面导航规范：业务页面链接使用 Django `{% url %}`，禁止硬编码业务路径
- 页面与 API 边界：页面导航不得直连业务 API（`/api/*`），仅 `/api/docs/` 例外

### 完整四层架构模块清单

#### 核心引擎模块
- `macro` - 宏观数据采集
- `regime` - Regime 判定
- `policy` - 政策事件管理
- `signal` - 投资信号管理
- `filter` - HP/Kalman 滤波

#### 资产分析模块
- `asset_analysis` - 通用资产分析框架
- `equity` - 个股分析
- `fund` - 基金分析
- `sector` - 板块分析
- `sentiment` - 舆情情感分析

#### AI 智能模块
- `alpha` - Alpha AI 选股信号（Qlib 集成）
- `alpha_trigger` - Alpha 离散触发
- `beta_gate` - Beta 闸门
- `decision_rhythm` - 决策频率约束
- `factor` - 因子管理
- `rotation` - 板块轮动
- `hedge` - 对冲策略
- `ai_capability` - **系统级 AI 能力目录与统一路由** ✅ 2026-03-19 新增

#### 风控与账户模块
- `account` - 账户与持仓管理
- `audit` - 事后审计（完整测试覆盖 + Brinson 归因 + 前端可视化）
- `simulated_trading` - 模拟盘自动交易
- `realtime` - 实时价格监控
- `strategy` - 策略系统

#### 数据接入模块
- `data_center` - 统一数据中台（Provider 配置、标准化、同步、查询、MCP/SDK 对齐）

#### 战术指标模块
- `pulse` - **Pulse 脉搏层（战术指标聚合与转折预警）** ✅ 2026-03-28 新增

#### 工具模块
- `ai_provider` - AI 服务商管理
- `prompt` - AI Prompt 模板
- `dashboard` - 仪表盘
- `backtest` - 回测引擎
- `events` - 事件系统
- `task_monitor` - 定时任务监控
- `share` - 分享功能
- `setup_wizard` - **系统初始化向导** ✅ 2026-03-23 新增

#### AI 运行时模块
- `terminal` - 终端 CLI（AI 交互界面）
- `agent_runtime` - Agent 运行时（Terminal AI 后端，支持任务编排和 Facade 模式）

---

## 阅读路径

### 新加入开发人员
1. [QUICK_START.md](QUICK_START.md) - 系统实战理念
2. [development/quick-reference.md](development/quick-reference.md) - 快速了解常用命令和 API
3. [governance/SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) - **系统基线叙事索引；动态数字读取机器基线**
4. [SYSTEM_SPECIFICATION.md](SYSTEM_SPECIFICATION.md) - 理解系统架构
5. [business/AgomTradePro_V3.4.md](business/AgomTradePro_V3.4.md) - 学习业务逻辑
6. [development/coding_standards.md](development/coding_standards.md) - 遵循代码规范

### 理解 AI 选股
1. [business/alpha-quickstart.md](business/alpha-quickstart.md) - Alpha 模块快速开始
2. [modules/alpha/qlib-model-import-guide.md](modules/alpha/qlib-model-import-guide.md) - Qlib 模型导入说明
3. [plans/implementation-progress-summary.md](plans/implementation-progress-summary.md) - 实施进度

### 部署运维
1. [deployment/VPS_BUNDLE_DEPLOYMENT.md](deployment/VPS_BUNDLE_DEPLOYMENT.md) - VPS 一体化打包与部署指南
2. [deployment/TEST_PACKAGE_RELEASE_WORKFLOW.md](deployment/TEST_PACKAGE_RELEASE_WORKFLOW.md) - 标准发布工作流（测试->打包->发布）
3. [deployment/DOCKER_DEPLOYMENT.md](deployment/DOCKER_DEPLOYMENT.md) - Docker 部署指南
4. [deployment/database_configuration.md](deployment/database_configuration.md) - 数据库配置
5. [development/startup-scripts.md](development/startup-scripts.md) - 启动脚本

---

## 文档口径来源

- 仓库级动态治理数据以 `governance/governance_baseline.json` 为机器唯一真源。
- MCP live 治理数据写入 `governance/governance_baseline.json` 的 `mcp_governance` 字段；历史整改过程见[已归档 MCP 收口计划](archive/plans/mcp-consolidation-remediation-plan-2026-07-09.md)，当前完成证据见 [MCP Full Closure Evidence](development/mcp-full-closure-evidence-2026-07-14.md)。
- 本索引只维护导航、清单和阅读路径，不复制业务模块数、MCP 工具数、静态测试函数数等动态治理数字。
- 验证命令：`python scripts/check_governance_consistency.py --baseline governance/governance_baseline.json --format text`

---

## 贡献指南

文档更新应遵循以下原则：

1. **时效性**: 重大变更后 24 小时内更新相关文档
2. **一致性**: 保持文档间引用关系的正确性
3. **完整性**: 新增模块必须同步更新架构文档
4. **准确性**: 代码示例必须经过验证

---

## 最近更新 (2026-02-20 ~ 2026-06-20)

### 2026-08-13
- ✅ **Portfolio inactive approval receipt subject seal 修正**
  - receipt 现绑定 exact subject identity/hash、requester 与 plan selector；actor/user 双身份非自批，跨 actor replay 失败关闭
  - `plan_status_at_issue` 仅为 inactive 审计快照，canonical-v1 hash 未绑定 lifecycle，submit 与 Broker 总闸继续关闭
  - 详见 [Evidence 治理与决策硬闸整改计划](plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md)
- ✅ **Portfolio inactive approval append-only persistence 首批**
  - 两张private-UOW append-only ledger、strict codec、exact/PIT reader与approved_at provider落盘；0017保持schema-only/zero-seed
  - 当前仍无人工入口与PostgreSQL并发证明，receipt固定inactive，不接旧approve/submit/Broker
- ✅ **Risk-owned Broker execution policy Domain 合同**
  - 冻结完整Decimal风险参数、source snapshot、activation/validity与supersession hash；拒绝把现有mutable policy临时hash成正式授权
  - 仅合同与纯测试完成，active provider/ledger仍缺，Risk authorization与Broker总闸继续关闭
- ✅ **Broker order approval owner artifact**
  - 以Broker自有content-addressed工件封存订单UUID/version、完整approval snapshot/digest、批准人和有效期，并重验金额与推荐lineage
  - 工件固定inactive/must-not-execute；append-only ledger/provider与跨owner授权仍未完成，四节点总闸不变
- ✅ **Risk execution policy Application workflow**
  - ID-only激活精确绑定五类source component、server human-staff actor、first-winner/CAS predecessor及logical-current PIT投影
  - 当前仅pure fake协议；生产source/ledger/provider与PG并发仍缺，Risk authorization不可生产签发，Broker总闸继续关闭
- ✅ **Broker order approval artifact append-only persistence**
  - private-UOW账本、strict codec、first-winner与历史exact/PIT reader已落盘；0008 schema-only/zero-seed，Django5.2最小SQLite往返通过
  - 仅为历史owner seal，不授予current execution permission；pre-risk scope、PG并发和四节点重验仍未完成
- ✅ **Risk execution policy append-only persistence**
  - 五源snapshot+actor-bound activation账本、strict codec、first-winner/CAS与full-chain current-head已落盘；0009 schema-only/zero-seed，Django5.2最小往返通过
  - mutable policy尚无可信source composition且PG并发未验，zero-seed不自动激活，Risk authorization与Broker总闸继续关闭
- ✅ **Broker/Risk ledger contract audit修正**
  - 对齐0008/0009 constraint state并补Broker persisted clock DB约束；Risk authorization同时绑定policy content hash与actor activation hash
  - 聚合53项与架构门禁通过；完整migration drift受当前环境缺cryptography阻断，PG并发/source selector闭集检测仍未完成
- ✅ **Risk policy source closed-world restore**
  - source first-winner与activation source binding先restore完整source ledger，再用Domain identity选winner；tuple+seal双篡改不能隐藏坏行或重开identity
  - component回归已补，完整Django runtime与PostgreSQL race仍待验证；zero-seed和Broker执行总闸不变
- ✅ **Broker pre-Risk inactive scope 合同与workflow**
  - ID-only注册在同一Broker server cutoff双读Portfolio plan/inactive receipt与Broker order artifact，并封存三源exact identity/hash/有效期及本地supersession head
  - scope固定inactive、must-not-execute并保留5个blocker；36项纯测试通过，ORM ledger、跨账户owner binding、Risk adapter和最终issuer仍未完成
- ✅ **Broker pre-Risk append-only persistence**
  - private-UOW账本、strict codec、root/successor first-winner及closed-world current-head restore落盘；双selector篡改不能隐藏后继，expired head不回退旧root
  - 0009 schema-only/zero-seed，Django5.2最小往返通过；完整component/PG race未验，inactive scope不能映射为Risk active provider，最终执行总闸不变
- ✅ **Broker/Portfolio 账户 namespace binding Domain 合同**
  - Broker整数账户与Portfolio字符串账户保持独立namespace，不以类型转换猜测同一身份；账户身份source固定归Account owner，Portfolio只消费字符串引用，两侧source seal和人工断言者均进入identity/content hash
  - 仅为inactive合同；source provider、ID-only workflow、append-only ledger、人工入口与PG并发均未完成，pre-Risk blocker和执行总闸不变
- ✅ **Broker Plan→Order inactive binding Domain 合同**
  - 精确绑定canonical-v1 plan/receipt/subject、稳定order ordinal与单行bytes/hash，以及Broker order artifact identity/content/digest；三方owner/type与最早有效期均被封存
  - 不使用资产/数量近似推断且固定must-not-execute；owner providers、Application workflow、ledger和真实签发均未完成，pre-Risk blocker不变
- ✅ **Broker/Account namespace binding Application workflow**
  - ID-only注册双读Broker与Account exact-current source，强制相同owner user、real+active，由server human-staff actor和first-winner/CAS封存inactive binding
  - 当前只有协议与pure fake；两侧immutable source/provider、binding ledger、composition及PG并发均缺，pre-Risk与执行总闸继续关闭
- ✅ **Broker/Account namespace binding append-only ledger**
  - strict codec/private UOW、single-root/predecessor CAS、closed-world exact/PIT/current与canonical/header/clock seals完成；0011 zero-seed
  - Django5.2 minimal round-trip通过；完整component/PG并发与两侧真实facade/composition未完成，inactive与执行总闸不变
- ✅ **Portfolio policy benchmark snapshot Domain 合同**
  - 以exact owner refs、严格Decimal组件、权重守恒、live inception与三源最早有效期冻结policy benchmark candidate；拒绝Float配置/临时行情洗白
  - 固定inactive；Account/planning-policy/definition owner source、daily valuation、审批、ledger/provider与Broker issuer均未完成
- ✅ **Portfolio policy benchmark definition Domain 合同**
  - 完整冻结成分/price identity/币种/Decimal权重、日历/价格/FX/公司行动/费用税费五类owner ref、估值cutoff/窗口/陈旧度和missing fail-closed
  - 固定definition-only；methodology owner provider、definition activation、daily valuation与approval仍未完成
- ✅ **Portfolio policy benchmark definition append-only ledger**
  - strict codec/private UOW、first-winner、全写绕过阻断和closed-world exact/PIT完成；0020 zero-seed且不回填mutable Float配置
  - 只提供historical exact，不冒充current/activation；PG并发、methodology providers、activation/daily valuation/approval仍未完成
- ✅ **Portfolio benchmark trading-calendar methodology Domain 合同**
  - 以IANA timezone、完整逐日membership、valuation session/cutoff与DST规则冻结Portfolio估值日历方法论；不复用R8 monitoring calendar或原始市场事实
  - 固定definition-only；ledger/两人activation/current provider与其余四类methodology未完成，benchmark definition不得提前active
- ✅ **Portfolio benchmark trading-calendar methodology append-only ledger**
  - private UOW/claim、first-winner、逐日/DST/header seals与closed-world exact/PIT完成；0021 zero-seed且不回填R8/Data Center事实
  - 不发明current/activation；PG并发、两人activation/current provider与其余四类methodology未完成
- ✅ **Portfolio benchmark price-fixing methodology Domain 合同**
  - 显式close/nav/settlement+unadjusted口径、有序exact source refs、IANA cutoff与stale/missing/source failure全fail-closed
  - 固定definition-only；ledger/两人activation/current provider及FX/corporate-action/cost-tax三类methodology未完成
- ✅ **Portfolio benchmark price-fixing methodology append-only ledger**
  - private UOW/claim、first-winner、source/DST/header seals与closed-world exact/PIT完成；0022 zero-seed且不回填行情/config事实
  - 不发明current/activation；PG并发、两人activation与FX/corporate-action/cost-tax三类methodology仍未完成
- ✅ **Portfolio benchmark FX-fixing methodology Domain 合同**
  - currency pair/报价方向/inverse显式闭合，IANA cutoff、exact sources、stale/missing/source failure全fail-closed；v1禁止自动三角换汇
  - 固定definition-only；ledger/两人activation/current provider及corporate-action/cost-tax两类methodology未完成
- ✅ **Portfolio benchmark FX-fixing methodology append-only ledger**
  - private UOW/claim、first-winner、source/DST/header seals与closed-world exact/PIT完成；0023 zero-seed且不回填FX配置/行情
  - Django5.2组件7 passed、Domain 8 passed；无current/activation，首次发现的transition drift已在下一阶段修复，PG并发/mypy plugin仍待收口
- ✅ **Portfolio benchmark corporate-action methodology Domain 合同**
  - 闭合分红、送股、拆股、并股与配股五类v1处理；除权/支付日防重复、拆并股不制造收益，配股缺exact条款和选择证据即阻断
  - 仅接受unadjusted输入和exact-event-once，有序exact refs、IANA业务日与fail-closed策略入hash；固定definition-only，ledger/activation/current及cost-tax仍未完成
- ✅ **Portfolio benchmark corporate-action methodology append-only ledger**
  - private UOW/claim、first-winner、五类event/source/DST/header seals与closed-world exact/PIT完成；0025 zero-seed且不回填事件事实
  - Django5.2组件9 passed、Portfolio migration no-drift；无current/activation，PG并发、单次行动owner facts与两人activation仍缺
- ✅ **Portfolio benchmark cost/tax methodology Domain 合同**
  - fee/tax exact source逐条封存scope、jurisdiction、方向、基数、时点、币种、Decimal值与取整；不内嵌真实税率或费用默认
  - 显式零可封存但missing/unknown不得转零，分红entitlement只计一次；固定definition-only，ledger/activation/current与owner producers仍未完成
- ✅ **Portfolio benchmark cost/tax methodology append-only ledger**
  - private UOW/claim、first-winner、source/rule/Decimal/header seals与closed-world exact/PIT完成；DB同时守恒fee/tax计数和authoritative clock
  - 0026 zero-seed、Django5.2组件12 passed、Portfolio migration no-drift；无current/activation，PG并发、owner producers与统一五源activation仍缺
- ✅ **Portfolio benchmark methodology bundle activation Domain 合同**
  - benchmark definition及固定顺序五源refs原子封存为单一bundle；server requester+第二staff双重非自批、root/predecessor successor与有效期闭合
  - 仅`benchmark_configuration_only`，daily valuation/Broker authority均false；Application/ledger/current provider与staff composition仍未完成
- ✅ **Portfolio benchmark methodology bundle activation Application workflow**
  - ID-only注册/审批以单一cutoff首末双读definition和五源graph，actor-bound first-winner、同definition logical head与predecessor CAS闭合
  - exact/current读拒绝superseded或source替换；仅Protocol+pure fake，ledger、owner current readers、staff composition与daily valuation仍未完成
- ✅ **Portfolio inactive approval authoritative persistence clock 修复**
  - subject/receipt显式封存`persisted_at=recorded_at`并增加DB等值约束，消除wall-clock导致合法记录自判腐败
  - Django5.2隔离5 passed、Portfolio migration no-drift；不改变inactive语义或连接Broker执行
- ✅ **Broker Plan→Order binding Application workflow**
  - ID-only注册在同一Broker cutoff双读plan ordinal row、inactive receipt和order artifact，闭合owner/type/hash/account/时钟及first-winner/CAS/current selector
  - 三个owner public reader、binding ledger/composition与真实签发均未实现；账户namespace blocker、pre-Risk与执行总闸继续关闭
- ✅ **Broker Plan→Order binding append-only ledger**
  - private UOW、四元logical subject root/predecessor CAS、canonical-v1 raw row bytes/hash与closed-world exact/PIT/current seals完成；0012 zero-seed
  - Django5.2 minimal round-trip通过；完整component/PG并发与owner readers/composition未完成，inactive/pre-Risk/执行总闸不变
- ✅ **Portfolio exact-active transition plan order owner reader**
  - ID-only plan/version/ordinal/PIT query由Portfolio owner发布canonical-v1 row bytes/hash、account与recorded/valid clock，不自行读取时钟
  - 仅Application Protocol；factory/composition、inactive receipt与Broker artifact ID-only owner readers仍缺，真实Plan→Order签发不可用
- ✅ **Portfolio inactive approval receipt ID-only owner reader**
  - ID-only receipt identity/PIT query重验receipt/subject/plan/account seals与issued=recorded clock，固定inactive/must-not-execute
  - 不替代hash-heavy历史审计，也不冒充logical current；owner factory/composition仍未接线
- ✅ **Broker order approval artifact ID-only owner reader**
  - ID-only artifact identity/PIT query保留approved/recorded双时钟并封存digest/risk-policy/order anchors，固定inactive
  - identity-winner infra/factory/composition未接；三源合同齐但Plan→Order真实双读/签发仍不可用
- ✅ **Plan→Order Portfolio owner reader adapters/composition**
  - plan复用owner exact provider，receipt仅暴露identity winner；read-only runtime/factory缺失fail-closed，不暴露writer或hash-heavy historical口
  - 纯/factory25 passed；Django ORM component、Broker runtime与跨App registry/真实三源签发仍未完成
- ✅ **Plan→Order Broker artifact owner adapter/composition**
  - closed-world sealed restore后按identity匹配，严格使用row recorded clock且不调用hash-heavy historical get_exact；只读factory无writer能力
  - Django5.2组件4 passed；跨App fail-closed registry/三源composition未接，inactive总闸不变
- ✅ **Portfolio planning policy definition Domain 合同**
  - 以policy identity、lot与五项exact Decimal、时钟和canonical hash冻结definition，明确排除mutable status/current/activation语义
  - legacy status=active不能成为benchmark或执行authority
- ✅ **Portfolio planning policy definition append-only ledger**
  - strict codec、私有UOW/claim、全写绕过阻断、identity/content/header/clock seal及closed-world exact PIT完成；0018 zero-seed且不回填legacy行
  - 完整manage.py drift因环境缺Celery、PostgreSQL并发未验；activation持久化/composition与legacy迁移仍未完成
- ✅ **Portfolio planning policy activation Domain 合同**
  - exact definition subject绑定server requester、definition identity/content/clock和前序hash，由第二名human staff按actor/user双重非自批签发configuration activation
  - 固定must-not-execute；ID-only workflow、activation账本/current provider、legacy迁移与benchmark composition仍未完成
- ✅ **Portfolio planning policy activation Application workflow**
  - ID-only注册/审批使用server actor/clock、definition/subject双读、first-winner与predecessor CAS；current reader拒绝superseded、过期和selector替换
  - 仅Protocol+pure fake；definition/activation持久化、真实composition、actor interface与PG并发仍未完成
- ✅ **Portfolio planning policy activation append-only ledger**
  - subject+activation双账本以私有UOW/claim、single-root/predecessor CAS、closed-world restore及FK/header/hash/clock seals闭合；过期head不回退
  - 0019 zero-seed；PG并发、完整manage.py drift、ruff、真实composition/actor与legacy迁移仍未完成
- ✅ **Account-owned account identity snapshot Domain 合同**
  - 分离字符串Account identity与底层整数unified provenance，封存source seal、owner/real/active、TTL最早有效期；legacy默认user必须有Account reclaim receipt
  - 固定inactive；trusted provider、ID-only发行/reclaim、append-only ledger/exact-current facade均未完成，不能解除namespace blocker
- ✅ **Account-owned raw identity source Domain 合同**
  - 字符串Account identity与整数underlying provenance不cast；row source与authoritative/legacy-default/unknown三态assignment evidence进入canonical seal
  - 固定source-evidence-only/inactive；capture workflow、ledger、simulated adapter与assignment provider未完成，默认user回填不得冒充owner事实
- ✅ **Account raw identity source Application workflow**
  - ID-only capture双读row observation和assignment evidence，以server actor/clock、first-winner/CAS封存authoritative或exact legacy source；unknown零写
  - 仅Protocol+pure fake；raw ledger、simulated adapter、assignment provider/composition未完成，Account snapshot与namespace binding仍不可真实签发
- ✅ **Account raw identity source append-only ledger**
  - private UOW/claim、assignment/actor/header seals、single-root/predecessor CAS与closed-world exact/PIT/current完成；0038 zero-seed/no-drift
  - Django5.2组件11 passed；真实migrate/PG并发与simulated adapter/assignment provider/composition仍缺，mutable row不得背书
- ✅ **Account identity snapshot Application workflow**
  - 普通Issue和legacy Reclaim均ID-only；raw/receipt双读、server actor/clock、first-winner/CAS及closed-current reader闭合，无exact reclaim receipt时零写入
  - 仅Protocol+pure fake；raw adapter、reclaim receipt/snapshot账本、composition、真实actor与PG并发仍未完成
- ✅ **Account identity snapshot append-only ledger**
  - actor/provenance/reclaim refs与全套seals、私有UOW/claim、single-root/predecessor CAS和closed-world exact/PIT/current闭合；0037 zero-seed不回填legacy行
  - Django5.2 minimal往返通过；完整组件/PG并发/full migrate未验，raw/reclaim owner provider与composition仍缺
- ✅ **Account owner assignment evidence Domain 合同**
  - canonical Account字符串身份与SimulatedTrading整数row provenance分离，精确绑定row observation与creation/migration/manual-reclaim receipt
  - claimant与独立human-staff approver两人制；固定inactive/evidence-only，Application/ledger/provider/人工入口仍未完成
- ✅ **Account raw-source assignment evidence 类型收口**
  - authoritative与legacy-default只接受正式`account_owner_assignment_evidence`，由state区分，不允许adapter改写旧legacy类型
  - Domain/Application/ORM/0038同步收紧且纯测试40 passed；无exact provenance仍零写，Django migration/component待复跑
- ✅ **Account owner assignment 两阶段 Application workflow**
  - ID-only注册/审批；claimant只来自exact Account provenance receipt，approver只来自当前staff actor，单事务单时钟双读并把subject seal绑定进最终Evidence
  - first-winner/CAS与exact/current reader纯测试37 passed；ledger、owner receipt/provider、Simulated row adapter、composition/interface未完成，0013 legacy默认零写
- ✅ **Account owner assignment subject/evidence append-only ledger**
  - 两表精确封存row/provenance/claimant、OneToOne subject及subject hash；private UOW/claim、single-root/predecessor CAS和closed-world exact/PIT/current完成
  - 0039 zero-seed、Django5.2组件12 passed且Account migration no-drift；PG并发、owner receipt/provider、Simulated adapter、composition/interface仍未完成，保持inactive
- ✅ **Account physical account-row observation Domain 合同**
  - 精确封存Account字符串identity、Simulated整数row provenance和nullable user/type/active/row clock，永远不把当前row user解释为authoritative owner
  - raw-source/TTL最早有效期、successor与PIT final不回退闭合；固定inactive/evidence-only，capture workflow/ledger/provider和独立provenance receipts仍缺
- ✅ **Account physical account-row observation Application workflow**
  - 8字段ID-only capture以同一server cutoff双读raw row，actor-bound first-winner、logical-head/predecessor CAS与exact/current读闭合
  - nullable user/type/active/row clock保真且owner固定unknown；仅Protocol+pure fake，ledger、Simulated adapter/composition与provenance receipts仍缺
- ✅ **跨 App 决策读边界与模块循环收口**
  - Portfolio账户访问和legacy Broker Evidence均经app-neutral registry，provider缺失稳定fail-closed；Account冷启动移除Strategy静态依赖
  - module guard收紧为206 edges、0双向依赖、0循环组件且全预算绿色；默认环境缺Django/Celery/Playwright的完整回归仍列为未验证
- ✅ **Broker-owned broker account identity snapshot Domain 合同**
  - 封存Broker账户、Account exact source、binding/Agent owner seal与keyed QMT reference digest；Account字符串与Broker整数身份不做cast，owner/real/active必须闭合
  - 固定inactive；Account facade、Broker raw provider/digest service、ID-only发行和ledger/current reader均未完成，namespace blocker不变
- ✅ **Broker account identity snapshot Application workflow**
  - ID-only发行双读Account exact source与Broker binding/Agent facts；QMT明文只进入注入的keyed digest服务，server actor、first-winner/CAS及closed-current闭合
  - 仅Protocol+pure fake；真实facade/raw provider、key service、账本/composition、actor与PG并发仍未完成，ruff未验证
- ✅ **Broker account identity snapshot append-only ledger**
  - actor/Account ref/binding/Agent/keyed digest与全套seals、私有UOW/claim、single-root/predecessor CAS及closed-world exact/PIT/current闭合；0010 zero-seed
  - Django5.2 minimal往返通过；完整组件/migration state/mypy/ruff、PG并发及真实provider/composition仍未完成

### 2026-07-08
- ✅ **发布后稳定化检查点更新**
  - live `healthcheck` 已恢复为全绿，`decision_data` 与 `alpha_workspace_consistency` 均为 `ok`
  - Alpha/workspace 口径统一到最近闭市日，避免盘中未闭市 cache 误判工作台 stale
  - P1 回归现已补跑通过：Alpha、Data Center、Risk Center、TUI/operator、governance
  - readiness evidence 现已引入正式 historical repair 路径：原始证据归档到 `_repair_archive/`，canonical 文件以 `trigger_source=repair` 重建且不计入 scheduler-clean
  - 当前剩余阻塞已收敛为 quote pre-readiness scheduler 连续性问题与后续真实运行窗口验证

### 2026-07-05
- ✅ **TUI 成为默认登录入口**
  - 根路径 `/` 改为默认进入 `/tui/`
  - 登录成功后的默认跳转从经典 `/dashboard/` 切到 `/tui/`
  - Setup Wizard 完成页同步把 `进入 TUI` 作为首选入口，并保留 `经典仪表盘`
  - `/dashboard/` 继续保留，作为经典 UI 的显式退出与回退入口

### 2026-06-20
- ✅ **TUI Workbench V2 经典 UI 平替**
  - `/tui/` 改为独立 DOS/PCTools 风格操作壳，不再作为旧 Django 页面 CSS 换肤或 API 目录
  - 运行时读取 `terminal_tui_metadata_registry` 已发布记录，缺省回退到 `config/tui/published/tui_operation_graph.published.json`
  - TUI metadata 已拆成 compact operation graph 与单独 evidence snapshot；运行时图不再内联 API/SDK/MCP/template 证据
  - 新增 `screen.default_action_key` 与 `screen.dashboard_panels`，支持经典页面打开即有内容、首页面板由已审核 action 组合
  - 普通用户界面隐藏 endpoint、method 与裸 JSON；Raw Response 仅保留在调试抽屉
  - 发布规模与 action 状态以 `config/tui/published/tui_operation_graph.published.json` 为机器产物，本索引不维护动态计数副本
  - API / SDK / MCP / template 编译证据以 TUI metadata 编译产物和治理基线为准；MCP live 数量统一读取 `governance/governance_baseline.json`

### 2026-04-24
- ✅ **人机协同决策分层文档**
  - 新增 `docs/business/human-judgment-decision-layering.md`
  - 明确 L0 数据与来源、L1 客观事实、L2 规则与信号、L3 解释与情景、L4 个人约束、L5 人工判断、L6 执行与复盘
  - 确立“客观底盘可复现，主观判断可追踪”的产品原则
  - 为后续 Investor Profile、Decision Memo、Override 留痕、反方观点和复盘机制提供业务边界

### 2026-03-28
- ✅ **Pulse 脉搏层模块文档补齐**
  - 发现 `apps/pulse/` 已完整实现但未被任何文档记录
  - 更新所有文档中的模块数量 (34 → 35)
  - Pulse 模块：战术层脉搏指标聚合与转折预警（4 维度：增长/通胀/流动性/情绪）
  - 被 `decision_rhythm`、`dashboard`、`regime` 模块依赖
  - 完整四层架构（Domain/Application/Infrastructure/Interface）
  - 4 个管理命令、2 个数据库迁移

### 0.7.0 (2026-03-23)
- ✅ **Setup Wizard 模块**
  - 新增 `apps/setup_wizard/` 模块（系统初始化向导）
  - 四层架构完整实现（Domain/Application/Infrastructure/Interface）
  - 首次安装引导：管理员密码 → AI Provider → 数据源
  - 已初始化系统需密码验证才能进入向导
  - 密码强度实时检查、进度条、步骤导航
  - 访问路径：`/setup/`
- ✅ **版本号规范化**
  - 统一版本号为 `0.7.0-build.20260323` 格式
  - 新增 `docs/VERSION.md` 版本管理规范
  - 新增 `core/version.py` 版本常量定义

### 2026-03-22
- ✅ **文档系统化对齐**
  - 更新模块数量 (32 → 34)，新增 ai_capability、setup_wizard 模块
  - 修复模块分类列表问题
  - 更新系统基线文档

### 2026-03-19
- ✅ **AI Capability Catalog 模块**
  - 新增独立 `apps/ai_capability/` 模块（系统级 AI 能力目录）
  - 四层架构完整实现（Domain/Application/Infrastructure/Interface）
  - 支持四种能力来源：builtin/terminal_command/mcp_tool/api
  - 统一路由 API：POST /api/ai-capability/route/
  - 自动采集全站 API 并进行安全分层（read_api/write_api/unsafe_api）
  - 完整 Admin 管理、审计日志、同步命令

### 2026-03-18
- ✅ **治理文档体系建立**
  - 新增 `docs/governance/` 治理文档目录（3个文件）
  - 删除冗余文档 5 个（SYSTEM_OVERVIEW.md 等）
  - 归档过程性文档 ~40 个到 `archive/`
  - 更新文档索引，建立三层文档体系

### 2026-03-17
- ✅ **Terminal CLI 模块**
  - 新增独立 `apps/terminal/` 模块（完整四层架构）
  - 支持两种命令类型：Prompt 模板调用、API 端点调用
  - 可配置命令系统（参数定义、JQ 过滤、输出格式）
  - 终端风格 AI 交互界面
  - 完整的 REST API 和 Admin 管理
  - AI 客户端已统一收敛到 `ai_provider`，命令数据模型已独立到 `terminal`

### 2026-03-11
- ✅ **估值修复策略参数配置系统**
  - 新增 Domain 层 `ValuationRepairConfig` dataclass（22 个参数）
  - 新增 DB 模型 `ValuationRepairConfigModel`（版本管理 + 激活机制）
  - 新增 Application 层配置工厂（缓存 + DB + Settings + 默认值优先级）
  - 新增 API 端点 5 个（active/list/create/activate/rollback）
  - 新增 Web UI 配置管理页面（`/equity/valuation-repair/config/`）
  - 新增 SDK/MCP 工具 5 个（get/list/create/activate/rollback_valuation_repair_config）
  - 新增配置文档（`docs/business/valuation-repair-config.md`）
  - 移除 Domain 层所有硬编码阈值

### 2026-03-02
- ✅ **估值定价引擎与执行审批闭环 - Phase 1 完成**
  - 新增 Domain 层实体: `ValuationSnapshot`, `InvestmentRecommendation`, `ExecutionApprovalRequest`
  - 新增 Domain 层服务: `ValuationSnapshotService`, `RecommendationConsolidationService`, `ExecutionApprovalService`, `ApprovalStatusStateMachine`
  - 新增 ORM 模型: `ValuationSnapshotModel`, `InvestmentRecommendationModel`, `ExecutionApprovalRequestModel`
  - 新增数据库迁移 0003
  - 新增 API 端点 7 个（估值重算、快照获取、聚合工作台、执行预览/审批/拒绝）
  - 添加单元测试 (14 个测试用例)
  - 更新文档索引

### 2026-03-01
- ✅ **首页主流程闭环改造 - SDK/MCP 同步**
  - 新增 `DecisionWorkflowModule` SDK 模块（precheck、beta gate、quota、cooldown 检查）
  - 扩展 `DecisionRhythmModule` SDK 模块（execute_request、cancel_request、get_request）
  - 新增 MCP 工具：`decision_workflow_precheck`、`decision_execute_request` 等
  - 更新 RBAC 权限：`decision_execute_request` 仅 admin/owner/investment_manager 可执行
  - 新增决策工作流使用指南文档
  - 更新 API 参考文档（决策工作流 API、决策执行 API）

### 2026-02-28
- ✅ **导航与文档口径同步**
  - 顶部导航文案统一为“我的投资账户”
  - API 文档入口收敛到“系统”菜单（去重）
  - 投资指挥中心左侧业务链接改为 Django `{% url %}` 反解
  - Policy 工作台入口统一为“政策/情绪/热点工作台”

### 2026-02-27
- ✅ **Policy + RSS + Hotspot/Sentiment 一体化工作台**
  - 实现双闸并行机制：Policy Gate (P0-P3) + Heat/Sentiment Gate (L0-L3)
  - 新增工作台 API 端点 9 个
  - 新增 Celery 定时任务 4 个
  - 新增测试用例 75 个（Domain/Application/API 三层覆盖）
  - 修复验收问题 6 个（P0-1 ~ P2-1）
  - 数据迁移含存量数据回填

### 2026-02-26
- ✅ **文档整理与归档**
  - 归档 20+ 过程性文档到 `archive/`
  - 整理模块文档结构
  - 新增 `QUICK_START.md` 快速启动指南
  - 更新模块数量（27 → 28，新增 `task_monitor`）
- ✅ Phase 3: 完善 RTM 和 CI 门禁
- ✅ 新增"主链路禁止 501"守护测试（8项静态检查）
- ✅ RTM Pending 项全部完成（R-SIG-001, R-AUD-001）
- ✅ **V3.4-RC2: RTM 关键项 100% 通过**

### 2026-02-24
- ✅ 执行全面测试（L0-L6 层级）
- ✅ 修复 DEF-001: `test_check_quota_exhausted` 竞态条件
- ✅ 修复 DEF-002: 22 个 API 路由命名规范问题
- ✅ **V3.4-RC1 通过 RC Gate**
- ✅ 更新测试策略文档和需求追踪矩阵

### 2026-02-21
- ✅ 新增 [外包团队工作指南](development/outsourcing-work-guidelines.md)

### 2026-02-20
- ✅ 架构修复：删除 `apps/shared/`，移动到 `shared/infrastructure/htmx/`
- ✅ 修复 `shared/` 对 `apps/` 的违规依赖（4处）
- ✅ 创建 `core/exceptions.py` 统一异常类
- ✅ Sentiment 模块完整路由配置
- ✅ AI Provider 模块 Application 层完善
- ✅ 新增 31 个单元测试，全部 1,395 测试通过

---

**文档维护**: AgomTradePro Team
**最后更新**: 2026-08-12
