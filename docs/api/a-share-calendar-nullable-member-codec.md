# 日历发布成员的空源时间编码前置合同

当前提供版本化 DTO、规范编码、摘要、证据校验及显式政策 codec 绑定，尚不接通发布仓储、指针或执行读取。上游未知的 observed/available/published 时间保持 `None`，不能用响应完成、入库或本地发布时间补齐。

## 身份与摘要

`CalendarPublicationMemberReference` 必须显式携带 `CalendarNullableMemberCodecVersion.V1`（`calendar-nullable-member-v1`）、完整 `PublicationMember`、日历 snapshot 的内容摘要与记录摘要。成员行的 `fact_content_hash` 是 64 位十六进制行摘要；两个 snapshot 摘要是带 `sha256:` 前缀的 71 字符摘要，三者不能相互替代。

DTO 为 frozen，校验成员身份、版本、时间类型及质量状态。未知源时间编码成 JSON `null`；本地 `fetched_at` 可为带时区时间或 `null`，不冒充源时间。新 `calendar_publication_hash` 显式绑定 `publication-evidence-calendar-nullable-v1`、codec version、版本化 policy identity 与有序成员内容。

普通 `publication_hash` 只接受原 `PublicationFactReference`；普通 `member_reference` 不接受新日历 DTO，仍拒绝缺失 observed_at 的旧成员。原非空 legacy/v2 canonical bytes 与 hash golden 保持不变。

## 校验与权限边界

`validate_calendar_publication_evidence` 要求显式 codec、版本化 policy、精确 dataset 一致、合法摘要/质量/时间及知识截止点。policy 若要求本来源未知的 observed/available/published 时间，直接拒绝，不能把未知字段跳过后宣称满足。

`PublicationPolicy.member_codec_version` 现在显式选择日历 codec；Domain 只接受已登记的 enum 成员，ORM 与 JSON 命令在边界将精确字符串转换为 enum。既有 `DatasetPublicationPolicyModel` 增加一个可空字段，旧行保持 NULL，不推断默认 codec。NULL 政策的原 `publication-policy-v1` 内容、hash 与 legacy/p2 identity 不变；显式绑定使用 `publication-policy-v2` 内容并把 codec 纳入 hash，仍使用既有 `p2:<version>:<digest>` identity 形式。同一政策版本不能通过 Repository 改变绑定，须创建新版本。

独立日历 hash/validator 现在拒绝未绑定政策；普通证据 validator 拒绝绑定日历 codec 的政策。这个判别与 dataset 的字符串拼写无关，也不自动证明某个数据集具有合法日历来源。两个配置命令均保留精确绑定，未知/空值与在 legacy identity 下隐藏 codec 的配置被拒绝；字段缺失或 JSON null 保持旧行为。

0102 只给既有政策表加字段及约束，不创建政策、不授予发布资格。新绑定改变 policy identity，因此此前未持久化的、无绑定日历候选外层摘要也会改变；成员 payload 的 codec 仍为 v1，旧普通政策的 golden 不变。反向迁移会丢失新绑定，不能声称仅靠旧行恢复；已有绑定发布时，降级必须先关闭不兼容读取与政策使用。

正式 publisher 仍必须读取真实持久政策、核对 snapshot/RawAudit、取得同 alias 发布权限并原子写入 Audit/Outbox；不能仅凭调用方构造的 Domain 对象或摘要直接激活。专用权限与发布事务尚在开发，本合同不授予交易能力。

当前没有注册可用 publisher、修改 Dataset Contract、扩宽通用 nullable member 或授予任何用户权限。正式发布、PIT 可用性、交易日历 reader 和旧消费者切换仍未验收。

## 验证

最初未绑定的内存 codec 定向组合 81 项通过，对应旧源码窗口保存在原检查点。后续显式绑定候选扩大组合 304 项通过，另有 21 项 Domain 补充测试；0102 的实际 operations 在独立 SQLite/PostgreSQL schema 完成升级、回退、再升级，旧字段保持不变，新列默认 NULL。10 个生产文件增量 mypy 零回归。完整新迁移链和正式发布的 PostgreSQL 集成仍须后续验收。

覆盖率按新增功能的实际语句和分支统计，不将大型历史 control_plane/contracts 模块的局部覆盖率写成全模块达标。

源码、原始 red/green、覆盖 JSON 和精确统计见[有界检查点](../testing/a-share-usability-calendar-codec-2026-10-16.json)。
