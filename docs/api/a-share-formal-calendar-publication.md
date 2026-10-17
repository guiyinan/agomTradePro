# A 股交易日历正式发布与当前读取

本文记录 Data Center 内部的交易所日历正式发布合同。该流程已有本地 HTTP 工作台入口，其 Session/CSRF 路径验收见[HTTP 接口合同](a-share-calendar-http.md)；TUI 工作台的 IA/runtime、主任务和实际验收范围见[工作台计划](../plans/a-share-calendar-workbench-plan-2026-10-17.md)。这些本地入口不等于生产发布资格，也不授予交易或券商执行能力。

## 当前边界

正式记录以精确 `dataset_key`、`exchange` 和由交易所确定的 `publication_key` 为范围。Domain 使用 `CalendarFormalPublicationSeal` 固定数据集版本、显式日历响应 TTL、合同与策略身份、快照和成员清单；Application 暴露发布与当前读取用例。Infrastructure 通过 `DjangoFormalExchangeCalendarPublicationRepository` 实现持久化、CAS 和读取，Core bridge 将发布 Audit/Outbox 操作接到 Audit Application。

内部采集、预览、确认、当前读取的 Application 操作和精确准备仓储见[操作合同](a-share-calendar-operations.md)。HTTP 工作台的本地路由和真实 Session/CSRF APIClient 旅程已验收；TUI 注册了 scope、current、prepare、confirm 四个动作，完整外层 action-run 与浏览器用户旅程的源码和夹具边界单独记在上述工作台计划。尚无真实 Provider、生产数据或券商端验收。现有 Snapshot/RawPayload 能支持候选事实与发布证据的重建，但本链路没有 Calendar 专属 `RawAudit` ID、请求 occurrence 或 run 绑定。因此，不能把保留的原文称作已验证的 RawAudit 请求记录。

正式日历仅是参考数据。`CalendarFormalPublicationCommit` 和 `CurrentPublishedExchangeCalendar` 都声明 `must_not_execute=True`；读取结果不包含盘中停牌状态、证券状态、价格边界、交易阶段、账户授权或订单许可。

## 端口与来源时间

发布调用由 `PublishExchangeCalendarSnapshotUseCase.execute(request, principal)` 编排，底层写端口为 `CalendarFormalPublicationWriterPort.publish`。Authority 由 `AuthorizeCalendarPublisherUseCase` 和 `DjangoCalendarPublisherAuthorityRepository` 提供：当前会话、用户和精确发布权限须在数据库事务内重新验证，传入的 session proof 本身不是权限凭证。

写入使用一个由 authority context 拥有的外层事务。Application/Infrastructure/Audit 必须使用同一显式数据库 alias，且 ORM router 的读写目标须与该 alias 一致。Repository 要求恰有这一个外层事务，不接受额外的 nested atomic/savepoint。该约束用于让指针 CAS、正式发布记录和 Audit event/outbox 一起提交或一起回滚。

Calendar Snapshot 保留精确 RawPayload 引用。上游观测、发布和可用时间未知时，相关字段保持 `None`；本地响应完成或首次接收时间不能冒充上游源时间。`first_seen_at` 是本地保留事实的首次知识时间，仅用来计算配置的新鲜窗口。正式 Audit 的 `recorded_at`/发布时刻也是系统知识时间，不是源观测时间。

## 封印、策略与新鲜窗口

Formal seal 使用版本化的 `exchange-calendar-formal-publication-v1` 摘要。它绑定数据集键及合同/Schema 版本、交易所与发布范围、显式 `calendar_response_max_age_seconds`、合同和策略的记录时刻、完整 `PublicationPolicy.identity`、成员 codec/清单、快照与 RawPayload 身份及快照首次接收/记录时间。策略身份包含策略版本和内容 hash，不以单独版本号替代完整策略身份。

该摘要不是整个 `DatasetContract` 行的通用指纹。合同中未进入 formal seal 的目录描述或其他非参与字段，不能据此声称已被完整绑定。发布写路径要求精确范围内唯一的 active contract 和 policy，要求合同、policy 与候选成员版本相符，并要求 calendar TTL 明确配置；不从研究 TTL 或隐式默认值回退。当前读取则按已发布记录中的精确合同/策略版本解析，不要求这些记录此刻仍为 active。活动配置变更本身不会自动撤销已发布的 current pointer。

有效时间窗由配置 TTL 和原始 `first_seen_at` 计算，采用半开区间：发布记录须满足 `published_at <= as_of < first_seen_at + calendar_response_max_age_seconds`；已有 `superseded_at` 时还须早于该时刻。缺少或未知的源时间不会被本地时钟填补。新候选须在最终写入和 Audit 返回后的时钟检查仍有效；发布或重放不能刷新源时间。过期 current 可以被新的 forward publication 替换，但旧发布及其 Audit 配对必须完整可验证，新候选也必须通过自己的新鲜度检查。

## 发布事务、锁序与 CAS

PostgreSQL 写路径在单一外层事务内按稳定顺序协调目录、事实和 current pointer：

1. 对合同与策略目录表加有界 `SHARE` 表锁，阻止候选验证期间出现活动目录行幻读；随后对数据集/发布 key 取得范围锁。
2. 按稳定顺序锁定候选及当前快照所引用的 RawPayload 与不可变事实，并从保留原文重建成员证据。
3. 锁定 current pointer，再锁定并重建其发布记录、成员和覆盖范围，验证完整的 pointer 预期值及旧 Audit 配对。
4. 写入发布记录/成员和完整 pointer CAS；然后通过 Core Audit bridge 写入或验证事件与 outbox。Audit 或最终时钟/权限检查失败时，异常穿过外层事务并回滚此前所有写入。

`CalendarPublicationPointerExpectation` 必须表示完整的存在或不存在状态。存在状态包括 pointer 行 ID、publication ID/hash、activation ID 和 `updated_at`；不允许部分 CAS 条件。首次发布只接受 pointer 与历史均为空。Forward publish 必须匹配旧 pointer 的完整身份，目标属于同一 dataset/exchange/publication-key 范围，旧记录为当前 `PUBLISHED`；成功时保留同一 pointer 行 ID、标记旧记录 `SUPERSEDED` 并把 pointer 原子切到新记录。新发布时间必须严格晚于旧 pointer 时间。缺 pointer 但已有历史、预期值不匹配或并发竞争均阻断，不从“最新记录”推断 current。

当前支持的转换是首次发布、forward supersede 和严格的当前结果重放。重放要求 activation、seal 和完整 pointer 都与当前持久化赢家相同，并由同一原发布 actor 持当前有效发布权限。重放只验证既有完整 event/outbox 并返回原始时间与身份；不得追加、修补缺失半边或重造旧事件。不同 actor 即使拥有相同发布权限也不能冒领旧结果。Formal Calendar 当前没有 rollback/reinstate 发布路径，也没有把 legacy rollback 接入此链路的能力。

## Audit 绑定

`CoreCalendarFormalPublicationAuditBridge` 通过 Audit Application 写入正式发布 event/outbox，并要求 Audit 结果与数据集、交易所、publication ID/hash、actor、记录时间、outbox ID 和 idempotency key 精确一致。数据库写入、CAS 和该 Audit 结果在同一 alias、同一 outer transaction 中提交。对已有 current 的 forward 操作还要求旧发布的 event/outbox 完整、内容未变且处于核验 cutoff 内；缺失或损坏会阻断，不会自动补写。

Audit v1 event 本身不记录旧 pointer 的完整 CAS 元组，因此它不能单独证明 forward 链；该转移由数据库事务中的 current pointer 与发布记录提供。Audit 事件的 `observed_at` 不会被伪造为日历源时间。

## 当前指针读取

公开查询是 `ReadCurrentExchangeCalendarPublicationUseCase.execute(ReadCurrentExchangeCalendarPublicationQuery(dataset_key, exchange, as_of))`，读取端口为 `CalendarCurrentPublicationReaderPort.read_current`。它只读取请求范围的精确 current pointer 和当前目标，不提供历史 publication/PIT 回放，也不回退到 latest 或其他 key。缺少 pointer 且没有相应历史时可返回无 current；若存在发布历史却缺 pointer，或 pointer 与目标记录不一致，则阻断。

读取同样要求调用方拥有唯一外层事务；PostgreSQL 使用 `READ COMMITTED` 加目录和范围 fence，SQLite 使用不新增业务记录的写保留。未配置数据库 alias 会返回 `CALENDAR_FORMAL_DATABASE_UNAVAILABLE`，不会暴露 Django 连接注册异常。源、目录、指针和 Audit 的一致核验不能脱离该事务边界。

读端要求 pointer 的 `updated_at <= as_of` 且与目标 publication 的 `published_at` 精确相等，验证目标在 `as_of` 的合同/策略身份、源窗口和正式 Audit event/outbox。即使 `as_of` 较早，也不能把今天的 pointer 当作当时的 pointer；若 pointer 后来已前移，旧 publication 不会由此查询恢复。故这个 `as_of` 是对当前指针返回物的知识/有效性检查，不是历史状态查询。

Current reference read 不要求调用者仍是原发布者，也不因原发布者撤权而自动失效；调用方的访问授权应由其上游入口独立负责。写操作的当前 active contract/policy 唯一性规则不应误用于 current read，读端按已发布的精确目录版本解析。任何下游若需要交易用途，仍须建立并验证单独的交易时点证据与授权合同；本端口输出保持 `must_not_execute`。

## 实现入口

主要定义位于：

- [formal_exchange_calendar_publication.py](../../apps/data_center/domain/formal_exchange_calendar_publication.py) 与 [calendar_publication_window.py](../../apps/data_center/domain/calendar_publication_window.py)：seal、状态转换、窗口和 current-only 校验。
- [formal_exchange_calendar_publication.py](../../apps/data_center/application/formal_exchange_calendar_publication.py)：发布/读取请求、结果及 Application ports。
- [formal_exchange_calendar_publication_repository.py](../../apps/data_center/infrastructure/formal_exchange_calendar_publication_repository.py)：事务、锁、CAS、精确 current 读取。
- [calendar_publication_authority.py](../../apps/data_center/application/calendar_publication_authority.py) 与 [calendar_publication_authority_repository.py](../../apps/data_center/infrastructure/calendar_publication_authority_repository.py)：当前发布者权限验证。
- [calendar_formal_publication_audit.py](../../core/integration/calendar_formal_publication_audit.py)：Data Center 与 Audit Application 之间的桥接。
