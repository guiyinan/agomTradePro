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

R1 forecast promotion decision 的有界切片已完成。它只覆盖
`apps/research/domain/r1_forecast_promotion_decision.py` 及列明的 Research
unit scopes；生产 Domain 文件、provider、持久化、策略和生产验收均未改变。
最终 55 tests exit 0，目标文件分支覆盖从 89/134 提升至 129/134，关闭 40
个 baseline missing arcs；statement coverage 为 389/394。五条剩余 arcs
仍是当前不可变 Equity 构造器在上游排除的空 forecast、跨 scope、错误 authority
或非 research 输入路径，未用 `object.__new__` 等方式伪造对象。该切片的完整
原件和 hash 见 [R1 seal](../testing/research-r1-forecast-promotion-controlled-branch-increment-2026-09-14.json)。
原 sidecar `8a790ab6d3732411cbb4b4c15302cddd77a9839d6edcd2a9345a9805a8b9927b`
对应旧 Windows CRLF 工作副本；发布后的 `text eol=lf` 文件与 Git 内容 hash 为
`058e072f50fc2fd51cc53e026bf6449c89e5f581e635d859024a3eb065d33b3a`，两者内容
语义相同，旧 raw 原件保留在 var 取证目录。R2 发布 LF sidecar 为
`0a191fb4e7c7d3ff09cffc60867414a83f865b461602b56edddd1f8390e1480d`。
它是独立测试证据，不能加算为全 Research 90% 或生产 readiness；测试提交可单独
回滚而不影响运行时。

### Scenario reminder / R2 promotion boundary slice

R2 reminder 与 market-structure promotion 的有界 Domain slice 已完成。测试提交为
`f122eef16b767411a5f7aa2983c5a73fce0d64e8`，测量基于合并 DATA-02 后的
`ba1605fa229b8ae8c59114af158cdf58b8f144fa`；生产 Domain 源文件未改变。

- baseline 为 14 tests；final 为 26 tests，exit 0，failures/errors/skips 均为 0。
- `scenario_review_reminders.py` 分支从 `104/148` 提升到 `145/148`，新增唯一 41 arcs。
- `r2_market_structure_promotion.py` 分支从 `66/108` 提升到 `104/108`，新增唯一 38 arcs。
- 合计新增唯一 79 arcs，baseline arcs 无丢失；剩余未覆盖分支保留在封存 JSON，未用非法 Domain 对象补齐。
- 这组结果只代表两个 Domain 文件的受控本地单元范围，不能加算为全 Research 结果、90% 门或生产验收。

完整 JUnit、coverage、命令、源绑定与独立复核引用见
[Scenario reminder / R2 promotion seal](../testing/research-reminders-r2-promotion-controlled-branch-increment-2026-09-14.json)。
基线 `receipt.json` 与 `command.txt` 未保留，封存明确列出缺证；基线合并 stdout/stderr、JUnit、coverage
和 final 原件仍保留。源快照的 before 是 Git LF reference，after 是 Windows working-tree
raw；两者 raw 不同但 canonical LF 相同，因此不宣称同期 raw-before 等价。

## 尚需真实来源的输入

State 与 R4 补测已分别通过独立审核和 CI，并合并。环境修复后的全 Research 实际重测为
1014 passed、exit 0，63 个 Domain 文件前后 SHA 一致。真实行覆盖为
12602/13546（93.031%），分支覆盖为 4101/5032（81.498%）；89.907% 是两者组合值，
不能称为行覆盖。达到 90% 分支覆盖还需至少 428 条，下一切片补 R7 monitoring 与 contracts。
完整当前覆盖证据见
[`research-whole-domain-current-coverage-2026-09-14.json`](../testing/research-whole-domain-current-coverage-2026-09-14.json)。
两次环境失败原件继续保留，不将切片新增分支数直接累加为全 Research 增量。

在保留上述 1014-pass 历史原件和指标的前提下，合并 origin/main 后以 HEAD
`8aaf20eb8abe7ce7b26c3420d3bc985b958ec6cf` 完成一次新的完整
`tests/unit/research/` 本地 SQLite 分支测量：`1035 passed`、exit 0，JUnit 为
1035 tests、0 failures、0 errors、0 skipped，63 个 Research Domain 文件的 raw、
canonical LF 与 Git blob before/after 均一致。covered lines/statements 为
`12663/13546 = 93.481%`，branches 为 `4161/5032 = 82.691%`，coverage.py
combined 值为 `90.559%`；分支 90% 门槛需要 `4529/5032`，当前还差 368 条。
这次全量结果更新当前分支事实，但仍不是生产验收，也不把 R7 选定切片的增量
与旧 1014 或全 Research 分支分母重复相加。完整原件与 14 项引用见
[当前全量封存](../testing/research-whole-domain-current-coverage-r7-full-2026-09-14.json)。

在保留上述历史原件且不将 R1/R2 窄切片增量相加的前提下，HEAD
`e68150f509daa47b54702dd4a3a6cb5e0c31e816` 的最新完整本地 SQLite 测量为
`1048 passed`、exit 0；JUnit 为 1048 tests、0 failures、0 errors、0 skipped，
用时 444.647 秒（runner wall 469.508 秒）。63 个 Research Domain 文件的 raw、
canonical LF、Git blob OID 与 Git 内容 SHA before/after 均一致。covered
lines/statements 为 `12736/13546 = 94.0204%`，branches 为
`4231/5032 = 84.0819%`，coverage.py combined 值为 `91.3285%`；分支 90%
门槛需要 `4529/5032`，当前还差 298 条。完整原始 stdout/stderr、JUnit、coverage、
63-file source snapshots 与独立复核见
[`R1 后当前全量封存`](../testing/research-whole-domain-current-after-r1-2026-09-14.json)。
该结果仍是本地 Research unit 取证，不是 PostgreSQL、VPS、供应商或生产验收，
也不宣称将窄切片的分支数叠加到全量结果。

在保留上述 1048-pass 历史原件且不将 R1/R2 窄切片增量重复相加的前提下，HEAD
`007203ed2cf62336e2e847357045ed64f585cd15` 的最新完整本地 SQLite 测量为
`1060 passed`、exit 0；JUnit 为 1060 tests、0 failures、0 errors、0 skipped，
测试进程用时 `720.476780` 秒，进程树 CPU 观测为 `402.09375` 秒。63 个 Research
Domain 文件的同期 working-tree raw、canonical LF、Git blob OID 与 Git 内容 SHA
before/after 均一致。covered lines/statements 为 `12814/13546 = 94.5962%`，
branches 为 `4310/5032 = 85.6518%`；coverage.py combined 值为 `92.1735%`。
分支 90% 门槛需要 `4529/5032`，当前还差 219 条。完整原始 stdout/stderr、JUnit、
coverage、63-file source snapshots、校正后的 coverage 语义和独立复核引用见
[`R2 后当前全量封存`](../testing/research-whole-domain-current-after-r2-2026-09-14.json)。
原始 receipt 中 `statement_coverage_percent=92.2` 的字段标签错误已保留并由派生解释
记录纠正；92.1735% 是 combined 值，不能称为 statement coverage。该结果仍是本地
Research unit 取证，不是 PostgreSQL、VPS、供应商或生产验收，也不将历史 1048 或窄切片
新增分支重复加入当前分母。

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


## 2026-09-20：生产收口任务包重新核对

当前实读生产为 `439468482` / `20260920184626`，v17 public snapshot 与 Audit loader 已通过，
但 audit off/outbox false/selector 缺失仍阻断发布；历史 v14 snapshot mismatch 不再作为当前原因。
09-19 校验原件范围已为 5,565；财报来源证据与四 Publication 对账仍未完成。
R1–R8 owner 批准文件的 Git LF 哈希均通过，canonical dry-run/registration 未完成。

AUD-05 保持唯一代码焦点直至原子 corrective activation、immutable successor/rollback 和测试证据
完成。DATA-02 → EVID-01/02 → AUD-03 的生产退出顺序不变；真实 authority 输入准备与数据前置
可交叉，但不得用 fixture 填业务主体。独立 staging 缺失使 TAR-05 转为 blocked_external，
维持 inline 并发=1。TUI 实际 candidate/Web/Prometheus 漂移使旧 09-30 时间门失效，需真实重新绑定。
Research 4310/5032 是历史全量分支基线，AUD-05 释放后才能另起测试主线并重测，不重复累计旧切片。

[脱敏实读封存](../deployment/production-closure-baseline-revalidation-2026-09-20.json)与
[分项恢复条件](../reviews/production-closure-2026-09-20.md)保留本轮范围、无生产写入事实和未验收风险。
