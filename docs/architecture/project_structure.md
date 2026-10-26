# AgomTradePro 项目结构说明

> 维护日期：2026-10-26。本文只描述稳定原则与查阅入口，不维护手写目录树、模型/API 清单、依赖版本或生产就绪结论。
> 版本与发布说明：[VERSION.md](../VERSION.md)；当前执行状态：[计划注册表](../../governance/active_plan_registry.json)。

## 1. 项目定位与资格边界

AgomTradePro 是个人投研系统。当前交付优先完成 A 股研究、模拟调仓与手工辅助下单的用户流程。Regime/Policy 是待用真实数据验证的研究和过滤能力，不能仅因模块存在宣称其能避免错误投资。

代码存在、开发测试通过、真实数据可用、普通用户验收和发布资格分别取证。当前范围、默认关闭的自动下单许可及尚未完成的验收，读取 [A 股主计划](../plans/a-share-usability-implementation-plan-2026-10-16.md)、[Owner 决策记录](../reviews/owner-scope-freeze-2026-10-18/approval-log.md)与当前候选证据；本文不宣称整个系统“生产就绪”。

## 2. 查找结构事实

| 要查什么 | 真源 / 入口 | 使用边界 |
| --- | --- | --- |
| 模块、依赖、公开入口、任务与路由 | [module_map.json](../../governance/module_map.json)；[字段说明](MODULE_MAP.md) | 代码树生成投影；不手工维护目标职责或政策 |
| ORM 模型、字段与来源文件 | [data_dictionary.json](../../governance/data_dictionary.json)；[可读数据字典](DATA_DICTIONARY.md) | 静态声明包含抽象类；不等于运行数据库实表/继承字段计数 |
| 动态治理数量与预算 | [governance_baseline.json](../../governance/governance_baseline.json) | 不复制数量到本文；减少债务也要核对口径 |
| 依赖和支持环境 | [pyproject.toml](../../pyproject.toml) | requirements 是生成投影，不手改；Python/Django 等具体约束以此为准 |
| 分层与模块红线 | [AGENTS.md](../../AGENTS.md)；[架构门禁](../governance/ARCHITECTURE_GUARDRAILS.md) | 门禁覆盖范围有限，扫描通过不替代边界审阅 |
| 主任务与计划顺序 | [计划导航](../plans/README.md)；[机器注册表](../../governance/active_plan_registry.json) | 单元状态、依赖和执行窗口只在机器注册表维护 |
| API/SDK 契约 | [API_REFERENCE.md](../testing/api/API_REFERENCE.md)；[操作参考](../development/quick-reference.md) | 包含 Account 交易记录及费用可用性合同；不在结构文档重复端点列表 |
| 数据是否可供当前决策使用 | [新鲜度合同](../development/data-freshness-contract-guard.md)；[机器合同](../../governance/current_data_contracts.json) | latest 不等于 fresh；保留来源时钟、用途、限制和阻断原因 |
| 用户界面 | [TUI 用户面标准](../development/tui-user-facing-design-standard.md)；[Web→TUI 迁移](../plans/web-to-tui-migration-plan-2026-07-25.md) | 新业务主任务默认 `/tui/`；迁移状态不能由目录存在推断 |

## 3. 依赖与所有权原则

Interface 验证输入、调用 Application 并格式化输出；Application 编排 Domain 规则，通过 Protocol/Facade/Query Service 使用外部能力。Infrastructure 实现这些端口并承担 ORM、缓存、文件和网络访问，由 composition root 注入。Domain 使用标准库，不依赖 Django、Pandas 或任何外部实现。

Application 不直接访问 ORM；Interface 不导入业务 Infrastructure；跨 App 优先使用公开 Application 入口。shared 不依赖 apps，也不承载业务实体、业务默认配置或模型。具体允许/禁止项按 AGENTS 和架构门执行。

账户身份归 account；组合、持仓和交易流水归 portfolio；风险规则与状态归 risk_center；全局运行配置归 config_center；data_center 负责统一 provider、查询和标准事实。既有遗留存储并不自动符合目标边界，迁移方法见 [数据边界收敛计划](../plans/data-boundary-convergence-plan-2026-10-26.md)。模拟账本、真实账本和券商观测区分语义，不因同名合并。

## 4. 生成与验证

模型变化使用 `python scripts/build_data_dictionary.py` 生成字典，再运行 `python scripts/check_data_dictionary.py`。模块结构、依赖、入口或路由变化使用 `python scripts/build_module_map.py`，再运行 `python scripts/check_module_map.py`。生成物只反映已修改代码，不用手工加入拟议架构。

依赖变化由 `python scripts/sync_dependency_projections.py` 生成投影。常用运行、迁移、测试和部署命令统一查 [quick-reference.md](../development/quick-reference.md)，Git 操作查 [GIT_WORKFLOW.md](../GIT_WORKFLOW.md)，不在此复制易漂移的命令手册。

SQLite 可用于本地快速开发；依赖 PostgreSQL 触发器、并发、角色权限或隔离级别的行为须在 PostgreSQL 验证，不能用 SQLite 通过代替。生产栈与候选是否满足要求以对应部署和发布证据为准。

## 5. 本次整理的范围

2026-10-26 依据 [重构评审回复](../reviews/refactor-review-response-2026-10-26.md) 删除过时手写目录树、八模型文件清单、旧 AI 型号示例、重复 API/依赖表与无条件“生产就绪”描述。历史版本由 Git 保留；本次只是文档纠偏，没有移动模块、删除数据、切换数据库或验证投资效果。
