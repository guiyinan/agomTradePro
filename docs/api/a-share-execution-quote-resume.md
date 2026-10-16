# execution 行情已完成发布的精确恢复

`resume_completed_execution_quote_activation` 用于发布已经完成、调用方未收到结果的情况。它验证并返回原 CanonicalPublication，不重新 staging，不生成另一发布记录，也不补写缺失的审计证据。它不负责续跑未完成的 CANDIDATE。

入口位于 `apps/data_center/application/execution_quote_activation.py`，要求显式注入同一 alias 的生产 composition bundle，并提供原 `run_id`、`task_attempt_id`、完整且规范排序的 `asset_codes` 和当前 `SystemAuditReaderContext`。目前只接受 `equity.quote.snapshot / execution`；不回退到 `current`。

## 恢复条件

1. 精确 run/task/dataset/key 查询最多两份 manifest，必须恰好一份；重新验证 manifest、每份 RawAudit 和发布绑定。
2. 发布必须已经 PUBLISHED，且未被标记为不可决策；成员、事实、完整资产范围和发布摘要一致。
3. 当前指针的 row ID、publication ID/hash、activation ID 和 updated_at 必须与原完成 epoch 一致。持锁后再次核对，不能将最新指针重建成原 CAS 意图。
4. 获取当前完整 Account authority，并在其同 alias 外层事务中复验目录版本、策略、事实、源 TTL 和租约。旧发布成功不替代当前权限。
5. 使用 verify-only Audit 适配器重建原时刻、原身份和原证据的 canonical event，与实际 event/Outbox 精确比较。不存在、篡改或 scope 不符均拒绝，不调用正常 append/enqueue 的修复分支。
6. 成功后仍须通过正式 execution quote 读取合同，确认返回的是请求发布及其成员事实。

锁后写入前以及实际 Audit I/O 后均读取新的 UTC 时钟，要求处于当前 lease 的半开有效窗且不早于此前检查。源 TTL 使用同一已验证时刻，不能通过重试或新的检查时间刷新源观测。新激活与 same-current 恢复共用此 execution 检查；原 current 三数据集合同保留。

## 阻断与未完成请求

`EXECUTION_QUOTE_RESUME_BLOCKED` 表示无法证明精确完成状态或当前读取条件，包括 manifest 缺失/歧义、CANDIDATE、指针 epoch 变化、权限或 TTL 失效。`EXECUTION_QUOTE_RESUME_CORRUPT` 表示原完成所需 Audit/Outbox 缺失或损坏。两者都不能解释为允许重建历史证据。

现有 staging 没有持久化原 activation CAS 意图，不能安全恢复未完成 CANDIDATE。原 `stage_and_activate_execution_quote_candidate` 的 PUBLISHED 重试仍会被 staging 拒绝；调用方应在已确认完成的情况下显式使用本入口。其他中断状态按明确新请求或后续恢复协议处理，不能拿当前指针冒充原预期值。

该能力不新增 HTTP/MCP 路由，不形成生产数据或券商执行授权。测试用完整 authority 接缝只证明本地事务与合同；真实 Account 权限图、生产发布能力及 QMT 停止线仍须分别验收。
