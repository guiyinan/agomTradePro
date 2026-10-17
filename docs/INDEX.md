# AgomTradePro 文档索引

> 导航整理：2026-10-14。公开版本线 `0.8.0` 见 [VERSION.md](VERSION.md)。
> 本页提供入口和阅读路径；工作状态、生产事实与历史记录分别从下列真源读取。

## 快速导航

| 任务 | 入口 | 用途 |
| --- | --- | --- |
| 初次使用 | [QUICK_START.md](QUICK_START.md) | 本地首跑与基本操作 |
| 理解系统 | [SYSTEM_SPECIFICATION.md](SYSTEM_SPECIFICATION.md) | 系统说明与功能边界 |
| 理解业务 | [AgomTradePro_V3.4.md](business/AgomTradePro_V3.4.md) | 金融规则和业务定义 |
| 日常开发 | [quick-reference.md](development/quick-reference.md) | 常用命令与 API 操作参考 |
| API 改动同步检查 | [engineering-guardrails.md](development/engineering-guardrails.md) | SDK、MCP、OpenAPI、文档和用户提示的同步门禁 |
| 架构与门禁 | [ARCHITECTURE_GUARDRAILS.md](governance/ARCHITECTURE_GUARDRAILS.md) | 架构、CI 与证据层级 |
| 分支与提交 | [GIT_WORKFLOW.md](GIT_WORKFLOW.md) | 长期开发分支与发布流程 |
| 工作安排 | [计划索引](plans/README.md) | 工作流、主计划与收口入口 |
| SDK / MCP 集成 | [SDK README](../sdk/README.md) | 安装、认证、能力发现与调用 |
| 运维 | [runbook.md](operations/runbook.md) | readiness、任务与运行检查 |
| 部署与生产证据 | [部署目录](deployment/README.md) | 部署指南及证据保留规则 |
| 用户研究流程 | [执行手册](user/topdown-bottomup-execution-playbook.md) | 环境、标的、执行与复盘 |
| 历史审核 | [reviews/README.md](reviews/README.md) | 按原候选范围解释审核记录 |
| 查找具体文档 | [CATALOG.md](CATALOG.md) | 更完整的专题文档目录 |

## 文档口径来源

| 信息 | 唯一真源 / 核验入口 |
| --- | --- |
| 系统版本 | [VERSION.md](VERSION.md)，与 `core/version.py` 一致性校验 |
| 运行与开发依赖 | [pyproject.toml](../pyproject.toml)，requirements 为生成投影 |
| 模块结构、入口与路由 | [module_map.json](../governance/module_map.json) 与 [MODULE_MAP.md](architecture/MODULE_MAP.md) |
| ORM 模型字段与表结构 | [data_dictionary.json](../governance/data_dictionary.json) 与 [DATA_DICTIONARY.md](architecture/DATA_DICTIONARY.md) |
| 动态治理规模 | [governance/governance_baseline.json](../governance/governance_baseline.json) |
| 测试门槛与报告口径 | [testing_quality_baseline.json](../governance/testing_quality_baseline.json) 与 [coverage-governance.md](development/ci/coverage-governance.md) |
| 工作流、状态、依赖与执行焦点 | [active_plan_registry.json](../governance/active_plan_registry.json) 的 `workstreams`、`closure_backlog`、`execution_focus` |
| 生产事实 | [部署证据目录](deployment/README.md) 内绑定候选、环境、观测时间与 hash 的原件 |
| 业务含义与专项合同 | [业务定义](business/AgomTradePro_V3.4.md)、[AGENTS.md](../AGENTS.md) 的专项文档路由 |

生产证据必须按候选、时间窗和实际验证范围解释。健康检查、某次 CI 成功或历史“completed”不能替代当前业务验收；整理导航不会改变机器状态和运行停止线。

## 文档目录

| 主题 | 入口 |
| --- | --- |
| 系统基线说明 | [SYSTEM_BASELINE.md](governance/SYSTEM_BASELINE.md) |
| 架构设计 | [专题目录：架构](CATALOG.md#架构设计) |
| 业务规则 | [专题目录：业务](CATALOG.md#业务逻辑) |
| 开发与测试 | [专题目录](CATALOG.md)、[测试 README](../tests/README.md) |
| 实施计划 | [计划索引](plans/README.md)、[本轮治理计划](plans/scripts-docs-mcp-governance-plan-2026-10-14.md) |
| 部署与运行 | [部署 README](deployment/README.md)、[监控 README](../monitoring/README.md) |
| TUI 前端 | [Workbench 契约](development/tui-workbench.md)、[前端 README](../frontend/tui-workbench/README.md) |
| Web → TUI 迁移 | [迁移总计划](plans/web-to-tui-migration-plan-2026-07-25.md) |
| [M5 readiness](plans/web-to-tui-m5-readiness-2026-07-27.md) | canonical cutover 兼容投影：`891c40c57…` / `20260915110952`，`2/10 DENY`；范围见下文 |
| SDK 与 MCP | [SDK README](../sdk/README.md)、[专题目录](CATALOG.md) |
| QMT 外部券商桥 | [QMT README](../qmt_agent/README.md) |
| 历史文档 | [ARCHIVE_INDEX.md](archive/ARCHIVE_INDEX.md) |

M5 readiness 行是候选一致性测试要求的最小兼容投影，读取 [canonical cutover](../config/tui/migration/web_to_tui_cutover_evidence.v1.json)。它描述该冻结候选的绑定和 DENY 状态，不表示今天的 VPS release、有效观察窗口或清理授权；当前执行安排仍以注册表为准。

## 各层级 README 索引

| 范围 | 入口 |
| --- | --- |
| 仓库概览 | [README.md](../README.md)、[README_EN.md](../README_EN.md) |
| 部署 Bundle / FRP | [部署包 README](../deploy/README_DEPLOY.md)、[FRP README](../deploy/frp/README.md) |
| SDK / QMT / 前端 | [SDK](../sdk/README.md)、[QMT](../qmt_agent/README.md)、[TUI 前端](../frontend/tui-workbench/README.md) |
| 监控 / 测试 / 样式 | [监控](../monitoring/README.md)、[测试](../tests/README.md)、[CSS](../static/css/README.md) |
| 计划 / AI Native | [计划](plans/README.md)、[AI Native](plans/ai-native/README.md) |
| 部署 / 审核 / 策略研究 | [部署](deployment/README.md)、[审核](reviews/README.md)、[STRAT-01](business/strategy-research/strat-01/README.md) |

## 阅读路径

### 新加入开发人员

1. 阅读 [QUICK_START.md](QUICK_START.md) 和 [AGENTS.md](../AGENTS.md)。
2. 查阅 [MODULE_MAP.md](architecture/MODULE_MAP.md) 与 [ARCHITECTURE_GUARDRAILS.md](governance/ARCHITECTURE_GUARDRAILS.md)。
3. 用 [quick-reference.md](development/quick-reference.md) 找到命令，再阅读本次改动触发的专项规范。
4. 从 [计划索引](plans/README.md) 和机器注册表确认任务归属及退出门。

### 理解 AI 选股

1. 阅读 [Alpha 快速开始](business/alpha-quickstart.md)。
2. 查阅 [Qlib 模型导入](modules/alpha/qlib-model-import-guide.md)。
3. 从 [策略研究定义包](business/strategy-research/strat-01/README.md) 核对数据、证伪与生命周期要求。

### 部署运维

1. 阅读 [VPS 部署指南](deployment/VPS_BUNDLE_DEPLOYMENT.md) 与 [标准发布流程](deployment/TEST_PACKAGE_RELEASE_WORKFLOW.md)。
2. 核对 [数据库配置](deployment/database_configuration.md)、[runbook](operations/runbook.md) 与本次候选证据。
3. 按 [部署目录保留规则](deployment/README.md) 区分正式证据和临时报告。

## 历史记录

总索引原有的生产检查点、状态表、模块列表和最近更新已冻结到 [清理前历史快照](archive/documentation/docs-index-history-before-2026-10-14.md)。计划索引历史见 [计划索引快照](archive/documentation/plans-index-history-before-2026-10-14.md)。正式证据继续保留原路径。

## 贡献指南

- 本页新增条目只描述用途与真源入口；较完整的专题链接放入 `CATALOG.md`。
- 新主计划先登记机器注册表，再更新计划索引；状态和数量变化不追加到本页。
- 实际执行结果写入对应计划检查点或正式证据；历史快照不再续写。
- 修改导航后运行治理一致性、活跃计划登记与文档/API/SDK 检查，检查新增链接和适用候选投影。
