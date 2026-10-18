# 普通模拟成交与结算事务端口

本端口说明普通模拟成交账本与结算 UoW。当前既有手动交易 API 的 BUY/SELL 已接入当前身份用途的普通模拟应用，接口范围见[当前身份手动模拟交易合同](a-share-simulated-current-reference-manual.md)。该代码接线不等于生产来源、盘中可交易状态或历史 PIT 已获证明，也不代表 ASH-03 完成。其他 `ExecuteBuyOrderUseCase`/`ExecuteSellOrderUseCase` 调用方、自动模拟、真实成交导入与 QMT 不随该入口切换。

当前手动 HTTP 入口的 request、幂等、状态码与授权边界见[专用合同](a-share-simulated-current-reference-manual.md)；本页继续说明共享账本和结算回执。

## 装配和责任

`apps.simulated_trading.execution_settlement_composition` 保留显式 settlement/release 工厂；两者仍要求调用方注入 alias、带时区 clock、正式日历 reader，成交还注入 Risk V3 rule reader 与 identity reader。普通手动 API 另由 `build_current_reference_manual_trade_use_case()` 组装同一账户账本 UoW 和当前用途 identity reader。reader 在请求时要求精确 active Config profile/snapshot、显式 selector、snapshot/mapping 原件及同一截止点；构造 factory 不补默认、不发网络请求。当前用途和证据边界见[专用 API 合同](a-share-simulated-current-reference-manual.md)。

该事务只更新普通模拟账户。手动 API 校验账户归属、正整数股数、显式 `equity` 类型和用户给定 Decimal 价格，并由当前用途 identity、Risk V3、费用与 settlement UoW 决定能否记账；它不获取行情报价，也不证明盘中停牌、涨跌停、可成交性或券商接受。真实成交导入保留券商事实与实收费用，不走模拟预估扣款。

## 成交输入与重放

`SimulatedTradeIntent` 绑定用户、账户、证券身份、精确资产代码、资产类型、市场、板块、方向、数量、价格和账户内幂等键。Decimal 数值等价的输入，例如 `100` 与 `100.000000`，使用相同规范化请求摘要；不同业务输入重用同键返回冲突。

`intent.market/board` 是 Risk 与 Fee 的规则分类，不是日历交易所。旧 V1 identity 仍要求严格的来源时钟与可用性，未知时间或禁止标记继续阻断 V1。当前手动普通模拟入口使用独立的 `ExecutionInstrumentIdentityEvidenceV2`：V2 将原 V1 证据、normal-simulated 选择元数据和所选证券的原响应 occurrence 绑定；按明确 `security_id`、`asset_code` 与截止点返回，并保留内部 ID、供应商代码、来源交易所/市场、规则 market/board、精确 snapshot/mapping 身份及原始时钟。不能猜代码后缀、推断映射或选择无 pin 的 latest。日历只按证据 `source_exchange` 读取。

V1 的严格验证规则保持原样。V2 只在 `normal_simulated_current_reference` 用途下，以 active profile activation、精确 snapshot/mapping recorded 时刻及该证券实际 occurrence 的 `response_completed_at + max_local_reference_age_seconds` 形成半开本地窗口。来源 `source_observed_at`/`source_available_at` 可继续为 None，`must_not_use_for_decision`/`must_not_execute` 可继续为 True；这些值逐字保留，不用查询时钟填补，也不把 local selection 升格为上游 PIT、provider tradability 或 broker authority。仅已配置的手动普通模拟账本路径消费此 V2。

Application 在锁外读取 V3 bundle、费用快照与完整日历证据。Repository 在单个同 alias 事务中依次锁定账户、目标持仓及按主键排序的未结算买入成交，然后重新读取时钟，校验时钟未倒退、证据仍有效、日期及覆盖仍一致。账户锁串行化同账户成交；重放只返回已持久化、内容完整且摘要匹配的结果，不重复变更账本。

使用 V1 identity 的原 settlement 调用保持 PlanV2/binding version 2；当前手动 V2 identity 路径使用 `SettlementExecutionPlanV3`，写入 `settlement_plan_binding_version=3` 与 `simulated-settlement-plan-binding.v3`。V3 外层包含 `schema/common_binding/identity_evidence`，`common_binding` 复用严格 V1 摘要，不复制原日历目录，并绑定 V2 当前用途身份与来源 exchange。V1 历史 wire/hash 不变；回执按版本严格解码、重算摘要并对照原行。未知版本、畸形 payload、摘要或原列差异均阻断，不以今日 current 重建历史原计划。

其他调用方和历史行仍保留原绑定版本；数据库默认版本 0 不表示经过当前 UoW。版本 1 是完整旧绑定且 exchange 空，版本 2 是完整绑定且 exchange 非空，版本 3 是完整 V3 binding 与 exchange 非空；版本 0 无绑定。Infrastructure 按 1/2/3 精确回读并保留旧分支；当前 manual Application 不在 identity 缺失时回退到旧买/卖用例。精确重放只读原回执和 owner-scoped trade，不重查新 identity selector 来改写原成交。

新增买入增加总持仓；可卖量仅按显式结算 lag 释放。卖出消耗已可卖股份，不消耗待结算批次。现金、费用分项、持仓、账户汇总和成交记录一起提交，任一写入失败整笔回滚。账户市值按本次目标持仓重估差额调整，保留其他资产部分；这不修复历史失真的账户汇总。部分卖出从持仓实际存储总成本按比例分摊，最后清仓带走剩余成本，避免从已舍入均价重建成本。

卖出费用高于成交毛额时，可由账户现金支付差额；资金不足则阻断并回滚，不允许透支。此行为属于正常模拟估算，不声称券商实收一致。

## 结算释放

每笔新买入在现有成交行中保存原 V3 bundle、结算 policy、原 lag、交易会话和当时正式日历引用。后续释放依据当前完整已发布日历，从原买入会话重新数开市会话，并使用该批次的原 lag。日历修订导致原预计释放日不再满足会话数时，应延后释放；不得仅比较旧预测日期，也不得改用新规则的 lag。

释放是显式写用例。查询没有隐式释放副作用；释放使用同一账户、持仓、批次锁顺序。已释放批次不重复加可卖量，并另外保存实际释放使用的日历与知识时点。原交易 bundle 失效不永久禁止其历史已成交股份结算，但释放日历和账户范围仍须完整验证。

预读 `get_pending_settlement_scope()` 校验全部 pending 原绑定后返回最早会话与唯一原交易所；混合交易所阻断。版本 1 从已核验 Calendar 摘要读交易所，版本 2 从 V1 identity 与独立列交叉核对，版本 3 从 V2 identity 与独立列交叉核对；不回填或借用当前映射。Release 的既有必填 `exchange` 参数只作一致性断言，实际按原 scope 选日历；锁内再次核验完整批次，预读不是授权或锁内一致性替代品。

在变更任何可卖量前，释放流程先核验整个锁定 pending 批次的版本 1/2/3 原绑定及回执。任一行缺证据或不一致，整笔事务回滚，包括同批中的正常行。该校验使用原成交时点与原保存的证据；它不会为旧成交重查当前 selector，也不会把当前映射回填进旧绑定。实际释放仍按正式发布日历和原 lag 计数。

版本 1/2/3 回执还要求成交状态为 `executed`。待结算锁查询不以状态过滤，避免被改为 `cancelled/failed` 的 pending 行隐藏并跳过核验；这些行会明确阻断释放。

## 发布摘要与费用边界

日历 snapshot 的 `content_hash/record_digest/raw_payload_hash` 是带 `sha256:` 的摘要；正式 member 的 `fact_content_hash`、publication hash、policy hash 是独立的 64 位摘要。它们各有验证用途，不能互相代替。仅有未发布的 source snapshot 不满足 `PublishedExecutionCalendarReader`。

当前费用来源是 FeeConfig 实际存储的 binary64 值，使用 `Decimal.from_float` 保留，并标记 `NORMAL_SIM_ESTIMATED / DATABASE_BINARY64`；按分项 HALF_EVEN 舍入至分，完整快照及口径纳入摘要。新成交要求[费用 V2 的完整精确 case](a-share-simulated-fee-policy-v2.md)，未知市场、资产、板块或方向不能落入零费用。原 V1 快照/hash/公式仅保留用于历史收据核验，不自动升级或重扣。真实费率、适用范围和正式日历仍需配置及联合验收，不能因本地政策算法通过而声称沪深北实费制已覆盖；旧问题与迁移边界见[费用适用范围缺口](a-share-simulated-fee-applicability-gap.md)。

## 迁移与验收边界

`simulated_trading.0024_settlement_bound_trade_uow` 在现有成交表增加可空追踪字段与成对幂等约束。旧成交不会被自动标成已结算，不重算旧实收费用，不重写旧可卖量，也不创建第二套账本。日历事实由 `data_center.0099_exchange_calendar_snapshot` 承载。

`simulated_trading.0026_simulated_trade_settlement_plan_binding` 增加原计划版本、payload 与 hash；旧行只赋版本 0，不生成历史证据。其反向保护先于删除约束或列执行：任一行有非旧版本或任一绑定值时抛出 `IrreversibleError`，防止降级丢证据。存在此类行时，代码回滚应停用候选写入/释放并保留数据结构；不能通过清空证据来强行降级。

PostgreSQL 反向保护要求当前连接已在迁移事务中，先获取目标成交表的 `ACCESS EXCLUSIVE` 锁，再检查证据；锁保留至该事务结束，避免检查后、删列前插入新证据。非事务调用拒绝。此操作会暂时阻塞该表读写，不能把它当作无需维护窗口的在线降级。SQLite 不执行 PostgreSQL 锁语句；其迁移与并发验证范围分别记录。

`simulated_trading.0027_separate_settlement_exchange_identity` 新增独立 exchange 列和 V0/V1/V2 约束；旧 V0/V1 行保留 NULL，不从规则市场推断来源交易所。回退遇到任何 V2 或非空 exchange 先拒绝；PostgreSQL 要求原子事务，并在检查前取得目标表 `ACCESS EXCLUSIVE` 锁、持有至事务结束。不得清空 V2 证据强行降级；该迁移不新增第二套账本。

`simulated_trading.0029_current_reference_plan_binding` 将成对约束扩展到 V3。它自己的反向保护在恢复旧约束前运行：若仍有 version 3 绑定则拒绝；PostgreSQL 同样在迁移原子事务内先取得目标表排他锁再检查。该迁移不改写旧绑定。

版本 0 的历史行仍没有绑定证据：只保留既有完整回执的只读重放，不补证、升级或进入 pending 释放；若历史待释放 V0 行缺少可核验原绑定，释放仍阻断。新增 V3 不会为历史 V0 生成摘要或授权释放。

绑定 hash 是存储一致性 checksum，不是签名或来源真实性证明，不能抵御有数据库写权限者同步重写字段。V3 手动用途选择只支持普通模拟账本 BUY/SELL；原始 Data Center source 仍保留未知 upstream clocks 与 `must_not_*` flags。该路径不提供历史 PIT、实时 tradability、broker execution、自动交易资格，也不证明历史持仓可卖量或完整 T+1 血缘。

局部迁移验收按实际 operations、旧行和精确来源窗口分别记录升级、回退、再升级与拒绝丢证据。旧 real 账户、费用或 RawPayload 保持不变，只在确实核验对应数据的测试窗口声明，不能由新增迁移通过自动继承。全历史回放、生产迁移和用户入口验收分别报告。并发验收必须使用 PostgreSQL 两个连接，SQLite 跳过不算通过。
