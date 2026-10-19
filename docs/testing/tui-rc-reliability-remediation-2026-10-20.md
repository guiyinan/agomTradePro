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

当前未完成项包括：安全修复的新候选正式全历史 CI、四处仓储 owner 规模整改及其回归、Nightly
完整复验、新候选完整验证及 S6。导入、费用及 SQLite 最小顺序回归已完成，见下节；完整回归通过前，
没有部署资格结论。

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
