# A 股参考数据的原始响应捕获与留存

2026-10-16。用于日历、证券名录等非财务来源接线；此切片不创建交易日历事实、不激活 Publication，也不授予执行权限。

## 入口与时间语义

Tushare 客户端显式注入 `provider_response_handler` 后，非财务 HTTP 路径捕获完整响应体；未注入时沿用原行为。direct 与受治理 egress 都读取 identity 编码的原始 HTTP entity bytes，检查大小、完整长度和 JSON。native SDK 只返回 DataFrame 时，启用捕获会拒绝，不能将序列化 DataFrame 冒充原始响应。既有财务捕获合同保持独立。

`ProviderResponseCapture` 位于 Data Center Domain，绑定不可变 bytes、SHA-256、字节数、状态及 transport。解析使用严格 UTF-8 JSON，拒绝重复键、非有限数值和超长整数；小数为 Decimal，保留原文中的精度。公开 parsed payload 即使被改动，也不能在留存时绕过重新解析及内容比对。

`response_completed_at` / `acquired_at` 是本系统完整读取响应体的 UTC 时刻。它不是上游观测、公告或生效时刻，不能填入这些缺失字段。后续各数据集分别建立日期有效性、系统知识时间和可空上游时间的合同。

## 持久化与摘要

Application 的 `RetainProviderResponsePayloadUseCase` 通过注入端口复用既有 RawPayload 仓储。它不创建第二套原文台账。

| 字段 | 覆盖内容 |
| --- | --- |
| body_sha256 | 捕获的原始 HTTP 响应体 bytes |
| retained_content_sha256 | 实际存储的响应文本 |
| payload_hash | 包含 provider、dataset、transport、请求范围和获取时间的留存 envelope |
| record_digest | 完整 RawPayload 记录及其元数据 |

不需要脱敏时，envelope 中保存完整 UTF-8 原文字符串，`original_body_retained=true`、encoding 为 `exact_original_utf8_json`，可从数据库重建 bytes 并核对原文摘要。需要脱敏时，保存 `redacted_canonical_json`，原文标志为 false；原文摘要仍可用于身份关联，但不能声称已保存或可回放原文。

请求中的凭据字段和显式传入的秘密值会被替换，包括普通消息文本中出现的值。无法安全替换的短秘密拒绝留存。相同内容在不同 provider/dataset/请求范围下有独立 envelope 身份；精确重试复用记录，内容冲突拒绝。

下游使用 `ProviderResponsePayloadReference.verifies(row)` 核对实际取回的记录。HTTP 成功或持有 reference 本身不证明日历完整、证券可交易、源时间新鲜，也不替代 RawAudit、事实和正式 Publication 的后续绑定。

## 有界验证

真实 Django RawLandingRepository 的四项 SQLite current-schema 组件检查通过；同四项在完成 537 条历史迁移的隔离 PostgreSQL 16.15 实例通过，原始日志为 `artifacts/a-share-usability/ash02/pytest-provider-response-native-pg.txt`。

测试覆盖原始 UTF-8/Decimal 词法往返、脱敏标志、精确重试、provider/dataset 隔离和篡改拒绝。上游使用本地 HTTP doubles，没有实际 Provider、生产数据库或部署验收。
