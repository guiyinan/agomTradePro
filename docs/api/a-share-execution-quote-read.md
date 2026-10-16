# A 股执行输入候选：精确发布报价读取

2026-10-16。本入口属于 ASH-02 的数据端口；它返回报价事实，不授予订单执行权限。

## 调用与依赖

业务消费者使用公开入口 `apps.data_center.application.public.get_execution_quote(asset_code, *, as_of=None)`。
`as_of` 必须带时区，省略时使用当前 UTC 时间。Application 用例通过
`ExecutionQuotePublicationGateReader` 和 `ExecutionQuoteFactReader` 两个 Protocol 注入读取能力；
实际实现由 Data Center composition root 组装。调用方不得直查 Infrastructure 或 ORM。

读取在既有 `publication_snapshot("equity.quote.snapshot")` 上下文内完成：活动政策、当前指针、
Publication 内容、精确成员与事实必须一致。只读取 `publication_key="execution"`，不会回退到
`current`。`as_of` 是知识截止点校验，不是历史指针回放功能；
当前指针指向截止点之后的对象时拒绝，不能自动寻找历史版本。

## 输出语义

`ExecutionQuoteSnapshot` 是 frozen dataclass，价格保持数据库读取到的 Decimal，不再经过 float。
`last` 必须为有限正数；`bid`、`ask`、`previous_close` 可以缺失，缺失表示 UNKNOWN。
SQLite 本身的 Decimal 存取精度不等于源数据无损；PostgreSQL 精确事实读取已做组件验证，供应商原始字节精度仍需独立验收。

| 字段组 | 含义 |
| --- | --- |
| asset_code / source / quality_status | 证券、来源与既有发布质量分类 |
| snapshot_at / fetched_at | 原始观测时间与获取时间；不能用查询时间刷新 |
| fact_pk / fact_content_hash | 本次 Publication 选择的精确事实及其摘要 |
| publication_id / publication_hash / publication_as_of / published_at | 当前发布对象身份、内容与时间 |
| policy_identity / freshness_deadline / queried_at | 活动政策身份、源时间加窗口的截止点、统一查询截止点 |
| dataset_key / contract_version / schema_version | 当前活动 DatasetContract 的精确版本身份 |
| execution_freshness_seconds / contract_resolution | 独立执行 TTL；合同解析范围固定为 `current_active_not_point_in_time` |

实际字段以 `apps/data_center/domain/execution_quotes.py` 为准，不在此维护独立 schema。
TTL 使用活动 DatasetContract 中显式配置的 `execution_freshness_seconds`，缺值时拒绝；
不继承研究使用的 `freshness_seconds`。本接口在
`as_of >= snapshot_at + execution_freshness_seconds` 时拒绝，没有完成会话豁免。
Risk/执行消费者仍须取所有来源窗口的交集，不能把“报价可读”当成“可下单”。

## 拒绝与来源边界

错误使用 `ExecutionQuoteUnavailable`（项目 `DataFetchError` 子类），`reason` 为
`ExecutionQuoteBlockReason`；政策拒绝时同时保留 `publication_blocked_reason`。
稳定原因覆盖 publication_missing、publication_blocked、policy_missing、provider_result_invalid、
member_missing、member_ambiguous、fact_missing、fact_changed、source_unverified、
source_evidence_missing、future_evidence、stale，实际值统一带 `execution_quote_` 前缀。
非法请求使用项目 `InvalidInputError`。

当前指针之外的新事实不补缺；事实修改、成员表/元数据错配、Publication hash 漂移均拒绝。
`qmt-bridge:` 来源即使在 JSON 中自报可决策也拒绝。此入口复用现有质量分类和来源证据门，
不新增来源白名单，不证明供应商数据已获真实环境验收。

## 已验证与待完成

旧 `current` 候选的本地测试不能继承为本次 `execution` 候选验收。
2026-10-16 首次复核中，夹具因对象为 `current`、指针为 `execution` 出现 11 项失败；
修正后 A 切片为 67 项单元、37 项 current-schema SQLite、37 项 PostgreSQL 组件通过。
另外一项真实 PostgreSQL 双连接竞态确认同合同版本的首写 TTL 不能被另一写入者覆盖。
PostgreSQL 使用独立本机 16.15 临时实例，实际执行了 537 条历史迁移；不是生产环境验收。
上述 A 组件夹具只代表已激活的隔离指针，不证明候选持久化会自动激活。

B 切片新增 `stage_and_activate_execution_quote_candidate` 与生产 composition：
精确 RawAudit/事实成员先落为 CANDIDATE，随后在完整 Account authority fence 内完成
execution 单体组的 CAS 激活及 manifest-bound Audit/Outbox。旧 current 三数据集组及
完成会话要求保持原契约。active contract、policy.dataset 与全部 Quote 事实的版本必须
一致；PostgreSQL 在其他发布锁之前锁定目录，避免活动合同插入形成幻读。
锁内写入前和审计 I/O 后分别用新时钟检查源 TTL，过期则整笔回滚，不能刷新源时间。

冻结 B 候选的独立本机 PostgreSQL 组件组合为 **46 passed**，覆盖实际 staging、发布、
读取、审计回滚及目录并发。完整历史迁移仍为同一隔离夹具的 537 条；工作流测试只替换
authority 获取接缝，不构成真实 Account 权限图验收。原始记录为
`artifacts/a-share-usability/ash02/pytest-native-postgres-execution-b.txt`。
指针级回退与 stage/activate 跨失败的显式恢复继续由 C 切片实现；旧历史 rollback
不会移动 current/execution 指针，不能用它声称已完成回退。

交易日历、证券状态、板块、有效价格边界、交易阶段与账户权限尚未由本接口提供。
Risk 市场证据生产者和正式订单消费者接线仍待完成，Broker Evidence 门保持关闭。

## 候选时间规则

`current` 日终候选要求行情观测达到所属中国交易日的 15:00 收盘边界；
`execution` 候选按盘中报价合同校验，不使用该日终限制。
后者仍要求显式 execution key、活动版本 guard、同范围事实及源观测时刻，
并在激活与审计 I/O 后重验独立执行 TTL 和权限租约。
两条路径的固定时钟回归覆盖中国上午、15:00 边界与跨午夜，
不得用把夹具移至盘后来掩盖执行路径的错误拒绝。
