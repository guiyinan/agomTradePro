# 日历发布的会话与显式权限前置合同

当前提供锁内主体授权组件，并已在本地日历 HTTP 工作台接入发布与读取流程；真实 Session/CSRF HTTP 验收见[日历 HTTP 合同](a-share-calendar-http.md)。TUI 工作台用户旅程及其实际验收范围见[工作台计划](../plans/a-share-calendar-workbench-plan-2026-10-17.md)。这些入口不代表生产部署或交易授权。已认证会话证明用户账户通过 Django 会话认证，不证明物理真人在场。

## 请求与权限来源

发布适配器只接受真实 DRF POST，成功认证器必须精确为 `SessionAuthentication`，保留 CSRF 检查。用户身份来自 request 与原 Django request 的已认证用户，不能由 body/header 中的 user_id 替代。Token、内部 HMAC 和测试用 forced-user 不作为本入口的授权来源。

后端必须是可锁定的 Django DB session；会话、User、ContentType、Permission、直接授权及组成员/组授权必须路由到同一个显式数据库 alias。当前发布权限为 `data_center.publish_exchange_calendar`，ContentType 精确为 `data_center.exchangecalendarsnapshotfactmodel`。staff、superuser、Account role、tenant/owner 或 broker owner 都不替代实际 user/group permission 行，不调用 `has_perm()` 缓存或 superuser 捷径。

0103 只给既有日历模型登记发布与审计读取两个 custom permission。Django 标准权限创建步骤生成定义，默认没有用户或组授权；没有新增权限账本或 grant 种子。撤销 Meta 定义不会自动删除既有 auth_permission/grant 行，不能把迁移降级当作撤权。

## 锁、时间与事务

授权组件拥有外层事务，拒绝调用方已在事务中或手动关闭 autocommit。锁顺序为 session、User、ContentType/Permission、直接授权、排序后的组成员关系和组授权，再由未来 publisher 接入发布数据及 Audit 锁。所有锁取得后，重新核对 active user、session 用户/backend/auth hash/expiry 和真实 permission witness；缺少或无法证明时返回稳定阻断。

主体只在创建它的线程及 context 生命周期内有效。每次访问重验带时区 UTC clock、最后验证时刻不倒退且严格早于 session expiry，并拒绝同 alias 事务的 rollback-only 状态；正常退出前再验证一次。过期、倒退或已无法提交使事务内调用方写入回滚并报告失败。调用方已经抛错时保留原异常并回滚，不用最终检查覆盖原错误。主体退出后不可复用，session key 不进入 repr、比较、审计或用户输出。

当前组件不提供历史授权区间。专属 reader 已通过 Core bridge 显式组装：真实 DRF GET 的 SessionAuthentication、同库 session/User 和精确 `view_exchange_calendar_publication_audit` 权限在查询及结果重验期间持续持锁。历史 `as_of` 只选择事件知识截止点；不能用当前 auth join 行伪造过去已有授权。读权与发布权分别固定到两个封闭 purpose，HTTP 输入不能选择 permission codename；仅有读权不能发布，仅有发布权也不能读取专属审计。

Calendar 仅允许两种完整 v1 无 tenant/owner scope 事件及 dataset/exchange 精确 stream。专属查询只恢复目标 stream，或类型、dataset、exchange 均匹配的 Calendar 行；校验目标原件、hash 和完整前驱链后再返回 PIT 前缀。无关坏行不阻断本 stream，目标错流、异类、断链及损坏时间均拒绝。通用租户审计读取和追加权限保持原约束。

## 验证与边界

SQLite 定向组合 28 passed，另有三个 PostgreSQL-only 行锁候选跳过。主代理独立复现锁内会话到期、提交前到期及锁后时钟倒退共三项失败，另复现跨线程复用一项失败；修复后原生 PostgreSQL 组合 58 项全部通过，包含真实登录/CSRF、旧普通政策和 codec ORM、四项独立反例及两类撤权测试。

六项主代理双连接场景用 `pg_blocking_pids` 实际确认等待：直接授权、组权限、组成员关系分别验证“授权先锁定，撤销等待提交”和“撤销先提交，锁后重验拒绝”。事务内标记写入只用于证明授权边界；它不冒充尚未实现的 publisher pointer/event/outbox 原子性。另三项候选验证持锁时 nowait 撤销被数据库拒绝。

本次复用 544 迁移、580 普通表的 Goal 专用 PostgreSQL 夹具，不是从空库重放。四个生产文件增量 mypy 零回归；最终全候选架构、格式、债务和生成投影仍需在证券快照、审计读写及组装冻结后联合验证。没有生产部署、真实供应商调用、真实用户授权或券商放行。

证据见[政策与发布主体有界检查点](../testing/a-share-usability-policy-authority-2026-10-16.json)。

## 2026-10-17 共享授权与审计联验

加入 reader 的共享实现已另行冻结，未改写前述 58 项旧源码证据。主代理新增 rollback-only 的两种反例，由子代理真实执行得到两项失败；检查现在覆盖显式 assert_live 和正常退出。内部 claim 的 session key 隐藏、未知 purpose 的运行时拒绝及原 POST/CSRF 行为均有回归。

主代理原生 PostgreSQL 15 文件组合 **205 passed / 331.38 秒，无跳过、无源码漂移**，包括旧普通 Audit/hash/Outbox 兼容、真实 GET/Core reader、政策 ORM 与 12 项双连接撤权顺序（发布/读取 × 直接授权/组权限/组成员 × 两顺序）。数据库实际 blocker/waiter 被观察；回调标记仍只证明授权事务，不等于正式 publication pointer/Audit/outbox 联合原子性。

新 Audit Domain 覆盖 **276/282 语句、78/84 分支**。真实 dispatcher 已将一个无 scope Calendar 事件写入内部持久回执，未证明外部消费者或生产 dispatcher 启用。**截至本节所引用的 2026-10-17 共享授权与审计检查点（后续 HTTP 工作台接入之前）**，两个事件登记为 planned/not_wired，且没有发布/读取 HTTP 路由；这段记录保留当时阶段，不代表当前路由状态。之后本地 HTTP 工作台路径及 Session/CSRF 验收见[日历 HTTP 合同](a-share-calendar-http.md)，TUI 用户旅程另见上述工作台计划。默认 provider、真实 grant、生产迁移或实盘开通仍未验收。详见[共享授权与审计检查点](../testing/a-share-usability-calendar-audit-authority-2026-10-17.json)。
