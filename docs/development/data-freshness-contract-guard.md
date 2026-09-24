# 当前数据新鲜度契约与 CI 门禁

## 目标

2026-09-19 补充：模型原始行情参考必须排除前复权/后复权记录；网关复权标记和成交量单位应传递至 canonical 存储，不能以 none 默认值掩盖调整口径。Alpha 定时入口遇到明确数据阻断应停止投递子推理。旧库错标记录不随代码自动改写。

所有带有 `current`、`latest`、`realtime`、`summary` 语义的数据面，都必须证明“源数据仍在允许的新鲜度窗口内”，不能仅因为数据库查询返回了最新一行就宣称数据当前可用。

机器真源为 `governance/current_data_contracts.json`，自动检查入口为：

```bash
python scripts/check_current_data_contracts.py
pytest tests/unit/ci/test_check_current_data_contracts.py -q
```

该检查已接入 `.github/workflows/consistency-check.yml`。

## 五条不可破坏的语义

Alpha Qlib 推理缓存必须按 `asof_date` 核对请求交易日；旧源日期仅可写为
`degraded`，发布 `must_not_use_for_decision=true` 和 `qlib_source_data_stale`，
并跳过下游推荐刷新。每日行情额度耗尽直接返回阻断且零写入，不改变旧评分时间。

1. **排序最新不等于当前可用**：`get_latest()` 之后必须执行 freshness/reliability 判断。
2. **源观测时间不可变**：`snapshot_at`、`observed_at`、`bar_date`、`as_of` 必须来自源数据；不得用请求时间或计算时间覆盖。
3. **过期结果不能截断 failover**：provider 返回非空但已过期时，组合数据源必须继续尝试后续来源。
4. **降级必须显式**：历史收盘、代理值和不完整数据必须发布明确的 freshness/source/fallback 状态。
5. **决策输出必须失败关闭**：数据不可靠时发布 `must_not_use_for_decision=true` 和稳定的 `blocked_reason`，不得继续生成确定性建议。

日频 A 股 quote/price/valuation 的自然小时预算到期后，只允许在所有 Publication member 都精确绑定最近已收盘交易日时标记为 `latest_completed_session`；quote 只在盘后、开盘前或休市日沿用最近已收盘交易日，新的交易时段一旦完成便必须重新发布。这不会改变源观测时间。全市场 current Publication 必须按冻结 universe 原子发布，单标的或中间批次同步只写 fact，不得缩小既有 current member 集合。

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

## 2026-09-24 全市场自然刷新范围

同日发布完整性整改：报价、日线、估值和财报的原始事实一旦被任一 PublicationMember 引用，后续同自然键刷新必须追加 `revision_number`，不得改写已冻结行及其获取/知识时间。普通原始查询每个自然键只返回最新修订；财报历史查询先限定真实知识截止时间，再选择范围内的最新修订。正式发布仍按原 fact PK/hash 读取，不因新修订自动替换成员。财报写入仍须通过独立来源证据校验，不得借修订绕过。`data_center.0085` 将四种事实的唯一键扩展为自然键加修订号，部署必须同步全部写入器；已有多个修订时禁止直接逆迁移删除历史版本。SQLite 行为回归不能代替 PostgreSQL 锁竞争及真实发布验收。

全市场任务在每次发布前刷新 A 股资产主数据，并通过 Tushare `daily_basic(trade_date=...)` 单次交易日批量响应确定当日可交易范围。估值市值仍由万元转换为元；响应只能缩小到已登记资产，重复、越界或空身份必须阻断。停牌等未出现在当日估值响应中的登记股票不得伪造当日估值，也不得阻断其他可交易股票发布；任务结果必须发布 `excluded_non_trading_count/codes`。报价、估值、历史价格和最终 Publication 使用同一可交易范围。自然刷新允许新增资产，不因一次外部名单缺失自动停用既有资产；退市清理由显式资产主数据维护流程执行。

长任务允许审计授权在运行中追加同身份 successor。只有 authority source、actor、user、tenant、owner、认证/职员状态或 role 改变，或起始授权自身无法覆盖下一写边界时才停止；单纯续期产生的新 content hash 不能中断已获授权且仍在有效期内的刷新。

日频估值只提供 `trade_date` 时，将该日期对应的中国大陆市场 15:00 收盘时刻作为 `observed_at`，再转换为 UTC 存储。该时间来自提供方交易日字段与交易所会话边界，不能使用抓取时间替代；Tushare 单股、全市场批量路径以及 AKShare 历史估值路径必须使用同一规则。缺少合法交易日仍失败关闭。

Tushare `daily_basic` 成功返回后，以响应完成 UTC 同时记录本系统首次取得该响应的
`available_at` 与 `fetched_at`，并标记 `availability_basis=response_completed_utc`。该时间只表示
本系统已经取得数据，不宣称是供应商最早披露时间，也不能覆盖上述交易会话 `observed_at`。
缺少这一知识时间的估值保持 `available_at_unverified`，不得进入 current Publication。
Tushare `daily_basic` 的直连传输同时对实际 HTTP response bytes 计算 SHA-256，按
`batch_response_body` 绑定到该批每条估值及稳定 source record id；规范化 DataFrame 或事实行哈希
不能替代该响应体证据。SDK-path 在估值接口上使用同协议的 Data Center 传输以保留这些证据，
其他 SDK 接口的既有路由保持不变。

[Tushare `daily_basic` 官方文档](https://tushare.pro/document/2?doc_id=32)给出的更新窗口为交易日 15:00～17:00。全市场自然发布默认安排在 17:05，确保任务确定的最近收盘交易日已有完整估值截面；提前人工触发时若当日截面仍为空，必须保持旧 Publication 并返回 `CURRENT_VALUATION_SCOPE_UNAVAILABLE`，不能退回前一日并伪装成当期成功。
