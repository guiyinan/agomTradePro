# DATA-02 财务真实来源时间整改方案（2026-09-13 拟议）

> 状态：精确来源时间全链仍为拟议；当前 DATA-16 候选已移除两 provider 的日期→午夜
> 合成，新 date-only 抓取保持 available_at=None。本文是后续 DATA-02 代码前置，
> 不代表 DATA-02 生产门通过，也不晋级任何生产 publication 或决策读取。
>
> 实际模型设置：gpt-5.6-luna / max。
>
> 最初 Luna 只读审查没有修改 production/tests 或执行网络、数据库、部署。
> 主代理随后补充候选 guard、测试及官方文档核验；没有执行历史 backfill，也没有
> 据此激活生产 policy 或认定精确来源时间已修复。

## 1. 结论与决定

当前财务数据链路仍不能证明供应商真实的首次可用时刻。审查时两个适配器将公告
日期压成 date 并合成 UTC 午夜；当前候选已删除此合成，available_at 保持 None。
解析器仍不能保留未核验的源日内精度，精确 announced_at 全链尚待实施。
period_end 是财政期末，不能作为
公告时间、PIT 可用时间或历史修复输入。

FinancialFactModel 已有 announced_at 和 available_at 两个独立的 DateTime 列，
但最初审查时（原 6760 实现）的 Domain FinancialFact 没有 announced_at，
repository、兼容 gateway 和 Equity FinancialData 也没有把它贯通；当前候选已通过
source_evidence bridge 保留 Domain↔ORM 的三个 core 字段。response bytes、scope、
completion 和 availability 仍未贯通。现阶段最小安全决定如下：

1. 保留 period_end 的财政期末语义。
2. 贯通一个 typed 的源公告时刻字段（优先使用已有模型 announced_at），并显式
   区分 announced_at、available_at、fetched_at。
3. 源端只有日历日期时，保留日期和 source_time_precision=date 证据，
   available_at 保持 None，不得合成 UTC 午夜，也不得进入要求精确可用时间的
   publication candidate。
4. response_completed_utc 只能证明本系统在该时刻已取得响应。它可以作为
   observed_by_system 的保守上界证据，但不能冒充供应商首次披露时间或历史
   announced_at。只有新的 dataset contract 明确接受该上界时，才可在新抓取中
   使用；不能借此改写历史行。
5. backfill_available_at_from_report_date 的 Cast(date → datetime) 不是来源
   修复方案。已有合成午夜值必须标记为 provenance degraded/unverified，不能升级
   为真实源时间。

## 2. 已读真源与硬证据

| 真源 | 当前事实 | 影响 |
| --- | --- | --- |
| [FinancialFactModel](../../apps/data_center/infrastructure/models.py:828) | period_end、report_date 是 DateField；announced_at、available_at 是可空 DateTimeField。report_date 的 help text 仍称 published date。 | 模型有目标存储列，但 report_date 名称和历史使用方式不足以表达精确时间。 |
| [Domain FinancialFact](../../apps/data_center/domain/entities.py:570) | 最初审查时（原 6760 实现）只有 report_date: date、available_at 和 fetched_at，没有 announced_at；当前候选通过 source_evidence bridge 增加三个 core 字段的 typed 往返。 | 原 ORM → Domain 边界会丢失 announced_at；当前候选保留 announced_at/source_record_id/raw_payload_hash，但不声称覆盖 response bytes/scope/completion/availability。 |
| [FinancialFactRepository](../../apps/data_center/infrastructure/financial_fact_repository.py:24) | 最初审查时（原 6760 实现）_from_model 只读取 report_date/available_at；当前候选通过 source_evidence bridge 读写三个 core 字段，bulk_upsert 仍独立处理 available_at/extra。 | 原 sync 不能保存或回读 announced_at；当前候选完成三字段 carrier，严格 policy3 所需的 response lineage 仍未实现。 |
| [_safe_date](../../apps/data_center/infrastructure/_provider_adapter_base.py:134) | datetime 调 .date()；字符串只取前 10 位。 | 2026-03-31 15:30:00 会变成 2026-03-31；源日内精度不可逆。 |
| [Tushare financial adapter](../../apps/data_center/infrastructure/_provider_adapter_tushare.py:174) | ann_date/announced_date 经 _safe_date 进入 report_date；当前候选已删除午夜 helper，native 与 compatibility 均保持 available_at=None。compatibility 仍只有 period-like report_date。 | 已阻止新合成；尚无 exact source evidence，也未修复历史时间。 |
| [AKShare financial adapter](../../apps/data_center/infrastructure/_provider_adapter_akshare.py) | REPORT_DATE/报告期进入 period_end；NOTICE_DATE/公告日期/公告日进入 report_date，当前候选保持 available_at=None。 | 已停止合成午夜；公告日内精度和原始财务响应证据仍需贯通。 |
| [Equity financial gateway](../../apps/equity/infrastructure/financial_source_gateway.py:18) | FinancialRecord 只有一个 report_date: date；按 anchor.report_date or period_end 生成，丢掉独立的 period_end、available_at 和公告时刻。 | 兼容投影会把两个日期语义压成一个字段；Tushare 兼容 builder 随后把它当 period_end。 |
| [Equity writer](../../apps/equity/infrastructure/fundamentals_write_repository.py:163) | FinancialData.report_date 同时被写为 period_end 和 report_date，不写 available_at/announced_at。 | Legacy DTO 写回 canonical 时可能把报告期、公告日再次混淆并丢 availability。 |
| [Equity reader](../../apps/equity/infrastructure/fundamentals_repository.py:409) | 从 canonical row 暂时读取 available_at，但 _financial_data_from_facts 只向 FinancialData 传递 report_date/fetched_at。 | canonical → Equity DTO 再次丢失 available_at。 |
| [Publication evidence](../../apps/data_center/infrastructure/publication_fact_evidence.py:62) | source_published_at 读取 ORM 的 published_at；财务模型没有该字段，也没有读取 announced_at。 | 财务源公告证据无法进入 publication member evidence。 |
| [Financial availability repair](../../apps/data_center/infrastructure/financial_availability_repository.py) | 候选已关闭原有 Cast 日期补时写入；保留只读日期盘点。 | Application 与直接 Repository 入口均以 FINANCIAL_SOURCE_TIMESTAMP_REQUIRED 阻断日期补时，不修改历史行。 |

现有 [financial publication candidate](../../apps/data_center/infrastructure/financial_fact_repository.py:97)
已经在 available_at is None 时跳过候选，既有测试也覆盖 missing/future availability
阻断（[test_financial_publication_sync.py](../../tests/unit/data_center/test_financial_publication_sync.py:172)）。
这条 fail-closed 保护应保留，修复范围是来源时间贯通，不是放宽 publication gate。

## 3. 当前端到端路径与精度缺口

native financial sync 的实际路径是：

fina_indicator / stock_financial_analysis_indicator_em
→ provider row
→ _safe_date
→ FinancialFact
→ SyncFinancialUseCase._normalize_fact_sources
→ FinancialFactRepository.bulk_upsert
→ candidate lookup。

_normalize_fact_sources 只改 source 和 extra.source_type/provider_name，不会恢复
被 _safe_date 丢掉的时间。当前两个 financial adapter 也没有像现有 valuation
response path 那样携带 source_record_id、原始响应 bytes hash、payload scope 或
response completion timestamp。

compatibility 路径更严格地暴露了边界：它只有财政期样式的 date 字段；现有测试
test_tushare_unified_provider_adapter_builds_typed_financial_facts 断言这种输入
必须保持 available_at=None，不能把 period_end 当作可用时间。这个行为应继续保留。

AKShare 现有测试
test_akshare_financials_preserve_partial_metrics_and_notice_date 目前断言
NOTICE_DATE=2026-03-31 00:00:00 产生 2026-03-31T00:00:00Z。该断言记录了
当前实现，不构成业务批准；真实字段契约确定后应改为精度明确的断言。Tushare 和
AKShare 当前使用的字段名只能证明代码选择了这些字段，不能证明供应商响应一定提供
日内时间；必须先取得原始 provider payload 或官方字段 contract。

## 4. 文档支持的时间边界

[主架构计划的财务时间语义表](data-center-canonical-architecture-refactor-2026-08-02.md:2124)
明确规定：

- period_end 是事实/财政期末；
- announced_at / available_at 是公告或 PIT 可用时间；
- fetched_at 是抓取时间；
- 禁止用报告期代替披露期；
- date 与 datetime 不混用。

[同一计划的 2026-09-07 历史修复记录](data-center-canonical-architecture-refactor-2026-08-02.md:5182)
明确写明，按既有 report_date 写入
2024-08-16T00:00:00Z “不能宣称取得公告日内时间”。因此没有文档依据把
date-only NOTICE_DATE/ann_date 当作精确 UTC 午夜可用时刻。

[DATA-16 计划](release-blocker-closure-execution-plan-2026-08-29.md:9)
支持保存原始响应完成时间和 exact bytes SHA-256，但同时明确：
响应完成时间只证明本系统此时已经取得响应，不代表供应商最早披露时间。由此可以
定义保守事实 vendor_available_at <= response_completed_utc，但当前财务
available_at 字段不能在未登记精度/依据的情况下直接承载它。对历史重抓，
response completion 是重抓时刻，不是历史首次披露时刻。

## 5. 最小有界实施路线

### Stage 0：先封存字段契约和真实输入

在任何 production code 变更前，取得并固定 Tushare fina_indicator 与 AKShare
stock_financial_analysis_indicator_em 的原始样本/官方字段 contract，至少确认：

- 财政期末字段及其口径：Tushare period_end/end_date、AKShare
  REPORT_DATE/报告期；
- 源公告字段及其粒度：Tushare ann_date 或官方替代字段、AKShare
  NOTICE_DATE/公告日期/公告日 或官方替代字段；
- 是否存在带时分秒的公告 timestamp；若存在，字段名、时区、精度、是否供应商
  声明的首次公开时间；
- 若不存在 timestamp，明确记录 source_time_precision=date，不要猜 vendor
  timezone，也不要把当地日期转换为 UTC 午夜；
- source record id、endpoint、request parameters、raw response bytes/hash、payload
  scope、provider schema/解析版本，以及 response completion UTC。

没有原始 payload 或官方 contract 时，Stage 0 停止，不能进入代码实现或生产修复。

### Stage 1：typed source-time boundary

在 Domain/Application 契约中增加一个 typed 的财务来源时间表示，具体命名可在
实现评审时确定，但必须能表达：

- announced_at: datetime | None：供应商声明的精确公告时刻；
- announcement_date: date | None：供应商只有日期时的原始日历值；
- available_at: datetime | None：经过 dataset contract 认可的 PIT 边界；
- availability_basis 与 source_time_precision；
- observed_by_system_at: datetime | None：本系统取得响应的上界证据；
- source record/raw payload identity。

优先复用模型已有 announced_at 列，贯通 Domain、repository 和 publication
evidence；不要把所有语义塞入未类型化的 extra。fetched_at 继续表示抓取审计
时间，不承担任何来源公告语义。

### Stage 2：provider 与 persistence 保真

1. Tushare 和 AKShare 只在原始字段确实提供精确 timestamp、且 timezone 已由
   contract 固定时，解析为 announced_at；period_end 独立解析。
2. date-only provider row 保留日期和 precision 标记，available_at=None，不调用
   或复用任何 report_date → datetime helper。
3. transport 边界保存 exact response bytes/hash、scope、请求身份和
   response_completed_utc。该时间仅作为 observed upper bound；不能写成
   vendor first availability。
4. _from_model、bulk_upsert、冲突更新字段、FinancialRecord、Equity
   FinancialData 读写映射必须保持 period_end、公告日期/时刻和 availability
   的独立性。兼容 gateway 不得用 anchor.report_date or period_end 代替完整字段。
5. publication_fact_evidence 把已验证的源公告时间投影到 source_published_at，
   同时保留 available_at；缺少 exact availability 时继续 fail closed。Application
   只依赖 typed Protocol/DTO，不能直接 import Infrastructure helper。

### Stage 3：历史真实来源修复

历史修复只能按冻结 universe、精确自然键和有界 batch 进行，每行必须有：

- before image（包括 period_end、report_date、announced_at、available_at、
  fetched_at、source identity/hash/extra）；
- 新 provider raw evidence 与 exact source record；
- 源字段原值、精度、时区和解析版本；
- after image、content hash、publication candidate 变化和独立只读复核。

只有日期的历史行保持 available_at=None，不满足 publication gate；既有 UTC 午夜
合成值不得被当作真实来源或继续扩散。该阶段不是执行现有 backfill 用例，也不是
provider 缺证据时的批量补值。

### Stage 4：publication/production 验收

先在专用测试 fixture 证明 source precision、repository round-trip 和
publication fail-closed，再做获批的有界生产读取/修复。DATA-16 的完成只解除代码
前置，不代表 DATA-02 的财务时间、全 universe source reconciliation 或生产
publication 已完成。

## 6. TDD meaningful tests 与完成标准

应补充或改造下列测试，测试名称可按最终 API 调整，但语义必须保留：

- Tushare native row 含独立 end_date 与带时区公告 timestamp：断言 period_end
  不变、announced_at 精确保留、available_at 只按已登记 basis 产生。
- AKShare native row 含 REPORT_DATE、NOTICE_DATE 和真实 timestamp（若官方
  contract 支持）：断言日期、时刻、timezone 不被 _safe_date 截断。
- Tushare/AKShare date-only row：断言 source_time_precision=date、
  available_at is None，明确不生成 UTC 午夜。
- compatibility FinancialRecord 只有财政期末：断言不会把 period end 当作
  announcement/availability，也不会在 FinancialRecord → FinancialFact 中交换
  period_end 与 report_date。
- model ↔ Domain ↔ repository round-trip：断言 announced_at、available_at、
  fetched_at、raw/source identity 各自保真，bulk conflict update 不遗漏
  announced_at。
- canonical fact ↔ Equity FinancialData round-trip：断言 legacy DTO 不再丢失
  availability；只有日期输入时仍保持 blocked/unknown，而不是写入合成时刻。
- publication evidence：断言 source_published_at 来自已验证的源公告字段；
  缺失、naive、future 或只有日期的 availability 均阻断 candidate/publication。
- transport evidence：断言 raw bytes hash、scope、source record id、
  response completion 被保存；断言 completion 只能标记 observed_by_system，
  不被序列化成 vendor first availability。
- negative regression：源码/调用图中不得由 DATA-02 路径调用
  backfill_available_at_from_report_date，也不得使用 fetched_at 或 period_end
  推导 available_at。

Stage 4 的本地完成标准是：官方字段 contract 和真实 raw sample 可复核；精确时刻
或 date-only 精度被明确标记；四层（provider、Domain/repository、Equity 兼容、
publication evidence）无丢失或字段互换；既有 candidate missing/future guard 仍通过；
完整 before/after 与 raw evidence 可重放；没有新增单位、资产规则或猜测时区。

## 7. 真实生产输入、停止、回滚和验收边界

生产动作前必须具备：

- DATA-16 完成后的候选代码、部署身份和现有 publication identity；
- Tushare/AKShare 官方字段 contract 或不可变原始 payload；
- provider endpoint、请求参数、source record id、raw body/hash/scope、
  response completion UTC、公告 timestamp/date 原值、timezone 和 precision；
- 冻结的 universe/natural-key 范围、batch 上限、before-image 保存位置和独立
  postflight 方式；
- DATA-02 既有 owner/reviewer、publication policy 与 stop/rollback 记录。

立即停止于以下任一条件：字段 contract 缺失或变化、公告时区未知、timestamp 被
解析器截断、source record/raw hash 缺失、同一自然键对应多个源事实、只有日期却
要求精确 available_at、before image 不完整、candidate/publication identity
漂移，或任何步骤试图以 report_date/period_end/fetched_at 补值。

回滚必须回到 DATA-16 完成后的已验证且兼容当前 policy/evidence 的代码候选；
`b18b18029f90af4b23693426a1f489af44ffe2b2` 仅能在 p2 policy 激活前作为既有代码
回滚点。激活 p2 后不得未经兼容性证明自动回退到 b18；不能逆迁移删除 additive
evidence schema。任何已写入的 DATA-02 行只能依据该次 run 的精确
before image 和 source identity 有界恢复，不能用 report date 重新构造时间，也不能
全表清空或重跑未经证据支持的 backfill。

生产验收需要同时证明：原始来源字段与精度可审计；exact timestamp（或明确的
date-only blocked 结果）贯通四层；新 publication 只含 evidence-safe members；
缺证据的范围仍 must_not_use_for_decision；existing publication identity、事实
值、natural key 和非目标行无漂移；独立只读 postflight 与重跑均符合预期。未满足
这些条件时，DATA-02 保持 awaiting production，不能因代码测试、合成午夜值或
response completion 上界而关闭。

## 8. 本次核对范围

本次只读检查覆盖 FinancialFact model/migration、Data Center Domain entity/protocol、
Tushare/AKShare unified financial adapters/base date parser、FinancialFact repository、
availability repair mixin、Equity financial gateway/reader/writer、publication evidence、
sync/publication use cases 及既有 adapter/publication tests。最初 Luna 审查未执行测试、provider refresh、
backfill、数据库读取/写入、部署或网络请求；后续主代理候选修复单独见下节。

## 9. 当前候选 guard 与官方字段核验

主代理在 DATA-16 source-witness 范围内删除 Tushare/AKShare 的
`_available_at_from_report_date`；只保留公告日和财政期末，available_at=None。
四个有意义的 provider 反例先红（实际得到合成午夜），修复后整个 adapter 测试文件
39 passed。同类历史修复入口也已关闭 Cast 日期补时：只读盘点不再把日期缺口标记为
可执行补时；Application 和直接 Repository 写入口均拒绝合成时间，零写入；发布
主流程在财务来源时间缺失时必须停止。对应回归先红（5 failed），随后已有 16 项
回归 XML 为零失败、零错误。未知报告日期反例随后先红（1 failed），关闭该放行
路径后日期/未知时间与发布主流程共 18 passed；该阶段冻结版本的完整集成回归为
2031 passed /16 skipped，Domain 选定范围为 2930 passed、聚合行覆盖率 94.17%。
跳过的 PostgreSQL 用例需要独立证据；策略激活四项另已在实际 PostgreSQL 通过，
独立只读检查确认 public base tables=0。这些结果不是后续来源凭证修复的测试证明。
此 guard 没有更新历史行；没有实现 typed
announced_at round-trip、原始财务响应 hash 或精确来源时区，也未部署验收。

2026-09-13 官方文档核验：Tushare 的 fina_indicator 分开定义公告日期与报告期，
样例公告字段只含年月日，没有提供可据此推导日内时间或时区的契约。
[官方财务指标文档](https://tushare.pro/document/2?doc_id=79)。
AKShare 的该接口定义 REPORT_DATE 为报告日期，公开字段表没有保证 NOTICE_DATE
的精确日内来源时间或时区；这不能作为 available_at 的充分证据。
[官方主要指标文档](https://akshare.akfamily.xyz/data/stock/stock.html)。
这次核验解除“可否用日期合成午夜”的疑问；生产原始 payload、不可变字段契约和
精确公告来源仍须按 Stage 0 收集，不能因官方页面可访问而认定已经齐备。

## 10. 历史合成时间的来源凭证缺口

2026-09-13 Luna max 只读审计确认：旧 calendar backfill 已写入的非空午夜
available_at 不会被当前缺失值 guard 拦截。Financial policy2 仅要求 payload_hash，
旧 identity 的 normalized-row hash 和 natural-key fallback 可以满足该要求；
announced_at 为空、raw hash/scope 和 source_record_id 缺失时仍可能通过。
冻结 member 的真实行 SHA 只能证明行内容，不能证明该时间或哈希来自供应商。

当前候选仅将 financial policy 的独立版本推进到3，保留既有六项并追加
source_record_id、published_at、raw_payload_hash、raw_payload_scope；其余九个
dataset 配置不变。manifest 回归先红（1 failed），随后与已有不可变策略版本
回归共5 passed。旧 policy2 及历史行不改写；激活新 identity 后旧 current 由现有
publication_policy_changed 门阻断。金融 ORM 来源边界已分类提交 `52abce5a2`，
严格读取持久化 announced_at/available_at/fetched_at、source record、raw hash/scope，
拒绝缺失及时间逆序；旧 policy2 的历史编码保持原有语义。来源和实际 current 读取到
持久化 member 回放的专项最终回归13 passed，53个生产文件增量mypy无新增错误，
全量mypy债务为零；该阶段完整选定集成2045 passed /16 PG opt-in skipped，
[来源校验阶段证据](../testing/data16-financial-source-validation-2026-09-13.json)绑定
`52abce5a2`。独立审查随后发现纯Domain集中校验未检查公告晚于可用时间；
`990a4876e` 在两字段均存在时补顺序检查，等时及旧策略缺字段兼容保留。
真实RED为1 failed/2 passed，修复后专项3 passed、完整证据文件20 passed；
受影响发布/current随后155 passed，官方Domain选定范围2939 passed、聚合行覆盖率
94.18%；最终追加版本16项静态门禁全部通过，增量mypy53生产文件无新增错误，
全量债务仍为零。[追加来源顺序证据](../testing/data16-domain-source-chronology-validation-2026-09-13.json)
绑定该源码；精确最终推送候选CI及生产升级/激活仍未完成。这证明字段边界与校验行为，
不证明生产原始响应 bytes、精确来源时刻或可用 current 已齐备。
新候选必须重新绑定准确 Git 字节和真实
生产 preflight，不能继续使用旧 policy2 的 candidate SHA。

2026-09-13T12:01:06.678997Z 实际生产只读聚合盘点：441944条金融事实，
available_at缺失160条；announced_at、原始raw hash、source_record_id和支持的
raw scope均缺失441944条；441784条有available_at却无source announcement。
结构上完整的来源凭证为0。记录仅证明存储字段缺口，不能据此将非空时间都分类为
旧Cast合成值，也不能证明原始供应商时间或current可用性；未修改任何生产行。
[实际只读证据](../deployment/data02-financial-provenance-readonly-2026-09-13.json)。
下一阶段只对经盘点冻结的决策当前universe做有界重新采集，不全表重写历史数据。

后续 DATA-02 历史决策边界另有只读确认的代码缺口：factor adapter
`_get_factor_from_data_center` 调用 `get_financial_facts(..., as_of=trade_date)`，
但该参数经 public_published_queries/query_services 传给 Repository 的 `end` 后，
仅用于 `period_end__lte=end`，没有校验源公告或真实 available_at 的知识截止。
因此财政期末早于回测日不能证明该日已获知报告；此处是代码路径审查，尚未运行
生产或回测反例。下一阶段在 factor 的历史决策入口补精确知识截止与缺证据阻断，
用“期末已到、公告未到”以及 date-only/unknown 来源反例证明无后视偏差；raw 历史
资料读取保留兼容性，不在 DATA-16 中改写既有历史接口语义。

独立只读调用链审查确认 Account AuthorityV3/SourceV2 只恢复 Account 与
simulated_trading 物理账户账本，未依赖 Data Center current publication；因此
financial policy3 的 publication_policy_changed 不会直接使 Account authority
失效。实际 Account current/expiry/ledger 指纹仍须单独复核，不能以调用链审查代替。
收紧来源策略后，默认回滚保持该策略及明确blocked状态，选择兼容的 DATA-16 代码；
不能为了恢复有数据的页面自动重新激活缺乏来源保证的旧 financial policy。

## 11. 2026-09-13 本地单标的真实原始响应样本

2026-09-13 的 Stage 0 供应商响应采集在本地 PC 完成，不是 VPS 请求；采集器没有数据库
读取、摄入或生产写入。scope 来自独立的生产只读查询，绑定 AKShare provider id 3、
单一 A 股 `000001.SZ`；scope
原始 SHA-256 为 `7697fb91f3f321111f79bcfa03fb4dc78b995ed553cc59f7df42e7374008071a`。

采集实际发出 1 次供应商 GET，无 retry、failover 或第二请求；HTTP 状态为 200，请求
参数 `ps=200` 是 SDK 分页大小，供应商响应实际包含 122 个报告行，并未声称服务端只返回
一个报告期。未经改写的 `requests.Response.content` body 为 388061 bytes，SHA-256 为
`6a56f4ccbaa203e689f62a1f14033ed8a61a0c0a842afda03a6c27e5b1054578`，原始 body 保持
在私有 var 工件中，未写入仓库；[只含元数据的封存工件](../deployment/data02-financial-single-source-raw-sample-2026-09-13.json)
及其 `.sha256` sidecar 只绑定这些摘要。

body 中 122 行的 `SECUCODE` 全部为 `000001.SZ`。`NOTICE_DATE` 有 119 个无时区午夜
文本和 3 个 `null`；`REPORT_DATE` 的 122 个值均为无时区午夜文本。样本没有行级
record ID，只有 `SECUCODE`、`SECURITY_CODE`、`ORG_CODE` 资产/组织标识；
`SECURITY_TYPE_CODE` 是分类码。供应商字段形状不能证明精确时区、来源公告瞬时或
独立 source record identity，因此 `announced_at` 和 `available_at` 仍为 `None`。

响应完成时间 `2026-09-13T13:45:24.729792Z` 只表示系统已取得该响应，是系统获取上界，
不能合成为供应商首次披露时间或可用时间。第一次 CLI 尝试在请求前发生 ModuleNotFound，
没有保留原始日志，故不为其伪造 receipt。该样本证明了单次供应商 response bytes 的
可复核 hash 和资产绑定，不构成 DATA-02 生产修复、历史回填、publication 激活或决策
可用性证明。

## 12. 2026-09-13 CNINFO official single-document evidence

本次官方契约核验使用公开 primary 来源：[CNINFO 信息披露页](https://www.cninfo.com.cn/new/commonUrl?url=disclosure/list/notice)、[CNINFO `000001` 年度报告摘要](https://static.cninfo.com.cn/finalpage/2024-03-15/1219306483.PDF)、[深交所上市公司公告页](https://www.szse.cn/disclosure/notice/company/)、[深交所上市公司自律监管指南第 1 号——业务办理](https://docs.static.szse.cn/www/disclosure/notice/general/W020230804631480613363.pdf)、[深交所《上市公司公告电子化规范》等标准公告](https://www.szse.cn/lawrules/csrcrules/notice/t20240802_608465.html)、[JR/T 0021.1—2023 公告分类标准](https://www.sse.com.cn/lawandrules/regulations/csrcannoun/c/10751844/files/c231e94e119145c2ba0c44ecd84dc713.pdf) 和 [JR/T 0021.8—2023 定期报告标准](https://www.sse.com.cn/lawandrules/regulations/csrcannoun/c/10751844/files/7b4b5425e6754b1eb03e13d8e12eea88.pdf)。这些来源支持公告文档身份、公告编号和定期报告类别的核对；标准中的正式公告日期仍为日期粒度，没有给出可直接映射到 UTC 的精确瞬时、时区或首次公开事件语义。

已在本地 PC 对 CNINFO 静态 PDF 发起单次真实 `GET`：HTTP 200、TLS 校验开启、无认证、无代理、无重定向、无重试，取得的 `requests.Response.content` 原始字节为 744555 bytes，SHA-256 为 `90932b0d8a08835f0fa8365b2e06464aec99aa69dd2f1d9d741946aeb2b88993`，系统完成获取时间为 `2026-09-13T14:43:43.386766Z`。这次完成时间只是系统获取上界，不是供应商首次披露时间。原始 PDF 保留在私有 var 工件中；receipt 的原始字节 SHA-256 为 `697bde279518ef4ce4f786c5ac7ab331eaa001a09d0be045eed5e37dd3ceef08`，其 exact bytes 以 gzip+base64 形式封存在[官方单文档 metadata seal](../deployment/data02-official-announcement-single-document-2026-09-13.json)中，仓库不附 PDF、原始 body 或提取文本。

PDF 头部和正文把 `000001`、平安银行、SZSE、公告编号 `2024-017` 与 2023 年度报告摘要绑定到报告期末 `2023-12-31`。文档类别是 `annual_report_summary`；`GB0101` 是年度报告全文类别码，本次摘要没有被冒称为 `GB0101` 全文。正文单位标签为“人民币百万元”“元/股”“%”及分配表中的“元”，没有做单位转换。URL 路径中的 `2024-03-15` 只保留为托管路径日期；PDF 没有可核验的带时区发布瞬时，故 `announced_at`、`available_at` 和 source timezone 仍为 `None`。

`1219306483` 仅是从 PDF URL basename 保留的不透明 CNINFO 文档句柄，不是机器财务行 ID；文档本身没有行级 financial `source_record_id`。前述 EastMoney financial fact 样本与此官方公告文档之间没有共同、可验证的 row-level 绑定，公告编号/文档句柄不能单独填充 EastMoney 行的 `source_record_id` 或精确可用时间。因此本封存仍是 DATA-02 Stage 0 identity evidence，不构成 Fin3 接受、历史回填、publication 激活或现有财务行修复。

## 13. 2026-09-14 隔离 PostgreSQL repository 往返证据

先前 41 项 SQLite 受影响回归只证明本地 SQLite/ORM 的 carrier、stale-witness
和写入计数语义，不能当作 PostgreSQL 或生产数据库证明。随后使用独立的本地
Docker PostgreSQL 16.14（loopback 映射 `127.0.0.1:55439`、数据库
`evid06_authority_test`）运行一次正式 opt-in component pytest；driver 通过既有
`var/evid09-private-pg.owner.lock` 互斥，数据库前后均为 0 个 public base table、
0 个 other client backend，最终锁已释放。driver 和 JUnit 保存在私有工件
`var/data02-financial-pg-roundtrip-20260913T203049.741789Z/`，receipt 的
`pytest_exit_code` 为 0，JUnit 为 7 tests/0 failures/0 errors/0 skipped，SHA-256 为
`c87097ceb6bba8164b060c11998ffd0de7a732472bee1b2a09056bf1638dadd4`（1629 bytes）。

上一份 PG 两用例已以同一 `FinancialFactModel.value` 的 direct-float 写入验证
`12.34525` 的 PostgreSQL 存储 oracle。本次正式测试重跑该边界，并追加实际仓库
writer-vs-direct-ORM 持久化及 replay=0 的五个 tie 输入：`+12.03125`、
`-12.03125`、`12.34505`、`12.34525`、`12.34535`；每个 expected value 都来自
同 backend 的 direct ORM writer，不由 formatter 或文字常量推导。正式测试也验证
repository 首写返回 1、`announced_at`/`source_record_id`/`raw_payload_hash`
往返保真、同一事实重放返回 0 且 `fetched_at` 不变。另一个 case 验证已有 witness
的值变化会在同一批次阻断，原受保护行保持不变且新行不残留。源码和正式测试的
before/after SHA 完全一致；这证明了本次隔离 PostgreSQL repository 行为，不证明
供应商原始响应、scope/completion、`available_at` 或生产全量数据已具备。

本组 `FinancialFactSourceEvidence` 仅承载已有的三个 typed core 字段：真实
`announced_at`、`source_record_id` 和 `raw_payload_hash`。它没有引入原始 response
bytes/hash 的 batch scope、response completion sidecar 或 `available_at` 的来源
证明；`is_complete` 只能表示这三个字段形状完整，不能表述严格 financial policy3
来源验收。date-only provider 输入仍保持未知时刻和 `available_at=None`，不得用
`fetched_at`、`report_date`、normalized row hash 或自然键补齐。该隔离测试没有生产
写入、历史修复、供应商网络请求或 policy 激活。


## 14. 2026-09-14 候选验证封存与剩余门

主代理随后完成受影响的完整 SQLite 回归：56 passed，0 failures/errors/skipped，
JUnit 总耗时 244.923 秒。正式隔离 PostgreSQL 的 7 项结果与该 SQLite 批次
分别封存，不能相加为 63 个独立业务场景。

[候选验证封存](../testing/data02-financial-source-carrier-validation-2026-09-14.json)
及其 `.sha256` 绑定 12 份原始工件，包括两个 backend 的 JUnit、PG 前后
数据库与源码记录、runner，以及先前各次 driver receipt。封存同时记录实际测试
源码 raw SHA 与 Git LF 标准化 SHA，避免将换行转换误认为业务源码变化。

本候选尚未部署；没有改变模型列、执行 migration、历史 backfill、供应商获取或
生产 publication 激活。后续仍须取得可核验的 response bytes、scope、completion、
row identity 和精确来源时间，并独立验证 availability；三字段 carrier 的
完整形状和本组顺序回归均不能替代 DATA-02 生产退出门或并发验收。

候选独立审查确认顺序写入、Decimal 存储归一化、整批 stale witness 阻断及
savepoint winner 的实际计数成立。缺失 natural key 无法预锁；反序并发插入可能
触发 PostgreSQL unique-index deadlock，当前事务会失败回滚，尚无自动恢复或
真实双事务验收。该门须独立补统一插入顺序和并发测试，不能将本组 PG7 宣称为
并发通过。

候选 CI 发现 architecture 与 entrypoint 自动生成清单过期；按现有生成器刷新
投影并保留既有治理状态，不增加 mypy 债务或放宽退出门。最终合并仍以对应
提交的完整 CI 成功为准。

## 15. 2026-09-14 实际代码审查与合并

最终审查提交 `242df9aada34fe3c0e57e1506cf4d38a140b186b` 的完整 30 项检查
均实际 completed/SUCCESS。PR42 在 `2026-09-13T21:16:11Z` 合并为 Main
`9390637ca72ef221b76179e62faaac8d2b552d7c`；候选与合并提交的 Git tree
一致。原始 ready、match-head merge、检查前后 JSON、stdout/stderr 和执行
receipt 共 13 份工件，连同 helper 源码共 14 份 exact bytes 封存在
[代码审查与合并记录](../testing/data02-carrier-review-and-merge-2026-09-14.json)
及其 SHA sidecar 中。独立代理的只读审查结论仅按收到的报告摘要记录，
没有伪造人工签名或生产批准工件。

这关闭候选代码的审查/合并待办，没有部署该财务候选。VPS 仍运行 EVID-09
优化来源 `6760c9aa`；真实响应、scope/completion、行身份、精确可用时间、
并发和 DATA-02 生产退出门保持未完成。下一隔离切片先实现 typed raw-response
捕获边界与 mock 测试，暂不接入 provider、写入或发布；date-only 来源保持
`announced_at=None`、`available_at=None`，缺失真实行 ID 时不把 partial hash
附到已有事实 witness，也不能以系统获取完成时间替代供应商披露或可用时间。

## 16. 2026-09-14 独立原始响应捕获边界

在 latest Main `282d0abfc564b94c86e3d48970e8c8c6f484d9a1` 的独立开发分支新增两个
生产模块及一个测试模块。Domain 只定义 typed request/response scope、body scope、
SHA-256、字节数和 aware UTC completion；Infrastructure 注入已经路由的 response、
decoder 与 clock，不自行创建 HTTP session 或选择供应商出口。读取仅发生一次，
stream EOF 后立即取完成时间，再拼接、计算原始字节 digest，并将同一 bytes 交给 decoder。

response scope 明确标记为 caller_declared，不冒称已从 body 验证出的行覆盖或独立
financial source_record_id。identity/未声明编码以外的响应拒绝接受，避免把透明解压后的
字节数与 wire Content-Length 混用；大小超限、无效/冲突长度头、截断、非 2xx、读取或
解析失败均不返回成功证据。严格 JSON decoder 拒绝重复 key、NaN/Infinity，用 Decimal
保留有限指数数值，之后仍须由供应商专用 parser 完成类型收窄与业务校验。

Luna 与主代理分别执行同一冻结源的 50 项定向测试，均零 failure/error/skip；不能合计为
100 个独立场景。主代理实际 coverage JSON 的 Domain 行覆盖为 98/99（98.9899%），
分支为 45/46（97.8261%）；98.6207% 是 statement+branch 的合并数值。Black、isort、
Ruff、两生产文件增量 mypy 与 full debt ceiling 均实际 exit 0，mypy 债务仍为零。
增量架构扫描实际覆盖两生产文件、502 新增行并通过。一次不支持 `--staged` 参数的
调用以 usage exit 2 失败，其原件保留；随后使用支持的 working-tree diff 调用通过，
未重跑已通过检查。[候选验证封存](../testing/data02-response-capture-candidate-validation-2026-09-14.json)
及其 sidecar 保存 20 份 exact originals、冻结源 raw/Git LF hash 和分别计算的覆盖率。

该切片尚未接入 provider/egress 调用、sync、model、write guard 或 Publication，没有
发起供应商请求、持久化、迁移或生产写入。也未将 partial transport digest 附到既有
FinancialFactSourceEvidence，保留后续完整 witness 的替换能力。ANN/available 的来源
瞬时及行身份仍须独立建立，系统响应完成时间只证明获取上界；DATA-02 生产退出门未改变。

## 17. 新键插入顺序与真实 PostgreSQL 并发验证（2026-09-14）

基于 Main `e5585a471ad4e28cd8e2e52289a11d2b8b85b966`，功能提交
`9c3abad278555cec287ed6588eceeec39abf5e13` 只修改 financial write guard 的新键插入顺序，
并新增 opt-in PostgreSQL 并发测试。插入前按既有五字段 natural key 排序，保留全批次 stale
witness 校验、确定性旧行锁、atomic/savepoint、冲突 winner 重读、实际存储计数与 replay=0；
没有增加 retry、ignore_conflicts 或业务 timeout。

主代理真实运行 PostgreSQL 16.14：两个独立后端 PID `1205/1206` 同时提交反序重叠批次，
实际 guard SQL 存储计数为 `[0, 2]`，最终两行，新增并发测试 1 passed、零 failure/error/skip。
测试 child wall 为 52.2862 秒，不是数据库服务器 CPU 或生产性能提升值。既有 PostgreSQL
provenance/数值回归另有 7 passed，定向 unit 10 passed；三组场景与 backend 分别记录。
Black/isort/Ruff、生产文件增量 mypy、full debt ceiling、增量架构检查均 actual exit 0。
DATA-02 entrypoint 投影更新为 1208，仅增加一个 candidate-review test_evidence；
active_public=751、adjacent_operational=298、compatibility=137 不变，单元退出状态不变。

通过批次已校验固定 staging Docker CID、loopback 端口与实际 PG 地址绑定、前后源码与运行
身份不变、public 普通/分区表=0、其他 client backend=0、public routine identity 不变及 owner
lock 释放。此前三次失败分别是 CIDR 地址格式比较、只读 statement timeout、夹具建连超时；
原始 failed receipts 保留，未计为通过。失败清理的 stdlib control 只证明失败记录保留、
foreign lock 不删除及未回收 child 不冒称已回收，不是 PG 证明。没有声明旧死锁的确定性复现。

[并发候选验证封存](../testing/data02-financial-insert-concurrency-validation-2026-09-14.json)
及 sidecar 保存 47 份公开 exact originals 和 changed source raw/Git LF hash。一次失败连接的
JUnit 与 stdout 含私有 staging 凭据，仅公开两份原件的大小与 SHA，内容留在本地私有记录中；
未将脱敏副本冒充原件，未发布旧封存。既有序列 runner
将 child stdout/stderr 丢弃，封存仅保留实际存在的原始 JUnit、source 与清理 receipts，不补造日志。
本切片尚未部署，没有修复历史 ANN/available/native row ID 或发布 policy3 current；DATA-02
生产验收仍未收口。响应捕获切片已由 PR #45 在全部 30 项检查通过后合入 Main，仍未接入实际
provider 或持久化完整行 witness；后续 Egress 接入独立推进。

## 18. 2026-09-14 Egress 响应捕获候选

新增显式可选的 `request_financial_response` 入口，在现有 Egress 的出口、TLS、
allowlist、限流、熔断和资源释放边界内调用原始响应捕获器。请求 scope 的 dataset
必须与 Egress context 一致，验证发生于 HTTP 请求前；旧 request/request_payload
入口保持兼容。新入口默认请求 identity encoding，保留调用方显式的 encoding header，
实际压缩响应仍按捕获契约阻断。失败返回稳定、脱敏的原因，不返回部分成功凭证。

代码分别提交 `23018b665` 与 `e7c160f7da7317fb3364b925b05e51bb8b80dd63`。
主代理最终受影响回归为 90 tests、0 failures/errors/skipped；Black、isort、Ruff、
生产文件增量 mypy、全量债务门禁及增量架构检查均实际 exit 0。
identity header 反例先红 1 项，修复后该测试文件 12 项通过；Luna 的初始 65 项
发生于 identity 修复前，不能与最终 90 项相加为独立场景。
entrypoint 和 architecture 生成器分别验证 1207 与 5025 项，治理规模和退出门不变。

[候选验证封存](../testing/data02-egress-financial-response-validation-2026-09-14.json)
及其 SHA sidecar 保存 20 份 exact originals、源码 raw/Git LF hash、最终回归与
类型门禁，以及单独标识的初始和先红后绿 JUnit。未保留的先红 stdout/stderr
没有重构为原始工件。

返回 DTO 仅保留解析后的 payload、原始 body SHA/大小和 EOF UTC，不保留原始
body bytes；RawAudit 的原件持久化仍须单独实现。scope 为 caller_declared batch，
不证明 native financial row identity、ANN 或 available_at。本候选没有接入 provider、
Application、FinancialFact 写入或 Publication，也没有供应商请求、PostgreSQL 验收
或 VPS 部署。DATA-02 可用时间、原始响应持久化及生产退出门保持未完成。

## 19. 2026-09-14 捕获后保留原始字节

独立代码提交 `00f66332688705ae5c5bb5abaf60d312eaa58336` 为捕获 DTO 增加
不可变 `raw_body`，直接保留传给 decoder 的同一份 buffer，不复制或再次计算哈希。
有意义的反例验证：解析后的 mutable payload 被修改后，原始 bytes、大小和 SHA
仍与解析器输入一致。仓库内调用均经过捕获工厂；外部直接构造该公开 DTO 的代码
现在须提供 `raw_body`，这是构造签名的兼容性变化。

普通 pytest 最终受影响回归为 91 tests、0 failures/errors/skipped；Black、isort、
Ruff、生产文件增量 mypy、full debt ceiling、增量架构检查共七项均 actual exit 0。
单项普通 green 是该批次中的重复场景，不能合计为 92 个独立场景。
独立代码复审确认同一 buffer、不可变 bytes 和仓库内调用方兼容性。

[候选验证封存](../testing/data02-retained-financial-response-body-validation-2026-09-14.json)
及 sidecar 保存 41 份 exact originals 和 raw/Git LF source hash。两次先前启动尝试
在 120 秒内超时，首次格式检查失败于 isort，均保留原始失败工件且不计为通过。
预先启动的诊断使用 `-S` 后显式 `site.main()`，实际得到缺少 `raw_body` 的一项
AttributeError 反例；它是单独标识的诊断，不是普通最终门禁，且没有独立的同期
source-before 快照。较早失败尝试的 source snapshots 未被重命名为该诊断的快照。
没有放宽超时预算，也没有据此声称定位了所有启动等待原因。

原始 bytes 目前仅随 DTO 保留在内存中；下一阶段仍须完成原件持久化、不可变存储
引用及实际 provider 的行覆盖校验。没有 RawAudit/FinancialFact/Publication 接入、
native row identity、精确 ANN/availability、PostgreSQL 或 VPS 证明。DATA-02
可用时间、历史原始哈希和生产验收继续保持未完成。

## 20. 2026-09-14 原始响应加密存储候选

独立代码提交 `d8a351a42` 新增 typed artifact/reference、Application 存储 Protocol、
显式配置的 Fernet 文件存储及契约测试。加密封装共同认证 allowlist 元数据和原始
bytes；读取后重新核对原始 SHA、大小及不可变引用。相同 capture identity 的完全一致
重放复用原件，元数据漂移拒绝；不同 identity 可以独立保存相同 body。原子发布不覆盖
已有原件，只清理本操作的 partial。Windows 使用 write-through、不覆盖的发布操作，
并拒绝现存符号链接和 junction；读取设有限上限，文件在 stat 后增长也会阻断。

主代理最终冻结回归为 33 tests、0 failures/errors/skipped；Domain 行覆盖为 58/58，
分支为 20/20，分别为 100%。Black、isort、Ruff、三个生产文件增量 mypy 和 full debt
ceiling 均实际 exit 0。独立增量架构扫描实际覆盖三个生产文件、1,015 新增行且零违规。
较早使用符号 `HEAD` 的扫描实际为零 changed files，不计为有效架构验证。六项普通
public-read 损坏元数据反例先失败，再通过，保证解析异常转为稳定的 corruption 原因。
较早 27 项回归与最终 33 项有重叠，不合计为额外独立场景。

最新 Main 集成后，architecture 与 entrypoint 生成器分别实际写出 5,028 个 current
surface references 与 1,208 个 entrypoints；数量及内容以生成的机器清单为准，
未修改治理单元状态或退出门。

[候选验证封存](../testing/data02-original-financial-body-store-validation-2026-09-14.json)
及 sidecar 保存 37 份 exact originals、冻结源码 raw/Git LF hash 和独立覆盖率数据。
六项先红 JUnit 没有单独同期源码快照或捕获的 stdout/stderr，未补造这些原件；其文件名
中的日期样式文本仅为标识，不作为实测执行时间。Main 已合并的财务写入排序通过正常
merge 纳入本分支，未回退其他主线。

该存储必须由调用方注入独立密钥、key reference/version、目录和大小上限；尚未完成
生产 secrets/composition wiring、实际 provider 原件保留或 RawAudit/FinancialFact/
Publication 绑定。文件和数据库没有共同事务，也不声称防御具有目录写权限的恶意
并发目录替换。本候选没有 PostgreSQL 或 VPS 验收，没有修复历史原始哈希或精确
ANN/availability/native row identity，DATA-02 生产退出门及人工签署状态保持不变。

## 21. 2026-09-14 Linux 平台类型门禁修复

候选提交 `e08a3dd1683a049bd67f8514d14de55513593a90` 的 CI 有两项重复的
Incremental Quality 失败，实际 Linux/Python 3.11 类型检查报告四个 Windows API
属性错误。代码提交 `62810df75` 将完整 Windows 实现放入 mypy 可识别的
`sys.platform == "win32"` 分支，没有增加 ignore 或抬高债务基线。

修复后主代理再次实际通过 Black、isort、Ruff、33 项回归、三个生产文件增量 mypy
及 full debt ceiling；Domain 行 58/58、分支 20/20。独立 Linux/Python 3.11 类型
投影也实际 exit 0，但其执行环境仍是 Windows，不替代 Linux 运行时测试。
实际增量架构扫描覆盖一个生产文件、29 新增行且零违规；生成清单只更新三处行号。

[平台验证封存](../testing/data02-original-financial-body-store-platform-validation-2026-09-14.json)
及 sidecar 保留 29 份 exact originals，分别标识旧 CI 失败与新源码本地门禁。
第 20 节原封存保持不变，继续描述其历史源码。新 head 的 CI 尚待实际观察；本次
验证不形成 provider 接入、历史原始哈希修复、精确 available_at 或生产验收证明。
