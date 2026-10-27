# 当前数据新鲜度契约与 CI 门禁

2026-10-27 M1 日终收盘预览：普通账户巡检可显式选择 `reference_price_basis=published_close`，默认仍为 `market`。模拟交易组装固定选择 `m1-rebalance-reference` 发布键，HTTP 不接受发布键或知识截止点。日终模式只读已发布的最近完整交易日成员，统一使用预览截止点核对发布、观测和获取时间；证券、交易日、来源、覆盖或发布证据缺失时返回明确阻断，不回退市场报价或裸事实。多证券必须来自同一发布身份；价格与来源引用一起进入计划。日终参考不代表可成交报价，不允许自动创建交易提案，账户、数量、费用和风险门禁保持。TUI 显示所选口径、基准日与来源时间，响应口径不匹配时隐藏计划；开发合成来源测试不构成账户 613 真实来源或普通用户验收。

2026-10-27 独立日线发布：受审计的价格同步由可信组装代码显式选择发布键，默认仍为 `current`，请求 DTO 和 HTTP 输入不接收任意发布键。返回证券必须等于请求经既有规则规范化后的代码，日期必须在请求范围内且不得重复；非价格实体、错误证券、越界或重复日期在事实及发布写入前拒绝，并沿用失败采集审计。独立键使用已有发布与事实版本保护，不能缩小或改写全市场 `current` 的成员和已引用事实；生成发布记录不自动激活读取指针，激活仍走既有独立门禁。此能力不自动赋予单证券数据当前用途资格，不取代完整范围、正式日历、新鲜度、原件来源或 M1 用户验收；同证券同日的隔离回归登记在既有 `data_center.publication_writer_atomicity`。

2026-10-27 费用材料编号恢复：重开页面可使用原预览的公开材料 UUID 在既有 head 入口只读定位原请求。仓储在当前 owner、账户和成交范围内校验不可变材料及事件绑定；同时提供原请求编号时两者必须匹配。材料存在但无入账回执仍为 `partial`，策略或令牌过期不改变历史回读资格。读取不更新材料时钟、不生成新请求、不授予执行权；页面显示的恢复编号不代替权限。既有费用绩效 as-of 合同增加精确材料回执与无回执反例。

2026-10-27 移动止损峰值观察：更新必须核对原峰值、源观测时间、有效规则、未关闭持仓及所有者范围，只更新峰值和观察时钟等既定观察字段。陈旧快照或并发状态变化返回不可用并要求重新读取，不继续发布旧峰值的触发结论。源时间不能倒退，写入时间不能替代源时间，价格不得静默舍入到存储精度。该路径仍仅作观察，不构成自动卖出或普通模拟成交资格；登记扩展既有 `account.legacy_automated_exit_price_observation`。

2026-10-27 费用更正确认：真实登录会话预览的确认期限固定为原材料 `stored_at + SESSION_COOKIE_AGE`，同键重读、会话续期和请求时间不能刷新材料时钟。确认在锁内核对当前数据库会话、用户认证摘要、账户权限、材料及原修订，入账后外层事务提交前再次核对令牌与实际会话期限；超期回滚。令牌过期不阻止当前所有者以原请求编号只读查询已完成回执。带编号的 head 只有找到真实回执才返回 `outcome=success`，未找到返回 `partial`，不能解释为未入账；普通 head 读取仍返回已验证版本。

2026-10-27 费用更正版本回读：owner 范围的 head 使用同一已验证完整账本、账户与主体锁以及带时区 `as_of`；未来事件、断链或未知金融事实必须阻断，不能变成版本 0。原请求编号可定位历史回执，策略停用后仍允许当前所有者读取已完成记录。未找到回执和存储不可用都不能证明未入账；写入结果不确定时保留原编号回读，不自动生成新请求。head 的本地读取时间不刷新材料源观测时间，不授予来源或执行资格，登记扩展既有费用绩效 as-of 合同。

2026-10-27 模拟账本仓储职责收敛：成交所有者范围读取和日净值费用更正投影迁至同 App 的专属读取仓储，既有 facade、构造注入及公开签名保留。current 合同同时检查 facade 接线和实际实现位置；费用更正的知识截止点、原净值、覆盖水位及未知指标语义不变，原子成交与日净值写入的锁和快照检查保持。该调整不改变当前数据资格或生产启用状态。

2026-10-27 全市场 Tushare quote 原件：一次 `daily(trade_date=...)` 响应在事务外获取并校验完整冻结范围，随后在短事务内签发真实父采集身份、留存一份安全 RawPayload。每个事实写入批次继续签发独立子身份，RawAudit 与事实同时绑定父采集引用，避免多个批次撞审计幂等键。供应商健康只记录实际采集一次，响应完成时间不替代交易日收盘观测时间。留存失败、身份或范围不一致不得退回无原件路径。候选 staging 在自己的事务内重读原件及关联，拒绝混合、缺失或错绑来源；完整范围、显式排除及原发布资格不变。旧的无 capture 候选仍按原合同处理，不补造历史原件。

2026-10-27 全市场行情响应身份：Tushare 日线返回同一请求证券的重复行时，以 `TUSHARE_DUPLICATE_QUOTE_ROW` 拒绝整次读取；完全相同、数值冲突和首行不能解析的重复都不能通过字典覆盖消失。检测在报价行解析之前进行，完整请求范围与单次全市场请求保持，范围外证券仍按原合同过滤。该检查不改变源观测时间、数值单位或当前用途资格，登记在既有 `data_center.tushare_full_market_empty_response`。

2026-10-27 单证券 Tushare quote 留存：精确请求在网络访问前绑定实际证券、交易日及provider，网络访问保持在数据库事务外；既有短UOW内先签发run，再留存同次响应、写入事实及审计。RawAudit引用安全封装payload_hash，原body摘要与含run的记录摘要不混用；响应与引用漂移或留存失败必须在事实/发布前阻断。响应完成时间仅是本地获得原件的时间，历史日线的观测日、最近已收盘交易日及原Publication政策保持。相同参数并发的capture归属各自返回值，不用共享最近响应缓存。此路径不为旧事实补造原件，不收缩全市场current范围，不因原件存在就取得决策或执行资格；登记扩展既有 `data_center.publication_writer_atomicity`。

2026-10-26 M1 普通用户预览：既有 `simulated_trading.readonly_rebalance_preview` 逐次核对风险版本与实时读取的账户、owner 专属策略和仓位规则来源；缺失、失效、撤销或来源变化时继续阻断 BUY。普通巡检先将账户真实 User 映射到独立 Profile，未经授权的策略不得进入报告；assignment 不构成共享授权。风险敞口合计已持有市值、未成交 BUY 的剩余限价本金及本次建议金额，并以已知费用扣减后的权益作分母；未结算 SELL 不提前释放敞口，未知本金或费用不能补零。版本发布留证时间、账本读取时间仍不替代行情观测时间，发布/撤销仅写风险与审计记录，不写金融账本或授权下单。

2026-10-26 M1 风险版本：`risk_center.m1_rebalance_policy_qualification` 使用显式带时区截止点，逐次核对账户归属、账户/策略/仓位规则来源、有效期和撤销事件。`known_at` 仅表示本地发布留证时间，不能替代供应商观测时间、旧策略风险版本或历史生效时间。缺失风险值保持未知；声明“不适用”不能移除已配置上限。该资格只服务调仓预览的风险判断，来源当前用途资格、普通用户实测和下单授权仍分别校验。

2026-10-26 模拟费用更正：`simulated_trading.fee_correction_effective_performance_as_of` 登记原成交、差额入账和有效绩效的时间边界。原成交费用与滑点不可改，更正仅在实际 `posted_at` 后进入有效历史；日净值须有匹配的更正 revision/prefix watermark 才能发布已知绩效。缺失历史、费用或覆盖证据时返回 null 与稳定原因，不能回退原缓存或零值。当前绩效缓存任务仅接受配置时区的当日，历史查询仍走显式只读 `as_of`。这些本地账本时间不替代行情源观测时间，也不授予交易资格。

2026-10-16 A 股 v2 候选评估登记 `risk_center.a_share_execution_submission_v2`：阶段及盘口与嵌套市场证据共享真实源时间窗，规则/市场均从同一账户和知识截止点读取；缺少 v2 来源不回退至 v1，不用计算时刻刷新旧事实。新的外层 hash 不替换嵌套 v1 hash，也不构成下单授权。候选算法与 Application 的本地通过不能替代 Agent、可信 Provider 和正式发布验收。

独立 Agent v2 校验器在服务端截止点和本地提交时重验源窗口、阶段及价格范围；共享算法由 `scripts/build_qmt_price_submission_projection.py` 生成，Consistency Check 运行 `--check` 拒绝字节漂移。心跳中声明的 schema 能力按每次已接收心跳替换，缺失时清空；它只说明所声明的解析能力，不能证明源新鲜、当前权限或执行就绪。

## 目标

模拟费用更正预览复用 `simulated_trading.fee_correction_effective_performance_as_of`：在账户锁内读取完整已验证历史，再保存并验证原材料。同一请求保留原 revision/前序，过时绑定不得跟随最新 head 重绑；已完成请求仅在原材料与入账事件的来源绑定一致时返回原回执。预览的 `as_of`、`stored_at` 与 `verified_at` 分别表示本地读取、保存和验证时间，不能覆盖 `source_observed_at`，也不代表材料经券商认证或更正已入账。预览失败回滚新增材料，实际更正仍在确认时重验来源、权限和版本。

2026-10-25 估值工作流范围：内部完整仓库范围不受外部5000项请求上限影响，质量分子只绑定本次冻结代码；范围外旧事实和尾空格身份不得抬高覆盖率。`scope_sha256`是排序后规范化唯一代码集合摘要，不绑定处理顺序，仅绑定本次响应，不为既有日期快照补造持久化范围/PIT身份；源码中的源日期及原freshness门保持。canonical处理计数含未变更重放，不能据同步outcome、请求时刻或新摘要宣称源已刷新、current Publication可用或可决策。质量阶段的operation成功只证明快照评估完成，证券有效性仍看valid/coverage/gate字段。登记见`equity.valuation_frozen_workflow_scope`，实际生产发布及来源资格另行验收。

2026-09-19 补充：模型原始行情参考必须排除前复权/后复权记录；网关复权标记和成交量单位应传递至 canonical 存储，不能以 none 默认值掩盖调整口径。Alpha 定时入口遇到明确数据阻断应停止投递子推理。旧库错标记录不随代码自动改写。

所有带有 `current`、`latest`、`realtime`、`summary` 语义的数据面，都必须证明“源数据仍在允许的新鲜度窗口内”，不能仅因为数据库查询返回了最新一行就宣称数据当前可用。

机器真源为 `governance/current_data_contracts.json`，自动检查入口为：

```bash
python scripts/check_current_data_contracts.py
pytest tests/unit/ci/test_check_current_data_contracts.py -q
```

该检查已接入 `.github/workflows/consistency-check.yml`。

## 五条不可破坏的语义

多证券股票池的 published 读取可展示已验证发布中的局部估值缺失：仅接受
`equity.valuation.fact` / `valuation_source_data_unavailable`，按真实 master 解析结果
绑定请求代码、canonical asset、发布身份与范围，保留完整请求分母、逐行限制及原始源时钟。
受限池发布 `outcome=partial` 和 `must_not_use_for_decision=true`；缺失 PE/PB 为 null，
均值必须覆盖完整请求分母才可输出。财务缺失、未知阻断原因、身份或全局完整性异常仍阻断全池。
全池阻断时逐资产受限数量未知则为 null，不能补零。SDK 完整 payload 保留池级证据，
旧裸列表在 published 资料受限或资格未知时明确拒绝并提示改读完整 payload。
本读取合同不改变发布策略、Provider 资格或单标研究财务 partial 的原有边界。

研究聚合 `mcp.equity_research_snapshot` 同时发布 owner 原始 `status` 与规范化
`outcome`：完整读取为 `success`，可选材料缺失为 `partial`，受阻、身份未解析、
未知结果状态或明确禁止决策为 `blocked`。HTTP 200 只证明传输成功；此附加字段
保留分区、可靠性、限制与源时间，不改变真实数据就绪度、研究或执行资格。
对应 HTTP/TUI 消费测试只供给读取端口及名称端口，真实走既有视图和执行器，
不是 Publication、四项就绪度或浏览器主任务验收。

财务公告范围发现 v2 以两份响应共同的知识截止点选择最新已可用公告，不能让尚不可用的最新行遮蔽旧的已可用公告。
缺失/占位日期隔离并保留原文；全集逐资产分类，`partial` 不具有完整财务刷新能力。范围 eligible 不等于财务事实 fresh，
不得绕过 Publication 的 freshness 与独立授权。登记见 `data_center.financial_scope_latest_available`。

Alpha Qlib 推理缓存必须按 `asof_date` 核对请求交易日；旧源日期仅可写为
`degraded`，发布 `must_not_use_for_decision=true` 和 `qlib_source_data_stale`，
并跳过下游推荐刷新。每日行情额度耗尽直接返回阻断且零写入，不改变旧评分时间。

1. **排序最新不等于当前可用**：`get_latest()` 之后必须执行 freshness/reliability 判断。
2. **源观测时间不可变**：`snapshot_at`、`observed_at`、`bar_date`、`as_of` 必须来自源数据；不得用请求时间或计算时间覆盖。
3. **过期结果不能截断 failover**：provider 返回非空但已过期时，组合数据源必须继续尝试后续来源。
4. **降级必须显式**：历史收盘、代理值和不完整数据必须发布明确的 freshness/source/fallback 状态。
5. **决策输出必须失败关闭**：数据不可靠时发布 `must_not_use_for_decision=true` 和稳定的 `blocked_reason`，不得继续生成确定性建议。

日频 A 股 quote/price/valuation 的自然小时预算到期后，只允许在所有 Publication member 都精确绑定最近已收盘交易日时标记为 `latest_completed_session`；quote 只在盘后、开盘前或休市日沿用最近已收盘交易日，新的交易时段一旦完成便必须重新发布。这不会改变源观测时间。全市场 current Publication 必须按冻结 universe 原子发布，单标的或中间批次同步只写 fact，不得缩小既有 current member 集合。

全市场任务的冻结分母同时绑定 universe refresh 报告、规范化代码集合及集合 SHA-256；数量或身份摘要不一致即以 `MARKET_UNIVERSE_SCOPE_INVALID` 失败关闭。Provider 缺行不构成停牌、未上市或退市证据；valuation seed 未完整覆盖冻结分母时发布 `CURRENT_VALUATION_SCOPE_INCOMPLETE`，保留缺失代码并禁止创建缩小范围的 current Publication。

生产预演也必须沿用完整 active universe 分母。`daily_basic` 等估值响应缺行时，即使缺失比例满足当前 Publication policy，也不能把这些证券转成 excluded 或继续测量缩小后的行情范围；容量预演以 `REHEARSAL_CAPACITY_VALUATION_SCOPE_INCOMPLETE` 阻断，并输出完整 active 代码集合、其 SHA-256、缺失代码和 requested/succeeded/failed/stored 统计。只有具备版本化、可校验的交易/上市状态证据合同后，才可将明确状态作为排除依据；provider 缺行和零值模式本身不构成该证据。

全市场刷新任务使用 `latest_closed_cn_market_session` 选择目标日：收盘后选择当日，盘中、开盘前和周末选择上一已收盘工作日。盘中触发不得因为实时决策函数返回 `None` 而跳过上一完整交易日的恢复；Publication 仍须通过完整范围、源观测日和事实证据检查后才能发布。

单股 published price 读取必须把 UTC 观测时间转换为中国市场日期后再限制 `end_date`，不得把中国收盘时刻截断为前一自然日。公开 API 只返回 Publication 的公开证据字段，以下划线开头的成员主键和内部快照状态不得序列化。Alpha 刷新提示应以更新且验证可用的 quote/price/valuation Publication 调和历史失败记录；恢复时间不晚于失败完成时间时仍保留告警。

## DATA-16 版本化证据边界

候选策略具有独立 `policy_version`，不可用同一版本改写决策字段；新的 `p2` 身份绑定
完整策略内容，Publication v2 同时绑定该身份和冻结成员证据。历史 v1 hash 字节与历史
查询语义保留。当前读取必须重新核对 active policy、完整 member 集合、实际事实行
内容、观测及可用时间和查询知识截止点，缺失或漂移发布稳定阻断原因。

`fact_content_hash` 是所有持久化事实字段的规范化行 SHA-256，不证明供应商原始响应。
兼容证据键 `payload_hash` 使用既有持久化哈希或原规范化 payload 回退规则；候选
price/quote/financial 策略保留这个兼容键并额外要求 `fact_content_hash`，不能据此声称
原始 HTTP body 留存已齐全。valuation 候选策略另行明确要求 `raw_payload_hash`、
`raw_payload_scope` 和 `source_record_id`；仅真实响应 bytes 的哈希和明确 body scope
可作为原始响应证据。共享 batch body 哈希不表示每个资产有独立响应体。
响应完成 UTC 只证明本系统此时已获得响应，不能作为供应商最早披露时间，也不得覆盖
vendor `observed_at`。未部署候选策略与代码前，不宣称生产 DATA-02 缺口已修复。

冻结成员的 natural key、source、source record、观测时间、兼容 payload hash、quality 和
revision 必须与实际事实行独立相符；持有正确行 SHA 也不能伪造这些身份字段。当前返回的
Publication 必须绑定请求的 dataset 与 publication key，否则以
`publication_scope_mismatch` 阻断。p2 的 selected source 来自所选事实的实际 vendor 集合，
不能使用逻辑 provider 名称替代 failover 后的来源。

完整 current 查询在同一数据库边界内读取元数据、策略、成员与事实。PostgreSQL 外层采用
repeatable-read/read-only；已有 repeatable-read 或 serializable 复用父快照。可写
read-committed 父事务先锁 dataset contract、相关 asset master/alias 或 indicator catalog，
再按 fact → policy → publication → member 顺序获取 SHARE 表锁，保护更新与缺失行插入。
每次锁等待不超过原调用方更严格的预算或 5 秒；最多 7 个锁，总等待上限 35 秒。超时或
deadlock 回滚嵌套 savepoint 并明确失败，锁持有至父事务结束。只读 read-committed 无法
提供完整快照时失败关闭；这些约束不改变历史查询访问。
snapshot helper 接受可选调用方 `lock_deadline`（monotonic 时间）；传入时，每个锁等待上限为剩余预算与更严格的调用方 `lock_timeout` 中较小者。未传入时保留原有逐锁预算。预算耗尽会回滚嵌套 savepoint、显式失败并恢复原 `lock_timeout`；此 helper 端口本身不规定任何 composition 是否以及如何共享该截止点。

Published equity analysis passes one monotonic 35-second deadline through the snapshots for all three dataset keys; each nested table-lock acquisition consumes the same remaining budget, so the wait allowance is not multiplied per dataset.

## 版本化登记内容

AUD-05 的 `config_center.active_public_snapshot_integrity` 约束当前配置读取：公开值与 secret ref
读取均须匹配 active profile 和有效的 canonical public snapshot hash，篡改/陈旧快照失败关闭，
不能回退为 superseded v13。full profile/revision hash 继续绑定完整已验证配置（含 secret ref
身份），public snapshot hash 仅覆盖公开投影；两者不得混用。配置 corrective activation 经
原子写入端口创建新 successor；该配置完整性门不替代市场数据 freshness 或真实 authority 验收。

2026-09-21 复核补强：secret 引用读取、active 配置验证和 patch 继承必须将完整持久值重算后
与 profile.content_hash 比较，并拒绝重复键或跨 profile 值。事务提交前锁定并再次核对旧值，
不能把已改动、缺失或额外插入的旧值重新封为合法 successor。最终写入端还核对新值完整哈希、
revision 前后哈希和 public projection/snapshot 一致性。多 active profile 或同 profile/version
多 snapshot 读取均失败关闭，不依靠排序选取一条；历史数据不随代码修复而改写。

每个当前数据面必须在 manifest 中登记：

- `id`：稳定、唯一的契约标识；
- `surface`：API、SDK、MCP 或内部服务入口；
- `source_files`：实现该语义的生产文件；
- `required_markers`：必须保留的观测时间、阻断与 failover 代码标记；
- `required_tests`：精确到测试函数的证据，并区分 stale/fresh/fallback/observation 等场景。

仅写测试文件名不算证据；检查器会解析 Python AST，确认函数真实存在。

## AST 时间戳洗白门禁

检查器会扫描 `apps/**/*.py`、`sdk/agomtradepro/**/*.py` 和 `sdk/agomtradepro_mcp/**/*.py`（排除 migrations/tests），当前拒绝三类高风险模式：

- 从 `bar/latest_bar/historical/close/nav/fact` 等历史变量构造 `RealtimePrice`，却使用 `timezone.now()` 或 `datetime.now()` 作为行情时间；
- 已包含 `trade_date/as_of/freshness/is_fallback/observed_at` 等来源元数据的 payload，又把 `timestamp` 设置成请求时刻。
- 当 `observed_at/snapshot_at/market_data_as_of` 缺失时，用 `timezone.now()`、`datetime.now()` 或 `date.today()` 补造源观测时间。

真实现货抓取在收到响应时以 `timezone.now()` 记录“抓取观测时间”是允许的，前提是值并非来自历史 bar 或旧 fact。

## 新数据面接入清单

财务公告日或报告期不能合成精确源可用时间。Tushare/AKShare 的 date-only financial
结果保留日期且 `available_at=None`；历史 calendar backfill 的 Application 和直接
Repository 写入口发布 `FINANCIAL_SOURCE_TIMESTAMP_REQUIRED`，不修改事实行。
只读盘点中任一 missing/unresolved availability 均不可执行，完整抓取计数也不能
使发布主流程绕过该阻断。精确公告时间、原始响应哈希和历史来源修复另行验收。

财务来源时间匹配契约只有在 owner approval 同时绑定精确 contract digest 集合时才能激活。
pending registry 必须保持 `contracts=[]`、`approval=null`；单独修改 status 或插入合约不能
形成授权。receipt SHA-256 只锚定审批原件内容，不证明签署人身份或当前 authority，生产启用仍须
独立核对真实 owner、receipt 和授权时效。`approved_at` 使用秒精度 canonical UTC-Z；更高精度或
带 offset 的表示必须在登记前规范化，不能让同一审批瞬间产生多个治理编码。

provider-specific matcher 必须以完整 contract identity（provider、contract id、contract version、
contract SHA-256）登记和解析。`parser_version` 只是受 contract digest 约束的实现字段，不能单独作为
matcher 路由键，也不能提供 parser-only fallback；未精确登记的 contract 必须失败关闭。

QMT 整体桥登记为 `data_center.qmt_bridge_observations`：源时间在重试时保持不变，VPS 仅接收授权标的，stale 快照不能截断备用源；批次落库不等同于全 universe current Publication 激活。

ASH-02 的 `data_center.exchange_calendar_reference` 登记精确日历快照的知识时间及能力边界，
不声明 current/fresh。`first_seen_at` 是本机完整收到响应，`recorded_at` 是首次写入事实；
两者均不晚于查询 `known_at`，重试不能刷新。上游发布时间没有明确来源时保留空值。
快照返回 `publication_status=unpublished`、两个不可用于决策/执行标记及
`exchange_calendar_unpublished_reference`；这些派生标记不改变原事实摘要。后续开市日只在
完整明确的自然日覆盖范围内查找，范围不足必须阻断，不能用周末算术、跨交易所日历或
最新一行补出执行证据。正式 Publication 引用及普通模拟消费者的接线另行验收。

候选模拟成交 V2 的身份 reader 必须按明确证券/资产和知识截止点提供原 snapshot/mapping 引用、
来源 exchange 与规则 market/board，以及独立来源时钟和明确半开有效窗。来源禁止标记、未知
observation/availability、未来知识或到期均阻断；本地 response completion 不能替代上游时间，
且已含事实的原响应不得早于该事实的可获得时间。真实 Data Center 参考快照仍为 True/None，
没有默认生产身份或用途资格 adapter。幂等重放和 pending scope 按原已保存证据核验，不能用
今日映射改写历史交易所；该候选合同及合成测试不授予参考数据执行资格。

### 首次 BUY 创建持仓的初始估值

`simulated_trading.first_buy_initial_position_mark` 只约束首次 BUY fill 为一个尚不存在的模拟持仓建立估值时的本地消费者行为。消费者要求独立、类型化的当前 mark proof，并将其精确绑定到五项证券身份；mark 的 `read_at` 是这次估值的知识截止点，真实成交价仍来自 fill 事件。`source_observed_at`、可空的 `source_available_at`、publication 时钟、读取时钟和策略有效期保持各自含义；未知的 `source_available_at` 继续为空，不能用请求、读取、发布或成交时间补造。

默认没有 `InitialPositionMarkReader` 接线；缺少 reader 或缺少可用 mark 时阻断首次建仓。已有持仓的未知估值不由此路径修复。已保存的精确成交回放使用封存回执，不重读 mark 或当前时钟。V2 回执把 mark 证明与成交经济数据分别封存，readback 校验身份和摘要绑定。

这项登记仅覆盖已注入 reader 的本地消费者与持久回执校验，不证明任何行情 provider 的资格、历史 PIT 适用性、全市场或盘中决策资格，也不授权 HTTP/SDK/MCP 或真实券商执行。外部 source adapter 尚未接线并另行验收。


`data_center.formal_calendar_current_pointer_contract` 登记后续正式日历的纯契约切片。
TTL 从原始响应的 `first_seen_at` 计算，未知的供应商 observation/availability/publication
时间继续为空；新发布时钟不能刷新响应年龄。当前读取只接受精确指针的 `PUBLISHED`
结果，不重建历史指针；pointer 更新时间必须与该次发布时刻一致，且配置、事实及指针
均已在查询截止点被系统知悉。向前发布时钟必须严格晚于旧指针，重放则保留原时间及
原操作者身份。成员行及 publication 行的存储 ID 不在既有证据编码内，数据库分配 ID 后
仍比较其余全部值，而非只比较摘要字符串。本登记仅证明 Domain/Application 合同，
Infrastructure 原子写入、Audit 完整性、路由和模拟消费者须分别验收；返回值继续
`must_not_execute=True`，不构成源观测新鲜性、盘中状态或券商执行许可。

新增任何当前数据读取时，按顺序完成：

1. 在 Domain/DTO 中定义 observation 与 freshness 约束；
2. 在 provider/failover 层区分 missing、stale、fresh；
3. 在 API/SDK/MCP 输出 observation 和决策阻断字段；
4. 写 fresh、stale、fallback、未来时间/naive 时间边界测试；
5. 更新 `governance/current_data_contracts.json`；
6. 运行本门禁、相关回归、mypy 和架构检查。

## 现有受管数据面

受管数据面数量以当前 manifest 为准，覆盖：

- Realtime 市场概况、轮询副作用、板块表现与缓存榜单；
- Data Center 最新报价、统一价格、日线收盘/基金净值 failover 与市场温度计；
- Regime 当前状态、缓存行动建议、Core 决策上下文与 Terminal/SDK/MCP 传播；
- Sentiment 当前状态及 Fund/Asset Analysis 消费者；
- Valuation 当前价格 fallback；
- Account 最新汇率、隐式换算与组合币种配置；
- Hedge 最新快照、Rotation 最新信号；
- Equity 分时备用源校验；
- Decision Rhythm 特征快照与统一推荐；
- Pulse 当前快照。
- TUI 操作者市场上下文对宏观象限、政策截面和 Pulse 时效结论的忠实呈现。
- Active A-share quote/price/valuation/financial 的全 universe current Publication、完成交易日语义、真实 report-date availability 修复和失败关闭的 provider 批次刷新。
- 决策运行门的三项严格预检、候选绑定 compare-and-set 激活、激活后复验与失败自动 re-block；禁止以裸 `active` 状态写入替代该流程。

受管范围应随新的决策数据面增加，只能扩展，不能静默删除。

### A 股执行约束的源时间与提交重验

登记 `risk_center.a_share_execution_constraints` 覆盖 Risk owner-read 规则评估与独立 Agent
重验。规则、日历、市场和股份分别保留源观测/可用/失效时刻；评估知识截止点不能代替
源时间。缺失配置、未来可用、过期或未知状态均阻断；Agent 同时校验服务端 `as_of` 和
本地实际提交时刻，不因服务端曾返回 `ALLOWED` 而跳过时效检查。

这一内部可交易性合同通过 `DENIED` 和稳定原因码失败关闭，不授予账户权限或正式执行
能力；公开任务界面的当前可用标志、完整价格笼子、实际 source adapter 和生产门禁仍按
[实施计划](../plans/a-share-usability-implementation-plan-2026-10-16.md)独立验收。


### 2026-09-09 Pulse 持久化快照读取

重建 Pulse 快照时，按既有指标频率与 PulseConfig 阈值重新计算数据年龄。保留采集时基于发布日计算的年龄，再加上快照观测日到读取日的经过天数（日频使用工作日）；保留原始 observed_at，历史已过期标记不能重新变为可用。缺失源日期或年龄、未来源日期均阻断。回归：`test_pulse_current_rechecks_persisted_reading_age`。


### 2026-09-09 模型历史行情中台路由

Qlib/Equity 的历史行情统一经过中台：旧观测继续尝试后续源，无重叠参考或超过配置容差时阻断；保留原始日期与不复权口径。详见 [本地改造与边界](../plans/model-market-data-center-routing-2026-09-09.md)。证据登记在 `data_center.model_market_history`。

## 2026-09-19 全天停牌与模型数据缺失的区别

模型行情仍先尝试 fresh failover；所有尾部缺失交易日只有在同一提供方的显式全天停牌记录逐日覆盖、且原始行情跨源一致性通过时，才发布 `MODEL_MARKET_SUSPENDED`。日内停牌、复牌记录、空响应、日期或资产不匹配不能豁免 stale。已校验的历史日线可按真实日期落库，不能改成当期或合成价格。后续备用源额度耗尽不推翻已验证停牌，但价格/成交量冲突仍阻断。Qlib 构建将已核验标的单列于 `suspended_codes` 和警告，限制 instrument 终日到真实末日，并仅在整个构建成功后原子写入绑定目标日与完整请求范围的停牌证据。账户推理只允许该证据解释当日缺席成分，未知缺失仍以 MODEL_MARKET_SCOPE_INCOMPLETE 阻断；缓存另存停牌清单、末次观测和请求/可推理数量，不能为停牌股票生成评分。未知滞后和指数 stale 仍整批阻断。

字段依据：[Tushare 每日停复牌](https://tushare.pro/document/2?doc_id=214)。

原始行情参考还必须保留缺失成交量的语义：volume=None 的 close-only 记录不能经 or 0 转成可比较的 OHLCV 参考，必须排除；真实 volume=0 继续参与严格比较。无其他可用参考时仍以 MODEL_MARKET_UNVERIFIED_FAILOVER 阻断。

Qlib 复权缩放必须使用相同观测日的已有 factor 与 incoming adj_factor 配对；重复刷新须保持二进制特征不变。已有 factor 出现非有限值或非正值时，在推进日历前以 MODEL_MARKET_LOCAL_FEATURE_INVALID 阻断；特征超出 float32 范围禁止落盘。已损坏数据需先备份、隔离再重建，不得复用无穷值。

Alpha 候选须消费 stock context 的发布阻断标志，不能仅检查评分缓存。缺失成交量保持 None 并阻断候选可执行性；真实 0 参与低流动性判断，不能回退成其他来源的正成交量。输出保留成交量来源和原观测时间，不能以请求时间代替。信号不足提示列示原 Alpha 分、当前映射值和实际策略门槛，证伪条件使用同一信号强度口径，不再混用固定原始评分 0.55。

2026-09-19 全市场恢复补充：腾讯快照成交量复用已配置并经跨源验证的板块手/股规则，禁止快照与日线量纲不同。模型行情可按代码批量预取，但缓存精确绑定起止日期；每次请求按自然日上界限制潜在返回行数，疑似截断、缺失成员和不支持批量时保留逐股请求。批量缓存不绕过逐股新鲜度、停牌证据或跨源 1% 一致性校验。

宽范围历史按真实交易日历逐日批取全市场 daily/adj_factor，最多 4 个并发请求链，检测 6000 行截断及忽略 trade_date 的响应后回退。股票小范围仍按代码批取。北交所快照与日行情可能有大宗交易口径差异；恢复核验须用真实大宗记录对账，不能放宽 1% 容差。源的原始成交量和日期保留在归档中。

共享 Qlib 目录增加跨进程读写锁：构建独占、推理共享读取，冲突发布 `MODEL_MARKET_REFRESH_BUSY`，不得读取半写入特征。停牌证据仍绑定构建成功后的完整范围和目标交易日。

Alpha 页面独立读取全市场发布任务的业务 outcome。评分推理成功不能清除尚未恢复的行情发布错误；成功发布才清除该路径的旧错误。未知异常仅显示固定提示，不回显凭据或原始异常。

股票全集同步保留源提供的合法交易所后缀；裸代码不在既有前缀规则中时，仅可从资产主数据解析，不能猜测新板块规则或误停用已知在市股票。

单股 published price 查询先校验全 Publication 的现行策略、范围、成员和所有源内容哈希，再仅按该股票选中成员的最旧观测评估时效，并保留 publication.as_of 上界。全市场 gate 仍反映全集最旧日期；单股返回 freshness_scope=asset。其他股票停牌不得让当期有效股票丢失成交量；目标股票过期、缺成员或任意成员被篡改仍阻断。


### 批量股票上下文（2026-09-19）

`get_published_equity_context_payloads` 按数据集创建一致性读取快照。在该快照内，
全量 policy、member、fact hash 证据只验证一次，再按股票选择成员主键读取事实。
价格 freshness 仍按股票计算，整体完整性核验必须覆盖请求范围之外的所有发布成员；
财务和估值保留原有全局 freshness 规则。证明只在本次函数调用内有效，不存入跨请求
缓存，不在下一次读取复用。缺成员、篡改、缺策略和过期数据仍返回明确阻断。

回归：`test_batch_validates_whole_market_once_and_rechecks_next_call`、
`test_batch_prices_preserve_each_assets_source_freshness`。

2026-09-20 合并前维护：观测时效计算统一放在 `publication_query_bounds.publication_freshness_gate`，单股与批量读取共享同一规则；全市场 Publication 的装配移至 `publication_rebuild_composition`，原 composition 工厂入口保持兼容。

### Published equity valuation analysis: current members, clocks and limits (2026-10-19)

`GET /api/equity/valuation/{stock_code}/?mode=published` must resolve valuation, financial and price evidence from the current publication gates and exact selected member facts. The analysis context enters all three dataset snapshots before reading any selected payload; a missing/invalid member, required gate, usable valuation history or snapshot boundary returns a blocked/failed result with decision fields left null. It must not hydrate from an unbound latest row or turn missing values into zero.

Published valuation history is bounded by an integer `valuation_limit` in `[1, 5000]`; the analysis use case requests 5000 rows. This is a query cap, not publication coverage, provider qualification or universe-completeness evidence. `observed_at` remains the source observation (`source_updated_at`) and `fetched_at` remains knowledge time (`updated_at`); neither may be replaced by request or calculation time.

The consumer contract is bound to `test_equity_analysis_context_enters_all_dataset_snapshots_before_read`, `test_equity_analysis_context_propagates_snapshot_timeout`, `test_equity_context_rejects_invalid_valuation_limits_before_read`, `test_equity_published_reads_block_when_a_publication_gate_is_missing`, and `test_published_valuation_api_reads_exact_current_members_and_source_clocks` / `test_published_valuation_api_blocks_when_current_member_is_missing`. The member API fixture persists synthetic rows and exercises the authenticated consumer endpoint; it does not establish formal publication activation authority, provider capacity or production readiness.

## 2026-09-24 全市场自然刷新范围

同日发布完整性整改：报价、日线、估值和财报的原始事实一旦被任一 PublicationMember 引用，后续同自然键刷新必须追加 `revision_number`，不得改写已冻结行及其获取/知识时间。普通原始查询每个自然键只返回最新修订；财报历史查询先限定真实知识截止时间，再选择范围内的最新修订。正式发布仍按原 fact PK/hash 读取，不因新修订自动替换成员。财报写入仍须通过独立来源证据校验，不得借修订绕过。`data_center.0085` 将四种事实的唯一键扩展为自然键加修订号，部署必须同步全部写入器；已有多个修订时禁止直接逆迁移删除历史版本。SQLite 行为回归不能代替 PostgreSQL 锁竞争及真实发布验收。

全市场任务在每次发布前刷新 A 股资产主数据，并通过 Tushare `daily_basic(trade_date=...)` 单次交易日批量响应确定当日可交易范围。估值市值仍由万元转换为元；响应只能缩小到已登记资产，重复、越界或空身份必须阻断。停牌等未出现在当日估值响应中的登记股票不得伪造当日估值，也不得阻断其他可交易股票发布；任务结果必须发布 `excluded_non_trading_count/codes`。报价、估值、历史价格和最终 Publication 使用同一可交易范围。自然刷新允许新增资产，不因一次外部名单缺失自动停用既有资产；退市清理由显式资产主数据维护流程执行。

自然刷新须分别发布 provider 本次观测范围与持久化后的有效 active 范围。provider 少量漏项在既有 1% 一致性容差内时，保留这些 active 证券并输出完整 `retained_missing_codes`、数量、比例、容差及两套范围哈希；正式刷新仍以持久化后的有效范围作为分母，缺失事实继续按数据集规则阻断或形成明确 scope block。漏项比例按刷新前 active 范围计算，provider 新增代码不得稀释该比例；超过容差时在资产写入前以 `A_SHARE_UNIVERSE_RETAINED_SCOPE_EXCESSIVE` 失败关闭。证券代码不得写死，provider 未观测本身也不构成退市证据。

长任务允许审计授权在运行中追加同身份 successor。只有 authority source、actor、user、tenant、owner、认证/职员状态或 role 改变，或起始授权自身无法覆盖下一写边界时才停止；单纯续期产生的新 content hash 不能中断已获授权且仍在有效期内的刷新。

2026-10-02 全市场同步 RawAudit 血缘：quote sync 成功结果携带精确 RawAudit 身份；quote RawAudit 的 `extra.source_type` 保持 provider config 规范来源。成功 valuation batch 在写入前要求所有返回 fact 具有唯一规范实际来源，并将该来源写入 hash-bound `extra.source_type`；配置路由来源单独写入 hash-bound `extra.provider_source_type`。空批次或失败估值审计可将配置来源写入 `source_type`，但非成功审计不能用于 Publication。full-market publication 只有在 valuation seed 与每个 quote batch 都提供绑定同一 sync identity 的 exact 引用时才能继续，并将引用按 dataset 保留在结果中；估值 staging 使用同步结果携带的实际来源，与 fact 和 RawAudit `source_type` 严格匹配。引用缺失、身份不符、来源不一致或重复都失败关闭；如同步事实已经持久化，结果仍报告实际 `stored` 行数和资产口径覆盖率，同时单独报告失败的 operation，不能把引用不完整的数据发布为 current。

日频估值只提供 `trade_date` 时，将该日期对应的中国大陆市场 15:00 收盘时刻作为 `observed_at`，再转换为 UTC 存储。该时间来自提供方交易日字段与交易所会话边界，不能使用抓取时间替代；Tushare 单股、全市场批量路径以及 AKShare 历史估值路径必须使用同一规则。缺少合法交易日仍失败关闭。

Tushare `daily_basic` 成功返回后，以响应完成 UTC 同时记录本系统首次取得该响应的
`available_at` 与 `fetched_at`，并标记 `availability_basis=response_completed_utc`。该时间只表示
本系统已经取得数据，不宣称是供应商最早披露时间，也不能覆盖上述交易会话 `observed_at`。
缺少这一知识时间的估值保持 `available_at_unverified`，不得进入 current Publication。
Tushare `daily_basic` 的直连传输同时对实际 HTTP response bytes 计算 SHA-256，按
`batch_response_body` 绑定到该批每条估值及稳定 source record id；规范化 DataFrame 或事实行哈希
不能替代该响应体证据。SDK-path 在估值接口上使用同协议的 Data Center 传输以保留这些证据，
其他 SDK 接口的既有路由保持不变。

[Tushare `daily_basic` 官方文档](https://tushare.pro/document/2?doc_id=32)给出的更新窗口为交易日 15:00～17:00。正式收盘的 `observed_at` 仍表示北京时间 15:00；全市场 current Publication 的 17:05 是任务触发时点，默认安排在提供方完整截面窗口之后。`setup_full_market_publications` 的 `--hour/--minute` 是固定按 `Asia/Shanghai` 解释的全市场交易日时刻，人工配置也必须不早于北京时间 17:05；该 Cron 固定使用中国市场时区，不随 Django `TIME_ZONE` 或夏令时变化。独立的财务刷新任务仍使用 Django `TIME_ZONE`。不能通过提前触发把 provider 尚未发布的数据解释成收盘事实。提前人工触发时若当日截面仍为空，必须保持旧 Publication 并返回 `CURRENT_VALUATION_SCOPE_UNAVAILABLE`，不能退回前一日并伪装成当期成功。响应完成时点继续记录为独立的 `available_at` / `fetched_at`。

按需检测与上述“生成当日 current Publication”的周期任务使用不同的目标日选择窗口。交易日北京时间 09:15 前，Tencent 尚未进入当日集合竞价观测窗口，精确返回的仍是上一已完成交易日；此时 full-market producer 可以选择上一已就绪交易日，并继续用事实中的源日期、15:00 收盘时点、完整覆盖和原始响应证据逐项验证。09:15 起至 17:05 前必须在 universe/provider/fact/publication I/O 前以 `CURRENT_MARKET_PROVIDER_WINDOW_NOT_READY` 零写阻断，不能把当日盘中快照重标成昨日数据；17:05 起才选择当日。周末和休市日仍可全天选择最近已就绪交易日。该窗口只增加对昨日不可变截面的清晨检测机会，不改变正式 Cron 的 17:05 触发时点。

显式历史市场事实回填与 current producer 分离。历史入口必须指定早于当前中国日期、且 provider calendar 证明为 open session
的 `target_trade_date`，并冻结该日 target-date universe。它可以追加 quote、valuation、price 事实与 raw audit，但不得请求
financial、不得创建或重建 current Publication，也不得因为历史事实写入成功而改变 decision readiness。结果必须发布
`must_not_use_for_decision=true`、`current_publication_changed=false`；真实 provider 缺行保留在原 requested 分母内并按资产
报告 partial。历史 Tushare valuation identity 只能表示该历史路由，不能改写为 Tencent current valuation identity。

Tushare `daily` 的源字段 `vol` 为手、`amount` 为千元。行情快照和历史日线在进入 Domain 前必须分别转换为股和元；完整收盘行情缺少成交量或成交额时不得物化为可发布日线。真实响应候选门禁必须同时重放 `close`、`vol`、`amount` 并与在线标准化事实逐项相等，原始值或规范值缺失、非有限、负数、单位或倍率不符都必须失败关闭。最终发布门禁从绑定的逐资产 observation 和单位合同原件重新计算，不能只信 `units_verified` 布尔值或只用价格一致性替代成交量与成交额量纲验证。

全市场行情快照必须按 `trade_date` 批量读取 Tushare `daily` 截面，并在有限的最近自然日窗口内寻找每只请求资产的最近完整交易日。禁止按股票逐只调用 `daily`，否则全市场任务会把一次发布放大为数千次外部请求并耗尽时限或配额。候选响应回执相应绑定 `full_market_trade_date` 范围；授权错误必须向任务层传播并形成可见阻断，不能被空列表掩盖。

2026-09-28 全市场快照只按任务/目标交易日预取一次：Application 冻结 provider identity、目标日期、规范化响应行 hash、真实可用的响应 body SHA-256/完成时间和完整 universe hash，再由每个事实写入批次读取该对象中的精确子集。该快照不得进入全局或跨任务缓存；下一任务必须重新向 provider 读取。响应 identity、日期、来源时间不完整或 provider 失败时，不得写 quote fact；不得把部分返回解释成停牌或缩小 current Publication 分母。

### 2026-09-26 当前估值容错与 Tencent 证据

隔离发布预演的合成事实使用目标交易日建立确定性的观测、可用和发布时间线，并通过显式、
时区明确的历史知识截止点读取。普通 current 查询仍使用当前时钟；跨周末超过正式新鲜度
窗口时必须返回 `canonical_publication_stale`。预演不得通过延长正式新鲜度或把执行时间写成
源观测时间来获得成功。

当前估值的 `requested` 始终是运行时冻结的完整 active universe。缺口由 `requested - target_session_succeeded` 动态计算，禁止把某次故障的证券代码、数量或排除结果写入生产规则。只有活动政策 `allow_partial=true`、实际覆盖率达到 `minimum_coverage_ratio`、逐证券原因均为 `valuation_source_data_unavailable` 且 Publication scope block 与事实集合可对账时，合格成员才可形成 `partial` 发布。报价仍要求完整；政策缺失、低于门槛、来源日期不符或证据链不完整继续全局阻断。

全市场完成会话发布必须把本次目标交易日显式绑定到 quote 与 valuation 的 Publication candidate 选择。候选 repository 的 `latest` 结果属于其他交易日时，只能作为本次会话缺口处理，不能用旧事实补足本次覆盖；完整 active universe 仍作为 requested 分母。valuation 自然键中的 `val_date` 必须与 `observed_at` 推导的中国市场日期一致，不一致时失败关闭，禁止选择其中任一日期来掩盖脏事实。目标日筛选后的 valuation 缺口只有在既有版本化 partial 政策和覆盖率门槛同时满足时才能生成 scope block；未声明的额外缺口、低于门槛、未知数据集绑定或保留成员日期不一致均失败关闭并保留旧 Publication。其他未参与本次会话刷新的数据集不得被这个日期绑定隐式过滤。

每个当前估值 scope block 必须保留目标交易日、provider/source、publication run id、policy version 与所属 publication id，并与父 Publication 的日期、来源、运行、政策和确定性 id 一致。内容 hash 纳入 block 的证据字段，但不纳入 publication id（它由内容 hash 确定）；重建、持久化不变性校验和查询 gate 必须按同一规则复算。单证券查询只投影该证券的完整阻断证据，不向用户返回其他证券的 aggregate blocks。

正式估值默认通过 AKShare provider 配置调用 Tencent quote-batch 上游。Provider identity 同时绑定配置行和实际 Tencent 上游，响应 artifact 使用 `tencent_quote_batch.v1`，逐 HTTP 批次记录实际返回证券集合并校验所有批次并集。原始响应字段 30 提供 Asia/Shanghai 来源时间，字段 44/45 的流通/总市值原始单位为亿元，进入 Domain 前按 `100000000` 转换为元；`available_at/fetched_at`、原始 body SHA-256、batch scope 和 source record id 必须保留。S6 离线重放必须从留存 bytes 重新解析这些字段并与在线事实逐项相等，不能套用 Tushare `daily_basic` 的万元单位或交易日收盘替代真实 Tencent 来源时间。

### 2026-09-27 正式价格发布与 Qlib 历史窗口隔离

全市场 current `equity.price.bar` 发布只对目标完成交易日执行批量预取和逐证券当前验证；逐证券读取必须复用这次单会话预取缓存。只有目标日缺行或明确不可用的证券才进入 120 日历史读取，以便既有 Data Center 路由验证来源一致性及逐日全日停牌证据。精确目标日停牌证据以外的缺失、过期、跨源冲突、权限或额度错误继续失败关闭。Qlib 特征构建仍可使用其历史窗口；该窗口不应扩大正式 Publication 的全市场 provider 请求。

全市场 current `equity.quote.snapshot` 对停牌采用 requested/eligible 双范围。requested 永远是本次
冻结的完整 active universe；eligible 只能由本次 quote 缺口与目标交易日全天停牌证据的精确交集
推导，不能来自静态名单、数量阈值或旧行情。Publication 保留 requested 全分母，要求
`selected == eligible`，并为每个 `requested - eligible` 成员写入
`quote_full_day_suspension` scope block；政策的 minimum coverage 数值和 `allow_partial` 不变，
策略校验按 eligible coverage 验证为 100%。单证券读取命中 block 时返回该证券的目标日与证据来源，
其余成员继续服务；任何未证实缺口仍全局阻断并保留旧 Publication。

目标交易日相同并不足以证明报价属于已完成交易会话。正式 quote 预取和全量容量预演都必须验证
`snapshot_at >= cn_market_session_close_utc(target_trade_date)`；北京时间 14:55 等同日盘中观测不得计入
收盘覆盖，也不得因任务在 15:00 以后执行而被重新解释为收盘行情。全局 readiness 对已核验停牌缺口
复用同一版本化政策验证：持久化成员、事实内容哈希、Publication 哈希/派生 ID、scope block 或时间证据
不一致时仍全局阻断；证据完整时只对停牌
证券保留局部说明，其他 eligible 证券继续可用。

该 15:00 完成会话门适用于正式全市场 current Publication rebuild。盘中报价的
`PublishQuoteSnapshotBatchUseCase` 是独立盘中候选持久化路径，可在收盘前形成 PUBLISHED 对象；
仅有该对象不证明 `current` 指针已经激活。消费者仍须通过当前指针、活动政策和完整内容校验。
正式盘中激活及其审计/回滚验收尚不能由候选持久化测试代替。

2026-09-29 全市场 point-in-time universe 契约：active universe 同步报告保留当前候选全集的原始 count/hash；正式全市场刷新和 S6 容量预演按同一目标日解析器派生 requested scope，并分别记录候选全集、目标日 requested、明确排除及未知上市日期的 count/hash。只有 `AssetMaster.list_date` 带有 `list_date_evidence_status=verified` 和非空 `list_date_source`，且日期晚于目标日时，才可作为 `not_yet_listed` 排除；等于目标日应纳入。无来源的历史日期、冲突/未知元数据以及普通 provider 缺行均继续留在 requested scope，provider 缺行不能充当未上市证据。Tushare `stock_basic.list_date` 为主证据；明显无效的 `19700101` 由 `new_share.issue_date` 交叉补正，其中 `issue_date` 表示上市日，`ipo_date` 表示申购日。AKShare 未提供日期时必须保留 AssetMaster 已有日期和来源元数据；元数据补充失败不得破坏当前 active membership 同步，但没有可验证排除证据的目标日缺口仍应阻断。

2026-10-05 全市场刷新互斥：人工和 Beat 入口共用同一个
`data_center.refresh_full_market_publications` task-wide fail-fast lease。重复运行在 provider、事实写入和
Publication 之前返回带稳定业务码的零写入 `noop`；cache lease 不可用时 fail closed 为零写入 `blocked`。
正常及异常结束释放匹配 owner 的 lease，进程崩溃由 6,000 秒有界 TTL 自动恢复。现有 5,700 秒 task hard
limit 与 6,300 秒 authority window 保持原值；TTL 必须严格大于 hard limit 且小于 authority window。
该 lease 只协调这一全市场 task 的多个入口，不改变 freshness、coverage、audit、lineage 或 publication 门槛。

### 2026-10-16 精确发布报价读取

`apps.data_center.application.public.get_execution_quote` 通过既有 Publication snapshot 上下文读取
活动 `equity.quote.snapshot/execution` 指针的精确成员及事实，不以证券的最新未发布事实补缺，
不回退到日终研究使用的 `current` 指针。
返回持久化 Decimal、源 `snapshot_at`、`fetched_at`、Publication/成员哈希、政策身份和查询截止点；
已完成会话豁免不能延长此入口的 `snapshot_at + DatasetContract.execution_freshness_seconds`。
缺指针、政策、成员、源证据、哈希不一致、未来或过期数据均失败关闭，原政策阻断原因保留。

执行 TTL 是 DatasetContract 的独立可空配置，没有业务默认值；缺值拒绝读取。
结果携带合同/schema 版本和 `current_active_not_point_in_time`，明确合同读取为当前配置，
不是历史合同或指针回放。配置和读取的组件复核尚在进行，未因此获得发布或执行验收。
空买卖盘表示 UNKNOWN，不能解释为明确无报价；QMT bridge 的自报可用标记不能授予来源可信性。
本入口不证明交易日、停复牌、板块、交易阶段、涨跌幅边界或账户权限，也不激活指针或授权下单。
公开契约和测试边界见 [精确报价读取](../api/a-share-execution-quote-read.md)。

### 2026-10-16 本地账户可卖数量投影

`simulated_trading.application.query_services.get_account_execution_projection` 保留本地账本的
`available_quantity`，不得由总持仓 `quantity` 推定。缺失、负数、非有限值、可卖量超过总量、
或旧 float 输出无法精确往返的数量使整个投影不可用，账户和用户范围继续校验。
该旧投影没有券商源时钟、结算批次完整性或委托预留证明；不得将查询时刻补成源时间，
也不得直接将它升级为 v2 `SellPositionEvidence`。对应机器 surface 只登记这项有限的保真修复。

### 2026-10-16 V3 结算配置的知识截止点

`risk_center.application.execution_settlement_v3.ReadEffectiveExecutionSettlementV3UseCase`
读取同一规则表中的 V3 配置包和原始数据库 `recorded_at`。这个配置目录具有显式系统知识截止点，
不同于执行报价当前活动 Dataset Contract 的 `current_active_not_point_in_time` 语义。
V3 外层身份、交集有效窗和最晚来源可获得时间必须与持久化查询列一致；不能用嵌套 V1 的较宽窗口。
`recorded_at`、所有来源可获得时间及最新来源观测均不得晚于 `as_of`；最早和最新观测分别保留，
不能以较新字段掩盖旧来源。所有来源在包失效前仍不可获得的组合必须在构造或导入时拒绝。

缺记录发布 unavailable，类型、范围、hash 或时间不一致失败关闭；V1/V2 读取遇到 V3 不自动降级。
退役在本系统已知且生效后才影响读取，恢复使用新包版本。该合同只验证来源绑定的规则配置，
不证明市场事实新鲜、交易日历完整或股份已结算，也不解除研究或正式执行门禁。
字段与验收边界见 [V3 结算参数合同](../api/a-share-execution-settlement-v3.md)。

### 2026-10-16 日历响应 TTL 与证券来源时间

日历 `calendar_response_max_age_seconds` 是独立的可空版本化配置，不继承 execution TTL 或研究 freshness；同一 Dataset Contract 版本不能原地补值或改值。纯日历发布窗口从原响应 `first_seen_at` 计算 expiry，新发布时间不能刷新旧响应；首次发布和前向 supersede 使用半开窗，rollback/reinstatement 尚无可读取合同。该窗口本身不证明正式发布或操作权限。详见[日历响应有效期](../api/a-share-calendar-response-age.md)。

证券 `stock_basic` 来源保留精确请求、完整代码、上市/退市日期和 RawAudit occurrence。供应商未提供的 `source_observed_at/source_available_at` 保持 None，不能从响应完成、入库或调用时间补齐。来源候选固定发布禁止决策与执行标记；名录状态不能替代盘中交易状态，也不能作为历史全量 PIT 名录。每次实际响应单独绑定数据库生成的 RawAudit ID，同 body 去重不允许合并调用身份。详见[证券名录来源合同](../api/a-share-instrument-reference-source.md)。

### 2026-10-17 正式日历内部 current 仓储

`data_center.formal_calendar_current_pointer_contract` 扩展到正式仓储：仅接受完整 current pointer，缺 pointer 但存在任意历史发布行时失败关闭。RawPayload dataset 必须与 seal dataset 完全相同；源响应 TTL 不因发布或重放刷新，post-Audit 再验 lease、单调时钟和半开 TTL。向前替换允许旧响应已过期，但必须核验旧 current 的精确 Audit event/outbox，且新来源仍新鲜；普通 current 参考读取不依赖旧发布人的当前授权。

目录 SHARE fence 后先锁 RawPayload、再锁 snapshot 与发布记录；只加入调用方唯一外层事务，不开启嵌套事务。PostgreSQL 要求 READ COMMITTED，SQLite 使用无新增行的写保留。内部原生 PostgreSQL 验证不代表已提供 HTTP/TUI 发布入口、已切换模拟消费者或已取得执行授权；`must_not_execute` 仍为 true。详细边界见 `docs/api/a-share-formal-calendar-publication.md` 和实施计划 19.28。

2026-10-18 仓储职责提取保留原公开 facade；同 App 的 support、writer、reader 承载原有校验、发布与读取方法。上述 current 合同的七项源码标记按实际定义位置迁移登记，并增加 facade 继承绑定检查；原测试要求、源时间、TTL、同一 alias／外层事务及 Audit/outbox 完整性语义不变。

### 2026-10-17 日历操作与精确准备

内部 preview/confirm 通过精确引用重建持久来源、实际事实摘要和活动目录，服务器提供知识截止点；确认不接受客户端时钟或 seal。原确认只可重试同 hash/activation 的当前赢家，原 CAS 范围仍须相符；无密钥 preview checksum 不授予权限。源过期和同版本 TTL 漂移均阻断，重试不刷新源时间。普通 current read 必须绑定 dataset/exchange 和服务器截止点。

精确准备加入唯一外层事务并核验旧 current 的完整 Audit 对，不写入或修补业务记录。HTTP/TUI、实际采集配置与消费者仍需独立验收，详见 [日历操作合同](../api/a-share-calendar-operations.md)。

### 2026-10-17 配置驱动日历采集

显式日历数据集必须只有一个活动合同版本；同数据集的空 TTL 活动版本仍参与歧义判断，不能先过滤后误认为唯一。选定配置的原始创建/更新时间不得晚于服务器知识截止点。采集持有四张目录表的事务 fence，保存原响应完成与入库时钟；来源未提供的观测/可获得时间继续为空，采集不授予发布、决策或执行权限。

现有适配器只支持 default alias、单个活动 Tushare 配置及显式 validator，中央密钥一致性校验不证明线性化密钥轮换，也没有第二个合格日历供应商。见[采集配置合同](../api/a-share-calendar-capture-configuration.md)。

### 2026-10-17 日历 Session HTTP 参考读取

四步 JSON 接口保留原响应完成/入库时钟，未知的上游观测及可获得时间继续为 null；正式 current 仅为参考，仍发布稳定阻断原因及禁止决策/执行标记。current 使用服务器截止点，拒绝客户端 as_of；已认证用户不因原发布人撤权而失去只读完整性核验。

采集、预览、确认各自从真实 Session+CSRF 请求取得主体并重验当前发布权限。机器回显原目录 TTL、完整 CAS 与预览摘要；同版本漂移、过期或旧 pointer 均阻断，不刷新旧源年龄。真实 HTTP 组件不代表浏览器/TUI、Provider 或生产资格。见[日历 HTTP 合同](../api/a-share-calendar-http.md)。

## Calendar 工作台的配置驱动 current 参考读取

工作台 current 入口只接受一个明确 exchange，按服务器唯一有效配置选出 dataset，再调用既有 exact-current owner；配置阻断不回退其他 dataset，缺 pointer 不回退历史。配置选择与 current 读取分别拥有自己的 default 外层事务，二者不宣称跨读取的同一数据库快照。此查询是配置驱动的只读显示；旧显式 dataset 查询仍可用于原范围。

当前合同不能用新配置 TTL 重算旧 publication 的有效期：公开 first_seen 和 response_expires_at 来自原 seal/window，as_of 是服务器核验截止点，不能冒充上游观测时间。未提供的 source_observed_at/source_available_at 保持 null，source_time_status=not_provided；已发布参考一律 must_not_execute=true、must_not_use_for_decision=true、blocked_reason=exchange_calendar_reference_only。未选出配置与没有 current 分别显式 blocked/not_found。登记 data_center.calendar_workbench_current_reference；本段不授予真实 Provider、交易决策或券商资格。

2026-10-20：内部模拟订单预留沿用 `simulated_trading.current_reference_manual_trade` 的来源资格合同。新预留复用既有身份、Risk V3、FeeV2 与正式日历，并在账户锁下重验；`source_snapshot_at` 仅为本地账本取样时间，不得作为行情观测或可用时钟。同键重放保留原封存证据，不刷新来源；撤单按所有者范围释放本地余量，不读取行情。解码还须将预留数量和限价逐项绑定封存的原始意图，不能以重算后的行内摘要代替该交叉校验。此登记不激活 HTTP、SDK、MCP 或实盘入口。

### 2026-10-23 Legacy automatic stop/take observation prices

Account legacy stop-loss and take-profit checks use `MarketPriceServiceProtocol.get_price_with_metadata`. They accept only a positive finite non-boolean price whose returned asset code exactly matches the requested canonical code, with `freshness=realtime`, `is_fallback=false`, and an aware source `observed_at` no later than the evaluation clock. Historical data, close fallback, missing/naive source clocks, and future observations are unavailable. The Account use cases add no separate age threshold: the default UnifiedPriceService already applies the registered quote freshness contract.

Every check output retains the actual source, source observation time, and freshness and publishes `must_not_use_for_decision=true` and `must_not_execute=true`. Owner notices call it a price observation and show its source time; notification delivery errors remain diagnostics and do not change exit counts. A trailing high-water update uses the source observation time. If the repository reports that update was not accepted, the check is unavailable. The only permitted mutation is the trailing high-water value/time and the ORM's automatic update timestamp; portfolio, position, transactions, and stop-trigger records stay unchanged.

The Celery result publishes normalized business outcomes and nullable denominators. Task Monitor retains the outcome and nullable counts in its business projection, while task metrics record the same normalized outcome label; a transport-level Celery success does not erase a blocked or partial exit result.

### 2026-10-24 统一价格的显式发布资格

统一报价、当前日线收盘及基金净值读取，只接受父发布 `must_not_use_for_decision` 为布尔值 `False`。缺失、null、数字零或空字符串/容器均不能推定为合格；行级标记缺省时继承已合格父发布，若提供则同样必须为布尔值 `False`，不能在重建价格 DTO 时丢弃限制。

公共 latest quote 对未知资格返回 `publication_eligibility_unverified`；已有非空阻断原因优先保留，阻断结果不提供价格或伪造源观测时间；已知新鲜度与资格分别保留，`is_stale` 缺证据时保持 null，不能因为资格未知就声称数据陈旧。不合格报价可继续尝试独立合格且满足原新鲜度要求的收盘回退，逐资产判定不影响其他资产。全部候选不合格时沿用 `PRICE_UNAVAILABLE`。历史读取、执行专用报价和 Provider/发布授权合同保持原范围。

### 2026-10-24 Realtime Top Movers monitor-scope failure

Top Movers 的完整监控分母由持仓、关注池和活跃订阅共同解析。任一来源查询失败时，缓存读取必须停止并返回 `outcome=blocked`、`must_not_use_for_decision=true`、`blocked_reason=monitored_price_scope_unavailable`；`requested`、`qualified`、`unavailable` 保持 null，不能用剩余来源或缓存行缩小分母。HTTP 以 503 表达范围暂不可用；成功解析出的空范围与查询失败保持区分。轮询任务继续走既有失败结果合同。

Top Movers 的 `requested` 表示完整监控资产数，`qualified` 表示范围内有 fresh cached price 的资产数，`unavailable` 表示范围内没有 fresh cached price 的资产数；`rankable/unrankable` 表示这些 fresh prices 中 `change_pct` 为有限、可解析数值与不可排序的数量。缺失、NaN、无限值、溢出数值和布尔值不能按 0 排序，也不能把价格标成 stale；它们只降低 Top Movers 的排名指标资格。返回列表按有限 change percentage 排序，`limit` 只限制结果行数，不缩小任何完整范围计数。未知范围时两组计数都保持 null。

Authenticated SDK 的 `get_top_movers_payload()` 和 governed MCP `realtime.read.top_movers` 保留 `results/count`、fresh-price 分母、排名资格计数、freshness/reliability、`outcome`、阻断原因与决策限制；MCP 保留兼容别名 `movers/total_count`。SDK 与 Application 裸列表方法仅在分母完整、价格全部 fresh、排名指标全部可用且明确允许决策时返回；HTTP 200 的 partial/blocked/未知资格由 `AgomTradeProAPIError.response` 保留原始合同，范围不可解析的 HTTP 503 继续由 `ServerError.response` 保留。它们不得把未知数量转换为零。

### 2026-10-24 Published quote change percentage evidence

`equity.quote.snapshot` Dataset Contract 2.0 adds nullable `change_pct` in canonical `percent` units. Its field may carry typed `source_contracts` configured through the existing Data Center catalog initializer. Each source rule must identify the provider field and origin, source and canonical units, exact integer scaling, reference session, and corporate-action basis. The shipped catalog intentionally contains no eligible source rule until those meanings are verified; an unconfigured or mismatched vendor field stays null. The quote sync path never computes this metric from `current_price` and `prev_close` and never fills a missing value with zero. An explicitly reported numeric zero remains a real value.

An operator may configure a reviewed rule in the optional `source_contracts` array on the `change_pct` field in `governance/dataset_contracts.json`, then load it through `initialize_data_center_catalog`. The initializer validates the typed source contract, and `DatasetContractRepository` rejects any quote DatasetContract semantic change under the same DatasetKey version, including field policy and source rule changes. The Dataset Contract admin remains read-only; no rule is enabled by default.

Qualified evidence retains the raw source value, source-rule content hash, exact Dataset Contract key/versions, source quote identity, and source observation time alongside the canonical Decimal. The quote model stores the nullable value at Decimal(38, 12); values that cannot round-trip exactly or exceed that column remain null. Existing rows are not backfilled or reinterpreted. New quote rows record the active Dataset Contract version even when the metric is absent; existing rows keep their persisted version. Tushare quote response hashes and row IDs flow from the witnessed response through `QuoteSnapshot.extra` into the existing ORM identity columns, so publication references can keep the raw-body hash precedence and exact batch scope after a database round-trip.

Quote fallback payload hashing keeps the exact v1 field set when `change_pct` is null. A non-null metric uses the explicit quote v2 fallback codec, including the value and complete source evidence; the raw vendor-body hash retains its existing precedence. Canonical row hashing likewise uses the frozen legacy quote field set for null metrics and the v2 concrete row, including evidence, for qualified metrics. The p2 publication member binds that row digest. A published row is never edited in place: a changed value or source rule creates a successor revision, while the old row and receipt keep their original bytes.

The p1 publication digest deliberately keeps its original member codec and does not bind `fact_content_hash`, even when a member has a raw provider-body hash. The public quote read therefore preserves the price fields but clears `change_pct` and its source evidence unless the gate's policy identity is p2. This prevents a self-consistent p1 member from presenting a later-added metric as sealed ranking evidence.

Realtime quote caching rechecks the current publication's asset, price, source, observation and fetch times, metric value, Dataset Contract versions, and evidence hash. A quote may remain price-fresh with a null/unrankable metric; a cached non-null metric is accepted only when it exactly matches the current published evidence. Daily bars continue to carry no quote change percentage. This contract adds no provider activation or production qualification; provider unit, session, and adjustment semantics remain unknown until individually reviewed and configured.

The `change_pct` normalizer also limits canonical values to at most 15 significant decimal digits after exact scaling, as a conservative bound for SQLite's numeric precision. Values beyond it remain null instead of being rounded. The ORM acceptance test covers zero, sub-cent precision, and a 12-digit integer part with fractional digits; a 16-significant-digit input is rejected before persistence. The candidate still requires the real database round-trip check before adoption.

### 2026-10-24 Realtime cached-value object qualification

当前缓存读取逐对象核验发布身份、来源、数值和观测时间。同一证券代码的一条记录合格，不能使另一条值、发布身份或来源凭据不同的记录合格；显式 external-provider 记录也不能使同代码的未知来源记录合格。过滤后保留合格输入对象的原顺序。

发布 quote 的非空 `change_pct` 只有在当前重读的同一发布行、Dataset Contract 版本、供应商原始值、不可变源规则证据和观测时点都与缓存一致时才可沿用；缺少或不匹配的证据保持价格可用但指标未知。旧 quote 缓存的非空 change/change_pct 没有这条证明时必须拒绝，包括零值。日线 bar 仍只接受 `change_pct=None`。显式 external-provider 的原有缓存合同保持独立。

### 2026-10-27 Exact daily price response retention

受审计价格同步的 `execute_exact_daily` 仅允许一个已配置且启用的 Tushare provider、一个规范证券代码和一个明确交易日。调用前核验历史价格能力、同次响应捕获能力及原件留存依赖；不允许无原件历史查询回退。返回原件必须成功、完整且仅含该证券该日一行；SDK 表格与原始字节的全部字段语义一致后才规范化价格、成交量和成交额。

原件 RawPayload、同步 identity、价格事实、发布记录和 RawAudit 在同一数据库事务中提交；留存引用的 provider、dataset、body hash/size、响应完成时间、transport 和 run 必须相同。RawAudit 保存原件哈希及引用，事实通过既有 ingested_run_id 关联；不将这条审计关联冒充事实自身 raw_payload_hash 的直接原件绑定。任一参与者失败均回滚。bar_date 保留真实交易日，fetched_at 使用响应完成时间，发布 observed_at 沿用正式市场收盘时刻；本入口不会自动激活发布指针，也不授予历史价格实时或执行资格。

### 2026-10-27 Published price knowledge cutoff

公开 Application 的已发布价格序列读取可接受显式、带时区的 `knowledge_cutoff`，并将其同时用于既有发布证据资格与 freshness 计算；缺省时保持原服务器时钟和调用形态。该参数只核验当前指针所选发布是否在截止点已知，不解析或回退到历史指针。未来发布、未来成员证据、无效截止点或受阻发布不能触发原始事实回退；通过后仍只读取同一快照内绑定的成员主键，并保留既有行情字段和序列顺序。HTTP 请求没有新增任意截止点或发布键入口。
