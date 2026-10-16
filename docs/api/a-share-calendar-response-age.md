# 日历响应有效期合同

`DatasetContract.calendar_response_max_age_seconds` 是独立、可空、版本化的日历响应 TTL。它约束系统收到原始响应后还能使用多久，不沿用研究 freshness、执行报价 TTL、数据保留期或新的发布时间。旧合同默认为 NULL；本轮没有初始化任何真实交易所的 TTL。

该字段经现有目录 JSON 加载、ORM、Domain 和 Repository 往返。值必须是 1 至有符号 64 位整数上限之间的严格整数，bool、浮点数和数值字符串不接受。相同合同版本不能改值或由 NULL 补值，应明确创建新版本；目录读取仍须独立处理多个 active version 的歧义。

## 纯窗口计算

`apps.data_center.domain.calendar_publication_window.CalendarPublicationWindow` 只计算时间窗，不读取数据库、不刷新源数据，也不授予发布或交易能力。调用方须提供精确来源快照、TTL、系统发布时间、明确生命周期及 supersede 时间。

```text
response_expires_at = snapshot.first_seen_at + calendar_response_max_age_seconds
valid_from         = published_at
valid_until        = min(response_expires_at, superseded_at if present)
effective          = valid_from <= as_of < valid_until
```

各时刻有不同含义：`first_seen_at` 是完整响应的本地接收时刻，等于 RawReference 的 `response_completed_at`；snapshot `recorded_at` 是首次事实入库时刻；`published_at` 是系统发布知识事件。上游 observation/publication 时间仍按来源保留，未知就为 None，不能用这三个本地时间补齐。

窗口要求快照来源与知识时点有效、时间为带时区 UTC、发布时间不早于事实记录。只接受首次发布与前向 supersede；缺 supersede 时刻、状态与时刻矛盾、未知/rollback/reinstatement、空窗口或 datetime 加法溢出均拒绝。发布时已经到达原响应 expiry 的数据没有可读窗口，新发布不会使它重新有效。

`is_effective_at()` 接受显式知识截止点，包含开始、不包含结束。未来正式 reader 必须从真实 canonical publication 的状态及时间字段构造该输入；尤其不能丢弃 `reinstated_at`，把恢复过的 PUBLISHED 对象冒充首次发布。本纯合同尚未提供该 reader，也没有证明任何 canonical publication 确已存在。

## 与正式发布的关系

正式日历仍需精确 RawAudit occurrence/run、原件、不可变事实、member 行摘要、Publication/Policy 版本与 CAS/Audit 绑定，以及覆盖精确 dataset/exchange 的真实操作权限。现有 Account tenant/owner fence 不自动授予全局日历发布权限。

源日历快照继续发布 `must_not_use_for_decision=true` 与 `must_not_execute=true`。即使纯时间窗计算为有效，也不能把参考快照交给普通模拟的正式日历端口，更不能据此判断证券停牌、盘中阶段或券商可交易性。

## 迁移边界

`data_center.0100_datasetcontract_calendar_response_age` 仅增加可空列与范围约束，不回填旧 TTL，不改变 execution TTL，不创建新发布表。

独立 SQLite 与 PostgreSQL 的真实 migration operations 已验证升级、回退、再升级：旧目录全部字段和原 execution TTL 保持不变，新列初始 NULL，合法 calendar TTL 不影响 execution TTL，非正数被数据库拒绝。反向迁移会删除新列，因此反向前新配置的 calendar TTL 不会自动保留；这不等同于新配置无损回退。Goal 专用完整历史夹具已经从 539 条迁移仅升级 0100 到 540 条，尚不代表正式日历发布或消费者联合验收。
