# 文档归档索引

> **归档日期**: 2026-08-15
> **说明**: 本目录存放已完成的过程性文档，供历史参考

---

## 归档分类

### 1. Phase 实施总结 (plans/)

| 原文件 | 说明 | 完成日期 |
|--------|------|----------|
| phase1-alpha-implementation-summary.md | Alpha 抽象层实施 | 2026-02-05 |
| phase2-qlib-inference-summary.md | Qlib 推理实施 | 2026-02-05 |
| phase3-training-summary.md | 训练流水线实施 | 2026-02-05 |
| phase4-monitoring-summary.md | 评估监控实施 | 2026-02-05 |
| phase5-integration-summary.md | 宏观集成实施 | 2026-02-05 |
| phase2-rotation-implementation-summary.md | Rotation 模块实施 | 2026-02-05 |
| phase-3-factor-implementation-summary.md | Factor 模块实施 | 2026-02-05 |
| phase-4-hedge-implementation-summary.md | Hedge 模块实施 | 2026-02-05 |
| factor-rotation-hedge-implementation-summary.md | 智能模块综合总结 | 2026-02-05 |

**综合参考**: `plans/implementation-progress-summary.md` (保留为活跃文档)

### 2. 修复记录 (fixes/)

| 原文件 | 说明 | 完成日期 |
|--------|------|----------|
| 2026-02-17-static-api-cleanup.md | 静态资源清理 | 2026-02-17 |
| api-routing-governance-plan-2026-02-18.md | API 路由治理 | 2026-02-18 |
| template-convergence-plan-2026-02-18.md | 模板收敛 | 2026-02-18 |

### 3. 前端改造 (frontend/)

| 原文件 | 说明 | 完成日期 |
|--------|------|----------|
| epic-a-refactor-checklist-2026-02-18.md | Epic A 改造清单 | 2026-02-18 |
| equity-fund-refactor-guide-2026-02-18.md | 证券分析改进 | 2026-02-18 |
| routing-governance-report-2026-02-18.md | 路由治理报告 | 2026-02-18 |
| visual-consistency-report-2026-02-18.md | 视觉一致性报告 | 2026-02-18 |

### 4. 外包协作 (development/)

| 原文件 | 说明 | 完成日期 |
|--------|------|----------|
| outsourcing-task-book-2026-02-22.md | 外包任务书 | 2026-02-22 |
| rectification-2026-02-23.md | 整改报告 | 2026-02-23 |

### 5. UAT 测试 (testing/)

| 原文件 | 说明 | 完成日期 |
|--------|------|----------|
| uat-memo-2026-02-07.md | UAT 备注 | 2026-02-07 |
| UAT_E2E_Test_Report_2026-02-21.md | E2E 测试报告 | 2026-02-21 |
| uat-route-baseline-2026-02-21.md | 路由基线 | 2026-02-21 |
| outsourcing-test-fix-review-2026-02-20.md | 测试修复审查 | 2026-02-20 |

### 6. 计划文档 (plans/)

| 原文件 | 说明 | 完成日期 |
|--------|------|----------|
| decision-platform-enhancement-2026-02-04.md | 决策平台增强 | 2026-02-04 |
| uat-execution-plan-2026-02-18.md | UAT 执行计划 | 2026-02-18 |
| ui-ux-improvement-prd-2026-02-18.md | UI/UX PRD | 2026-02-18 |

---

## 使用说明

1. 归档文档仅供历史参考，不代表当前系统状态
2. 活跃文档请参考 `docs/INDEX.md`
3. 如需恢复某文档，请复制到对应目录并更新 INDEX.md

### 10. 计划目录整理归档（2026-08-12）

本批从 `docs/plans/` 迁入 44 份已完成文档。归档标准是“仓库范围已经实现、阶段已经验收或已被后续计划取代”；仍有真实数据、生产 cutover、外部环境或上线验收门禁的文档继续留在活跃计划目录。

#### 发布、产品与数据能力

- `0.8.0-release-closure-plan-2026-07-05.md`
- `auto-advisor-prd-2026-06-25.md`
- `auto-advisor-implementation-2026-06-25.md`
- `personal-auto-advisor-roadmap-2026-06-30.md`
- `production-code-remediation-plan-2026-06-26.md`
- `data-mid-plat-260405.md`
- `eastmoney-integration.md`

#### 工程治理与阶段收口

- `architecture-cycle-remediation-2026-04-26.md`（由 2026-07-15 后续计划取代）
- `ci-stabilization-2026-07-13.md`
- `large-file-remediation-2026-07-14.md` 及 7 份分模块记录
- `provider-abstraction-convergence-2026-07-18.md`
- `repository-debt-remediation-closure-2026-07-19.md`
- `repository-governance-debt-2026-07-19.md`
- `mypy-debt-remediation-2026-07-19.md`
- `maintainability-refactoring-plan-2026-07-20.md` 及 `maintainability-r0/`、`maintainability-r2/`、`maintainability-r3-lite/`、`maintainability-stability/`
- `testing-improvement-plan-2026-07-24.md`
- `tui-regime-display-contract-postmortem-2026-07-30.md`

#### 已完成里程碑证据

- `regime-navigator/`（总方案与 Phase 1–3）
- `web-to-tui-m0-evidence-2026-07-26.md`
- `web-to-tui-m1-chart-evidence-2026-07-26.md`
- `web-to-tui-m2-consolidated-evidence-2026-07-26.md`
- `web-to-tui-m3-consolidated-evidence-2026-07-26.md`
- `web-to-tui-m4-consolidated-evidence-2026-07-26.md`

活跃入口与保留理由见 [`../plans/README.md`](../plans/README.md)。

#### 同日后续补归档

- `architecture-cycle-remediation-2026-07-15.md`（最终实现零双向依赖、零强连通循环组件）
- `tui-ia-consolidation-2026-07-20.md`（AgomTradePro 主计划已实施；跨仓兼容后续由独立可移植性计划承接）

#### 2026-08-15 限期审查队列收口

- `macro-sizing-multiplier-outsourcing-2026-03-31.md`（实现资产已存在；source freshness、config/version/hash、owner scope 与 exact-current 残余验收转入 Evidence `EVID-03`）
- `post-0.8.0-stabilization-priority-2026-07-08.md`（过期两周排期归档；未完成生产门禁按 S1-S10 转入当前 Data / Strategy / Evidence / TUI 工作流）

#### 2026-08-15 review queue 七项收口

- `account-performance-260401.md`：统一业绩/估值实现资产已存在；真实回填、owner scope、freshness/hash、exact-current 与 PostgreSQL 生产验收转入 Evidence `EVID-01/EVID-03`。
- `account-refactor-260327.md`：统一账本历史实施叙事被 Account Evidence-v3/Portfolio owner 边界取代；legacy 写路径、迁移覆盖/回滚和 provenance composition 转入 Evidence `EVID-01`，破坏性数据动作绑定 `DATA-01/02/03`。
- `admin-settings-closure-260404.md`：Classic admin/settings shell 收口归档；角色 UAT、保留页清理、观察窗口转入 Web→TUI `TUI-01/TUI-02`，Config Center 生产 profile 仍归 Data Center。
- `alpha-exit-loop-2026-04-30.md`：退出 advisor 与 BUY→TRACK→SELL 实施方案归档；真实数据、Evidence exact-current、执行授权和 UAT 转入 `STRAT-02/03` 与 `EVID-03`。
- `alpha-homepage-upgrade-260416.md`：Classic Alpha 首页方案由 `research.signals`/TUI 迁移取代；角色 UAT 转入 `TUI-01/TUI-02`，PIT/OOS 与 owner/receipt 转入 Strategy/Evidence。
- `streamlit-dashboard-upgrade-plan.md`：保留为兼容 sidecar 历史方案；独立 reverse-proxy/SSO/cutover 线取消，Regime/equity/signal 用户任务由 TUI 承接。
- `workflow-upgrade-260326.md`：旧漏斗设计被 Decision Workspace/Transition Plan 文档取代；legacy writer、receipt、exact-current 和执行门禁转入 Evidence `EVID-03`，Promotion/UAT 转入 `STRAT-03`。

上述七项均已在原文写入收口说明，未被误标为生产通过；残余工作只能通过现有 canonical closure unit 继续推进。

#### AI、Terminal 与 MCP 收口

- `mcp-consolidation-remediation-plan-2026-07-09.md`（统一 core surface、governed capability、legacy disposition 与写能力门禁已完成）
- `system-ai-capability-catalog-outsourcing-task-book-2026-03-19.md`（Catalog、自动采集、统一路由、权限与审计已完成）
- `terminal-mcp-governance-outsourcing-task-book-2026-03-19.md`（旧命令治理目标已完成，并由持久化 AgentProposal 审批架构承接）
- `terminal-refactor-plan-260709.md`（Agents SDK、MCP stdio、SSE 与持久审批已完成）

---

### 7. 过程性文档批量归档 (process/)

归档时间：2026-03-04

#### process/plans

- test-improvement-plan-from-report-2026-02-26.md
- system-code-doc-alignment-implementation-plan-2026-02-06.md
- sdk_mcp_coverage_matrix_20260226.md
- sdk-mcp-2026-02-26plan.md
- post-v34-followup-roadmap-2026-02-26.md
- a0049fd-acceptance-issues-2026-02-27.md
- home-workflow-outsourcing-spec-2026-03-01.md
- decision-workspace-topdown-bottomup-outsourcing-spec-2026-03-02.md
- outsourcing-valuation-pricing-execution-plan-2026-03-02.md
- outsourcing-p0p1-stability-hardening-plan-2026-03-04.md

#### process/testing

- TEST_REPORT_2026-02-26.md
- outsourcing-full-regression-plan-2026-02-26.md
- outsourcing-acceptance-plan-post-v34-2026-02-26.md

#### process/frontend

- ux-user-journey-checklist-2026-02-18.md
- ui-ux-full-page-audit-2026-02-18.md

### 8. 开发文档归档 (development/)

| 原文件 | 说明 | 归档日期 |
|--------|------|----------|
| module-dependency-graph.md | 模块依赖关系图（已被 `architecture/MODULE_DEPENDENCIES.md` 取代） | 2026-03-18 |

### 9. 架构计划文档归档 (plans/)

| 原文件 | 说明 | 归档日期 |
|--------|------|----------|
| architecture-audit-report-2026-04-22.md | 2026-04-22 架构审计与整改计划，已被 `docs/architecture/architecture-remediation-result-2026-04-26.md` 取代 | 2026-04-26 |
| architecture-audit-backlog-2026-04-22.md | 2026-04-22/24 架构审计积压快照，当前架构审计已清零 | 2026-04-26 |
| architecture-debt-remediation-260422.md | 指向旧审计报告的兼容跳转，随旧报告一起归档 | 2026-04-26 |

---

**归档维护**: AgomTradePro Team
**最后更新**: 2026-08-15
