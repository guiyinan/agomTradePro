# 发布阻塞清零综合实施方案（2026-08-29）

> 状态：执行中；`DATA-01` 已关闭，`DATA-04/05` repository 修复已随当前候选部署，部署后 PostgreSQL client 只读样本稳定；2026-09-02 09:24Z 曾出现 Web liveness unhealthy/公网 502，15:38Z 受控 web-only restart 后恢复 healthy，`DATA-02/03` 继续 fail-closed；TUI successor 的机器 UAT、清理矩阵与隔离回滚已形成，旧 retained source 已因该次重启作废并仅保留为历史，等待重启后首个真实样本及新的 14 日窗口
> 机器状态真源：`governance/active_plan_registry.json`
> 适用 closure units：`DATA-01/02/03/04`、`AUD-03/04`、`EVID-01/02/03`、`STRAT-01/02/03`、`TUI-01/02`、`TAR-05/06`、`AI-01`、`QMT-01/02`
> 原则：本文只编排既有 unit，不建立第二套状态、不降低阈值、不代签、不伪造 PIT/OOS 历史，也不把生产写入授权扩大为实盘交易授权。
> 授权记录（2026-08-30）：用户已授权 A1–A8 动作包继续执行；每个动作仍受其前置门、精确目标、回滚点、外部环境和真实 owner/reviewer 决策约束，授权不等于验收通过。

## 2026-09-13：DATA-16 来源证据与发布身份修复范围

EVID-08 仓库退出后，下一项唯一 repository focus 登记为 DATA-16，作为 DATA-02 的代码前置。
它覆盖四段同一契约：Tencent HTTP 原始响应完成时间和 exact bytes SHA-256；适配器到事实及
冻结 member 的证据保真；不可重写的 policy 版本与覆盖所有决策字段的新 Publication 编码；
generic/batch/rebuild/idempotent 发布前与 current 读取时的 typed fail-closed 校验。
响应完成时间只证明本系统此时已取得该响应，不代表供应商最早披露时间；批量响应哈希明确
标为共享 batch scope，不将数值规范化哈希冒充原始 HTTP body 哈希，也不覆盖 observed_at。

完成标准以 registry 的 DATA-16 exit_gate 为准。先补有意义的缺口回归，再实现上述完整链路，
保持 legacy Publication 哈希及历史查询原义，并检查所有哈希重算、重建、质量与 replay 引用方。
增量 mypy/debt、格式、新鲜度/catalog、架构和治理门全部通过后才进入候选部署。
风险为旧事实原始证据未知、可变 fact 行污染既有 member、同版本 policy 重写及幂等早返回
绕过校验；缺证据一律阻断，不通过历史回填虚构时间或哈希。回滚点为本分支起点
main b18b18029f90af4b23693426a1f489af44ffe2b2；新增 schema 采用扩展方式保留旧编码。

EVID-08 标准备份/code-only 部署与真实 admin 的显式回滚 Facade 事务复测继续并行；它们不
关闭 DATA-02 的全 universe 四数据集、财务可用时间、来源一致性及生产决策验收。
DATA-12/15 已完成，不重复执行已收口覆盖率主线。未完成项仍由机器 registry 唯一维护。

## 2026-09-13：权威读取性能、生产复测与下一阶段范围

后续 repository 工作登记为唯一 focus `EVID-08`：Authority V3 facade 的整次 `_locked` 操作接入
已有 `validation_graph_operation`，只复用 exact immutable JSON 解码和成功的对象校验，禁止启用
write/current/ORM snapshot 缓存。先用生命周期接线、操作退出/失败、changed payload 与 callback
两次 current/drift rejection 测试验证语义，再比较同一 repeatable-read 代表性完整图的重复 restore
CPU/解码/SQL。只读 restore 基准不是新写入或生产并发验收；未验证前 EVID-08 保持 active。

EVID-08 首次完整隔离 PostgreSQL 批次实际结束为 `6 passed / 3 failed / 3,727.20s`。
successor 自指 predecessor 的原始 SQL 篡改已经被 `_restore_root` 的 ledger seal 校验拒绝；
失败是测试仅接受 predecessor/successor 文案，不能据此声称生产校验被绕过。另两项分别是
并发测试未进入 Simulated repository 的 private UOW，以及 facade fixture 未建同 alias 的
Simulated source ledger 表。修正完整 fixture 与合法事务调用后仍须重跑真实锁竞争及生命周期；
此前成功的纯组件测试和 CI 不代替该批次。完整 helpers 复核及 Luna max 独立复核确认，
既有 `_validate_root_slots` 已覆盖物理 predecessor 到 canonical supersedes 的交叉校验，
重算非秘密 seal 也不能绕过它；删除重复生产补丁和镜像测试，仅保留 fixture、合法 UOW、
准确拒绝点与真实锁 SQLSTATE `55P03` 断言的修正。相关单元 59 项与非 PG composition 10 项通过，
修正后的三项 selector 批次结束为 `2 passed / 1 setup error / 751.42s`：实际源锁竞争和
predecessor 篡改拒绝均通过，facade 在 mixed-node 选取下未发现 owner_alias fixture，
没有进入业务测试体。该批次后隔离库再次确认零公共表。composition 显式导出同一个 fixture，
主代理复验 mixed 三项 `--setup-plan` 成功解析完整依赖，`no tests ran / 0.61s`；该命令仅验证
fixture 可见性，不算 PostgreSQL 业务验证。剩余 facade 生命周期已单独重跑，结果仍待完成。

facade 重跑随后实际失败 `1 failed / 254.89s`：fixture 完整解析并进入 issue，当前 Evidence V5
端口返回 None，Owner 层据此 fail closed。继续核对 fixture 的 live physical source、actor 与
时点前置，不把 canonical ledger 的可恢复性视为完整 current 图，也不以 mock 当前权限绕过；
该结果不能记为生命周期通过或未经诊断直接认作生产缺陷。

进一步核对确定 historical fixture 只封存 synthetic ActorSource，没有对应 raw authentication、
user、RBAC 父源，也没有 live SimulatedSourceV2 行；该历史图不满足完整 current Facade 前置。
测试支持按专用 disposable alias 写入三类真实 canonical raw roots，通过既有 Capture 用例生成
derived actor，再以 optional source 注入已有 V5/Owner seed；默认历史 fixture 保持原义。
PhysicalV2 对应 SourceV2 由完整字段精确重建并断言 content/raw seals，通过合法 private UOW append。
principal 时间改取真实 actor source 的 authenticated_at/valid_until，生命周期时点留有到期余量，
显式 preflight 检查 live physical 与 current Evidence。Luna max 独立复核无 blocker；非 PG
composition `10 passed / 1 deselected / 0.82s`、py_compile、Black/isort/Ruff、diff check 通过。
修正后的单项真实 PG 生命周期正在执行，以上不替代其业务通过结果；EVID-08 仍 active。

该次实际结束为 `1 failed / 273.03s`：真实 raw-source Capture 和合法 replay 已执行，随后
PersistedEvidence 的既有时序检查拒绝 `approval_valid_until > actor.valid_until`。夹具的 approval
窗口长于临时 capture TTL，不能缩短或绕过生产校验。改为从同一个 Domain Evidence fixture 的
完整 approval deadline 推导 raw validity 与 capture TTL，并留 1 分钟余量；不会改写 Evidence
窗口或默认历史 fixture。失败后隔离库再次验证零公共表，Black/isort/Ruff 通过，单项实际 PG
继续重跑；生命周期通过仍未证实。

该次随后实际结束 `1 failed / 218.68s`，PersistedEvidence 的完整有效期绑定已通过，
assignment append 按既有 `recorded_at <= now` 门拒绝：测试时钟仍停在更早的 Capture 时点。
在 Capture 真实落账后，将 fixture clock 前移到 Evidence recorded_at+1 分钟再持久化后续图，
保留事件原始时间与生产时序检查；失败后隔离库零公共表。Black/Ruff 通过，单项实际 PG
正在继续执行，不用历史 ledger 可恢复性、pure Domain current 或 CI 替代它的完成结果。

该次实际结束 `1 failed / 247.33s`：完整 Capture、approval deadline 和 assignment persistence
时序均已通过，测试随后误读 `EvidenceV5.reobservation`；完整定义的路径为
`EvidenceV5.subject.reobservation.current_physical`。只修正测试属性访问。主代理按实际 Domain
fixture 预检 SourceV2 content/identity/raw hashes、Source/Evidence current 与 current command，
全部通过，未执行 fixture seed；Black/Ruff 和 diff check 通过。失败批次后的隔离库已验证零表。
本次重跑前额外 host cleanup 连接发生 timeout；容器实际接受连接，随后唯一测试连接正在创建
专用 ledger 表，未重启数据库或另起重复测试。单项真实生命周期继续执行，尚未宣称通过。

首次生产完整图 cProfile 基线已返回：同一个 READ ONLY / REPEATABLE READ 快照内两次 exact
get_winner restore 耗时 `2,576.715s`、CPU `2,380.099s`、`58,492 SELECT`、DB execute `162.046s`。
它包含 profiler 开销；候选阶段只有 started，连接在 3,600 秒超时后失去输出，不能计算性能提升。
曾核实后台仍存活，随后精确 PID 检查确认进程已退出；没有终止服务或重启写入。替代诊断于
`2026-09-12T21:18:29Z` 使用独立远端目录启动，runner PID `2423267`，脚本 SHA-256 为
`8a01a967b12554f176a5f55b73be766b87080d972863713be540869eb9529970`。
该次仍测同快照内完整 baseline/candidate，stdout、stderr、exit code 与起止时间持久保存。
实际于 `2026-09-12T22:21:35Z` 结束，exit code=0，精确 runner 已退出。
[完整 cProfile 检查点](../deployment/sprint-evid08-complete-graph-cprofile-2026-09-13-c8bb9b780.json)
封存同快照两个 completed stage：baseline elapsed `2,636.320s` / CPU `2,473.226s`，
candidate elapsed `1,128.302s` / CPU `1,014.602s`；两者均 `58,492 SELECT`，
DB client execute 分别 `174.073s` / `170.719s`。该样本 elapsed 减少 57.20%、CPU 减少 58.98%，
只支持 read-only prerequisite 的 operation context 复用，不表示生产新写入或并发性能已通过。
top 20 cumulative functions 不能证明准确解码数量；完整图原始 decoder / decorated validator
计数使用独立 reviewed 诊断，前一 job terminal 后才启动，不重叠测量。该计数与真实 facade
生命周期仍待完成，EVID-08 和 PR #36 均不晋级。

[独立完整图解码计数检查点](../deployment/sprint-evid08-complete-graph-decode-work-2026-09-13-c8bb9b780.json)
实际于 `2026-09-12T22:49:53Z` terminal exit=0，精确 runner `2453471` 已退出。
每个 stage 的两次 exact restore 均断言同一快照全部 4 个 `(PK, content_hash)`，未启用 SQL snapshot
缓存。已加载且有装饰器的 raw decoder 原函数调用为 baseline `329,320` / candidate `40`，
decorated object validator 为 `1,838,056` / `29,864`；两者均 `58,492 SELECT`。
该独立样本 elapsed 减少 51.35%、CPU 减少 55.70%，包含 counter wrapper 与顺序测量影响。
它只统计显式列出的已加载 decorated functions/class attributes 原函数入口，不能称所有
Python/JSON 调用或所有未装饰 validator 的总量，也不是新写入/并发验收。checkpoint 封存并
逐份核验 9 份实际 raw/instrument artifacts；它与 cProfile 的不同 cutoff/开销不合成单一样本。
代表性完整图测量前置已形成，真实生命周期仍待通过；EVID-08 保持 active。

随后真实 Facade 生命周期完整结束：`1 passed / 1,716.17s`，进程 exit=0，隔离库清理后公共表=0。
真实 raw roots/Capture、live SourceV2、current Evidence 与 issue/current/with_current/revoke/exact
均执行通过。[生命周期检查点](../testing/evid08-authority-validation-lifecycle-2026-09-13.json)
封存 7 份独立批次 XML 和实际静态/治理/清理材料，共 16 份嵌入证据逐字节核验；原始
`6 passed/3 failed`、修正 `2 passed/1 setup error` 和单项失败仍分别保留，不拼成一批九绿。
[仓库退出证据](../testing/evid08-authority-validation-repository-closure-2026-09-13.json)绑定
代码 head `7d2138b7df8af975a693f6233fffdb07ecd57f2e`、生产 Git blob SHA、两份已封存完整图样本及
最新 10 项非 PG composition、增量 mypy/debt=0、四个 fixture/support 格式检查、单行架构/audit=0、
全治理=0 和该 head 全部 CI success。`EVID-08=completed`，registry v92 释放 repository focus。
此处仅完成仓库退出门；优化尚未部署，生产写入/并发性能和 DATA-02/EVID-01/02 不晋级。
后续按已有 VPS 授权进行标准备份、code-only 部署及真实 admin Facade 事务复测，显式回滚测试写入，
核对 Owner V3 headers/payloads 与原 current 恢复；序列号前进不伪装成全库无变化。

同候选的[DATA-02 分数据集诊断](../deployment/sprint-data02-dataset-gap-checkpoint-2026-09-13-c8bb9b780.json)
保留只读事务、严格预览失败和 200 资产来源预检的原始响应/脚本及 SHA：completed-session price
合格为 `1/5,533`，最新 valuation `5,533/5,533` 均缺 observed_at；financial 候选已有全资产覆盖，
null available_at 修复暂无 eligible 行。preview 的 ready 仅是候选覆盖，不能记为 freshness 通过。
公共 provider 对 frozen universe 首 200 资产返回 quote/valuation 各 `200/200`、源日期均为
2026-09-11，但新 valuation adapter 仍全缺 available_at，将被标为 available_at_unverified。
因此 EVID-08 验证后先补实际响应首次可见时间的 source-bound 传递，再执行有界事实修复；
禁止直接 patch 历史 observed_at/available_at 或把响应抓取时间替换为源观察时间。

随后[完整冻结资产池来源预检](../deployment/sprint-data02-full-source-preflight-2026-09-13-c8bb9b780.json)
补齐源读取范围：第一次受控预算耗尽前保留 4,200 个代码的完整批次，offset=4,200 的续查补齐
其余 1,333 个。两次独立只读快照的 universe SHA 与 completed session 相同，合并 quote 和
valuation 均精确覆盖 `5,533/5,533`、无重复或缺口，源观察日期全为 2026-09-11。
全部估值 available_at、raw_payload_hash 仍缺失；源读取覆盖不等于已写入事实库或形成 Publication。
checkpoint 封存 16 份实际输出/脚本/handle，验证 112 份响应体：56 份 HTTP 502、56 份 HTTP 200；
配置 quote 路径由 Eastmoney 失败后回退 Tencent，全部返回事实的 source 为 tencent。
保留实际 response.content bytes 的 hash、压缩原文及接收时间，不伪装成已进入 Domain 的单资产
raw hash 或全局首次发布时间。该预检没有财务修复、runtime 开启、Publication 切换或容差对账，
也不证明 failover 一致性、实时 quote freshness 或 DATA-02 退出门；机器状态保持不变。

下一有界开发包必须同时覆盖四条链：source Snapshot/adapter 传递 witnessed completion 与明确
scope 的 raw evidence；catalog inputs 版本化 policy 的 required_evidence；batch/rebuild/幂等及
generic publish 的统一 typed fail-closed 检查；旧 current 的 active policy 与成员证据检查。
policy 初始化真源为 publication_policies.json，经 initialize_data_center_catalog 同步落库，
禁止修改同一个版本身份来掩盖策略修订。保留既有 observed_at、历史事实和 Publication hash 身份，
不得只填 source 字段而让旧 unverified current 继续可决策。EVID-08 验证完成前不启动该 repository 包。

Luna max 只读复核补充下一包的时间和身份边界：valuation publication 的 `as_of=max(observed_at)`
是源数据边界，response 完成时间作为 witnessed availability 可以晚于它；应检查
`available_at <= fetched_at <= published_at`，current 再检查实际查询知识时点。完整快照可用边界
取成员 availability 的 max；缺失值不能用 min/oldest 混过。历史 `get_as_of` 已使用
`published_at <= 历史查询时点`，保留该可知性门。其他实体的 vendor published_at 语义不同，
不能直接复用或反转其时间规则。typed reference/member 需保留对应 availability 与原始证据。
现有 digest/UUID 只绑定 member refs，policy_version 未参与幂等身份；下一包须以覆盖决策字段的
稳定 policy content identity/hash，加 policy version 进入新的 versioned publication encoding，
并同步 quality/replay 等重算调用方。旧 publication 保留原 hash 编码，不静默重解释；初始化
不得以同版本 upsert 改写策略意义。上述仍是已核实的设计前置，未实施或完成生产修复。

补充的[估值 availability enforcement 检查点](../deployment/sprint-data02-valuation-availability-gap-2026-09-13-c8bb9b780.json)
纠正一个必须区分的边界：`available_at_unverified` 被投影为 degraded，并不表示 publication/current
已硬性阻断。现有纯 Application 测试与本地 fresh 控制复现实验均允许该成员发布，并返回
`must_not_use_for_decision=false`；生产只读策略查询也确认 required evidence 仅有 source、observed_at、
payload_hash。该实验不宣称实际历史生产 Publication 当前 fresh，也没有创建或切换生产 Publication。
下一 repository 包必须在实际响应时间/hash 传递之外，证明 batch publish、current rebuild、幂等返回及
旧 current member 的缺失 availability 均 fail closed，再领取 DATA-02 Publication 修复批次。

[AUD-03 只读 backlog 起点](../deployment/sprint-aud03-backlog-readonly-2026-09-13-c8bb9b780.json)
在 2026-09-12 20:41:34Z 记录两条 due pending、零 claimed/delivered/failed，最旧事件年龄约 19,571 秒；
runtime 为 off、outbox disabled、authority selector absent。这是后续恢复起点，不是已开启 worker 的
异常，也不证明恢复时长、无重无丢、HTTP metrics、alerts、TUI 或 archive/restore。AUD-03 状态不变。

随后[真实 HTTPS metrics 检查点](../deployment/sprint-aud03-http-metrics-2026-09-13-c8bb9b780.json)
在 20:46Z 记录健康与 metrics 均为 200，七个 outbox gauge 仅使用 owner=audit 低基数标签；
pending/due_pending 各 2，其余 0，与前述只读账本计数一致。该样本补齐当前候选的 HTTP 指标取证，
不代替告警、恢复、admin TUI、archive/restore 或生产签收；本地采集时钟与服务器时钟不作精确同步假设。

[真实 admin TUI 读取检查点](../deployment/sprint-aud03-admin-tui-read-2026-09-13-c8bb9b780.json)
随后保留 admin/user1 的 screen、overview 和默认 health read-action 实际 HTTP 结果，均为 JSON/200，
默认动作 outcome=success。它走既有内部认证，没有新建 credential 或执行 approval/dispatch/AI。
健康主表只有 component/status/message/checked_at 四列；pending=2 与年龄约 20,549 秒仅在 debug raw
数据中，不在主表。AUD-03 用户验收仍须验证首屏可见积压条数、年龄与恢复状态，不能把读取 success
当作运营主任务已完成；浏览器视觉、告警、恢复、archive/restore 与签收仍待真实证据。

PR #34 已通过全部 CI 并合并，生产当前绑定
`c8bb9b780bcd5181066aa4f8b8a4b331b8ac19cc` / `20260913014501` /
`sha256:5dd37368b64f735b7850647659ae18e07684eb7d7444d99baf0a900d087943ea`。
部署前备份、迁移/schema、Django、TUI、Qlib、TLS、Celery 和容器健康均通过。
[生产性能检查点](../deployment/sprint-data02-authority-performance-checkpoint-2026-09-13-c8bb9b780.json)
记录候选、生产操作事实、计时、独立查询与限制；它是任务观测摘要，不是独立签署验收报告。

已完成的有界实现是读路径 exact immutable read 复用：只有 `get_current` 的同 alias Account
ledger 锁和 Simulated physical source 锁全部获取后才开启；provisional row 只发现 composition
selector，完整 canonical current/head/revocation 校验仍决定权限。写路径及 `with_current` callback
不启用缓存。Luna max 在补齐跨 App 物理来源锁后复核无 blocker。

账户 631 的真实新图完成后，生产再次仅同步 `000001.SZ`、`publish_current=false`：新增一条
accepted quote、一条 success canonical event 和一条相同 payload hash 的 pending outbox。
权威预检 13.57 秒、quote 同步 19.29 秒、runtime 开关窗口 34.09 秒；event recorded_at 到结果
envelope 观测为 12.30 秒。独立完整 reader 读取为 14.52 秒、1,824 SELECT、DB execute 4.53 秒。
此前内层 get_winner 在三个 root 上为 118–125 秒、7,946 SELECT；新测量覆盖完整 reader 和四个
root，不能据此计算同工作负载的精确百分比。独立清理确认 off、outbox disabled、selector absent。
quote 源观察时间为 2026-09-11，周末 accepted 存储不表示 fresh/current 决策资格，未切换 Publication。

剩余目标明确分开：新建 Evidence V5 + Authority V3 图在 runtime 开启前仍花约 50 分钟。只读 PG
活动显示 ClientRead/idle in transaction，下一步先定位 Python restore/闭世界递归验证的重复工作。
首次远端脚本超过本地 1,800 秒 timeout 后继续持锁，已精确终止旧进程组使事务回滚；重试完成，
本地 ignored helper 增加显式有界 timeout。各写阶段精确时间未留存，不补造分钟分解。

| 下一工作包 | 完成标准与回归范围 | 风险与恢复点 |
|---|---|---|
| 写图性能定位及最小实现 | 先保留真实锁、mutation 与 exact-current 语义，测量重复 restore；补 successor/revocation/rollback、跨来源变化及并发测试；生产 Python 通过类型/架构门 | 不把读缓存直接扩到写路径；代码可独立回退，生产图保持 append-only |
| DATA-02 有界批次 | frozen 5,533 资产覆盖、完成交易日分布、financial report-date、四 Publication identity 与 canonical 容差对账全部满足 | partial/stale/超差停止并保留 checkpoint；不得把单资产 smoke 记成全量完成 |
| EVID-01/02 → AUD-03 | 真实 PG first-winner/lifecycle 与 candidate-bound 签收；再做 recovery/metrics/alerts/admin TUI/archive/restore | 本次一条 pending outbox 不证明 delivery 或恢复验收 |
| TAR-05 | 独立 staging、专用 Worker、真实负载/恢复证据与自然观察窗口 | 当前生产 VPS 不改名为 staging；时间门未满足不晋级 |

本阶段部署回退点为此前 release `20260912213853`，数据库恢复点为标准部署生成的
`postgres-20260912-200207.dump`；本轮没有执行恢复。DATA-12/15 不重复领取。
DATA-02、EVID-01/02、AUD-03、TAR-05 仍为 `awaiting_production`，Goal 继续 active。

## 2026-09-12：DATA-02 单资产审计写入与候选重绑定检查点

PR #32 已在全部 CI 通过后合并，生产部署绑定
`ee872a51bb0967e3d822ec0d436991f4f2329c4c` / `20260912213853` /
`sha256:470c4fcac0a032dd3a57f79e5d9dbee1942bc2a2ab6d892cd3f15f35ea35934d`。
标准部署流程先生成 PostgreSQL/Redis 备份，再完成 migration、Data Center schema、TUI metadata、
Qlib、HTTPS/TLS、Celery 和容器健康检查。完整候选与备份事实见
[生产检查点](../deployment/sprint-data02-audited-quote-checkpoint-2026-09-12-ee872a51.json)。

用户已明确把 `admin/user_id=1` 指定为本项目 owner 与人工审批账户，并授权本次部署和生产受控测试。
测试通过正式账户创建、raw authority publisher、Evidence V5 和 OwnerTenantAuthority V3 入口建立
独立账户 630 的真实治理图；随后仅对 `000001.SZ` 执行 `publish_current=false` 的一资产 quote 同步。
生产结果为 `stored_count=1`，quote 的 `quality_status=accepted`，同一写事务记录一条
`data.fetch.completed/outcome=success` 事件及一条 payload hash 相同的 pending outbox。独立后检确认
两套治理图各自唯一，审计 runtime 已恢复 `mode=off`、outbox disabled、selector absent。

两个失败路径也按事实保留：账户 629 的重复 Evidence V5 root 被唯一约束拒绝；账户 630 首次四分钟
有效期在完整当前态复核期间到期，Authority V3 fail closed。两次治理事务均回滚，runtime 未遗留开启。
最终成功批次使用 50 分钟受控窗口。事件写入到结果 envelope 观察相隔约 20.9 分钟，显示不可变证据图
的写后读取/解码仍是扩大批次前必须处理的性能问题；该耗时不改写已经成功提交的一资产原子写事实。

本检查点不关闭 canonical unit。`DATA-02` 仍缺 5,533 资产 quote/valuation 覆盖、完成交易日分布、
financial report-date 修复、四个 publication identity 与 canonical 容差对账；`EVID-01/02` 仍缺
PostgreSQL first-winner 并发、successor/current-head/revocation、rollback 汇总及独立 owner/reviewer
签收；`AUD-03` 仍缺 backlog recovery、metrics/alerts、admin TUI、archive/restore 和生产签字；
`TAR-05` 的 staging、容量、chaos、恢复与自然观察窗口未启动。

## 2026-09-10：续跑评估与实际关键路径

本节承接用户要求的 `DATA-02 → EVID-01/02 → AUD-03 → TAR-05` 顺序，优先于下文历史排期。
应用 Goal 已创建，worker 指定 `gpt-5.6-luna / max`；主代理负责派工、完整 diff 审查、最终验证和
机器状态晋级。仅一条 repository 测试补强线，另一 Luna 只读核验生产前置，不执行生产变更。
`DATA-12` 已于 2026-09-06 完成，不重新领取；本轮 task_monitor/research/signal 分支测试是用户
明确要求的后续补强，历史行覆盖率恢复与新增分支覆盖不能重复计数。

该补强登记为唯一 repository focus `DATA-15`，验收分支目标为 task_monitor 100%、research 80%、
signal 90%，各 Domain 行覆盖率至少 90%。比较同一选定测试范围的前后报告；该有界目标不承诺
消除全部理论分支，也不替代完整 Nightly 的全仓分母。只有实际报告与回归满足时才关闭 DATA-15。

### 已核对的新事实

后续检查点优先：并发提交 `ca11af075/404e68c0f/fd56f1a46` 记录了 successor 部署及 TUI 绑定。
主代理保留这些变更，独立取得[successor 只读证据](../deployment/sprint-successor-readonly-2026-09-10-dba9ab2c.json)：
当前为 `dba9ab2c8c18b824a6ed60d90b0765e020e6908d` / `20260910002501` /
`sha256:7a42abe215ba5fe80af304758c0f7cd74ee221d88867e7eedd66badbc9904706`，前后 Docker identity
与 manifest 一致。actor/scope=0、audit 三项配置缺失、publication 1/23/80 及 valuation 缺失仍成立。
下列 122373b1 采集和首个本地 TUI 检查点保留为历史，不覆盖 successor。
这三个并发提交没有改动本轮三个 Domain 或既有测试，覆盖率采集可按同源文件 hash 继续；
旧 TUI 配置 hash 已变化，必须用新配置重新判断 TUI readiness。

[生产只读证据](../deployment/sprint-preflight-readonly-2026-09-10-122373b1.json) 同时保留原始响应、
SHA-256、SQL、命令、采集时间及局限。容器镜像与 OCI revision、容器 release manifest 和第二次
Docker identity 读数一致：生产已是 `122373b180da603cc9845a8721f79c3ad681afa9` /
`20260909232516` / `sha256:3f5f7a8ebe2be8120fbce2e9cfb33c1065030643f9999cea4e8fe25d413256a0`。
这只证明所观测候选身份，不补造该版本的部署授权、UAT、回滚或完整验收。

- PostgreSQL repeatable-read/read-only 查询：actor authority 与 owner/tenant authority 均为 0 行；
  audit event/outbox 均为 0 行。500 条 applied migration 记录不等于已验证零 pending migration。
- production snapshot 仍为 version 2，`audit.system_event.mode/outbox_enabled/authority_selector`
  三项均缺失。没有真实 actor/scope 来源时不能构造有效 audited refresh。
- 当前 published quote/price/financial 成员数仍为 1/23/80，valuation publication 缺失；
  本次没有执行 provider fetch、数据修复、publication 切换或 runtime 启用。
- 公共 HTTP health=200、decision-ready=503；audit health 返回 OK。release identity 未认证返回
  403，ready 请求在 12 秒超时。公共请求不绑定候选；单次超时不证明持续宕机。
- 不继承旧候选的 TUI/TAR/AUD 观察结论。新候选的首个有效 retained sample 和完整窗口尚未核验，
  不能从部署日期或旧排期直接算出验收日期。

### 调整后的交付顺序

主线顺序保持，但 `DATA-02` 的审计身份/runtime 是实际前置，因此先与 `EVID-01` 输入准备交叉，
不能等 DATA-02 全部结束才开始找身份。已有有界生产整改授权继续有效；缺少真实输入与缺少授权
分别记录，不重复请求泛化确认。

| 时间箱 | 主要交付 | 进入下一步的条件 |
|---|---|---|
| D1 | 当前候选绑定；真实 Account 主体/tenant/owner/scope、runtime selector 与数据集比较合同清单；覆盖率前后基线 | 来源可核验，缺项明确，不生成虚构权威记录 |
| D1–D2 | DATA-02 有界 quote/valuation 回填、逐批 checkpoint、source-time 和 canonical 对账 | 身份/runtime/比较规则/精确目标/停止线/恢复点齐全；partial/stale/超差不晋级 |
| D2–D3 | EVID-01/02 的真实主体接入、append-only/current-head、撤销及 PostgreSQL 并发证据 | 真实 owner 决定和来源齐全，生产验收与隔离数据库测试分别取证 |
| D3–D4 | AUD-03 当前候选 writer/metrics/alert、恢复、archive/restore 与业务操作验收 | 不以空 outbox 或无指标样本代替真实 writer/recovery 结果 |
| D4–D7 | TAR-05 独立 staging envelope、专用 Worker、非计费 provider、阶梯负载和恢复准备；满足前置才执行 | 真实 staging/身份/资源及动作边界齐全；完整观察期自然经过后才能收口 |
| 并行 | task_monitor/research/signal 实际遗漏分支的行为测试、聚焦回归、来源绑定覆盖率报告 | 不降低现有门槛，不修改生产逻辑来追求比例，不把局部报告当全仓 Nightly |

D1 从相应动作的技术前置齐全后起算。当前登记的 DATA-03、EVID-03、STRAT-02/03、AI-01 仍按
各自依赖解锁；QMT 保留外部阻塞，不计入本轮内部开发完成条件。

一周可作为有界实现和阶段证据的预算，不能承诺关闭约 10 个 canonical unit。DATA-02/EVID/AUD
的真实输入、TAR 的 staging 和 14 日观察、策略 PIT/OOS 样本都影响关键路径。周末分别报告
`exit gate 完成 / 阶段证据完成 / 真实输入或时间未满足`，不以拆分工作包凑 unit 完成数。

### 一次性真实输入清单

| 输入 | 现有入口与精确约束 | 缺失时的下一动作 |
|---|---|---|
| Account 主体与范围 | 真实 user/actor、tenant、owner/scope 与上游 assignment 来源；`capture_account_actor_authority` 默认 dry-run，不能代替 owner/tenant root | 提供既有记录/输入文件位置，先校验来源和 exact-current 链 |
| 审批角色身份 | OwnerTenantAuthority Domain/Application 与 DB `acct_own_ten_auth_actor_ck` 均要求 claimant/approver 的 actor、user ID 不同 | 同一真人可承担角色，但不能把一个 user ID 同时填进两端；两个实际角色账户仍须真实来源。若业务要求单账户流程，应先有界审查并同步修改契约，不能直接绕过约束 |
| Audit runtime | active profile 中 mode=`off/shadow/required`、outbox_enabled=bool、authority_selector 六字段：actor/scope 各自的 source_id/version/content_hash | 先有真实当前来源，再通过 Config Center typed profile patch/activation 接入；哈希不能自造，定义初始化不填实际值 |
| 数据集对账 | quote/price/valuation/financial 各自 source/operator、字段、单位、源观察时间及治理容差 | 从既有 catalog/rule/owner 来源解析；宏观 1% 不自动成为其他数据集比较合同 |
| EVID/AUD 验收 | 实际 approval/current-head/撤销来源，PG 并发结果；当前候选 migration/outbox/metrics/alerts/tui/recovery/archive 七段事实 | 现有 recorder 是离线外部输入验证器；其成功不表示已经抓取生产事实或执行恢复 |
| TAR staging | 非生产 URL、不可变 candidate/runtime/workload、完整 SLO query map、有效精确 preflight、20 个 actor credential 引用和 Prometheus credential 引用；独立 Worker/queue、prefetch=1、non_billable_stub、MCP disabled | 先 validation-only，再在既有动作边界和真实环境齐全后执行；不把 production VPS 标成 staging，凭证不得写进计划或聊天 |

最小代码入口已存在：DATA-02 `repair_active_a_share_current_facts` 的 execute/operator/source/batch-size
及 1..500 批次约束；EVID `capture_account_actor_authority`；AUD
`record_aud03_operational_observation_evidence.py`；TAR `run_terminal_runtime_staging_baseline.py`。
本次只读审查未证明这些入口缺实现，不以新增一套 collector 替代缺失真实输入。具体执行仍先核对
相应命令帮助、候选及当前输入 schema，不将本表当可直接执行的生产授权回执。

### 本轮恢复点与验收边界

当前只读取证无生产回滚动作。测试与文档可按本轮 diff 单独撤回，不涉及数据库或部署回退。
原始工件及其 sidecar 已重新计算校验；active-plan checker 在本轮修改前通过。覆盖率测试结果、
最终治理检查和精确下一步由后续 material checkpoint 补充，未执行的检查不记为通过。

首个[本地检查点](../testing/sprint-local-checkpoint-2026-09-10.json)：主代理独立运行 Task Monitor
新增行为测试，1 passed；这不满足整个 DATA-15 覆盖率退出门。TUI readiness 命令 exit=0，
但业务结果为 2/10 DENY，仍绑定 `20260908163105` 且 first_retained_sample_at/eligible_at 均为空；
不能把工具正常退出记为 TUI 验收通过。DATA-15 登记后的 active-plan checker 为 47 units、
45 paths、0 violations；生产证据 raw hash 与 sidecar 再次核对一致。

### DATA-15 实质进展检查点（2026-09-10）

[同源局部覆盖率检查点](../testing/data15-domain-checkpoint-2026-09-10.json)保存前后 JSON、JUnit、
240 个源码/测试文件 hash 和采集限制。基线分两批共 1264 passed，新增 Task Monitor/Signal
9 passed，Research 第一片及关联测试 50 passed；另一次主代理聚焦回归 62 passed。

| Domain | 基线行 / 分支 | 当前增量行 / 分支 | 状态 |
|---|---|---|---|
| task_monitor | 97.32% / 50.00% | 99.11% / 100.00% | 局部目标已达到 |
| research | 89.88% / 73.53% | 90.27% / 74.60% | 距 80% 尚需 272 个分支 |
| signal | 94.71% / 87.82% | 95.73% / 90.36% | 局部目标已达到 |

该检查点采用保留基线后追加覆盖率的并集；最终完整相同选定范围回归尚未执行，不能称作 Nightly
或 DATA-15 完成。Luna 下一片仅补 state model 的公开行为分支，主代理复核后再测实际增量。
生产 Python 和现有覆盖率 floors 未修改，无生产写入。

successor TUI readiness 重新运行后依然 DENY（2/10），已绑定 `20260910002501`，
commit=verified_with_snapshot、binding=true，但 first_retained_sample_at/eligible_at 均为空。
14 日窗口尚无有效起点；不继承旧候选观察，也不从部署日期计算收口日。原始结果封存在上述检查点。

后续独立复核：检查点 sidecar、9 份嵌入原始工件 SHA、240 个来源文件 SHA 和三模块分子/分母
全部一致。计划索引工作流表中遗留的旧 TUI eligible 时间、SSH 超时及 AUD 旧候选 section 计数
已按 successor 的已知事实修正；未新采集生产状态，未据此晋级任何生产单元。
最终完整回归命令已固定三个单元测试目录、两组 Task Monitor 组件及七个跨模块文件；仍等待
Research 测试切片完成和审查，再从空 coverage 数据执行。

## 0. 2026-09-06：单一所有者内测冲刺提案

用户明确系统尚未正式对外，要求按单一所有者项目重新评估发布范围与门槛。本节登记执行提案，
不构成已经签署的风险接受、生产动作回执或 unit 完成证据。机器注册表仍是状态与依赖真源；
截至本次核对有 15 个未完成 unit，`DATA-12` 仍是 repository focus，等待完整同提交 Nightly
覆盖率证据。允许的 production/governance 工作可以继续准备，不据此跳过 repository 执行锁。

### 范围与门槛修订

- TUI：优先考虑延后 Classic 清理，把单一所有者内测验收与旧页面退役分开；保留现有
  `TUI-02` 观察及清理门，内测可用不得记作 `TUI-02=completed`。若所有者选择三天方案，须
  另行记录所替代的条款、适用候选与环境、真实起算样本、重置条件、风险接受和恢复原门的条件，
  同步 checker/config/registry/测试后才生效；不得仅把历史时间或状态改成通过。
- Terminal：全局并发 5 是待测上限，不是既定安全容量。先验证 1，再验证至多 5 的受限内测
  envelope；通过 Web SLO、队列背压、去重、Worker 存活、资源与恢复/回滚检查后，才能按实测
  接受的上限启用。现有 TAR-06 runner 只接受 staging，不能把 VPS production 目标伪装为 staging。
  内测 canary、完整 TAR-05 验收和 inline 退役须分别记录；若要调整 1/5/10/20 或观察门，先正式
  修订对应合同，不能以低并发测试代替当前完整退出门。
- 策略：首批限定为实际数据和 owner 输入齐备的 1–2 个 capability，其余逐项记录为本轮范围外，
  保持不可 Promotion。具体 capability 待真实数据盘点确定；被选中的项目仍必须完整通过
  `STRAT-01 -> STRAT-02 -> STRAT-03` 及 `EVID-01/02 -> EVID-03`，不豁免 PIT/OOS、证伪阈值、
  权限、回执和回滚。范围缩减不自动关闭原来覆盖更广的 unit。
- QMT：保留外部阻塞及实盘禁用，不作为研究展示或非交易内测的前置。

### 一周执行顺序与可验证交付

以下 D1 从候选绑定及必要前置完成后起算，是计划预算，不是已发生的观察天数。

| 时段 | 单元 | 本阶段交付 | 不满足时的处理 |
|---|---|---|---|
| D1–D2 | DATA-02 | 核对真实缺口与恢复点；有界回填、逐批 checkpoint、来源时间和写后对账 | partial、stale、容差或资源超限即停在 checkpoint；DATA-03 不放行 |
| D1–D2 | STRAT-01 准备 | 选定 1–2 个 capability，列出真实 owner、定义、policy、calendar、scope、样本及证伪输入 | 缺输入保持未登记，不用默认值替代 |
| D2–D3 | EVID-01/02 | 真实 owner receipt 对应的 canonical authority/approval 写入与 PostgreSQL first-winner、撤销、current-head、rollback 证据 | 缺真实授权或并发证据不关闭；EVID-03 仍等待 |
| D3–D4 | AUD-03 | candidate-bound 告警/恢复、archive/restore、管理员 TUI 与可恢复性演练证据 | unavailable 明示，不能作零值通过 |
| D4–D5 | TAR-05 内测准备 | 精确目标、负载与资源预算、受限阶梯结果、终止条件及回滚点；据实决定是否启用受限 canary | 容量未验证不启用；不能据此宣称完整 TAR-05 或 AI-01 验收 |
| D5–D7 | DATA-03、STRAT-02、EVID-03 | 按已满足的依赖启动真实观察、样本积累或 adapter 实现；仓库工作遵守唯一 focus | 时间不足继续积累，不补写历史；DATA-12 未退出前不抢占实现焦点 |

周末分别报告已通过退出门的 unit、获得阶段证据的 unit、等待真实时间/owner 输入/外部环境的
unit，不以“约关闭 10 个”作为验收指标。DATA-03 的行情交易日与宏观调度周期、TAR-05 的观察、
策略样本窗口都须单独核算。单一所有者可作真实角色决定，代理负责准备、执行和取证，不代造决定。

### Goal 启动记录（2026-09-06）

用户随后明确要求“设置一个goal 然后指挥luna max完成”。当前任务已创建持续 Goal，由主代理负责
派工、审查、生产动作协调和状态晋级；worker 使用 `gpt-5.6-luna`、`max`，覆盖自主调度合同中
worker `medium` 的默认值。先分别核验 DATA-12 的 exact-commit Nightly/coverage 证据与 DATA-02
只读 preflight/动作包，最多两个 worker，均不得提交、推送或执行生产写入。初始工作树的本节提案
保留，技术门槛和 unit 状态尚未修改。TUI 在明确选择三天修订之前按延后 Classic 清理处理；
启动 Goal 本身不构成风险接受签字或任何验收通过。

### Goal 检查点：DATA-12 验核与前置接线（2026-09-06）

- DATA-12 的 Nightly `34025990248` 与 artifact `9988878086` 已由 Luna 复核；主代理重新计算
  manifest 及其 7 份报告哈希均匹配。Research/Signal line 为 `90.02%/94.71%`，九项 branch
  目标全部满足。已有提交 `1e02caf5d` 的 completed 状态成立，不重复收尾。
- 14:56–14:57 UTC 的[生产域名探针](../deployment/prelaunch-public-readiness-observation-2026-09-06.json)
  确认 health/ready=200、decision-ready=503；5,533 资产的 price published coverage=0、financial=1，
  valuation publication 缺失，provider capability 仍 stale。它是当前公开接口的实际返回，不能与
  旧 DATA-02 dry-run 的候选重建结果混为已发布事实。工件仅保存解析后的 JSON 和原响应 hash，
  未保留原始响应字节；不作为 canonical reconciliation 或候选验收。
- 环境中的 SSH 目标两次在协议握手前失败，未认证、未执行远端命令；候选 commit/OCI 和数据库
  仍未重验。本地 SDK 地址实际为 loopback，已排除，不能据其连接失败声称生产宕机。
- 仓库调用链确认 canonical actor capture 缺 composition、请求 exact-current reader 缺实现；
  已登记 `EVID-05` 为唯一 repository focus，并作为 EVID-01 前置。Luna 执行有界接线与测试，
  主代理审查。生产 seeding、审批规则修订、DATA-02 execute、TAR capacity 和 runtime 均未放行。

### Goal repository 收口记录（2026-09-07）

`EVID-05` 已按机器注册表完成并释放 repository focus：95 项扩大回归、12 项隔离 PostgreSQL 回归、
capture 后撤销的独立复验及类型/架构/格式/治理门禁通过。正式
[closure evidence](../testing/evid05-account-actor-capture-repository-closure-evidence-2026-09-07.json)
绑定 17 个源码/测试文件；其 scope 只证明仓库接线和本地数据库行为，不能替代 EVID-01/02 生产验收。
SSH banner 重试仍超时，未部署补丁，DATA-02、authority/approval、TAR runtime 与 TUI 窗口均未变更。
当前无依赖已满足的 repository unit；生产和外部通道仍按 registry 的 auto_collect/真实前置继续判断。

## 1. 目标与完成口径

本方案把当前“可用但降级”和“部署后仍硬阻断”拆成七条可独立验收的执行轨。整体完成必须同时满足：

1. 最终不可变候选完成 TUI 三角色生产 UAT、108/108 route-page、同 run 写回执、readback 与精确零残留 cleanup；`TUI-01` 关闭，`TUI-02` 的 14 日窗口随后按真实时间完成。
2. 活跃 A 股 canonical quote、price、valuation、financial Publication 覆盖和历史深度达到治理合同，provider freshness 与决策数据均明确为 `ok`；持久化决策门只在其他严格检查全绿后切到 `active`，`/api/decision-ready/` 返回 `200`。
3. 行情 stale 时模拟交易继续禁止发布可信估值；决策数据恢复后重新估值并保留 source observation time。
4. 13 张 authority/evidence 表不再 zero-seed，真实 owner/root/reviewer、append-only approval/current-head、撤销和 rollback 均有 PostgreSQL 证据；随后才启动 `EVID-03`。
5. R1–R8 的 owner definition、policy、calendar、scope、qualification 与样本窗口来自命名业务 owner；真实 PIT/OOS receipts 完成后才 Promotion 和 consumer UAT。
6. AUD-03 完成 migration/rollback、告警、恢复、管理员 TUI、archive/restore 和双签，不再把 unavailable 字段当作零。
7. queued Terminal Runtime 完成 provider、1/5/10/20 容量、chaos、恢复、rollback、观察和双签；legacy inline 仍保持并发 1，只有已验收的 queued worker 扩容。

`strategy.execution_preview` 的 `can_execute=False`、`research_only=true` 是展示契约，不作为待翻转开关。策略执行必须走 Evidence、Promotion、风控、审批和 broker execution 的正式链；QMT 实盘另受 `QMT-01/02` 外部门禁。

## 2. 当前事实与先行纠偏

- `core/middleware/decision_gate.py` 覆盖 11 类决策路径；`core/health_checks.py` 要求 runtime state、核心覆盖、provider capability 与 decision data 四项同时通过。
- 当前候选 `aa7127ff4d9f71555b0d0486314da5518bd2ac20` / release `20260901232812` 的只读 dry-run 显示 completed-session price 合格覆盖为 `0/5,533`，quote/price/valuation Publication 覆盖为 `5,533/5,533` 但全部 stale，financial fact 覆盖为 `1,923/5,533`；因此 `DATA-02` 仍为 `DENY`，没有执行回填或 Publication 切换。第一动作仍须区分“事实缺失”“发布成员缺失”和“新鲜度失败”，不能无差别重抓全市场。
- 当前生产候选已由只读 deployment/preflight 工件绑定到 `aa7127ff4d9f71555b0d0486314da5518bd2ac20` / `20260901232812`；执行时仍先对账实际 commit/release/OCI/matrix/graph/runtime identity。候选身份不符才允许另行申请部署，身份一致时只补 canonical evidence 与 UAT。
- `TUI-01` 的 candidate-bound production-safe UAT、cleanup 与 isolated rollback 已完成；`TUI-02` 仍为 `5/10 DENY`，等待重启后真实 retained sample、精确 14 日窗口与结构化 telemetry/attestation。
- authority/evidence 与 R1–R8 owner-ledger 的零行是缺少真实业务/审批输入，不是 migration 或 fixture 问题。

## 3. 总体执行顺序

| 阶段 | 主要 unit | 动作 | 退出门 | 可并行项 |
|---|---|---|---|---|
| P0 候选对账 | TUI-01 | 只读核对 Git/OCI/manifest/production identity；条件式部署 | 唯一候选身份无漂移 | 准备审批包、owner 输入模板 |
| P1 TUI 快速闭环 | TUI-01 | production-safe recorder、三角色、写回执、readback、exact cleanup | recorder 全绿且真实 role owner 确认 | DATA/AUD preflight |
| P2 恢复与审计窗口 | DATA-01、AUD-03 | 备份、维护、shadow restore/switch-back、故障恢复、alert、archive/restore | RTO/RPO、零丢失/重复、回滚和双签 | STRAT/EVID dry-run |
| P3 数据快修与深回填 | DATA-02 | Publication 重建优先；仅补真实 fact/history 缺口；逐数据集对账 | coverage/freshness/reconciliation 全绿 | owner/root 审批采集 |
| P4 决策恢复 | DATA-03 | 严格预检、受控激活、失败自动 re-block、双 readiness 与观察 | decision-ready=200 且无 must-not-use | STRAT-02 receipts 开始积累 |
| P5 Evidence/策略 | EVID-01/02/03、STRAT-01/02/03 | 真实 authority、审批、定义、PIT/OOS、Promotion、consumer UAT | exact-current 与执行前重验通过 | AUD/TUI 观察 |
| P6 Terminal/AI | TAR-05、AI-01 | queued canary、容量、chaos、14 日 telemetry、AI staging/prod UAT | hard SLO 与双签全部通过 | QMT Phase 0（获权后） |
| P7 实盘桥 | QMT-01/02 | XtQuant 探针、5 日仿真、3 日小额实盘 | 券商与业务 owner 验收 | 不阻塞模拟盘或研究展示 |

依赖未满足时阶段顺延。真实观察窗口、PIT/OOS 样本期、券商开权和人工审批不可通过补写时间戳压缩。

## 4. P0/P1：候选与 TUI-01

### 4.1 候选只读对账

1. 对账 `origin/main`、部署 commit、release、OCI revision、matrix SHA、operation graph SHA、runtime manifest SHA。
2. 读取生产 health、ready、decision-ready、migration、TUI registry 和容器 revision；生成 candidate-bound preflight。
3. 若生产 identity 已包含 `003cb58c…` 的 TUI 修复且所有摘要一致，禁止重复部署；把已有 attestation 纳入 canonical 分支即可。
4. 若不一致，先创建并校验 PostgreSQL custom-format backup，再从独立 clean worktree 做 code-only deployment；保留 PostgreSQL/Redis volume，自动失败回滚必须 armed。

### 4.2 生产 UAT

使用固定 profile，不混入外部 AI、queued runtime、authority seed、active RSS、shared quota、load、fault 或 live rollback：

```bash
python scripts/record_web_to_tui_candidate_evidence.py uat \
  --uat-profile production-safe \
  --base-url <production-base-url> \
  --skip-server
python scripts/check_web_to_tui_cutover_readiness.py --json
```

验收必须同时包含：

- regular/operator/admin 三角色边界；
- 108/108 route-page 与 9/9 参数化读取；
- 账户 create/cancel、strategy 与 inactive personal provider 的同 run receipt；
- confirmed mutation 后在 60 秒 settlement SLO 内进入明确完成态；
- 按 run/name/owner/primary key 精确 cleanup，剩余为 0；
- role owner 对业务结果作真实确认。

`TUI-01` 关闭后才启动 `TUI-02` 第 0 天。候选、matrix、graph 或 runtime identity 漂移，或者出现 P0/P1 缺陷，14 日窗口重置。

## 5. P2：一次受控维护窗口关闭 DATA-01 与 AUD-03 的高风险子项

### 5.1 窗口前置

- 生产 owner 指定窗口、操作人、reviewer、RTO/RPO 目标和终止条件。
- 新建 backup（不 prune），下载后核对远端/本地 SHA-256，执行 `pg_restore --list`。
- 记录 writer、Celery、beat、queue、连接数、磁盘/WAL 与当前 release 基线。
- 把 decision runtime 切到 `maintenance` 或 `validating`；这不是解除总闸。

### 5.2 DATA-01 演练

1. 将最新 dump 恢复到隔离 sibling PostgreSQL 数据库，核对表、migration、sequence、逐表摘要。
2. 对隔离数据库执行候选 migration forward/backward；验证 rollback 后 schema/data hash 回到基线。
3. 做受控 connection switch smoke 后切回原生产库，或者按批准的 `vps-restore` 路径完成等价 live rehearsal。
4. 记录实际 restore、verify、switch-back 时间；失败立即保持 maintenance 并回到原 release/DB，不删除恢复点。

### 5.3 AUD-03 演练

在同一窗口但使用独立证据包：

- 注入一条有界 audit/outbox canary fault，验证 metric → alert → acknowledge → recovery；
- 验证 backlog age、duplicate、loss、recovery duration 均来自原始 timeline；
- 管理员 TUI 能定位 P0 事件链且不暴露秘密/任意 JSON；
- 对 canary 时间窗执行 archive，校验 manifest/content/predecessor hash，再恢复到隔离 namespace 并重放查询；
- owner 与独立 reviewer 分别签署 DATA-01、AUD-03，不共用一个“总体通过”占位。

退出门：原生产数据不丢失、恢复点可用、rollback 可重复、audit duplicate/loss 为 0、alerts/TUI/recovery/archive 不再 `unavailable`。任何一项失败时 `DATA-02` 不启动。

## 6. P3/P4：DATA-02/03 与决策 API 恢复

### 6.1 先修 Publication，再补事实

按 `active_a_share` 冻结当次 universe 与 as-of：

1. 只读导出 quote/price/valuation/financial 的 fact count、每标的最早/最晚 observation、历史深度、Publication/member/coverage。
2. 若 facts 已存在且 observation time、natural key、source、unit、quality 均有效，重建 immutable Publication/member/coverage；禁止为了填 member 再抓一遍同样事实。
3. 只有真实缺口才运行受控回填。默认从小批开始：

```bash
python manage.py backfill_active_a_share_core_data \
  --resume-offset <verified-offset> \
  --batch-size 50 \
  --source <approved-provider> \
  --history-days 756 \
  --financial-periods 8 \
  --max-batches <approved-batch-limit>
```

4. 任一 batch 为 `partial/blocked/failed`、零写入伪成功、WAL/磁盘越界、锁预算超限或 provider 跨源差异超过治理容差时立即停在 checkpoint；不得跳过失败标的推进 offset。
5. 每个 dataset 单独生成 legacy/canonical snapshot 与 reconciliation evidence；差异分类必须是 same、source-only、target-only、value mismatch、timestamp mismatch 或 quality mismatch，不能只比总行数。
6. 回填完成后运行 decision reliability repair，刷新宏观、quote、Pulse 与 Alpha；使用 `--strict` 保持失败关闭。

### 6.2 两阶段激活决策门

不允许先执行裸 `set_decision_runtime_state active` 再观察：

1. 在 runtime 仍 blocked/validating 时，对 `core_coverage`、`provider_capabilities`、`decision_data` 做不含 runtime-state 的严格 preflight；三项必须 `status=ok` 且 `must_not_use_for_decision=false`。
2. 通过受审计的 compare-and-set 操作把 runtime state 绑定到精确 release ref 并切为 `active`。
3. 立即请求 `/api/decision-ready/`；必须为 `200`，四项检查完整且全部 `ok`。
4. 若最终探针失败或 candidate 漂移，自动写回 `blocked`，保留原 reason、release ref 和恢复证据。

若仓库当前只有无预检的通用 state command，应先在 `DATA-03` 范围补一个 fail-closed activation wrapper 与契约测试；不能把操作纪律当原子保证。

决策 API 恢复不等于 DATA-03 最终关闭。仍须保留至少行情 3 个交易日加周末、宏观 2 个调度周期的 candidate-bound observation；期间 stale/failover/conflict 必须重新阻断。

## 7. P5：Evidence、R1–R8 与策略执行

### 7.1 首批真实输入包

业务 owner 为每个 R1–R8 capability 提交：owner/tenant identity、definition version/hash、policy、calendar、scope/universe、sample window、qualification、benchmark/cost/liquidity/label 语义、失效条件、回滚条件。系统只做 schema/hash/dry-run 验证，不代填业务值。

独立 root/reviewer 随后完成：

1. 创建真实 owner/tenant authority root；
2. append-only approval first-winner、successor、revocation/current-head 与 rollback；
3. same-alias Evidence composition 和端到端 receipt；
4. 对 13 张表及 EVID-02 head 再做 candidate-bound inventory。

禁止 raw SQL、fixture、User/Profile/session 推断 owner 或自动生成审批。

### 7.2 依赖顺序

- `EVID-01 + EVID-02 → EVID-03`：只有两项真实生产门关闭后，才把 priority Research/Portfolio/Broker consumer 接到 exact-current revalidation。
- `STRAT-01 + DATA-02 → STRAT-02`：历史数据必须保留 source observation time、lineage、receipt 与 PIT/OOS 边界；可回填事实，不能伪造当时可见性。
- `STRAT-02 + EVID-03 → STRAT-03`：Promotion、权限、consumer UAT 与 rollback 使用同一 receipts/evidence hash。

`strategy.execution_preview` 继续 display-only。模拟盘可在决策数据恢复后重新估值；实盘订单只能由已 Promotion 的策略、正式 execution proposal、风控、人工确认和 broker execution 生成。

## 8. P6：TAR-05 与 AI-01

### 8.1 queued runtime 验收

先在同一候选的批准 staging 环境启用 `TERMINAL_RUNTIME_AUTHORIZED`、queued intake 与专用 `terminal_agent_worker`。legacy inline 的 `TERMINAL_AGENT_MAX_CONCURRENCY` clamp 继续为 1；容量扩展只发生在隔离 worker。

顺序执行：

1. 单用户 provider/MCP 成功、审批暂停/恢复、SSE 重连、cancel、idempotency 和费用审计。
2. 1/5/10/20 用户阶梯、15 分钟容量测试与 soak；四档必须绑定同一 commit/release/OCI/runtime/test-matrix。
3. Worker SIGTERM/SIGKILL、Redis down/restart、broker 丢消息、model timeout、Web restart、deploy drain。
4. 队列 drain 到 0，永久 running=0，重复非幂等副作用=0，跨用户泄漏/秘密泄漏=0。
5. staff canary → 小比例普通用户 → 全量 queued；每级单独批准，任一硬门失败即停新接单并回滚 feature flag。

硬 SLO 至少包括 run API p95 ≤ 500 ms；20 用户时普通 Web 5xx=0、p95 劣化 ≤10%；Daphne 因聊天负载重启=0；同幂等键 20 次并发只产生 1 个 run 和 1 次模型调用。

TAR-05 关闭前不退休 inline、不放大全局容量。完成 14 日 telemetry、restore/rollback 与 Operations/Product 双签后，`AI-01` 才运行同候选 staging/production browser UAT、外部模型链路和独立 owner/reviewer sign-off。

## 9. P7：QMT 外部链

`QMT-01/02` 不与“系统决策 API 恢复”绑成一个开关。内部可完成安装包、read-only probe 和证据模板，但以下必须由外部环境提供：

1. 券商允许启动 XtQuantServer，并开通查询、委托和撤单权限；
2. 目标 Windows 主机完成 Phase 0 资金/持仓/委托/成交只读探针；
3. 仿真环境连续 5 个交易日无重复单和未处置差异；
4. 单笔、单日、总资金上限经批准后，连续 3 个交易日小额实盘逐单确认；
5. 四维对账、STOP、重连、撤单、回滚与券商/业务 owner 双签。

在此之前 `blocked_external` 保持正确；模拟盘、研究展示和非实盘功能不应被 QMT 门禁连带关闭。

## 10. 集中授权包

| 授权包 | 精确动作 | 默认回滚 | 人工/外部责任人 |
|---|---|---|---|
| A1 | TUI production-safe UAT 的限定写入与 exact cleanup；条件式候选部署 | 自动回旧 release；删除本 run 测试记录 | Release owner、role owner |
| A2 | 新备份、maintenance、shadow restore/switch-back | 原 DB/release 不动或立即切回 | Production owner、reviewer |
| A3 | DATA-02 分批回填、Publication 重建、reconciliation 写证 | checkpoint 停止；不删旧事实 | Data owner |
| A4 | AUD-03 canary fault、alert/recovery、archive/restore | 停注入、恢复配置、保留 ledger | Audit/Ops owner |
| A5 | owner/root/approval/definition/policy 的真实生产写入 | append-only revoke/successor | Business owner、独立 root/reviewer |
| A6 | queued canary、staging/生产 load/chaos、feature flag | 停接单、drain、flag 回关闭 | Operations、Product |
| A7 | 付费外部模型 UAT及费用上限 | 关闭 provider/canary | AI owner、reviewer |
| A8 | QMT 仿真或真实报撤单 | STOP、撤未成交、关实盘开关 | Broker、business owner |

A1–A8 不互相蕴含。特别是 A1/A3/A6 不能推导 A8 实盘授权。

## 11. 时间与交付节奏

| 工作 | 工程时间目标 | 不可压缩时间 |
|---|---:|---:|
| 候选对账 + TUI-01 recorder | 0.5–1 天 | role owner 确认 |
| DATA-01 + AUD-03 受控窗口 | 1 个准备日 + 1 个窗口 | owner/reviewer 安排 |
| Publication 快修 | 1–3 天 | provider/数据质量异常会顺延 |
| 全市场历史回填与 reconciliation | 3–10 天起 | 配额、WAL、失败标的、真实历史深度 |
| EVID-01/02 + STRAT-01 | 1–3 天工程执行 | 真实业务输入与审批 |
| TAR-05 容量/chaos | 3–4 工程日 | 14 日 telemetry |
| TUI-02 | 证据自动采集 | 14 日无阻断观察 |
| QMT | 少量工程支持 | 最少 5+3 个交易日且先获券商权限 |

每个 material checkpoint 必须同步：规范化 evidence artifact、对应 primary plan 实施记录、`governance/active_plan_registry.json`、`docs/plans/README.md` 和必要的 `docs/INDEX.md`。状态只能在唯一 exit gate 真正满足后晋级。

## 12. 停止线

- 不降低 freshness、coverage、SLO、跨源 1% 默认容差或观察天数来换通过。
- 不清除持久化决策门后再补数据；激活失败自动 re-block。
- 不把 stale price 用于模拟盘可信估值，不用计算时间伪装 observation time。
- 不把 local/SQLite/fixture evidence 写成生产证据。
- 不代替 owner/root/reviewer、券商或真实用户作决定。
- 不通过把 `can_execute` 改为 true 绕过 Evidence/Promotion/QMT。
- 任一写入超出授权包、候选身份漂移、数据/审计 hash 不一致、无法回滚或出现秘密泄漏时立即停止并保留 fail-closed。

## 13. 执行检查点（从 2026-08-30 起的时间序列）

> 本节按时间追加检查点；候选与状态以各小节日期为准，较早小节不代表当前生产状态。当前投影以本计划顶部、`governance/active_plan_registry.json` 和最新检查点为准。

### 13.1 DATA-01 已关闭

在生产候选 `c826f741edc0f12f5e29fa5b0441b34a89f6dac5` 上完成了新建并保留的 PostgreSQL custom-format 备份、下载与 SHA-256 对账、sibling database 恢复、`data_center.0072 → 0071 → 0072` 迁移往返、真实 Web 连接切换和切回。恢复库包含 `542` 张 public 表、`72` 项 Data Center migration 和 `463` 个 sequence，schema SHA-256 为 `d9f761e83e45cf5111af7b76ef546f99d52d3e7198489a03a458ba9e519ca447`。迁移往返后业务表、schema 和 migration 名称集合一致；唯一变化是 `django_migrations` 的正常 ledger id 及 sequence 从 `496` 增至 `497`。

真实切换演练中，恢复库启动 `63s`、原库切回启动 `42s`、外部累计不可用 `217s`；切换前后核心计数保持 `2,784,337 / 167,724 / 441,944 / 2,197 / 171,503 / 173`，WAL 均为 `3/EF274DF0`。切回后 Web health=`200`、Celery 节点=`1`、决策门恢复为原先的 `blocked`，临时恢复库与临时秘密文件均已删除，远端恢复点继续保留。

证据文件及 SHA-256：

- [`data01-live-rehearsal-c826f741-baseline.json`](../deployment/data01-live-rehearsal-c826f741-baseline.json)：`7271832f3f19b8463126a0c54068dcc6007b80978c04080b4071fdc6fad8f6ea`
- [`data01-live-rehearsal-c826f741-migration-roundtrip.json`](../deployment/data01-live-rehearsal-c826f741-migration-roundtrip.json)：`a404d575d6e5252529779b6675d798374a4e009a98c3282d3116564d8fa4afa4`
- [`data01-live-rehearsal-c826f741-migration-classification.json`](../deployment/data01-live-rehearsal-c826f741-migration-classification.json)：`cb51a8f9e87b4bfe4bcdb795b620a5de76599480fa615712b8c7c4cf7d1f79ec`
- [`data01-live-rehearsal-c826f741-connection-switch.json`](../deployment/data01-live-rehearsal-c826f741-connection-switch.json)：`d7e73b6f24ad6ee6660ec24abe5f31ab2cc07f6b3e7f5b12577a95fd663cb526`

### 13.2 DATA-02 候选已部署并完成 dry-run，尚未宣称生产通过

新增 active-A-share quote/price/valuation/financial Publication 的全量原子重建用例和 dry-run-first 管理命令。候选选择以每个资产的确定性最新真实 fact 为来源，执行前验证 universe 精确一致、时间戳 aware 且不在未来、dataset/table 绑定正确；四类 Publication 在同一外层事务中发布，任一失败整体回滚。标准单标的同步和 backfill 中间批次改为 fact-only，避免局部任务把全市场 current Publication 缩成单标的；只有完整 backfill 成功后才触发全 universe 原子发布，失败返回 `blocked` 并保留 checkpoint。

DATA-02 增加 `repair_active_a_share_current_facts`：默认 dry-run；显式执行时先做 historical-price 与 financial provider 探针，再分批抓取真实 quote/valuation，任何批次不是 frozen universe 精确覆盖即停止；仅将已有 `report_date` 的 null `available_at` 修复为源日期边界，并只从 15:00 后的最近已完成交易日真实 quote materialize 日线。周末/开盘前的日频 price/valuation 使用最近已收盘交易日语义，实时 quote 不继承该放宽。2026-08-30 生产只读 provider 预检得到 Tencent failover `5,533/5,533`、observation date 全部为 `2026-08-28`、OHLC 缺口 `0`；东方财富 batch endpoint 失败被显式记录，未静默改写 source。

DATA-03 同候选新增 `activate_decision_runtime_fail_closed`。通用 runtime update 和 `set_decision_runtime_state` 已禁止写 `active`；唯一激活入口先在 blocked/validating 状态运行 core coverage、provider capability、decision data 三检查，再锁行 compare-and-set 到精确 release ref，随后立即复验，任何失败自动写回 blocked。该实现就绪不等于 DATA-03 解锁；必须先完成 DATA-02 生产执行与 reconciliation。

部署前候选门禁已经统一复跑：DATA-02/03 与相关数据链回归包 `230 passed, 2 skipped`，四个强制高风险包（TUI、Terminal Agent、SDK、内部 SSL）`356 passed`，改写后的四类 latest-fact 选择器及 remediation 组件包 `43 passed`，最终 backfill checkpoint 回退用例包 `9 passed`。Black/isort/Ruff、Django system check、25 个生产 Python 文件增量 mypy、完整 mypy debt ceiling、architecture delta、91 项 Celery task contract、53 项 current-data contract 与 active-plan registry 均通过。最终批次若 Publication 重建失败，checkpoint 的 `next_offset` 会回退到该批次起点，避免后续空批次把未发布状态误报为完成。

该实现已随 commit `36b72d2fc01604afdb15d236a1e91d082fb62a5b` 部署为 release `20260830071422`。生产默认 dry-run 确认 universe=`5,533`：financial 可安全修复 `288,409` 行、覆盖 `3,750` 个资产，unresolved/future=`0/0`；但最近完成交易日 price 的合格资产为 `0`、旧事实 invalid/stale=`5,533`。现有 quote/price/valuation Publication 虽为 `5,533/5,533`，仍是 stale；financial 仅 `1,923/5,533`，缺 `3,610`。因此没有执行写回或 Publication replacement，更没有尝试 DATA-03 激活。结构化 checkpoint 见 [`data02-audit-runtime-checkpoint-2026-08-30.json`](../deployment/data02-audit-runtime-checkpoint-2026-08-30.json)。

### 13.3 仍保持阻断的边界

- `TUI-01` 最终 release 自动化已经 10/10、108/108、两条同 run 写回执、精确零残留；六类 cleanup/rollback scope 也为 108/108，隔离 rollback drill 已通过。真实 role-owner 业务确认仍缺，`TUI-02` 的 14 日窗口到 `2026-09-12` 才能自然结束。
- `EVID-01/02` 已在最终 release 的同一只读事务中重绑：Account 0050–0055 应用，但 13 张 authority/evidence 表及 operator/approval/activation 三表仍为零，approval/activation head 为空；真实 root/reviewer/业务 owner 输入仍缺，不能用 fixture 或代理签名补齐。
- `STRAT-01` 已在最终 release 重绑四个固定 selector：65/7/16/35 张目标表全部 zero-seed；真实 owner/definition/policy/calendar/scope/qualification 仍缺，不能把 Data Center facts 或空表推导成业务批准。
- `AUD-03` 的三项 runtime definition 已幂等登记，但 production profile 缺少三项真实值，七张 authority root/ledger 表均为零；alert、fault recovery、archive/restore 和双签仍需单独生产证据。
- `TAR-05` 的 1/5/10/20、chaos、恢复和观察未完成；inline concurrency clamp 继续为 1。
- `QMT-01/02` 仍缺获批 XtQuant 目标环境；A8 授权不能替代券商环境、回执和交易日观察。

### 13.4 最终 TUI 候选与 M5 机器门禁

最终候选 `36b72d2fc01604afdb15d236a1e91d082fb62a5b` 已部署为 release `20260830071422`、image `sha256:09f6491440a4bc16934ac5544c793a0b5b9d22c8ec6f8ab35d61693b0121c94b`，OCI revision 与 source commit 精确一致；health/ready=`200/200`，decision-ready 按设计继续 `503 blocked`。canonical production-safe run `tui01-36b72d2f-20260830-01` 通过 `10/10` tests、`108/108` routes、regular/operator/admin 三角色、strategy/provider 两条 create-update-readback receipt 与 exact cleanup residual=`0`。

随后 cleanup recorder 对 `empty_state/error_state/legacy_url/permission/primary_task/rollback` 六类 scope 全部得到 `108/108`，候选绑定的本地隔离 rollback drill 通过。当前 readiness 为 `5/10` gate 通过：`source_consistency`、`execution_dependency`、`route_task_uat`、`route_cleanup_readiness`、`rollback_drill` 为 PASS；`stable_version_window`、`blocking_defects`、`production_telemetry`、正式 `production_registry_backup` attestation、`cutover_approvals` 为 FAIL，整体保持 DENY。

生产 registry generation `30` 已备份到 Git 工作树外，bundle SHA-256=`1fe6b01fd36cf855a9af395c5b570029442cb5593834d2a15c24fa8601dfb882`，sidecar 校验和 restore dry-run 均通过，active graph hash 与 backup 一致。它只关闭“没有可恢复原始 bundle”的缺口；正式 payload-free attestation 必须在 `2026-09-12` 后由真实独立 reviewer 生成，当前不得把 raw backup 投影成 gate PASS。证据见 [`tui-registry-backup-checkpoint-2026-08-30.json`](../deployment/tui-registry-backup-checkpoint-2026-08-30.json)。

### 13.5 Audit 配置阻塞与唯一可继续顺序

在新建且校验通过的 PostgreSQL 恢复点 `postgres-20260829T220625Z.dump`（SHA-256=`434903ac03c4fd6e4623682c65628f6b3f7be533a279b53fa063d692470e3d95`）之后，生产只执行了幂等 `initialize_runtime_definitions`。现在三项定义均存在，但 active production profile v2 仍缺 `audit.system_event.mode`、`audit.system_event.outbox_enabled`、`audit.system_event.authority_selector` 三项值；七张 Account authority root/ledger 表计数均为零。没有创建 profile successor、selector、root、owner 或 reviewer，也没有绕过 writer fail-closed。

因此下一顺序固定为：命名 production owner 与独立 root/reviewer 提供并批准真实 authority/profile 值 → 验证 typed audit writer 可加载 → 执行 DATA-02 A3 写回与四 Publication reconciliation → 只有三项 readiness 全绿才调用 DATA-03 fail-closed activation wrapper。Goal 可以继续自动采集 TUI 缺陷/遥测、观察日与已有外部状态，但不能靠重复探针、代签或虚构业务输入推进上述人工门。

### 13.6 最终 Evidence 候选重绑定

在同一 release `20260830071422` 上完成 EVID-01/02 的 `REPEATABLE READ READ ONLY` 快照：
Account 0050–0055 均已应用，13 张 authority/evidence 表与 EVID-02 operator/approval/activation
三表全部为零。原始 bundle SHA-256=`f7a26a5eb5db3fd31fb5d601e146120346f8681aaa7c2f8ca55308e982b3a0cd`；
EVID-01 content-addressed report SHA-256=`63c08dcb2d984da92f4b2dddd8e039fe3dafc79688c629e9e2f42d73adbf4d85`，
outcome=`blocked_zero_seed_authority`；EVID-02 report SHA-256=
`c2fec726ef6903c8c941703f6afd9036190cb9c8be7a43ebe630667065ca6275`，approval/activation head 均为
`empty`，人工批准保持 `not_collected`。这关闭了“Evidence 证据仍绑定旧候选”的缺口，不关闭
EVID-01/02 exit gate；未创建 authority/approval、未执行生产并发/rollback、未解除全局 deny。

### 13.7 最终 Strategy owner-ledger 重绑定

STRAT-01 在同一最终 release 上完成候选绑定的 PostgreSQL `REPEATABLE READ READ ONLY`
inventory：Research R1–R8、Portfolio R4/R5/R8、Account authority/assignment、
owner/policy/operator/assignment 四个 selector 分别命中 `65/7/16/35` 张表，全部总行数与非零
表数为 0。strict snapshot SHA-256=`6f8dac572a2c72c410975413833d9c4852462fff9b5a31779499d69536035814`，
canonical report SHA-256=`71bd1af35985eea8795f797095de07522b5ad7ece3a4562f70ca44c64f9299d4`，
outcome=`zero_seed`。这只关闭“STRAT-01 证据仍绑定旧候选”的缺口；真实业务 owner 输入、
PIT/OOS、receipts、Promotion、consumer UAT 与双签仍缺，`STRAT-01/02/03` 状态不晋级。

### 13.8 最终 AUD-03 只读运行观察重绑定

最终 release `20260830071422` 在 `2026-08-30T02:59:24.576960Z` 的单个 PostgreSQL
`REPEATABLE READ READ ONLY` 事务中确认 `496` 项 migration 全部 applied、pending/failed=`0/0`，
最新为 `audit.0013`；候选自 `09269c14…` 起没有 migration 文件变化，leaf plan 仍为空，graph SHA
保持 `02406e0a395d09e89785ba969202a8fdb060bcb7814283f9cee9e4212ada0496`。operation logs/failures=
`563/0`、failure rate=`0.0`，outbox 六类 backlog 均为 `0`；随后公网 Audit health 复核为 `200/OK`。

原始 envelope SHA-256=`6d16a9ff57fd9391927714d66ed3d61b74aaf3dfe81c7f338f6fda2a266b864a`，
canonical artifact SHA-256=`963e4efd8527916d4bbbe5a5b0923868f3be043a1d63834014b9e0fa97a86950`。
alerts/admin TUI/recovery/archive 仍明确 unavailable；本次未做迁移、写入、fault、recovery、
archive/restore 或代签，`AUD-03` 不晋级。在候选、ledger 或授权范围变化前不重复探针，下一步只接受
真实 owner/root/reviewer 输入及逐项可回滚的运营验收。

### 13.9 AUD-03/DATA-02 逐项授权包

下一次生产写入的 no-fake-values preflight 已固化为
[`aud03-data02-production-authorization-preflight-2026-08-30-36b72d2f.json`](../deployment/aud03-data02-production-authorization-preflight-2026-08-30-36b72d2f.json)，
SHA-256=`25dc78fd5dfc627460761f7c7aa28c5fef08da8f3cd7ec8b62b81ac3665096d1`。只读复核确认 active profile
v2 与 snapshot 的 identity/hash 内部一致，但按当前 catalog 仍缺三项 critical Audit value，loader
第一原因是 `mode_invalid`；exact actor 与 owner/tenant authority reader 的三张表也均为零。

现在不再缺“怎么做”的操作定义，缺的是不得由自动化生成的真实输入：production owner、独立 root
approver/reviewer 及三份 receipt hash，actor/scope 各三项 exact ledger head，`shadow|required` mode、
`outbox_enabled=true` 决策，profile activation actor/reason，以及 DATA-02 operator、source、`1..500`
batch-size 和恢复点接受决定。四阶段固定为 authority heads → 高版本 profile successor → 只读 writer/
authority preflight → `repair_active_a_share_current_facts --execute`，每阶段单独授权、单独验收。

DATA-02 的 provider facts 会先于最终四 Publication 事务写入，因此失败时只能对精确 partial facts 做另行
授权的 reconciliation/compensation；不能批量删除。四 Publication 的切换本身保持原子性。profile
回滚也必须创建携带完整值集的更高版本 successor，不能原地修改/删除。当前 artifact 明确
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`；没有执行任何
生产写入，AUD-03/DATA-02/DATA-03 状态均不晋级。

### 13.10 TUI M5 observation source preflight

候选绑定的只读检查已形成
[`tui-m5-observation-source-preflight-2026-08-30-36b72d2f.json`](../deployment/tui-m5-observation-source-preflight-2026-08-30-36b72d2f.json)，
SHA-256=`b8b22c64f260d5a2d43de78a2ee30d30637ea741203d3173b1b28fe6fc660bcf`。公网 exporter 可达并覆盖
catalog 的全部 `101` 个可比较 task key，但 `203` 条 series 全部来自 TUI surface；它只提供当前
进程 counters，不能执行六条固定的 14 日 PromQL。VPS 无 Prometheus-compatible 容器、9090 listener
或进程，部署 compose 也没有时序库；外部 query origin/retention 证明未提供。

扩展只读 discovery 对 web/host env key、Docker volume、systemd、常见 agent、Caddy route 和标准
Prometheus 路径也均未发现本地 source 线索；外部 SaaS 直接 scrape 仍只能由 operations 提供证明。

正式 telemetry/defect builder 均拒绝 `2026-09-12` 前的最终快照。若 operations 不能证明已有从
`2026-08-29` 连续留存的外部 source，则监控部署/配置必须另行授权，并从首个可证明 retained sample
重置 14 日窗口；不得在窗口结束时用瞬时 scrape、零值或 UAT counters 回填历史。`TUI-01` 仍缺真实
role-owner，`TUI-02` 仍等待依赖，readiness 保持 `5/10 DENY`。

聚焦回归同时修正一处仍期待历史空 UAT 的 checked-in readiness 测试，只让测试接受当前五项机器门
PASS、五项最终门 FAIL 的事实，没有改 gate 实现或阈值；telemetry/defect/readiness 合同最终
`48 passed`。

条件化监控整改授权包
[`tui-m5-monitoring-remediation-preflight-2026-08-30-36b72d2f.json`](../deployment/tui-m5-monitoring-remediation-preflight-2026-08-30-36b72d2f.json)
SHA-256=`c386ea4552df2af991c2ae824acbef79ccd7dc337bc139994145babdc89c1b76` 已准备完毕。若没有既有外部
retained source，现有 `localhost` targets 配置不能原样部署；必须先分配 bounded repository focus，
再逐项授权 pinned monitoring service、持久化 retention、受控 query access 与 candidate re-attestation。
只有 canonical observation starter 从新的 verification date 重置 14 日窗口后，才允许积累最终证据。

### 13.11 审核团队交接包

为避免“泛化审批”继续缺少可执行字段，已把 AUD-03/DATA-02 与 TUI M5 拆成两个独立审核 work order，
并形成可直接转发的
[closure-review-team-handoff-2026-08-30-36b72d2f.md](../deployment/closure-review-team-handoff-2026-08-30-36b72d2f.md)，
SHA-256=`4ba887ba3d7a81cf6c6e1349f08a082968626c9d647c55644b44852a4771dc36`。
交接包要求每个 phase 只能输出 `APPROVE/REJECT/DEFER`，真实身份、生产账号、职责分离、receipt、
小写 SHA-256、授权有效期和精确候选均为必填；未审核字段必须保持 `null`，禁止用 placeholder 冒充。

AUD-03/DATA-02 回传模板
[aud03-data02-production-review-return-template-2026-08-30-36b72d2f.json](../deployment/aud03-data02-production-review-return-template-2026-08-30-36b72d2f.json)
SHA-256=`bebe057503ef1d7196bd00f84ef3d71b3a2660dd0097283e68a40e71a490d6c7`，分别约束真实
authority heads、forward profile successor、只读 writer/authority preflight 与一次精确 DATA-02
execute。pre-execution 批准明确不宣称 DATA-02/AUD-03 exit gate；执行后的 5,533 coverage、四
Publication identities、Audit receipts 与 reconciliation 必须另行审核，不能预签。

TUI 回传模板
[tui-m5-operations-review-return-template-2026-08-30-36b72d2f.json](../deployment/tui-m5-operations-review-return-template-2026-08-30-36b72d2f.json)
SHA-256=`1cd479735fc9888e7e08d9f5badeb5d5c9ce216ededa4565bd31610666e93fd5`，要求 operations 在“提供
既有 retained source”与“授权 repository+production monitoring remediation”中二选一，并单独记录
role-owner 对既有 UAT 的业务确认。14 日 telemetry/defect、formal registry attestation 与 cutover
双签仍必须在有效窗口自然结束后形成。

三个文件均有独立 `.sha256` sidecar。模板本身保持 `template_only=true`，不构成审批；审核团队必须
复制为新的 final return、设为 `false` 并附最终 JSON sidecar 与外部 receipt hash。该治理 handoff
不改变 `execution_focus=null`，也不晋级 AUD-03、DATA-02、DATA-03、TUI-01 或 TUI-02。

### 13.12 Docs 审核入口与动态清单

面向审核团队的稳定入口已放入
[`docs/reviews/release-36b72d2f/README.md`](../reviews/release-36b72d2f/README.md)，动态审核状态投影为
[`review-checklist.json`](../reviews/release-36b72d2f/review-checklist.json)，初始 SHA-256=
`1ed28752073e9cb409fa4772d6e54c8626598e9ef11051b737713c31f1d3c417`。审核结果统一返回
[`docs/reviews/release-36b72d2f/reports/`](../reviews/release-36b72d2f/reports/README.md)，不覆盖 preflight、
template 或 checklist。加入 single-owner 授权和 TUI-03 repository evidence 后，可脱离仓库转发的 23 项输入包为
[`release-36b72d2f-review-input-package.zip`](../reviews/release-36b72d2f/release-36b72d2f-review-input-package.zip)，
SHA-256=`b587848dbc690f607acc21881c2b092f74f7513dfa938ae736f1f008af0ceb41`，并附独立 sidecar。

checklist 只由 repository governance 流程动态维护：收到 final report 后先验证 JSON/schema、
`template_only=false`、同名 sidecar、候选 commit/release/image、真实身份与 production account、职责分离、
receipt、有效期、分阶段必填字段及依赖；全部通过才写入对应 work order 的 decision/status/report hash，
重建 checklist sidecar，并同步本计划、`docs/plans/README.md` 与机器 registry。无效、过期、跨候选、缺
sidecar 或尚未发生的 execution/14-day final review 不改变授权。当前 checklist 为
`awaiting_review_reports`，`approved=0`、`completed=0`、`authorization_changed=false`，因此所有既有
fail-closed 状态保持不变。

### 13.13 EVID/STRAT 补充审核入口

主审核包未覆盖的 `EVID-01/02` 与 `STRAT-01` 已形成独立、不可与 AUD/DATA/TUI 决定互相替代的
补充审核入口：
[`docs/reviews/release-36b72d2f/evidence-strategy/README.md`](../reviews/release-36b72d2f/evidence-strategy/README.md)。
候选绑定 preflight SHA-256=`8518c165c21395716497a320f23e232d2744e29bea1cec8281f50fd7d19787ae`；
EVID 五阶段模板 SHA-256=`e7055af3c6dc94893a1c2900c2fbc6fd783125b96d432cddfa3f691df05269a2`；
STRAT R1–R8 模板 SHA-256=`c21b14ed8a60123f3412fde414a4c2aab6ccd695eb651e5daef7722973322c24`。

补充动态清单
[`review-checklist.json`](../reviews/release-36b72d2f/evidence-strategy/review-checklist.json) 将 10 个 work order
按真实依赖登记为 `2 awaiting_review_report / 6 waiting_dependency / 2 not_due`，当前
`approved=0`、`completed=0`、`authorization_changed=false`。final report 只接收于
[`reports/evidence-strategy/`](../reviews/release-36b72d2f/reports/evidence-strategy/README.md)。可脱离仓库转发的
加入 single-owner 授权后的 28 项输入包为
[`release-36b72d2f-evidence-strategy-review-input-package.zip`](../reviews/release-36b72d2f/evidence-strategy/release-36b72d2f-evidence-strategy-review-input-package.zip)，
SHA-256=`93c7540d88dc437c6c843e923a2385d03f7e2e60eeb4f318c38750ad11175fc6`，并附独立 sidecar。

EVID 生产 race/rollback 与 post-execution heads、STRAT append-only registration、PIT/OOS、Promotion 和
consumer UAT 都必须真实发生后再审核，不能在当前报告预签。此 handoff 没有生产写入、authority seed、
registration 或授权变更；`EVID-01/02`、`STRAT-01` 保持 `awaiting_production`，`EVID-03`、
`STRAT-02/03` 继续等待依赖，`execution_focus=null`。

### 13.14 TAR-05 Terminal Runtime 补充审核入口

TAR-05 已形成第三个独立补充入口：
[`docs/reviews/release-36b72d2f/terminal-runtime/README.md`](../reviews/release-36b72d2f/terminal-runtime/README.md)。
最终 release report 证明 commit/release/image 与基础 Web/Celery/PostgreSQL/Redis 健康，但未发现专用
Terminal Agent Worker，也没有在最终候选重新证明 runtime manifest digest、完整 flag snapshot、
批准 staging、真实 provider/MCP profile 或 retained metrics source。历史 `71e62773…` capacity
artifact 明确不可跨候选复用。

候选绑定 preflight SHA-256=`0e07657152230a52e431e76d899d1527588f7556a3146d8b247a78ac54ea9ed6`；
TAR-05 return template SHA-256=`06c71dc80c8196e0273a8eca77be5f91ba2fa3f024464376fb573dc5b5276b3f`；
动态清单
[`review-checklist.json`](../reviews/release-36b72d2f/terminal-runtime/review-checklist.json) 登记 7 个 work order：
`1 awaiting_review_report / 4 waiting_dependency / 2 not_due`，当前 `approved=0`、`completed=0`、
`authorization_changed=false`。final report 只接收于
[`reports/terminal-runtime/`](../reviews/release-36b72d2f/reports/terminal-runtime/README.md)。

审核顺序固定为 P1 environment/candidate → P2 staging capacity 与 P3 staging chaos → P4 real
provider/MCP/role UAT → P5 production staff canary（等待 `TUI-01`）→ P6 retained observation/cutover →
P7 general-user rollout/inline retirement。当前只允许审核 P1，且其批准也只允许只读 re-attestation；
load、fault、model、flag、canary、rollback、观察或退役都需后续独立决定。

加入 single-owner 授权后的 23 项输入包为
[`release-36b72d2f-terminal-runtime-review-input-package.zip`](../reviews/release-36b72d2f/terminal-runtime/release-36b72d2f-terminal-runtime-review-input-package.zip)，
SHA-256=`684bd75a6754c73b3dc64ad876418f87bc3ea103e9d6e8c3affee355d7bec196`，并附独立 sidecar。
本 checkpoint 未启动 Worker、生成负载、注入故障、调用外部模型、修改生产 flag、部署或 rollback；
`TAR-05` 保持 `awaiting_production`、`capacity_ready=false`，queued runtime 与并发大于 1 继续
fail-closed，`execution_focus=null`。

### 13.15 个人项目治理简化与首个技术整改

唯一真人项目所有者的交互式授权已固化为
[`personal-project-single-owner-authorization-2026-08-30-36b72d2f.json`](../deployment/personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)，
SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`。同一 owner 可承担
owner/root/reviewer/role-owner；五份回传均按真实技术内容处理：AUD/DATA、TUI source、EVID、STRAT、
TAR 为有效 DEFER，TUI role-owner 对已发生 UAT 的范围内决定为 APPROVE。只有 `TUI-01` 因机器证据
和 owner 业务确认同时满足而完成；零播种账本、业务定义、staging、runtime manifest、retention 与
负载/模型结果均未被签字替代。

随后登记并关闭 `TUI-03` repository unit，产出固定 digest 的 Prometheus、`21d/4GB` 双上限、持久卷、
真实 `web:8000/metrics/` target、M5 rules、健康检查、host-only credential 和 HTTPS read-query allowlist，
同步 VPS/local 打包。证据
[`tui03-retained-monitoring-repository-closure-evidence-2026-08-30.json`](../testing/tui03-retained-monitoring-repository-closure-evidence-2026-08-30.json)
SHA-256=`8fda79136ae1a3a70afd22ce4b1134f69f5d4af44bd484786ea4fd2f9c9891a7`。`TUI-03=completed`、
`execution_focus=null`、`TUI-02=awaiting_production`；尚未部署或生成观察样本。

### 13.16 single-owner successor production Day 0

后续用户授权已固化为
[`personal-project-single-owner-authorization-2026-08-30-80ea002b.json`](../deployment/personal-project-single-owner-authorization-2026-08-30-80ea002b.json)，
SHA-256=`f675c44647764c93292f223fc94a0f7ac3d5c89a1ad651d2d12a6ba1918300e1`，并取代旧候选授权。
个人项目不再要求 owner/root/reviewer 分属不同自然人；同一项目所有者可以在对应技术证据形成后承担
这些角色。零播种账本、业务定义、外部环境、观察历史与执行结果仍不得补造。

commit `80ea002bf910110621022a70e4f1ec5c1b704a56` 已部署为 release `20260830215638` / image
`sha256:54cb9646912c494d64c1eb664b6a3a8af772c36f5388d8456d669285398c39fc`。Prometheus target、
`21d/4GB`、17 rules/0 unhealthy、persistent volume 与 authenticated query 已通过生产探针，canonical
observation 重置为 `2026-08-30..2026-09-13`。production-safe run
`tui02-80ea002b-20260830-01` 通过 `10/10`、`108/108`、三角色、两 receipt、zero residual；cleanup
recorder `8/8`、六 scope `108/108`，isolated rollback PASS。临时 fixture 已精确删除并查询为全零。

生产 registry generation `30` 的 root-only bundle SHA-256=`c3cc3a05dc509afad99262749d96f2c5c7b715754dd8c8b92ff69a1c86d48b8d`，
sidecar 与 restore dry-run 均通过。结构化 Day 0 证据为
[`tui02-production-day0-checkpoint-2026-08-30-80ea002b.json`](../deployment/tui02-production-day0-checkpoint-2026-08-30-80ea002b.json)，
SHA-256=`1cff7915f03e3c12618ada5e4b02fd3d81741db16c121cd3aef362192a9e4d85`。

`TUI-02=active`、readiness=`5/10 DENY`、`execution_focus=null`。随后一次受控 web-only restart 于
`2026-09-02T15:38:21.178433901Z` 恢复同一候选，旧 retained source 按合同作废；reset artifact 已绑定
候选、旧 checkpoint SHA 与健康探针，cutover evidence 已清空旧 retained projection。下一个真实 checkpoint
是重启后的首个 retained sample；其精确 14 日窗口结束后再收集 structured defect/101-task telemetry、
导出 post-window registry backup/attestation、生成 review snapshot，再由同一 owner 写入 owner/reviewer
两个 role-bound attestations。不得回填或把 Day 0 backup 当成 final attestation。

### 13.17 AUD-04 repository archive/rehearsal checkpoint

在不触碰生产的前提下，AUD-04 已补齐候选绑定的审计归档与隔离恢复演练能力：归档源读取要求
provider-issued reader context，并在读取前后复核 exact candidate；归档窗口采用半开区间、限定 scope、
确定性排序和成员上限；canonical JSON codec、manifest/stream anchor/replay hash、严格 schema 与重复键
拒绝共同防止替换或降级；恢复目标被固定为 `memory_only`，结果固定
`production_claim=false`、`production_ready=false`。内容寻址归档存储只提供写入和校验读取，没有删除接口。

Repository exit 证据为
[`aud04-audit-archive-rehearsal-repository-closure-evidence-2026-08-31.json`](../testing/aud04-audit-archive-rehearsal-repository-closure-evidence-2026-08-31.json)，
SHA-256=`1c64e66a5a975b9041f7c1e34291cc0b6d4de8f11d3d16d48f657c8507f4e317`。聚焦回归
`32 passed`，audit 全量回归 `531 passed, 5 skipped`；增量 mypy、债务上限、Black、isort、Ruff、
全量架构扫描及 active-plan registry 校验均通过。治理状态为 `AUD-04=completed`、
`execution_focus=null`，AUD-03 依赖更新为 `AUD-02 + AUD-04`。

这不是 AUD-03 的生产批准或生产验收：仍未执行生产 reader/writer、archive/restore/delete、故障注入、
运行时 profile 切换、部署或 canary。AUD-03 只有在真实生产 authority/profile 可用，并完成受控写入、
恢复/归档演练和负面查询后才能关闭；原生产 exit 标准不因 AUD-04 完成而降低。

### 13.18 DATA-04 PostgreSQL client saturation corrective

2026-08-31 的 successor-bound DATA-02 SELECT-only preview 在业务计算前被 PostgreSQL
`too many clients already` 阻断。只读证据固定：`max_connections=100`、保留槽位 `3`，database
health、service readiness、Audit health 均为 `503`；依赖无关 liveness 仍为 `200`。Web 容器占据
绝大多数 idle client，并按约 30 秒累积；这与 DB-backed Prometheus scrape 周期以及生产
Daphne/ASGI 的 `CONN_MAX_AGE=600` 同时存在。源码还证明 coverage-universe 的所谓读取通过
`get_or_create` 可能隐式写入。

`DATA-04` repository exit 已把生产 `CONN_MAX_AGE` 固定为 `0`，读配置改为纯 SELECT +
`MISSING_CONFIG` fail-closed，显式 PUT/save 成为唯一初始化边界，并补管理命令、API、repository 与
production-settings 合同。证据
[`data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json`](../testing/data04-asgi-db-select-only-preview-repository-closure-evidence-2026-08-31.json)
SHA-256=`aaaa675ed5bc078a916244de91bf2a335da5e2519883b312c2cc1dd0a034ea8d`；聚焦 `18 passed`，
增量/全量 mypy、current-data、架构、格式、Django、migration 与治理门禁通过。

本次未终止生产 session、重启、部署、写库或回填，故不宣称 incident recovered。
`DATA-02` 新增 `DATA-04` 依赖；下一步必须另行授权部署含修复的 clean candidate，验证连接数跨多个
scrape interval 不增长且 readiness 恢复，再重跑 candidate-bound dry-run。部署或重启将使当前 TUI
观察候选发生变化，必须按 TUI-02 规则重绑定并重新计时，不能保留旧窗口完成度。

### 13.19 DATA-05 financial repository bounded-owner corrective

DATA-04 扩大回归确认一个独立 HEAD CI blocker：`financial_fact_repository.py=243` 非空行，超过
`200` 行预算，且修改前工作树与 HEAD 完全一致。DATA-05 在不改公开 repository identity/behavior 的
前提下，把 availability preview/backfill 持久化抽到 65/100 行的独立 owner，原模块降到 189/200；
结构门预算和债务基线均未提高。新 owner 同步纳入 current-data source/marker 清单。

证据
[`data05-financial-repository-owner-closure-evidence-2026-08-31.json`](../testing/data05-financial-repository-owner-closure-evidence-2026-08-31.json)
SHA-256=`7c535f2a1802561be3430a8a9a2149da4ab08b885f2ad672f96828209da8a56a`；聚焦 `12 passed`，
扩大回归 `70 passed`，mypy/debt、current-data、格式、3,006-file architecture、Django/migration 与
治理门禁通过。该单元纯 repository 整理，未连接/写入生产、未重启/部署/backfill，不解除 DATA-02
生产阻塞，也不改变 TUI-02 候选/观察规则。

### 13.20 候选只读可用性事故与 decision-readiness fail-closed 修复

2026-09-02 对当前 TUI-02 候选执行了一次低频、候选绑定的只读观察，未部署、未重启、未写库、未改配置。
候选身份没有漂移：commit=`aa7127ff4d9f71555b0d0486314da5518bd2ac20`、release=`20260901232812`、
image=`sha256:55d2b1d8dd7078acc42aef72f0fa33e57035d30e5c2727b574dfd43aafd9519c`，运行 Web 容器
restart=`0`、OOM=`false`，但在 `2026-09-02T09:24:13Z` 已为 `running/unhealthy`。同一时间公网
`/api/health/`、`/api/ready/`、`/api/decision-ready/` 均返回 `502`，Caddy 记录到 `web:8000`
上游连接超时；最后一次容器 healthcheck 也以 2 秒连接超时失败。Prometheus 仍为
`running/healthy`、restart=`0`、唯一 scrape target=`up`，但 `/api/ready/` P95=`4.875s` 的
`HighAPILatency` 告警处于 pending。此前一次 12 秒 decision-ready 探针无响应，Daphne 日志记录了
超时 application instance 被杀；同一观察窗口中 Celery 的 `refresh_market_thermometer_task`
耗时约 `110.10s` 成功完成，并伴随 EastMoney/AKShare 断连或 502 警告。这些是事故事实，不足以
推断单一根因，也不能把当前服务状态判为可用。

候选只读工件为
[`tui02-production-readonly-refresh-2026-09-02-aa7127ff.json`](../deployment/tui02-production-readonly-refresh-2026-09-02-aa7127ff.json)，
SHA-256=`8992083e05e5a45c4b22ae20b88802cdc0485d844ecfd8f7942035eeeedb6c16`，并附 sidecar。该工件固定
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`、决策门
`DENY`/`must_not_use_for_decision=true`，不能作为 production UAT、容量、恢复或签署证据。

为避免全局决策门已经 blocked 时仍扫描 5,533 资产并再次拖住 Web，本地新增
`run_decision_readiness_checks()` 的 fail-closed 短路：持久化 runtime gate 非 `ok` 或明确
`must_not_use_for_decision` 时，直接返回完整四键 blocked projection；gate open 时保留原四项严格检查。
`core/health_checks.py` 的增量 mypy regression=`0`，Black/isort/Ruff 通过；完整
`tests/component/test_health_checks.py`=`25 passed in 179.93s`，新增 blocked/open 两路径回归均通过。
修复已提交为 `ac95af184` 并推送，尚未部署到上述候选；对应 CI 与 review 完成前不改变生产绑定。

后续 reason-code 校正提交为 `efe301941`，Architecture、Security、Consistency、Fast Feedback 四条
CI 均 completed/success（run `33615499188`、`33615499197`、`33615499196`、`33615499201`）。
CI 只证明仓库合同，不改变生产候选或恢复状态。

本节不授权或暗示远端恢复动作。下一步是等待 CI/review，并在另行明确批准后只做一次受控候选恢复
（restart/deploy 二选一）与重新取证；任何 restart 都会使 TUI-02 retained window 按规则重新绑定，
并需复核 Caddy/Daphne/healthcheck 的恢复机制。DATA-02、AUD-03、EVID-01/02、STRAT-01、TAR-01/05
以及 TUI-02 的 14 日窗口、queued/load/chaos、restore/rollback 与 owner/reviewer 门禁均保持原状态。

### 13.21 Web liveness host-watchdog repository slice

对 13.20 事故的仓库侧整改不通过重复部署解决，而是补齐明确的服务器端恢复合同：新增
`scripts/vps-web-watchdog.sh` 与 systemd service/timer 模板。watchdog 只读取 compose `web`
容器的 Docker health 状态；连续三次 `unhealthy` 后才允许 `docker compose ... restart web`，并
保留 15 分钟冷却、每小时最多两次重启和最多 120 秒恢复等待。它不会直接 kill 共享 PID namespace
中的 Daphne，也不会重启 `runtime_ns`、Celery、PostgreSQL、Redis、volume 或写入数据库/配置。
`healthy`（包括 decision-ready 业务门正确 blocked）会清理失败计数而不触发重启。

`tests/unit/test_vps_web_watchdog.py` 覆盖阈值、精确 Web-only restart、恢复确认、冷却、滚动重启预算
和健康清零；`sh -n` 与现有打包脚本检查通过。实现已提交为
`efdbb63c6c9ccc2b108ab3e5f3155404dc0758bf`，Architecture `33619653200`、Security `33619653029`、
Consistency `33619653074`、Fast Feedback `33619653085` 四条 CI 均 success。watchdog 是一次显式运维安装，不随应用部署自动启用，
不使用 Docker socket sidecar；本 slice 未安装、未重启、未部署或修改 VPS，未改变当前候选、TUI-02
观察窗口或任何 DATA/EVID/STRAT/AUD/TAR 门禁。下一步仅在明确授权后安装 timer，并对实际恢复取一次
候选绑定证据；安装或任何 restart 都按 TUI-02 规则重新绑定 retained sample。

### 13.22 TUI-02 retained checkpoint 跨平台哈希护栏

候选 `aa7127ff4` 的 retained checkpoint sidecar 使用 Git canonical LF 字节，但 Windows
`text=auto` checkout 会把工作树 JSON materialize 为 CRLF。此前
`scripts/check_web_to_tui_cutover_readiness.py` 调用的 retained validator 直接哈希 raw bytes，
因而在本机把有效 checkpoint 误判为 `retained_source=false`；Linux CI 不会暴露该差异。

`scripts/web_to_tui_retained_observation.py` 现在在绑定和校验时统一使用 UTF-8/Git-compatible LF
字节，仍对内容变化保持 SHA fail-closed；不会修改生产 raw-byte provenance，也不会放宽候选、观察窗口或
任何生产门禁。新增 CRLF checkout 回归，以及候选绑定的 restart-reset 合同：reset artifact 必须证明同一
候选、旧 checkpoint SHA、web start/healthy、public health/ready=200 与 decision-ready=503 fail-closed；
绑定后 retained projection 与 post-window 证据被清空，旧样本不能与 reset marker 共存。验证：retained/readiness
focused `44 passed`；当前 readiness 仍 `5/10 DENY`，重启后的新 retained sample、telemetry/defect/backup/
attestation 证据未被伪造。

### 13.23 VPS bundle watchdog 资产验收护栏

watchdog 已由 `scripts/package-for-vps.ps1` 纳入部署包，但原
`scripts/verify-vps-bundle.ps1` 的 required-file 集合未强制检查 service、timer 和脚本本身；
这会允许不完整的 bundle 在不启用 watcher 的情况下通过文件验收。现已把
`deploy/agomtradepro-web-watchdog.service`、`deploy/agomtradepro-web-watchdog.timer` 与
`scripts/vps-web-watchdog.sh` 加入 required-file 合同，并补 verifier source regression。

`tests/unit/test_vps_web_watchdog.py` `5 passed`，PowerShell parser 通过；本 slice 不安装 timer、
不部署或重启 VPS，不改变候选、retained window 或任何生产门禁。

### 13.24 当前候选计划/索引投影一致性护栏

新增 `test_current_candidate_identity_is_consistent_across_registry_and_evidence` 的计划投影断言：
它从 active registry/cutover binding 读取不可变 candidate commit/version，并精确校验
`docs/plans/README.md` 的 `web-to-tui-m5` 行与 `docs/INDEX.md` 的 M5 readiness 行同时包含该绑定。
同时校验 `TUI-02=active` 与 `5/10 DENY` 的当前状态投影。这样候选或状态切换时若只更新机器真源
而遗漏人读计划或索引，测试会 fail-closed；本 slice 仅验证静态投影，不改变 registry 状态、生产
候选、VPS、TUI-02 观察窗口或任何生产门禁。

### DATA-15 情景证据切片检查点（2026-09-10）

[后续原始检查点](../testing/data15-scenario-checkpoint-2026-09-10.json)绑定上一检查点 SHA：
主代理补历史窗口、样本唯一性、研究用途限制与 fail-closed assessment，相关回归 33 passed，
Black/isort/Ruff 通过。Research 增加 45 个分支，当前 3799/5032=75.50%，行 12271/13544=90.60%。
距离 80% 尚需 227 个分支；Task Monitor/Signal 结果不变。Luna 状态模型片仍在进行，最终完整
同范围回归未执行，DATA-15 保持 active。生产前置缺项不变，本片没有新的生产查询或写入。

后续[状态模型检查点](../testing/data15-state-checkpoint-2026-09-10.json)：Luna 测试片经主代理
审查并补内部辅助函数类型，89 passed，Black/isort/Ruff 通过。Research 再增加 124 分支，
当前 3923/5032=77.96%，行 12399/13544=91.55%，距80%尚需103分支。下一Luna片只补R4/R5
监控；最终完整选定范围回归仍待执行，DATA-15未完成。

后续[证据契约检查点](../testing/data15-evidence-checkpoint-2026-09-10.json)：主代理补样本守恒、
指标完整性、精确输入与跨输出授权隔离，46 passed、Black/isort/Ruff通过。Research分支
3955/5032=78.60%，行12430/13544=91.78%，距80%需71分支。Luna继续R4/R5监控，DATA-15
保持active；最终完整回归待切片结束后执行，生产退出门无变化。

### successor 留样通道实查（2026-09-10）

主代理复用现有只读 collector，仅重绑预期候选三项常量，返回 exit=2、
`migration_series_count_unavailable`。原始源码/输出见[留样缺项证据](../deployment/tui02-successor-readonly-pending-2026-09-10-dba9ab2c.json)。
该 blocked 输出不含原始容器/查询 metadata，不冒充新的完整候选身份回执；前述 successor
身份取证单独保留。无有效首个样本，不能开始14日窗口；未发业务请求制造指标，未修改生产。


### DATA-15 最终退出检查点（2026-09-10）

[最终验收证据](../testing/data15-domain-closure-evidence-2026-09-10.json)保留原始前后 coverage JSON、
JUnit、完整命令和源码 hash。固定同一选定范围，从空 coverage 数据运行，1371 passed、0 failed、
0 error、0 skipped；不是增量并集代替完整运行，也不是全仓 Nightly。七个新增测试文件的
Black/isort/Ruff通过，完整治理一致性0违规；生产Python和原有floors未修改。

| Domain | 基线行 / 分支 | 最终行 / 分支 |
|---|---|---|
| task_monitor | 97.32% / 50.00% | 99.11% / 100.00% |
| research | 89.88% / 73.53% | 92.48% / 80.15% |
| signal | 94.71% / 87.82% | 95.73% / 90.36% |

前后分母一致，基线来源文件及最终冻结源码hash均未漂移。DATA-15标记completed，repository
focus释放为null；此前各增量检查点仅为历史过程。没有依赖齐全的后继repository unit。

阶段Goal未完成：DATA-02仍缺真实actor/scope、审计profile selector和dataset-specific对账输入；
EVID-01/02仍缺真实主体/审批与生产证据；AUD-03真实writer/recovery/archive验收未完成；
TAR-05缺独立staging与完整运行/负载证据。TUI只读collector返回migration_series_count_unavailable，
无首个retained sample，不启动或补造14日窗口。已有授权保留，不重复索要泛化确认。

恢复条件是提供既有真实Account用户/actor、tenant/owner/scope与来源记录，配置对应审计绑定及
数据对账合同，并指定独立staging；随后主代理重新核验精确候选、备份/停止线和动作包，串行执行。
未提交、推送、部署或写生产数据；保留全部可审查工作树变更。


### 2026-09-10 当前候选查询接线修复与剩余门禁

[独立修复回执](../deployment/tui02-query-wiring-repair-2026-09-10-dba9ab2c.json)绑定 dba9ab2c8 / release 20260910002501，保留11份原始材料、精确动作、备份和自动回滚记录。
原始collector的 migration_series_count_unavailable 先由认证401触发，不能据此断言没有指标；配置修复后才观察到HTTP 200空vector。Compose配置中的美元符号转义未损坏原哈希。

依据既有单所有者授权，恢复原host-only env的相同字节至当前release，权限0600；仅Caddy以no-deps/no-build/pull-never重建。第一次尝试因Mounts列表顺序误判在重建前停止，新增文件已撤回；独立复查确认实际容器/挂载未变。修正比较后第二次成功。所有原始结果保留，不覆盖失败记录。

验证：HTTPS health 200、认证query 200且up=1、未认证401、非允许路径404、18规则健康；Web/Prometheus的ID、镜像、启动时间、restart count与挂载均不变。pyqlib发行包与qlib导入版本均0.9.7。decision-ready仍503、decision_runtime_blocked；没有启用运行时、改业务权限或写生产业务数据。

截至2026-09-09T18:16:26.069731Z，迁移指标查询返回空vector，first_retained_sample_at/eligible_at均未绑定。TUI-02观察、当前候选UAT及最终验收未完成。后续发布脚本仍需有界修复host-only配置延续并补契约测试，当前运行修复不保证下一次release自动继承。


本轮最终检查：active-plan-registry v78为0违规，完整governance consistency基线v220为0违规，Web-to-TUI inventory通过，git diff --check通过，修复证据及11份嵌入原始材料的SHA均验证一致。Luna max完成最终只读交叉复核。生产Python未变，未提交或推送。

Goal因连续多轮相同真实输入缺项转为blocked，而非complete：需要既有Account用户/actor、tenant/owner/scope及其权威来源记录、对应审计profile selector和逐数据集对账合同，以及独立staging目标和凭据引用。现有所有者授权继续有效，恢复时不重复请求泛化审批。未完成的canonical生产退出门、真实UAT与观察时间不晋级；后续部署脚本配置延续为单独有界开发跟进，不在本轮追加无边界仓库单元。


### 2026-09-10 Goal恢复核验（10:45 UTC）

上一轮为有效进展：DATA-15验收和Caddy接线修复完成。本轮恢复后的阻塞审计重新计为第1轮，Goal保持active，尚未完成。
[当前只读证据](../testing/sprint-resume-readonly-2026-09-10.json)确认候选和容器稳定，认证查询200、up=1、18规则健康，迁移指标仍为空；数据库只读事务确认actor/scope均0、审计runtime字段仍缺。未发生产写入或生成指标。
注册表v79补齐上一轮Caddy修复投影，不晋级任何生产unit；DATA-02/EVID/AUD真实输入与TAR独立staging仍是恢复条件。原1371项测试证据保留，未因纯投影更新重复运行。
