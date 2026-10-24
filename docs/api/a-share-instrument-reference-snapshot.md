# 证券名录整批快照与显式映射

本切片消费[证券名录来源合同](a-share-instrument-reference-source.md)，追加保存完整来源批次。它仍是不可用于决策或执行的来源证据，不更新 AssetMaster，也不提供证券盘中交易状态。

## 数据身份与时间

复用既有 RawPayload、RawAudit，只新增两张表：版本化 `InstrumentReferenceMappingModel` 和整批 `InstrumentReferenceSnapshotModel`。没有逐证券的第二主数据表，也没有第三套 occurrence 台账。

映射明确给出 source exchange 到 Rule.market、以及 `(exchange, source market 原文)` 到 board 的对应关系，并嵌入完整版本化代码后缀 crosswalk。crosswalk 的 64 位摘要与映射整体 `sha256:` 摘要含义不同。未知标签保持原文并阻断分类，不按证券代码前缀或常见中文标签猜测。当前没有真实市场映射、证券范围或上市状态种子配置。

一个 snapshot 保存同一 run 的完整 fetch rounds；每轮保留精确请求范围和全部 occurrence，零行响应也保留。重复响应 body 不合并调用发生身份，不同轮次的生命周期或 source market 冲突均保留；存在歧义时不输出唯一可执行分类。

内容摘要不含数据库 UUID 或记录时刻。仓储使用自己的 UTC clock 一次性封装首次记录凭据，record digest 同时绑定 UUID、内容摘要、首次 `recorded_at` 及精确 mapping record。精确重试返回原 UUID、时刻和摘要；不能借重试刷新知识时点。上游未知 observed/available/published 继续为 None，上市/退市日期保持 date。

## 原件验证与读取

写入和按 snapshot UUID 的精确读取均核对 RawAudit、RawPayload 的真实行、摘要、run/occurrence、请求范围、状态及记录数。仓储重新解析保留的响应 body，并比较全部来源记录，防止调用方用合法原件引用搭配伪造名称、日期或 market。缺原件、审计不一致或 seal 损坏立即失败。

当前适配器明确只支持 `default`。构造时检查 RawAudit、RawPayload、两个新模型的实际 Django read/write 路由以及端口的 UoW 身份；其他 alias 配置拒绝组装。既有 RawAudit/RawPayload 的 exact-ID 查询明确使用 default，不用跨库相同主键拼接证据。没有增加多库发布能力。

读取入口是 `GetInstrumentReferenceSnapshotUseCase.execute(snapshot_id)`，不是 latest/current 查询，也没有历史 `as_of` 授权或发布时间筛选。返回凭据公开自身记录时刻；后续正式发布与 PIT 消费必须另行验证知识截止点、发布状态和数据时效。

## 不可变与并发边界

普通 Model.save 使用 INSERT，拒绝已有行更新；QuerySet/Manager 的更新、删除和 bulk upsert 路径受保护。数据库约束裁决同一 mapping 版本和 snapshot 内容的首次写入，字段/模型校验不使用存在竞态的唯一性预查询代替 INSERT。唯一冲突后只重读精确胜者，内容一致才返回原凭据。

这些是普通 ORM 和应用端口保护，不是数据库不可变触发器。直接 SQL 可破坏记录，精确读取会重新验证 seal 和来源；直接 SQL 不是本切片提供的管理入口。

0101 仅创建两张空表，不回填旧数据。独立 SQLite/PostgreSQL 实际 operations 升级、回退、再升级验证了版本/内容唯一性、非负计数、正轮数/occurrence 数及 mapping 外键，旧政策行全部持久字段保持。迁移探针使用 synthetic seals，仅证明 DDL 约束。**回退会删除两张新表及证据记录**；须先保存证据、关闭依赖读取，不能宣称数据无损回退。

## 验证范围

SQLite 来源、快照、留档、HTTP 及 ORM 组合 146 项通过。主代理 PostgreSQL 11 个测试文件实际 151 项通过，包括两项真实双连接精确重试与四项独立 ORM 覆写反例；运行期间只有一个测试文件整理了 import，生产九文件摘要未变，该最终测试文件另外在 PostgreSQL 通过 11 项。后者与前者重叠，不相加为唯一测试数。

原生覆盖数据经过精确 parallel 文件合并，Domain 为 417/420 语句、147/150 分支；文本 98.9% 是合并口径。源文件、失败原件与具体检查范围见[有界检查点](../testing/a-share-usability-instrument-snapshot-2026-10-16.json)。正式发布、真实 Provider、旧消费者切换、盘中状态及实盘能力尚未由本切片验收。

## 有界捕获 claim 基础

捕获请求以稳定 `capture_id` 导出独立 run/batch 身份；请求摘要绑定完整 Provider 路由、显式映射与抓取范围，存入保留的 request descriptor checkpoints。没有 Config Center 快照输入时，`SyncRun.config_snapshot_hash` 保持空字符串，不能拿请求摘要代填。

claim 仓储复用现有同步控制表，在父行锁内创建单一 owner capability；普通重试报告进行中，显式 resume 追加受校验的 epoch，旧 owner 随即失效。通用 run/batch/checkpoint/attempt 写者在同一锁边界拒绝保留命名空间，不能伪造捕获进度。完整描述符、checkpoint 元数据及链条漂移均失败关闭。

基础批次没有实现受租约保护的完整抓取、持久进度或最终完成指针。仅在 run 下出现 snapshot 不代表捕获完成，claim 必须拒绝这种未封存完成的 snapshot，不能返回假完成或借重试追加新 owner。后续编排见下一节；此基础不激活默认来源、不改写上游时钟，也不自动发布或授予交易资格。

## 捕获编排与原子完成

`CaptureInstrumentReferenceSnapshotUseCase.execute(invocation)` 通过显式端口编排 claim、逐 scope 抓取、原始响应留档、审计、严格解析和最终快照。`create_instrument_reference_capture_use_case()` 组装既有数据库与 Tushare 适配器，不新增 Celery 任务或默认来源激活。Provider 必须是请求明确指定且在每次抓取时仍启用的 Tushare 配置，只允许 `stock_basic` 路由；`route_revision` 绑定调用请求，不冒充外部注册表版本，也不冻结端点或凭据内容。

每次持久写入均在 default 数据库事务内重新锁定并核对当前 claim epoch。已留存的响应和审计通过精确 ID、请求 scope、body hash、发生身份及记录数重读验证；显式 resume 可以复用已提交的进度，旧 epoch 不能追加写入。内存暂存按实际响应对象身份隔离，失败回调只清理本次产生的响应，持久化结束也清理对应暂存。

快照、完成 checkpoint 和 run/batch 的终态统计在同一事务提交；完成标记同时绑定请求、claim seal 和快照凭据。只有标记、快照及原件全部匹配才返回完成，精确重放保留原 UUID 和知识时点。RawPayload 指针使用规范 UUID，RawAudit 指针使用正整数主键，快照凭据摘要使用既有 `sha256:` 格式，不混用内容摘要与请求摘要。

首次并发领取在初次查无 run 后发现子记录时，会锁定并重查精确父行；并发胜者已提交则走既有唯一冲突后的完整绑定验证，真正缺父行仍拒绝。owner 隔离依赖 epoch 和 capability，没有新增按时间自动接管规则。

这仍是来源证据捕获：上游未知时钟保持 None，决策与执行限制保留，不更新 AssetMaster、不发布 current、不授予证券盘中状态或执行资格。实际 Provider、生产账户 M1 与发布验收分别完成；本批开发证据见[同一事项验收索引](../testing/a-share-usability-source-capture-foundation-2026-10-22.md)。

## 管理员操作入口

Data Center 工作台的“证券名录来源”操作复用上述 Application 用例与公开组合入口：

- `POST /api/data-center/tui/instrument-reference/mappings/` 接收完整映射标识、版本、交易所后缀 crosswalk、Rule.market 对应和来源 market→board 对应。相同映射标识/版本与相同内容的重试返回原凭证；同版本不同内容返回冲突。写入与精确回读后返回首次记录时刻、内容摘要和记录摘要。
- `GET /api/data-center/tui/instrument-reference/mappings/<mapping_record_id>/` 只按指定凭证 ID 返回完整映射材料。登记仅表示保存调用方提供的内容，不表示 Owner 或服务商已审批。
- `POST /api/data-center/tui/instrument-reference/captures/` 要求调用方明确给出稳定 `capture_id`、已配置 Provider 的精确 ID、映射凭证 ID、交易所范围、上市状态范围及 `normal`/`resume` 模式。系统固定使用 `tushare.stock_basic` 路由，并在发送请求前验证映射精确存在且范围覆盖交易所。完成返回 `200`/`outcome=success`；进行中返回 `202`/`outcome=noop`，需要显式恢复返回 `202`/`outcome=blocked`，阻断返回 `409`/`outcome=blocked`。原始 `status`、`success` 与原因仍单独保留，不会把尚未完成的请求描述为完成。
- `GET /api/data-center/tui/instrument-reference/snapshots/<snapshot_id>/` 按精确快照 ID 返回收据、来源记录页和逐次响应页；`limit` 为 1–200，`offset` 不小于 0。`rows` 使用 `total`/`next_offset`，`occurrences` 独立使用 `occurrence_total`/`occurrence_next_offset`，两页分别按同一组有界参数切片。收据公开捕获 `run_id`、抓取轮数、Provider 合同和交叉表身份；每条响应保留抓取轮次、交易所/状态范围、零行计数、响应体摘要、本地响应完成时刻及完整 RawAudit 引用。响应完成时刻不是上游观测时间；`source_observed_at` 与 `source_available_at` 仍为未知，结果继续禁止用于决策和执行。
- “查看逐次来源响应”是同一精确快照读取的只读工作台动作，使用 `occurrences` 页和独立总数，不把全部 occurrence 嵌入捕获结果或无界 summary。操作者可以回查空响应范围及 RawAudit/RawPayload 证据身份，但该视图不代表来源审批、证券分类批准或交易资格。

这些 HTTP 操作由后端管理员权限保护。通过工作台触发的写动作沿用现有会话认证、确认、`Idempotency-Key` 重试和操作者审计；直接 HTTP 调用本身不强制工作台会话、确认或操作者审计。操作者审计与用于验证来源原件的 `RawAudit` 是不同记录。映射输入和捕获范围均无预置业务值；该入口不声称来源材料已获审批，也不创建、激活或填充交易 selector、证券身份或投资资格。
