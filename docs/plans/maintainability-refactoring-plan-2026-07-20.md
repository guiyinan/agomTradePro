# 代码库可维护性定向重构计划

> **文档日期**: 2026-07-20
> **状态**: R0 与 R1 已完成；R1A 保持 deprecated，物理删除等待独立 sunset 评审
> **适用对象**: 架构负责人 / 开发负责人 / 测试负责人
> **依据**: 2026-07-20 全仓代码审计（两轮结构调查，逐文件统计）
> **目标**: 不做推倒重写，通过"归位 + 收敛"定向重构，先将全仓 Python 从 ~69 万行收敛到保守可承诺的 ~61-63 万行；若 `filter` 完成 sunset 并满足物理下线条件，则进入 ~59-61 万行；在 R6 候选逐项证实且不牺牲语义后，再以 ~56-58 万行为延伸目标。可维护性收益以模块边界、稳定契约和单一真源为主，不以删行数作为单批验收门槛

## 执行状态（2026-07-20）

| 批次 | 状态 | 结果 |
|---|---|---|
| R0 | 完成 | 五份 inventory/矩阵已落档，见 `docs/plans/maintainability-r0/` |
| R1A | deprecated 阶段完成 | Filter API/SDK/MCP 发布弃用契约；因 TUI 与 governed MCP 仍是登记消费者且无生产连续日志窗口，未物理删除 |
| R1B | 完成 | readiness evidence provenance、quote freshness、workspace core 分类收敛为公共真源 |
| R1C | 完成 | 新 owner 为 `apps.operational_readiness`；旧命令模块和旧 Celery task name 保留兼容代理，静态 Beat 与 setup 命令的 canonical task 已切换；专项、固定、治理与 Celery 注册回归均通过 |

R1A 的物理删除不属于本次完成项；必须等到 2026-09-30 前后的独立 sunset 评审且四重证据门槛全部满足。

---

## 1. 背景与结论

### 1.1 代码量审计

全仓 Python 实测 **~69.2 万行**（已排除 `agomtradepro/` venv、`htmlcov-unit/`、`dist/`、`backups/`、`data/`），构成如下：

| 构成 | 行数 | 性质 |
|---|---|---|
| apps 业务源码 + core/shared | ~36 万（34.2 万 + 1.9 万） | 系统本体 |
| tests/（顶层 19.5 万 + app 内 0.9 万） | ~20 万 | 测试资产 |
| sdk/（代码 4.8 万 + 测试 2.6 万） | ~7.4 万 | 同一能力手写 4 遍（见 2.2） |
| scripts / tools / 前端 / tui-metadata-compiler | ~3.5 万 | 辅助 |
| migrations | ~3.1 万 | 自动生成，不计维护负担 |

### 1.2 结论

**不做推倒重写。** 理由：

- 四层架构方向正确，CI 架构护栏有效，模块间依赖方向基本正确（无循环依赖失控）。
- 20 万行测试是资产而非负担；重写意味着业务代码回到 25-30 万行的同时重写全部测试，投入以年计、收益趋近于零。
- 真正的问题集中在三类**局部病变**：归属错位、平行体系、模板 boilerplate。这些用定向重构即可解决，且每批独立可验证、可回滚。

---

## 2. 诊断与证据

以下所有行数均不含测试与 migrations，来自逐文件统计。

### 2.1 归属错位（最大可维护性问题，约占头部模块 25-30%）

**`apps/decision_rhythm`（25,704 行）—— 名不副实之最**

"决策频率约束"内核（quota/cooldown/rhythm_*）仅 **~3,800 行（15%）**，其余 2.1 万行是一整个投资顾问平台：

| 内容 | 行数 | 实质 |
|---|---|---|
| `advisor_*` | 3,789 | 持仓合并、下单意图、顾问绩效，完整 advisor 工作流 |
| `recommendation_*` + `decision_recommendation_use_cases.py` | ~3,600 | 统一推荐引擎全套 |
| `workspace_*` + `decision_workspace_use_cases.py` | ~3,300 | 决策工作台页面流 |
| `valuation_*` | 2,078 | DCF/PE_BAND/PB_BAND/PEG/DIVIDEND/COMPOSITE 六方法估值引擎 |
| `feature_providers.py` | 1,236 | 推荐引擎特征聚合层，含 ~450 行估值逻辑错放 infrastructure 层 |

外部消费者仅 dashboard / terminal / agent_runtime 三家；代码质量本身不差，是"多个模块寄生于一个名字下"。

**`apps/task_monitor`（14,837 行）—— 虚胖最严重**

- 85% 是与任务监控无关的 readiness 取证工具链：`management/` 目录独占 9,582 行（`readiness_status_acceptance.py` 1,251、`inspect_personal_readiness_evidence.py` 1,217、`collect_personal_readiness_evidence.py` 1,169、`readiness_window_validation_evidence.py` 957、`show_personal_readiness_status.py` 811）。
- 核心监控（views/models/tasks/backup）仅 ~2,000 行。
- 4 个 readiness 命令间存在逐字重复的常量（`ACCEPTED_DECISION_QUOTE_FRESHNESS_STATUSES`）与证据解析逻辑。

**`apps/account`（23,069 行）—— 已自认未执行的拆分**

- portfolio 仍在：`infrastructure/portfolio_models.py` 488 行 7 个模型 + 仓储 + `portfolio_api_views.py` 458 行。
- rbac 仍在：`identity_models.py` 418 行（AccountProfile/UserAccessToken/PortfolioObserverGrant）+ admin/users、admin/tokens 一族管理视图。
- trading_config：`trading_config_models.py` 522 行 7 个配置模型。
- `management/commands/init_docs.py` 615 行硬编码 markdown 文档字符串（内容数据伪装成代码）。
- AGENTS.md 已写明"组合/持仓/交易流水归独立组合模块（后续 portfolio）、角色与授权归独立权限模块（后续 rbac）"——本计划将其落实。

**`apps/policy`（14,349 行）—— 一个模块干了 4 件事**

11 个模型中混入：RSS 摄取管道（`RSSHubGlobalConfig`/`RSSSourceConfig`/`RSSFetchLog`，~1,900 行）、`HedgePositionModel`（与 `apps/hedge` 职责直接重叠）、`SentimentGateConfig` + `GateActionAuditLog`（贴近 sentiment/beta_gate 领域）、站内通知。政策事件+档位+关键词+审核队列的本职内核约占 60%。

### 2.2 平行体系（同一件事维护多遍）

- **SDK 同一能力手写 4 遍**：`modules/` 9,079 + `mcp/tools/` 9,382 + `registry/modules/owners/` 12,047 + `registry/runtime_handlers/owners/` 11,172 ≈ **4.2 万行**，其中 50% 以上可从单一 manifest 真源生成。
- **能力目录双真源**：`apps/ai_capability`（DB 化 CapabilityDefinition/RoutingLog + collectors）与 sdk registry（静态 capability manifest）平行存在，靠 sync 机制对齐。
- **风险参数双体系**：`account/trading_config_models.py`（StopLoss/TakeProfit/MacroSizing/TransactionCost 等 7 模型）与 `risk_center`（GlobalRiskFloor/RiskTemplate/AccountRiskPolicy，共用 RiskParameterMixin）并存。
- **data_center 三代 akshare 接入并存**：`_provider_adapter_*` 共 1,806 行遗留半废弃适配器，与 `gateways/`、`macro_sources/` 新层同时被引用——上一轮重构未拆干净。
- **TUI metadata 三轨验证**：`config/tui/schema/tui_metadata.schema.v3.json`（316 行）↔ Python `ALLOWED_*` 常量（~240 行，与 schema enum 逐字重复）↔ ~950 行手写验证函数。且 `jsonschema` 未在 `pyproject.toml` 声明，JSON Schema 实际是死规格，漂移已成必然。
- **纯 API 壳模块 `apps/filter`（2,108 行）**：apps 内零业务引用，仅挂 `core/urls.py` 暴露 API；HP/Kalman 算法真源本就在 `shared/infrastructure/`。但 SDK/MCP 消费链完整存在（`sdk/agomtradepro/modules/filter.py` 96 行 + `mcp/tools/filter_tools.py` + registry owner + owner 测试）——下线决策点不在代码引用，而在于是否有真实 MCP 客户端用户调用 filter API（需查访问日志确认）。

### 2.3 模板 boilerplate

- **四层管道代码 ≈ 1.9 万行**（占 apps 5.5%）：`repository_provider.py` 36 文件 2,555 + `interface_services.py` 26 文件 9,035 + `query_services.py` 25 文件 2,915 + `dtos.py` 3,961 + `providers.py` 846；其中 40-50% 为机械透传，可通过约定优于配置（统一 composition root）消减。
- **测试模板化**：
  - `tests/unit/test_tui_workbench.py` 7,765 行 / 209 个测试，其中 141 处静态资源字符串断言（应收敛为契约测试 + 扫描脚本）。
  - `test_personal_readiness_*` 一族 8 文件 9,933 行测一个 readiness 功能。
  - `tests/unit/test_ai_capability/` per-owner 模板族 12,470 行。
  - `tests/api/test_*_api_edges.py` ~20 文件 14,700 行，30 个文件各自重复定义 fixture，全 tests 共 **252 处 `create_user`**。
  - sdk `test_core_registry_owner_*` 一族 19,701 行同型模板。

---

## 3. 重构原则

1. **不重写、不并行大爆炸**。每批独立 `dev/*` 分支、独立 PR、独立验证、独立可回滚，遵守 AGENTS.md 主线切分规则。
2. **归位优先于删减**。多数行数是搬家不是删除；收益在模块边界清晰、命名诚实，而非行数下降。
3. **单一真源优于同步机制**；**生成优于手写多遍**。
4. 每批必跑 AGENTS.md 固定最小回归包（`test_tui_workbench` / `test_terminal_agent_service` / `sdk test_client` / `test_internal_ssl_redirect`）+ 本批局部测试集；未跑项必须在总结中显式声明。
5. 涉及 `terminal/tui/mcp/sdk/deploy` 的批次，收尾必须列出：已完成项 / 未完成项 / 已验证测试 / 未验证风险。
6. **稳定身份优先于物理归位**。Django `app_label`、`db_table`、ContentType、权限、URL namespace、Celery task name、事件 source 和管理命令名均视为兼容契约；未经迁移设计不得随目录移动一起改名。
7. **运行时投影不得反向充当构建真源**。SDK/MCP 的构建输入必须来自版本库内可审查、可复现、可 round-trip 验证的声明式契约；数据库可保存运行时投影与人工覆盖，但不得成为构建 SDK 的隐式环境依赖。

---

## 4. 分批计划

### R0 边界与兼容契约冻结（前置批次，不改运行行为）

| 项 | 内容 |
|---|---|
| 范围 | ① 固化 `filter` API/SDK/MCP 消费者清单、访问日志观察窗口与下线口径；② 盘点 readiness 管理命令、Celery task、PeriodicTask、证据 provenance、runbook 和外部监控引用；③ 为 Decision Rhythm 产出“文件/模型/API/task/event source → 目标 owner”矩阵，并决定 ORM 模型暂留旧 app 还是进入后续 expand/contract migration；④ 为 Account/Risk Center 产出“字段语义 × 作用域 × 当前消费者 × 优先级 × 迁移目标”矩阵；⑤ 冻结 SDK/MCP canonical manifest vNext 的字段集合与生成边界 |
| 行数影响 | 基本不变；本批只产生决策记录、inventory 与契约测试基线 |
| 验收标准 | 上述 5 份清单/矩阵均落档；所有稳定身份有明确的“保持/alias/迁移”结论；无“迁到独立目录或独立 app”这类未决分支进入实施批次 |
| 回归范围 | 只运行清单生成与治理一致性检查；不修改运行代码 |
| 回滚点 | 纯文档与 inventory 批次，可独立调整，不阻塞现有生产链路 |

### R1A `filter` 生命周期收口（低风险，独立执行）

| 项 | 内容 |
|---|---|
| 范围 | 根据 R0 证据处理 `apps/filter` 及其 SDK/MCP 消费链：若在约定观察窗口内无调用且无登记消费者，则先发布 deprecated 契约和 sunset 日期，再整体下线；若日志、客户端登记或治理 manifest 仍显示使用，则只做 deprecated 标记与迁移提示，不删除代码 |
| 行数影响 | 完成下线时净删约 2.1k apps 代码及对应 SDK/MCP/测试；仅 deprecated 时基本不变 |
| 验收标准 | 证据必须同时覆盖访问日志、已登记客户端、定时/离线调用和 MCP governed capability；下线 commit 前一个发布周期已暴露弃用信息；删除后 API/SDK/MCP inventory 与治理基线一致 |
| 回归范围 | filter API/SDK/MCP 契约测试 + 固定最小回归包 |
| 回滚点 | deprecated 与物理删除分成两个 commit；删除 commit 可在 sunset 周期内整体 revert |

### R1B readiness 重复收敛（低风险，不迁路径）

| 项 | 内容 |
|---|---|
| 范围 | 在 `apps/task_monitor` 原路径内先合并 readiness 命令间的重复常量、证据解析和状态归一逻辑；本批不修改管理命令名、Celery task name、PeriodicTask task 字段、证据 `trigger_task_name` 或 runbook 入口 |
| 行数影响 | 净删约 0.5-1k |
| 验收标准 | 所有既有命令 `--help` 和 JSON 契约保持；历史 evidence 可继续验证；Beat 配置与数据库 PeriodicTask 仍指向 `apps.task_monitor.application.tasks.run_personal_readiness_daily_task` |
| 回归范围 | readiness 命令、daily task、scheduler initialization、window validation、status command 全量相关测试 + 固定最小回归包 |
| 回滚点 | 纯内部去重 commit，不与路径迁移混合，可整体 revert |

### R1C readiness 工具链归位（中风险，R1B 后单独评审）

| 项 | 内容 |
|---|---|
| 范围 | 将 readiness 取证能力迁到 R0 已批准的 owner；若采用独立 Django app，旧管理命令入口和旧 Celery task name 至少保留一个兼容周期，旧 task 仅代理到新实现；同步迁移静态 Beat 配置、数据库 PeriodicTask、操作文档与监控配置，但不得让既有 evidence provenance 失效 |
| 行数影响 | 搬家为主；`task_monitor` 收敛至任务监控本职，全仓净行数基本不变 |
| 验收标准 | 旧/新入口行为等价；已有 evidence 窗口仍被接受；新 evidence 带稳定或版本化 provenance；调度行迁移可重复执行；旧 alias 移除必须另立 sunset 批次 |
| 回归范围 | R1B 全部测试 + 实际 `manage.py` 命令 smoke + Celery task 注册/Beat/PeriodicTask 集成测试 + 固定最小回归包 |
| 回滚点 | 新 owner、兼容 alias、调度切换分步提交；回滚调度后旧 task 仍可执行，不以数据库手工修复作为唯一回滚方式 |

### R2 测试收敛（低风险大收益）

| 项 | 内容 |
|---|---|
| 范围 | ① 顶层 `tests/conftest.py` 提供共享 `api_client/auth_user/authenticated_client` 与实体工厂，消除 252 处 `create_user` 重复；② `tests/api/test_*_api_edges.py` 参数化为"端点×角色×断言"契约矩阵，同时保留端点特有副作用与错误语义测试；③ `test_tui_workbench.py` 静态字符串断言改为扫描脚本 + 少量契约测试；④ ai_capability per-owner 族参数化；⑤ readiness 测试族只在 R1C 合并后处理，R1A/R1B/R1C 期间不得并行重写 |
| 行数影响 | tests 20 万 → 15-16 万（api_edges 14.7k→~7k；tui_workbench 7.8k→~2k；readiness 9.9k→~5k；ai_capability 12.5k→~5k） |
| 验收标准 | 建立“原测试 ID/语义 → 新矩阵 case/扫描规则”映射；权限、状态码、Content-Type、数据库副作用和错误分支覆盖不减少；pytest collected case 数仅作观察指标，不作为覆盖充分性的替代；无新增 skip/xfail；全量 pytest 通过 |
| 回归范围 | 被参数化的每个测试族单独跑通后，运行全量 unit/API/integration；TUI 相关变更补 UAT/Playwright 抽样，不以全量 unit 替代用户流程验证 |
| 回滚点 | 每个测试族一个 commit，可单独 revert |

### R3 decision_rhythm 拆分为 4 个模块（中风险，契约测试先行）

| 项 | 内容 |
|---|---|
| 范围 | 分两阶段执行：① 先拆无状态 Domain/Application 能力与 composition，建立 `advisor`、`recommendation`、`valuation` owner，`decision_rhythm` 保留 quota/cooldown 内核，旧 import 入口保留兼容 facade；② ORM 模型按 R0 决策另立 migration 批次，不与第一阶段混合。`feature_providers.py` 中估值逻辑先迁入 valuation Domain，再由 Application Protocol 注入，不允许新 app 直接互相 import Infrastructure |
| 行数影响 | 行数基本不变（搬家）；收益在边界与命名诚实 |
| 验收标准 | 31 个 API path 契约先行且全部通过；dashboard / terminal / agent_runtime 消费方逐一回归；目标 app 依赖 DAG 经 cycle guard 证明无环；`app_label/db_table/ContentType/permission/URL namespace/Celery task/event source` 均按 R0 结论保持或有显式迁移测试 |
| 回归范围 | 固定最小回归包 + decision_rhythm 全部既有测试 + 三消费方相关测试 + migration plan/check + Celery task 注册与事件 source 兼容测试 |
| 回滚点 | 无状态拆分、兼容 facade、ORM migration 分批提交；若模型 app identity 发生变化，采用 expand/contract 或可逆状态迁移，不承诺通过简单代码 revert 回滚数据库中间态 |

### R4 account 拆 portfolio/rbac + 风险参数体系统一（中高风险，涉及 migration）

| 项 | 内容 |
|---|---|
| 范围 | ① 拆出 `apps/portfolio`（7 模型 + 仓储 + API + service）；② 拆出 `apps/rbac`，但 `PortfolioObserverGrant` 的 owner 必须按 R0 的授权/组合语义矩阵决定，不因文件名直接归 rbac；③ 只合并 R0 矩阵证明同义的风险字段：Risk Center 继续拥有全局/模板/账户风险政策，持仓级止损止盈状态、交易成本、触发记录等不同作用域概念不得被整体并入 `RiskParameterMixin`；④ `init_docs.py` 615 行硬编码 markdown 迁为数据文件 |
| 行数影响 | 搬家为主；净删目标在语义矩阵完成后重新估算，不预设通过删除不同作用域模型取得 1-2k 收益 |
| 验收标准 | migration 在脱敏的生产级 PostgreSQL 备份上演练通过；每个被合并字段都有 source→target、单位、默认值、优先级、消费者切换和反向恢复规则；既有 API 契约不变；account 收敛为身份/账户本职 |
| 回归范围 | 固定最小回归包 + account 全量测试（113 项单元 + 51 项 API/集成为基线）+ risk_center / strategy / simulated_trading 联动链路 |
| 回滚点 | 数据迁移前必须有已验证备份；采用 expand→backfill→read switch→write switch→contract 分步，只有定义了双读/双写或兼容 facade 的阶段才允许停留；发生新写入后不得把“恢复旧备份”作为常规回滚方案 |

### R5 SDK manifest 生成化 + 能力目录单一真源（依赖 manifest vNext 机器启动条件）

| 项 | 内容 |
|---|---|
| 范围 | ① 以版本库内的 canonical manifest vNext 为 SDK/MCP 构建真源，完整表达 input/output schema、executor、confirmation preview/commit、idempotency、roles、audit tags、legacy replacement 等治理字段；② `apps/ai_capability` 继续作为该 manifest 及其他 API/terminal 能力的运行时投影，并将人工 routing/visibility override 与 collected 字段明确分层；③ 只生成机械层（registry index、tool/module wrappers、owner 参数化测试等），runtime handler 的业务逻辑不从 DB 生成；④ 退役反向 sync 双真源机制 |
| 行数影响 | sdk 7.4 万 → ~5 万 |
| 验收标准 | 干净 checkout、无数据库、无 Django runtime 时可确定性生成；连续生成两次 git diff 为空；canonical manifest → 生成物 → runtime catalog projection round-trip 无字段丢失；现有 SDK/MCP 行为、权限、确认、幂等和审计测试全部通过；新增能力变为“改 1 份 manifest + 重新生成” |
| 回归范围 | `pytest sdk/tests -q` 全量 + MCP 契约测试 + 固定最小回归包 |
| 回滚点 | schema vNext、生成器、生成物切换、DB projection 切换分步落地；手写版保留一个验证周期，生成产物带 schema/version 标识，可切回上一版本生成快照 |

### R6 合并与清理（可选，逐项评审后插入）

| 候选项 | 行数影响 | 说明 |
|---|---|---|
| `policy` 错位归位：RSS 摄取 → 独立 app 或 data_center；`HedgePositionModel` → hedge；`SentimentGateConfig` → sentiment/beta_gate | 搬家 + 净删 ~1k | 启动前先证明是否真有双写，并产出 owner/数据迁移矩阵 |
| `data_center` `_provider_adapter_*` 遗留清理 + DTO 归并 | 待重新审计 | `repository-debt-remediation-closure-2026-07-19.md` 已声明上一轮 adapter 收口完成，本项必须以当前文件 inventory 和运行引用重新证实，不沿用旧行数直接立项 |
| TUI metadata 三轨验证归一：声明 `jsonschema` 依赖，schema 为真源，Python 常量改生成 | 净删 ~1k | 依赖只改 `pyproject.toml`，并通过 `scripts/sync_dependency_projections.py` 更新生成投影；同步 schema/compiler/runtime injection 与用户任务测试 |
| equity `valuation_repair` 补丁族（~2.5k 行）整合；screener 引擎上抽 asset_analysis | 净删 ~1-2k | fund/equity 各一份 screener 的结构性重复 |
| signal + alpha_trigger 合并为统一信号生命周期域 | 净删 ~2-3k | 省一套 interface + 一套证伪 UI；signal 被 14 个 app 依赖，需单独评审 |

---

## 5. 代码量目标

以下目标分为保守目标、`filter` 满足 sunset 条件后的条件目标，以及依赖 R6 逐项证实的延伸目标。搬家只改变模块归属，不计入全仓净删；任何批次不得为了命中行数目标合并不同语义、删除契约测试或生成不可审查的代码。

| 部分 | 现状 | 保守目标 | `filter` 下线后 | 延伸目标 | 手段 |
|---|---|---|---|---|---|
| apps + core/shared | ~36 万 | 35-36 万 | 33-34 万 | 30-31 万 | readiness 去重、filter 经完整 sunset 后下线、R6 经证实的去重；模块搬家不计净删 |
| tests/ | ~20 万 | 15-16 万 | 15-16 万 | 15-16 万 | 共享 fixture + 参数化 + 语义映射 |
| sdk/ | ~7.4 万 | ~5 万 | ~5 万 | ~5 万 | canonical manifest 确定性生成 |
| 其余 | ~6 万 | ~6 万 | ~6 万 | ~6 万 | 原则上不动；readiness 搬入 ops/app 时不把分类变化误计为净删 |
| **合计** | **~69 万** | **~61-63 万** | **~59-61 万** | **~56-58 万（需 R6 证实）** | |

**关键认知**：可维护性收益主要来自归位（找得到代码）、单一真源（改一处不改四处）、稳定身份（迁目录不破坏生产契约）和生成替代手写（新增能力不再复制 4 遍）。行数是结果指标，不是驱动语义合并的目标。

---

## 6. 每批通用验收门槛

- CI 架构护栏（domain/application/interface 层扫描）通过。
- AGENTS.md 固定最小回归包 4 条通过：`pytest tests/unit/test_tui_workbench.py -q`、`pytest tests/unit/test_terminal_agent_service.py -q`、`pytest sdk/tests/test_sdk/test_client.py -q`、`pytest tests/unit/test_internal_ssl_redirect.py -q`。
- 只有机器事实发生变化时才通过现有生成/检查脚本更新 `governance/governance_baseline.json`、module cycle allowlist 或 mypy 基线；禁止为让 CI 变绿而手工放宽预算或新增 allowlist。
- 涉及 Django 模型归属时，必须检查 migration plan、ContentType、权限、`db_table` 与反向迁移；涉及 Celery/事件/命令时，必须检查稳定名称和历史 provenance。
- 涉及生成器时，必须在干净 checkout、无运行数据库环境完成确定性生成，并执行“生成两次 diff 为空”检查。
- docs 同步：本计划对应批次状态更新 + 相关模块文档更新。
- 每批结束后按 `repository-debt-remediation-closure-2026-07-19.md` 惯例补阶段记录文档。

---

## 7. 风险与未验证项

- **未验证项**（纳入 R0，不再留到实施中临时判断）：`apps/filter` 的访问日志、登记客户端、离线/定时调用和 governed capability 使用；现有 SDK 生成脚本及可复用边界；`tests/uat`、`tests/playwright` 对 TUI/API 主任务的覆盖；Decision Rhythm model/app identity；readiness 外部监控与历史 evidence 对完整 task name 的依赖。
- **R1C/R3/R4 涉及稳定身份或数据迁移**：契约测试必须先行；生产数据迁移必须在已验证备份上演练；备份只解决灾难恢复，不替代可逆 migration、兼容 alias 或 expand/contract 设计。
- **与相关主线的协调**：
  - `uat-remediation-2026-07-20`（代码整改完成，待生产发布与数据回填）——R3/R4 排在其生产发布之后。
  - `mcp-consolidation-remediation-plan-2026-07-09` 已记录 SDK/MCP 契约全量收口结果，但仍有按证据冻结的 raw-tool gap。R5 不再等待笼统的“计划收口”，启动条件改为：canonical manifest vNext 字段评审通过、现有 registry/governance tests 绿色、raw legacy disposition 可由 vNext 无损表达、生成范围与 runtime handler 边界已冻结。
  - `architecture-cycle-remediation-2026-07-15` 已完成零双向依赖、零强连通循环组件收口；它不再是等待项。R3/R4 必须以当前空 allowlist 和现有 graph budget 为硬基线，不得新增循环或放宽预算。

---

## 8. 建议排期

| 窗口 | 批次 | 前提 |
|---|---|---|
| 立即可做 | R0 | 只做 inventory、矩阵、契约与真源决策，不改运行行为 |
| R0 批准后 | R1A deprecated 阶段 → R1B | 两者独立分支、串行合并；R1A 是否物理删除取决于完整 sunset 证据 |
| R1B 完成并单独批准后 | R1C | 必须先具备旧命令/task alias、调度迁移和历史 evidence 兼容方案 |
| R0 完成后 | R2 非 readiness 测试族 | 与 R1B/R1C 不修改同一测试族；readiness 测试压缩排在 R1C 合并之后 |
| uat-remediation 生产发布完成后 | R3 → R4（串行，均涉及运行面） | R3 先无状态拆分、ORM 另批；R4 先语义矩阵、再 migration/备份演练 |
| R5 机器启动条件满足后 | R5 | manifest vNext、无损表达、生成边界和治理回归全部就绪 |
| 穿插 | R6 单候选审计 | 每项先重新取证，再独立决策、独立分支；不得用 R6 填补行数目标 |

每批 1 个 `dev/*` 分支 + 独立 PR + 阶段记录文档；单日不并行推进两个高风险批次（R1C/R3/R4/R5）。R2 的 readiness 子批次不得与 R1B/R1C 并行。
