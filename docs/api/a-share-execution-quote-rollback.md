# execution 报价指针的受治理回退

2026-10-16。ASH-02 C 切片已完成有界本地验证；实际来源和账户权限验收仍独立进行。入口为 `rollback_execution_quote_pointer`；生产 bundle 由 Data Center composition root 组装。

该入口只处理 `equity.quote.snapshot / execution`。命令绑定 rollback UUID、目标 id/hash、预期当前 id/hash/activation，以及操作原因、操作者与带时区的操作时间。原因允许有界单行中文；操作时间规范化为 UTC，不是源行情观测时间。

完整 Account authority fence 是最外层事务。其内按目录、事实、指针及发布证据锁序验证目标、当前对象、成员、事实、RawAudit、活动合同和政策。新目标必须是同 scope 的 SUPERSEDED 对象；CAS 冲突不覆盖当前指针。状态、指针和原 Publication/事实摘要分别保留各自语义，不重算旧源时间。

回退复用 PublicationRollbackModel。Data Center 自有审计端口经 Core 桥交给真实 Audit/Outbox，调用方事务内核对实际 event/outbox commit 及完整范围。事件 detail 使用 `data.publication.rolled_back.v2`，额外绑定 `previous_pointer_activation_id`；格式见[detail schema](data-publication-rolled-back-v2-detail.schema.json)。原历史 rollback 仍使用 v1，不移动指针，历史 payload/hash 保持原样。机器登记发布当前 v2 detail 合同，不代表删除 v1 读取或写入兼容路径。

写入前与审计后检查实际时钟、权限和原源 TTL。到期、未来证据、目录/政策/事实漂移或审计失败使整笔回滚。恢复不刷新 snapshot_at、published_at 或 fetched_at 来延长行情寿命。

精确重试要求同一 rollback 记录、当前指针仍指向该结果，并有完全匹配的既有事件和 Outbox；缺失任一项报告损坏，不能补造。历史结果被后续操作取代或源证据过期时，不能通过重放再次夺回当前指针。

此切片不证明真实 Account 权限图、上游 Provider 或实盘执行验收。stage/activate 跨失败的恢复是独立入口工作，不放宽 staging 对 PUBLISHED 对象的拒绝。
