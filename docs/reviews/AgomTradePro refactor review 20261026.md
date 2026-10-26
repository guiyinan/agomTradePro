# AgomTradePro 数据层与模块边界重构意见（评审稿）

Oct 26, 2026 · @uncleliou

## 1. 背景与评审方式

建议：暂停新增治理结构，先收敛 account 与 research 的版本表和复制结构，再统一业务名词真源，并尽早用回测验证 Regime 过滤的增量价值。

**依据范围。** 本意见只基于 `docs/architecture/project_structure.md`（2026-07-10 版）和自动生成的 `DATA_DICTIONARY.md`（42 个 app、596 个模型、9287 个字段）。没有读代码、AGENTS.md、迁移历史和 module\_map。凡与代码事实冲突，以代码为准，并请在回复中指出。

**产品目标锚点。** 当前目标是“A 股研究 + 模拟调仓 + 手工辅助下单”，系统不自动下单。所有改动以服务这一目标为准；不服务该目标的能力，默认冻结，而不是继续加固。

**评审要求。** 评审阶段不改代码，不为反驳而新增结构。请按第 7 节的格式逐条回复：结论、理由、证据（文件路径、表名、测试名）。

## 2. 现状诊断

核心判断：治理结构的体量已经超过投研主业，且大量是版本并存和结构复制，而不是必要复杂度。下表的计数均来自数据字典；字段计数为“含该字段的模型数”。

| 编号 | 问题 | 证据 | 影响 |
| --- | --- | --- | --- |
| D1 | 治理与业务体量倒挂 | account 71 模型 / 1494 字段，research 96 / 1753，data\_center 79 / 985；而 macro 3、regime 10、signal 14、backtest 2 | 维护成本集中在非核心模块；核心立论的验证层最薄 |
| D2 | 版本表并存未退役 | 30 个 `V\d+Model`，11 个模型族多版本并存。AccountOwnerAssignment Evidence/Subject/ProvenanceReceipt 有 V1–V5；OwnerTenantAuthority 有 V1–V3；PhysicalAccountRowObservation、SimulatedAccountRowSource、CanonicalAccountCreationBinding 各有 V1–V2 | 读路径以哪版为准不明确；迁移债持续累积 |
| D3 | 单 owner 系统内置多租户与 RBAC | OwnerTenantAuthority\*、AccountRbacAuthority\*（MutationBindingV3 单表 85 字段）、PortfolioObserverGrantModel，以及 SingleOwnerAuthorityPolicyV1Model | 结构针对的威胁（多租户越权）在当前场景不存在 |
| D4 | 安全标记做成逐表的列 | `must_not_use_for_decision` 95 个模型，`must_not_execute` 91，`research_only` 91，`must_not_publish_current` 46 | fail-open：任何新读路径漏查一个 flag，保护即失效 |
| D5 | 完整性字段泛化 | `content_hash` 151，`canonical_payload` 138，`ledger_header_hash` 73，`record_seal` 24，`ledger_seal` 22 | canonical\_payload 与结构化列构成双真源；封印成本高、收益低 |
| D6 | R1–R8 结构复制 | research 中每个 R 各有 Promotion / Lifecycle / Monitoring / AppendOnly / AuditSnapshot / Authorization 一套表；portfolio 中 R4/R5/R8 receipt 同构 | 同一逻辑维护 7 份，修复需逐份同步 |
| D7 | 业务名词多真源 | 持仓 3 处、汇率 2 处、资产主数据 3 处、宏观 3 处、行情 3 处、估值 3 处、筛选 3 处（明细见 WP5） | 数据不一致、对账困难、职责边界模糊 |
| D8 | 结构文档严重漂移 | 文档称“8 个 ORM 模型文件”；目录树缺 data\_center、research、portfolio、broker\_execution、risk\_center、config\_center；`docs/` 与 `doc/` 说法矛盾；AI 服务商停留在 gpt-3.5；标注“生产就绪” | 人与 agent 都会被过时文档误导 |
| D9 | 具体隐患 | ai\_provider 仍有明文 `api_key` 列（标 deprecated）；account 依赖 statement-level trigger，而开发库 SQLite 只支持行级触发器；broker\_execution 含 LiveOrder、BrokerAgent、OrderLease，data\_center 含 QMT bridge | 密钥泄露面；开发与生产行为不一致；手工下单阶段存在闲置的实盘攻击面 |

## 3. 重构原则

每个改动都按以下八条判断；与原则冲突的方案，需在评审中单独说明理由。

1. **威胁模型先行。** 每张治理表必须写明它防的具体风险。单 owner 场景下的有效威胁是：本人误操作、前视偏差与数据泄漏、数据源错误、AI 产出被当作事实、误下单。多租户越权、内部篡改不在清单内，不设专门结构。
2. **结构隔离优于标记检查。** 让非法状态无法表示。研究产物在类型和读路径上就进不了决策侧，而不是靠每个调用方检查 flag。
3. **一个业务名词只有一个 owner。** 只有 owner 模块能写；其他模块通过 Protocol 只读。
4. **同一时刻只有一个现行版本。** 新版上线即启动旧版退役倒计时，默认不超过两个迭代。
5. **可复现优先于防篡改。** append-only、as\_of 版本、content\_hash 足以支撑复现；封印只用于外部证据入口。
6. **删除也是交付。** 每个工作包的验收都包含净减少的模型数与字段数。
7. **不改变外部行为。** 重构期间 API 契约、MCP 工具和现有测试结果保持不变，明示删除的除外。
8. **先补护栏再动刀。** 每个工作包先补特征测试（characterization tests），锁定现有行为后再改。

## 4. 工作包

共八个工作包。文中的数量目标是供评审的建议值，请按代码实际给出你的估计。

### WP0 冻结与基线

目标：先止住增长，再开始收敛。

- 在 governance 中加 CI 规则：新增 `*Model` 的 PR 必须关联工作包编号或第 3 节的威胁条目，否则失败。
- 新增 `V\d+Model` 时，必须同时声明被替代的旧表和退役期限。
- 以当前 `data_dictionary.json` 生成基线（模型数、字段数、Vn 数、flag 列数），写入 `governance_baseline.json`；之后每个工作包报告差值。

验收：CI 规则生效，基线数字入库。

### WP1 账户域收敛（account）

目标：account 只保留身份、令牌和偏好。

- 为每个 Vn 族确认现行版本，列出全部读写调用点。旧版本先导出为只读归档快照（附 hash），再迁移数据、删表。
- 用一条单 owner 不变式替代多租户与 RBAC：系统只有一个 owner，所有写操作的身份是 owner 本人或其签发的 token。`UserAccessTokenModel` 的只读 / 读写两级保留。
- OwnerTenantAuthority\*、AccountRbacAuthority\*、OwnerAssignment\* 合并为最多三张表：owner 配置、token、审计事件。PortfolioObserverGrant 若有真实的只读分享需求则保留，否则并入 share。
- Portfolio、Position、Transaction、CapitalFlow、StopLoss、TakeProfit、TradingCost 等迁出 account，owner 按 WP5 确定。

验收：account 不超过 15 个模型；没有并存的 Vn；现有测试全绿。

### WP2 决策可用性隔离

目标：用结构隔离替代逐表 flag。

- 定义唯一的“决策可用”入口。决策侧模块（signal、decision\_rhythm、beta\_gate、strategy、simulated\_trading、broker\_execution）只能通过 publication pointer 对应的读模型或 Protocol 获取研究产物。
- 研究产物默认对决策侧不可见。晋级等于写入 publication，而不是翻转行内 flag。
- 加 import-linter 或 `rg` 规则：决策侧模块禁止 import research 的 infrastructure 层和研究产物表。
- 过渡期由统一的查询基类强制过滤，未声明即不可用（fail-closed）。迁移完成后删除 `must_not_use_for_decision`、`research_only`、`must_not_execute`、`must_not_publish_current` 列。

验收：架构测试证明决策侧读不到未发布的研究产物；flag 列只存在于 publication 层，或降为 0。

### WP3 完整性字段收敛

目标：消除双真源，封印只留在需要的地方。

- 每个模型明确真源：结构化列或 `canonical_payload`，二选一。保留的 payload 标注为 archive-only，读路径禁止解析。
- `content_hash` 保留，用于去重、幂等和复现。
- `ledger_header_hash`、`record_seal`、`ledger_seal` 只保留在外部证据入口：券商成交导入、外部数据原始载荷（RawPayload）、AI 产出入库。其余移除。

验收：保留封印的表清单不超过 10 张；`rg` 校验读路径不再解析 `canonical_payload`。

### WP4 研究生命周期引擎

目标：R1–R8 共用一套生命周期，只保留真正的领域差异。

- 抽象通用对象：LifecyclePolicy、Subject、Event（append-only）、Decision/Receipt、MonitoringObservation、MonitoringAssessment、AuditSnapshot。
- R 编号作为 `capability_code` 字段。R 专属内容放 payload，由 Domain 层为每个 R 定义 schema 并校验。
- 真正领域特有的表保留，例如 R7 的 HistoricalAnalogy 与 ScenarioPath、R6 的 Qualification。
- portfolio 中的 R4/R5/R8 receipt 一并并入。
- 先以 R4、R5 两个最同构的能力试点，验证等价后再推 R1、R2、R6、R7。

验收：research 不超过 35 个模型；同一套状态机测试覆盖全部 R。

### WP5 业务名词单一真源

目标：每个业务名词只有一个写入方。下表为建议，请用 module\_map 核对。

| 名词 | 现有位置 | 建议 owner | 说明 |
| --- | --- | --- | --- |
| 持仓 | account.PositionModel、simulated\_trading.PositionModel、broker\_execution.BrokerPositionSnapshotModel | 模拟持仓归 simulated\_trading；手工导入的实盘持仓归 portfolio | broker 快照只作对账输入 |
| 汇率 | account.ExchangeRateModel、macro.ExchangeRateModel | data\_center | 两处合并 |
| 资产主数据 | data\_center.AssetMasterModel / AssetAliasModel、account.AssetMetadataModel / AssetCategoryModel、equity.StockInfoModel | data\_center | 其他位置改为引用 |
| 宏观数据 | macro.MacroIndicator、data\_center.MacroFactModel、macro\_factor | data\_center 存事实 | macro 只做采集适配；macro\_factor 只存派生因子 |
| 行情 | realtime、data\_center.QuoteSnapshotModel / PriceBarModel、equity.StockDailyModel | data\_center | realtime 只做轮询与缓存，不落库 |
| 估值 | equity.ValuationModel、data\_center.ValuationFactModel、valuation | valuation 负责计算 | data\_center 存估值事实 |
| 筛选 | filter、asset\_analysis、equity.StockScreeningRuleConfigModel | asset\_analysis | 或合并为一个模块 |

- 在 module\_map 中写入“名词 → owner”映射，CI 校验每个名词只有一个写入方。

验收：跨模块直接写他人表的调用为 0。

### WP6 隐患修复

目标：小改动，可与其他工作包并行。

- 确认 `api_key_encrypted` 全量迁移后，删除 ai\_provider 的明文 `api_key` 列。
- 测试切到 PostgreSQL（testcontainers 或 docker compose），至少覆盖依赖触发器的账户与账本测试。
- 实盘链路：确认 `TradingControl` 默认 fail-closed（无配置即禁止）。LiveOrder、BrokerAgent、OrderLease 与 QMT bridge 放入可选 app 或 feature flag，默认不加载；保留手工成交导入。

验收：上述三项各有对应测试。

### WP7 文档与核心验证

目标：文档不再漂移；核心立论有证据。

- `project_structure.md` 改为“稳定原则 + 指向生成物”（module\_map、data\_dictionary、governance\_baseline）。目录树由脚本生成，或直接删除。
- 建立 Regime 过滤的 walk-forward 验证。宏观数据按 `published_at` 与修订版本做 PIT；市场为 A 股；基准为买入持有（沪深 300 或中证 800）和简单动量 / 均线择时。
- 报告样本外超额、最大回撤和换手，并纳入 research experiment 与 MultipleTestFamily。

验收：一份可复现的验证报告。其结论决定 regime 与 policy 模块后续的投入。

## 5. 推进顺序与关口

分五个阶段推进，每个阶段过关口后才进入下一阶段。WP7 中的回测验证不依赖重构，建议在阶段 1 就并行启动，因为它的结论可能改变后续优先级。

| 阶段 | 工作包 | 退出关口 |
| --- | --- | --- |
| 0 止血 | WP0、WP6 | 基线入库；CI 冻结规则生效；PostgreSQL 测试跑通；实盘链路默认关闭 |
| 1 账户收敛 | WP1；WP5 盘点；WP7 回测验证启动 | account 无并存 Vn；名词 → owner 映射评审通过 |
| 2 边界隔离 | WP2、WP3 | 架构测试证明隔离成立；flag 列可删；读路径不解析 payload |
| 3 研究引擎 | WP4（R4/R5 试点 → 全量）、WP5 落地 | 试点等价性测试通过后再推全量；跨模块写他人表为 0 |
| 4 收尾 | WP7 文档部分；回测报告定稿 | 文档改为生成；验证报告可复现，并据此调整 regime / policy 投入 |

执行约束：每个 PR 只动一个模型族或一个名词，可独立回滚；每个 PR 附 data\_dictionary 基线差值。

## 6. 不做什么与风险控制

**范围之外。** 本次重构不换技术栈，不做性能优化，不新增功能。不删除外部证据入口的审计（券商成交、外部原始载荷、AI 产出入库）。不改 Domain 层的金融逻辑（Regime 判定、HP 与 Kalman 滤波），测试需要的除外。

| 风险 | 控制措施 |
| --- | --- |
| 删除历史 ledger 后丢失可追溯性 | 删表前导出只读归档快照并记录 hash；归档清单入库 |
| 迁移破坏 API 或 MCP 契约 | 先补契约测试；契约变更需单独 PR 并在评审中说明 |
| agent 一次性大规模重构，难以回滚 | 每个 PR 只动一个模型族或一个名词；超过约定规模的 PR 直接拆分 |
| “删除”被理解为降低治理水平 | 每项删除写明对应威胁现由什么机制覆盖；无法说明的不删 |
| 收敛过程中又长出新的 Vn 表 | WP0 的 CI 规则先于其他工作包生效 |

## 7. 评审问题与回复格式

请逐条回答以下十个问题，并对每个工作包给出结论。

1. D1–D9 中哪些与代码事实不符？请给出证据。
2. account 的每个 Vn 族，现行版本是哪个？旧版本是否仍有读写调用？阻止删除的具体原因是什么？
3. 多租户与 RBAC 结构当初为哪种场景引入？目前是否存在第二个真实用户，或真实的只读分享需求？
4. `must_not_*` 与 `research_only` 这些 flag 目前由谁读取？是否存在决策侧未检查 flag 的读路径？
5. `canonical_payload` 与结构化列冲突时以谁为准？现有代码是否有解析 payload 的读路径？
6. R1–R8 的结构差异中，哪些是真正的领域差异，哪些是复制？以 R4、R5 作试点是否合适？
7. 是否同意 WP5 的名词 → owner 表？不同意的请给出替代方案。
8. statement-level trigger 在 SQLite 下目前如何测试？
9. 实盘下单链路当前的默认状态是什么？是否能确认 fail-closed？
10. 各工作包的规模估计（PR 数）与你认为的最大风险。

**回复格式。** 每条问题与每个工作包各一行：

| 编号 | 结论（同意 / 部分同意 / 不同意） | 理由 | 证据（路径 / 表 / 测试） | 建议修改 |
| --- | --- | --- | --- | --- |
|  |  |  |  |  |

最后用一段话说明：如果由你来排期，你会如何调整第 5 节的阶段顺序。
