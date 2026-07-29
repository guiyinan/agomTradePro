# 研究可信度与决策可复算体系整改计划

## 一、目标与文档落点

计划文档写入：

`docs/plans/research-integrity-and-decision-reproducibility-2026-07-21.md`

并在 `docs/INDEX.md` 的进行中计划中登记。

采用“渐进式收敛”方案：

- 新增独立 `portfolio` 模块，统一目标组合、持仓快照、组合差额和订单草案。
- 新增独立 `research` 模块，负责实验登记、样本切分、参数试验和研究结果晋级。
- PIT、预测记分板、AI 评测和决策状态冻结分别收敛到现有 `data_center`、`signal + audit`、`prompt + agent_runtime`、`events + decision_rhythm`。
- 保留现有 API 和表的兼容入口，至少经过一个稳定版本后再删除旧写路径。

最终成功标准：

1. 任何可用于策略晋级的回测都能证明“每个日期只读取当时公开可见的数据版本”。
2. `strategy` 不再直接生成可执行订单，只输出目标组合。
3. 每个研究结论能还原数据版本、代码版本、参数组、样本切分和多重检验结果。
4. 每条可评分 signal 都有持续证伪记录和期后兑现结果。
5. Prompt 变更必须经过离线契约测试和受预算约束的在线评测才能激活。
6. 每次决策都能通过不可变快照和事件链复算出相同输入及结果。

## 二、目标架构与职责

| 问题 | Canonical owner | 现有能力处理 |
|---|---|---|
| PIT/vintage 数据 | `data_center` | 扩展现有事实表和查询服务；backtest 只能消费 PIT manifest |
| 组合构建 | 新增 `portfolio` | 接管 `decision_rhythm.PortfolioTransitionPlan`、`strategy.OrderIntent` 的 canonical 写入 |
| 实验登记 | 新增 `research` | backtest 成为执行引擎，不再自行代表研究结论 |
| 预测记分板 | `signal` 记账、`audit` 聚合 | 保留现有证伪任务，新增逐次检查记录和期后评分 |
| AI 回归防线 | `prompt` 评测、`agent_runtime` 执行留痕 | 扩展现有 PromptExecutionLog 和 ContextSnapshot |
| 状态一致性 | `events` 记录变更、`decision_rhythm` 冻结决策包 | 复用 StoredEvent/EventSnapshot，不实施一次性全面事件溯源 |

核心数据流固定为：

`PIT 数据清单 → 决策输入快照 → strategy 目标组合 → portfolio 差额/约束 → 审批 → simulated_trading 执行 → audit/forecast 复盘`

## 三、分阶段实施

### M0：架构冻结与现状盘点

- 建立六条问题的责任矩阵、现有表/API/任务清单和迁移映射，明确每个模型的最终 owner。
- 冻结新增写路径：整改期间不得继续向 `strategy`、`decision_rhythm`、`simulated_trading` 增加新的组合 diff 实现。
- 为既有回测增加可信度分类：
  - `legacy_unverified`：现有结果，不能用于策略晋级。
  - `exploratory`：允许非 PIT 探索，但页面和 API 必须显式标记“不可信用于投资决策”。
  - `pit_verified`：满足 PIT coverage 和研究门禁。
- 输出 ADR：
  - PIT 双时间语义。
  - 组合构建模块归属。
  - 实验晋级规则。
  - 决策快照与事件链关系。

验收：能够从任一 backtest、transition plan、signal 或 Agent 执行记录定位其当前数据来源和责任模块。

### M1：PIT/vintage 数据基础与回测硬门禁

#### 数据契约

在 `data_center` 建立统一双时间语义：

- `effective_at/effective_to`：数据描述的业务有效期。
- `available_at`：数据首次公开可知时间。
- `ingested_at`：本系统实际获取时间。
- `superseded_at`：该版本被下一修订取代的时间。
- `revision_number/source_record_id/content_hash`：版本和来源证据。
- `pit_quality`：`verified/estimated/unknown`。

适用范围：

- 宏观数据修订。
- 财报发布及追溯调整。
- 指数/行业成分变更。
- 上市、退市和证券状态变化。
- 价格及估值更正。
- 新增公司行动事实，用于按当时已知信息计算复权价格。

规则：

- 事实版本采用追加写入，不覆盖历史值。
- 不得用当前 `is_active` 构造历史股票池。
- 缺少真实发布日期的数据不得伪造为已验证；可依据治理配置估算，但只能标记 `estimated`。
- 回测默认使用公开可知时间；生产决策复盘可切换为系统实际摄取时间。
- PIT 查询必须同时接收 `as_of_time` 和 `knowledge_scope=public|system`。

#### PIT manifest

新增不可变 `PITDatasetManifest`，记录：

- 查询截止时间、knowledge scope 和交易日历版本。
- 所选事实版本的 ID/hash。
- 宏观、财报、成分股、证券状态、价格和公司行动覆盖率。
- 缺失、估算和未知数据明细。
- manifest 总体 hash。

回测结果新增：

- `data_manifest_id`
- `pit_coverage`
- `trust_status`
- `config_hash`
- `code_commit`
- `engine_version`

#### 回测切换

- 将 `use_pit_data=False` 从普通默认选项改为显式 exploratory 模式。
- `pit_verified` 回测必须通过 `PITDataView` Protocol 读取数据，禁止回测层自行推算固定发布滞后。
- 删除 backtest Domain 中硬编码的 `DEFAULT_PUBLICATION_LAGS` 业务真源；规则迁移到 data_center 治理配置。
- manifest 存在 `unknown`、未来版本泄漏、当前成分股反向套用或覆盖率不足时，回测可以产出诊断结果，但不得进入策略晋级。
- backtest → strategy 的晋级接口只接受 `pit_verified` 且关联已通过的 research trial。

### M2：决策状态冻结与独立组合构建层

#### 决策状态包

在 `decision_rhythm` 新增不可变 `DecisionInputSnapshot`：

- `snapshot_id/schema_version/as_of_time/state_hash`
- `pit_manifest_id`
- Regime、Policy、Risk、Beta Gate、Decision Rhythm 的状态版本和事件 ID
- 当前账户/持仓快照 ID
- 配置版本、策略版本和 Prompt 版本
- freshness、quality、must-not-use 和缺失组件
- 创建原因、correlation ID 和调用方

扩展 `events.StoredEvent` 的索引字段：

- `aggregate_type`
- `aggregate_id`
- `aggregate_version`
- `effective_at`
- `schema_version`

并建立 `(aggregate_type, aggregate_id, aggregate_version)` 唯一约束。各状态模块仍拥有自己的表，但所有有效状态变更都必须追加领域事件。

下游规则：

- strategy、portfolio、agent_runtime 和可信 backtest 只接受 `snapshot_id`，不再分别读取“当前” Regime/Risk/Gate 状态。
- snapshot hash 不一致、组件时间晚于 `as_of_time`、状态版本缺失或 `must_not_use=True` 时 fail closed。
- `AgentContextSnapshot` 改为展示/任务上下文，必须引用 canonical `DecisionInputSnapshot`，不得成为另一套决策真源。

#### 新增 `portfolio` App

按四层架构建立：

- Domain：`TargetPortfolio`、`PortfolioSnapshot`、`TransitionPlan`、`OrderDraft`、`ConstraintDecision`。
- Application：构建目标组合、计算差额、应用交易约束、生成审批包。
- Infrastructure：读取现有账户/模拟盘持仓、市场状态和持久化计划。
- Interface：计划预览、详情、审批和执行交接 API。

职责边界：

- `strategy` 只输出目标权重、目标现金和策略解释。
- `portfolio` 完成目标组合与当前持仓的 diff，并生成订单草案。
- `risk_center` 返回组合级与订单级约束结论。
- `simulated_trading` 只执行已批准且未过期的不可变计划。
- `account` 继续负责身份；现有实际持仓在迁移期通过 Protocol 读取。

交易约束必须覆盖：

- A 股 T+1 可卖数量。
- 停牌、涨跌停和证券交易状态。
- 100 股买入单位及零股卖出规则。
- 现金、费用、滑点和卖出后买入顺序。
- 单资产及组合权重上限。
- 成交额参与率和流动性上限。
- 最小调仓阈值、部分可执行、剩余订单及过期处理。

以上规则由数据库配置和 data_center 市场事实驱动，不在 Domain 中硬编码资产清单或阈值。

#### 兼容迁移

- 将 `PortfolioTransitionPlanModel` 的 canonical owner 迁入 `portfolio`，保留原 `db_table`，使用 Django state/database 分离迁移避免搬表。
- 将 `OrderIntentModel` 迁为 portfolio 订单草案/执行意图；strategy 暂时保留兼容 re-export。
- `simulated_trading.RebalanceProposal` 变为执行投影，停止作为独立规划真源。
- 旧入口先转发至 portfolio facade，并记录 deprecated 调用；连续一个版本无旧写入后再删除。

### M3：Experiment Registry 与研究晋级门禁

新增 `research` App，核心模型：

- `ResearchExperiment`：研究问题、假设、负责人、状态。
- `ExperimentTrial`：单组参数、随机种子、代码版本、运行环境 hash。
- `DatasetSplitSpec`：训练、验证、样本外及 walk-forward 窗口。
- `MetricObservation`：原始指标、样本数和置信区间。
- `MultipleTestFamily`：同一研究问题下全部试验集合。
- `PromotionDecision`：通过、拒绝及证据。

每个 trial 必须冻结：

- PIT manifest。
- Git commit、依赖锁摘要和引擎版本。
- 完整参数及参数 hash。
- 随机种子。
- 样本内/外划分和 embargo。
- 基准、费用、滑点和股票池规则。
- 父 experiment 和 multiple-test family。

纪律门禁：

- trial 启动后不可修改参数、数据清单或切分规则。
- 未声明样本外窗口、未执行 walk-forward 或未登记全部参数试验时，状态不能进入 `eligible_for_promotion`。
- 同一 family 默认计算 Benjamini–Hochberg FDR 5% 校正，并同时报告原始 p-value、q-value和 Deflated Sharpe。
- 不允许只登记“最佳参数”；family 的计划试验数、实际试验数、失败和中止试验全部保留。
- strategy 参数版本只能引用已批准的 `PromotionDecision`。
- exploratory/legacy backtest 不能生成 PromotionDecision。

### M4：Forecast Ledger 与预测记分板

在 `signal` 中新增：

- `ForecastLedgerEntry`：信号发布时冻结预测内容。
- `ForecastEvaluation`：每次定时检查的追加记录。
- `ForecastOutcome`：到期、证伪、退出或数据不足时的最终结果。

可评分 signal 必须包含：

- 发布时间、方向、资产、预测期限。
- 基准资产。
- 概率或置信度。
- 证伪规则版本。
- 决策快照及 PIT manifest。
- 来源策略、模型和 Prompt 版本。

每日证伪任务必须记录所有检查，而不只记录触发结果：

- 检查时间和使用的数据版本。
- 每个条件的实际值、阈值和布尔结果。
- 是否触发、首次触发时间和状态转换。
- 数据缺失或陈旧原因。

`audit` 提供记分板：

- LONG/SHORT 以期末相对基准收益方向判断命中。
- NEUTRAL 使用可配置中性带判断。
- 报告命中率、平均超额收益、Brier Score、证伪率、证伪耗时和有效覆盖率。
- 按 signal 来源、策略版本、Regime、模型和 Prompt 版本分组。
- 样本量不足时显示数量，不输出误导性排名。
- 旧 signal 标记 `legacy_unscored`，不得用缺失字段推造历史预测。

### M5：Prompt/Agent AI 评测门禁

在 `prompt` 中增加不可变版本和评测体系：

- `PromptVersion`
- `PromptEvalDataset`
- `PromptEvalCase`
- `PromptEvalRun`
- `PromptEvalAssertion`
- `PromptPromotionDecision`

状态流固定为：

`draft → candidate → evaluated → active → retired`

评测分层：

- PR 必跑离线测试：模板渲染、必需变量、工具调用契约、JSON Schema、解析器、脱敏和固定响应回归。
- Candidate 必跑在线评测：固定 provider/model、temperature=0、明确数据集版本和最大预算。
- 定时回归：对 active 版本和候选版本做同集对照，检测质量、结构成功率、延迟、token 和费用漂移。

激活门禁：

- 所有结构化输出先通过 schema 校验，再进入 Application 用例。
- 存在必需字段缺失、越权工具调用、成本超限或关键用例退化时禁止激活。
- 成本、token、用例数和超时上限由 `config_center` 管理。
- 每次 agent 执行记录 PromptVersion、模型、schema、eval baseline、DecisionInputSnapshot 和实际成本。
- 不允许直接修改 active Prompt；修改必须产生新版本。

### M6：切换、清理与生产验收

按 feature flag 分步启用：

- `research.pit_required_for_promotion`
- `portfolio.canonical_planner_enabled`
- `decision.snapshot_required`
- `prompt.eval_gate_enabled`
- `signal.forecast_ledger_enabled`

切换顺序：

1. 只记录新元数据，不改变旧结果。
2. 新旧链路影子对比。
3. 新链路成为默认，旧链路只读。
4. 生产连续窗口通过后停止旧写入。
5. 下一稳定版本删除兼容代码和无调用 API。

所有迁移保持 additive、可逆；历史数据无法可靠回填时标为 unknown/legacy，不伪造证据。生产 PostgreSQL 和本地 SQLite 都必须通过迁移验证。

## 四、公共接口变化

新增或收敛的 canonical 接口：

- `data_center.PITDataView.query(dataset, as_of_time, knowledge_scope, filters)`
- `data_center.BuildPITManifestUseCase`
- `decision_rhythm.BuildDecisionInputSnapshotUseCase`
- `strategy.BuildTargetPortfolioUseCase`
- `portfolio.BuildTransitionPlanUseCase`
- `portfolio.ValidateTransitionPlanUseCase`
- `portfolio.SubmitApprovedPlanUseCase`
- `research.RegisterExperiment/RunTrial/EvaluatePromotion`
- `signal.RecordForecastEvaluationUseCase`
- `audit.GetForecastScoreboardUseCase`
- `prompt.RunPromptEvaluation/PromotePromptVersion`

HTTP API 放入各 App 的 `interface/api_urls.py`：

- `/api/data-center/pit-manifests/`
- `/api/decision-rhythm/input-snapshots/`
- `/api/portfolio/transition-plans/`
- `/api/research/experiments/` 与 `/trials/`
- `/api/signal/forecast-ledger/`、`/evaluations/` 与 `/outcome/`
- `/api/audit/forecast-scoreboard/`
- `/api/prompts/evaluations/` 与 `/versions/{id}/activate/`

v1 不新增 MCP 写能力；先稳定 canonical API、权限、幂等和审计契约。

## 五、测试与验收

### PIT

- 某指标初值、修订值和二次修订在不同 as-of 时间返回正确版本。
- 人为注入未来大幅修订后，早期回测结果完全不变。
- 退市股票在历史股票池中存在、在退市后消失。
- 指数调入调出日期和公开时间分别生效。
- 财报追溯调整不会污染调整公布前的因子。
- forward-adjusted 价格不得使用未来公司行动。
- PIT coverage 不足时晋级门禁失败。

### Portfolio

- 目标权重到订单数量的舍入、现金和费用守恒。
- T+1、停牌、涨跌停、最小单位和可卖数量约束。
- 流动性上限导致部分订单和剩余计划。
- 重复请求通过 idempotency key 返回同一计划。
- 计划引用的决策快照变化后禁止直接执行。
- backtest 与 simulated trading 使用同一套组合构建 Domain 规则。

### Research/forecast

- Trial 启动后参数和数据 manifest 不可修改。
- 未登记失败 trial 或未提供样本外窗口时不能晋级。
- 多重检验 family 计算结果可重复。
- 每条 signal 每日检查幂等且保留完整轨迹。
- 到期、提前证伪、数据缺失和基准缺失均有确定状态。
- 记分板分母必须排除未到期和不可评分记录，并显示 coverage。

### AI/state

- Prompt 版本变更触发离线基线差异。
- 非法 JSON、字段缺失和工具越权被阻断。
- 在线评测达到成本上限后停止且不能激活。
- 相同 DecisionInputSnapshot 重放得到相同 hash 和组合计划。
- 状态事件缺失、乱序或版本冲突时 snapshot 构建失败。
- API 契约测试覆盖 Content-Type、状态码、权限、幂等和错误结构。

### 回归包

除新增 Domain、Application、迁移和 API 测试外，至少运行：

- backtest、data_center、signal、strategy、decision_rhythm、events、prompt、agent_runtime、simulated_trading、risk_center 的单元和集成测试。
- `pytest tests/unit/test_terminal_agent_service.py -q`
- `pytest tests/unit/test_tui_workbench.py -q`
- 架构护栏、ruff、mypy 定向检查。
- PostgreSQL migration smoke test 和 SQLite 全新建库测试。

## 六、交付与提交拆分

独立主线和 commit 组：

1. `docs/ADR + M0 inventory`
2. `data_center PIT schema/query + backtest gate`
3. `events + decision snapshot`
4. `portfolio module + compatibility migration`
5. `research registry + promotion gate`
6. `signal forecast ledger + audit scoreboard`
7. `prompt eval suite + agent runtime linkage`
8. `cutover flags + legacy retirement + final docs`

每个阶段均更新本计划的完成状态、已验证测试、未验证风险和回滚点；不得将 PIT、portfolio、AI 和部署修改混入一个提交。

## 七、默认假设

- 所有实施计划统一放在 `docs/plans/`，不再保留单数形式的计划目录。
- 正式生产数据库继续使用 PostgreSQL，本地开发保留 SQLite。
- 采用渐进式收敛，不在本阶段将所有业务状态一次性改造成完整事件溯源。
- PIT 是第一优先级；在 PIT 晋级门禁完成前，现有 Sharpe 等指标只保留展示，不再作为策略激活依据。
- 无法证明历史发布时间的数据宁可标记 unknown，也不通过固定滞后推造 verified vintage。
- 兼容入口至少保留一个稳定版本，确认无旧写入后再删除。

## 八、实施状态（2026-07-22）

开发分支：`dev/feat-research-integrity-reproducibility`。

| 阶段 | 状态 | 本阶段交付 |
|---|---|---|
| M0 | 已完成 | 责任/迁移盘点及 ADR 0002-0005 已落库，canonical owner 和回滚边界已冻结。 |
| M1 | 代码完成，待数据源推广 | 已实现追加式双时间事实、不可变 PIT manifest、manifest-bound 查询、回测可信度元数据和 `pit_verified` 硬门禁。真实宏观/财报/成分股/公司行动的 provider 回填仍按数据源逐项推进，缺失项保持 `unknown`。 |
| M2 | 代码完成，待影子窗口 | 已实现不可变决策输入快照、事件聚合索引、独立 `portfolio` 四层模块、state-only owner 迁移、数据库版本化规划策略、确定性差额/交易约束/审批/执行交接及 strategy 兼容只读入口。客户端不能自行覆盖规划阈值。 |
| M3 | 已完成 | 已实现实验、trial、切分、指标、multiple-test family、FDR、Deflated Sharpe 和不可变 PromotionDecision；strategy 参数激活可由开关强制验证批准证据。 |
| M4 | 代码完成，待 PIT 数据版本接线 | 已实现 Forecast Ledger、逐次检查、期后结果、分组记分板及 HTTP API。每日证伪链路会追加全部检查；旧宏观读取无法提供 PIT 版本时明确记录 `legacy_invalidation_source_has_no_pit_version_ids`，不伪造版本证据。 |
| M5 | 门禁与证据模型完成，待生产 runner | 已实现 Prompt 不可变版本、离线/在线评测证据、预算停止、完整数据集覆盖、激活门禁和 Agent 执行版本/成本/决策快照关联。实际 provider 调用、定时同集回归由生产 evaluation runner 接入 canonical API。 |
| M6 | 本地切换基础完成 | 五个 feature flag 均已落地且默认关闭；SQLite 全新迁移、架构/模块环检查和本地回归已通过。PostgreSQL migration smoke、生产影子对比及连续稳定窗口必须在部署环境执行。 |

### 已验证

- 新增 PIT、决策快照、portfolio、research、forecast、prompt、backtest 与 API 契约用例通过。
- 架构边界测试通过；App 依赖图为 41 个模块、193 条边、0 双向依赖、0 环。
- `manage.py check`、`makemigrations --check --dry-run` 与 SQLite 全新建库迁移通过。
- Terminal/TUI 固定回归包通过；Agent Runtime/MCP 回归通过。
- 本次新增/修改 Python 文件的 Ruff 检查通过；核心新增 Domain/Application 的定向 mypy 检查通过。

### 未验证风险与回滚点

- 当前开发环境没有可用 PostgreSQL 实例，因此未执行 PostgreSQL migration smoke；上线前不得跳过。
- feature flag 尚未在生产开启，也未完成新旧结果的连续影子窗口；任何异常先关闭对应 flag，保留追加式证据表，不删除或回写历史记录。
- 旧数据源没有可靠发布时间或 PIT 版本映射时继续标记 `unknown`/缺失；不得为提升 coverage 人工填造 verified 时间。
- Prompt 在线评测需要受控生产 runner 和配置中心预算策略；在 runner 验收前保持 `PROMPT_EVAL_GATE_ENABLED=False`。
