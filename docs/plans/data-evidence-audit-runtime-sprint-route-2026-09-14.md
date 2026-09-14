# DATA / Evidence / Audit / Runtime 阶段路线

本文件记录 2026-09-14 的执行判断与证据入口，不替代
`governance/active_plan_registry.json` 的 canonical unit 状态、依赖和 exit_gate。
推进顺序保持 DATA-02 → EVID-01/02 → AUD-03 → TAR-05；“一周约十个单元”是计划估计，
不能代替真实生产验收、人工决定或观察时间。

## 当前证据与执行边界

- 标准代码部署已完成，生产源仍为 `194183454fdef541a728ccce7e0a1520fe5ac860`。
  部署、备份和四个既有 authority root 的保留证据见
  [部署验收记录](../deployment/evid09-main194-rollout-validation-2026-09-14.md)。
- 完整父链的隔离 PostgreSQL 16.15 测试通过，物理解码链计数 2144、调用期 SQL 2608。
  [原始报告封存](../testing/evid09-v5-postgres-full-parent-validation-2026-09-14.json)
  的合成历史规模不能代替生产四个 root 与完整历史链，也没有证明生产解码数或优化比例。
- 新鲜生产 lifecycle 在 successor `with_current` 阶段触发原有 25 分钟 watchdog，实际失败。
  已执行独立恢复验证：19 个授权链表完整指纹、四个旧 root、旧 current/exact 与候选绑定均通过；
  这不是全数据库恢复证明，认证会话在外层事务之外。
  [失败及独立恢复封存](../deployment/evid09-failed-main194-facade-lifecycle-2026-09-14.json)
  保留失败，不以恢复通过晋级 lifecycle。
- DATA-02 原件接入实现已分类提交至 PR #55：显式配置启用后，真实 Tushare 财务请求经
  已登记出网规则、strict capture、加密原件存储与版本化 RawAudit 引用。
  实际回归 161 passed；九个生产文件增量 mypy 零回归，全生产类型债务为零；格式与契约检查通过。
  代码尚未部署，真实供应商留存尚未验收，详见
  [接入阶段记录](data02-provider-artifact-adoption-2026-09-14.md)。
- Research State 边界测试已提交 `18bd7560cb1112f24a23052df6f60c9fa7187c56`，独立审核中。
  当前切片声明不能作为全 Research 达到 90% 的证据。DATA-12 已完成，不重复执行。

## 接下来的开发与验收

| 顺序 | 可立即推进 | 必须证明的退出门 |
| --- | --- | --- |
| DATA-02 | 合并原件接入；部署；核验持久化挂载、密钥引用及合法 HTTPS provider/出网规则；保存真实响应并读回核对；分批取证与对账 | 生产 universe 回填保留真实观测时间，并在治理容差内与 canonical sources 对账；包括 5,533 资产覆盖、财务可用时间修复数及四个不可变发布身份 |
| EVID-01 | 完成 Facade 操作内共享读取；补多历史根、successor/replay、cutoff 与回调写入回归；真实 PG 测试；部署后重跑绑定新候选的 lifecycle | 每个生产 Evidence 读取/审批边界强制 exact user、tenant、owner authority，失败关闭；真实 root 及 owner/reviewer 生产验收必须有真实决定 |
| EVID-02 | 对真实 PostgreSQL 并发 harness 取证，核对 first-winner、successor、current-head 与 rollback | 可重复 PG 并发证据及真实授权 reviewer 的人工审批决定 |
| AUD-03 | 在依赖完成后核验迁移/回滚、outbox backlog/age、恢复、有限维度指标、告警、admin TUI、归档恢复 | 迁移和恢复观察、归档完整性及生产 owner/reviewer 的运行验收签署 |
| TAR-05 | 在 TAR-03/TAR-06 依赖完成后，对不可变候选跑 staging 负载及恢复包，收集真实事件时间线 | 1/5/10/20 用户负载、公平性、重复、worker crash、Redis 故障、模型超时、Web SLO、rollback 与真实观察门；容量及切换需真实 owner 决定 |

Facade 优化保留 `with_current` 前后两次读取、全部历史/FK/head/revocation 校验与原有预算。
先共享单次操作的仓储图并用实际模型/阶段计数证明收益；连接、alias、cutoff 或回调写入边界变化
必须失效或隔离，不能用全局缓存或增加 watchdog 掩盖生产瓶颈。

Domain 覆盖并行顺序为 Research State → R4 monitoring → R7 post-promotion → scenario reminder
calibration → R2 trial promotion。task_monitor 与 signal 已有合格实际覆盖证据；Research 当前
全 Domain 基线为 4033/5032 分支（80.147%），达到 90% 至少需 496 个额外分支。
每个切片保留同源前后覆盖，合并后再测全 Research，禁止将切片比例直接写成全模块结果。

## 尚需真实来源的输入

生产 inventory 中没有 `equity.financial.fact` 出网规则。现有 provider 行上的凭据存在性
不证明解密、令牌、网络或供应商权限有效；配置和请求须按实际值验证，禁止生成假凭据。
公告日期或响应 EOF 时间不能成为精确 available_at，capture UUID 不能成为供应商原生行 ID。
没有原生时间/身份来源的历史缺口继续发布阻断原因，不修改既有 canonical fact hash。

admin / user 1 已获用户指定为项目 owner 与人工审批账户。技术授权可以继续实现、部署和测试；
真实业务审批、质量豁免及容量决定仍须由该账户或实际授权 reviewer 作出可核验决定。
TAR 观察期只累计真实经过时间，不以模拟天数提前验收。

## 风险与回滚点

原件文件与数据库不能跨事务原子提交；审计失败保留原件引用并核对孤儿，不自动删除。
原件配置禁用可恢复旧 provider 路径。代码部署沿用标准备份及自动回滚，不恢复数据库、不清除
catalog 或旧原件。Facade 回归失败则保持当前生产候选及既有 fail-closed 策略，不晋级单元。
