# AgomTradePro 文档索引

> **AgomTradePro 0.8.0** - 个人投研平台
> **最后更新**: 2026-08-30
> **项目状态**: 生产验证进行中；关键决策与执行门禁仍 fail-closed
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
| 审核团队 | [reviews/README.md](reviews/README.md) | **候选 `36b72d2f` 的 AUD/DATA/TUI、EVID/STRAT 与 TAR-05 Terminal Runtime 审核入口、动态 JSON 清单、输入证据和报告输出地址** |
| FRP 三机部署 | [architecture/frp-vps-local-runtime-architecture.md](architecture/frp-vps-local-runtime-architecture.md) | VPS 入口 + 服务端 AI/Agent 薄客户端架构；QMT 外部券商桥另有本地执行例外 |

---

## 当前收口说明

- 2026-08-31 本个人项目的生效 [`single-owner 授权`](deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json) 允许唯一真人 owner 承担 owner/root/reviewer/role-owner，不要求第二名自然人；技术事实和 fail-closed 门禁不豁免。`TUI-01/TUI-03` 已完成，successor `80ea002b…` / release `20260830215638` 已部署，10/10 UAT、108/108 cleanup、isolated rollback 和 Day 0 registry backup 均通过。最新 [`retained observation checkpoint`](deployment/tui02-production-observation-checkpoint-2026-08-31-80ea002b.json) 将首个真实样本绑定为 `2026-08-30T15:09:35.034Z`，精确 14 日最早到 `2026-09-13T15:09:35.034Z`；`TUI-02=active`、readiness 仍为 `5/10 DENY`。
- 2026-08-31 [`AUD-03 successor 只读 checkpoint`](deployment/aud03-successor-production-readonly-checkpoint-2026-08-31-80ea002b.json) 将 Audit 运营证据重绑到同一 successor：496 migration 全 applied、Audit health=`200/OK`、outbox 六项为 0、Prometheus 12 条 alert rules 全健康且无 active alert，同候选 108/108 UAT 覆盖 10 个 Audit route。alerts/admin TUI 已可核验；recovery/archive 仍 unavailable，`AUD-03` 保持 fail-closed。
- 2026-08-31 [`AUD-04 repository closure`](testing/aud04-audit-archive-rehearsal-repository-closure-evidence-2026-08-31.json) 已补齐 scoped/candidate-revalidated 半开归档窗口、event/source/manifest/predecessor/replay hash、append-only artifact 与 `memory_only` exact replay；Audit 回归 `531 passed / 5 skipped`、架构/类型/治理全绿。该结果固定 non-production，未执行生产 archive/restore；`AUD-03` 的 recovery/archive 两节仍须真实取证。
- 2026-08-31 [`DATA-04 repository closure`](testing/data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json) 记录 successor PostgreSQL client saturation（database/ready/Audit health=`503`）并关闭两个代码根因：生产 Daphne/ASGI `CONN_MAX_AGE=0`，coverage-universe read 删除 `get_or_create`、缺配置 `MISSING_CONFIG`、仅显式 PUT/save 可初始化。该修复尚未部署，未终止 session/重启/写库/backfill；DATA-02 必须在 clean successor 上重验连接稳定、readiness 与 SELECT-only dry-run，候选变化同时重置 TUI-02 观察。
- 2026-08-31 [`DATA-05 repository closure`](testing/data05-financial-repository-owner-closure-evidence-2026-08-31.json) 已关闭 HEAD 上既有的 financial repository 243/200 行 CI blocker：原 owner 降至 189/200，availability owner 为 65/100，公开 class/facade identity 与 current-data 行为保持；组合相关回归 `70 passed`，没有抬预算或触碰生产。
- 2026-08-30 DATA-01 已在生产候选 `c826f741…` 完成新备份、sibling restore、`0072→0071→0072` 迁移往返、真实连接切换与切回；关键计数/WAL 一致，health=`200`、Celery=`1`，原决策门恢复为 `blocked`。四个原始证据见下方部署索引；`DATA-01=completed`，但不代表 DATA-02/03、AUD-03 或 decision-ready 通过。
- 2026-08-30 DATA-02 四类原子全-universe Publication 与当前事实修复候选已实现；生产只读 provider preflight 为 Tencent failover `5,533/5,533`、全部绑定 `2026-08-28`、OHLC 缺口 `0`。DATA-03 同候选增加三检查 + CAS + 自动 re-block 激活包装器，并禁止通用命令裸写 `active`。下一步是部署后 dry-run、真实缺口修复和逐数据集 reconciliation；持久化决策门此前继续 fail-closed。
- 2026-08-24 EVID-01 最新候选只读复核：候选 `94abd76e…` 的 health/ready/audit 为 `200`、decision-ready 为 `503` fail-closed，`0055`/`0029` 已应用且 13 张 authority/evidence 表全零；快照 [`evid-01-authority-inventory-snapshot-2026-08-24-recheck-2105.json`](deployment/evid-01-authority-inventory-snapshot-2026-08-24-recheck-2105.json)，report [`39760173ab5aa8e4adfab03d088c62519e22e5b6cea40d78eaf2d5d0befd6372.json`](deployment/evid-01-authority-inventory/39/39760173ab5aa8e4adfab03d088c62519e22e5b6cea40d78eaf2d5d0befd6372.json)；`authority_ready=false`、`production_claim=false`，不解除 EVID-01 或全局决策/执行总闸。
- 2026-08-24 DATA-03 认证 canonical Data Center smoke：同一候选 `94abd76e…` / release `20260824133504` 上，认证 `/api/ready/`=`200`、`/api/decision-ready/`=`503` 且 `must_not_use_for_decision=true`；providers=`200` 返回 2 条脱敏记录，provider status=`200` 但 15 条 capability 中 8 条仍 `must_not_use_for_decision=true`，含 `stale/degraded`，故 smoke 失败而非误报通过。快照 [`data03-readiness-authenticated-smoke-2026-08-24-1335.json`](deployment/data03-readiness-authenticated-smoke-2026-08-24-1335.json)，报告 [`55f20b1348564daf6dea93f23aecc229953954e6fcc1859f40180fbebea84d98.json`](deployment/data03-readiness/55/55f20b1348564daf6dea93f23aecc229953954e6fcc1859f40180fbebea84d98.json)；仅只读观察，不解除 DATA-02/DATA-03、M9/M10 或决策总闸。
- 2026-08-24 DATA-02 当前候选 `fund.nav` SELECT-only reconciliation：当前候选 `94abd76e…` / release `20260824133504` 内，`fund_net_value` 与 canonical `data_center_fund_nav_fact(source=fund_legacy_repo)` 各 `7,648` 条，snapshot hash 相同，`same=7,648`、差异/缺陷均为 `0`。原始 envelope [`data02-reconciliation-candidate-2026-08-24.json`](deployment/data02-reconciliation-candidate-2026-08-24.json)，canonical artifact [`65935870cc4002c1e96fb0ab2473ee679b6b1540318aa72f2155a95d47db43dc.json`](deployment/data02-reconciliation/65/65935870cc4002c1e96fb0ab2473ee679b6b1540318aa72f2155a95d47db43dc.json)；这是单 dataset/单快照证据，仍 `production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`，不解锁 DATA-02/03 或 decision-ready。

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
| [adr-0008-terminal-agent-runtime-boundary.md](architecture/adr-0008-terminal-agent-runtime-boundary.md) | **ADR：Terminal Agent 多用户运行时边界与 queued composition contract** | 2026-08-18 TAR-01~04 repository 合同已完成；TAR-05 等待生产 provider、容量、混沌、恢复与观测验收 |
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
| [frp-vps-local-runtime-architecture.md](architecture/frp-vps-local-runtime-architecture.md) | 三机架构方案：VPS FRP 转发 + 服务端 AI/Agent 与 B/S 薄客户端；仅 QMT 外部券商桥允许本地执行 | ✅ 2026-03-08 新增 |
| [frontend_design_guide.md](architecture/frontend_design_guide.md) | 前端设计指南 | ✅ 2026-02-20 更新 |
| [ui_ux_design_tokens_v1.md](architecture/ui_ux_design_tokens_v1.md) | UI/UX 设计 Token 规范 v1.0 | ✅ 完成验收 |
| [routing_naming_convention.md](architecture/routing_naming_convention.md) | 路由命名规范 | ✅ 完成验收 |

### 2. 业务逻辑 (`business/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [AgomTradePro_V3.4.md](business/AgomTradePro_V3.4.md) | 核心业务需求文档（2650行） | 最新 |
| [human-judgment-decision-layering.md](business/human-judgment-decision-layering.md) | **人机协同决策分层：客观底盘、系统解释、个人约束、人工判断与复盘** | ✅ 2026-04-24 新增 |
| [strategy-research-capability-roadmap-memo-2026-08-04.md](business/strategy-research-capability-roadmap-memo-2026-08-04.md) | **策略研究长期能力备忘（经营驱动、资金结构、高频宏观因子、宏观风险平价、固收相对价值及启动门禁）** | 备忘，按前置条件启动 |
| [STRAT-01 R1–R8 业务定义包](business/strategy-research/strat-01/README.md) | **八项策略研究能力的 owner、scope、calendar、sample、qualification、证伪与生命周期定义** | ✅ 2026-09-01 待 owner 签署 |
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
| [codex-autonomous-goal-usage.md](development/codex-autonomous-goal-usage.md) | **Codex 自主 Goal 启动、Sol/Luna 调度、worktree、计划回写与恢复备忘** | ✅ 2026-08-25 新增 |
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
| [active_plan_registry.json](../governance/active_plan_registry.json) | **活跃计划与 canonical closure backlog 机器真源（工作流 / owner / 状态 / 依赖 / 唯一退出门 / 文件归属 / 限期审查）** | v27 共 33 units；`DATA-04/DATA-05/AUD-04=completed`、当前 focus 显式为 null；DATA-02 等待修复候选部署与重验，其他 DATA/AUD/EVID/STRAT/TAR 门保持 fail-closed |
| [release-blocker-closure-execution-plan-2026-08-29.md](plans/release-blocker-closure-execution-plan-2026-08-29.md) | **发布阻塞清零综合实施方案（DATA/AUD/EVID/STRAT/TUI/TAR/AI/QMT 顺序、授权包、回滚点和停止线）** | 执行中；DATA-01/DATA-04 repository exit 完成，线上 PostgreSQL incident 尚未恢复；DATA-02 等 clean deploy/readiness/SELECT-only dry-run，候选变更重置 TUI-02 观察，其余硬门保持 fail-closed |
| [scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md](plans/scenario-governance-and-strategy-method-quick-wins-plan-2026-08-04.md) | **情景硬编码治理、动态/参数/宏观情景、AI MCP 受控修改及策略方法 Quick Wins（M0-M6）** | 提案，待评审实施 |
| [strategy-research-capability-completion-audit-2026-08-05.md](plans/strategy-research-capability-completion-audit-2026-08-05.md) | **策略研究 R1—R8 完成度审计、真实数据阻断与无数据开发队列** | 实施中；无 P0，剩余 P1 分批收口 |
| [sentiment-awareness-enhancement-plan-2026-07-31.md](archive/plans/sentiment-awareness-enhancement-plan-2026-07-31.md) | **A 股情绪态势感知增强计划（S0-S4，交易行为情绪指标 / Pulse sentiment 维度 / 文本情绪打通 / TUI 情绪面板）** | ✅ 已完成并归档 |
| [web-to-tui-migration-plan-2026-07-25.md](plans/web-to-tui-migration-plan-2026-07-25.md) | **Web 界面 → TUI 整体迁移计划（M0-M5，195 模板去向矩阵 / 图表样板 / web 保留清单）** | 实施中；M0-M4、TUI-01/TUI-03 完成；TUI-02 retained sample 已 hash-bound，精确时间门运行中且 final inventory DENY |
| [web-to-tui-m0-evidence-2026-07-26.md](archive/plans/web-to-tui-m0-evidence-2026-07-26.md) | **Web → TUI M0/M0-D 证据（195 模板矩阵、7 个死模板清理、冻结门与双端基线）** | ✅ M0/M0-D 已完成并归档 |
| [web-to-tui-m1-chart-evidence-2026-07-26.md](archive/plans/web-to-tui-m1-chart-evidence-2026-07-26.md) | **Web → TUI M1 图表样板证据（portable chart 契约、多序列/采样/可访问性、双端门禁）** | ✅ M1 已完成并归档 |
| [web-to-tui-m2-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m2-consolidated-evidence-2026-07-26.md) | **Web → TUI M2 合并证据（W1-W20，15 份原始 wave 记录与 SHA-256 清单）** | ✅ M2 已完成并归档 |
| [web-to-tui-m3-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m3-consolidated-evidence-2026-07-26.md) | **Web → TUI M3 合并证据（W21-W42，22 份原始 wave 记录与 SHA-256 清单）** | ✅ M3 已完成并归档 |
| [web-to-tui-m4-consolidated-evidence-2026-07-26.md](archive/plans/web-to-tui-m4-consolidated-evidence-2026-07-26.md) | **Web → TUI M4 合并证据（W43-W51，9 份原始 wave 记录与 SHA-256 清单）** | ✅ M4 已完成并归档 |
| [web-to-tui-m5-readiness-2026-07-27.md](plans/web-to-tui-m5-readiness-2026-07-27.md) | **Web → TUI M5 Readiness（14 日兼容期、UAT、telemetry 与回滚演练门禁）** | ⛔ 当前 `5/10 DENY`；candidate `80ea002b…` / `20260830215638` 的 UAT、cleanup、rollback、retained source 与 Day 0 backup 已通过，等待 `2026-09-13T15:09:35.034Z` 后的 v2 structured telemetry/defect、formal backup/review 和 single-owner attestations |
| [web-to-tui-m5-production-preflight-2026-07-28.md](plans/web-to-tui-m5-production-preflight-2026-07-28.md) | **Web → TUI M5 生产 Preflight（只读健康、release/commit 与候选差异核查）** | 历史只读记录；不代表 2026-08-13 当前线上版本，不计入 cutover gate |
| [web-to-tui-m5-production-preflight-2026-08-13.md](plans/web-to-tui-m5-production-preflight-2026-08-13.md) | **Web → TUI M5 生产 Preflight（公开探针 + release/OCI 核对）** | 历史只读候选记录：`20260816223921` / `443658d33159`；当前运行候选以最新 deployment evidence 与 registry 绑定为准。M5 仍 DENY，角色化 UAT、观察窗口和写后审计待补 |
| [web-to-tui-m5-rollback-drill-evidence-2026-07-27.md](plans/web-to-tui-m5-rollback-drill-evidence-2026-07-27.md) | **Web → TUI M5 回滚演练（隔离 reverse/restore、旧 graph 兼容与 registry 回滚发布）** | 历史记录不再算当前闸门；candidate-bound 本地演练已修复，最终候选/生产备份恢复待验 |
| [web-to-tui-m5-browser-uat-evidence-2026-07-27.md](plans/web-to-tui-m5-browser-uat-evidence-2026-07-27.md) | **Web → TUI M5 浏览器 UAT（角色边界、矩阵深链、直读/参数读取与生命周期）** | 历史自动化 15/15、主任务 108/108；未绑定最终候选，当前 gate FAIL |
| [web-to-tui-m5-route-closure-evidence-2026-07-27.md](plans/web-to-tui-m5-route-closure-evidence-2026-07-27.md) | **Web → TUI M5 逐 Route 清理证据（认证边界、兼容目标与状态/回滚范围）** | ✅ 六类 scope 均为 108/108；不替代生产门禁 |
| [tui-regime-display-contract-postmortem-2026-07-30.md](archive/plans/tui-regime-display-contract-postmortem-2026-07-30.md) | **TUI Regime 有数据未显示复盘（契约漂移、fail-closed 与跨层回归门禁）** | ✅ 整改完成并归档，持续执行门禁 |
| [qmt-live-trading-bridge-plan.md](plans/qmt-live-trading-bridge-plan.md) | **QMT 本地执行桥与 VPS 实盘交易接入计划（Web / TUI / MCP / 权限 / 风控 / 对账）** | 仅 QMT 外部券商桥允许本地执行；仓库 MVP 已实现，待目标券商 Phase 0 与仿真实测 |
| [tui-usability-and-metadata-governance-plan-2026-08-18.md](plans/tui-usability-and-metadata-governance-plan-2026-08-18.md) | **TUI 可用性与 metadata 治理整改（加载回退 / 三真源合一 / auto action 文案重写 / IA 整理 / 布局收口，TUX-01~05）** | TUX-01~05 repository exit gate 已完成；TUX-05 的布局、字段翻译、内部 key/状态栏、freshness 呈现与 8 屏证据已闭合，外部/M5 生产证据仍独立 fail-closed |
| [terminal-agent-multi-user-runtime-plan-2026-08-18.md](plans/terminal-agent-multi-user-runtime-plan-2026-08-18.md) | **Terminal Agent 多用户队列、专用 Worker、可恢复事件流与服务端 AI/Agent 薄客户端整改（TAR-01~05）** | TAR-01~04 repository 合同已完成；当前转入 TAR-05 生产 provider、容量、混沌、恢复与观测验收，TAR-05 通过前保持 inline 并发 1；普通用户不安装本地 Agent/provider |
| [adr-0002-qmt-local-execution-bridge.md](architecture/adr-0002-qmt-local-execution-bridge.md) | QMT 本地 Agent + VPS 控制面架构决策 | 已接受 |
| [qmt-agent-runbook.md](operations/qmt-agent-runbook.md) | Windows QMT Agent 安装、分级启用、停止与故障处理 | 可执行 |
| [qmt-agent-local-install-package.md](operations/qmt-agent-local-install-package.md) | 国金普通 QMT `userdata` 本地 Agent ZIP 安装包、DPAPI Token、权限诊断与卸载 | 可执行 |
| [research-integrity-and-decision-reproducibility-2026-07-21.md](plans/research-integrity-and-decision-reproducibility-2026-07-21.md) | **研究可信度、组合构建与决策复算整改（M0-M6）** | 开发中：canonical schema/API 已落地，切换门禁默认关闭 |
| [qmt-agent-v1.schema.json](api/qmt-agent-v1.schema.json) | QMT Agent v1 请求契约 JSON Schema 文档投影 | DRF Serializer 为运行时真源 |
| [tui-ia-consolidation-2026-07-20.md](archive/plans/tui-ia-consolidation-2026-07-20.md) | **TUI 信息架构重构计划（普通用户 13 屏 / 管理员 16 屏，8 步决策流，权限分层）** | ✅ 2026-07-21 已实施并归档 |
| [agomtui-portability-remediation-2026-07-21.md](plans/agomtui-portability-remediation-2026-07-21.md) | **AgomTUI 可移植性整改方案（Runtime 单向同步、schema 兼容、宿主接入与双端门禁）** | 待批准；AgomTradePro 已补 static-vs-runtime actionability guard，AgomTUI 外部 validator 与双端门禁仍待 |
| [uat-remediation-2026-07-20.md](plans/uat-remediation-2026-07-20.md) | **外部 UAT 复核、代码整改与生产数据恢复边界** | 进行中：代码整改完成，待生产发布与数据回填 |
| [implementation-progress-summary.md](plans/implementation-progress-summary.md) | **总体进度总结（Phase 1-5 完成）** | 最新 |
| [AI-native-blueprint-260315.md](plans/AI-native-blueprint-260315.md) | **AI Native 升级蓝图** | 进行中 |
| [AI-Native-upgrade-implement-plan-260315.md](plans/AI-Native-upgrade-implement-plan-260315.md) | **AI Native 升级实施计划** | 进行中 |
| [ai-native/README.md](plans/ai-native/README.md) | **AI Native 子项目索引** | 进行中 |
| [ai-native/execution-backlog.md](plans/ai-native/execution-backlog.md) | **AI Native 执行积压** | 进行中 |
| [eastmoney-integration.md](archive/plans/eastmoney-integration.md) | **东方财富数据源集成计划** | ✅ 已实施并归档 |
| [production-code-remediation-plan-2026-06-26.md](archive/plans/production-code-remediation-plan-2026-06-26.md) | **投产代码整改方案（数据守门 / 初始化 / UI 闭环）** | ✅ 2026-06-26 完成并归档 |
| [0.8.0-release-closure-plan-2026-07-05.md](archive/plans/0.8.0-release-closure-plan-2026-07-05.md) | **0.8.0 收口开发计划（发布 / 运维 / 架构减债 Top 10）** | ✅ 2026-07-05 已执行并归档 |
| [post-0.8.0-stabilization-priority-2026-07-08.md](archive/plans/post-0.8.0-stabilization-priority-2026-07-08.md) | **0.8.0 发布后两周稳定化实施清单（优先级 / 负责人 / 命令 / 验收）** | ✅ 已归档；未完成生产门禁已转入当前 Data / Strategy / Evidence / TUI 工作流 |
| [evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md](plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md) | **证据治理与决策硬闸改造计划** | 第一期 P0：代码侧 immutable owner/tenant authority lifecycle、same-alias selector/writer composition 与 Evidence boundary 已落盘；受控候选 `94abd76e…` / release `20260824133504` 已应用 `0055`/`0029`，但 13 张 authority/evidence 表仍 zero-seed；仍缺真实独立 root approval、PG first-winner/successor/revocation/rollback、生产 route/writer 与双签，所有执行总闸保持关闭，MCP integrated=0 |
| [system-audit-log-consolidation-plan-2026-08-13.md](plans/system-audit-log-consolidation-plan-2026-08-13.md) | **系统级统一审计日志收口计划（统一事件账本 / 数据可靠性纵向链 / 指标告警 / TUI 观测）** | AUD-01/AUD-02/AUD-04 repository exit 已完成；归档/隔离恢复软件合同已就绪但未执行生产，AUD-03 剩余 authority/profile、writer smoke、rollback/recovery、获批 archive/restore 与 single-owner 最终确认 |
| [mcp-consolidation-remediation-plan-2026-07-09.md](archive/plans/mcp-consolidation-remediation-plan-2026-07-09.md) | **MCP 收口整改计划（统一能力注册、统一调用、legacy 退役）** | ✅ 完成并归档；持续状态由机器门禁维护 |
| [system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md](archive/plans/system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md) | **系统级 AI Capability Catalog 与统一路由任务书** | ✅ 代码与自动化验收完成并归档 |
| [terminal-mcp-governance-outsourcing-task-book-2026-03-19.md](archive/plans/terminal-mcp-governance-outsourcing-task-book-2026-03-19.md) | **Terminal MCP 治理与确认机制任务书** | ✅ 已实现并由 AgentProposal 持久审批架构承接 |
| [terminal-refactor-plan-260709.md](archive/plans/terminal-refactor-plan-260709.md) | **Terminal Agents SDK + MCP 重构计划** | ✅ Agents SDK、SSE、MCP 与持久审批完成并归档 |
| [auto-advisor-prd-2026-06-25.md](archive/plans/auto-advisor-prd-2026-06-25.md) | **账户级自动投顾 PRD（持仓驱动 + 建议订单清单）** | ✅ Implemented v1，已归档 |
| [auto-advisor-implementation-2026-06-25.md](archive/plans/auto-advisor-implementation-2026-06-25.md) | **账户级自动投顾实施文档（后端/Classic UI/TUI/测试）** | ✅ Implemented v1，已归档 |
| [personal-auto-advisor-roadmap-2026-06-30.md](archive/plans/personal-auto-advisor-roadmap-2026-06-30.md) | **个人自用自动投顾增强路线图（风控 / 数据新鲜度 / 决策卡片 / 复盘）** | ✅ Implemented v1，已归档 |
| [macro-sizing-multiplier-outsourcing-2026-03-31.md](archive/plans/macro-sizing-multiplier-outsourcing-2026-03-31.md) | **宏观感知仓位系数模块外包任务书（Regime+Pulse+回撤三因子）** | ✅ 实现资产已归档；source freshness、config/version/hash、owner scope 与 exact-current 残余验收转入 Evidence `EVID-03` |
| [streamlit-dashboard-upgrade-plan.md](archive/plans/streamlit-dashboard-upgrade-plan.md) | Streamlit 仪表盘交互升级方案（兼容 sidecar 历史计划） | ✅ 2026-08-15 已归档；当前用户任务由 TUI 承接 |
| [account-performance-260401.md](archive/plans/account-performance-260401.md) | 统一账户业绩与估值历史实施计划 | ✅ 2026-08-15 已归档；生产 owner scope、freshness/hash 与 PostgreSQL 验收转入 Evidence |
| [account-refactor-260327.md](archive/plans/account-refactor-260327.md) | 真实仓/模拟仓统一账本历史实施计划 | ✅ 2026-08-15 已归档；legacy 迁移、owner/provenance 与回滚转入 Evidence/Data 门禁 |
| [admin-settings-closure-260404.md](archive/plans/admin-settings-closure-260404.md) | 设置中心与管理控制台 Classic 收口计划 | ✅ 2026-08-15 已归档；角色 UAT、观察与清理转入 Web→TUI M5 |
| [alpha-exit-loop-2026-04-30.md](archive/plans/alpha-exit-loop-2026-04-30.md) | Alpha BUY→TRACK→SELL 退出闭环方案 | ✅ 2026-08-15 已归档；Strategy/Evidence 继续管理生产证明 |
| [alpha-homepage-upgrade-260416.md](archive/plans/alpha-homepage-upgrade-260416.md) | 账户驱动 Alpha 首页历史方案 | ✅ 2026-08-15 已归档；首页/TUI 迁移与 PIT/OOS 归入现有门禁 |
| [workflow-upgrade-260326.md](archive/plans/workflow-upgrade-260326.md) | 决策工作台 Transition Plan 历史设计 | ✅ 2026-08-15 已归档；当前真源为 Decision Workspace/Evidence 文档 |
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
| [critical-reliability-test-closure-2026-07-22.md](plans/critical-reliability-test-closure-2026-07-22.md) | **数据到对账关键可靠性测试与发布门禁收口记录** | ✅ SQLite + GitHub PostgreSQL Nightly 已取证；生产 QMT 仍受外部权限阻断 |
| [smart-test-selection.md](development/ci/smart-test-selection.md) | **增量测试映射、未知 App 全量回退与关键集合选择规则** | ✅ 2026-07-22 更新 |
| [coverage-governance.md](development/ci/coverage-governance.md) | **多范围行/分支覆盖率真源、报告与 ratchet 规则** | ✅ 2026-07-24 新增 |
| [celery-task-contract-guard.md](development/celery-task-contract-guard.md) | **Celery 技术状态、业务 outcome 与关键任务测试契约门禁** | ✅ 已纳入 fast feedback |
| [data-freshness-contract-guard.md](development/data-freshness-contract-guard.md) | **当前数据 observation/freshness/failover/决策阻断契约门禁** | ✅ 已纳入 consistency check |
| [postmortem-realtime-stale-market-summary-2026-07-30.md](development/postmortem-realtime-stale-market-summary-2026-07-30.md) | **VPS Terminal 旧行情冒充当前值事故复盘与防复发矩阵** | ✅ 2026-07-30 完成 |
| [vps-uat-e2e-findings-2026-07-31.md](development/vps-uat-e2e-findings-2026-07-31.md) | **VPS UAT / E2E / MCP 生产问题清单（先冻结问题，再逐项修复与复测）** | ✅ 2026-07-31 完成 |
| [personal-investment-readiness-2026-06-30.md](testing/personal-investment-readiness-2026-06-30.md) | **个人投研系统可用性验收记录（readiness / Qlib / Alpha / 决策数据 / 连续运行证据）** | ✅ 2026-06-30 更新 |
| [0.8.0-release-regression-report-2026-07-05.md](testing/0.8.0-release-regression-report-2026-07-05.md) | **0.8.0 发布回归报告（版本 / TUI / 治理 / readiness）** | ✅ 2026-07-05 新增 |
| [post-0.8.0-stabilization-checkpoint-2026-07-08.md](testing/post-0.8.0-stabilization-checkpoint-2026-07-08.md) | **0.8.0 发布后稳定化检查点（live health / 回归 / readiness 阻塞项）** | ✅ 2026-07-08 新增 |
| [aud04-audit-archive-rehearsal-repository-closure-evidence-2026-08-31.json](testing/aud04-audit-archive-rehearsal-repository-closure-evidence-2026-08-31.json) | **AUD-04 候选绑定归档、append-only artifact 与内存隔离恢复 repository closure 证据** | ✅ 2026-08-31；仅 repository 能力，不是生产 archive/restore 验收 |
| [data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json](testing/data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json) | **DATA-04 PostgreSQL client saturation 只读事实、ASGI 连接生命周期与 SELECT-only preview repository closure 证据** | ✅ 2026-08-31 repository exit；修复未部署，生产恢复与 DATA-02 重验待执行 |
| [data05-financial-repository-owner-closure-evidence-2026-08-31.json](testing/data05-financial-repository-owner-closure-evidence-2026-08-31.json) | **DATA-05 Financial availability owner 拆分、结构预算与兼容回归 closure 证据** | ✅ 2026-08-31；243/200 既有 CI blocker 已关闭，未触碰生产 |
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
| [data01-live-rehearsal-c826f741-baseline.json](deployment/data01-live-rehearsal-c826f741-baseline.json) | DATA-01 sibling restore 的 542 表、72 migration、463 sequence 与 schema/content hash 基线 | ✅ 2026-08-30 |
| [data01-live-rehearsal-c826f741-migration-roundtrip.json](deployment/data01-live-rehearsal-c826f741-migration-roundtrip.json) | DATA-01 `0072→0071→0072` 原始迁移往返差异报告 | ✅ 2026-08-30 |
| [data01-live-rehearsal-c826f741-migration-classification.json](deployment/data01-live-rehearsal-c826f741-migration-classification.json) | DATA-01 对 `django_migrations` 正常 ledger/sequence 增量的分类证明，业务/schema 一致 | ✅ 2026-08-30 |
| [data01-live-rehearsal-c826f741-connection-switch.json](deployment/data01-live-rehearsal-c826f741-connection-switch.json) | DATA-01 真实 Web 连接切换/切回、RTO、关键计数/WAL 与健康检查证据 | ✅ 2026-08-30 |
| [VPS_BUNDLE_DEPLOYMENT.md](deployment/VPS_BUNDLE_DEPLOYMENT.md) | VPS Bundle 一体化部署与迁移指南（含 Postgres/Redis 迁移） | ✅ 新增 |
| [M5_OBSERVATION_BINDING_GUIDE.md](deployment/M5_OBSERVATION_BINDING_GUIDE.md) | M5 observation 候选绑定位置、命令、重置规则与验证方法 | ✅ 2026-08-19 新增 |
| [personal-project-single-owner-authorization-2026-08-30-80ea002b.json](deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json) | 唯一真人 owner 对 successor remediation、生产验收和同一人多治理角色的生效授权；不豁免技术门 | ✅ 2026-08-30 |
| [tui02-production-day0-checkpoint-2026-08-30-80ea002b.json](deployment/tui02-production-day0-checkpoint-2026-08-30-80ea002b.json) | TUI-02 successor deployment、retained source、UAT、cleanup、rollback、registry backup 与 5/10 readiness 的 Day 0 汇总 | ✅ 2026-08-30 |
| [tui02-production-observation-checkpoint-2026-08-31-80ea002b.json](deployment/tui02-production-observation-checkpoint-2026-08-31-80ea002b.json) | TUI-02 candidate/Prometheus 无漂移只读复核、首个 retained raw sample 与精确 14 日 eligible instant | ⏳ 2026-08-31；窗口运行中 |
| [vps-deployment-evidence-2026-08-15.md](deployment/vps-deployment-evidence-2026-08-15.md) | 候选部署、provenance、备份与运行复核证据（最新 Web→TUI successor `80ea002b…` / `20260830215638`） | ✅ 动态更新至 2026-08-30 |
| [web-to-tui-deployment-preflight-20260816223921.json](deployment/web-to-tui-deployment-preflight-20260816223921.json) | `443658d33159` / `20260816223921` 候选 deployment preflight、OCI/source/health/ready 绑定 | ✅ 2026-08-16 |
| [vps-runtime-verification-2026-08-16-2258.json](deployment/vps-runtime-verification-2026-08-16-2258.json) | `443658d33159` / `20260816223921` 候选只读 release/health/container/Qlib/Celery 复核 | ✅ 2026-08-16 |
| [evid-01-authority-inventory-2026-08-16-2258.json](deployment/evid-01-authority-inventory-2026-08-16-2258.json) | `443658d33159` / `20260816223921` 候选只读 authority migration/zero-seed inventory；EVID-01 guard 动态核对当前 registry/preflight/runtime binding | ✅ 2026-08-17 |
| [vps-postgres-backup-verification-2026-08-16-2348.json](deployment/vps-postgres-backup-verification-2026-08-16-2348.json) | `443658d33159` / `20260816223921` 候选 PostgreSQL custom-format 备份下载、尺寸与 SHA-256 复核（未恢复） | ✅ 2026-08-16 |
| [evid-01-authority-inventory-2026-08-16.json](deployment/evid-01-authority-inventory-2026-08-16.json) | e167 候选只读 authority migration/zero-seed inventory | ✅ 2026-08-16 |
| [evid-01-authority-inventory-snapshot-2026-08-23-0810.json](deployment/evid-01-authority-inventory-snapshot-2026-08-23-0810.json) | 候选 `4cef9040cccc...` 的 PostgreSQL authority 只读快照：0050–0053 已应用、12 张 authority/evidence/root-lock 表全零；经离线 normalizer 生成 content-addressed report `3900c08b9054...` | ✅ 2026-08-23 |
| [vps-runtime-verification-2026-08-16-1811.json](deployment/vps-runtime-verification-2026-08-16-1811.json) | `5a13125bb84e` / `20260816181141` 候选只读 release/health/container/Qlib/Celery 复核 | ✅ 2026-08-16 |
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

## 2026-08-16 历史收口快照

- 计划与机器状态的唯一导航入口是 [`docs/plans/README.md`](plans/README.md) 与 [`governance/active_plan_registry.json`](../governance/active_plan_registry.json)；本索引不复制动态 closure 数字。
- AUD-01 的 durable-publisher preflight contract 与 release identity guard 曾合入候选 `443658d33159dd80a35b3001ae2c8505113e3fff` / `20260816223921`；远端只读运行证据见 [`vps-runtime-verification-2026-08-16-2258.json`](deployment/vps-runtime-verification-2026-08-16-2258.json)。
- EVID-01 当时的 authority inventory 绑定同一候选，12 个 authority/evidence 表为零；该历史快照不代表当前代码侧 authority lifecycle 或生产 seed 已完成。
- 该候选的健康、迁移、schema、TUI registry、Qlib、Celery 与 HTTPS 复核不解除角色化浏览器 UAT、写后 receipt/refresh、14 日 telemetry、生产 publisher/authority、数据恢复/回滚与 QMT/AI 外部验收。

## 2026-08-24 历史验收状态（当日快照）

- 代码验收候选为 `b779d4eaf21f9dbf3972191b8f4c4508bb3851ed`；随后部署绑定的候选为 `94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / release `20260824133504` / image `sha256:1c560b5fed14964a008c278a88d9f3e3b144444a172ecc239d06cedbd76d6a3e`。本地验收基线 `95618f840c60ab545b9c194d3fe981e8c8aaed0e` 相对该 VPS 候选仅新增部署/计划/治理证据文档，无生产代码差异；截至当前 HEAD `5c6e4da5087c39ccdbaa612f6599a0b3b392f0a8`，`git diff --name-only 94abd76e..HEAD` 共 31 个文件，全部为 `docs/`、`governance/` 或 `.gitleaks.toml`，`apps/`、`config/`、`core/`、`scripts/`、`tests/` 均为 0，故仍不触发重复部署。候选的四条 push CI、部署 verifier、备份、迁移/schema、TUI registry、Qlib、Celery、Caddy/TLS 全通过。结构化验收见 [`tar01-current-vps-deployment-acceptance-2026-08-24-94abd76e.json`](deployment/tar01-current-vps-deployment-acceptance-2026-08-24-94abd76e.json)。
- `0055_owner_tenant_authority_v1` 与 Research `0029` 已由正常部署迁移应用；同一 `default` PostgreSQL alias 的 13 张 authority/evidence 表全部为 `0` 行，EVID-01 post-0055 inventory 报告为 `blocked_zero_seed_authority`、`authority_ready=false`、`production_claim=false`、`runtime_enablement=not_authorized`（快照 [`evid-01-authority-inventory-snapshot-2026-08-24-post-0055.json`](deployment/evid-01-authority-inventory-snapshot-2026-08-24-post-0055.json)，报告 [`55bb41f6129c30d42c8ec3041bc4e90b4ae5064e29409b83d8df6ea86bb7d680.json`](deployment/evid-01-authority-inventory/55/55bb41f6129c30d42c8ec3041bc4e90b4ae5064e29409b83d8df6ea86bb7d680.json)）。未创建 approval/seed/backfill；EVID-01 继续 `active`/fail-closed，生产 first-winner/revocation/rollback、角色化 UAT 与 owner/reviewer sign-off 仍未完成。
- 当日执行波次规则与当时 registry 的 `execution_focus=EVID-01` 对齐：TAR-01 至 TAR-04 repository 合同完成，生产 auto-collect 可并行，但不因健康或本地合同解除 Evidence、决策、TUI 或容量门禁；当前 focus 以本页顶部和机器注册表为准。
- 公网 `/api/health/`、`/api/health/db/`、`/api/ready/`、`/api/audit/health/` 均正常；`/api/decision-ready/` 仍为 `503` 且 `must_not_use_for_decision=true`，匿名 `/api/tui/` 为 `403`。这次只做一次受控部署与低频只读观测，不反复部署、不启用 queued/capacity/chaos，不把健康或匿名边界当作角色写后回执；B/S、CLI/API 只向服务器提交请求，AI/provider/tool execution 在服务器端；本地执行仅适用于 QMT 外部券商桥。
- EVID-02 已在同一已部署候选 `94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / `20260824133504`、同一 `default` alias 下完成 `REPEATABLE READ READ ONLY` current-head 复核；三张 canonical approval/activation 相关 ledger 均为 `0` 行，head=`empty`。快照与报告见 [`evid-02-select-only-vps-snapshot-2026-08-24-94abd76e.json`](deployment/evid-02-select-only-vps-snapshot-2026-08-24-94abd76e.json) 与 [`3513ea4582a73d2afccd5c2967008c4a8c17aa70d3a7039473947724c289e4fd.json`](deployment/evid-02-head-audit/35/3513ea4582a73d2afccd5c2967008c4a8c17aa70d3a7039473947724c289e4fd.json)；报告固定 `human_approval_status=not_collected`、`production_claim=false`、`runtime_enablement=not_authorized`，EVID-02 仍 `awaiting_production`。
- DATA-01 已在不重新部署 VPS、不创建远端归档的前提下，使用 `--download-latest` 读取并验证既有 `/opt/agomtradepro/backups/database/postgres-20260824-074227.dump`；远端/本地大小 `142813695` bytes、SHA-256=`7eb67da66bb6d3c550bc35f96abbc2c38ea403f776c56602316e83b912b4fd6d`，`pg_restore --list`=`7204` entries，manifest SHA=`795d83b33400407596991f92523a5b15b2148bbf5e4e77fc52682194875f3886`。结构化证据为 [`data-backup-evidence-2026-08-24.json`](deployment/data-backup-evidence-2026-08-24.json)，content hash=`423387ef6125233f4257694935beef0cea9c8543993803b3ef58bc896758e9f9`；仅证明现有恢复点的下载/格式完整性，生产 restore/rebuild、维护态 rollback、RTO/RPO、backfill/reconciliation 与 owner/reviewer 仍缺，`DATA-01` 继续 `awaiting_production`，`DATA-02/03` 不解锁。
- DATA-01 同一归档随后在本地 disposable `postgres:16-alpine` 完成 source→restore 全量自洽校验：`539/539` public 表、`72/72` Data Center migrations、`460/460` sequences，schema/逐表内容/sequence 差异均为 `0`；restore `689.563s`、verification `628.355s`、total `2214.035s`，verifier report SHA-256=`0391884b5792150cdcefe74a9a41817c025a3d216e670dfbac18a47facd00f17`。精简证据 [`data01-local-isolated-restore-2026-08-24.json`](deployment/data01-local-isolated-restore-2026-08-24.json)，离线 canonical recorder artifact [`e7af4216ed86cdd63a62d84d5a38ef5bcc28ee255e82490611f673bb945ebe9d.json`](deployment/data01-isolated-restore/e7/e7af4216ed86cdd63a62d84d5a38ef5bcc28ee255e82490611f673bb945ebe9d.json)，artifact SHA-256=`e7af4216ed86cdd63a62d84d5a38ef5bcc28ee255e82490611f673bb945ebe9d`。restore/source 临时库已清理；该耗时不构成生产 RTO/RPO，未执行生产 restore/DDL、维护态 rollback、backfill/reconciliation 或 owner/reviewer 签署，`DATA-01` 仍 `awaiting_production`，不解锁 DATA-02/03。
- STRAT-01 已对当前受控候选 `94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / release `20260824133504` 做同一 `default` alias 的 `REPEATABLE READ READ ONLY` owner-ledger 盘点：Research `65`、Portfolio `7`、Account 广义 `16`、owner/policy/operator/assignment 广义 `35` 张表均为 `0` 行。快照与报告见 [`strat-01-owner-ledger-readonly-recheck-2026-08-24-0707.json`](deployment/strat-01-owner-ledger-readonly-recheck-2026-08-24-0707.json) 与 [`0bed8c11f20f7b93b1b5cb424270f98419f61e6c948f61f46a9c775a9ed3c0ca.json`](deployment/strat-01-owner-ledger-inventory/0b/0bed8c11f20f7b93b1b5cb424270f98419f61e6c948f61f46a9c775a9ed3c0ca.json)；结果固定 `zero_seed`、`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`，`STRAT-01` 继续 `awaiting_production`，不解锁 STRAT-02/03。
- AUD-03 已对同一受控候选 `94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / release `20260824133504` 做一次低频 `select_only` 运营观察：公网 `/api/audit/health/`=`200/OK`，operation logs=`555`、failures=`0`、outbox 各 backlog gauge=`0`；同一 `default` alias migration applied=`495`、pending/failed=`0`、graph SHA=`142da62cb866ee9ef2a291bd0f1f0edf527615c3d76cf15a1aae02d1cb191c2a`。快照与报告见 [`aud03-operational-observation-select-only-2026-08-24-0736.json`](deployment/aud03-operational-observation-select-only-2026-08-24-0736.json) 与 [`00d9f623008af7d51286e6620fad6dee6e87a741f9439156d7830ab8918cee53.json`](deployment/aud03-operational-observation/00/00d9f623008af7d51286e6620fad6dee6e87a741f9439156d7830ab8918cee53.json)；alerts/TUI/recovery/archive 仍 unavailable（`missing_section_count=4`），因此 `AUD-03` 继续 `waiting_dependency`，不解锁 migration/rollback、recovery、archive/restore 或 owner/reviewer sign-off。
- AUD-03 successor `80ea002b…` / release `20260830215638` 的非重复只读重绑定见 [`aud03-successor-production-readonly-checkpoint-2026-08-31-80ea002b.json`](deployment/aud03-successor-production-readonly-checkpoint-2026-08-31-80ea002b.json)（SHA=`a5ce4fbd…182d`）及 canonical [`6022067c4c615ebd1b92e97da6df03608c261f9e39b3495f288ee3eae622efaf.json`](deployment/aud03-operational-observation/60/6022067c4c615ebd1b92e97da6df03608c261f9e39b3495f288ee3eae622efaf.json)：migration=`496/0/0`、logs/failures=`563/0`、outbox 六项为 0、12 rules/0 unhealthy、active alerts=0，10 个 Audit route 均在同候选 108/108 UAT 中通过；`missing_section_count=2`，recovery/archive 仍不可用，未执行任何生产写动作。
- DATA-03 已对同一受控候选 `94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / release `20260824133504` 做一次低频双 readiness 只读复核：`/api/ready/`=`200/ok`，`/api/decision-ready/`=`503/blocked` 且 `must_not_use_for_decision=true`，`/api/health/`=`200`；匿名 Data Center providers `403`，canonical smoke 保持 `unknown`。快照与报告见 [`data03-readiness-http-get-2026-08-24-0757.json`](deployment/data03-readiness-http-get-2026-08-24-0757.json) 与 [`8144f224cce8840a8284c64517fbf49b646e56d600235f976f7e423b4b35bf5a.json`](deployment/data03-readiness/81/8144f224cce8840a8284c64517fbf49b646e56d600235f976f7e423b4b35bf5a.json)；`decision_blocker_count=1`、`smoke_failure_count=1`，不解锁 DATA-03、M9/M10 或决策使用。
- TUI-01/TAR-05 当前候选边界只读核对仍为 `DENY`：正式 M5 binding、108 路由/任务 UAT、101 项 telemetry、rollback、registry backup 与双签均缺；`94abd76e` 只作为 TAR/EVID 受控候选，不重复部署、不直接重绑为 M5 候选。
- EVID-01 当前仓库合同复核：owner/tenant authority、core authenticated composition、Research scope lifecycle/provider/observation、Evidence composition guard 与 v2 inventory 定向回归 `89 passed`；Account/Research component repository/model 合同 `36 passed in 156.20s`；composition guard 扫描 `2931` 个生产文件通过，registry/governance 均为 `0 violations`。这只证明本地 fail-closed 合同，不解除 post-0055 zero-seed、生产 PG race/rollback、root approval、same-alias 端到端回执或 owner/reviewer sign-off。
- 09:35 UTC 低频公网只读复核：health/ready/audit 均 `200`，匿名 `/api/tui/`=`403`，decision-ready=`503` 且 `must_not_use_for_decision=true`；结构化工件 [`tar01-public-health-readonly-recheck-2026-08-24-0935.json`](deployment/tar01-public-health-readonly-recheck-2026-08-24-0935.json)，SHA-256=`41f4604302b1ab4b5a9d2425fcb9713833636fb91436453722694ecfc9aeaa4e`。这是未绑定候选的只读事实，不解锁 TAR/AUD/TUI/EVID 生产门禁，也不触发重复部署。
- TUI/M5、TAR-05、AUD-01、数据与策略生产门禁仍按 registry 逐项等待外部授权和证据。

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
- ✅ **Portfolio benchmark methodology bundle activation append-only ledger**
  - subject+activation双账本以private UOW、per-definition root/predecessor CAS和closed-world restore封存五源/FK/actor/header/clock seals；0027 zero-seed
  - Django5.2组件13 passed、Portfolio migration no-drift；固定configuration-only，PG并发、owner readers/staff composition与daily valuation仍缺
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
- ✅ **Account physical account-row observation append-only ledger**
  - 单表private UOW、raw-source/logical-row first-winner与root/predecessor CAS，closed-world restore封存actor/header/identity/content/clock seals；0040 zero-seed
  - Django5.2组件21 passed、Account no-drift；真实migration/PG并发、Simulated adapter/composition与provenance签发仍缺，owner保持unknown
- ✅ **Account owner-assignment provenance receipt Domain 合同**
  - creation/manual-reclaim/migration共用一个closed receipt，exact绑定physical row全部seals与有效期；authoritative owner只能等于claimant
  - migration仅由当前staff reviewer声明legacy-default且永不声称owner；固定inactive，Application/ledger/provider与assignment adapter仍缺
- ✅ **Account owner-assignment provenance receipt Application workflow**
  - 5字段ID-only签发以单一cutoff双读physical row，creation/manual claimant与migration staff reviewer分支闭合；issuer-bound first-winner/CAS完成
  - exact/current读拒绝superseded或row替换；仅Protocol+pure fake，ledger/provider/composition/签发入口和assignment adapter仍缺
- ✅ **Account owner-assignment provenance receipt append-only ledger**
  - strict codec/model/repository封存physical-row、claimant/issuer、authority/header/ledger与persisted-clock seals；private UOW/claim、first-winner、single-root/predecessor CAS完成
  - Django5.2组件10 passed、0041 zero-seed且migration state同构；PG并发/真实migrate、provider/composition、签发入口与assignment adapter仍缺，固定inactive
- ✅ **SimulatedTrading simulated-account row source Domain 合同**
  - owner-issued source identity/hash封存Account字符串identity、整数row provenance及nullable user/raw type/active/row clock；unknown owner且不做cast
  - tombstone、source/TTL最早有效期与PIT final不回退闭合；Application/ledger、全writer接线与Account adapter/composition仍缺
- ✅ **SimulatedTrading simulated-account row source Application workflow**
  - 6字段ID-only capture只接受owner-issued typed observation，同cutoff双读、actor-bound first-winner、logical-head/predecessor CAS与exact/current闭合
  - 禁止从pk/updated_at/now临时生成source；仅Protocol+pure fake，ledger、全writer、production adapter/composition与Account映射仍缺
- ✅ **SimulatedTrading simulated-account row source append-only ledger**
  - strict owner ledger封存row/presence/tombstone、actor/header/ledger与persisted-clock seals；private UOW/claim、first-winner、logical-row single-root/predecessor CAS完成
  - Django5.2组件3 passed、0021 zero-seed且migration state同构；PG并发/真实migrate、全writer/raw provider仍缺，空账本稳定fail-closed
- ✅ **SimulatedTrading owner-side Account physical-row provider**
  - exact winner必须等于final logical head且source仍present/active/fresh才原样映射Account DTO；superseded/tombstone/expired不回退
  - owner-side composition避免Account反向依赖；pure tests 3 passed；ledger zero-seed时稳定None，raw observation/outbox与全writer仍缺
- ✅ **SimulatedTrading raw account-row observation Domain**
  - owner raw facts封存row/user/type/active/presence/tombstone与observed/valid clocks；root/successor/PIT final no-fallback闭合，pure tests 23 passed
  - 固定inactive/evidence-only；Application/ledger/outbox/全writer与source v2 raw-hash binding仍缺，既有row不回填
- ✅ **SimulatedTrading raw account-row observation Application**
  - exact Domain-only record、version=owner mutation/outbox identity；server recorded clock、first-winner/predecessor CAS与exact/current闭合，组合31 passed
  - 仅Protocol+pure fake；raw ledger、owner adapter/source v2与全writer同事务outbox仍缺，production zero-seed
- ✅ **SimulatedTrading raw account-row observation ledger**
  - strict无FK账本、private UOW/claim、first-winner、logical-row root/predecessor CAS与closed-world PIT/head闭合；Django5.2组件5 passed、0022 zero-seed
  - PG并发/真实migrate、owner provider/source v2与全writer同事务outbox仍缺，既有行不回填
- ✅ **SimulatedTrading raw-bound account-row source v2 Domain**
  - 独立v2 type/schema精确封存raw authority、identity/content/predecessor hash与owner clocks；source/raw ID-version同源，禁止alias与fallback v1
  - raw/source双链successor与PIT final no-fallback闭合，pure tests 41 passed；Application、0023 ledger、v2 adapters与全writer outbox仍缺
- ✅ **SimulatedTrading raw-bound account-row source v2 Application**
  - ID/hash-only capture以同cutoff双读raw exact-current source，source/raw双链first-winner与predecessor CAS闭合
  - current会重验raw final head并防止projection lag，组合56 passed；0023 ledger、v2 adapters与全writer outbox仍缺
- ✅ **SimulatedTrading raw-bound account-row source v2 ledger**
  - 独立strict/closed-world账本封存raw、row、logical、clock与header seals；private UOW/claim、identity/raw binding/root/predecessor CAS闭合
  - Django5.2组件5 passed、0023 zero-seed；PG并发/真实migrate、v2 adapters与全writer outbox仍缺，v1不作current fallback
- ✅ **SimulatedTrading raw observation → source v2 owner provider**
  - raw identity winner与logical final head双闭合，ID/version/hash/row/clocks逐项原样映射；tombstone可读但superseded/expired/future不回退
  - read-only composition无UOW/writer，pure tests 8 passed；两账本zero-seed、Account v2 consumer与全writer raw outbox仍缺
- ✅ **Account physical-row observation v2 Domain**
  - 独立v2完整封存并重算Simulated source/raw双层canonical hashes，三重predecessor和三层时钟/有效期闭合
  - Domain联跑101 passed、architecture 2799/0；Application、0042 ledger、owner provider、全writer outbox仍缺，v1不fallback
- ✅ **Account physical-row observation v2 Application**
  - ID/hash-only capture、source exact-final/current双读面、同cutoff双读、actor first-winner、三重predecessor CAS与closed-current闭合
  - Domain/Application 43 passed；0042 ledger、owner provider/composition、全writer raw outbox仍缺，v1/provenance不fallback
- ✅ **Account physical-row observation v2 ledger**
  - 独立strict/closed-world账本封存Account/source/raw/actor/header seals，private UOW/claim与identity/source/root/predecessor CAS闭合
  - Django5.2组件2 passed、0042 zero-seed；PG并发/真实migrate、owner composition与全writer outbox仍缺
- ✅ **SimulatedTrading source v2 → Account v2 owner provider**
  - source winner/final head双闭合；exact-final传播terminal、exact-current仅live，完整source/raw/hash/clock原样映射
  - read-only composition pure 9 passed、architecture 2805/0；三账本zero-seed、Account wiring与全writer outbox仍缺
- ✅ **SimulatedAccount raw mutation writer 安全前置**
  - typed mutation、跨opaque-ID physical-row head、显式同alias外层事务与create/update/delete/tombstone CAS已闭合
  - unit 11 passed、Django5.2 component 5 passed；尚未接生产writer，全部ORM/Admin/cascade一次性切换前保持zero-seed
- ✅ **Account v2 自动证据 recorder 语义修正**
  - v2 capture改用fixed service/evidence_projector，codec/0042/header与recorder/record/ledger seals全链闭合，不伪造human staff
  - pure 43 passed、component 2 passed；仅技术provenance修正，不提升owner/permission，pipeline与writer cutover仍缺
- ✅ **SimulatedAccount 三账本 Evidence Pipeline 安全前置**
  - 未激活pipeline要求调用方同alias外层事务，固定raw→source-v2→Account-v2并原样传递hash/tombstone；unverified canonical-form identity不做str/int cast
  - unit 8 passed、architecture 2807/0；未接production writer，Account owner authoritative provider与一次性全writer cutover仍缺
- ✅ **Account owner-assignment claimant provenance receipt v2 Domain**
  - 独立v2精确绑定physical/source/raw三层hash、clock与presence；claimed-owner/legacy-default只代表human claim，live-row签发且final失效不回退
  - pure 22 passed、architecture 2808/0；Application/0043/staff approval evidence v2与authoritative provider仍缺
- ✅ **Account owner-assignment claimant provenance receipt v2 Application**
  - 6字段ID/hash-only签发、physical-v2同cutoff双读、actor-bound first-winner/head CAS；exact/current重验upstream且无v1 fallback
  - pure 9 passed、architecture 2809/0；0043/provider/staff approval evidence v2与authoritative identity仍缺
- ✅ **Account owner-assignment claimant provenance receipt v2 ledger**
  - strict/closed-world 0043账本以private UOW、identity/root/predecessor CAS及physical/source/raw/actor/header seals闭合claimant receipt
  - Django5.2组件5 passed、migration state无漂移；PG race/真实migrate、staff approval evidence v2与authoritative provider仍缺
- ✅ **Account owner-assignment staff approval evidence v2 Domain**
  - subject重验完整physical-v2与claimant receipt-v2；独立human staff双维防自批，claim→authoritative/legacy→ownerless精确映射，双root、approval TTL及相邻successor闭合
  - pure 28 passed、architecture 2813/0；两阶段Application、0044账本、authoritative current provider与PG并发仍缺
- ✅ **Account owner-assignment staff approval evidence v2 Application**
  - ID/hash-only subject注册与staff审批；两upstream同cutoff双读、双mapping head一致、actor-bound first-winner/predecessor CAS及exact/current重验闭合
  - 组合36 passed、architecture 2814/0；0044账本、双root DB约束、authoritative provider/composition与PG并发仍缺
- ✅ **Account owner-assignment staff approval evidence v2 strict codec**
  - 完整嵌套subject/physical-v2/claimant-receipt-v2/Evidence，以exact shape/type、UTC-Z及canonical roundtrip闭合篡改检测
  - codec 9 passed；0044双表/双root/closed-world repository/component与authoritative provider仍缺
- ✅ **Account owner-assignment staff approval evidence v2 0044 schema**
  - subject/Evidence双表、OneToOne PROTECT、private UOW/claim与全mutation guard；Account/underlying双root分别partial unique，successor predecessor unique
  - Django5.2 model component 4 passed、architecture 2816/0；closed-world repository/真实migrate/PG race与authoritative provider仍缺
- ✅ **Account owner-assignment staff approval evidence v2 repository**
  - full-table canonical restore后才selector；双mapping完整链/同head、predecessor CAS、exact/PIT/first-winner与IntegrityError exact幂等闭合
  - component 9 passed、pure 45 passed、architecture 2817/0；PG四类race/真实0044 migrate与authoritative provider/composition仍缺
- ✅ **Account authoritative mapping v2 read-only facade**
  - 以underlying namespace/id + PIT选择最终Evidence head，再重验双mapping head及physical/claimant receipt current；legacy、missing、stale均fail closed
  - pure 11 passed、architecture 2818/0；仅发布identity_mapping_only/inactive/execution=false，首次create的canonical identity bootstrap循环仍阻断pipeline/writer
- ✅ **Account canonical creation allocation/binding Domain**
  - Account owner在physical row产生前分配opaque canonical ID；一次性binding重验allocation、live Physical-v2 root、user/type与Account/underlying双claim
  - pure 5 passed、architecture 2819/0；固定pending-owner-approval/inactive/must-not-execute，Application/ledger与全writer原子cutover仍缺
- ✅ **Account canonical creation allocation/binding Application**
  - Account ID由server generator产生，request first-winner跨时钟幂等；binding用ID/hash-only selector双读exact-unconsumed allocation与Physical-v2 root，并闭合四唯一锚
  - Domain+Application 9 passed、architecture 2820/0；仅Protocol+fakes，ledger、Physical allocation seal、pipeline/writer仍缺
- ✅ **Account canonical creation strict codec**
  - Allocation完整封存requester/service/fixed/hash/UTC-Z；Binding嵌套完整Allocation和Physical-v2 canonical payload，不压缩成caller hash
  - unit 12 passed；exact keys/types/canonical roundtrip与tamper fail closed，0045 schema/repository与pipeline仍缺
- ✅ **Account canonical creation 0045 schema**
  - Allocation/Binding双append-only表以private UOW/exact claim与全mutation guard闭合；Account ID/request幂等、allocation唯一消费及Account/underlying/Physical四锚均有DB约束
  - Django5.2 isolated component 3 passed、architecture 2822/0；0045仅CreateModel/zero-seed，repository、PG竞争及pipeline仍缺
- ✅ **Account canonical creation repository**
  - 全表strict restore后做allocation identity/request/exact/current-unconsumed与binding four-anchor/exact/append，逐列seals、OneToOne和时钟重验
  - Django5.2 models+repo component 9 passed、architecture 2823/0；消费/过期不回退，PG竞争、Physical/receipt新schema及pipeline仍缺
- ✅ **Account allocated Physical-v3 creation-root Domain**
  - 独立v3 wrapper完整封存exact allocation与Physical-v2 root，强physical/source/raw三predecessor为空、live/present、label/user/type一致与三路min-validity
  - pure 28 passed、architecture 2824/0；仅creation root，durable Binding-v2/Application/ledger/update-delete successor仍缺，无v2 fallback
- ✅ **Account durable canonical creation Binding-v2 Domain**
  - exact allocation + allocated Physical-v3 root与Account/underlying双claim、v3/v2/source/raw hashes完整封存；映射耐久性不再绑定短TTL
  - pure 10 passed、architecture 2825/0；固定inactive/unknown/must-not-execute，Application/ledger/provider及Physical-v3 successor仍缺
- ✅ **Account durable canonical creation Binding-v2 Application**
  - ID/hash-only binding双读exact-unconsumed allocation与Physical-v3 root，以server binder/clock和identity+四锚first-winner闭合永久映射证据
  - Domain+Application 29 passed、architecture 2826/0；独立ledger/provider、跨v1/v2 allocation消费、Physical-v3账本与receipt/Evidence-v3仍缺
- ✅ **Account allocated Physical-v3 creation-root Application**
  - ID/hash-only capture双读allocation与Physical-v2，独立service projector、winner/head/root-CAS、exact PIT/closed-current及消费后winner replay闭合
  - 四批组合61 passed、architecture 2827/0；0046 ledger、0047统一consumption claim/Binding-v2 ledger、successor与receipt/Evidence-v3仍缺
- ✅ **Account durable canonical creation Binding-v2 strict codec**
  - 完整嵌套allocation、Physical-v3/v2、source/raw与binder canonical payload，exact shape/type/UTC-Z/Domain重建及全层tamper fail closed
  - codec 48 passed；无model/repository/migration，0047统一consumption claim/Binding-v2 ledger与跨v1/v2并发仍缺
- ✅ **Account allocated Physical-v3 creation-root 0046 ledger**
  - nested allocation+Physical-v2/source/raw与projector全seals，五锚unique、private UOW、root-only CAS及closed-world exact/PIT/head/tamper闭合
  - Django5.2 isolated component 4 passed、architecture 2831/0；zero-seed，PG竞争/真实migrate与0047统一claim/Binding-v2 ledger仍缺
- ✅ **Account canonical creation unified Consumption Claim Domain**
  - exact allocation与Binding-v1/v2 consumer分支、非递归ref、同recorded_at、Account/underlying raw claims及Physical-v2/v3矩阵闭合
  - pure 30 passed、architecture 2832/0；codec、0047 expand、v1 dual-write/backfill、Binding-v2 repo与0048 contract仍缺
- ✅ **Account canonical creation unified Consumption Claim strict codec**
  - nested allocation完整恢复，consumer按非递归ref注入核对；exact shape/type/UTC-Z/canonical roundtrip与全selector/hash tamper fail closed
  - codec 32 passed；无model/repository/migration，0047 expand、closed-world restore、v1 dual-write/backfill与0048 contract仍缺
- ✅ **Account canonical creation consumption 0047 expand schema**
  - 新Claim+Binding-v2 append-only表与旧Binding-v1 nullable claim FK，跨generation raw anchors、branch/fixed/clock checks及private guards闭合
  - Django5.2 isolated 6 passed、architecture 2834/0；仅expand/no-backfill，v1 dual-write、Binding-v2 repo、0048 contract与PG交叉竞争仍缺
- ✅ **Account canonical creation unified Claim Application workflows**
  - Binding-v1/v2均由allocation identity+generation确定性派生claim identity；两条路径先replay winner，再按authoritative recorded clock双读并原子append Binding+Claim pair
  - 聚合pure 85 passed、architecture 2834/0；仅Protocol+fakes，v1/v2 repositories、逐aliasinventory/backfill、0048 contract与PG交叉竞争仍缺
- ✅ **Account Binding-v2 unified Claim repository**
  - closed-world恢复allocation/root/v1/v2/claim并验证全headers/seals；allocation parent锁、Claim→Binding-v2同事务双写、legacy null-claim占用与exact pair replay闭合
  - Django5.2 isolated repo 8 passed、组合17 passed；v1 repo dual-write、逐aliasinventory/backfill、0048 contract与PG交叉竞争仍缺，writer/pipeline禁用
- ✅ **Account Binding-v1 unified Claim dual-write repository**
  - 0045/0047同alias双UOW，full-world恢复v1/v2/root/claim；current-unconsumed跨generation闭合，新写强制Claim→Binding-v1 pair且legacy null-FK仅历史fail-closed兼容
  - Django5.2 v1 6 passed、组合17 passed、architecture 2835/0；逐aliasinventory/backfill、0048 contract与PG竞争仍缺，writer/pipeline禁用
- ✅ **Account canonical creation consumption 逐alias盘点与回填预览**
  - 精确核验0045–0047 migration、列/nullability/constraint/FK并closed-world恢复五账本；发布稳定inventory SHA与跨generation一致性计数
  - deterministic backfill仅预览候选；缺真实backfilled-at和writer-freeze时写模式稳定阻断。Django5.2 isolated 10 passed；生产alias/0048/PG竞争未验证
- ✅ **Account canonical creation consumption 运维命令**
  - inventory/backfill以显式alias输出稳定单行JSON；默认dry-run且batch标记reserved，不把全事务冒充分批执行
  - PG+fresh inventory SHA仍因writer-freeze缺失阻断写入；pure 14 passed、architecture 2839/0，0048 readiness保持false
- ✅ **Account canonical creation consumption writer-freeze 前置**
  - v1/v2 writer UOW在PG事务内取得同key shared advisory lock；maintenance exclusive helper默认PG-only，SQLite仅显式test degradation
  - 组合18 passed；尚无真实PG两连接竞争且backfill仍阻断，不能视为已取得生产freeze或0048授权
- ✅ **Account canonical creation consumption knowledge clock expand**
  - 0048 nullable/indexed knowledge_at保留业务recorded_at与canonical bytes；live同钟，Claim pair/anchor/unconsumed PIT按真实知识时点
  - component 29 + command 14 passed、architecture 2840/0；既有NULL Claim、exclusive backfill、NOT NULL contract与PG迁移/竞争仍阻断
- ✅ **Account canonical creation consumption knowledge backfill engine**
  - transitional closed-world处理已有NULL Claim、legacy null-FK与缺Claim；exclusive lock内取DB clock并以完整归属anchors CAS，失败整批rollback
  - component 34 passed、architecture 2840/0；默认无write authorization且command阻断，production SHA/PG双连接/逐alias签字仍缺
- ✅ **Account owner-assignment creation claimant receipt v3 Domain**
  - 仅以durable Binding-v2为权威来源，重验allocation、allocated Physical-v3、Physical-v2/source/raw及Account/underlying全seal；creation claimant必须同时等于allocation requester和live physical row user
  - pure 16 passed、strict mypy、architecture 2841/0；固定claim-only/inactive/must-not-execute，Application/ledger、独立staff Evidence-v3、Physical-v3 successor/current provider与生产writer仍缺
- ✅ **Account owner-assignment creation claimant receipt v3 Application**
  - 6字段ID/hash-only签发优先重放immutable winner；新签发在单cutoff双读durable Binding-v2、exact-current Physical-v3和当前human claimant，使用server clock与predecessor CAS
  - Domain+Application 24 passed、strict mypy、architecture 2842/0；历史exact永久可读而closed-current重验TTL/head/upstream，ledger/provider、staff Evidence-v3与production composition仍缺
- ✅ **Account owner-assignment creation claimant receipt v3 strict codec**
  - exact Receipt-v3 record完整嵌套并重建Binding-v2→allocation→Physical-v3→Physical-v2→source/raw；exact keys/types、UTC-Z、claimant/issuer、fixed booleans/hash与canonical roundtrip均fail closed
  - codec 17 passed、strict mypy；0049独立zero-seed账本、provider/composition、staff Evidence-v3与PG并发仍缺
- ✅ **Account owner-assignment creation claimant receipt v3 0049 ledger**
  - append-only账本完整封存Binding-v2/Claim knowledge、allocation/Physical-v3/v2/source/raw、actor与chain seals；全Receipt及Consumption closed-world后才按PIT选择，late knowledge不得洗白历史签发
  - Django5.2 isolated component 7 passed、architecture 2846/0；zero-seed，PG竞争/真实migrate、provider/composition与production actor入口仍缺
- ✅ **Account owner-assignment staff approval Evidence v3 Domain**
  - creation-only subject显式封存11项Receipt/Binding/root/Account/underlying/Physical/source/raw seals；独立human-staff双维防自批，authoritative owner固定等于claimant，双mapping root domain-separated且candidate-independent
  - Receipt-v3+Evidence-v3 pure 33 passed、strict mypy、architecture 2846/0；Application/codec/0050账本/current facade与production composition仍缺
- ✅ **Account owner-assignment staff approval Evidence v3 Application**
  - ID/hash-only Subject注册与staff审批；winner-first历史重放，单cutoff双读Receipt-v3/Physical-v3/approver，双mapping root CAS，exact永久而current重验全部upstream
  - Domain+Application pure 48 passed、architecture 2848/0；winner replay不依赖当前approver且recorded clock重新复核全部输入，0050双表账本、production providers/composition与PG竞争仍缺
- ✅ **Account owner-assignment staff approval Evidence v3 strict codec**
  - 公开Subject/Evidence codecs完整重建Receipt-v3→Binding-v2→Physical-v3/v2→source/raw，exact keys/types、UTC-Z、fixed booleans及canonical roundtrip fail closed
  - codec 24 passed、Application组合30 passed、strict mypy；无ORM，0050必须逐行闭合上游FK与Claim knowledge
- ✅ **Account owner-assignment staff approval Evidence v3 0050 ledger**
  - Subject/Evidence双表以PROTECT FK封存Receipt-v3、Binding-v2、Physical-v3与独立approver；全表restore后逐行闭合FK链、0049 Receipt与Consumption Claim knowledge，双mapping分别unique root
  - Django5.2 isolated本批4 passed、0049组合11 passed、architecture 2850/0；zero-seed，PG竞争/真实migrate、providers/composition/current mapping仍缺
- ✅ **Account authoritative mapping v3 read-only facade**
  - underlying selector先取0050 Evidence-v3 head，再以ID/version/hash重验current exact equality；只发布identity_mapping_only/inactive/execution=false，legacy/missing/stale均None且无v2 fallback
  - pure 6 passed、architecture 2851/0；production Account-only exact-first composition、staff provider与PG证明仍缺
- ✅ **Account Evidence-v3 Account-only只读composition**
  - 同alias组装0046/0047/0049/0050 readers，Physical/Receipt以scalar exact selector恢复完整Domain后再做current复核；无Simulated反向依赖、v1 fallback或writer/approval surface
  - pure组合18 passed、Django5.2空账本组件1 passed、architecture 2852/0；全账本仍zero-seed，staff写入口、knowledge contract、PG竞争与全writer cutover未完成
- ✅ **Account Physical/Receipt-v3 current ID/hash-only边界**
  - current command仅接ID/version/content hash/PIT，服务端exact恢复canonical对象后再派生最终head、TTL与upstream selectors；composition不再拼接caller Domain对象
  - 定向pure 41 passed、0049/0050/composition组件链12 passed、architecture 2852/0；无schema/write变化，production authority前置与execution总闸不变
- ✅ **Account owner-assignment v3 actor authority Application合同**
  - request principal仅作selector，每次读取重新验证exact-current active/user/RBAC authority；claimant为nonstaff/nonsuperuser，approver为staff+Account admin，撤权/过期fail closed
  - 定向pure 32 passed、architecture 2853/0；仅Protocol/DTO+fakes，Django authority source、request adapter、write composition与路由均未实现
- ✅ **Account actor authority source v3 Domain**
  - Account独立封存opaque principal/auth-context、User/RBAC exact refs、actor/facts、三有效上界与domain-separated seals；successor锁同session/actor并禁止source clock回填，terminal撤权不可恢复
  - source+Application+Receipt/Evidence pure 65 passed、architecture 2854/0；无capture/codec/ledger/raw providers，请求写入口与execution继续关闭
- ✅ **Account actor authority source v3 Application**
  - 单一atomic bundle provider承载auth-context/User/RBAC exact-current输入；winner-first，cutoff双读与recorded-at第三读后以same-session predecessor CAS落候选，历史exact与final-head current严格分离
  - pure 40 passed、architecture 2855/0；仅Protocol/DTO+fakes，无codec/ledger/真实authority bundle/request adapter/staff入口，terminal/expired不回退且execution继续关闭
- ✅ **Account actor authority source v3 strict codec**
  - 完整恢复principal/context/User/RBAC refs、facts、时钟、chain与全部domain-separated seals；exact keys/types、UTC-Z及canonical encode-equality使替换与篡改fail closed
  - codec 28 passed、Domain/Application/codec组合68 passed；无ORM/migration，zero-seed、真实bundle provider、staff入口与execution仍关闭
- ✅ **Account actor authority source v3 0051 schema/append guards**
  - schema-only双表引入candidate-independent source/root anchor与完整ledger，PROTECT predecessor、持久化service recorder/ledger seals、private UOW/exact claim及全mutation guards
  - isolated Django5.2 3 passed、mypy 0 regressions、architecture 2857/0；无repository/closed-world/PG race，仍zero-seed且不构成production authorization
- ✅ **Account actor authority source v3 0051 repository**
  - source/root anchor串行化、whole-append savepoint、first-winner/predecessor CAS与全表closed-world恢复；codec、recorder/content binding及ledger seals逐项闭合，terminal/expired final head不回退
  - isolated model+repo 7 passed、strict mypy、architecture 2858/0；PG双连接race与三项raw authority sources/atomic bundle仍缺，zero-seed且execution关闭
- ✅ **Account actor authority raw-source v3 Domain primitives**
  - Account Domain内复用exact identity、aware observation/knowledge/validity clock、root/predecessor XOR、UTC-Z/domain hash及fixed inactive/nonexecution header，不混合三种业务artifact
  - pure 10 passed、architecture 2859/0；仅primitives，auth-context/User/RBAC concrete artifacts与ledgers/atomic provider仍缺
- ✅ **Account auth-context/User/RBAC raw authority source v3 Domains**
  - 三种独立artifact分别封存secret-free认证上下文、User active/staff/superuser及7-role canonical RBAC；各自domain-separated identity/root/seals、successor与terminal no-fallback语义
  - primitives+三Domain pure 85 passed、strict mypy、architecture 2862/0；无codec/ledger/immutable Django writers/atomic bundle/request adapter，staff与execution仍关闭
- ✅ **Account auth-context/User/RBAC raw authority source v3 strict codecs**
  - 三个独立codec完整恢复nested identity/clock/chain、专属facts、fixed semantics与全部seals；exact shape/types、UTC-Z、role/state及canonical equality使替换fail closed
  - codec 100 passed、三Domain+codec组合175 passed、architecture 2865/0；无raw ledger/writer/atomic bundle，staff与execution仍关闭
- ✅ **Account actor authority raw-source v3 Application primitives**
  - 统一ID/hash/PIT scalar selector、fixed automated service recorder及三类稳定异常，不引用ORM或任一具体raw artifact
  - pure 22 passed、Ruff/strict mypy/AST边界通过；尚无concrete reader/repository/capture/ledger/bundle/request adapter
- ✅ **Account auth-context/User/RBAC raw authority v3 Application readers**
  - 三个typed Persisted/repository/exact/current合同闭合ID/hash/PIT、final head与recorder；未来或替换Corruption，terminal/expired/superseded不回退
  - 定向29 passed、Domain/codec/Application组合236 passed、architecture 2869/0；尚无Django repo/capture/version allocator/atomic bundle
- ✅ **Account auth-context/User/RBAC raw authority v3 0052 schema/guards**
  - 三套独立anchor+concrete ledger完整投影facts/seals/recorder并以PROTECT链、fixed/state/clock/root/role约束及private nonnested UOW封住旁路；无generic discriminator或mutable auth FK
  - Django5.2与0051组件19 passed、增量mypy 0 regressions、architecture 2870/0；仍zero-seed且无repo/PG race/lifecycle writer/atomic bundle
- ✅ **Account auth-context/User/RBAC raw authority v3 0052 repositories**
  - 三个concrete repo锁定candidate-independent anchor并以whole-append savepoint、strict codec/recorder/ledger full-world restore和predecessor CAS闭合single-root链；terminal/expired head不回退
  - repo 14 passed、与0052 model合计30 passed、architecture 2873/0；PG race/production migrate/lifecycle writer/version allocator/atomic bundle仍未完成
- ✅ **Account RBAC authority mutation v3 dormant fact-outbox合同**
  - 单一Application UOW合同要求stable mutation identity、Profile lock/CAS、0052 winner/head/append与server clock处于同alias事务；winner-first历史重放不读取当前Profile，首次写和append后均复核Profile/head
  - expired final仍是唯一合法predecessor，只有revoked阻断同epoch后继；pure 13 passed、architecture 2874/0。无concrete UOW或生产入口，且没有issuer、mutation kind、exact old/new Profile hash及持久mutation→source绑定，不能称mutation receipt，0052保持zero-seed
- ✅ **Account RBAC mutation binding v3 Domain合同**
  - Domain封存exact Profile old/new refs、human staff+canonical admin operator authority与service recorder，并将bootstrap/role_change/revoke/reactivate、initial/reactivation epoch、binding/raw-source双链和PIT exact selector分域闭合
  - pure 16 passed、strict mypy/official增量门禁通过、architecture 2875/0；无codec/0053 schema/repository/Profile version ledger/concrete UOW，现存mutable Profile不得回填历史，旧写入口和execution继续关闭
- ✅ **Account RBAC mutation binding v3 strict codec**
  - codec完整恢复epoch、old/new Profile、human operator、service issuer、binding/raw-source双链与全部seals；exact keys/types、UTC-Z、Domain重验和canonical encode-equality使替换与跨链篡改fail closed
  - codec 18 passed、official增量mypy 0 regressions、architecture 2876/0；仅payload封存，不证明mutable来源真实性，0053 schema/repository/UOW/lifecycle writer与execution仍关闭
- ✅ **Account RBAC mutation binding v3 Application读合同**
  - ID/version/hash/PIT selector与typed repository Protocol闭合Exact历史和Current最终head/TTL；terminal/expired/superseded不回退，future或selector/hash/type替换fail closed
  - pure 4 passed、official增量mypy 0 regressions、architecture 2877/0；仍无Django repository、0053 schema、capture/Profile UOW或生产入口，zero-seed与execution关闭
- ✅ **Account RBAC mutation binding v3 0053 schema-only基座**
  - 独立epoch anchor、Profile authority anchor/version ledger与mutation binding ledger；四个CreateModel、PROTECT FK/self predecessor、old/new Profile exact refs、human operator/service issuer、binding/raw-source双链、fixed/state/clock/unique约束及全append-only guards
  - isolated Django5.2 9 passed、与0052模型组件合计25 passed、official增量mypy 0 regressions、architecture 2878/0；仅zero-seed schema，真实PostgreSQL migrate/race、closed-world repository、持久issuer/UOW、mutable lifecycle接线与生产入口仍未完成
- ✅ **Account RBAC mutation binding v3 dormant closed-world repository**
  - 同alias/private UOW的winner/exact/head/append先恢复全部epoch、Profile anchor/version、binding及0052 raw-source rows，逐列重验canonical payload、fixed recorder、recorder/ledger seals、Profile exact refs、raw/binding双链与全图；inner savepoint、epoch锁、predecessor CAS、exact replay和terminal/expired no-fallback闭合
  - repository component 4 passed；与Domain/codec/model组合47 passed、official增量mypy 0 regressions、architecture 2879/0；仅dormant persistence合同，未接owner UOW/mutation issuer、mutable lifecycle/production route或真实PostgreSQL空链竞争，zero-seed与execution关闭
- ✅ **Account authority component evidence runner correction（2026-08-15）**
  - 八组 schema-editor 组件显式持有 `django_db_blocker.unblock()`，在隔离 settings 下可由标准 pytest 复现；RBAC mutation binding、RBAC/User raw、actor raw、owner-assignment actor authority 与 authentication-context repository/model 合计 `50 passed`，mutation-binding repository `4 passed`
  - 这是 SQLite/no-migrations 测试边界修复，不是 PostgreSQL 空链/同 predecessor 并发证据；production lifecycle writer、mutation issuer、atomic bundle 与 execution 仍关闭
- ✅ **Account RBAC mutation binding v3 dormant Application writer contract**
  - ID/hash-only mutation command与server-issued identity resolver注入单一typed UOW；winner-first重放不读取Profile/operator/raw source，首次写校验完整old/new Profile、human staff+canonical-admin operator、0052 raw source exact/current及source-role/subject闭合，再以final predecessor CAS append并复核winner/head
  - writer unit 7 passed；与既有Domain/codec/read contract/0053 model+repository组合54 passed、official增量mypy 0 regressions、architecture 2879/0；仍无concrete Profile mutation receipt/version issuer、mutable lifecycle同alias实现、跨epoch reactivation PG闭环或production route，execution继续关闭
- ✅ **Account Physical v2 migration-state drift correction（2026-08-15）**
  - VPS deploy warning 已复现为 `acct_phys_v2_fixed_ck` 的 model/migration serialization drift；新增 schema-only `0054_normalize_physical_v2_fixed_constraint`，`makemigrations --check --dry-run` 为 `No changes detected`，Django check 通过，isolated SQLite forward/reverse/re-forward 通过
  - 仅修复 migration state warning；下一候选仍需真实 PostgreSQL migration/rollback 观察，Evidence owner authority、生产 lifecycle 与 execution gate 不变
- ✅ **跨 App 决策读边界与模块循环收口**
  - Portfolio账户访问和legacy Broker Evidence均经app-neutral registry，provider缺失稳定fail-closed；Account冷启动移除Strategy静态依赖
  - module guard收紧为206 edges、0双向依赖、0循环组件且全预算绿色；默认环境缺Django/Celery/Playwright的完整回归仍列为未验证
- ✅ **CI module-cycle regression repair（2026-08-16）**
  - Data Fetch audit envelope 归回 Audit owner；Research/Risk 通过注入 Protocol 解耦；Dashboard→Sentiment 走 `core.integration` registry；module guard `206 edges / 0 cycles`，架构/治理合同 `0 violations`，聚焦回归 `32 passed`
  - 未扩大 cycle allowlist 或 mypy baseline；全仓 mypy debt ceiling、远端 CI 与生产 authority/publisher/execution 证据仍需独立完成
- ✅ **CI full-production mypy debt ceiling reduction（2026-08-16）**
  - Account authority/codec、canonical creation closed-world、append-only model guards、Broker/Portfolio/Risk/Research repositories 与 serializer 类型收口；全量 `mypy --no-incremental` `2881 source files / 0 errors`，CI 同款 debt ceiling `0 errors`
  - 未修改 baseline/allowlist；新提交仍需等待 GitHub Actions Fast Feedback，生产 authority/publisher、execution/TUI 门禁不因类型检查变绿而解除
- ✅ **Evidence composition boundary / governance consistency 收口（2026-08-14）**
  - Operator Spec approval/lifecycle concrete Django 组装移入 Risk Center/Research owner composition，`core/integration` 仅保留无 infrastructure import 的兼容导出
  - governance consistency 与 architecture audit 均 0 violations；Data Center catalog、legacy fact、current-data 与 Celery guards 通过。五组 Django component 在 `--no-migrations` 下 `22 passed`；这不替代真实 migration、生产人工审核、PostgreSQL 并发与真实数据
- ✅ **Web→TUI backend contract provenance（2026-08-14）**
  - runtime manifest 逐文件覆盖 IA、Application metadata、IA loader、repository/signals 与全部 `tui_metadata_runtime_*.py`；manifest digest contract 与 observation/candidate recorder 定向回归合计 21 passed
  - 仅完成本地候选 provenance；生产仍 revision=`unknown`/无 manifest，M5 观察窗口继续 DENY
- ✅ **Web→TUI M5 readiness recheck（2026-08-15）**
  - `check_web_to_tui_cutover_readiness.py --json` 返回 `DENY`；matrix/catalog/evidence SHA 一致，108/108 route/task 静态覆盖与 rollback scope 证据存在
  - candidate commit/version 绑定、14 日 observation、production telemetry（`0/101`）、production rollback/registry backup 与 owner/reviewer 双签仍缺；不执行 cleanup/cutover
- ✅ **Web→TUI R0 actionability audit（2026-08-14）**
  - 归一化 runtime graph 的 277 个 write/admin action 均需真实写方法与 mutation effect；创建/编辑/删除/审批入口必须有可见字段，8 个无输入整批命令与 4 个 POST/read 预览/测试命令分别显式登记；`test_tui_actionability_contract.py` `5 passed`、TUI JS `33 passed`
  - 仅证明本地“可填写/可提交”门禁；最终候选角色化浏览器 UAT、写后回执、人工审批和生产审计证据仍未满足，M5 继续 DENY
- ✅ **Web→TUI R1 row-level edit form closure（2026-08-15）**
  - Workbench 对带可见字段的非 GET 行操作先打开/聚焦 action form，按行身份与可匹配字段预填；用户修改并提交后才发送 PATCH/POST，approve/delete/toggle/批量等无额外字段动作仍直接执行
  - 覆盖 `policy.workbench-override`、`signal.update`、`beta-gate.config-update`、`rotation.asset-update`、`rotation.config-update`、`rotation.account-config-update`、`ai-ops.update-my-provider`、`data-center.provider-update` 及用户治理 `identity-access.reject-user`、`identity-access.set-user-role` 等编辑/更新入口；R0 guard 绿色不替代行级提交路径证据
  - 新增浏览器契约覆盖“点击编辑不立即发请求、修改后携带 ID+body 提交”；并锁定 IA/runtime 编辑 row action 必须有可见字段与行上下文；TUI JS `34 passed`、Python actionability `9 passed`、`npm run check:tui` 通过。仍未替代最终候选角色化 UAT、写后回执、人工审批与生产证据
- ✅ **Web→TUI R1 direct row-action semantics（2026-08-15）**
  - 只有存在可见 `body` 字段的行操作才打开表单；仅含 path/query identity 的 approve/delete/toggle/批量命令直接执行，避免冗余的只读标识表单；浏览器契约 `22 passed`，`npm run build:tui`、`npm run check:tui` 通过
  - 仍只证明本地交互判定，角色化浏览器 UAT、写后 receipt/refresh、人工审批、生产审计和 M5 candidate evidence 继续待完成
- ✅ **Web→TUI role-filtered row affordance closure（2026-08-15）**
  - Dashboard 行操作现在按当前用户已通过权限过滤的 action 集合投影；普通用户不再看到无法执行的 Signal/Beta Gate/Rotation 管理员写按钮，管理员行操作保持
  - `tests/unit/test_tui_workbench.py` 覆盖普通用户与管理员双向投影，定向回归 `2 passed`；该项只收紧展示边界，不替代后端权限、角色化浏览器 UAT、写后回执或 M5 生产证据
- ✅ **Web→TUI candidate consistency guard hardening（2026-08-16）**
  - guard 从 cutover 当前 candidate 的 version/commit 唯一匹配已提交 preflight，并截取 readiness/deployment 最新候选段，逐项核对 matrix/graph/runtime manifest binding；当前 `fc145423c4de04cae20c3a6a2e94780505aa5938` / `20260816170851`，回归 `1 passed`
  - 仅防止旧候选章节或旧 preflight 造成一致性误通过，不代表角色化浏览器 UAT、写后 receipt/refresh、14 日 telemetry、rollback、registry restore 或 owner/reviewer 双签完成
- ✅ **STRAT-01/02 readiness runtime preflight guard（2026-08-15）**
  - `test_capability_readiness_runtime.py` 现在明确锁定 R1 六项生产要求为 `UNVERIFIED`、Forecast specification 为 `MISSING`，以及 R2 五项生产要求为 `UNVERIFIED`，防止机制 manifest 被误报为 production readiness
  - 定向组件回归 `8 passed`；这是本地 fail-closed 防伪证据，不是 owner/definition/policy、PIT/OOS 历史、canonical receipt、对账或 Promotion 证据，`STRAT-01` 与 `STRAT-02` 仍保持阻断
- ✅ **STRAT-01 mechanism attestation expiry guard（2026-08-16）**
  - `AttestedMechanismOwnerAdapter` 在直接收集阶段拒绝将 `valid_until <= evaluated_at` 的过期机制 attestation 暴露为 `VERIFIED`，改为 `STALE` 并发布稳定 `*.runtime.attestation_expired` 原因；Research focused `53 passed`、增量 mypy `0 regressions`
  - 仅收紧本地 readiness 中间层，不登记真实 owner/definition/policy/calendar/scope、PIT/OOS、canonical receipt、Promotion 或生产/UAT 证据；`STRAT-01`/`STRAT-02` 继续阻断
- ✅ **Evidence owner/tenant scope read contract（2026-08-15）**
  - 纯 Application scope grant/provider/authorizer 在三类 exact read 触碰 repository 前执行 artifact-level gate；缺失、future/stale、revoked、替换和 hash tamper fail closed，`11 passed`
  - 新增强制注入 authorizer 的 `ScopedEvidenceReadFacade`，避免未来 owner-scoped composition 忘记安装 scope gate；旧 staff-only facade 保持兼容
  - 仅本地合同，未接生产 owner/tenant source、人工授权、PostgreSQL 并发或写/执行路径；API 继续 staff-only，Evidence hard gate 未解锁
- ✅ **Evidence owner/tenant authority source contract（2026-08-15）**
  - 纯 Domain `EvidenceScopeSourceV1` 固定 owner/tenant/account/actor/artifact exact refs、read-only/non-execution 语义、root/successor、PIT 与 revoked/expired no-fallback；source 不读取 Django User/session，也不现场 hash mutable rows，Research scope 合计 `30 passed`
  - 仅 source 语义合同，未创建 ledger/provider、未接 API/ORM/人工授权或 production route；真实 owner/tenant source、PostgreSQL current-head/并发与 Evidence hard gate 继续关闭
- ✅ **Evidence owner/tenant authority source strict codec（2026-08-15）**
  - strict codec 完整重建 `EvidenceScopeSourceV1` 与 nested `ArtifactRef`，exact keys/types、UTC-Z microseconds、root/successor/fixed semantics、identity/content hash roundtrip 和 tamper fail closed；scope/source/facade codec 合计 `42 passed`
  - 仅 canonical persistence contract，未创建 ledger/repository/provider 或生产 owner/tenant 接线；Evidence hard gate、人工授权、写入和 execution 继续关闭
- ✅ **Evidence owner/tenant authority source Application readers（2026-08-15）**
  - dormant pure Application readers 只接受 source ID/version、expected content hash 与 aware PIT；exact 保留历史可知记录，current 要求 exact 与 final logical head 完全相等，terminal/expired/superseded 不回退；相关 source/codec/Domain/facade 回归合计 `52 passed`
  - 仅 read contract，未创建 ledger/repository/provider、未读取 mutable User/session/tenant rows、未接人工授权或 production route；真实 owner/tenant source 与 Evidence hard gate、写入和 execution 继续关闭
- ✅ **EVID-02 Evidence scope PostgreSQL concurrency harness（2026-08-15）**
  - 新增专用 settings 与 opt-in component，覆盖空 root first-winner、同 predecessor successor 单赢家和 rollback/no-orphan；数据库必须是本地/测试 PostgreSQL 且名称含 `evidence`/`test`，拒绝非空库、SQLite、VPS/生产 host
  - 默认回归 `3 skipped`；本轮 Docker daemon 未响应，尚未获得 disposable PostgreSQL 实际通过证据，因此 EVID-02 仍 planned，不能解除 owner/tenant lifecycle、production composition 或执行总闸
- ✅ **EVID-02 VPS current-head SELECT-only observation（2026-08-23）**
  - 对候选 `4cef9040c` / release `20260822134658` 以同一 `default` PostgreSQL alias 执行一次 `REPEATABLE READ READ ONLY` 查询；canonical approval/activation 账本均为 `0` 行，外部 envelope 与 content-addressed head-audit report 已分别落盘
  - 这是只读事实采集，不是 approval/activation 写入、生产并发/rollback、owner/reviewer 签署或 Evidence hard-gate 证据；`production_claim=false`、`production_ready=false`、`human_approval_status=not_collected`，EVID-02 继续 `awaiting_production`
- ✅ **Evidence owner/tenant authority source schema-only ledger（2026-08-15）**
  - 新增零种子 `research_evidence_scope_source_v1` append-only ORM 表与 `0028` migration；逐列保存 scope/artifact projection、canonical payload、identity/content hashes、root/successor/predecessor、PIT clocks 和 fixed read-only/non-execution flags，ORM shortcut 与 delete 全部 fail closed
  - isolated component `4 passed`，source 读/codec/Domain/facade 合计 `56 passed`，Django check、migration drift、增量 mypy、architecture audit、Black/isort、compile 通过；仅 schema/guard contract，未接 repository/provider/生产 route
- ✅ **Evidence owner/tenant authority source repository（2026-08-15）**
  - public exact/PIT/current-head reader 与 private atomic append store 已完成；selector/append 前全表 canonical restore、逐列 header/chain 校验、root/successor predecessor CAS、exact replay、terminal/expired no-fallback、tamper/rollback fail closed；repository `6 passed`，schema+repository `10 passed`，组合回归 `66 passed`
  - 仅本地 repository/schema contract；PostgreSQL 空链并发、可信 owner/tenant immutable lifecycle/provider、production composition、人工授权和 route 仍未完成，Evidence hard gate、写入和 execution 继续关闭
- ✅ **Evidence owner/tenant authority source dormant provider adapter（2026-08-15）**
  - `EvidenceScopeSourceV1Provider` 只接受服务端 selector，先走 current reader 完整重验 source identity/content/artifact/PIT/current，再投影现有 `EvidenceScopeGrant`；缺 selector、source substitution、terminal/expired、reader unavailable/corruption 均 fail closed；provider `15 passed`，组合回归 `79 passed`
  - 仅 dormant Application adapter，未读取 mutable User/session/tenant、未创建可信 selector lifecycle/provider composition、未接 API/人工授权/production route；PostgreSQL 并发、Evidence hard gate、写入和 execution 继续关闭
- ✅ **Web→TUI M5-C alias target checker correction（2026-08-14）**
  - 最终库存检查器同时读取 published graph 与 IA `published_screens`/`runtime_screens`，因此 runtime 注入的 `capability-router.mcp-center` 会被正确视为 canonical target；`capability-router.gateway` dangling 误报已消除
  - 11 个无活生产代码消费者的 dead alias 仍需真实流量观察、逐 wave 与回滚证据后再清理；M5 final 仍 DENY
- ✅ **Data Center architecture inventory source snapshot（2026-08-14）**
  - 重新生成并复核架构清单：cross-App ORM 48、current-data surface 4225、data-write decorators 58、runtime config references 49；Data Center/Provider 外部直连、legacy fact 与待审外部 HTTP 均为 0
  - 这是静态源码治理证据，不是生产 PostgreSQL/VPS、备份恢复、shadow reconciliation 或 M9 destructive migration 证据；生产切换继续 DENY
- ✅ **AI-Native local release gate（2026-08-14）**
  - `config/ai_native/ai_native_release_gate.v1.json` 与 `scripts/check_ai_native_release_gate.py` 冻结并校验 API、SDK、MCP、TUI provenance、migration 和 test assets；定向测试 `3 passed`
  - 首页聊天已复用共享 `AgomChatWidget`，Node 前端回归 `33 passed`，本地 Playwright 普通提问/建议执行与取消流通过；真实候选/生产浏览器 UAT、staging 和 owner/reviewer 人工双签仍缺，机器 gate 继续 `DENY`
- ✅ **系统级统一审计日志 M0 事件注册表（2026-08-14）**
  - `governance/audit_event_contracts.json` 与 `scripts/check_audit_event_contracts.py` 冻结 7 个顶层 category：20 个 Data Reliability 事件有完整合同，其余 6 类保留 source-file inventory；已接入 consistency workflow，定向测试 `5 passed`、治理 wiring `29 passed`，当前明确为 `shadow/registry_only/not_wired`
  - 尚未创建 Event Model、migration、outbox 或业务双写；未知事件仍应拒绝登记，M1+ 与生产审计覆盖继续待评审
- ✅ **系统级统一审计日志 M1 Domain/codec 最小合同（2026-08-14）**
  - `apps/audit/domain/system_audit_event.py` + `apps/audit/infrastructure/system_audit_event_codec.py` 封存 typed envelope、correlation/evidence refs、UTC clocks、stream predecessor/idempotency 与 domain-separated hashes；定向 `5 passed`、增量 mypy `0 regressions`
  - 仍未接运行写入口；本地合同不替代 PostgreSQL 并发、生产审计覆盖和运行接线
- ✅ **系统级统一审计日志 M1 schema-only ledger/outbox 基座（2026-08-14）**
  - 新增 `audit_system_event` 与 `audit_system_outbox` 两张 zero-seed 表及迁移 `0011`；事件/载荷的 append-only guards、outbox claim-state 边界和两套隔离 component 均通过（`3 + 3 passed`），Domain/codec 回归 `10 passed`
  - 仍无 repository/query/dispatcher/Data Center 双写或生产 runtime wiring；SQLite/schema 证据不替代 PostgreSQL 并发、真实迁移回滚、outbox 恢复、生产审计与双写覆盖
- ✅ **系统级统一审计日志 M1 ledger repository/query 合同（2026-08-15）**
  - 事件 repository 完成 strict full-world restore、exact/first-winner/PIT/head/list 与 predecessor CAS；staff-only query DTO/Protocol 完成分页与 exact selector 重验；repository component `5 passed`、query unit `5 passed`、增量 mypy `0 regressions`
  - 仍无 outbox dispatcher、Data Center 双写、业务 runtime wiring 或生产 authority composition；SQLite/纯测试不替代 PostgreSQL 空链并发、真实迁移回滚与生产审计覆盖；专用 PostgreSQL race harness 已就绪但尚未运行
- ✅ **系统级统一审计日志 M1 PostgreSQL 并发证据 harness（2026-08-15）**
  - 显式 opt-in harness 修正 pytest 隔离库 fixture 顺序，并直接执行 migration `0011` 的 PostgreSQL forward/backward；在临时 Docker `postgres:16-alpine` 的 `test_audit_test` 上完成空 stream first-winner、同 predecessor CAS、outbox claim lease ownership 与 rollback 后重新 claim，`4 passed`（194.64s）；容器已删除
  - 仅代表本机真实 PostgreSQL 隔离库的软件证据，不代表生产 VPS/PG、完整迁移回滚、backlog/恢复、Data Center 双写、publisher/runtime wiring 或生产审计覆盖；M1 registry gate 继续阻断
- ✅ **系统级统一审计日志 M1 staff query actor binding（2026-08-15）**
  - Staff reader context 现在要求 `actor_id == django-user:{user_id}` 才能触碰 repository，未绑定 actor 直接 fail-closed；query unit `6 passed`、增量 mypy `0 regressions`
  - 仅校验请求上下文内部绑定，不替代 authenticated user/RBAC authority source、owner scope、PostgreSQL 或生产 composition，M1 gate 不变
- ✅ **系统级统一审计日志 M1 outbox claim/dispatcher 合同（2026-08-15）**
  - Outbox repository 完成全表 payload/codec restore、private exact-insert claim、enqueue first-winner、private UOW、due claim、worker/token ownership 与 delivered/failed 状态机；dormant dispatcher Protocol/use case 输出 bounded outcome；component `7 passed`、dispatcher unit `3 passed`、增量 mypy `0 regressions`
  - 未接真实 publisher、业务双写、Data Center runtime 或生产 composition；SQLite/纯 fake 不替代 PostgreSQL claim race/lease、backlog 恢复、真实迁移回滚和生产审计覆盖；专用 harness 默认 `4 skipped`，未把 SQLite 计为 PostgreSQL 证据
- ✅ **系统级统一审计日志 M1 outbox transition guard（2026-08-15）**
  - Outbox 现有行的 ORM `save/save_base`、QuerySet/manager `update/bulk_update` 均要求 repository 私有 transition capability，直接状态绕过会 fail-closed；定向模型/repository/dispatcher 回归 `10 passed`、增量 mypy `0 regressions`
  - 仅关闭本地状态绕过写入；expired lease reclaim、mixed batch accounting、真实 PostgreSQL race/lease、backlog 恢复、业务双写和生产 publisher 仍待完成，M1 gate 不变
- ✅ **系统级统一审计日志 M1 expired-lease recovery（2026-08-15）**
  - `claim_due()` 现在按正 lease TTL 回收过期 claimed 行；新 worker 获得新 token、attempt 递增，旧 token 不能 finalize；定向 outbox model/repository/dispatcher 回归 `11 passed`、增量 mypy `0 regressions`
  - 仅证明本地 lease 状态机；mixed batch accounting、真实 PostgreSQL 双连接 race/lease、backlog 观测、业务双写和生产 publisher 仍未完成，M1 gate 不变
- ✅ **系统级统一审计日志 M1 dispatcher mixed-batch accounting（2026-08-15）**
  - dormant dispatcher 现在覆盖成功+失败混合批次的精确计数与 `partial` outcome，以及空批次 `noop`；dispatcher/event unit 回归 `10 passed`
  - 仅纯 fake Application 证据；真实 publisher、批量事务、PostgreSQL lease race、backlog 观测、业务双写和生产审计仍待完成，M1 gate 不变
- ✅ **系统级统一审计日志 M1 outbox backlog/recovery observability contract（2026-08-15）**
  - 新增只读 `SystemAuditOutboxBacklogSnapshot`/use case 与 repository 聚合读取；全表 closed-world restore 后统计 pending/claimed/failed/delivered、due pending、expired claim、oldest age；Application unit `9 passed`、repository component `7 passed`、增量 mypy `0 regressions`
  - PostgreSQL opt-in harness 已补 backlog 聚合/只读断言，但本批未启动 disposable PostgreSQL；仅本地读取/聚合契约，未接 Prometheus/health、publisher/runtime、自动恢复或生产告警，真实 PostgreSQL backlog/恢复观察、生产迁移回滚、Data Center 双写与 authority source 仍待完成，M1 gate 不变
- ✅ **系统级统一审计日志 M1 outbox closed-world clock/state hardening（2026-08-15）**
  - restore 现在闭合 available/claim/delivery/failure/updated 时序，拒绝各状态残留的跨状态字段，并对 future observation cutoff fail-closed；raw-tamper component 与 outbox model/repository/dispatcher 回归 `32 passed`、增量 mypy `0 regressions`
  - 仅加强本地 fail-closed；PostgreSQL 双连接竞争、生产 backlog 观察、publisher/runtime、自动恢复、生产迁移回滚与生产审计覆盖仍待完成，M1 gate 不变
- ✅ **系统级统一审计日志 M1 outbox backlog health projection wiring（2026-08-15）**
  - Audit health 现在消费只读 backlog snapshot，投影 pending/due/claimed/expired/failed/delivered 与 oldest age；recovery work 为 WARNING、异常只发布类型；unit/API `16 passed`
  - 仅 health projection wiring；Prometheus/runtime publisher、自动 reclaim、生产 migration/rollback、真实 PostgreSQL backlog 观察与 Data Center 双写仍待完成，M1 gate 不变
- ✅ **系统级统一审计日志 M1 bounded outbox backlog Prometheus projection contract（2026-08-15）**
  - 新增固定 `owner=audit` 的 pending/oldest-age/due/claimed/expired/failed/delivered gauges；仅接收已验证 backlog snapshot，不读库、不 claim、不 publish、不暴露高基数或敏感标签；metrics safety + backlog Application 回归 `23 passed`
  - 仅 dormant projection sink，尚未接 `/metrics/` scrape、health scheduler、Celery、publisher 或 failed-row retry；生产 migration/rollback、PostgreSQL backlog 观察/恢复、Data Center 双写仍待完成，M1 gate 不变
- ✅ **系统级统一审计日志 M4 `/metrics/` lazy backlog projection wiring（2026-08-15）**
  - Audit application provider 固定 `default` alias 与 aware `timezone.now()` cutoff，`metrics_view` lazy 调用并在 reader/restore/projection 异常时保持通用 scrape 200；provider/view/指标回归 `33 passed`，异常日志仅含类型且 owner label 仍固定为 `audit`
  - 这是单进程 scrape-time 的只读 projection wiring，不是生产 PostgreSQL backlog 观察、自动恢复、publisher/Celery/retry 或告警闭环；Data Center 双写仍保持 `planned/not_wired`，M4/M1 gate 不变
- ✅ **系统级统一审计日志 M1 Data Center RawAudit identity boundary（2026-08-15）**
  - `RawAudit` 新增稳定 row identity、run/ingested-run 关联与 canonical content hash；历史缺字段行向 fetch event 的提升 fail-closed；迁移 `0070` 仅 nullable expand、不回填；RawAudit/SyncMacro/Macro publication `15 passed`
  - 仅 evidence boundary；尚未接服务端 run issuer、共同 UOW、事实/Health/RawAudit/Publication/event/outbox 双写或 PostgreSQL 生产证据，`data.fetch.*` 仍 `planned/not_wired`
- ✅ **系统级统一审计日志 M1 Data Center SyncExecution identity contract（2026-08-15）**
  - 纯 Application `SyncExecutionIdentity`/issuer port 固定 server-issued run/ingested-run/batch UUID 与 domain-separated identity hash；command 不接受 caller identity/clock，纯测试 `8 passed`，增量 mypy/architecture/格式门禁通过
  - 仅 dormant identity boundary；尚无 issuer persistence、SyncMacro 同 UOW、事实/Health/RawAudit/Publication/event/outbox 双写、迁移回填或 PostgreSQL 证据，`data.fetch.*` 仍 `planned/not_wired`
- ✅ **系统级统一审计日志 M1 Data Center SyncExecution identity persistence boundary（2026-08-15）**
  - 新增 strict `SyncExecutionIdentityRepositoryPort`/persist use case、schema-only migration `0071` 与 private insert-claim/append-only ORM guards；完整 identity exact replay，hash/context/ID 冲突 fail-closed；纯/migration/SQLite component 合计 `16 passed`，`makemigrations --check` 通过
  - 仅 owner-issued identity persistence boundary；未接 SyncMacro writer/共同 UOW/事实/Health/RawAudit/Publication/event/outbox 双写、历史回填、生产 PostgreSQL race/rollback，`data.fetch.*` 仍 `planned/not_wired`
- ✅ **系统级统一审计日志 M1 outbox dispatch task fail-closed contract（2026-08-15）**
  - Celery dispatch task 在 canonical publisher 未组装时于 claim 前返回 `blocked`，不使用通用 Events/memory/eager fallback；输入、blocked、composition failure `4 passed`，Celery manifest `88 registered / 22 governed files` 通过
  - 仅 dormant task/gate；无 durable publisher、claim/retry/requeue、beat schedule、业务双写、生产 broker/PG 或自动恢复证据，system-audit publisher/runtime gate 继续阻断
- ✅ **系统级统一审计日志 M1 event/outbox atomic composition contract（2026-08-15）**
  - 新增 dormant 同 alias coordinator，event append 与 outbox enqueue 同 outer transaction；exact retry、event substitution、outbox failure rollback 已覆盖；unit `5 passed`、SQLite component `3 passed`、增量 mypy/architecture 通过
  - 尚未接 Data Center `data.fetch.*`、publisher/runtime 或生产 route；真实 PostgreSQL 双写竞争、migration/rollback 与业务事件仍待完成，M1 gate 不变
- ✅ **系统级统一审计日志 AUD-01 composition preflight contract（2026-08-15）**
  - 新增纯 Application publisher/authority boundary：publisher 必须返回 exact event-preservation receipt，authority 必须来自注入 provider；dispatcher 对 envelope substitution、generic/memory 风格返回值与未绑定 authority 均 fail closed；audit 定向回归 `20 passed`
  - 仅完成本地合同与阻断边界；runtime 仍固定 `publisher_not_wired`，没有 durable sink、authenticated scoped lifecycle、beat/retry/PG/VPS 证据，AUD-01 未解除，AUD-02 继续等待
- ✅ **系统级统一审计日志 AUD-01 authority boundary hardening（2026-08-15）**
  - authority cutoff 严格要求 aware `datetime`；provider 异常或错误类型结果统一脱敏为 `authority_unavailable`，不泄露数据库/RBAC异常；定向 unit `15 passed`，增量 mypy/architecture/Black/isort/diff-check 通过
  - 仍未接真实 authenticated scoped authority、durable publisher/receipt sink、beat/retry、PostgreSQL/VPS 证据；`AUD-01` 未解除，`AUD-02` 继续等待
- ✅ **当前候选部署与运行取证（AUD-01/TUI，2026-08-15）**
  - `dev/next-development@cf68dc1e9` 已部署为 release `20260815182857`；manifest/OCI/source 绑定一致，HTTPS health/ready、容器、迁移、canonical schema、TUI registry、Qlib、Celery 复核通过，部署前 PostgreSQL 备份成功
  - `/api/ready/` 仍报告 Alpha/Qlib degraded、workspace recommendation stale 和 market thermometer partial-stale warnings；只更新候选身份与运行证据，不解除 AUD-01、M5、DATA-01 或相关 rollback/观察门禁
- ✅ **系统级统一审计日志 AUD-01 canonical receipt exact-tree hardening（2026-08-15）**
  - receipt 在 JSON 编码前递归校验容器/标量类型、序列顺序与 key 类型；tuple/list、嵌套非原生 mapping 和标量类型替换统一 fail-closed 为 `publisher_contract_violation`；composition/dispatcher/dispatch 定向回归 `30 passed`，audit contract、增量 mypy、architecture、Black/isort、compile/diff-check 通过
  - 仅本地 receipt 合同加固（当前环境未安装 ruff 模块）；runtime 仍固定 `publisher_not_wired`，没有 durable publisher/receipt sink、authenticated scoped lifecycle、beat/retry/PG/VPS 证据，`AUD-01` 未解除，`AUD-02` 继续等待
- ✅ **系统级统一审计日志 AUD-01 preflight-to-receipt sink binding（2026-08-16）**
  - preflight 仅执行一次并把已验证 `sink_id` 绑定到每条 delivery receipt；sink substitution、publisher contract drift fail-closed；composition/dispatcher `47 passed`，task/authority `10 passed`，增量 mypy/architecture/governance 通过
  - 仍无 durable publisher/receipt sink、authenticated scoped authority、Celery beat/retry、Data Center 同 UOW 或 PostgreSQL/VPS 投递证据，runtime 继续 `publisher_not_wired`，`AUD-01` 未解除
- ✅ **EVID-01 nested artifact invariant hardening（2026-08-16）**
  - scoped grant boundary 对嵌套 `ArtifactRef` 重新执行完整 invariant，provider 原地篡改并重算 grant hash 时 fail-closed；scope/source/provider/facade `71 passed`，增量 mypy/architecture/governance 通过
  - 仅本地 owner-scoped boundary；immutable owner/tenant lifecycle、人工授权、PostgreSQL 生产证据与 Evidence hard gate 仍缺，`EVID-01` 状态不变
- ✅ **DATA-02 primary-key collision identity guard（2026-08-16）**
  - control-plane upsert 在自然键未命中而 primary key 冲突时按完整 lookup+identity 复核，稳定拒绝 batch/checkpoint 身份替换；`test_control_plane.py` `12 passed`，增量 mypy/Black/isort/diff-check 通过
  - 仅本地幂等合同；未连接生产 PostgreSQL、未执行 restore/backfill/reconciliation/rollback，`DATA-01/02/03` 状态不变
- ✅ **EVID-01 critical execution-test contract alignment（2026-08-16）**
  - 关键 broker/agent 测试对齐当前 Evidence hard gate：create/approve/lease/Fake Agent 在 evidence 未接入时稳定阻断、订单保持 `WAITING_APPROVAL`；`tests/critical` 两文件 `13 passed`，Black/isort/py_compile/diff-check 通过
  - 仅修正过时测试合同；未放宽 execution gate、未接入 publisher/authority；全仓 mypy debt 与 module-cycle baseline 仍需独立治理，`EVID-01` 继续 active
- ✅ **DATA-01 production PostgreSQL backup evidence refresh（2026-08-15）**
  - `scripts/backup-vps-postgres.ps1` 重新取得并验证 custom-format 归档（`139057048` bytes，SHA-256 `a8f005eb3a461f28d21689ecef6d5aee89b59a353d06944b79e08c82662839cc`）；仅完成备份子步骤，维护态/恢复/回滚/回填仍未通过，DATA-01 继续 awaiting
- ✅ **DATA-01 latest PostgreSQL backup refresh（2026-08-15）**
  - 候选 `a76db97d` 部署前以 `-DownloadLatest` 下载并校验 `postgres-20260815-093506.dump`（`140095243` bytes，SHA-256 `a1e7092aacc1241525ba52a083395f3d38bb0b88c7b8f6436b3ad508f4520bc0`）；远端 `pg_restore --list`、尺寸与本地校验通过，prune 未启用
  - 仍不等于 restore/rebuild、维护态回滚、回填或 reconciliation；DATA-01 继续 awaiting，不解锁 DATA-02/03
- ✅ **DATA-01 post-deploy backup refresh（2026-08-15）**
  - 最新候选 `ae1e5e532` / release `20260815162419` 部署后重新下载并校验 `postgres-20260815-103019.dump`（`140112628` bytes，SHA-256 `46dd5003de2943ac23d8ab599c24454e3e770b7828b088857be355fa4f5a364d`）；远端 `pg_restore --list`、完整下载、尺寸与本地校验通过
  - 仅恢复点证据；没有 restore/rebuild、维护态回滚、回填或 reconciliation，DATA-01 继续 awaiting，不解锁 DATA-02/03
- ✅ **DATA-01 local restore/rebuild verification attempt（2026-08-15）**
  - 既有恢复脚本合同单测 `10 passed`；临时 PostgreSQL 容器在 `initdb` bootstrap 超时，专用本地数据库的归档传输又被 Docker Desktop API 超时阻断，未执行 `pg_restore`/快照对比；专用数据库和临时文件已清理，未写 VPS
  - 不产生 restore/rebuild、RTO 或回滚通过证据；DATA-01 继续 awaiting，不解锁 DATA-02/03
- ✅ **DATA-01 当前候选部署后 backup refresh（2026-08-15）**
  - `cf68dc1e9` 部署后以 `scripts/backup-vps-postgres.ps1 -DownloadLatest` 下载并验证 `postgres-20260815-123539.dump`，`140176474` bytes，SHA-256 `e1c0821543a36f19d2ea292d9c4fdc544003010579ccef5df9175d083a2e2e2f`；远端 `pg_restore --list`、SFTP、尺寸与本地校验通过
  - 仍只是恢复点；本机缺 `pg_restore`/`psql` 且 Docker restore 链路此前超时，没有 restore/rebuild、维护态回滚、回填或 reconciliation，DATA-01 继续 awaiting
- ✅ **DATA-01 restore evidence input immutability + current backup refresh（2026-08-16）**
  - `scripts/verify_postgres_backup_restore.py` 现在在格式校验前、恢复前后固定 dump SHA-256，并对归档替换稳定 fail-closed；unit `14 passed`、增量 mypy 0
  - 当前 VPS custom-format backup 已完整下载并校验：`postgres-20260816-100924.dump`，`140804438` bytes，SHA-256 `06e52b33c637c17cae4c9f0223246e0e09af84254717196d904f67044e7b2cba`
  - 仍不等于 restore/rebuild、维护态回滚、RTO/RPO、回填或 reconciliation；DATA-01 继续 awaiting，不解锁 DATA-02/03
- ✅ **DATA-01 最新归档本机隔离 restore 验收（2026-08-20）**
  - 最新 `postgres-20260820-110946.dump` 在唯一命名 disposable `postgres:16-alpine` 中 source↔restore 自洽通过：537/537 public 表、72/72 Data Center migrations、458/458 sequences、schema/table/migration/content hash 全匹配；restore `2061.820s`、verification `1017.837s`、total `4866.916s`。证据：[`data01-local-isolated-restore-2026-08-20.json`](deployment/data01-local-isolated-restore-2026-08-20.json)
  - 只证明本机隔离恢复自洽，不是生产 RTO/RPO、维护态 rollback、生产 restore/DDL、回填或 reconciliation；`DATA-01` 继续 awaiting，不解锁 DATA-02/03
- ✅ **DATA-01 最新归档本机隔离 restore 验收（2026-08-22）**
  - 新归档在 disposable `postgres:16-alpine` source↔restore 自洽通过：539/539 public 表、72/72 Data Center migrations、460/460 sequences、schema/逐表内容/sequence 差异均为 `0`；restore `1144.211s`、verification `945.14s`、total `3358.717s`。证据：[`data01-local-isolated-restore-2026-08-22.json`](deployment/data01-local-isolated-restore-2026-08-22.json)，报告 SHA `33b7217d839b3036934ef0d3d2fbb45b61fd412af44ec354680e9a260b9c50a0`
  - 只证明本机隔离恢复自洽，不是生产 RTO/RPO、维护态 rollback、生产 restore/DDL、回填或 reconciliation；`DATA-01` 继续 awaiting，不解锁 DATA-02/03
- ✅ **DATA-02 control-plane identity reuse guard（2026-08-16）**
  - `SyncRun/SyncBatch/SyncCheckpointRepository` 对 stable key 重试逐字段核对不可变身份，拒绝 dataset/provider/run/checkpoint 替换；identity-reuse 回归通过，增量 mypy `0 regressions`、Black/isort/diff-check 通过
  - 仅本地幂等/身份合同；未连接生产数据库、未执行 restore/backfill/reconciliation，PostgreSQL 锁/并发、RTO/RPO 与 DATA-01 前置仍缺，DATA-01/02/03 状态不变
- ✅ **VPS candidate deployment with account migration/data-center fixes（2026-08-15）**
  - `ae1e5e532` 以 release `20260815162419` 完成 git-clone/provenance 校验和代码-only upgrade；health/ready HTTP 200，web/worker/beat/PostgreSQL/Redis/RSSHub 正常，迁移步骤无待应用项，canonical schema `missing_migrations=[]`/`missing_tables=[]`，TUI/Qlib/Celery 复核通过
  - `/api/ready/` 仍有 Alpha/Qlib、workspace 与市场温度计 freshness warnings；不解除 decision-data、TUI M5、DATA-01/02/03 或 AUD-01 gate
- ✅ **DATA-02 backfill control-plane PostgreSQL preflight contract（2026-08-15）**
  - 新增 PostgreSQL-only fake-provider 控制面预演：重试幂等、唯一 `run/batch/checkpoint` 和 partial 计数契约；本地 SQLite 仅 `1 passed, 2 skipped`，任务单元 `8 passed`，PostgreSQL-only 尚待 CI/一次性服务执行，不能作为生产回填或锁证据
- ✅ **DATA-02 control-plane atomic snapshot rollback（2026-08-15）**
  - run、batch、checkpoint 三个持久化调用由 Data Center composition root 统一包在同一事务；注入 checkpoint 写入失败时三张表均保持零行；组件 `2 passed, 2 skipped`、任务单元 `8 passed`，architecture/mypy/Celery/格式门禁通过
  - 仅本地事务/回滚证据；PostgreSQL-only 并发与锁预算、生产回填、coverage/reconciliation 仍未取得，`DATA-02/03` 继续 waiting
- ✅ **Equity research snapshot Django runtime contract（2026-08-14）**
  - Django 5.2.12 复跑 API `15`、SDK/MCP/routing/evidence `36`、use case/gateway `26`，合计 `77 passed`
  - 仅证明 mock/fake 隔离环境的软件契约与 fail-closed 行为；真实数据覆盖、PostgreSQL 规模/故障注入、备份恢复和 readiness 仍未解除
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

### 2026-08-24

- TAR-05 当前候选认证保留路由只读阶梯证据：[`tar01-current-reserved-route-observation-2026-08-24-94abd76e.json`](deployment/tar01-current-reserved-route-observation-2026-08-24-94abd76e.json)。
- DATA-02 当前候选 coverage/freshness 只读证据：[`data02-coverage-freshness-observation-2026-08-24-94abd76e.json`](deployment/data02-coverage-freshness-observation-2026-08-24-94abd76e.json)，active A-share=`5,533`，fact coverage 完整但 canonical publication 不完整，`decision-ready=503` fail-closed；不解除 DATA-02 或决策门禁。
- EVID-01 本地 authority/composition focused revalidation：Account/Research/Core/Audit 合同 `93 passed`；仅证明 fail-closed 本地边界，VPS authority ledger 仍 zero-seed，不解除 EVID-01 或全局决策/执行门禁。
- EVID-01 候选漂移最新复核：当前 HEAD `271513f2a` 相对 VPS 候选 `94abd76e…` 的 12 个非文档/治理差异均为 TUX-02 TUI 文件；无后端生产代码漂移，因此不重复部署。

### 2026-08-25

- EVID-01 owner/tenant authority same-alias guard：`GetCurrentOwnerTenantAuthorityV1` 暴露 repository `unit_of_work_key`，authenticated Evidence bridge 拒绝跨 `django:{using}` alias 的 authority reader；新增回归后 focused contract `94 passed`，本地质量与 mypy/debt 门禁通过。未 seed/写生产/部署或批准，VPS authority ledger 仍 zero-seed，EVID-01 与 decision-ready fail-closed 不变。

### 2026-09-02

- 当前 `dev/next-development` 已同步至 `140bf23fcdacdd92160ec59286eabba88e156252`；deterministic Data Center architecture/entrypoint inventories 已按合并源码刷新，Architecture、Security、Consistency、Fast Feedback 四条 CI 全绿。
- 当前受控 VPS 候选仍为 `aa7127ff4d9f71555b0d0486314da5518bd2ac20` / release `20260901232812`；9/2 的只读部署、EVID/STRAT/AUD 快照和 TUI-02 retained-source 事实已回写计划 README。EVID/DATA/STRAT/AUD/TAR 生产门禁仍按注册表 fail-closed，TUI-02 观察窗口未到期，不重复部署或写生产。
- EVID-04 跨平台 content-addressed fixture 已完成；修复只影响 repository fixture bytes，不改变生产 raw-byte provenance、authority zero-seed 或 `decision-ready` 阻断。

**文档维护**: AgomTradePro Team
**最后更新**: 2026-09-02
