# AgomTradePro 文档索引

> **AgomTradePro 0.7.0** - 个人投研平台
> **最后更新**: 2026-04-21
> **项目状态**: 生产就绪
> **版本管理**: [VERSION.md](VERSION.md)

---

## 快速导航

| 角色 | 入口文档 | 说明 |
|------|----------|------|
| **系统概览** | [SYSTEM_SPECIFICATION.md](SYSTEM_SPECIFICATION.md) | **完整系统说明书（技术+功能）** |
| **系统基线** | [governance/SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) | **单一叙事来源（版本/模块/部署/测试）** |
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

## 文档目录

### 0. 治理文档 (`governance/`) - 新增

| 文档 | 说明 | 状态 |
|------|------|------|
| [SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) | **系统基线（单一叙事来源）** | ✅ 2026-03-18 新增 |
| [MODULE_CLASSIFICATION.md](governance/MODULE_CLASSIFICATION.md) | **模块分级表（核心/成熟/试验）** | ✅ 2026-03-18 新增 |
| [DEVELOPMENT_BANLIST.md](governance/DEVELOPMENT_BANLIST.md) | **开发禁令（5条核心约束）** | ✅ 2026-03-18 新增 |

### 1. 架构设计 (`architecture/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [MODULE_DEPENDENCIES.md](architecture/MODULE_DEPENDENCIES.md) | **模块依赖关系文档（拓扑图+改进建议）** | ✅ 2026-03-18 新增 |
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
| [valuation-pricing-engine.md](business/valuation-pricing-engine.md) | **估值定价引擎业务文档** | ✅ 2026-03-02 新增 |
| [valuation-repair-config.md](business/valuation-repair-config.md) | **估值修复策略参数配置（在线调参/版本管理/回滚）** | ✅ 2026-03-11 新增 |
| [config-center-matrix.md](business/config-center-matrix.md) | **配置中心能力矩阵（前端/API/SDK/MCP/权限）** | ✅ 2026-03-11 新增 |
| [alpha-quickstart.md](business/alpha-quickstart.md) | Alpha 模块快速开始指南 | 完整 |
| [equity-valuation-logic.md](business/equity-valuation-logic.md) | 个股估值逻辑 | 完整 |
| [regime_calculation_logic.md](business/regime_calculation_logic.md) | Regime 计算逻辑 | 完整 |
| [signal_and_position.md](business/signal_and_position.md) | 信号与持仓关系 | 完整 |

### 3. 开发指南 (`development/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [quick-reference.md](development/quick-reference.md) | 快速参考手册 | ✅ 2026-03-31 更新 |
| [engineering-guardrails.md](development/engineering-guardrails.md) | **工程护栏与 PR Checklist（含 API 改动同步门禁）** | ✅ 2026-03-31 更新 |
| [../GIT_WORKFLOW.md](GIT_WORKFLOW.md) | **Git 工作流规范（`dev/*` 分支、commit、合并流程）** | ✅ 2026-03-23 新增 |
| [outsourcing-work-guidelines.md](development/outsourcing-work-guidelines.md) | **外包团队工作指南** | ✅ 必读 |
| [api_structure_guide.md](development/api_structure_guide.md) | API 结构指南 | 完整 |
| [coding_standards.md](development/coding_standards.md) | 代码规范 | 完整 |
| [decision-platform.md](development/decision-platform.md) | 决策平台实现 | 完整 |
| [debug-automation-log-api.md](development/debug-automation-log-api.md) | Codex/Claude 自动化调试日志 API | 完整 |
| [startup-scripts.md](development/startup-scripts.md) | 启动脚本使用指南 | 完整 |
| [module-ledger.md](development/module-ledger.md) | 模块账本（边界规则/依赖统计） | ✅ 2026-03-18 更新 |
| [system-review-report.md](development/system-review-report.md) | 系统审视报告 | ✅ 2026-03-18 更新 |
| [regime-chain-unification-2026-03-02.md](development/regime-chain-unification-2026-03-02.md) | Regime 统一计算链路说明 | ✅ 2026-03-02 |
| [api-route-consistency.md](development/api-route-consistency.md) | API 路由一致性分析 | ✅ 2026-02-20 |
| [frontend-performance-analysis.md](development/frontend-performance-analysis.md) | 前端性能优化分析 | ✅ 2026-02-20 |
| [frontend-development-standards.md](development/frontend-development-standards.md) | **前端开发规范（CSS/JS/模板/弹窗/HTMX）** | ✅ 2026-03-10 新增 |
| [error-handling-guide.md](development/error-handling-guide.md) | 错误处理改进指南 | ✅ 2026-02-20 |
| [api-mcp-sdk-alignment-2026-03-14.md](development/api-mcp-sdk-alignment-2026-03-14.md) | **API / MCP / SDK 契约对齐说明** | ✅ 2026-03-14 新增 |
| [dashboard-alpha-decision-chain-2026-04-12.md](development/dashboard-alpha-decision-chain-2026-04-12.md) | **Dashboard Alpha 决策链收束说明（含通用/专属拆分、解释面板、API/SDK/MCP）** | ✅ 2026-04-22 更新 |
| [data-reliability-remediation-checklist-2026-04-21.md](development/data-reliability-remediation-checklist-2026-04-21.md) | **数据可靠性修复清单（macro / quote / pulse / dashboard alpha）** | ✅ 2026-04-21 更新：新增 repair 流水线 |
| [unified-financial-datasource-registry.md](development/unified-financial-datasource-registry.md) | **统一财经数据源中台与统一注册表说明** | ✅ 2026-03-28 新增 |

### 4. 实施计划 (`plans/`)

> **说明**: 大部分计划已完成并归档到 `archive/plans/`，以下为进行中的重要计划

| 文档 | 说明 | 状态 |
|------|------|------|
| [implementation-progress-summary.md](plans/implementation-progress-summary.md) | **总体进度总结（Phase 1-5 完成）** | 最新 |
| [AI-native-blueprint-260315.md](plans/AI-native-blueprint-260315.md) | **AI Native 升级蓝图** | 进行中 |
| [AI-Native-upgrade-implement-plan-260315.md](plans/AI-Native-upgrade-implement-plan-260315.md) | **AI Native 升级实施计划** | 进行中 |
| [ai-native/README.md](plans/ai-native/README.md) | **AI Native 子项目索引** | 进行中 |
| [ai-native/execution-backlog.md](plans/ai-native/execution-backlog.md) | **AI Native 执行积压** | 进行中 |
| [eastmoney-integration.md](plans/eastmoney-integration.md) | **东方财富数据源集成计划** | 进行中 |
| [macro-sizing-multiplier-outsourcing-2026-03-31.md](plans/macro-sizing-multiplier-outsourcing-2026-03-31.md) | **宏观感知仓位系数模块外包任务书（Regime+Pulse+回撤三因子）** | 待开发 |
| [streamlit-dashboard-upgrade-plan.md](plans/streamlit-dashboard-upgrade-plan.md) | Streamlit 仪表盘交互升级实施方案 | 最新 |
| [regime-navigator-pulse-redesign-260323.md](plans/regime-navigator-pulse-redesign-260323.md) | **系统重新设计：Regime Navigator + Pulse 分层架构** | ✅ 已实施并收口 |
| [phase-1-regime-navigator-pulse-mvp.md](plans/phase-1-regime-navigator-pulse-mvp.md) | Phase 1: Regime Navigator + Pulse MVP + Dashboard 改造 | ✅ 已完成 |
| [phase-2-decision-funnel.md](plans/phase-2-decision-funnel.md) | Phase 2: 决策模式引导漏斗 | ✅ 已完成 |
| [phase-3-enrichment-polish.md](plans/phase-3-enrichment-polish.md) | Phase 3: 增强与打磨（Pulse V2 + 配置化 + 历史回溯） | ✅ 已完成 |

### 5. 测试文档 (`testing/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [master-test-strategy-2026-02.md](testing/master-test-strategy-2026-02.md) | **全面测试策略（L0-L7 层级、门禁定义）** | ✅ 2026-02-24 更新 |
| [outsourcing-full-regression-plan-2026-02-26.md](archive/process/testing/outsourcing-full-regression-plan-2026-02-26.md) | 外包全量回归执行方案（双环境+分层门禁+证据包）（归档） | ✅ 已归档 |
| [outsourcing-acceptance-plan-post-v34-2026-02-26.md](archive/process/testing/outsourcing-acceptance-plan-post-v34-2026-02-26.md) | 外包开发验收方案（V3.4 后续路线图）（归档） | ✅ 已归档 |
| [requirements-traceability-matrix-2026-02.md](testing/requirements-traceability-matrix-2026-02.md) | **需求-测试追踪矩阵（RTM）** | ✅ 2026-02-26 更新 |
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

### 3.0 实施计划 (`plan/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [qlib-local-upload-user-isolation.md](plan/qlib-local-upload-user-isolation.md) | Qlib 本地上传用户隔离方案 | 完整 |
| [eastmoney-integration.md](plan/eastmoney-integration.md) | **东方财富数据源集成计划（资金流向/新闻情感/实时行情/技术指标）** | ✅ 2026-03-09 新增 |

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
| [hedge/hedge-guide.md](modules/hedge/hedge-guide.md) | Hedge 模块指南 | 完整 |
| [terminal/terminal-guide.md](modules/terminal/terminal-guide.md) | Terminal 模块指南（终端 AI CLI） | ✅ 2026-03-17 新增 |
| [ai_capability/ai-capability-guide.md](modules/ai_capability/ai-capability-guide.md) | **AI Capability Catalog 模块指南** | ✅ 2026-03-19 新增 |
| [simulated_trading/daily-inspection.md](modules/simulated_trading/daily-inspection.md) | 模拟盘日更巡检 | ✅ 新增 |
| [strategy/position-management.md](modules/strategy/position-management.md) | 策略仓位管理 | ✅ 新增 |

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

**系统版本**: AgomTradePro 0.7.0

**业务模块**: 35个

**MCP 工具**: 302个（本地注册快照）

**REST API 路径**: 515个（OpenAPI 快照）

**测试规模**: 5,212 个已收集测试项（`pytest --collect-only` 快照）

**文档文件**: 271个（`docs/` 目录）

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

### 完整四层架构模块 (35个)

#### 核心引擎模块 (5个)
- `macro` - 宏观数据采集
- `regime` - Regime 判定
- `policy` - 政策事件管理
- `signal` - 投资信号管理
- `filter` - HP/Kalman 滤波

#### 资产分析模块 (5个)
- `asset_analysis` - 通用资产分析框架
- `equity` - 个股分析
- `fund` - 基金分析
- `sector` - 板块分析
- `sentiment` - 舆情情感分析

#### AI 智能模块 (8个)
- `alpha` - Alpha AI 选股信号（Qlib 集成）
- `alpha_trigger` - Alpha 离散触发
- `beta_gate` - Beta 闸门
- `decision_rhythm` - 决策频率约束
- `factor` - 因子管理
- `rotation` - 板块轮动
- `hedge` - 对冲策略
- `ai_capability` - **系统级 AI 能力目录与统一路由** ✅ 2026-03-19 新增

#### 风控与账户模块 (5个)
- `account` - 账户与持仓管理
- `audit` - 事后审计（完整测试覆盖 + Brinson 归因 + 前端可视化）
- `simulated_trading` - 模拟盘自动交易
- `realtime` - 实时价格监控
- `strategy` - 策略系统

#### 数据接入模块 (1个)
- `data_center` - 统一数据中台（Provider 配置、标准化、同步、查询、MCP/SDK 对齐）

#### 战术指标模块 (1个)
- `pulse` - **Pulse 脉搏层（战术指标聚合与转折预警）** ✅ 2026-03-28 新增

#### 工具模块 (8个)
- `ai_provider` - AI 服务商管理
- `prompt` - AI Prompt 模板
- `dashboard` - 仪表盘
- `backtest` - 回测引擎
- `events` - 事件系统
- `task_monitor` - 定时任务监控
- `share` - 分享功能
- `setup_wizard` - **系统初始化向导** ✅ 2026-03-23 新增

#### AI 运行时模块 (2个)
- `terminal` - 终端 CLI（AI 交互界面）
- `agent_runtime` - Agent 运行时（Terminal AI 后端，支持任务编排和 Facade 模式）

---

## 阅读路径

### 新加入开发人员
1. [QUICK_START.md](QUICK_START.md) - 系统实战理念
2. [development/quick-reference.md](development/quick-reference.md) - 快速了解常用命令和 API
3. [governance/SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) - **系统基线（单一叙事来源）**
4. [SYSTEM_SPECIFICATION.md](SYSTEM_SPECIFICATION.md) - 理解系统架构
5. [business/AgomTradePro_V3.4.md](business/AgomTradePro_V3.4.md) - 学习业务逻辑
6. [development/coding_standards.md](development/coding_standards.md) - 遵循代码规范

### 理解 AI 选股
1. [business/alpha-quickstart.md](business/alpha-alpha-quickstart.md) - Alpha 模块快速开始
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

- 代码扫描日期：`2026-04-21`
- 事实来源：
  - `apps/*` 目录结构扫描（业务模块数，排除 `__pycache__`）
  - `python -c "import asyncio; from agomtradepro_mcp.server import server; print(len(asyncio.run(server.list_tools())))"`（MCP 工具注册数）
  - `docs/testing/api/openapi.json` 的 `paths` 键计数（REST API 路径）
  - `pytest --collect-only -q`（全仓库已收集测试项）
  - `docs/` 目录文件计数（文档文件）
- 口径说明：
  - "业务模块数"按 `apps/`（排除 `shared` 与 `__pycache__`）统计
  - "MCP 工具数"按本地 server `list_tools()` 注册结果统计
  - "REST API 路径"按 OpenAPI `paths` 键数量统计
  - "文档文件"按 `docs/` 目录中的文件数量统计
  - "完成度"使用里程碑状态，不再维护固定百分比
  - "测试规模"以最新 CI/本地 collect / 执行结果为准

---

## 贡献指南

文档更新应遵循以下原则：

1. **时效性**: 重大变更后 24 小时内更新相关文档
2. **一致性**: 保持文档间引用关系的正确性
3. **完整性**: 新增模块必须同步更新架构文档
4. **准确性**: 代码示例必须经过验证

---

## 最近更新 (2026-02-20 ~ 2026-03-28)

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
**最后更新**: 2026-03-28
