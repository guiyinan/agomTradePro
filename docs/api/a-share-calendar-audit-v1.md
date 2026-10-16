# 日历专属 Audit v1 合同

日历作为全局参考数据，只允许两个完整封闭的无 tenant/owner scope 事件：`data.calendar.publication.published` 和 `data.calendar.publication.blocked`。继续使用现有 SystemAuditEvent v1、事件表、Outbox 和内部投递回执，不增加 envelope 版本或审计表。

合同同时校验事件版本、来源 owner/component、真人账户会话主体、固定发布权限、精确 dataset/exchange、资源/关联、详情键、原始响应和 snapshot 证据、各类独立摘要、知识时刻及前驱链。它不是对任意无 scope 事件的类型白名单，也不授予发布权限。

调用方必须显式注入同库、仍持锁的授权 principal。Calendar append 只加入调用方已持有的外层事务，event 与精确 outbox 共同提交；重放必须同时证明原 event/outbox 完整且一致，缺半套拒绝，不补造记录。通用 tenant/owner 追加和读取仍要求原来的 scope。

专属 reader 端口需要注入保持锁到查询结束的权限 provider，按精确 dataset/exchange 查一个 stream。当前有效权限授权读取；`as_of` 只筛事件知识时点，不推断历史授权。查询只恢复目标 stream，或类型、dataset、exchange 均匹配的 Calendar 行；完整检查目标原件和链后返回 PIT 前缀。无关坏行不会让目标全局停机，目标坏 hash、错流、异类、断链或损坏时间仍阻断。

39 项单测、13 项组件用例通过，且已进入主代理原生 PostgreSQL 的 205 项共享联验。Domain 覆盖 276/282 语句、78/84 分支。实际 dispatcher 旅程证明无 scope 事件进入内部持久回执；外部消费、生产 runtime 开启和正式日历 publisher 均未验收。两个事件在治理登记中保持 planned/not_wired。

此合同可独立提交，Data Center 的真实 SessionAuthentication/精确读写权限 provider、正式发布指针和交易消费者属于后续依赖批次；注入接口不等于这些消费者已启用。
