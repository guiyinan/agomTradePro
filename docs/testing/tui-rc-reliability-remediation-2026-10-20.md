# TUI RC 回归收尾整改（2026-10-20）

本轮基线为 `ecb59591e3696b89d0f66457a66993c07efe7e84`，不可移动标签
`tui02-observation-ecb59591e369`。正式 RC `39288001593` 已失败；该标签只记录验证候选，
不构成部署、生产观察 T0 或 TUI-02 关闭。独立 Publication PostgreSQL `39288001502` 成功。

## 已取得的结果

| 验证 | 实际结果 | 解释边界 |
| --- | --- | --- |
| RC 用户流程 | 89 passed，0 failures/errors/skipped | 包含 ReDoc、TUI 主任务、M5；不能替代完整 RC |
| 独立 Publication PostgreSQL | success | 仅绑定 ecb 候选，不能移用于后续修复 SHA |
| Architecture / Consistency | success | 各 job 的原始结果保留 |
| Secrets Scan | failure | 发现的值必须逐项分类，不能批量忽略或缩小正式扫描历史 |
| Critical PostgreSQL | failure | 用例 call 通过；teardown 缺少显式 TEST.NAME，被已有身份保护拒绝 |
| 增量质量门 | failure | 注册期望遗漏已提交的 AutomaticTradingInvocationModel；不包含未合入 G1 |
| Fast Python 3.11 / 3.13 | 同为 8 failed、9396 passed、353 skipped、119 errors、56 subtests | 119 error 包含 29 flush、7 username 唯一键、83 ContentType 唯一键；不能算作 119 个独立业务故障 |
| Nightly 全量 unit | 25 分钟 step timeout | 最后到 87%，已有 20 个 F；没有最终节点清单或 pytest summary，不能记为通过或仅预算不足 |

## 分批目标及验证边界

1. **历史证据误报**：仅对精确证据路径中完整一行的路径到 SHA-256 映射添加规则级 AND 例外；
   Git 对象等其他已证明项仅用精确历史 fingerprint。保留未证明项、原扫描失败和正式全历史入口。
   同版本 scanner 必须复扫，并用同路径的真实凭据形状、同行额外 key、非 hex、错误字段/路径及新提交
   凭据反例证明仍能检出。剩余 38 条已完成来源复核；最终私有历史实扫 exit 0、0 findings，
   六个实际 scanner 反例通过。范围、精确输入及本机归档见
   [安全证据](tui-rc-gitleaks-evidence-2026-10-20.md)，新候选正式全历史 CI 仍待验证。
2. **测试数据库身份及模型注册**：critical 专用 settings 显式绑定 workflow 预建测试库，拒绝缺失、
   空白、同源库和非 PostgreSQL；保留原数据库身份、singleton 和清理保护。注册列表只补 ecb 已有模型。
   先跑反例/注册契约及增量类型、债务与适用生成投影，再由正式 PostgreSQL 工作流验证清理。
   本批本地 10 项契约通过；增量类型、默认全库债务、官方 architecture/test-tier 投影及 runtime coverage 均通过。
   原件仅本机可用：`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-20/tui-critical-postgres-settings-contracts/`，
   `index.json` SHA-256：`75eeffe2b0d7e67c0114f2b1ce23993a9faf5419b9f38c0cdf989e7d540f61d3`。正式 PostgreSQL 清理结果仍待新候选 RC。
   官方 module map build/check 也已通过，44 modules / 209 edges，投影字节与基线相同；
   同一归档下 `module-map-supplement-r1/index.json` SHA-256：`0d68d9b363bb050d73abfeed0c7ab010ca85a77d503cdbd32424a1d64dc49af9`。
3. **事务测试清理**：在全新 PID 隔离 SQLite 库先跑首个 pending 节点，再跑 CI 紧邻前驱与该节点。
   必须取得实际内层异常，区分缺失 singleton、身份拒绝和 SQL 错误。禁止手动补种 singleton、删除
   ContentType/用户行掩盖问题或移除身份保护。修复后再复测权限与两项迁移失败，确认是否独立问题。
4. **导入投影契约**：对确实意图投影的用例使用真实 preview、显式 excluded 及两个 fingerprint；
   原余额、源时间和幂等断言保留。旧 mock 不再命中的 rollback 用例必须沿当前真实写入或投影边界，
   证明 facts-first 合同及无意外经济副作用，不能修改生产行为来迁就旧断言。
5. **全量 unit 诊断**：保留完整 unit 选择、coverage 和单用例 300 秒上限，增加节点级输出；
   可依据本轮 87% 的实际进度采用有限 35 分钟 step 预算取得完整失败明细。此项只是诊断改动，
   20 个未定位 F 必须取得明细并解决，不能通过延时或省略测试宣布通过。

每组以独立、可回退的 commit 提交直接相关源码、测试、必要投影及精简说明。完整日志、JUnit、
脚本和重复源码仅保存在忽略目录或本机归档，索引必须注明本机可用，不能声称远端已持有。

## 并行约束

- A 股 Root 持有共享 Source/index/Git；TUI 仅在明确列出的短窗口合入自身路径，保护四项已有 WIP。
- 本地重 QA 串行交接；独立私有候选可以做只读静态审计。不得使用 A 股原生 PostgreSQL 测试库。
- 尚未共享的 G1 模型、迁移及 HTTP 入口不进入本轮 TUI 修复候选；后续由 A 股重新验证和合入。
- 旧候选的成功 job 与失败原件均保留。修复改变 SHA 后，必须重新冻结标签并取得该 SHA 的完整证据。

## 完成标准、剩余风险与回滚

本阶段完成标准是：上述失败都有可复现的修复或明确的真实阻断结论；新不可变候选完整 RC、独立
Publication PostgreSQL 和全新 S6 结果均绑定同一 SHA。S6 只在一次全新 prepare 的隔离 PostgreSQL
中创建已获授权的临时 superuser，随机口令仅通过内存及闭合匿名 FD 3 传递，不进入 Git、聊天、文件、
环境或日志。合成身份不构成独立人工复核，不能把 production manifest review 状态伪造为通过。

当前未完成项是最终不可变候选的完整 RC（含 Nightly）、独立 Publication PostgreSQL、全新 S6
及具体部署方案确认。导入、费用、SQLite 顺序回归和仓储 owner 拆分的定向类型/投影回归已完成，
见下文；这些本地结果尚不构成最终候选的部署资格。

每组回滚点是该组 commit 的前一 SHA；不改写历史、不破坏外部 WIP。S6 若失败只按 attempt 所有权
清理其隔离资源，不删除生产卷或仅凭 untagged 判断可删镜像。生产服务、账户、迁移、认证和观察 T0
均不在本阶段写入范围；具体部署与回滚方案准备完整后，另交用户确认。

Nightly 诊断候选 `310347fa884f` 的 `39297634789` 已实际完成完整 unit：
24 failed / 21297 passed / 2 skipped / 76 subtests passed，1456.70 秒。原件保留；
失败分组为费用 parser fixture 14 项、QMT 跨平台打包 2 项，及注册/结构/状态和 seal 契约 8 项。
35 分钟预算用于取得明细，不将失败认定为通过。


## 导入与费用测试的实际回归（2026-10-20，本地定向）

手工导入测试沿当前真实 preview、显式 excluded 和双 fingerprint 合同验证；未改变生产导入、
余额、源时间、幂等或 facts-first 行为。RED 使用精确 ecb 全量 Git 导出；GREEN/FOLLOWUP
仅叠加一份手工导入测试修订。每阶段独立进程及全新 PID SQLite clone，迁移开启、预检为
零 pending migration、空 auth/account/账本和唯一有效 authority clock；源码库未创建。

| 阶段 | 实际结果 | 接纳条件 |
| --- | --- | --- |
| Manual RED | 5 failed / 7 passed，0 errors/skipped | 精确命中预先列明的五个旧契约失败 |
| Manual GREEN | 12 passed，0 failures/errors/skipped | 完整导入测试模块 |
| Manual FOLLOWUP | 27 passed，0 failures/errors/skipped | 完整既有 23 项及四项 broker facts 用例 |
| Fee GREEN | 53 passed，0 failures/errors/skipped | 完整费用可用性单元模块；此前 RED 为 14 failed / 39 passed |

费用修订只将 parser fixture 的无约束 `Mock()` 改为 `Mock(spec=["parse"])`，保留原费用断言及业务数值；
不修改生产费用计算。该阶段没有数据库访问，不宣称取得 SQLite 或 PostgreSQL 验证。
其私有源树是精确 1d842fe65 导出加已提交的 critical settings、注册测试与官方 test-tier 投影，
再加这一份费用测试；1d842fe65 到 790844ad4 没有 apps/shared 生产变化。两组均完成源码及模板
前后身份校验，所有受控进程终止；这些结果不替代最终候选完整 RC 或 S6。

首次费用 GREEN 脚本在 overlay、Django 和 pytest 之前，因既有空 `logs` 目录而预检拒绝；
修订版只接受该额外空目录，仍拒绝其中任何文件或子目录。原拒绝记录保留，不能算作测试失败或通过。

56 份原始日志、JUnit、输入与审阅记录已逐项校验并复制到本机持久归档
`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-20/tui-import-and-fee-regressions-r2/`。
`index.json` SHA-256：`02cedf6c0ebf7ff23fafcdfbe4d9e966e8d9940024d219b82af96d7ac5e4638f`。
ZIP 内每项 payload 摘要与原件一致，未移动或删除原件；归档仅本机可用。


## SQLite 事务清理的最小顺序回归（2026-10-20，本地定向）

原 ecb 紧邻前驱会在事务清理时删除迁移持有的 authority-generation singleton，
随后既有严格清理保护拒绝执行，造成后续污染。测试专用 session guard 只在 default SQLite 的显式
clock-inclusive flush 中排除该表；逐次校验测试库身份、唯一合法 singleton、原样 SQL 配对及 generation
不倒退。其他业务表仍正常清理，不补种或修复 clock，不删除用户/ContentType 来掩盖失败，既有 module guard
保持原字节。

| 阶段 | 实际结果 | 覆盖及边界 |
| --- | --- | --- |
| guard 单元契约 | 18 passed，0 failures/errors/skipped | 纯 seam 反例及 nested guard；不等于原生数据库证明 |
| 原紧邻组合 | 1 passed / 1 既有 PostgreSQL skip，0 failures/errors | 原前驱及原 pending 节点，保留精确 skip reason |
| 邻近权限与迁移 | 8 passed / 5 既有 PostgreSQL skip，0 failures/errors | 四个前驱用例、完整 broker 并发文件、精确权限节点及两整份迁移文件 |

邻近组实际通过原三项污染失败：费用 Admin 的 CSRF/外属权限用例、0026 正向/反向保护/再次正向迁移，
以及 0030 可用数量知识标记用例。0030 的另一日期知识参数也通过。三组的用例有重叠，不相加为独立覆盖数。
5 个 skip 均为既有双连接或 PostgreSQL 锁/事务专属场景；原生 PostgreSQL 与其他收集顺序仍由同候选正式 RC 验证。

实际测试使用精确 790844ad4 的完整导出加三份 guard 测试路径和 manual R2；10254 个基础文件加两个新增
测试路径共 10256 文件、967 目录。每组独立 PID 和 fresh clone，零 pending migration、空业务模型及一个
迁移持有的有效 clock；源码库未创建，完整源码/overlay、模板和收据前后身份一致。Python/Node 及已观察
后代均已审计终止。本阶段未修改生产代码，也未写入生产账户、生产迁移或服务配置。

原脚本预检失败、收据少计两个新增路径和未执行的旧 launcher 均保留；最终补充收据仅改原计数的一个 ASCII
字节，源树、pins、模板和严格 worker 检查不变。它们不是业务测试通过证据。73 份原件已逐项校验归档至
`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-20/tui-sqlite-flush-regressions-r5/`，
`index.json` SHA-256：`98c84fe791a4b4c89cb89fff957377877cf10be102a47b62d98dabb98357dd79`。
ZIP 每项 payload 均读回验证；原件未移动，归档仅本机可用。


## D 仓储 owner 拆分的实际回归（2026-10-20，本地定向）

A/B/C 已分别提交并推送为 `7052e6bc3c15`、`9266275dbd13`、`7c47d89d8260`。
本批 D 基于精确 C 组合 DC R1 与 Sim R4：19 个 overlay 含 18 个 Python 文件（8 个新增、15 个生产文件）
及现有 current-data 合同，另有 4 个官方生成投影和本说明，共 24 个审阅路径。测试分层投影仅为 CRLF
与 LF 的换行差异，标准 Git clean 后与 C 相同，不作为提交变更；本批实际有 23 个 Git 变更路径。
Sim R4 相对 R3 只增加
mapper 的显式同名再导出；仓储方法按归属拆分，原兼容入口和业务阈值保留。成本知识测试逐项覆盖未知费用、
未知成本及未知已实现盈亏，保留账户归属和取消交易排除规则。

合同仍为 89 行，仅三项金融合同的 source_files/required_markers 映射到实际 helper；其中 revisions
只变 source_files。九个 marker 移至真实实现，其余 86 行、required_tests 和所有业务字段不变。

| 阶段 | 实际结果 | 限制 |
| --- | --- | --- |
| R6 compose / focused | exit 0 / 34.027 秒；exit 0 / 73.704 秒；199 passed，0 failed/errors/skipped | 21 个完整模块、10 个精确节点和 Windows 打包必过节点；仅为定向回归 |
| 恢复 types | 两条官方命令 native rc 均为 0，363.924 秒，无超时 | 15 个生产文件无增量错误；默认全库债务 0 errors / 0 files，未改债务基线 |
| 恢复 projections | 八条官方生成/检查命令 native rc 均为 0，428.234 秒，无超时 | 包含两份 Data Center 清单、模块地图、测试分层及数据新鲜度合同检查 |

恢复使用原 R6 的同一份 10,264 文件源码及正常 mypy cache，每条命令立即保存实际退出码和日志摘要。
完整源码、19 个 overlay 原始字节和模板在阶段前后校验；最终仅四个正式投影相对组合收据改变，
只容许打包测试产生的空根 tmp。focused 使用全新 PID 的隔离 SQLite clone、正常迁移预检及唯一有效 clock，
没有源码数据库；两段恢复和定向测试的受控进程已终止，不能替代原生 PostgreSQL 证明。

旧 D-driver R4 / Sim R3 的两项隐式再导出类型错误，以及 R6 quality 的 900.328 秒超时原样保留；
原超时目录没有补写成功 summary。新的两段恢复独立记录十条实际 native rc=0，聚合收据 SHA-256：
`b9a424bf2fee6051e8597888f3c6a5d4c3d828b8684a0414ea9829ad181e36c2`。
消费脚本的目录/字段兼容拒绝与日志摘要抄录错误亦保留，没有修改通过原件或生产逻辑。

124 份冻结输入、源码 payload、日志、JUnit 和收据已逐项校验并归档到本机：
`C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-20/tui-d-owner-splits-r6-recovery-final/`。
index.json SHA-256：`920f21a456de771b79ca5fc7be8f8626018d01414c999ed35e3e80e385774678`。
ZIP 每项均读回与原件比较，原件未移动或删除；归档仅本机可用。

C 的 CI 另发现两份测试文件需 Black 格式化；两个候选与 C 的完整 AST 相同，Black 26.3.1、isort 和 Ruff
均已通过，作为 D 之后的独立格式提交。最终发布证据必须绑定这两批提交后冻结的同一个新标签；旧 Nightly
24 failed / 21297 passed / 2 skipped 仍为历史失败，不能以本次 199 项定向通过覆盖。
本批不部署、不创建生产账户、不启动观察 T0，也不关闭 TUI-02；完整 RC、独立 PostgreSQL 和 fresh S6
尚待该最终候选实际通过，临时测试 superuser 仅在获授权的一次性 S6 数据库创建。

## D 最终候选的正式 RC 反馈与下一批边界（2026-10-20）

D 已实际提交为 `78c1a35e5970`，独立 AST 等价格式提交为 `d36174fca625`，
不可变标签为 `tui02-rc-d36174fca625`。完整 RC `39342399965` 与独立 Publication PostgreSQL
`39342419370` 绑定同一 SHA；后者已通过，前者存在失败，不能启动该候选的 S6 或部署。

已确认的失败分为四类：PostgreSQL migration integrity 的 8 个用例体通过但 6 次 teardown
因该步骤缺显式 `TEST.NAME` 被保护器拒绝；NoDB 12,705 passed / 24 subtests passed，
wrapper 148.24 秒超过既有 120 秒；Fast Python 3.11/3.13 各四次 setup 在恢复
序列化 ContentType 时出现唯一键冲突。后者发生在普通事务清理之后，与 Django
[#36429](https://code.djangoproject.com/ticket/36429) 的已接受问题一致，不是四项业务断言失败。
此外，Nightly 全量单测触及既有 35 分钟步骤上限，最后可见进度为 97%；日志收集 21,356 项，
仅能数出已完成的 20,052 PASSED / 2 SKIPPED，没有 pytest 最终汇总，不能视为完整通过。
最后完成事件距离终止约 1.46 秒，未出现单项 timeout traceback，不能认定最后一项挂起。
耗时较长的相邻完成事件集中在全仓清单和投影扫描；这些间隔包含 fixture/runner 开销，
不等于精确的单项测试耗时。正在核查重复枚举和已忽略目录的无效遍历，不提高预算或减少断言。
原 RC 和失败标签保留，不重写或以定向结果覆盖。

下一批只处理这些测试前置和生命周期：migration/current-data 两步骤绑定既有隔离 PostgreSQL
settings/数据库名；为真实 current-data Playwright 节点在同 job 安装 Python Chromium；
NoDB 既有命令追加 `-- -n 2`，不改完整 812 文件选集、guard 或 120 秒预算；SQLite
收集顺序把会普通 flush 的事务用例稳定排在序列化恢复用例之后，保留所有用例、marker 和业务断言。
不清理 ContentType 来掩盖冲突，不补种 clock，不给所有事务强制启用慢速序列化恢复。
这五路径补丁当前仅为私有候选，三份 Python 副本经 Black 格式化；显式 `zip(strict=False)`
保持既有行为，最终 Black/isort/Ruff 均实际 exit 0。初次格式检查失败和 Ruff B905 原件保留。
新增排序契约真实依赖 `django.test`，必须用官方生成器更新
test-tier 投影；完整 Fast 812 文件选集不变，两份修改的契约模块仍须显式运行。

本地首轮实际验证：旧代码两节点 RED 为 1 passed / 1 setup error，精确复现 ContentType
序列化恢复冲突；修复后 fresh PID/独立 SQLite GREEN 为 2 passed，0 failed/errors/skipped。
两阶段 preflight 均通过，迁移完整、源码库未创建；RED native 1 和 GREEN native 0 均原样保存。
官方 test-tier `--write`、`--check` 分别 native 0，两份显式契约模块合计 28 passed。
以上为本地定向结果，尚未提交，也不替代全量 RC。

原 NoDB runner 在 Windows `CreateProcess` 处因完整 812 文件参数列表触及 `WinError 206`，
0.206 秒/native 1，未收集测试。该失败原件保留；本地适配器复用官方选集、命令构造和预算，
仅将参数列表交给 `pytest.main`，保留 `-n 2`、guard、strict markers 和 120 秒预算。
适配结果不等同原 subprocess runner 或 Linux 预算资格，真实 RC 仍须使用原命令。
该适配实际在两个 worker 上开始执行，最后可见 22%，在既定 180 秒外层上限终止
（180.318 秒，managed rc 124，taskkill rc 0），无最终 pytest 汇总；结果为未通过，不能计作完整覆盖。
本次借用窗口内未提高预算或再次运行。全部受控进程族已核查为空，完整源码前后 10,264 文件/
967 目录校验通过，仅五份精确补丁及官方 tier 投影变化；00:55:26 UTC 已向 A 股显式归还 Backend。

本地 Python 3.13.5 / pytest 8.3.4 / Django 5.2.12 与 CI 不同。本地 canary 只能验证
完整选择及 worker/排序兼容；Linux 上的总耗时和 24 个 unittest 子测试汇总必须由新冻结候选
的真实 RC 确认。修复后使用新标签，重新完成同 SHA 的完整 RC、独立 Publication PostgreSQL
和全新 S6；不能拼接 d361 的独立 PG 成绩。

Owner 已授权在一次性 S6 PostgreSQL 创建随机测试 superuser；无需再次输入人工口令。
口令仅在内存、Docker stdin 与闭写端匿名 FD3 间传递，不进入 Git、文件或发布证据。
该账户尚未创建，不修改生产账户，也不满足独立人工复核；S6 的
`production_manifest_review_satisfied=false` 和待确认部署边界保留。

## NoDB fast-suite worker-count follow-up (2026-10-20; trial only)

The frozen candidate `tui02-rc-b09671199427` (`b096711994277f373bd98262c90f81d521966ded`) has four automatic CI checks marked successful. The automatic NoDB observation using the existing `-n 2` command completed 12,705 tests plus 24 subtests in 82.61 seconds. In formal RC `39352075318`, the same NoDB gate took 131.39 seconds and exceeded its unchanged 120-second fast-suite budget. The independent Publication PostgreSQL run `39352086657` succeeded; the required RC journey succeeded and the eight migration cases completed without teardown errors. The formal RC still failed on QMT current-data PostgreSQL nullable-outer-join row locking, in job `118398334645`, node `test_batch_retry_preserves_observation_and_volume_contract`; these results do not qualify the candidate for S6 or deployment.

This private trial changes only the fast workflow invocation from `-n 2` to `-n 4`. The public GitHub-hosted `ubuntu-latest` standard runner is documented as 4 vCPU / 16 GB ([runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)); explicit `-n 4` is intended to test worker-count alignment while retaining the same selected files, guard plugin, strict markers, per-case limits, eight-minute job timeout, and 120-second aggregate fast-suite budget. It does not change runner scheduler defaults or use `-n auto`. No `-n 4` result exists yet, so this is an unvalidated timing experiment and cannot be described as a fix or as proof that the budget will pass.

For the earlier `d36174fca625` Nightly log, the corrected broad progress-line parser counts 20,711 `PASSED` and 2 `SKIPPED`; it replaces the earlier 20,052 count, which came from a narrow expression that missed whitespace-bearing node IDs. Nightly still timed out without a final pytest summary, and the count remains incomplete progress evidence, not a green result.

## NoDB prepared-world isolation and worker rollback

- The four-worker trial did not meet the unchanged 120s budget: 5da recorded 12705 passed + 24 subtests / 157.72s; G1 26ed recorded 12717 passed + 24 subtests / 159.44s. Both failures remain failures. This change returns to two workers without changing the inventory, guard, assertions, parameters, dependencies, or budget.
- The scope test module now prepares its valid world once per module/worker and deep-copies the complete tuple for each test. Every test receives independent nested mutable state; production authorization and current-read validation remain unchanged. All original test-function ASTs and the original setup body are preserved.
- In private Windows Python 3.13 QA based on 26ed, both versions passed the same 19 cases with zero failures/errors/skips. Pytest elapsed changed from 57.96s to 10.59s (wrapper 86.858s to 27.495s); these local timings do not establish the complete Linux 120s gate. The actual input also contained the separately prepared QMT four-path overlay; this is local scope evidence, not clean-candidate RC qualification.
- Original evidence: `.tmp/tui-rc4-followup/qmt-nodb-private-actual-r4-base26ed7080ab6d/` (`scope-baseline.xml`, `scope-green.xml`, logs and `result.json`). That combined run subsequently stopped on a 180s setup/reproduction timeout before the first control-plane case completed; it did not establish the migration mock RED or run QMT PostgreSQL/mypy. All observed process families were closed, no PG was started, and no unexpected tracked source drift was found.
- Full Linux NoDB timing and final same-candidate RC, direct Publication PostgreSQL, and fresh S6 remain required. No test account, deployment, observation T0, or TUI-02 closure occurred in this batch.

## Migration-test connection state isolation

The b096 full-unit run completed with 20 failures and 36 errors, including transaction bodies and cleanup rejected by pytest-django after pure migration tests. Three tests patched `ensure_connection` on a connection instance; monkeypatch cleanup restored a bound blocker as an instance-local shadow. The fix patches the connection class so cleanup restores dynamic inheritance. It changes only test isolation, preserving production migration logic, database guards, collection order, and existing assertions.

A new no-SQL regression compares exact instance-local membership and value identity before and after the existing fully faked migration helper. In private Windows QA, its RED run failed on `assert True is False`; the corrected complete module passed all 15 tests, with zero errors or skips. Black, isort, and Ruff passed. The reused source was based on 26ed with the separate QMT overlay and scope clone, so these results are targeted isolation evidence, not clean-candidate RC qualification. Evidence: `.tmp/tui-rc4-followup/seam-nodb-private-actual-parent-r2/`; result SHA-256 `b29f21351986eba820966990cb2bde7f58fdb739f3f979ecdd05083c30cc439a`. The RED run also emitted a Windows cache-rename warning; GREEN emitted none. All observed process families were closed and no PostgreSQL was started.

For the preceding prepared-world commit 921f215e, complete automatic Linux CI passed: NoDB 12,717 tests plus 24 subtests, 115.52 seconds against the unchanged 120-second budget; Python 3.11/3.13, quality, consistency, architecture, and security checks also succeeded. This does not replace final same-SHA RC, direct Publication PostgreSQL, or fresh S6. No test account, deployment, or observation T0 has occurred.
