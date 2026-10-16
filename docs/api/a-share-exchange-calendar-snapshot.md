# A 股交易所日历参考快照

本合同描述 ASH-02 的来源事实前置切片。它保存一次完整 `trade_cal` 响应及指定交易所、指定自然日范围的逐日状态，供精确引用和研究核对。快照尚未绑定正式 Publication，不能用于决策、模拟成交结算或实盘执行。该限制通过 `ExchangeCalendarSnapshot.to_payload()` 的派生字段发布：

```json
{
  "publication_status": "unpublished",
  "must_not_use_for_decision": true,
  "must_not_execute": true,
  "blocked_reason": "exchange_calendar_unpublished_reference"
}
```

这些字段不加入原始来源内容、`content_hash` 或 `record_digest`，避免改变历史事实的摘要。

## 来源与完整性

`TushareExchangeCalendarSource.fetch_candidate(exchange, coverage_start, coverage_end)` 要求显式交易所和日期范围，调用 `trade_cal` 的 `exchange/cal_date/is_open/pretrade_date` 四个字段，不发送仅返回开市日的 `is_open` 过滤参数。响应必须覆盖范围内每一个自然日，且每天只有一个明确状态。布尔值、浮点值、未知状态、缺日、重复日、错误交易所和范围不一致均拒绝；原始整数或字符串 `0/1` 可显式解析。

`pretrade_date` 在覆盖范围内必须与此前已明确开市的日期一致。范围首日之前的日期作为来源字段保留，不据此补出范围外的每日状态。周末、节假日和临时休市均以来源行表示，不使用工作日算术代替交易所日历，也不自动将另一交易所的日历套用过来。

原始响应经过 [Provider 响应留存合同](a-share-provider-response-retention.md) 捕获并保存。该日历切片要求 `original_body_retained=true`，验证原文字节、摘要、请求 API、字段、交易所与日期参数；只有 DataFrame 或仅有脱敏响应时拒绝。仓储写入和读取均从已留存原文重建候选，与事实逐日内容、内容摘要及记录摘要核对。

## 时间与摘要

| 字段 | 含义 |
| --- | --- |
| `first_seen_at` | 本系统完整收到响应的 UTC 时刻，等于原始捕获的 `response_completed_at` |
| `recorded_at` | 首次写入该日历事实的 UTC 时刻，在数据库事务内生成 |
| `source_published_at` | 供应商明确提供的上游发布时间；本来源没有时保留 `null` |
| `content_hash` | 来源绑定、完整日期状态及来源时间等候选内容的规范化摘要 |
| `record_digest` | 包括快照 ID、候选内容和首次 `recorded_at` 的完整事实摘要 |

两个本地时刻均不能冒充供应商观测或公告时间。相同 RawPayload 只能对应一个日历事实；精确重试返回原 ID 和原 `recorded_at`。不因重试刷新可获得时间，也不把同一原始响应重新绑定为修改后的开闭市状态。不同响应可以形成新快照，旧快照保持不变。

## Application 入口

- `IngestExchangeCalendarSnapshotUseCase.execute`：抓取并保存明确范围的完整候选。
- `ReadExchangeCalendarSnapshotUseCase.execute(reference, known_at=...)`：按快照 ID、交易所、覆盖范围、事实摘要及 RawPayload 引用精确读取；要求 `first_seen_at <= known_at` 且 `recorded_at <= known_at`。
- `ReadNextExchangeCalendarSessionUseCase.execute(reference, after_date=..., known_at=...)`：仅在该精确快照覆盖范围内寻找严格晚于 `after_date` 的明确开市日。

没有 latest/current 自动选择；缺少精确记录或知识截止点过早时发布 `EXCHANGE_CALENDAR_SNAPSHOT_NOT_KNOWN`。范围不足或范围内没有后续开市日时发布 `EXCHANGE_CALENDAR_NEXT_SESSION_UNCOVERED`，不向外推算。下一开市日结果仍为未发布快照的参考答案，不是执行授权。

## 持久化与后续正式接线

新增 `ExchangeCalendarSnapshotFactModel`，迁移为 `data_center.0099_exchange_calendar_snapshot`。一对一 RawPayload 引用、不可变模型写入约束及 PROTECT 保留原始来源；不新增发布总账。此切片不包含生产调度、公开 HTTP/MCP 路由或自动发布任务。

后续正式日历引用必须复用 CanonicalPublication、显式策略版本、成员绑定、权限与审计，并单独验证当前有效窗、知识截止点及覆盖范围。普通模拟消费者要求的正式日历端口不能直接接收这里的未发布参考快照。日期级日历也不能证明盘中交易阶段、证券停牌或订单价格合法性。

来源字段依据：[Tushare 交易日历](https://tushare.pro/document/2?doc_id=26)、[Tushare HTTP 调用说明](https://tushare.pro/document/1?doc_id=40)。实际供应商权限、实时抓取与正式生产发布仍需独立验收。
