# 普通模拟成交与结算事务端口

本端口是 ASH-02 的局部基础设施候选，不代表 ASH-03 完成。现有 `ExecuteBuy/ExecuteSell`、自动模拟、真实成交导入和 QMT 尚未切换。缺少正式日历发布适配器、明确费用适用范围及调用方交易准入检查时，不应将此端口装配成用户可用交易入口。

## 装配和责任

`apps.simulated_trading.execution_settlement_composition` 提供两个显式工厂：`build_execute_settlement_bound_simulated_trade_use_case()` 和 `build_release_due_simulated_settlements_use_case()`。调用方必须提供数据库 alias、带时区的 clock，以及正式发布日历 reader；成交还必须显式提供 Risk V3 rule reader 和 `ExecutionInstrumentIdentityReader`。没有默认规则、身份解析、交易所、日历、时钟或网络刷新。成交工厂让账本和 FeeConfig 读取共用同一个 alias 的 repository。目前没有接入生产身份 owner 或参考日历用途资格 adapter。

该事务只更新普通模拟账户。调用方仍须在成交前完成数量、价格、证券身份与状态、盘中阶段、账户能力和风险准入；日级日历不能证明这些条件。真实成交导入保留券商事实与实收费用，不走模拟预估扣款。

## 成交输入与重放

`SimulatedTradeIntent` 绑定用户、账户、证券身份、精确资产代码、资产类型、市场、板块、方向、数量、价格和账户内幂等键。Decimal 数值等价的输入，例如 `100` 与 `100.000000`，使用相同规范化请求摘要；不同业务输入重用同键返回冲突。

`intent.market/board` 是 Risk 与 Fee 的规则分类，不是日历交易所。身份 reader 按明确的 `security_id`、`asset_code` 和知识截止点返回 `ExecutionInstrumentIdentityEvidenceV1`，保留内部证券字符串、独立供应商代码、来源交易所/市场、映射后的规则市场/板块，以及精确 snapshot/mapping 身份和原时钟。不能推定内部 ID、资产代码与供应商代码相等，不能猜后缀、倒推映射或选择 latest。日历只按该证据的 `source_exchange` 读取。

证据可表示原有的禁止标记和未知来源时间；新成交必须拒绝禁止用于决策/执行、未知来源时钟或来源市场、未来知识及明确半开有效窗之外的结果。观测、可获得时间及原响应完成时间分别保留，并校验其先后关系，不用查询时间修复原值。有效窗由独立可信 reader 明确提供，不从 first_seen 或默认 TTL 合成。现有 Data Center 参考快照仍是 True/None，不能通过本合同自动获得资格；单测合成证据不证明正式身份 owner 存在。

Application 在锁外读取 V3 bundle、费用快照与完整日历证据。Repository 在单个同 alias 事务中依次锁定账户、目标持仓及按主键排序的未结算买入成交，然后重新读取时钟，校验时钟未倒退、证据仍有效、日期及覆盖仍一致。账户锁串行化同账户成交；重放只返回已持久化、内容完整且摘要匹配的结果，不重复变更账本。

本 Application 的新成交使用 `SettlementExecutionPlanV2`，显式写入 `settlement_plan_binding_version=2`；规则市场继续保存于 `settlement_market`，来源交易所独立保存于 `settlement_exchange`。`simulated-settlement-plan-binding.v2` 只包含 `schema/common_binding/identity_evidence`，外层保存独立 SHA-256。`common_binding` 复用原严格 V1 摘要及其解析器，保留原请求、预读/成交时间、会话/lag/释放日、Risk、Calendar snapshot/raw/publication 与费用摘要；历史 V1 wire/hash 不变，不复制千行校验或完整目录。回执严格解码、重算摘要，并逐项比较原行与身份、市场、交易所。未知版本、畸形 payload、摘要或原列差异均阻断。Calendar 全量 days 不复制，也不以今日 current 重建原计划。

尚未切换的旧买卖/导入入口及历史行保留版本 0 和空绑定；数据库默认值为 0，不能将所有新建 Model 行误认为经过本 UoW。版本 1 必须有完整原绑定和追踪身份，且独立 exchange 列仍空；版本 2 必须同时有完整绑定及独立 exchange，版本 0 必须无绑定与 exchange。Infrastructure 保留 exact V1 计划兼容分支；新 Application 不在 identity 缺失时回退到它。版本 0 仅保留既有完整回执的只读重放，不补证、升级或进入 pending 释放。精确幂等重放返回原收据，不重查新身份映射来改写原成交。

新增买入增加总持仓；可卖量仅按显式结算 lag 释放。卖出消耗已可卖股份，不消耗待结算批次。现金、费用分项、持仓、账户汇总和成交记录一起提交，任一写入失败整笔回滚。账户市值按本次目标持仓重估差额调整，保留其他资产部分；这不修复历史失真的账户汇总。部分卖出从持仓实际存储总成本按比例分摊，最后清仓带走剩余成本，避免从已舍入均价重建成本。

卖出费用高于成交毛额时，可由账户现金支付差额；资金不足则阻断并回滚，不允许透支。此行为属于正常模拟估算，不声称券商实收一致。

## 结算释放

每笔新买入在现有成交行中保存原 V3 bundle、结算 policy、原 lag、交易会话和当时正式日历引用。后续释放依据当前完整已发布日历，从原买入会话重新数开市会话，并使用该批次的原 lag。日历修订导致原预计释放日不再满足会话数时，应延后释放；不得仅比较旧预测日期，也不得改用新规则的 lag。

释放是显式写用例。查询没有隐式释放副作用；释放使用同一账户、持仓、批次锁顺序。已释放批次不重复加可卖量，并另外保存实际释放使用的日历与知识时点。原交易 bundle 失效不永久禁止其历史已成交股份结算，但释放日历和账户范围仍须完整验证。

预读 `get_pending_settlement_scope()` 校验全部 pending 原绑定后返回最早会话与唯一原交易所；混合交易所阻断。版本 1 从已核验的原 Calendar 摘要读交易所，版本 2 从原 identity 与独立列交叉核对，不回填或借用当前映射。Release 的既有必填 `exchange` 参数只作一致性断言，实际按原 scope 选日历；新成交的交易所也须与原 pending 一致。锁内再次核验完整批次，预读不是授权或锁内一致性替代品。

在变更任何可卖量前，释放流程先核验整个锁定 pending 批次的版本 1 或 2 原绑定及回执。任一行缺证据或不一致，整笔事务回滚，包括同批中的正常行。该校验使用原成交时点和原保存的证据，旧 bundle 或 identity 此刻过期不等于原成交时无效；实际释放仍按当前完整发布日历和原 lag 计数。

版本 1/2 回执还要求成交状态为 `executed`。待结算锁查询不以该状态过滤，避免状态被改为 `cancelled/failed` 的 pending 行被隐藏而跳过检查；这些行会明确阻断释放。

## 发布摘要与费用边界

日历 snapshot 的 `content_hash/record_digest/raw_payload_hash` 是带 `sha256:` 的摘要；正式 member 的 `fact_content_hash`、publication hash、policy hash 是独立的 64 位摘要。它们各有验证用途，不能互相代替。仅有未发布的 source snapshot 不满足 `PublishedExecutionCalendarReader`。

当前费用来源是 FeeConfig 实际存储的 binary64 值，使用 `Decimal.from_float` 保留，并标记 `NORMAL_SIM_ESTIMATED / DATABASE_BINARY64`；按分项 HALF_EVEN 舍入至分，完整快照及口径纳入摘要。新成交要求[费用 V2 的完整精确 case](a-share-simulated-fee-policy-v2.md)，未知市场、资产、板块或方向不能落入零费用。原 V1 快照/hash/公式仅保留用于历史收据核验，不自动升级或重扣。真实费率、适用范围和正式日历仍需配置及联合验收，不能因本地政策算法通过而声称沪深北实费制已覆盖；旧问题与迁移边界见[费用适用范围缺口](a-share-simulated-fee-applicability-gap.md)。

## 迁移与验收边界

`simulated_trading.0024_settlement_bound_trade_uow` 在现有成交表增加可空追踪字段与成对幂等约束。旧成交不会被自动标成已结算，不重算旧实收费用，不重写旧可卖量，也不创建第二套账本。日历事实由 `data_center.0099_exchange_calendar_snapshot` 承载。

`simulated_trading.0026_simulated_trade_settlement_plan_binding` 增加原计划版本、payload 与 hash；旧行只赋版本 0，不生成历史证据。其反向保护先于删除约束或列执行：任一行有非旧版本或任一绑定值时抛出 `IrreversibleError`，防止降级丢证据。存在此类行时，代码回滚应停用候选写入/释放并保留数据结构；不能通过清空证据来强行降级。

PostgreSQL 反向保护要求当前连接已在迁移事务中，先获取目标成交表的 `ACCESS EXCLUSIVE` 锁，再检查证据；锁保留至该事务结束，避免检查后、删列前插入新证据。非事务调用拒绝。此操作会暂时阻塞该表读写，不能把它当作无需维护窗口的在线降级。SQLite 不执行 PostgreSQL 锁语句；其迁移与并发验证范围分别记录。

`simulated_trading.0027_separate_settlement_exchange_identity` 新增独立 exchange 列和 V2 三态约束；旧 V0/V1 行保留 NULL，不从规则市场推断来源交易所。回退遇到任何 V2 或非空 exchange 先拒绝；PostgreSQL 同样要求原子事务并持表级排他锁至事务结束。不得清空 V2 证据强行降级。该迁移不新增第二套账本。

绑定 hash 是存储一致性 checksum，不是签名或来源真实性证明。它不能抵御拥有数据库写权限者同步重写所有字段。V2 区分规则市场与来源交易所并核验注入身份断言，但尚无正式身份选择 owner、reference 数据用途资格、历史 PIT 或调用方交易准入；原 source/decision/execution 限制不因绑定而改变。

局部迁移验收按实际 operations、旧行和精确来源窗口分别记录升级、回退、再升级与拒绝丢证据。旧 real 账户、费用或 RawPayload 保持不变，只在确实核验对应数据的测试窗口声明，不能由新增迁移通过自动继承。全历史回放、生产迁移和用户入口验收分别报告。并发验收必须使用 PostgreSQL 两个连接，SQLite 跳过不算通过。
