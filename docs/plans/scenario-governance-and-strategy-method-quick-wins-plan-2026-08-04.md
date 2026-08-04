# 情景治理与策略研究 Quick Wins 整改计划（2026-08-04）

> 状态：提案，待评审后按独立主线实施
> 级别：业务配置治理 / 风险研究 / MCP 写能力 / TUI 用户任务
> 适用版本：0.8.0 之后
> Canonical owner：`risk_center`（情景定义与风险解释）
> 依赖 owner：`data_center`、`portfolio`、`strategy`、`research`、`ai_capability`、`terminal`、`audit`
> 来源边界：方法参考来自用户对四份策略会材料的摘要；本计划未读取原始 PDF，不把摘要外推为原材料的精确需求。

## 1. 执行结论

本计划解决两类问题：

1. 移除压力测试情景、建议阈值和运行参数的代码级业务硬编码，把情景变成可版本化、可审批、可回滚、可审计的运行时业务配置。
2. 在不启动重型量化研发的前提下，复用现有 Regime、Policy、Pulse、市场温度计、估值、组合、回测和 Agent 能力，补齐策略会方法中开发成本较低、决策收益较高的功能。

整改后的核心链路固定为：

```text
Data Center 可用事实
        ↓
情景定义 / 情景集版本（Risk Center）
        ↓
影响预览与组合压力测试（Portfolio snapshot + PIT evidence）
        ↓
胜率/赔率记分卡 + 情景矩阵 + 研究简报
        ↓
人工确认后激活配置；策略和执行只消费已激活版本
        ↓
Audit 记录版本、输入、结果与后续兑现
```

本计划不允许 AI 原地修改已生效配置。AI/MCP 只能创建不可变替代版本、预览差异并提交 AgentProposal；AI service principal 不能批准或激活自己的提案。激活、停用和回滚必须由人类 staff/operator 经服务端 RBAC、持久审批、确认、幂等和审计门禁执行。

## 2. 现状问题与整改依据

### 2.1 已确认的硬编码

当前 `apps/account/application/stress_testing_use_cases.py` 存在以下运行时业务常量：

| 问题 | 当前实现 | 风险 |
|---|---|---|
| 固定历史情景目录 | `HistoricalScenarioService.SCENARIOS` 直接定义 `2015_crash`、`2020_covid`、`2018_trade_war` | 新增、停用或修订情景必须发版 |
| 固定情景日期 | 起止日期直接写在 Application 文件 | 不能版本化，无法记录来源与修订理由 |
| 固定初始资产 | 压力测试使用 `Decimal("1000000")` | 与真实组合权益脱节，结果口径不透明 |
| 固定建议阈值 | 回撤、波动和亏损阈值直接生成建议 | 策略参数散落，不能在线调整或回滚 |
| 固定测试目录 | 单元测试断言情景正好为 3 个 | 测试反向锁死业务目录 |
| 缺少配置入口 | 没有情景 Repository、数据库模型、API、TUI、SDK/MCP | 不能形成运营和审计闭环 |

相邻链路还存在第二组必须纳入 M0 审计的业务硬编码：`apps/strategy/domain/allocation_matrix.py` 中的 4×4 配置比例、预期收益、预期波动、Sharpe 和 Policy 权益乘数。情景工作台不得继续把这套常量当成不可解释的下游真源。整改时应：

- 由 `strategy` 拥有版本化 Allocation Policy，而不是迁入 Risk Center；
- 配置比例与 Policy 调整在线可审计、可回滚；
- 预期收益/波动来自已批准研究结果或显式人工假设，不能继续由代码常量伪装成估计值；
- 情景运行证据同时引用 `scenario_revision_id` 和 `allocation_policy_version`。

### 2.2 不是删除旧情景，而是取消其运行时特权

2015 股灾、2020 疫情和 2018 贸易摩擦仍可作为历史样本保留。整改目标不是追逐新闻并删除旧样本，而是：

- 旧样本通过一次性数据迁移成为数据库中的初始版本；
- 运行时不再回退到 Python 常量；
- 新情景可以在不发版的情况下新增、修订、停用和回滚；
- 滚动情景能根据最新已发布数据持续更新；
- 每次压力测试都引用确定的情景版本和组合快照。

### 2.3 架构边界

- `account` 只保留身份与迁移期兼容 Facade，不继续拥有情景业务真源。
- `risk_center` 拥有情景定义、版本、激活规则、风险解释和压力测试政策。
- `portfolio` 提供不可变持仓/组合快照，不让风险引擎跨 App 直查 ORM。
- `data_center` 提供 historical/as-of 或 current published 数据；情景引擎不得直接调用外部数据源。
- `strategy` 消费已激活情景集和风险输出，不拥有另一份情景映射。
- `research` 保存需要晋级的实验与 PIT 证据；探索性结果不得自动进入生产。
- `ai_capability` 只保存能力治理投影，真实执行必须落到 Risk Center Application UseCase 或 canonical API。
- `terminal` 只发布 TUI metadata，不承载情景业务规则。

## 3. 目标与成功标准

### 3.1 业务目标

1. 管理员或投资经理可以在线创建情景草稿、比较版本、预览组合影响、激活和回滚。
2. 普通用户可以查看当前情景集、假设、概率、证据时间和组合影响，但不能修改生产配置。
3. AI Agent 可以通过 governed MCP capability 创建修订草稿和影响预览；生产激活必须显式确认。
4. 压力测试同时支持历史窗口、滚动极端窗口、参数冲击和宏观路径情景。
5. 系统可在策略简报中解释“哪个情景、哪些假设、什么概率、对哪些资产产生什么影响”。

### 3.2 工程成功标准

1. 运行时代码中不存在历史情景目录、情景日期、默认组合本金、建议阈值、资产配置比例或 Policy 调整乘数的业务真源。
2. 每个生效版本具有 `version`、`content_hash`、`change_reason`、`created_by`、`effective_at` 和来源证据。
3. 已激活版本不可原地更新；修改只能创建新版本。
4. 压力测试结果引用 `scenario_revision_id`、`scenario_set_revision_id`、`portfolio_snapshot_id`、`as_of_time` 和数据证据。
5. MCP 写能力满足 preview-first、RBAC、确认、幂等、乐观锁、审计和稳定错误 envelope。
6. stale、missing、unpublished 或时间穿越数据不得生成可用于决策的成功结果。
7. 迁移期兼容入口连续一个稳定版本无旧写入后方可删除。

## 4. 范围与非目标

### 4.1 本计划范围

- 历史情景硬编码迁移。
- 情景定义、修订、情景集、激活和运行证据模型。
- 动态滚动情景和参数化情景。
- 初始新增的宏观二维情景假设。
- API、SDK、governed MCP capability 和 TUI 用户任务。
- 情景矩阵、胜率/赔率记分卡、研究简报、经营驱动敏感性工作表等 Quick Wins。
- 必需的架构、数据新鲜度、MCP、TUI、测试与发布门禁。

### 4.2 明确不在本轮实施

- Factor Mimicking Portfolio、Lasso、显著性检验、BIC 和完整宏观因子风险平价。
- 自动化公司季度盈利预测和行业高频经营数据全量接入。
- 完整债券久期、凸性、carry、roll-down 和信用组合优化。
- Markov 状态切换、政策反应函数和自动概率校准。
- AI 自动激活生产情景、自动下单或绕过 Beta/Risk Gate。
- 新增 Classic Django 业务主页面。
- 在 MCP 顶层增加新的 raw `@server.tool()`。

上述能力进入另行维护的《策略研究能力后续开发备忘》。

## 5. Canonical 数据模型

### 5.1 Domain 实体

建议在 `apps/risk_center/domain/scenarios.py` 建立纯 Domain 值对象：

| 实体 | 关键字段 | 不变量 |
|---|---|---|
| `ScenarioDefinition` | `scenario_key`、名称、分类、owner、状态 | `scenario_key` 稳定且不可复用 |
| `ScenarioRevision` | `revision_id`、版本、`based_on_version`、状态、类型、假设、来源、证据、时间范围、`content_hash` | 发布后不可变；类型化校验通过 |
| `ScenarioSet` | `set_key`、用途、适用资产范围 | 只表达情景集合身份 |
| `ScenarioSetRevision` | 成员修订、概率、驱动轴、有效期 | 概率和为 1；不得引用草稿成员进入激活版本 |
| `ScenarioActivation` | 环境、激活版本、前版本、操作者、原因、时间 | 同一环境同一用途只能有一个 active 版本 |
| `ScenarioRunEvidence` | 情景版本、组合快照、PIT/Publication 证据、结果 hash | 输入引用完整才允许标记 decision-usable |

所有 Domain 实体使用 `@dataclass(frozen=True)`，不得依赖 Django、Pandas、NumPy 或外部 SDK。

### 5.2 情景类型

`scenario_type` 使用稳定枚举，不允许任意 Python 表达式：

| 类型 | 用途 | 主要参数 |
|---|---|---|
| `historical_window` | 回放真实历史窗口 | `start_date`、`end_date`、source、事件说明 |
| `rolling_extreme` | 自动寻找近期极端区间 | `lookback_days`、`window_days`、选择指标、方向、重算频率 |
| `parametric_shock` | 对资产/因子施加显式冲击 | 类型化 shock 列表、单位、horizon、相关性假设 |
| `macro_path` | 条件化宏观路径或二维情景 | 驱动变量、离散状态、概率、路径节点、证伪条件 |

参数 JSON 只作为持久化边界；进入 Domain/Application 前必须通过类型化 DTO、`TypedDict` 或 dataclass 收窄。禁止 `eval`、脚本字符串和无限递归公式。

### 5.3 数据库模型

Risk Center Infrastructure 增加：

- `StressScenarioDefinitionModel`
- `StressScenarioRevisionModel`
- `ScenarioSetModel`
- `ScenarioSetRevisionModel`
- `ScenarioSetMemberModel`
- `ScenarioActivationModel`
- `ScenarioRunEvidenceModel`

关键约束：

- `(scenario_definition_id, version)` 唯一；
- `(scenario_set_id, version)` 唯一；
- `content_hash` 与结构化内容一致；
- activation 只引用 validated revision；
- revision 不允许 update/delete，废弃通过状态和替代版本表达；
- revision 状态至少区分 `draft/proposed/approved/active/superseded/rejected`，并记录 `source_type=human/ai_mcp/seed/detector`；
- 幂等键在作用域内唯一；
- `created_at/effective_at/observed_at` 全部 timezone-aware；
- 所有修改记录 actor、source channel、correlation ID 和 change reason；
- revision、activation 和 canonical domain audit 必须由显式 transaction/Unit of Work 同事务提交；审计失败时整单回滚。

### 5.4 Repository 与 UseCase

Application 只能依赖 Protocol：

- `ScenarioQueryRepositoryProtocol`
- `ScenarioRevisionRepositoryProtocol`
- `ScenarioActivationRepositoryProtocol`
- `ScenarioRunEvidenceRepositoryProtocol`
- `PortfolioSnapshotProviderProtocol`
- `ScenarioMarketDataProviderProtocol`

核心 UseCase：

- `ListScenarioDefinitions`
- `GetActiveScenarioSet`
- `CreateScenarioRevisionDraft`
- `ValidateScenarioRevision`
- `PreviewScenarioImpact`
- `ActivateScenarioSetRevision`
- `RollbackScenarioSetRevision`
- `GenerateRollingScenarioCandidate`
- `RunPortfolioStressTest`

## 6. 迁移设计

### M0：冻结边界与建立清单

1. 登记所有 `HistoricalScenarioService`、`StressTestingUseCase` 和旧接口调用方。
2. 冻结新增 `SCENARIOS`、日期、阈值和默认本金常量。
3. 输出兼容映射：旧 scenario ID → 新 `scenario_key`。
4. 审计 `ALLOCATION_MATRIX`、预期收益/波动、Sharpe 和 Policy 乘数，冻结新的策略业务常量。
5. 确认压力测试 canonical owner 为 Risk Center，Allocation Policy canonical owner 为 Strategy，Account 仅保留转发 Facade。
6. 为本计划建立独立分支/commit 组，不与 Data Center 唯一真源重构、部署修复或 TUI 大迁移混在同一批次。

验收：扫描脚本能够识别新增的情景业务常量和 Application 级静态目录。

### M1：扩展式建表与初始数据迁移

1. 建立 Domain、Repository Protocol、ORM 模型和迁移。
2. 使用 Django data migration 把三个旧情景迁为 `historical_window` v1：
   - 保留旧 `scenario_id` 作为 alias；
   - `source_type=legacy_code_migration`；
   - 记录原文件、原日期和迁移版本；
   - 迁移只负责初始数据，不成为新的运行时 fallback。
3. 把初始资产改为调用方传入的实际组合权益或 Portfolio Snapshot 净值。
4. 把建议阈值迁入版本化 Risk Center 配置，不放入 Domain 常量。
5. 新 UseCase 通过 Repository 获取情景；目录为空时 fail closed 并提示初始化/配置，不回退到 Python 常量。
6. 在 `strategy` 建立版本化 Allocation Policy，把 4×4 配置和 Policy 调整作为 `legacy_code_migration` 初始版本迁入数据库。
7. 旧预期收益、波动和 Sharpe 只能迁为显式 `legacy_unverified` 假设；没有批准研究证据时不得发布为模型估计。
8. Strategy 读取只消费 active Allocation Policy；缺少 active policy 时 fail closed，不回退到 `ALLOCATION_MATRIX`。

验收：旧 ID 和旧配置调用结果与迁移前基线一致；重启和重复迁移不会生成重复版本；情景与 Allocation Policy 均无代码常量 fallback。

### M2：兼容切读与运行证据

1. `apps/account/application/stress_testing_use_cases.py` 变为兼容 Facade，转发 Risk Center Application UseCase。
2. 压力测试使用不可变 Portfolio Snapshot，不在 Risk Center 内跨 App 查持仓 ORM。
3. 历史回放读取 Data Center historical/as-of port；滚动情景读取 published current port。
4. 每次运行保存情景、组合、数据、配置和代码版本证据。
5. 对旧入口记录 deprecated 使用计数；连续一个稳定版本无旧写入后再删除。

验收：相同输入版本可复算相同结果；不同 revision 不会被静默合并。

## 7. 新增情景假设

### 7.1 动态滚动情景

首批动态情景不依赖人工维护事件日期：

| 情景 | 生成规则 | 更新频率 | 用途 |
|---|---|---|---|
| 近期最差窗口 | 近 N 年中组合/基准最差的连续 M 个交易日 | 每周或月 | 捕捉比 2015/2020 更新的尾部窗口 |
| 波动率冲击 | 近 N 年实现波动率最高窗口 | 每周 | 测试波动扩张与仓位上限 |
| 流动性收缩 | 成交额、融资余额、ETF 流同步恶化的历史窗口 | 每周 | 连接市场温度计与组合风险 |
| Regime 转折窗口 | Regime/Pulse 出现显著背离后的历史样本 | 月度 | 检验环境切换敏感性 |

动态生成结果先进入 `candidate`，只有数据覆盖、来源、时间窗口和人工审核完整后才可成为 active revision。

### 7.2 参数冲击情景

首批支持以下类型化冲击，不以固定幅度写入代码：

- 权益指数或行业收益冲击；
- 利率平移/陡峭化/扁平化，单位为 bp；
- 信用利差扩大/收窄，单位为 bp；
- 人民币汇率冲击；
- 原油、铜、黄金等商品价格冲击；
- 成交额、融资余额、ETF 流动性冲击；
- 组合相关性上升和可交易性折扣。

具体幅度、horizon 和适用资产必须来自 Scenario Revision；代码只提供 Schema 和安全范围。

### 7.3 宏观二维情景集

参考权益市场材料摘要，建立一个数据库初始化候选集，不直接激活：

| 横轴 | 纵轴 | 情景 |
|---|---|---|
| AI Capex 延续 | 海外货币偏鸽 | 风险偏好扩散、成长与周期均可能受益 |
| AI Capex 延续 | 海外货币偏鹰 | AI 主线占优、估值与流动性约束增强 |
| AI Capex 回落 | 海外货币偏鸽 | 非 AI、利率敏感和防御资产可能接力 |
| AI Capex 回落 | 海外货币偏鹰 | 风险资产先承压，等待政策或盈利证据转向 |

每个象限必须配置：

- 明确定义的可观测代理变量；
- 当前值、来源、观测时间和 freshness；
- 主观概率及修改人；
- 受益/受损资产映射；
- 证伪条件；
- 组合影响预览；
- 下次复核日期。

### 7.4 货币—信用情景集

参考宏观固收材料摘要，增加四象限候选：

- 宽货币 + 宽信用；
- 宽货币 + 紧信用；
- 紧货币 + 宽信用；
- 紧货币 + 紧信用。

本轮只提供规则化状态、利差雷达和组合解释，不宣称已构建政策反应函数或债券定价模型。

## 8. AI MCP 修改情景假设接口

### 8.1 原则

1. 真实执行源是 Risk Center Application UseCase / canonical API。
2. SDK 负责类型化客户端；MCP 只做 governed transport。
3. 不新增 raw 顶层 tool，通过现有 `agom_capability_search/schema/call` 发现和调用；高风险激活不依赖进程内 confirmation 状态。
4. AI 修改永远创建新 revision，不允许 PATCH 已发布 revision。
5. AI 只能提出 revision proposal；人类 staff/operator 才能批准并执行激活、停用或回滚。
6. Prompt、manifest role 和 MCP 进程状态都不是最终安全边界，Django Application 必须依据真实用户或 AI service principal 再鉴权。

### 8.2 HTTP 与 SDK 面

建议 canonical API：

| 语义 | API 行为 | SDK 方法 |
|---|---|---|
| 列出/读取 | 查询定义、版本、active set | `list_scenarios()`、`get_scenario()`、`get_active_scenario_set()` |
| 校验草稿 | 只做 Schema/业务校验，不写入 | `validate_scenario_revision()` |
| 影响预览 | 返回 diff、数据依赖、组合影响，不激活 | `preview_scenario_revision()` |
| 创建修订提案 | 新建 draft/proposed revision 和持久 AgentProposal | `propose_scenario_revision()` |
| 批准/激活 | 人类批准后单独执行的高风险写操作 | `approve_scenario_proposal()`、`activate_scenario_revision()` |
| 回滚 | 人类批准后把旧内容复制为新 revision 并激活 | `rollback_scenario_revision()` |
| 停用 | 用替代版本或 retired 状态表达 | `retire_scenario()` |

API 路径由实现阶段的 DRF router 统一确定；TUI 普通用户文案不得暴露路径、HTTP method 或裸参数名。

### 8.3 Governed capability keys

建议 capability 语义：

- `risk_center.stress_scenario.list`
- `risk_center.stress_scenario.read`
- `risk_center.stress_scenario.compare`
- `risk_center.stress_scenario.validate_revision`
- `risk_center.stress_scenario.preview_revision`
- `risk_center.stress_scenario.propose_revision`
- `risk_center.stress_scenario.activate_revision`
- `risk_center.stress_scenario.rollback_revision`
- `risk_center.stress_scenario.retire`

其中 list/read/compare/validate/preview 不改变生效状态；propose 只创建持久提案；activate/rollback/retire 只能执行已获人类批准的提案。

### 8.4 写能力强制契约

所有写能力必须包含：

- `requires_confirmation=true`；
- `idempotency=required` 和稳定的 `idempotency_key`；后端数据库建立 `(actor_id, capability_key, idempotency_key)` 唯一约束和 request fingerprint；
- `expected_active_version`、`expected_active_hash` 或 `based_on_version` 乐观锁；
- preview-first 证据，返回 `preview_id/request_fingerprint/base_version/base_hash/after_hash/expires_at`；
- actor、role、source channel、change reason、correlation ID；
- 输入白名单和未知字段拒绝；
- `audit_tags`；
- commit 逐项复核 actor、role、scenario、exact payload hash、base version/hash、expiry 和 single-use；
- 重放相同 idempotency key + 相同 fingerprint 返回原结果；同 key 不同 payload 返回冲突，不创建新版本；
- stale preview、版本冲突或权限不足时返回稳定冲突/阻断，不允许 lost update；
- 激活使用数据库事务、行锁和条件唯一约束，保证同一作用域只有一个 active；
- canonical domain audit 与 revision/activation 同事务并 fail closed；MCP transport audit 只作为第二层记录。

现有 MCP dispatcher 的 pending confirmation/idempotency 可能是单进程状态，不能作为多 worker、重启后的最终保证。情景写入必须使用后端持久幂等；高风险激活优先复用持久 `AgentProposal → 人类 approve → execute` 链路，或实现等价的单次持久确认，不走可被新参数覆盖的简化确认路径。

权限建议：

| 操作 | 最低权限 | 说明 |
|---|---|---|
| 读取/预览 | 已认证且有账户/情景可见性 | 不返回无权组合和敏感账户信息 |
| 创建提案 | `investment_manager`、`admin` 或受限 AI service principal | AI 只能提案，草稿不影响生产 |
| 批准/激活/停用/回滚 | 人类 `staff/operator/admin`；生产可配置双人复核 | approver 不得等于 AI principal，不允许 Agent 自动续跑 |

### 8.5 MCP 返回契约

写能力统一返回：

- `status`：`preview_required / confirmation_required / created / activated / rolled_back / rejected`；
- `scenario_key`、`revision_id`、`proposal_id`、`preview_id`、`version`、`content_hash`；
- `diff` 和 `impact_summary`；
- `warnings`、`blocked_reason`、`must_not_use_for_decision`；
- `audit_id`、`correlation_id`；
- 可选 `next_actions`，不得暗示已执行未执行的激活或交易。

## 9. 低成本高收益功能包

### 9.1 取舍原则

优先复用现有数据与规则，先补“组织、解释和决策闭环”，不先造重型统计模型。所有评分必须展示组件和来源，不把规则分数包装成科学概率。

| ID | 功能 | 参考方法 | 成本 | 预期收益 | 复用能力 |
|---|---|---|---|---|---|
| QW-1 | 前瞻情景矩阵与组合影响预览 | 权益市场、宏观固收 | 中 | 很高 | Regime、Policy、Pulse、Strategy、Portfolio |
| QW-2 | 事前“胜率/赔率”双记分卡 | 高频宏观、宏观固收 | 小—中 | 很高 | Regime fit、估值分位、利差、风险中心 |
| QW-3 | 五维市场状态证据卡 | 权益市场 | 小 | 高 | Regime、Pulse、Rotation、Equity、市场温度计、Valuation |
| QW-4 | 自动策略简报与反方观点 | 四份材料共同链路 | 小 | 高 | Agent、Prompt、Share、Audit |
| QW-5 | 固收利差雷达 Lite | 宏观固收 | 小—中，受数据约束 | 中—高 | Macro、Regime、Data Center |
| QW-6 | K 型结构/自定义资产组比较 | 权益市场 | 中 | 中—高 | Asset master、Sector、Factor、资金流 |
| QW-7 | 经营驱动与敏感性工作表 Lite | 大消费 | 中，受数据约束 | 高 | Equity、Valuation、Data Center |

### 9.2 QW-1：前瞻情景矩阵

交付内容：

- 用户创建二维或列表型 Scenario Set；
- 每个成员有概率、假设、证伪条件和复核日期；
- 展示各情景下大类资产与当前组合的影响；
- 展示概率加权结果，但不自动下单；
- 情景概率总和必须为 1，主观概率与模型推断分开标注。

验收：用户无需编辑代码即可复制现有情景集、调整假设和概率、预览差异并创建新版本。

### 9.3 QW-2：事前胜率/赔率双记分卡

定义：

- `environment_fit_score`：Regime、Policy、Pulse、流动性和资产适配度形成的事前环境分；
- `valuation_odds_score`：估值分位、股息率、ERP/利差等形成的赔率分；
- 历史交易 `win_rate` 继续只表示已实现胜率，不得复用同一字段名。

要求：

- 输出 0—100 分时同时输出组件、权重、数据时间和缺失项；
- 缺少关键数据时返回 unavailable/blocked，不用 0 或中性值填充；
- 第一版只覆盖证据完整的权益和大类资产，不为覆盖面伪造债券/商品估值；
- 权重进入版本化业务配置并支持回滚。

### 9.4 QW-3：五维市场状态证据卡

复用现有能力聚合五个维度：

- 宏观：Regime 与 Pulse；
- 产业：Sector 与 Rotation；
- 盈利：Equity 财务增长、质量和覆盖率；
- 资金：开户、成交额、融资余额、ETF 流、情绪和市场宽度；
- 估值：PE/PB、股息率和历史分位。

第一版只做证据聚合、方向比较和冲突提示，不再创建一个不透明综合模型。每个维度必须发布 `observed_at`、freshness、coverage、source 和阻断状态；多个维度冲突时保留冲突，不强行平均成单一结论。

验收：TUI 首屏一屏可读，任一缺失项不会被 0、中性分或请求时间掩盖，并可直接作为情景假设与胜率/赔率卡的证据输入。

### 9.5 QW-4：自动策略简报

统一生成：

1. 当前 Regime/Policy/Pulse；
2. 市场温度、资金和估值；
3. 主情景、备选情景及概率；
4. 胜率/赔率记分卡；
5. 当前组合脆弱点与压力测试；
6. 反方观点和证伪条件；
7. 数据 freshness、缺失项和禁止用于决策提示。

AI 只根据结构化事实生成解释。简报必须保存事实引用、情景版本、Prompt 版本和生成时间，不能通过 Prompt 重新计算金融规则。

### 9.6 QW-5：固收利差雷达 Lite

在数据覆盖通过后，先做只读雷达：

- 10Y—2Y 期限利差；
- 10Y 国债—政策利率；
- 2Y 国债—短端资金利率；
- 信用利差与历史分位；
- 曲线形态和数据时间。

第一版只输出同日对齐的当前值、历史分位、z-score、趋势、覆盖率和规则化久期倾向，不输出债券交易指令，也不声称已实现 carry/roll-down 或信用组合优化。单位必须统一为 BP/%；阈值数据库化；若 Data Center 缺少可发布数据，QW-5 自动降为长期备忘项。

### 9.7 QW-6：K 型结构/资产组比较

允许通过数据库定义资产组，例如 AI/非 AI、成长/价值、内需/外需、大盘/小盘。输出相对收益、市场宽度、估值分位、资金流和盈利增速差异。

要求：

- 资产组成员必须有生效日期和版本；
- 不在代码中硬编码 AI 概念股名单；
- 只在分组覆盖率、价格和估值 freshness 达标时发布；
- 结论标记为结构描述，不自动等同于可交易信号。

### 9.8 QW-7：经营驱动与敏感性工作表 Lite

该能力不属于最小成本核心包。只有至少一个行业的 KPI 字典和事实口径明确后才进入 M5B；否则完整能力保留在长期备忘。第一版不自动预测，也不接入昂贵的行业高频数据，只提供数据库驱动的类型化模板：

- 餐饮：门店数 × 同店销售 × 客单价；
- 零售/零食：门店数 × 单店收入，并单列毛利率、净利率；
- 啤酒：销量 × 吨价；
- 教育：培训人数 × 学费；
- 服装：渠道/门店 × 单店收入 × 毛利率。

用户可录入 base/bull/bear 假设，系统生成收入、利润和估值敏感性。禁止任意脚本公式；模板采用有限算子和字段 Schema。结果可以生成 Valuation 草稿，但不能替代正式数据或自动激活估值。

## 10. 分阶段实施与依赖

| 阶段 | 主交付 | 前置依赖 | 退出标准 |
|---|---|---|---|
| M0 | 冻结、清单、ADR、情景与 Allocation Policy 硬编码扫描 | 无 | owner、旧入口和常量清单冻结 |
| M1 | Scenario Domain/ORM/Repository、Allocation Policy 与旧数据迁移 | M0 | 三个旧情景和配置矩阵数据库化，运行时无常量 fallback |
| M2 | Portfolio snapshot、运行证据、兼容切读 | M1、Data Center historical port | 可复算且旧 API 行为兼容 |
| M3 | API/SDK/TUI/MCP 草稿—预览—激活—回滚 | M1-M2 | 权限、确认、幂等、审计全通过 |
| M4 | 滚动、参数化、AI Capex×海外货币、货币×信用情景集 | M2-M3 | 新情景无需发版可维护 |
| M5A | QW-1、QW-2、QW-3、QW-4 | M4 | 用户完成“看五维状态—建情景—预览—形成简报”主任务 |
| M5B | QW-6、QW-7 | M5A 可并行后置 | 资产组数据库化；经营模板满足数据前置才实施 |
| M5C | QW-5 | Data Center 固收数据覆盖门 | 缺数据时 fail closed，不阻塞主线 |
| M6 | shadow、生产切读、旧入口退役 | 稳定观察窗、备份/回滚证据 | 无旧写入，回滚演练通过 |

开发节奏：

- 情景治理、MCP 写能力、Quick Wins 分成独立分支阶段或 commit 组；
- 不和当前 Data Center 架构重构、VPS 部署或治理文档大收口混成单个提交；
- 推荐分支：`dev/refactor-scenario-governance`、`dev/feat-scenario-mcp-governance`、`dev/feat-strategy-method-quick-wins`。

## 11. TUI 用户任务

新增或调整 TUI 时遵守迁移冻结标准：

- 不新增 Classic 业务主页面；
- 情景屏主任务为“查看并调整未来情景，预览对组合的影响”；
- P0 首屏展示 active 情景集、主情景概率、最近修改、数据健康和组合影响；
- 写动作使用专用表单与确认语义，不把 JSON 放给普通用户编辑；
- 非 dashboard screen 有 `default_action_key`；
- 普通用户文案不显示 API path、HTTP method、placeholder 或内部 capability key；
- 所有修改先生成 diff/preview，再进入确认。

建议在既有 `macro-regime.strategy` 或 Risk Center 工作流中增加入口，避免为每个技术对象创建新屏幕。

## 12. 测试与治理门禁

### 12.1 Domain/Application

- 四种情景类型的有效与无效边界；
- 版本不可变、概率和为 1、content hash 稳定；
- 历史/滚动/参数/宏观路径计算；
- 数据缺失、stale、unpublished、未来时间穿越时 fail closed；
- Portfolio Snapshot 与情景版本不匹配拒绝；
- 旧 ID 兼容映射和旧 API 输出一致性；
- fake repository 替代固定情景目录测试。

### 12.2 数据库与迁移

- SQLite 与 PostgreSQL migration graph；
- data migration 幂等；
- 三个旧情景行数、内容和 alias 对账；
- 唯一约束、并发激活和乐观锁；
- 回滚不修改历史 revision。

### 12.3 API/SDK/MCP

- Serializer 未知字段拒绝和数值范围校验；
- RBAC 成功/拒绝；
- preview 零写入，preview hash、actor、payload、base version、single-use 和过期严格绑定；
- AI proposal → 人类 approve → execute，AI 自批/自激活拒绝；
- 跨用户、过期和重放确认拒绝；
- 后端持久 idempotency 在进程重启后仍成立，同 payload 重放、异 payload 冲突；
- stale base 返回冲突，并发激活只能成功一个；
- canonical audit 失败时 revision/activation 整单回滚；
- rollback 生成新版本，不修改旧版本；
- governed manifest、catalog 去重和 core dispatcher 调用；
- 不新增 raw MCP tool；
- SDK/API/MCP 输出契约一致。

必须运行相关门禁：

```bash
python scripts/check_mcp_manifest_schema.py
python scripts/check_mcp_no_raw_tools.py
python scripts/check_mcp_write_confirmation.py
python scripts/check_mcp_write_preview.py
python scripts/check_mcp_write_audit.py
python scripts/check_mcp_write_evidence.py
python scripts/check_mcp_tui_action_coverage.py
python scripts/check_current_data_contracts.py
python scripts/verify_architecture.py --include-audit --format text
```

若增加或修改 current/latest 决策面，同步更新 `governance/current_data_contracts.json`。若增加滚动情景定时任务，同步更新 `governance/celery_task_contracts.json` 并覆盖非法输入、成功、部分失败、全部失败、零产出和业务阻断。

### 12.4 TUI 与高风险最小回归包

至少覆盖：

- active 情景集和组合影响 P0 展示；
- 草稿表单、preview、确认、角色边界、回滚；
- 普通用户不泄露 endpoint 和裸 JSON；
- stale/blocked 状态可见且不会提供激活动作。

提交前运行与本次链路相关的固定最小回归包：

```bash
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/test_terminal_agent_service.py -q
pytest sdk/tests/test_sdk/test_client.py -q
pytest tests/unit/test_internal_ssl_redirect.py -q
```

生产 Python 变更还需运行增量 mypy、ruff、black/isort 检查，不得提高债务基线。

## 13. 发布、观察与回滚

### 13.1 发布顺序

1. 扩展建表和初始数据迁移，不切换读取；
2. 新旧引擎对同一组合/情景做 shadow 对账；
3. API/SDK/MCP/TUI 先发布只读和 preview；
4. 开启草稿创建；
5. 在管理员范围灰度激活/回滚；
6. 切换压力测试读取到 canonical scenario repository；
7. 连续一个稳定版本无旧写入后退役静态服务和兼容入口。

### 13.2 生产前置条件

- 已验证 PostgreSQL 迁移；
- 已完成数据库备份与恢复演练；
- shadow 对账无语义冲突；
- MCP 写能力门禁全绿；
- 至少完成一次创建—预览—确认—激活—回滚演练；
- TUI 普通用户和管理员 UAT 通过；
- 未授权情况下不触发 VPS 部署。

### 13.3 回滚

- 应用回滚：关闭 scenario write capability 和 TUI 写动作；
- 配置回滚：通过新 revision 激活上一份已验证内容，不篡改历史行；
- 读取回滚：迁移观察期内可切回兼容 Facade，但不得切回 Python 静态目录；
- 数据回滚：只使用已验证备份，禁止破坏性 reset。

## 14. 风险与防线

| 风险 | 防线 |
|---|---|
| AI 提交危险假设并直接生效 | 草稿/预览/确认/激活分离；高风险 RBAC |
| JSON 假设变成脚本执行面 | 有限 Schema、未知字段拒绝、禁止 eval |
| 最新事件自动加入导致噪声 | 动态结果只生成 candidate，人工批准后激活 |
| 历史回放使用未来数据 | PIT/as-of 数据端口、manifest 和时间穿越测试 |
| 配置并发覆盖 | 不可变 revision、expected version/hash、事务激活 |
| 新旧引擎结果漂移 | shadow 对账、差异分类、版本化解释 |
| 把规则分数伪装成概率 | 明确 score/probability 语义，展示组件和来源 |
| 为快速上线复制 MCP/API 逻辑 | Application UseCase 单一执行源，SDK/MCP 仅 transport |
| Quick Wins 扩散成大重构 | M5A/M5B/M5C 分阶段，长期能力进入备忘 |

## 15. Definition of Done

本计划只有同时满足以下条件才可标记完成：

1. 三个旧情景和旧 Allocation Matrix 已迁移并可通过 UI/API 查询，运行时不存在静态目录或配置矩阵 fallback。
2. 至少一种滚动情景、一种参数冲击和两个宏观情景集可维护并可复算。
3. AI MCP 能完成读取、校验、preview 和创建 revision proposal；人类 staff/operator 能在持久审批与确认后激活或回滚，AI 自批与直接激活均被拒绝。
4. 所有 MCP 写门禁、SDK/API 契约、TUI 角色与确认测试通过。
5. QW-1、QW-2、QW-3、QW-4 完成用户主任务验收；QW-5—QW-7 按各自数据门决定实施或保留为明确未完成项。
6. 所有决策型结果发布数据时间、来源、版本、freshness 和阻断状态。
7. shadow、PostgreSQL、备份恢复和回滚证据齐全。
8. 文档、TUI metadata、SDK/MCP 清单和治理投影同步更新。
9. 交接说明明确列出已完成项、未完成项、已验证测试和未验证风险。

## 16. 关联文档

- [人机协同决策分层设计](../business/human-judgment-decision-layering.md)
- [集中风控中心](../business/risk-center.md)
- [研究可信度与决策可复算体系整改计划](research-integrity-and-decision-reproducibility-2026-07-21.md)
- [MCP 技术与开发标准](../mcp/mcp-technical-and-development-standard.md)
- [MCP Agent 运行契约与工作流 Playbook](../mcp/mcp-agent-contract-and-playbook.md)
- [当前数据新鲜度契约门禁](../development/data-freshness-contract-guard.md)
- [策略研究能力后续开发备忘](../business/strategy-research-capability-roadmap-memo-2026-08-04.md)
