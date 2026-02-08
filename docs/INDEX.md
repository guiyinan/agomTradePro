# AgomSAAF 文档索引

> **AgomSAAF V3.4** - 宏观环境准入系统
> **最后更新**: 2026-02-06
> **项目状态**: 持续迭代（以代码与发布说明为准）

---

## 快速导航

| 角色 | 入口文档 | 说明 |
|------|----------|------|
| 开发人员 | [development/quick-reference.md](development/quick-reference.md) | 命令速查、API端点、模块速查 |
| 新加入者 | [architecture/SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md) | 系统全景、模块说明、数据流 |
| 产品/业务 | [business/AgomSAAF_V3.4.md](business/AgomSAAF_V3.4.md) | 业务逻辑、金融规则、数据源 |
| 最终用户 | [user/decision-platform-guide.md](user/decision-platform-guide.md) | 决策平台使用指南 |
| 运维人员 | [deployment/DOCKER_DEPLOYMENT.md](deployment/DOCKER_DEPLOYMENT.md) | 部署指南 |

---

## 文档目录

### 1. 架构设计 (`architecture/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md) | 系统全景概览（1620行） | 最新 |
| [asset_analysis_framework.md](architecture/asset_analysis_framework.md) | 资产分析框架设计 | 完整 |
| [project_structure.md](architecture/project_structure.md) | 项目结构说明 | 完整 |
| [simulated_trading_design.md](architecture/simulated_trading_design.md) | 模拟盘交易设计 | 完整 |
| [strategy_system_design.md](architecture/strategy_system_design.md) | 策略系统设计 | 完整 |
| [frontend_design_guide.md](architecture/frontend_design_guide.md) | 前端设计指南 | 完整 |

### 2. 业务逻辑 (`business/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [AgomSAAF_V3.4.md](business/AgomSAAF_V3.4.md) | 核心业务需求文档（2650行） | 最新 |
| [equity-valuation-logic.md](business/equity-valuation-logic.md) | 个股估值逻辑 | 完整 |
| [regime_calculation_logic.md](business/regime_calculation_logic.md) | Regime 计算逻辑 | 完整 |
| [signal_and_position.md](business/signal_and_position.md) | 信号与持仓关系 | 完整 |

### 3. 开发指南 (`development/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [quick-reference.md](development/quick-reference.md) | 快速参考手册（329行） | 已更新 V1.1 |
| [api_structure_guide.md](development/api_structure_guide.md) | API 结构指南 | 完整 |
| [coding_standards.md](development/coding_standards.md) | 代码规范 | 完整 |
| [decision-platform.md](development/decision-platform.md) | 决策平台实现 | 完整 |
| [startup-scripts.md](development/startup-scripts.md) | 启动脚本使用指南 | 完整 |
| [module-dependency-graph.md](development/module-dependency-graph.md) | 模块依赖关系图 | 完整 |

### 4. 实施计划 (`plans/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [implementation-progress-summary.md](plans/implementation-progress-summary.md) | 总体进度总结（Phase 1-5 完成） | 最新 |
| [agomsaaf-qlib-integration-plan-v1.1.md](plans/agomsaaf-qlib-integration-plan-v1.1.md) | Qlib 集成方案 v1.1 | 完整 |
| [factor-rotation-hedge-implementation-plan.md](plans/factor-rotation-hedge-implementation-plan.md) | 因子轮动对冲实施计划 | 完整 |
| [sdk-mcp-implementation.md](plans/sdk-mcp-implementation.md) | SDK & MCP 实施方案 | 完整 |
| [phase1-alpha-implementation-summary.md](plans/phase1-alpha-implementation-summary.md) | Phase 1 Alpha 模块总结 | 完整 |
| [phase2-qlib-inference-summary.md](plans/phase2-qlib-inference-summary.md) | Phase 2 Qlib 推理总结 | 完整 |
| [phase3-training-summary.md](plans/phase3-training-summary.md) | Phase 3 训练流水线总结 | 完整 |
| [phase4-monitoring-summary.md](plans/phase4-monitoring-summary.md) | Phase 4 监控评估总结 | 完整 |
| [phase5-integration-summary.md](plans/phase5-integration-summary.md) | Phase 5 宏观集成总结 | 完整 |
| [system-code-doc-alignment-implementation-plan-2026-02-06.md](plans/system-code-doc-alignment-implementation-plan-2026-02-06.md) | 代码巡检与文档对齐实施方案 | 最新 |
| [streamlit-dashboard-upgrade-plan.md](plans/streamlit-dashboard-upgrade-plan.md) | Streamlit 仪表盘交互升级实施方案 | 最新 |
| [admin-to-modern-interaction-migration-plan.md](plans/admin-to-modern-interaction-migration-plan.md) | Admin 依赖迁移实施方案 | 最新 |

### 5. 测试文档 (`testing/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [sdk-mcp-integration-test-plan.md](testing/sdk-mcp-integration-test-plan.md) | SDK & MCP 集成测试计划（1000行） | 完整 |
| [full-integration-test-report.md](testing/full-integration-test-report.md) | 完整集成测试报告 | 完整 |
| [system_algorithm_evaluation_report.md](testing/system_algorithm_evaluation_report.md) | 系统算法评估 | 完整 |
| [doc-link-check-report.md](testing/doc-link-check-report.md) | 文档链接校验报告 | 最新 |
| [bug-report-template.md](testing/bug-report-template.md) | Bug 报告模板 | 完整 |
| [test-results-template.md](testing/test-results-template.md) | 测试结果模板 | 完整 |
| [api/API_REFERENCE.md](testing/api/API_REFERENCE.md) | API 参考文档 | 完整 |

### 6. AI 相关 (`ai/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [ai_prompt_system.md](ai/ai_prompt_system.md) | AI 提示词系统使用文档 | 完整 |
| [ai_provider_requirements.md](ai/ai_provider_requirements.md) | AI 服务商管理需求 | 完整 |
| [prompt_templates_guide.md](ai/prompt_templates_guide.md) | Prompt 模板指南 | 完整 |

### 7. 部署文档 (`deployment/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [VPS_BUNDLE_DEPLOYMENT.md](deployment/VPS_BUNDLE_DEPLOYMENT.md) | VPS Bundle 一体化部署与迁移指南（含 Postgres/Redis 迁移） | ✅ 新增 |
| [DOCKER_DEPLOYMENT.md](deployment/DOCKER_DEPLOYMENT.md) | Docker 部署指南 | 完整 |
| [postgres_windows_docker.md](deployment/postgres_windows_docker.md) | Windows PostgreSQL Docker 配置 | 完整 |
| [database_configuration.md](deployment/database_configuration.md) | 数据库配置 | 完整 |

### 8. 用户指南 (`user/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [decision-platform-guide.md](user/decision-platform-guide.md) | 决策平台用户指南（442行） | 完整 |

### 9. Regime 主题文档

| 文档 | 说明 | 状态 |
|------|------|------|
| [regime_calculation_logic.md](business/regime_calculation_logic.md) | Regime 计算逻辑（业务规则） | 最新 |
| [SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md) | Regime 在全系统中的位置与数据流 | 最新 |

### 10. 模块文档 (`modules/`)

| 文档 | 说明 | 状态 |
|------|------|------|
| [alpha/alpha-guide.md](modules/alpha/alpha-guide.md) | Alpha 模块指南 | 完整 |
| [audit/audit-module-guide.md](modules/audit/audit-module-guide.md) | Audit 模块指南（新增） | ✅ 新增 |
| [audit/attribution-methodology.md](modules/audit/attribution-methodology.md) | Brinson 归因方法论（新增） | ✅ 新增 |
| [factor/factor-guide.md](modules/factor/factor-guide.md) | Factor 模块指南 | 完整 |
| [rotation/rotation-guide.md](modules/rotation/rotation-guide.md) | Rotation 模块指南 | 完整 |
| [hedge/hedge-guide.md](modules/hedge/hedge-guide.md) | Hedge 模块指南 | 完整 |

---

## 根目录文件

| 文件 | 说明 |
|------|------|
| [alpha-quickstart.md](business/alpha-quickstart.md) | Alpha 模块快速开始指南 |

---

## 项目状态

**系统版本**: AgomSAAF V3.4

**业务模块**: 27个

**完成度**: 持续迭代（请以里程碑文档与代码状态为准）

**测试覆盖**: 使用 `pytest` + `coverage` 持续验证（覆盖率以最新 CI/本地执行结果为准）

### 完整四层架构模块 (26个)

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

#### AI 智能模块 (7个)
- `alpha` - Alpha 选股信号（Qlib 集成）
- `alpha_trigger` - Alpha 离散触发
- `beta_gate` - Beta 闸门
- `decision_rhythm` - 决策频率约束
- `factor` - 因子管理
- `rotation` - 板块轮动
- `hedge` - 对冲策略

#### 风控与账户模块 (5个)
- `account` - 账户与持仓管理
- `audit` - 事后审计（✅ 新增：完整测试覆盖 + Brinson 归因 + 前端可视化）
- `simulated_trading` - 模拟盘自动交易
- `realtime` - 实时价格监控
- `strategy` - 策略系统

#### 工具模块 (5个)
- `ai_provider` - AI 服务商管理
- `prompt` - AI Prompt 模板
- `dashboard` - 仪表盘
- `backtest` - 回测引擎
- `events` - 事件系统

### 完整四层架构 (27个)
所有业务模块均已完成四层架构重构。

---

## 阅读路径

### 新加入开发人员
1. [development/quick-reference.md](development/quick-reference.md) - 快速了解常用命令和 API
2. [architecture/SYSTEM_OVERVIEW.md](architecture/SYSTEM_OVERVIEW.md) - 理解系统架构
3. [business/AgomSAAF_V3.4.md](business/AgomSAAF_V3.4.md) - 学习业务逻辑
4. [development/coding_standards.md](development/coding_standards.md) - 遵循代码规范

### 理解 AI 选股
1. [alpha-quickstart.md](business/alpha-quickstart.md) - Alpha 模块快速开始
2. [plans/agomsaaf-qlib-integration-plan-v1.1.md](plans/agomsaaf-qlib-integration-plan-v1.1.md) - Qlib 集成方案
3. [plans/implementation-progress-summary.md](plans/implementation-progress-summary.md) - 实施进度

### 部署运维
1. [deployment/VPS_BUNDLE_DEPLOYMENT.md](deployment/VPS_BUNDLE_DEPLOYMENT.md) - VPS 一体化打包与部署指南
2. [deployment/DOCKER_DEPLOYMENT.md](deployment/DOCKER_DEPLOYMENT.md) - Docker 部署指南
3. [deployment/database_configuration.md](deployment/database_configuration.md) - 数据库配置
4. [development/startup-scripts.md](development/startup-scripts.md) - 启动脚本

---

## 文档口径来源

- 代码扫描日期：`2026-02-06`
- 事实来源：
  - `core/settings/base.py`（`INSTALLED_APPS` 模块清单）
  - `apps/*` 目录结构扫描（四层完整性）
  - `python manage.py check`（系统健康）
- 口径说明：
  - “业务模块数”按 `apps/`（排除 `shared` 与 `__pycache__`）统计
  - “完成度”使用里程碑状态，不再维护固定百分比
  - “测试覆盖”以最新 CI/本地执行结果为准

---

## 贡献指南

文档更新应遵循以下原则：

1. **时效性**: 重大变更后 24 小时内更新相关文档
2. **一致性**: 保持文档间引用关系的正确性
3. **完整性**: 新增模块必须同步更新架构文档
4. **准确性**: 代码示例必须经过验证

---

**文档维护**: AgomSAAF Team
**最后更新**: 2026-02-06
