# ASH-03 订单预留实施切片

> 本文细化主计划原 §7 的剩余工作，不改变 registry 的执行焦点、单元依赖或退出条件。
> 纯领域原语与 G1 持久预留/既有写口保护已完成本地验收并接入共享开发树；部分成交、重启恢复和原单元其他残项继续保留，不代表整单元或生产资格。

依据：[A 股主计划 §7](a-share-usability-implementation-plan-2026-10-16.md#7-ash-03结算预留和费用)；[原单元七组残项](../testing/a-share-ash03-unit-exit-remainder-2026-10-19.md)。

## 分批交付

1. 纯领域原语：精确金额/股份的承诺资源、已消耗与已释放守恒；区分账面、可用、冻结及未知可取现金；显式 Fee V2 预算与请求/费用摘要。独立提交此步必须说明尚未接入数据库或用户交易入口。
2. 持久预留与现有写口：在现有 simulated_trading 账本所有者内增补窄 hold 记录；同账户订单键唯一、完整请求与费率/结算来源快照不可改写。所有 reserve/cancel/ordinary fill 遵守 account 父锁；普通手动和自动成交扣除其他订单承诺，SDK 平仓、通用账户/持仓写入和 reset/delete 不得绕过。Admin 不再直接编辑账户/持仓金融行，业务更改走用例。新增表无历史推断回填，任何存量记录阻止反向删表。
3. 部分成交、撤单与差额：实际 fill/event 键幂等，成交与对应 hold 消耗在同一事务；剩余委托继续受预算和可卖量保护。终态释放一次，不能借重复回报释放其他订单。与第 2 步分开验收和提交。
4. 持久恢复：重启后读取保存的订单/hold/fill/事件事实恢复，不以进程内状态、超时或过期行情擅自释放。未知成交结果必须明确不确定并对账。

原 §7 的费用修订、历史可卖差异、普通模拟/回测同输入最小对照、旧自动止损调用仍按原残项第 4—7 组执行。此切片不代替整单元完成；ASH-07 仍以 ASH-03 原退出条件为前置。

## 资金与数量约定

- 当前账面现金和已结算可卖量仍读现有 Account/Position，hold 只记录已承诺资源；不另存第二份可用余额。
- BUY 冻结限价金额加明确费用预算，预算不得小于精确 Fee V2 逐项分舍入估计；未知费用不得按零处理。
- SELL 仅冻结已知可卖股数，费用从限价成交收入抵扣，只有净现金缺口才需现金预留。因此已知零现金但收入覆盖费用的卖单可建立。
- pending T+1 已成交数量不能作为未成交委托、不能提前变成可卖；到期结算与建 hold 必须同事务，失败全部回滚。
- 可取现金缺少独立资金交收来源时为 None；不由账面现金、股票 T+1 或当前时间推断。
- 同键重试核对完整 intent hash 以及含原 fee hash 的 reservation request hash；精确重放不依赖当前来源可用，也不自动采用后来费率改版。

## 验收与质量控制

先以未实现的基线运行失败反例，再验证候选。纯单元覆盖金额/股份精度、合法尾零、低 Decimal context、未知与零、费用不足、竞争预留、摘要冲突、部分消耗守恒和重复终态释放；Domain 覆盖目标不低于 90%。

持久组件必须验证：owner/active scope、同键异载荷、费用改版后的精确重放、SELL 现金零、pending T+1、事务中注入写入失败、ordinary/manual/auto 与 SDK close 绕行、reset/delete、Admin 只读。SQLite 只验证业务与原子性；并发互斥须 PostgreSQL 两连接，覆盖 BUY/BUY、SELL/SELL、hold/即时成交和撤单/重复创建。反向迁移有行拒绝、无行可回退。

每批生产 Python 执行格式/lint、增量 mypy 与默认债务门禁；不抬基线。新增模块运行官方 module-map 构建和检查；模型变更运行官方数据字典构建和检查。首批不新增 HTTP 路由；后续任务界面和跨端入口须补 Content-Type/状态码及实际主任务旅程验收。

保存精确候选文件摘要、命令/结果和失败原件位置。完整日志留 Git 忽略目录或持久归档，只提交紧凑结论/索引。共享源码、生成投影、index/Git 与重 QA 窗口按当前并行会话实际进程终态交接。

### 集成中发现的前置修复

低 Decimal 精度下，既有数量规则的取模会误拒绝合法买卖，零股余量的减法还会错误放行不整步的余额。旧代码的五个定向反例实际为三失败、两通过；隔离两处运算精度后，含这些反例的 116 个单元与兼容用例通过。此修复修改既有即时结算路径，须单独通过类型检查并单独提交，不能混在“尚未接线”的纯预留原语中。

持久化批次先得到 23 个 PostgreSQL 组件通过与一个真实数据库约束红测：BUY 的初始现金等式未落为数据库约束。修复后，实际迁移往返、历史行保留和 PostgreSQL 表锁两例通过；金额/预算三个反例、资源阻断原因及正常买卖共七例通过，均无跳过。资源阻断原因也先在旧仓储得到两例真实失败，再验证修复，避免把资金不足统称为无效请求。普通写口、其余结算回归、并发、类型检查和持久恢复继续保留，不由这些局部通过替代。

失败原件与源码绑定保留在 `.tmp/ash03-integration-qa-535`、`.tmp/ash03-decimal-red-537`、`.tmp/ash03-integration-qa-538` 和 `.tmp/ash03-integration-qa-539`；535/538 等原件已按逐文件哈希归档到本机 `ash03-hold-quantity-and-constraint-red-538.zip`，并未上传或转为 CI/生产资格。正式交接时归档后续原件并生成紧凑索引。

## 风险和回滚

第一步尚未持久消费，不激活任何订单；撤销该未接入代码不改账本。引入持久表之后保留订单键与初始承诺，禁止通过删表/删行回滚已接受订单。应用回退必须能识别 active holds 并阻断旧写口，不允许回到完全忽略预留的成交版本。生产部署、真实来源资格和券商执行继续沿原门禁单独验收。

## 纯领域阶段验收（私有候选）

冻结基线 `cbdccd361814a5d10039f837de46f3b18bbe230e` 上的新 Domain 文件与对应测试已验证：24 个唯一用例，分支模式综合覆盖 94.27%，Black/isort/Ruff、增量 mypy、默认全量类型债务门均通过。官方 module-map 构建/检查通过；共享接入时按当时源码重新生成投影。

前置失败证据保留：未实现模块的收集失败；BUY 尾零测试误断言 SELL 冻结量；非布尔终态标志触发的三个真实失败；私有目录被默认 coverage 配置排除；首轮整数幂推断产生的一条 mypy 错误。最终修复没有抬高任何基线。相同用例的重复验证不累加数量。

具体文件摘要、命令、结果、原件校验和本机归档位置见[验收索引](../testing/a-share-ash03-reservation-domain-2026-10-19.json)。该索引不证明 hold 的数据库持久化、普通成交接线、并发互斥、用户旅程或正式 CI 已通过；第 2—4 批及原第 4—7 组仍保留。

## 共享开发树接入验收

在开发基线 `4c5361d10a96e1e125b59dc705435ef5a0871534` 上接入相同两个 Python 文件，24 个唯一单元用例、Black/isort/Ruff、增量 mypy、默认类型债务门及官方模块地图构建/检查均通过。覆盖率仍引用相同冻结源码的私有 521 实测 94.27%，本轮未重复采集覆盖率。原件与文件摘要见验收索引的 `shared_adoption`，原件仅在本机归档可用。

本批没有接入既有数量精度修复、持久表、迁移、普通成交联动或用户入口；未完成项与原 §7 退出条件保持。实际提交 CI 和生产资格须分别取证。

## 既有数量规则精度修复（独立批次）

仅将既有取模与卖出余量减法/取模放入精度80的局部 Decimal context，保持普通订单最小量、步长和零股条件原样。五个低精度反例已先在旧源码取得三失败、两通过；共享开发树现已通过该测试文件全部 79 例、格式/lint、增量 mypy 与默认债务门。该结果不代表持久预留、并发、部分成交或整个 ASH-03 已完成。具体命令、摘要与原件见[数量精度验收](../testing/a-share-ash03-quantity-context-2026-10-20.json)，实际 CI/生产资格单独取证。

## G1 持久化与既有写口保护验收（2026-10-20）

第2批已接入持久 hold、请求/费用快照、同账户锁、精确重放和取消释放，并阻断普通成交、SDK 平仓、账户/持仓通用修改及 reset/delete 绕过预留。七组定向测试逐组通过，含 PostgreSQL 两连接并发和迁移往返；类型、分层覆盖与官方生成投影门禁通过。详见[G1 验收](../testing/a-share-ash03-g1-order-reservation-2026-10-20.md)，完整日志与失败原件仅本机归档。

接下来第3批先完成持久成交事件读取、完整链校验与原子消费，再推进第4批停机恢复；当前私有候选不作为已接入或已验收代码。原第4—7组仍按残项清单执行，registry焦点及整单元退出条件不变。应用回退仍须识别存量hold并阻断绕行，不能以反向删表回退。

## G2 分阶段交付（2026-10-20）

G2A 已完成成交经济/日历证明、不可变回执模型与0036迁移、V4绑定及owner精确只读重放的本地验收；详见[G2A验收](../testing/a-share-ash03-g2-fill-receipt-reader-2026-10-20.md)。32/216/77三组通过，迁移定向6例包含于77，不重复计数；逐文件分层覆盖、14生产文件类型和官方投影门禁通过。失败原件仅本机归档，未借此声明正式CI或生产资格。

G2B 单独验收原子消费与全部现有写口/读取邻接路径兼容；G2C 接入合格的durable matcher并验收停机恢复。G2B3已新增真实原子成交与取消写入口，但不关闭原第2、3组或ASH-03整单元；第4–7组、registry焦点及ASH-07依赖保持。

## G2B1 账户重置保护（2026-10-20）

带持久成交回执（订单或成交任一侧属于该账户）或V4成交标记的账户，重置前在账户锁内明确拒绝并保留全部账本。仓储及真实owner API均覆盖，接口返回422与`ORDER_FILL_HISTORY_RETAINED`。本批PG32项和SQLite重复选择3项均通过，生产两文件类型、分支模式逐文件综合覆盖及官方投影门禁通过；详见[G2B1验收](../testing/a-share-ash03-g2b-reset-history-2026-10-20.md)。

本批只关闭成交历史删除保护缺口。原子消费、读取邻接兼容、首次BUY、V4待结算释放、合格模拟来源组合和重启恢复仍按后续G2B/G2C推进；原七组当前关闭条件见[退出清单](../testing/a-share-ash03-unit-exit-remainder-2026-10-19.md)。未改变registry焦点或获得生产资格。

## G2B2 SQLite 预留守恒与迁移前置（2026-10-20）

SQLite预留守恒改为逐字段整数分/微份额比较，0037先只读预检全部既有行，再替换约束；不修改财务值，PostgreSQL原NUMERIC语义保留。完整前驱SQLite54/PG55通过；最终仅helper类型修正后双库各9项定向通过，5生产文件类型及官方投影门禁通过。源码与范围分别记录在[G2B2验收](../testing/a-share-ash03-g2b-sqlite-precision-2026-10-20.md)。

G2B3已把真实fill/cancel写入口接入SQLite统一精度守卫；首次BUY、V4 pending释放、来源组合、读取邻接和重启恢复仍待单独验收。默认来源未激活，不关闭原第2–7组；生产迁移与发布资格另行验收。

## G2B3 原子成交写入与取消完整链（2026-10-20）

G2B3将成交与hold消费、Trade/Position/账户更新、Fee V2累计差额及取消释放接入同一事务，并统一使用SQLite整数单位精度守卫；逐笔回执链先校验再写入。最终6文件同一候选在SQLite85项、PostgreSQL88项通过，含48项不变G1仓储回归及3项PostgreSQL并发；四个生产文件各自分支模式综合覆盖均超过60%，4文件增量mypy与默认债务、格式及7项官方投影门禁通过。详见[G2B3验收](../testing/a-share-ash03-g2b-writer-2026-10-20.md)。

未完成边界：首次BUY缺少已有Position时的写路径；V4 T+1 pending释放、durable来源组合、读路径邻接和重启恢复仍未关闭。默认来源仍为None并fail-closed；不关闭原第2–7组或ASH-03整单元，不构成生产/发布资格。

## G2B3 顺序回归与测试隔离修正（2026-10-20）

完整 CI 发现三个 SQLite 撤单用例因旧迁移测试遗留0036结构失败，另两个重置用例在准备阶段被新完整链校验拦截。本批只恢复迁移测试叶节点并调整合成历史准备顺序，保留全部财务与历史保护；旧顺序已真实复现4通过/3失败，最终SQLite75项、PG11项均无失败/错误/跳过。见[测试隔离验收](../testing/a-share-ash03-g2b-ci-fixtures-2026-10-20.md)。新提交CI单独取证，原bf3冻结RC失败保留；首次BUY、V4 pending释放、来源组合和原第2–7组继续开放。

## G2B4 初始估值证明与成交回执基础（2026-10-21）

初始估值证明类型、版本化成交回执、0038 迁移和读取兼容已完成本地验收：122 项单元、双库对应的 46 项 schema/读取检查，以及 SQLite85/PG88 写入回归均通过；逐文件覆盖、类型、迁移一致性和官方投影门禁通过。详见[G2B4 验收](../testing/a-share-ash03-g2b-first-buy-2026-10-21.md)。完整与失败原件仅本机归档。

本批没有把初始估值证明接入 writer，首次 BUY 缺少 Position 的执行仍待下一批；V4 pending 释放、合格来源/日历组合、邻接读取和停机恢复继续保留。0038 在任何 V2 历史存在时拒绝反向删除；回退应用须保留可识别版本及历史的保护。原第2–7组、§7退出条件及 registry 焦点不变；不构成发布或生产资格。

## G2B4 收据反例夹具修正（2026-10-21）

远端 Fast Feedback 暴露 helper 重建有效收据并覆盖反例坏哈希的问题。本批只恢复保存调用方收据，保留 V1/V2 和生产严格校验；两个完整读取模块 SQLite32/PG32 均通过。详见[夹具验收](../testing/a-share-ash03-g2b-receipt-fixture-2026-10-21.md)。首次 BUY writer 与原第2–7组继续按既定边界推进，CI及生产资格另行取证。


## G2B5 首笔 BUY 与初始持仓估值（2026-10-21）

G2B5 将已封存初始估值证明接入首笔 BUY 写入事务；mark 与成交/限价独立，Fee V2 费用、pending lag、Position 创建和原子回滚均有本地回归证据。SQLite/PostgreSQL 写入与并发选择分别为 98/102 项；1177 reader fixture 修订后另有 SQLite/PostgreSQL 各 32 项通过。19源的9项官方生成/检查均通过，含90个新鲜度合同；类型、逐文件分支模式覆盖和独立审查通过。详见[首笔 BUY writer 验收索引](../testing/a-share-ash03-g2b-first-buy-writer-2026-10-21.md)。

本批不激活默认市场数据源；reader 默认未绑定。V4 pending 释放、G2C 来源资格、邻接读取与恢复、ASH-03 原第 2–7 组及 §7 退出条件继续开放，不声明生产或整项完成。

## G2B6A 释放证明持久格式（2026-10-21）

释放证明Domain/codec、Trade可空证明字段与0039约束已完成本地验收：39项单元、最终SQLite13通过/1个PG专用跳过、PostgreSQL14通过；Domain97.5%、codec88.41%、交易模型96.22%，四生产类型及默认债务、格式和11项官方生成/检查通过。详见[释放证明基础验收](../testing/a-share-ash03-g2b-release-proof-2026-10-21.md)。本批不回填历史或激活来源，实际四入口释放及严格读取留待G2B6B；ASH-03原第2–7组和退出条件继续开放。

## G2B6A 历史迁移夹具兼容修正（2026-10-21）

299bdefd CI 暴露旧迁移测试使用最新 ORM 与反向拒绝后遗留旧表结构的问题。本批仅修三个测试函数，保留全部拒绝、锁与财务断言；双库有序选择各25通过/2后端专用跳过。见[迁移夹具验收](../testing/a-share-ash03-g2b-migration-fixture-2026-10-21.md)。新 SHA CI 单独取证，G2B6B与原第2–7组继续开放。

## G2B6B V4 到期释放接线（2026-10-21）

四入口原子释放、严格释放证明读取和账户范围锁定已完成本地双库249节点回归：SQLite237通过/12个PG专用跳过，PG249通过；逐文件覆盖、8生产类型及默认债务、格式和官方投影门禁通过。见[V4释放验收](../testing/a-share-ash03-g2b-v4-settlement-release-2026-10-21.md)。来源资格、邻接读取、恢复及原第2–7组继续开放，新SHA CI另行取证，不构成生产或整项完成。

## G2B7A 既有读取面兼容（2026-10-21）

在 trade、summary、share 与 performance 只读入口补充兼容回归；同一精确 80 节点选择在 SQLite/PostgreSQL 均通过，合并分支模式覆盖按五个变更生产文件逐文件核验。验收和原始证据索引见[读取兼容验收](../testing/a-share-ash03-g2b7a-read-compat-2026-10-21.md)。本批不绑定默认市场数据源，不验证来源资格，不关闭 G2B7B、ASH-03 原第2–7组或生产发布条件。

## G2B7B W1 Trade Admin 历史保护（2026-10-21）

V4 标记或持久回执保护已接入真实 Admin，拒绝修改及单笔/批量删除，并限定批量删除的原选中主键集合；无回执 V3 保留兼容。同一 95 节点双库通过，逐层覆盖、类型、格式、官方投影和架构审计通过，详见[W1 验收](../testing/a-share-ash03-g2b7b-trade-admin-2026-10-21.md)。Position 写口、普通结算邻接、来源/日历与恢复继续按 G2B7B/G2C 推进；原第2–7组和生产条件保持开放。

## Trade 仓储结构预算修正（2026-10-21）

扩展回归实际发现 Trade 仓储 169 行超过既有 150 行预算。本批保持接口及方法体，分离精确历史查询；原仓储 136 行，新仓储 57 行，同一 100 节点双库回归、逐文件覆盖、类型和架构门禁通过。见[结构修正验收](../testing/a-share-ash03-trade-owner-budget-2026-10-21.md)。W1 原 95 项结果保留；Position 与普通结算邻接、来源/日历及恢复仍按原 G2B7B/G2C 和第2–7组推进。

## W2a 持仓直接写口保护（2026-10-21）

已保留 V4 成交历史的同账户、同证券持仓，直接资源改写、删除及无账本重建被明确阻断；报价与证伪、真正无 V4 的 V3 兼容路径保留。同一 61 节点双库、覆盖、类型与架构门禁通过，见[本批验收](../testing/a-share-ash03-g2b7b-position-history-2026-10-21.md)。普通结算续写及清仓后再买入另批处理，正式来源/日历与订单恢复仍待完成，第 2–7 组不关闭。


## W2b 普通结算续写的账户历史校验（2026-10-21）

普通 BUY/SELL 改变账户现金前校验本账户保留的 V4 历史及持仓前缀；损坏关联在跨账户加锁前拒绝，精确回放和合法清仓后再买入保留。私有同源 275 节点：SQLite260通过/15个PG专用跳过，PG三批100+98+77全部通过，逐文件覆盖、类型、格式和官方投影检查通过。原整组PG超时保留为未通过，详见[本批验收](../testing/a-share-ash03-g2b7b-account-history-2026-10-21.md)。最终采用父版本与时间函数结构调整另有100节点SQLite和28节点PG关键回归取证，不把原275节点结果归给新布局；累计投影、暂存门禁和新提交CI各自登记。旧买卖/平仓入口、来源/日历及恢复仍待完成，原第2–7组不关闭。


## W2c1 旧持仓写口的孤立成交历史保护（2026-10-22）

旧BUY/SELL变更及直接保存/删除在账户父锁内保护Reservation已成交/已消费/完成标记，子Receipt或Trade缺失也不得绕行。同源SQLite140项为136通过/4个PG专用跳过，隔离PostgreSQL22项全部通过；两生产覆盖、类型和干净采用父版本的全库债务与官方投影检查通过。详见[本批验收](../testing/a-share-ash03-g2b7b-legacy-orphan-guard-2026-10-22.md)。精确模拟平仓的标准SELL/现金/费用接线、REAL投影类型与owner边界、正式来源/日历及订单恢复继续分批实施，原第2–7组不关闭；本批不激活来源或构成生产资格。

## G2C 成交来源与订单重启恢复实施（2026-10-28，纯规则已开发，来源与恢复待接线）

### QMT 历史日线来源纠错（2026-10-29，开发完成）

接入逐日状态前，先修复已有 `QMTGateway.get_historical_prices` 的来源错误：目标证券缺失时递归取其他证券的 frame，epoch 日期按 UTC 而非交易所本地日期解释，自动补齐缺口，以及已复权结果仍标记为未复权。上述错误直接影响现有行情消费者，作为一个完整修复及时提交，不等待整个 G2C。

两位 Luna max 分别直接修改 `apps/data_center/infrastructure/gateways/qmt_gateway.py` 及对应历史行情单测、`_provider_adapter_specialized.py` 的 QMT 复权传递及实际适配链测试；Root 负责边界复核、原有适用门禁、本文及正式提交。请求关闭 `fill_data`；读取绑定精确证券及请求日期范围；日期解释保留上海时区；显式复权配置经 Gateway 传入 Domain，未知配置拒绝；缺失或不合法的 OHLC 不补零，同日重复记录拒绝。先复现错误，再覆盖真实 SDK 返回形状的替身测试和原 Gateway 兼容测试。已有复权枚举只区分前/后方向，未声称区分等比算法；旧浮点行情不升级为执行原件。范围不包含新表、默认配置、行情下载或交易写入口。

逐日状态的后续来源方向依据 [XtData 官方合同](https://dict.thinktrader.net/nativeApi/xtdata.html)：日线 `suspendFlag` 明确区分正常、停牌和当日起复牌；原停牌事件查询的空响应仍不代表正常。接下来优先复用 `qmt_agent/bridge_worker.py` 的未复权、未补齐采集与 `QmtBridgeBatchModel.payload/digest` 的现有持久批次，补齐 typed 状态、原字段和请求覆盖，再实现对应公开读取；旧批次缺字段保持未知。本修复尚未增加这些状态字段。批次是规范化上传记录，不是原始 HTTP 响应；不得给空响应补造完整覆盖，也不另建通用发布治理平台。

另已定位时钟接缝：现有价格 Publication 的 `observed_at` 是由交易日映射的日线区间结束点，初仓 mark 却以 `source_observed_at` 命名。后续合格输入接线须明确区间时间与供应商观察时间，保持供应商未知值，并保留已保存成员/收据的精确回读；不能悄悄重写历史哈希或以此放宽成交资格。该接缝及逐日状态、持久事件和恢复旅程仍开放。

下一时间语义事项须同时处理公开价格 DTO、显式 mark policy、Proof、reader 和原 codec：只有明确允许日线区间锚点的政策才能按区间结束时间计算 TTL，供应商观察时间保持未知。旧 mark v1 和成交事件 v1 均为严格字段集，且嵌入已保存 receipt 哈希；需保留旧载荷原样解码、重编码和回读，新语义采用窄的独立载荷分支，不改写原 v1、不新增 ORM 表或通用版本平台。成交事件的对应接线与真实日线 producer 同一完整事项处理，不能仅将必填时间改成任意空值后开放执行。

完成条件：来源正反例、原 Gateway 回归、增量类型及债务、格式与架构检查通过，必要投影由原生成器更新后提交 `dev/next-development`。一个事项仅维护 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/qmt-history-integrity/` 下的精简索引和原件；不调用真实 QMT/供应商、不部署、不写生产。回滚仅反向应用本修复，不覆盖其他人的改动。

实施结果：正式 Gateway 关闭缺口补齐，拒绝错证券、无身份及同日重复记录，按上海日期和请求范围取数；OHLC 缺失、布尔、非有限、非正数及次序冲突均不产生有效 bar。配置的复权方向经实际统一适配器进入 Domain。整数成交量在 Gateway 保留精度；适配器如无法将其无损传入旧浮点合同，以 `QMT_VOLUME_NOT_EXACTLY_REPRESENTABLE` 明确拒绝，不舍入、不补零或假装部分成功。旧 Bridge 分支保留。

最终同一输入合批 **124 通过、0 失败、0 跳过**，覆盖 SDK 替身到实际 Gateway/统一适配器及既有 Bridge 兼容；两个生产文件增量 mypy、全库类型债务均为零，Black/isort/Ruff 通过，原 1000 行规模门内为 532/199 非空行。增量架构核对 323 新增行，边界及审计违规均为零；架构清单和模块地图经原生成器处理，统一架构/入口/模块投影检查通过。未改模型、路由、当前数据资格或 Domain 规则，无新增数据库验收。本机精简索引为上述目录 `verification-index.json`，SHA-256 `3a4264f18b8e9865d16e6e005ba9e36e719688040be18d61317c2295b7fcf689`；实际提交与推送记录另存 `delivery.json`，不以私有对象算交付。早期诊断不拼入最终通过证据；一份被子代理覆盖的中间日志仅保留工具输出片段，索引已明确披露该原件缺口。

另先行提交 `891816fb1f36336b2654fbc54948bc9f6b23a7b7` 修复上一批 CI 的随机参数用例编号：仅将收集阶段 9 处 UUID 固定，审计测试双 worker **109 通过**，业务逻辑和运行时随机身份保持。最终 QMT 提交的 CI 仍须按其自身 SHA 核验。逐日状态、时间语义修复和订单恢复继续开放，均不以本事项通过代替。

### 发布权限测试隔离修复（2026-10-29，开发完成）

`891816f` 累计 CI 和 `88a076d` 的 Fast CI 实际出现 `Permission.DoesNotExist`：权限组件的受限 `available_apps` 在清理 auth 表后抑制 `post_migrate`，下一发布旅程严格读取权限定义时失败。原样相邻顺序在本地复现 **1 通过、1 错误**。本事项仅移除该测试的 app 限制，保留原完整迁移、事务清理守卫与业务入口的严格 `Permission.get`；新增权限定义缺失必须拒绝的反例，不添加夹具补权 fallback，也不修改生产授权逻辑。

0107 迁移测试同时验证实际 Django 权限生成：在已应用迁移状态中删除精确权限，通过正式 `create_permissions` 恢复后核对 ContentType、codename 和名称，原空库往返、有历史拒绝逆迁移及数据库约束保持。首轮 **9 通过、1 失败**，原因是只按 data_center 目标构造状态，误将早期 ContentType 的 `name` 列用于当前库；改为实际已应用的完整迁移节点后，同一组最终 **10 通过、0 失败/错误/跳过、1 项 PostgreSQL 专用测试未选入**，pytest 376.62 秒、完整进程 407.30 秒，输入哈希未变。SQLite 当前 PID 独立测试库和 10 次原清理守卫记录均在 JUnit；Black/isort/Ruff 与 diff 检查通过。无生产 Python、模型或入口变化，不重复执行此前 QMT 或 PostgreSQL 整批验收。

完整失败及最终原件仅本机保留在 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/ci-permission-isolation/`，同一 `verification-index.json` 绑定 18 份原件和实际输入，SHA-256 `629dbc293a9dab94cd344cf7a399ef1e4ff54e1a406c4aaeac6210da3583b1e0`。两测试文件与本说明独立提交，实际 SHA/tree/推送记入同目录 `delivery.json`；修复 SHA 的累计双 Python CI 另行核验，不用旧窄选集绿灯代替。本事项不部署、不写生产，不关闭 G2C 或总 Goal。

### 发布权限夹具跨模块清理兼容（2026-10-29，开发完成）

`eb97db60d` 的自然 push Fast CI 在 Python 3.11 job `123241764028` 取得 4945 通过、175 跳过、1 个 setup 错误；Python 3.13 同组通过，Consistency workflow 被取消，不能记为全部 CI 通过。原失败日志显示 gw0 在 12 个 Calendar PostgreSQL 专用用例跳过后，Price Limit 管理夹具的精确 `Permission.get` 找不到定义。该前驱的受限 auth/contenttypes/sessions 夹具仍执行整表清理并抑制 Data Center 的 `post_migrate`；这与上一项已修复的 Price Limit 权限组件是不同前驱。

Root 使用原 SQLite 设置、完整迁移和清理守卫，在同一进程按“最后一个 Calendar 专用节点 → 原失败管理节点”顺序再次取得 **1 跳过、1 setup 错误**，pytest 324.63 秒；没有通过重跑绿灯掩盖失败。最小修复仅在管理测试夹具调用 Django 原 `create_permissions`，从真实 Data Center `Meta.permissions` 重建被前驱清理的测试定义，随后继续严格 `Permission.get`。没有手造 codename、生产自动补权或放宽撤权校验；补充声明缺失仍失败及清理后恢复但撤权继续拒绝的回归，原 0107 历史迁移与权限生成测试保持。

最终验证范围为同一污染前驱、完整 Price Limit 管理测试（排除一个 PostgreSQL 双连接专用节点）和原 0107 迁移正反例，串行、900 秒预算。结果 **14 通过、0 失败/错误、1 个预期前驱跳过、1 个 PostgreSQL 专用节点未选入**，pytest 305.18 秒；JUnit 记录真实 SQLite 库 `test_db_23280.sqlite3` 及 14 次权限时钟清理观测。测试字节与运行输入核对一致，Black/isort/Ruff 通过。本机原件及精简索引在 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/price-limit-permission-isolation/verification-index.json`，SHA-256 `36075d3f98fa440fc176386e26603654035661ebf93d530aaadfc974b814bc19`；保留原 CI 日志和有序 RED。本项修复明确的夹具前提，不改通用隔离 helper 或重新执行 QMT 51/PG 2 整批。生产代码没有变化，正式提交及推送身份记在同目录 `delivery.json`，新 SHA 的 CI 单独观察。

### QMT 日线停复牌来源留存与读取（2026-10-29，开发完成）

前置日线估值时间修复已正式推送 `e91d6bdb6afa0f7bab7e3cbc8a1cbeb8b2207183`。本事项补原 QMT worker 因 OHLC 不完整丢失停牌行的真实来源缺口：[native XtData 官方 K 线契约](https://dict.thinktrader.net/nativeApi/xtdata.html) 定义 `suspendFlag` 为 0 正常、1 停牌、-1 当日起复牌。只读取实际返回的日线行，缺值保留 unknown；不能借 tick `stockStatus`、本地时钟或缺行推造当日可交易状态。

Root 负责原批次 API/Application/Repository 接线、新严格持久载荷 decoder、owner/binding/asset/date/cutoff 读取、对应集成测试、原合同和必要投影；Luna max 分别负责新 `domain/qmt_daily_status.py` 及单测，以及原 `qmt_agent/bridge_worker.py` 和 market bridge 单测，路径不重叠。正式源码直接整合，Root 独占共享 Git、投影及数据库验证窗口。继续复用现有配对、HMAC/nonce、资产白名单、JSON 批次及本地 outbox，无新模型、迁移或默认执行开关。

新 `daily_status` typed batch 与旧 quote/bar 分开，旧 DTO/asdict 摘要原样。状态批次带明确 schema、自报请求起止日期、本地采集完成时刻及实际样本；日期范围只能约束记录，不能证明 SDK 请求或完整覆盖。一次 native 读取分别生成价格和状态，停牌无 OHLC 仍可形成状态批次。旧服务器拒新 kind 时 outbox 保留原 UUID/载荷重试，不允许忽略字段后成功确认。服务端拒混合字段、坏类型、重复/越界日、错误时钟及越权；原 receipt 保证相同批次精确重放、异内容冲突。读取验证载荷/摘要/身份/记录时序并重查当前归属与启用状态；最新 unknown 不回退旧正常，已知互相冲突时保留阻断，不能用新正常值静默清除旧停牌。结果仍是未发布的规范化来源证据，供应商时间未知，不冒称 SDK 原响应、原始 HTTP 或交易许可。

完成标准：原 SDK 替身→durable outbox→签名 HTTP→真实 JSON 批次→公开读取实现链通过，覆盖无价格停牌、三种标记/unknown、丢失确认/重启、旧协议与旧摘要、权限/防重放、损坏/冲突及知识截止；相应 NoDB/数据库测试、类型债务、格式、架构、freshness 和原生成投影门禁通过后按一个完整事项提交。原件仅本机 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/qmt-daily-status/` 单一索引保存。本事项不替代后续来源发布资格、durable matcher producer 和订单恢复，不部署、不写生产。回退须保留已有 status 载荷识别，未确认的 agent outbox 不得删除；不通过回退删除已留存证据。

最终开发验证：123 项 NoDB 通过，新增 Domain 分支模式综合覆盖 97.5%；修正后的原两个 API 集成模块在独立 SQLite 库中 51 项全部通过，含真实本地 HTTP、实际 outbox、丢失确认后重启重放及旧 quote 载荷/摘要黄金值。原生 SDK 边界使用替身，不代表真实 QMT 来源验收。独立 PostgreSQL 完整迁移后两项并发测试通过且无跳过：`pg_blocking_pids` 实证写入持有 owner 锁时停用等待，已提交停用则拒绝 daily_status/quote/bar 且无行情或批次写入。实际测试库身份由原 helper 的 SQL 断言及运行观察支持，JUnit 仅记录测试结果；测试结束仅清理本轮两个库，其他库集合保持。

9 个生产文件增量 mypy 与默认全库债务均为 0；16 个 Python 文件 Black/isort/Ruff、3,787 文件架构扫描及 audit、98 项 freshness 合同、测试分层与原统一投影核验通过。投影只增加本批 Application/层计数、状态合同及 PG 测试入口，仍为 44 模块/210 依赖边，无新模型、迁移、发布开关或治理框架。Root 负责正式整合和提交，Luna max 分工完成 Domain、worker、codec、PG 测试并独立复核权限/时钟/幂等边界。

保留真实失败：原 API 尚不接受新 kind 的 RED；Domain、codec、worker 和读取反例；4 项增量类型错误；SQLite 首轮 40 passed / 3 failed / 8 errors，后者由跨用例限流缓存累积引起。只在原测试夹具中使用逐用例独立 LocMemCache，保留真实生产限流、验签、nonce 与权限。修后 SQLite 为 51 passed / 307.85 秒，PG 为 2 passed / 260.78 秒；生产文件及 NoDB 已执行输入未变，新增 PG 与修后集成测试分别绑定自己的最终输入，不将早期结果冒称同一候选。来源正式发布、durable matcher producer、订单发现/恢复及原单元退出条件继续开放。

本机唯一验收索引：`artifacts/a-share-usability/ash03-order-recovery-2026-10-29/qmt-daily-status/verification-index.json`，SHA-256 `c431419cee13e432244b3fc82a1de446793f1b9db4d11d2005b4b376ff1bfcdb`；输入基线 `e91d6bdb6afa0f7bab7e3cbc8a1cbeb8b2207183`，索引逐项保留正式源码摘要、命令、结果与失败原件哈希。原件未上传；正式提交 SHA/tree、实际提交规模门及远端结果追加同目录 `delivery.json`，不另开状态提交。

### 日线估值时间语义修复（2026-10-29，开发完成）

本批修复上文已定位的日线区间结束点被写为供应商观察时间的问题。Root 修改原 `apps/data_center/application/published_price_source.py` 及来源单测，公开 `observation_basis`、`interval_end_at`、未知的 `source_observed_at` 和原响应完成 `local_known_at`；既有成员和公开兼容字段保持原值。两个 Luna max 分别负责 `apps/simulated_trading/domain/initial_position_mark.py` 与 `infrastructure/order_reservation_fill_initial_position_mark_codec.py` 的 Proof/编码，以及 `domain/initial_position_mark_policy.py` 与 `infrastructure/published_price_initial_position_mark_reader.py` 的显式政策/读取器；各自同步现有单测，Root 补现有仓储组件的保存和重放回归、当前数据合同与必要生成投影。业务代码直接落正式源码；本批共五个生产路径，无新增模型或迁移。

沿用同一 Proof 类型，旧 `simulated-initial-position-mark.v1` 字段集、规范 JSON、hash 及已有 receipt 精确回读保持；新嵌套分支 `simulated-initial-position-mark.daily-interval.v1` 显式绑定日线 basis、区间结束和本地 known-at，供应商观察未知仍为空。对应 `simulated-initial-position-mark-policy.daily-interval.v1` 必须显式选择 `daily_interval_end` 并绑定版本/内容及当前配置证据；旧 policy 不自动获得新用途。TTL 只从区间结束计算，本地读取、发布或响应时间不得刷新它；缺少判别、混合字段、未知 basis 和错误时序拒绝。旧 policy 和 mark 仅为历史兼容保留其编码，不替旧证据补造源时间。原 writer 默认绑定、fill event v1 及持久 producer 接线不在本批启用。

先留失败反例，再覆盖公开来源→显式政策→reader→Proof→嵌套 receipt 的实际实现链，固定旧 JSON/摘要金样及新增载荷篡改、TTL/知识截止点反例。NoDB 轻测按不重叠文件并行；完整迁移的隔离 SQLite 仓储定向验收由 Root 单独运行，保留原清理守卫，不重复此前 PostgreSQL 大包。完成适用增量 mypy/债务、格式、当前数据合同、架构及原统一投影检查后按完整事项提交。本机原件复用 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/daily-mark-time-basis/` 下单一精简索引，失败不覆盖。无真实供应商调用、部署或生产写入；回滚须保留新载荷识别与历史回读，不允许使已保存的新证据变成不可读。

最终生产/测试字节已通过 **204 项单测**（pytest 6.99 秒，进程 33.20 秒）及 **15 项 SQLite 仓储测试**（0 失败/错误/跳过，37 项无关用例未选入；JUnit 363.958 秒，进程 385.40 秒）。两个 Domain 文件分支模式综合覆盖分别为 95.85% / 98.93%，纯分支分别为 50/52、51/52。五个生产文件增量 mypy、全库零类型债务、Black/isort/Ruff、当前数据合同和架构/audit 检查通过，未提高基线。初轮三项类型错误及随之主动中止的旧 DB 候选保留，后者无 JUnit、不能记为通过；修正类型后已完整重跑上述最终测试。统一投影初轮仅入口清单过期，原生成器产生本事项一条 current-data surface 的 id/locator 更新；module-map 与架构清单重建后无差异。随后只修正合同 notes 中残留的旧 TTL 文字，生产及测试字节保持不变，治理合同与投影另行复核。

本轮原 SQLite 设置、完整迁移和清理守卫未改。原运行期间工具观察到 pytest PID 31660 与对应 `test_db_31660.sqlite3`；该身份未写入 JUnit，不能称为 XML 所证。JUnit 的 `sqlite_authority_generation_flushes=[]`：本组件原有受限 available_apps 不包含 account，未执行涉及该时钟的清理，不宣称验证了全账户权限清理。来源链测试执行真实原件核验、reader 和 codec，但来源仓储/分类/日历边界仍用替身；DB 保存/重放使用显式 mark fixture。它们不等于真实供应商、真实账户旅程或整单元验收。

修复后的原统一投影检查已通过（architecture、entrypoints、module map），当前数据合同仍为 98 项。正式基线为 `daf43f3a765b46af101825a60b97cc01eee05de8`；同一目录 `verification-index.json` 绑定 18 项最终输入及 56 份本机原件，SHA-256 `88062b10886663def53b15f582facb1de109a7b8e2edcc4d8bf28b91dc033be5`。代码、六个对应测试文件、合同、唯一有差异的入口投影及专项说明共 15 个路径合批提交；实际 SHA/tree、推送和提交后规模门记录在同目录 `delivery.json`，新 SHA 的 CI 单独观察。此事项开发完成，不关闭 G2C、ASH-03 或总 Goal；持久 producer、逐日交易状态资格和订单发现/恢复仍待后续交付。

### 当前整合事项：独立初仓估值读取（2026-10-28～29，开发完成）

在正式提交 `342b47964e2f61ae4ce61533dfd00b6555b049f5` 的精确价格来源上补齐已有 `InitialPositionMarkReader`，不新增表或迁移。Root 整合公开价格 DTO 的真实 `publication_as_of`、Config Center 可选策略定义、显式 composition 和生成投影；Luna max 开发 `domain/initial_position_mark_policy.py`、`infrastructure/published_price_initial_position_mark_reader.py` 与对应单测。正式目标均位于 `apps/simulated_trading/`，不以临时副本作为交付。

- 新用途政策通过 `config_center.market.simulated_initial_position_mark_policy` 显式配置，保存用途、版本、来源、publication key、资产范围和观测起算的 TTL；读取验证 active profile/snapshot 的版本、hash、生效可见性及前后稳定性。无种子值、无默认激活，不继承 M1 参考价资格。
- 五项证券身份取现有 current-reference classification，交易日取正式已发布 execution calendar，价格取原始响应逐行验证后的未复权 Decimal close。缺失、漂移、日历覆盖不足、未知或过期来源均阻断，不能复制请求字段冒充身份，也不能用成交价或限价代替估值。
- 原版保留供应商可用时间未知为 `None`，公开 `publication_as_of` 保持真实发布值；但把日线区间结束点写进了名为 `source_observed_at` 的字段，并据此计算 TTL。上文日线时间修复明确这一差异，原验收不能证明取得了真实供应商观察时钟。
- 验收覆盖有效读取、五字段错配、用途/来源/key 错配、政策失效或读取中变化、未完成交易日/假日/覆盖不足、源时钟与 TTL 边界及精确价格。运行对应来源/身份/日历/mark 回归和适用类型、架构、当前数据合同、模块投影门禁。失败原件保留在本机忽略目录的同一事项索引。

本事项完成标准是正式可调用的显式 reader 及其验证，不是默认启用。原 writer 的默认 reader 仍为空；逐日交易状态/涨跌停来源、持久 producer、订单发现和恢复入口仍按原 G2C 依赖推进，未部署、未写生产。回滚时仅反向应用本事项提交，保留已进入开发分支的其他修改。

本阶段关闭的目标仍是原第 2/3 组的订单级缺口：预留后中断、源成交已生成但未记账、记账成功但响应丢失，均可按原订单和事件恢复，且不重复预留、成交或释放。自动 invocation 的 `started` 防重不替代订单恢复；不新增其账户 checkpoint 作为前置。M1、费用恢复 SDK/TUI 已完成的开发验收也不重新成为本阶段前置。

### 现有落点和缺口

- `application/order_reservation_fill.py` 已有精确事件应用/重放、typed source binding 和未知结果回读；`read_event` 要求已知事件编号，缺少按订单发现。
- `infrastructure/order_reservation_fill_repository.py` 已有账户父锁、锁内精确重读、fill/receipt/hold 原子更新，事件 reader 和首仓 mark reader 默认未绑定。
- `execution_settlement_composition.py` 只有 reserve/cancel 等组装，没有 fill 组装。正式代码中没有 durable matcher reader 实现。
- `SimulatedOrderFillReceiptModel` 的非空 Trade 外键使其只能证明成交后的记账事实；券商 `BrokerFillModel` 绑定 LiveOrder，也不能充当本地模拟订单的成交前事件。既有行情原件能证明输入，不能单独证明已做出撮合决定。

### 生成事件的业务规则

拟采用一个明确、保守的日线收盘模拟撮合用途，入口必须由当前 owner 显式调用；默认不启用，不接 Beat，不改变已有普通模拟或实盘入口。输入为原持久订单、明确交易日与操作键、该证券该日的正式未复权价格/成交量及交易状态、有效的显式撮合配置。撮合参数走既有 config_center 管理入口，缺少配置即阻断，不在业务代码写默认参与率。最终准入必须逐项核实已有公开来源能否提供这些字段；M1 只读参考价资格不能转用为成交资格。

纯 Domain 规则计算是否交叉限价及可撮合量：订单必须在被使用的市场观察之前已接受；仅使用指定交易日和截止时间前可见的真实观察，不跨日找价。价格为源收盘价，BUY 不高于原限价、SELL 不低于原限价。停牌、交易状态未知、涨跌停边界、未知或零成交量、未知量纲、缺少原观察/可用时间均不得形成成交。数量受原未成交量、明确份额单位和配置参与率约束；同账户同证券同交易日的已保存模拟事件共同消耗该观察的容量，不能用换操作键、不同订单或新发布版本重复使用整日成交量。该模型明确不模拟队列优先权，不声称真实可成交性；日线模拟假设与实际券商成交始终分开。

纯规则已按下述反例实现；真实接线仍须核对来源合同。若正式来源缺必需字段，保留阻断并补齐其原公开合同，不用当前价、收据或测试替身填补资格。初仓估值独立读取既有 `InitialPositionMarkProof` 所需的正式发布与时效证据，不把成交价直接作为估值证明；不能获得时，新事件不能进入首笔 BUY 记账。

已核实的公共字段映射如下；这些缺口是实际接线工作，不作为“永远拒绝所有撮合”即可完成的替代目标。

| 所需事实 | 现有公开入口/承载 | 当前事实与最小补齐范围 |
| --- | --- | --- |
| 指定证券/交易日 OHLCV 与未复权、量纲 | `public_published_queries.get_published_price_bar_series` → 原 `query_services`/price-bar repository；`PriceBarModel` | 能按日期和 Publication member 读取 OHLCV；模型有 adjustment、volume（声明 shares）、source_record_id/raw_payload_hash/run/revision，现公开行未完整发布。补原事实行投影和逐来源规范化证明，精确数值不得经 float 损失精度；不能由 help_text 推断所有历史行合格。 |
| 目标行 observed/available/known-at、Publication/Raw 身份 | 原 Publication member 与 bar/fetch/RawAudit 关联 | 外层 freshness 的 observed_at 是成员集合统计，不能替代目标行。补精确 member/fact/raw 绑定及真实已知时间；合同明确本地完整响应 basis 且原件匹配时，可使用响应完成时刻作为保守已知时间。缺少该证据保持未知，不以普通 fetched_at 或当前请求时间冒充。 |
| 逐日停牌及涨跌停状态 | 已有 `TushareModelMarketSource.suspended_days` 仅为历史缺口解释；risk_center `ExecutionMarketEvidenceProvider` 仍为 Protocol | 静态 instrument listing 信息不提供逐日状态；suspend_d 返回空/缺列也不能推断“正常交易”。需要保留覆盖、原件及时钟的逐日状态公开读取，并补实际上下限来源。bounded/unbounded/unknown 必须区分，不猜固定涨跌幅比例。 |
| 正式会话和结算日 | `OrderFillSettlementCalendarResolver` 与原 `PublishedExecutionCalendarReader` | 复用正式日历证据和封存 exchange/lag；撮合仍需核对该证券目标会话的真实观察时间，不仅比较 date。 |
| 初仓估值 | `InitialPositionMarkReader`/`InitialPositionMarkProof` | 已有显式发布来源 reader、配置政策及稳定性绑定，writer 默认仍未配置。日线区间与供应商时间的修复按本批验收；原 `PublishedClosePriceReader` 仍仅用于 M1，不能直接移作执行或首仓估值资格。 |

实现顺序先补可验证的原公开来源字段与逐日状态/mark 适配，再接 producer。纯撮合计算可独立开发和测试，但其通过只证明已声明输入下的数学与限制，不证明真实来源、持久恢复或任何执行入口已完成。

### 精确涨跌停价格捕获与原件回放（2026-10-29，已完成开发验收）

最近可提交事项是把实际 Tushare adapter 的单证券、单交易日 `stk_limit` 请求接到 Application 捕获/留存用例，复用原 `ProviderResponseCapture`、`RetainProviderResponsePayloadUseCase`、RawPayload 仓储和公开 reference 校验完成回读。Luna max 负责独立 `application/price_limit_response_capture.py`、`infrastructure/tushare_exact_price_limit_capture.py` 及对应单测；Root 负责原 adapter 公开方法、`application/price_limit_capture.py`、显式 composition、真实传输替身到留存回读的集成测试、原生成投影和正式提交。业务源码直接进入正式路径，不以临时副本作为交付。

捕获只接受原始字节证明的有限正数上下界，Decimal 精度不经 float 回填；空、缺失、重复 JSON/字段、多个目标行、错证券/日期、截断及反序均拒绝，不推断“不设涨跌幅限制”。回放核对精确请求、原件保留标记、编码、body 摘要及 reference 对 RawPayload 的完整绑定。单位仅为供应商原生价格，币种、市场观察时刻和供应商发布时间保持未知；本地完整响应时刻单列为 known-at。官方 [stk_limit 文档](https://tushare.pro/document/2?doc_id=183) 的约 9 点更新安排不作为逐行时钟。显式 provider 捕获不静默切换成其他来源。

完成标准为真实 adapter→Application 捕获/留存→RawPayload 读取/回放正反例通过，关联原件与传输回归、增量 mypy、全库债务、格式、模块和 Data Center 投影/架构门禁通过后及时提交。运行限隔离 fixture/本地测试库，不访问真实供应商或写生产；如涉及数据库，保留原迁移与清理守卫。仅用原事项维护一份精简证据索引。本事项不新增模型、Publication、默认调度或执行权限；RawPayload 不能代替可发现的正式业务事实。逐日状态、发布资格及原 producer/恢复闭环继续按上表推进。回滚仅反向应用本事项提交，保留既有 RawPayload 和其他人的修改。

### 日线成交事件时间语义与现有记账兼容（2026-10-29，开发完成）

下一完整小事项修复已存在的消费合同：`LocalSimulatedFillEventV1` 原来要求两个供应商时钟非空，不能诚实承载已验证日线区间数据。Root 整合并修复真实 writer 的 `infrastructure/order_reservation_fill_ledger_storage.py` 同一非空假设；Luna max 修改 `application/order_reservation_fill.py`、`infrastructure/order_reservation_fill_snapshot_codec.py` 及两份原单测，另一 Luna max 在原仓储夹具上补 `tests/component/simulated_trading/test_order_reservation_fill_daily_interval.py`。原 snapshot codec 扩展后从 974 增到 1127 个非空行，实际触及规模门禁，因此按事件编解码职责抽出 `infrastructure/order_reservation_fill_event_codec.py`，不提高阈值。全部源码直接进入正式路径，不新增模型、迁移或临时交付副本。

- 旧 `local-simulated-fill-event.v1` 的字段、规范字节和 receipt 哈希保持；默认构造继续表示原供应商时钟合同。新窄分支为 `local-simulated-fill-event.daily-interval.v1`，只接受来源版本 `local-daily-interval.v1` 与显式 `daily_interval_end` basis，禁止两种语义混用。
- 日线分支保留供应商观察及可用时间为 `None`，显式保存 `interval_end_at` 和 `local_known_at`。`occurred_at` 仅表示日线模拟的生效时刻，必须等于区间结束点；区间结束、本地已知、事件记录和读取截止依次非递减且均有时区，不能伪装真实市场成交时间。后续 producer 的已知时间须覆盖全部输入在服务端实际可见的时点，不能相信 Agent 自报采集时间。
- 验证原 Application 正反例、严格 codec/旧哈希、真实仓储写入与 receipt 回读、原键重放及错误时钟无副作用，运行适用格式、增量 mypy、债务、架构与投影门禁。复用原 pytest/隔离数据库机制，原件合并保存在 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/durable-matcher/`，以实际输入和运行记录区分后续 producer 验收。

本项完成即提交开发分支，不等待持久 producer、整单元或生产发布资格。测试中的显式 reader 仍是替身，只验证现有消费者可保存并重放该语义，不能宣称实际来源已合格或可发现的源事件已生成。后续完整事项仍须一起交付模拟用途资格、持久决定、账户/交易日容量、pending/cancel 历史保护及发现恢复；不提交孤立的新表，也不以永远阻断的适配器代替正向闭环。当前参考来源限制继续保留：状态批次不是原始 SDK 响应，限价的币种未知也不能由用途政策猜定。回滚仅撤回本项代码；如将来已保存新分支事件，须保留能识别该分支的 reader 或关闭受影响写入口，不删除历史。

最终验收：8 个原无数据库模块 **356 通过**（9.31 秒）；7 个新组件节点与原 fill repository、row reader 合批 **86 通过、0 失败/错误/跳过**（387.88 秒），覆盖新日线写入/回执解码/精确重放、直接仓储拒绝未来时钟、旧部分成交/取消及失败回滚。首次组件运行漏导入 `ledger`，出现 7 个 setup error，修复后先以 `--setup-plan` 核对传递夹具再执行最终合批；该失败不是业务 RED。单测早期 RED、格式错误和原件均保留。实际运行用原 SQLite 设置、完整迁移及清理机制，观察到 pytest PID 25000 与对应独立库；JUnit 没有库名属性，权限时钟 flush 观测为 `[]`，不扩写成全账户权限清理或 PostgreSQL 并发验收。

4 个生产文件增量 mypy、全库零类型债务、7 个 Python 文件格式、3788 文件架构/audit、98 当前数据合同、测试分层与原 module-map 生成校验通过。Domain 无修改；新 Application 校验由 codec 和锁内 writer 复用，旧 receipt 回放仍先于当前来源和时钟。拆分后原 snapshot codec 为 781、新 event codec 为 352 个非空行，规模门禁阈值未变。最终业务和测试输入核对未漂移；一份本机索引 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/durable-matcher/verification-index.json` 绑定实际输入、命令与 31 份原件，SHA-256 `7481ac0cfac0304a516e86d998f75f89155ae340147c03206346b18d3fa1203c`。基线为 `f75837cc9c360014c2b779705b8aba70695c7efa`，正式 SHA/tree/远端及提交后精确差异门记在同目录 `delivery.json`；不关闭 G2C、ASH-03 或总 Goal，本次不部署、不写生产。

### 证券交易币种来源捕获与精确读回（2026-10-29，开发完成）

本次完整小事项沿既有证券名录捕获链加入可选 `curr_type`，不根据证券后缀、成交额单位或 AssetMaster 默认值推断价格币种。官方 [stock_basic 输出定义](https://tushare.pro/document/2?doc_id=25) 将该字段列为非默认返回的交易货币；它没有保证每行均为人民币。默认请求保持原七字段及 v1 合同；显式选择采集币种时使用八字段和 v2 合同，同一捕获编号改变选择必须按原请求身份冲突阻断。未请求、供应商 null、空串及未知文本不补成 CNY，字符串原样保存。

Root 负责原公开 composition、原捕获/快照仓储往返验证、适用门禁和正式提交；Luna max 分别负责 Domain 合同及严格快照编解码、Infrastructure 原件解析和绑定、现有 TUI 捕获选项及回读。直接修改正式源码，保留旧七字段快照的规范字节与固定哈希；新合同必须有币种键，币种差异纳入来源一致性和内容哈希。复用原 RawPayload/RawAudit/快照/claim，不增加表、迁移、来源审批或默认调度。

验收覆盖原件字段与值类型、未知币种保留、跨轮币种冲突、旧哈希、同编号改变合同的恢复拒绝，以及实际原件留存→快照封存→公开读取；TUI 保留管理权限，验证显式选项与用户回读。复用既有 NoDB、隔离数据库和 API/metadata 契约测试，格式、类型债务、架构、规模及必要生成投影合批校验；失败与实际输入身份用本机原 `durable-matcher/` 目录的 `currency-*` 原件区分，不覆盖前一批索引。

本项仅补齐可验证的证券币种来源，不关闭 G2C 或授予撮合、通用决策、真实执行资格。后续专属历史日线模拟资格必须联合精确价格、正式限价、用户所属 QMT 状态的服务端记录时间、日历和显式配置；原来源禁止决策/执行标记保持。完成本项适用开发门禁即提交，不等待整个 producer。回滚需保留可读已存八字段快照的 reader，不能删除旧来源历史；未部署、不写生产。

最终输入已完成 9 个原 NoDB 模块 **220 通过**（7.71 秒）；原仓储、API 和新捕获组件合批 **44 通过、0 失败/错误/跳过**（332.22 秒），其中 12 个新组件节点含 1 个本地浏览器检查，另有原仓储 17 项和 API 15 项。真实 public capture 使用传输及配置替身，沿原 claim、RawPayload、RawAudit、快照封存和公开读回运行；重放不再请求传输，同捕获编号改变币种选择拒绝，事后改写币种不能用原件通过校验。浏览器复用原 `live_server` 和 Playwright 工具，真实登录、加载既有表单及读取已保存来源，核对默认未勾选、可勾选和可见的来源币种列；未在浏览器提交供应商捕获，不能写成生产或账户 613 验收。来源表格以币种列替换重复的原件编号列，API 与原件视图仍保留原件编号。

SQLite 使用完整原迁移、每进程独立库和原清理守卫；实际观察到 pytest PID 26728 及 `test_db_26728.sqlite3`。JUnit 的权限时钟清理观测为 `[[0,0]]`，没有库名属性；浏览器原件路径使用 `record_property` 带来 1 项 xunit2 兼容告警，不能把该属性当成严格 xunit2 schema 验收。未改变模型或锁序，本事项没有重跑 PostgreSQL 并发门。最终 Domain 100 项为 220 项的子集，行/分支合并覆盖 **99.2%**；多轮币种冲突统一返回 `None`，两种轮次顺序及 null/已知冲突均有反例，相同币种但其他字段冲突仍保留原共同币种与阻断原因。

7 个生产文件增量 mypy 和全库类型债务均为 0；14 个 Python 文件 Black/isort/Ruff、3788 文件架构及审计、98 当前数据合同、测试分层、Data Center 架构清单和原模块映射校验通过，模块映射无实质变化。原 TUI 构建器仅更新 runtime manifest 的本次 metadata 摘要、构建身份及祖先提交，未手改生成投影。原件继续保存在本机 `durable-matcher/currency-*`，不提交日志、截图或重复源码包。

本批基线为 `c92310fa194a084f9cf3275fd74eea8811663a2d`。精简索引 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/durable-matcher/currency-verification-index.json` 的 SHA-256 为 `716424b1793e12a6b741dcb596e4583470c0a23672fcd21654bca4f1902f2387`，绑定 15 个最终代码/测试/投影输入、实际运行命令及 38 份本机原件；原 Domain 缺字段 RED、parser 7 失败和公共入口 8 失败均保留。无输出即停止的早期 TUI 尝试不计成功或业务 RED。测试输入哈希与最终源一致；运行中补记的 PID/库名是观察附记，不冒充启动前证明或 XML 属性。正式 commit/tree、远端核对与 15 个外来路径/暂存状态保护结果记在同目录 `currency-delivery.json`。开发完成不等于来源资格、持久撮合、整 ASH-03 或总 Goal 完成。

### 历史日线模拟的资格与持久事件正向闭环（2026-10-29，开发验收完成）

本批完成后文第 1 批完整后端事项，基线 `3dea9b1543b08a1ca2bc02388362d691ff1a2ce4`：真实来源组合通过后产生不可变 matched/no-match 决定，显式 reader 能发现并重读 matched 事件，再交原 Fill writer 消费；源决定和账本分事务，未消费或损坏事件阻断重复撮合与撤单。本项不单独提交政策、新表或永远阻断的适配器。Root 整合 Application 命令/资格组装、composition 与完整测试；Luna max 分别负责用途政策和 Config Center 读取、正式限价 consumer 只读口、窄决定存储与历史保护。源码直接进入正式目录，不新建平台或第二份状态真源。

用途唯一为 `historical_daily_simulation`。配置显式给出价格发布键、同一 Tushare 配置身份、证券快照编号、CNY/未复权/股数单位、参与率、步长及可接收的 QMT 正常或复牌状态；缺值不启用。来源资格绑定原锁定订单、相同证券/交易日、正式日历、精确日线发布及 raw、证券币种、QMT owner binding 和正式限价引用。币种快照须在目标交易日收到原件且上市日期覆盖该日，跨轮歧义、退市或未知币种拒绝；不能以当前名录解释任意历史日期。限价的 provider-native price 与同一人民币证券对应是显式模拟解释假设，原限价 `currency=None` 与禁止决策/执行标记不变。QMT 只承认 authenticated normalized assertion 的性质，用服务端 recorded_at（含全部参与证据）限制已知时间，不把 Agent 自报时间当服务端可见时间。

配置身份核对限定在原件确实提供该身份的价格与限价：价格公开证据增加从已验证请求恢复的 `provider_configuration_id`，不推断缺失编号；配置显示名称可以是 `Tushare Pro`，与固定来源类型 `tushare` 分开验证。证券快照原合同只公布来源类型，币种资格核对其 `stock_basic` 合同、同日原件和证券身份，不补造配置编号。跨订单按账户/证券/交易日累计所有已接受数量，不按发布、批次或配置分桶；同订单的稳定观察唯一约束防止换发布或操作键重复撮合。

真实组合验证发现原限价 Audit 将 `provider_name` 当机器 token，导致带内部空格的现有配置名在确认发布时被拒。改为该字段专用显示名称校验，原样保留内容，不做大小写、空格或哈希归一化；空值、首尾空白、Unicode 控制字符和超长名称继续拒绝，其余 token 及 scope/seal/raw/hash 校验不变。

正向样例为：订单在 T 日收盘前接受，T 日币种原件、T 日已发布未复权价格与限价可核对，所属用户 QMT 的 T 日正常状态在 T+1 服务端留存，调用截止点覆盖所有这些已知/发布时点。产生有界数量的日线模拟事件，并显式标明日线收盘生效、非交易所真实成交。错用户/配置/证券/日期、未来知识、币种缺失或冲突、停牌/未知状态、发布回滚链或原件损坏均不保存“已接受决定”，也不改账或释放 hold。

限价现有管理读口与 Audit 验证均要求 publisher principal。新增内部 exact-scope/cutoff consumer query 只读全球市场参考，沿 Data Center Application → Infrastructure → Core bridge → Audit Application 验证同一 event/outbox；不创建管理员身份、不开放任意审计浏览，不给旧管理写口绕行参数。读取仍须在同数据库一致事务内复用原目录、来源、封印、事件及回滚历史校验。所需改动限相关原支持函数及窄新查询，不扩展新的发布状态或数据表。

日历增加窄只读组合口：在独立读取时使用原事务，在 producer 已持有的唯一外层事务中复用原正式发布与 Audit 校验；拒绝嵌套事务和其他数据库别名。原独占事务入口不放宽，原调用方默认行为保持。

新 MATCHED 决定在实际写入时点复用原 Fill 的封存计划及身份有效期检查；凭据在该时刻已过期则不保存事件，订单仍可按原规则取消。已保存操作与已有 receipt 的精确重放不重新套用当前资格。有效时产生、但延迟至凭据到期后才 Apply 的 pending 事件仍受原入账门禁阻断，也不能直接释放 hold；这类超期恢复处置属于第二批尚未完成范围，不能通过篡改封存订单、放宽身份时窗或强制撤单处理。

最终验收覆盖旧 receipt 优先重放、同操作键遇到新政策仍返回原决定、换键重复观察拒绝、跨订单共享账户/证券/交易日容量、跨交易日仍只有一个未消费 matched 事件、事件先提交而记账失败后原键恢复，以及 pending/cancel/reset/delete 保护。限价 reference 读口遇损坏、不可用或输入无效的 Audit 证据，转换为窄数据读取异常并保留原 code/cause；原管理入口仍保留自身异常合同，缺失 event/outbox 不会自动修补。0041 空表真实回退/前进通过，遇任何已保存决定则拒绝反向迁移。

本地最终 NoDB 合批 **398 通过**；最终 PostgreSQL r15 四模块 **32 通过、0 失败/错误/跳过**（JUnit 713.019 秒，进程 750.691 秒，低于 900 秒预算），含正式来源组合、原限价管理权限/回滚及锁竞争/迁移。r14 的 32 通过单独保留为补跨日断言前一轮，不替代 r15。SQLite 四模块 **137 通过、0 失败/错误/跳过**（508.02 秒），使用完整迁移和实际 pytest PID 29704 对应的独立临时库。PG/SQLite 运行输入均零漂移；PG 使用两个 worker backend 加一个主线程持锁连接，单 pytest worker。真实来源测试用本地传输/配置及身份替身沿原留存、发布、签名绑定和公开读口运行，不代表真实供应商、QMT、生产或账户 613 验收。

25 个生产文件增量 mypy 和全库类型债务均为 0；40 个 Python 文件 Black/isort/Ruff、架构边界及审计、原模块地图、数据字典、Data Center 清单、99 项当前数据合同和测试分层通过。迁移图无未应用叶节点，makemigrations 检查无变化。两个改动 Domain 的 190 项测试均通过，Audit 与模拟用途政策的行/分支合并覆盖分别为 **94.9% / 95.9%**；首次覆盖率导出遗漏并行数据合并而没有报告，使用原 coverage combine --keep 合并已保留原件后通过，没有重跑业务验收。最后清单生成器仅刷新引用行号，未更改运行源码或测试。

失败原件全部保留：r5 促成生成时有效期保护；r7/8 促成 provider 显示名窄校验；r10 修复新 reference 异常边界和测试依赖表清理顺序；r12 修正第二等待者可能被第一等待者阻塞的断言。r12 继续使用原 helper 的真实 pg_blocking_pids、目标账户 relation OID、RowShareLock/granted、Lock wait 和查询检查，未退化为只匹配 SQL。其余夹具、截止时间及导入失败也保留在逐轮输入/结果中。

精简本机索引 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/durable-matcher/g2c-verification-index.json` 的 SHA-256 为 `5852577fa75683d7ce03d0001b3e19231926cad60b4b1cdd29680503920c2ad2`，绑定最终 46 个代码/测试/投影/合同输入、实际命令和逐轮原件；本节因避免自引用不放入该哈希集合。完整日志、JUnit 和覆盖率数据不提交 Git，不能宣称远端持有。正式提交/远端 SHA 以及 15 个外来路径和暂存状态保护结果记录在同目录 `g2c-delivery.json`。本批不关闭第二批普通 owner 用户入口、超期 pending 可操作处置、整 ASH-03 或总 Goal；不部署、不写生产。

正式功能提交 `46ad5f59771cb495ac4f53182711fefcfb1576d8` 的自然 Security Scan（40845147700）发现 5 处固定合成测试幂等键误报，原 CI 红日志已保留。后续独立小修只在原 `.gitleaks.toml` 的 generic-api-key 规则下追加两组 `AND` 精确文件路径与完整固定行匹配，不放宽全局扫描或忽略其他值/路径。复用本机与 CI 相同的 gitleaks 8.24.3，原提交由 5 项命中变为 0；错路径、改值及行尾追加内容的 4 个反例仍命中。生产源码及业务测试完全不变，不重复数据库验收；TOML 解析与实际扫描结果保存在原目录 `g2c-gitleaks-*`，其中 `g2c-gitleaks-fix-result.json` 的 SHA-256 为 `d42099d69126c7dd3bf90c1f273353fa113045380dbb2aa12b757c641f5a2bec`。修复提交及其自然 CI 状态续记原 `g2c-delivery.json`，原失败运行不改写成成功。

自然 Fast Feedback 的两个 Python 版本另发现测试收集期 UUID 随机值导致 xdist 节点 ID 不一致。独立测试修复仅将该 NUL 前缀反例的合法 UUID 后缀固定，仍保留真实控制字符及其拒绝断言；本批其余参数化未发现同类直接字符串随机 ID。Python 3.13.5 下受影响 Application 模块使用 `-n 2` 实跑 **7 通过**（27.13 秒），未关闭并行；原双版本 CI 错误日志和新 JUnit 保留在原目录 `g2c-ci-fast-failure.txt` / `g2c-xdist-fixed.*`。生产源码不变，修复后的双版本 CI 另按实际结果记录。

Fast Feedback / Consistency 还发现入口清单过期：此前本地运行了 `data_center_architecture_inventory.py`，遗漏了独立的 `data_center_entrypoint_inventory.py`，不能把前者通过写成后者通过。修复使用原入口生成器，读取已提交 `1161e01ede49782f9d2394ad21b262f023469c12` 的相关 Git 文件临时镜像，避免共享工作树的 15 个外来修改混入投影；没有手工编辑生成 JSON。首次 180 秒生成超时保留，原输入重试后生成与检查分别以零退出码完成（145.706 / 134.635 秒），输入零漂移。正式 `governance/data_center_entrypoints.json` 仅新增本批来源资格合同和并发测试证据两条记录，总数 1418→1420；生成文件 SHA-256 为 `8e14a77b5c6d455a9df7e63b006195279212db778a16c64b3dc4cef46e079230`。启动输入、原命令日志及结果留在原目录 `g2c-entrypoints-candidate-r2-*`；此检查针对上述已提交输入，不宣称共享脏工作树的投影一致。三个 CI 修复分别提交并统一推送，最终 CI 只按修复后实际 SHA 记录，不把原失败或旧成功借给新提交。

修复后的自然 CI 均通过，但其测试选择只覆盖小修，不能补齐原功能提交因 xdist 收集失败而未运行的包。因此沿原 Fast Feedback 从 `3dea9b1543b08a1ca2bc02388362d691ff1a2ce4` 启动一次累计验证（40850588364）：Python 3.11 / 3.13 各 **6771 通过、258 跳过**，NoDB job 通过；质量 job 的 Domain 覆盖阶段为 **1 失败、4025 通过、2 subtests 通过**。唯一失败是原模型注册测试的严格顺序名单遗漏 `LocalDailyMatchModel`。后续独立修复仅补该真实模型的注册顺序、实际表名与定义模块，保留公开/Infrastructure/定义模块为同一对象、表身份和唯一注册断言；不改业务源码或放宽检查。原 CI 红日志与定向 RED/GREEN 续存本机 `g2c-cumulative-registration-failure.log` / `registration-*`，正式提交及新 SHA 的 CI 仍单独记录。

### 首仓估值与成交事务接线修复（2026-10-29）

普通 owner 入口前置核对发现：`DjangoSimulatedOrderFillRepository.apply_fill_event` 在账户锁的唯一外层事务内读取首仓 mark，而 `build_published_initial_position_mark_reader` 默认使用拒绝外层事务的日历入口。因此这组实际适配器组合无法完成首次 BUY；此前注入 typed mark 的首仓验收不能替代这组接线验证。

生产修改仅 4 行，在该 builder 显式绑定既有 `read_current_exchange_calendar_reference`；普通日历入口、唯一外层事务/Audit/数据库别名守卫、mark 用途政策、TTL 和原时钟校验保持。未新增模型、默认策略或 writer 启用。Root 以原生产字节运行新增行为单测先得到 **1 失败**，恢复修复字节后原组合模块 **13 通过**。新增 PostgreSQL 单节点 r6 为 **1 通过、0 失败/错误/跳过**（JUnit 25.783 秒，进程 48.489 秒），34 项实际输入零漂移。缺失及损坏日历前先证明公开价格来源可读，随后断言 `INITIAL_POSITION_MARK_UNAVAILABLE`、账务/预留不变及原待消费事件可回读；正常首次 BUY 在 Fill 事务内写入独立 mark，Position 和 V2 receipt 完整保留价格及原件身份；嵌套事务仍拒绝，精确 receipt 重放不再读取来源或时钟。

本验证的合成日线响应经过实际 capture、RawAudit、独立 current candidate staging、正式三数据集激活及 Audit/Outbox；实际 Config Center、证券参考快照、正式日历读取和 Fill 仓储共同完成首仓。撮合资格、已接受订单的结算日历及权限围栏仍是既有 typed fixture；quote/valuation 仅为满足完整激活形状的伴随夹具，证券范围与真实价格候选不同。该测试只证明首仓 mark 接线，不声称完整市场同范围发布、真实供应商/权限/结算旅程或普通 owner 用户闭环。

r1–r5 原失败完整保留：先后暴露测试证券身份不匹配、常量导入错误、结算夹具时间晚于原成交、旧 published 写口未建立正式 current 指针，以及伴随权限夹具与 M1 审计流的 owner 不一致。最后两项改用已有 staging/group activation 和同归属的权限夹具修正，没有手工伪造指针或放宽生产门禁。始终只复跑同一节点、单 worker，沿独立 `test_ash_mark_fill_20261029` 测试库和 900 秒预算；未重复 G2C 的 32/137 项整包。结束确认零连接后仅删除本批测试库，源库、历史库与 PostgreSQL 服务保留。

生产增量 mypy、全库债务、Black/isort/Ruff、架构/audit、模块投影、99 项当前数据合同和测试分层检查均通过。入口清单沿已有临时输入镜像使用原生成器生成及检查，隔离 15 个外来改动；本节结论属于原生成器不扫描的计划路径。精简索引和原件继续留在本机 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/durable-matcher/mark-fill-verification-index.json`，SHA-256 为 `548ac8ad6539d1bdf7cf1404f08c1035ee1130daa7c08533cb5d4ed712622acb`；索引绑定代码、合同、投影、逐轮输入和真实结果，本节不纳入自身哈希集合。正式 SHA/tree、推送及外来暂存保护结果续记原 `g2c-delivery.json`。此修复不关闭普通 owner 用户入口、超期 pending 处置、整 G2C/ASH-03 或总 Goal；未部署、未写生产。

### 普通账户订单与原成交回执只读入口（2026-10-29，开发验收完成）

本事项基于首仓 mark 接线修复 `b54599fbd16595ec1b122b7ac3dac69ff981802e`，已让普通用户在现有 `execution.accounts` 查看本人模拟订单，以及选定订单的原成交回执；后端两条 GET、同屏显示、权限/金融反例和用户操作验证一起交付。已有 `ManualTradeAPIView` 仍是即时交易入口，不改作订单流程；本批不开放 Reserve/Match/Apply/Cancel，不读取供应商、生成源事件或改账，也不新建模型、状态平台或 screen。

订单只用公开数字编号定位，业务幂等键、封存 payload 和内部来源定位留在服务端。新增窄 Application query/typed DTO 与 Infrastructure reader，沿原 `decode_order_reservation` 验证金额和封存列；原成交回执沿 `read_order_reservation_fill_row` 精确核对 Reservation/Receipt/Trade。只声明单条回执核对，不能以此宣布完整费用/资源前缀链有效。订单列表包含终态和已停用模拟账户；每次请求从认证 principal 取得用户并在数据库重验当前有效用户、账户 owner、reservation owner，不采用允许 superuser 读取他人账户的旧便捷 helper。

分页有界，续页绑定用户/账户/订单范围、末行及服务端收录截止，拒绝篡改、换账户、未来截止和非法页大小；收录截止只限定成员集合，本次读取时间单列，不能称历史 PIT 状态快照。回执列表直接读持久账本，不依赖可损坏或不可用的撮合 source；空页只表示本页无可核对记录，不能推断从未成交或可释放 hold。durable decisions 发现及显式撮合/入账/撤余量留到后续完整事项。

实施落点限定为 simulated_trading 的 order_history Application/Infrastructure/composition/Interface 与原 API 路由、对应单元/组件契约，以及 terminal 内原账户 screen 的窄 metadata/result/test 接线。复用现有账户选择、表格/详情和分页，不增加 JS 业务状态机、不泛化费用恢复 continuation；原 `30-actions.js` 已接近规模门限，优先零改动。Luna max 独占已分配源码路径，Root 负责复核、共享投影与 Git 短窗口；只读诊断并行，数据库及浏览器验收由 Root 冻结输入后安排隔离资源与预算。

已验证普通 owner 正例、陌生用户/管理员越权/停用用户拒绝、停用账户和终态订单历史、缺失或损坏回执、分页稳定范围、无来源读取与零持久写入，以及 API Content-Type/状态码。TUI 接线补齐解析后的账户/订单路径参数，并传播真实阻断结果；正常的单条回执核对范围说明进入业务摘要。专业模式窄屏表单保留可点击的提交区域，详情采用单列；浏览器实际展开回执区并验证可见价格单元格、结果宽度和无页面横向溢出，不以隐藏 DOM 文本充当用户验收。

开发验证保留逐轮输入和真实结果：最终无数据库回归 **93 通过**；原生 PostgreSQL 组件轮为 **13 通过、1 个夹具失败**，修复测试对不可变创建时间的非法更新后，该节点单独 **1 通过**，不称为一次 14 项全绿运行。SQLite 关联回归为 **508 通过、1 个窄屏点击失败**，其中全部 14 个新 API 组件用例通过；修复布局后，最终原生 PostgreSQL 的真实 HTTP/浏览器旅程在 1440×1000 和 390×844 两种视口 **2 通过、0 跳过**，原 Node 视口/专业模式回归 **7 通过**。浏览器覆盖已有部分成交、空回执、分页、跨账户 404 后清除旧事实和金融行不变；不能把首轮 SQLite 记录改称全绿。测试复用合成的资格、日历和成交夹具，不代表生产账户、真实行情或 QMT 验收。

10 个生产 Python 文件的最终输入与类型运行一致，增量 mypy 和全库债务均为零；16 个 Python 文件 Black/isort/Ruff、增量架构边界/audit、测试分层及原模块/TUI 投影门禁通过。原 Data Center 入口检查通过（1420 项、投影无变化），其后仅调整 CSS 与浏览器断言，没有新增入口；runtime manifest 显式纳入新结果 projector。自有 PostgreSQL 测试库在确认零连接后清理。失败原件保留，未增加债务基线或放宽权限与金融守卫。

本机索引为 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/order-history/verification-index.json`，SHA-256 `f9238cb925cd902344eb373b2000d61c9e0fc7e4612f75ba8ada05b859de32d5`；绑定 21 个源码/测试/投影/专项说明输入及原件，本节不纳入自身哈希。正式提交、tree、推送、精确提交密钥扫描及 15 个外来改动保护结果另记同目录 `delivery.json`，完整原件仅本机可用。本批不关闭双时点结算证据、超期 pending 业务处置、完整 owner 写流程、G2C/ASH-03 或总 Goal；没有部署或生产写入。

### 成交与释放双时点日历（2026-10-29，开发验收通过）

前批 `83792ad` 的自然 CI 已终态：双 Python 主运行各 1051 通过、76 跳过，新增订单历史 API 各 14 节点实际通过；Publication、Architecture、Security、Dashboard 通过。但 Fast quality 与 Consistency 因 `governance/data_center_architecture_inventory.json` 过期失败，不能将该 SHA 写作 CI 全绿。原失败记入 order-history 的 `delivery.json`；本事项按当前完整源码用原生成器更新这一投影，并一并验其精确候选，不重跑旧浏览器或替换旧 CI 结论。

普通账户只读入口已提交 `83792ad449f6d5fdbc8699a82cb2bc9a115e9af9`。下一完整事项修复延迟入账共用一份日历的实际阻断：原 resolver 从当前指针取证，但 fill proof 要求该证据在成交时已知；仓储又要求同证据在当前仍有效。当前日历发布晚于成交或原日历已过期限时，两种语义无法同时满足。

事件证明改读 reservation 原有完整封存日历，严格重建原字段和哈希，在事件知识截止校验有效期、开市日及完整结算周期；锁内再次核对 proof 与原计划的精确封印。`calendar_read_cutoff` 在这一路表示事件知识截止，不伪造实际读取或记录时间。新的 MATCHED 决定保存前先验证同一事件证明，缺失、事件时点过期或未来发布均不得产生不可入账的新事件。原决定和 receipt 精确重放保留，不修改旧记录。

当前释放日历由明确注入的公开 reader 在原账户外层事务内读取，用于当前开市日、既有 pending 股份释放和独立 release proof；覆盖从最早待结算日到当前的完整区间。新 T+0 跨日入账沿已有 release proof 字段记录当前证据，旧 lag-zero 无 proof 回读兼容。新 T+1 成交仍先 pending，原 ReleaseDue 用例或后续交易负责实际释放，不改写原预计释放日、封存 lag 或事件时钟。复用原 proof/V4 binding 和模型，不新增持久版本或状态平台。锁账户后重验并锁当前 active actor；缺来源或权限时事务无金融写入。

Root 负责仓储、显式 composition、共享投影和分批提交；原 Luna max 分别负责 Application/严格解码、新撮合前置验证和组件反例，直接回写正式源码。验收覆盖旧日历在事件时有效但当前已过期、当前日历晚于事件、缺失/过期/错范围/覆盖缺日、封存证据替换、跨日 T+0、T+1 后续释放和精确历史重放；轻量单测可并行，数据库使用独立资源串行运行。原件统一留 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/fill-dual-calendar/`，复用既有门禁，不另建控制设施。

开发验收：冻结输入的无数据库单测 **360 通过**；原生 PostgreSQL 双时点新例 **12 通过**、真实持久撮合及 Apply 组装 **10 通过**、原账本/释放/费用/权限/并发回归 **108 通过**；SQLite 兼容 **14 通过**，上述各轮原件独立保留。全部 10 个生产文件增量 mypy 无回归、全库类型债务为 0；18 个 Python 文件 Black/isort/Ruff 通过；架构 boundary/audit 为 0，原当前数据合同、模块图、入口和架构投影、测试分层检查通过。原生 PG 专用测试库确认无连接后已清理。首次三值解包生产缺陷、后续替换日历测试夹具错误及原投影 stale 失败均保留，修复后分别运行对应完整回归，未降低门禁。

本机原件及精简索引为 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/fill-dual-calendar/verification-index.json`，SHA-256 `fb8fe6238a0cedc72d428a0514494a25d9eca0f8c7a112700f780aded3290027`，绑定 23 个实际源码/测试/投影/专项说明输入，本节排除自身哈希。正式 commit/tree、精确提交规模与密钥检查、推送和 15 处外来改动保持结果记录在同目录 `delivery.json`；原件仅本机可用。回滚范围为本完整代码事项，不重写历史订单或成交证据；新 SHA 自然 CI 与正式发布仍独立核验。

本事项仍保持身份凭据在实际入账时有效的既有检查。下一事项拟在原账户、当前 active actor 和订单锁内，直接锁定并严格解码同库原 `LocalDailyMatchModel`：核对唯一 MATCHED、账户/订单/namespace/操作键、完整输入/结果/事件及记录摘要，只有验证通过的真实持久事实才可使用其原 `recorded_at` 校验当时身份。不得信任调用方 DTO 时钟、延长旧 TTL 或强制取消解除 hold；普通事件仍使用当前时钟，当前权限、余额、释放日历和首仓估值检查保持。此方案仅完成只读边界复核，尚未实现或验收；公开 owner 写流程待此依赖完成再接线。本批没有部署、生产写入或真实供应商调用，不关闭整 ASH-03 或总 Goal。

### 最小持久事实及事务边界

如无可复用的成交前事实载体，仅在 simulated_trading 增加一张窄的不可变模拟撮合决定表，不另建余额、账户状态或通用恢复平台。候选字段为：原 reservation 外键、当前 owner/account 绑定、namespace/稳定决定编号、调用操作键及请求哈希、观察的稳定证券/交易日标识、决定类型与规范 payload/SHA-256、输入 Publication/原件/策略摘要、原 observed/available/published/occurred/recorded 时钟。决定类型明确区分已生成成交事件和已核实的 no-match；no-match 记录原输入及原因，重试原键返回原结果，不能因后续策略或发布变化而改成成交，也不伪造 Fill 事件。缺资格的拒绝不伪造已接受决定。成交 payload 保持现有 `LocalSimulatedFillEventV1` 和 receipt 合同，不另造 Vn。数量、价格、事件类型及订单 intent/reservation/plan 哈希均在规范 payload 中严格解码；查询所需的订单、稳定观察及操作键采用明确索引。

producer 是显式撮合 Application 用例及其 Infrastructure 实现：先查询同一操作键的已存事件，精确重放不重新读取最新行情；新操作在账户父锁和原订单锁内复验 owner、订单、冻结输入、容量与配置，再运行纯规则并提交事件。唯一约束同时保护原订单的操作键和原订单的稳定市场观察，换键不能重复撮合同一观察。事件持久化事务必须先提交，再由第二事务调用原 `ApplySimulatedOrderFillUseCase` 消费；发生中断时已保存事件就是恢复真源。读口不懒生成事件，账本失败不删除源事件，事件保存不直接改 Trade/Position/现金或 hold 消耗。

同一订单只允许一个尚无精确账本 receipt 的源成交事件；检查在同一账户锁内进行，覆盖所有原观察及交易日。E1 已保存 300 股而 hold 仍显示 500 股时，E2 必须等待 E1 恢复或核对，不能据 hold 再承诺 500 股。事件/receipt 损坏、无法确认消费或顺序时继续阻断；不引入多个 pending 的新费用/数量状态机。容量统计计入未消费的已接受事件，no-match 不消耗成交容量。

reader 实现现有精确 `read_event`，并增加当前 owner 下、按原订单的有界事件发现；页大小和游标只控制显示，不能跳过未决事件而释放预留。锁内重读必须与锁前事件完全一致；损坏、异主、异订单、异 namespace、同键不同 payload 或未来可见时间均阻断。先读本地精确 receipt；已入账的旧事件在来源不可用、策略变化或订单终态时仍可按当前权限核对。未找到 receipt 不能推断未入账；新恢复写入须显式调用原事件，不换键、不改原时间、不自动解除未知状态。

撤单须在同一账户锁内核对该订单已保存但尚未消费的源事件。存在未决或损坏事件时不得先释放 hold；先恢复精确成交或保持待核对。已成交部分沿原费用前缀和 V4 结算链，余量取消仍只释放一次。新增事实的取消、释放、reset/delete 保护与 producer 同一完整事项交付；已有 active hold/receipt 保护能覆盖的路径注明代码依据，不重复造守卫。迁移不回填旧订单的猜测事件；只要存在新事实，反向迁移拒绝删除历史。本事项上线后不得回滚到不认识新源事件的旧应用继续提供写接口；代码回退只能选择仍含该保留守卫的兼容版本，或保持这些写入口关闭，不以删除新表换取回退。

### 分批实现与验收

0. **纯撮合计算**：先独立交付 `domain/local_order_matching.py`、对应测试和模块投影。该小事项只处理已声明输入下的数学与阻断规则；不新增来源、模型、写接口、任务或配置默认值，不关闭下面两批。
1. **生成并保存可恢复模拟事件**：完整交付纯撮合规则、显式配置读取、合格来源适配、producer、唯一约束、只读发现以及上述取消/释放/历史保留守卫；源事实必须由实际用例产生，不以测试直接插表冒充。预计落点为本 App 的 matcher Domain/Application、窄 Infrastructure 模型/仓储、迁移和现有 composition，配置仍归 config_center。无公开自动执行入口，实际字段/代码范围在接线前依实体定义收窄。若保留守卫不能与现有入口完整闭合，就合并第二批一起交付，不能仅依赖默认关闭接受有事件时的旧写口绕行。
2. **订单恢复与用户入口**：将同一 reader 注入 Application 和原 fill 仓储，复用正式日历 resolver 和独立首仓 mark，接通普通 owner 的显式撮合/发现/恢复/撤单流程。包含恢复后的真实账本及用户旅程；不得仅交一个空 factory 宣称闭环。两个完整事项分别过适用开发门禁即提交，不等待整 ASH 单元或生产发布资格。

失败优先矩阵：500 股 BUY 预留后 E1=300 股部分成交，分别在事件提交前、提交后账本前、账本事务中、账本提交后响应前中断；重启只使用原 E1，剩余 200 股及费用前缀正确。E1 未消费时，即使跨日也不能产生 E2；E2 只消费合法余量，撤单只释放未成交部分。覆盖同事件重复、no-match 同键遇到策略/发布变化、换操作键/发布版本重复观察、并发 producer 与同账户抢容量、E1 与取消竞争、同 locator 不同 payload、损坏链、错 owner/order/source、缺时钟/日历/mark、原始源不可用的历史 receipt 回放。未知条件不改账、不释放 hold，不把未知费用或数量写成零。

复用原 reservation/fill Application、repository、concurrency、migration 和 receipt 模块及 API/SDK/TUI 契约测试；新增仅覆盖实际 producer/discovery 和完整重启路径。SQLite 用于定向开发，账户锁、竞争、真实迁移和保留历史回退用隔离 PostgreSQL 验证。生产 Python 完成增量 mypy、全库债务、格式及真实增量架构检查；模型和入口变更用原生成器更新字典/模块/入口投影，更新实际适用的新鲜度或任务合同。一个业务事项维护一份输入/日志索引，失败原件保留，不增加验收运行平台。默认关闭、生产资料、真实外部对账、同候选正式发布门仍保留；本阶段不部署、不写生产。

### 纯规则开发验收（2026-10-28）

基于 `2640c8b5693f2cb7fb52da7688b46387826cc2f2`，正式源码新增 `local_order_matching.py` 及对应测试：使用精确整数份额计算，原订单须早于观察；同账户/证券/会话的历史事件共同扣减容量，先核对未取整的总容量，再对剩余量取步长。未知结果数量保持 null；已知无成交才为零。参与率与步长均显式传入，无业务默认值。

最终同一输入运行新撮合 79 项及原预留/部分成交 55 项，共 **134 通过**；新 Domain 分支模式覆盖 **93.2%**。Black/isort/Ruff、单生产文件增量 mypy、全库类型债务上限均通过，类型债务为 0；增量架构实际覆盖新增 533 行，边界及审计违规均为 0。原模块生成/检查通过，投影仅 `simulated_trading.domain` 29→30；data-center 架构清单仍一致。未改变 ORM、路由或当前数据读取合同，未运行数据库、生产或发布验收。

原件和各次输入身份保存在本机忽略目录 `artifacts/a-share-usability/ash03-order-recovery-2026-10-28/`；精简索引 `verification-index.json` 的 SHA-256 为 `6cd6a33d6df9786813b0fcdee67d101b102cab63ec8a9c8d5156c96581be1b1c`。索引绑定最终源码/测试、命令、36 份原件摘要，并保留初次缺模块 RED、容量取整及非交叉掩盖异常的 2 项 RED、84.7% 覆盖不足、mypy `no-any-return` 失败；旧轮次不冒称最终候选证据。完整日志与覆盖文件不进入 Git，也不声称远端已有本机原件。

尚未完成：正式逐行来源/逐日交易状态与独立首仓 mark、持久 producer、订单发现及重启恢复入口。上述纯规则通过不赋予成交资格，不关闭 ASH-03 第 2/3 组或 G2C，未部署、未写生产。

### 首个来源读取修复：保留已有行情元数据（2026-10-28）

原 `price_payload_helpers._price_bar_payload` 现在透传 `PriceBar` 中保存/映射的 `adjustment.value` 和 `ingested_run_id`；原数值仍为 float、旧键及 `fetched_at` 保持，历史空批次仍为空串。实际调用链为 `fetch_price_bar_payloads` → `query_published_price_bar_series`、`published_equity_context` 和公开 `get_price_bar_series`；参数、序列顺序和发布门禁不变。这是读取丢字段修复，两个字段本身不证明未复权原件、行情真实有效或执行资格。

下一来源事项须补齐精确行的事实/成员/原件绑定：沿现有发布成员 `fact_pk` 对应价格 ORM 行，保留 Decimal 原值及调整类型，再凭真实采集批次与 RawAudit 的 `ProviderResponsePayloadReference` 精确定位 RawPayload。当前写入未填价格行 `source_record_id/raw_payload_hash`，成员回退摘要可能只代表规范行，不能当原始响应哈希；缺失或不唯一的关联保持未知。原 ORM 的价格转换为 float 后已不能无损恢复，应在现有仓储边界取得原 Decimal，再通过 typed 公开合同传递。此工作可使用现有表，仍需完整读写合同和来源测试，不能由本次两个附加键代替。

单位和时钟边界：已核对的精确 Tushare 日线采集确有手→股、千元→人民币转换，但不能由这一采集器或模型 help_text 给所有历史行补单位。`PriceBarModel.fetched_at` 是本地保存时间；本次不将它或 RawPayload 本地响应完成时间改名为供应商可用时间。真实逐日交易状态/涨跌停覆盖、所需源时间及首仓 mark 资格继续按上表补齐；不新增模型、producer、账户写口或默认来源绑定。

原合同不把供应商最早披露时刻设为撮合前置：`LocalSimulatedFillEventV1` 将可见性、时钟排序和来源资格交给 adapter；`ProviderResponseCapture`/`ProviderResponsePayloadReference` 已绑定完整响应的本地完成时间，现有估值合同亦明确 `availability_basis=response_completed_utc` 只表示本系统已取得数据。后续价格 adapter 在精确原件/请求/证券/日期/行绑定通过后，可按明确声明的同类 basis 采用 `response_completed_at` 作为保守已知时间，分别保留会话观测、供应商发布（可能未知）、本地响应完成及记录时钟。它证明截至该时刻已知，不证明市场最早发布或系统历史上最早取得；capture 完成和发布可见时刻均须不晚于使用截止点，晚到采集不能倒推早期可见或刷新旧观察。价格端实际映射和资格测试仍未实现。

本批开发验收以 `8c7dd38a8b4adf1be9d807789a5591aa499e4692` 为父版本：先跑原查询端口的 5 个目标用例，得到缺字段的 **4 失败、1 通过**；修复并冻结输入后，原发布查询、公开端口、批量研究 context 及收盘排序回归共 **85 通过**，变更 helper 覆盖 **100%**。运行环境为既有 `development_sqlite` 测试库、`--nomigrations` 和独立 pytest cache，未运行 PostgreSQL/迁移/来源资格验收。Black/isort/Ruff、增量 mypy、全库债务（0）、97 项当前数据合同及增量架构（1 文件、3 新增行、0 违规）通过。全库债务首轮被外层 300 秒时限打断，保留超时失败；第二次原命令成功，未改基线。本批不涉及模块结构/ORM 投影变化。

本机原件复用 `artifacts/a-share-usability/ash03-order-recovery-2026-10-28/price-metadata/`，`verification-index.json` 的 SHA-256 为 `4257c25d764b0fb05c35ded908e3db38f6f196ae2a6f243db909cf8650805f83`，绑定实际测试/门禁输入、命令和 21 份原件摘要。日志不进入 Git，不将本地结果写成远端 CI 或正式发布通过；源适配及订单恢复的剩余项继续开放。

### 精确价格来源读回（2026-10-28，独立开发事项）

本事项新增单证券/单交易日的 typed 公开读取，保持旧浮点序列兼容。输入为规范证券、交易日、明确知识截止点及原发布键；先复用当前发布/策略/成员/事实完整性及 freshness 门禁，再沿所选成员的精确 `fact_pk` 读取 ORM Decimal。重复目标事实、缺字段或成员与当前行引用不一致均阻断。结果仅证明该价格来源，不授予 M1 以外用途、成交、结算或自动执行资格。

复用既有 `CandidateRawAuditManifest` 的只读读取和哈希验证，以事实 `ingested_run_id` 唯一匹配 manifest 中的审计引用，再核对实际 RawAudit 内容哈希、成功单行结果、provider/source/request scope、run 与 RawPayload 引用。使用现有 `ProviderResponsePayloadReference.from_payload/verifies` 及严格 JSON 解析器，复用并提取 exact daily 响应规则为 Decimal 解码；价格和量额须与 ORM 原值精确相等，不从 float 回建。事实行摘要、原始 HTTP body hash 与 RawPayload envelope hash分别核对，不混作同一种摘要。缺失、歧义、错证券/日期/复权/频率、截断响应、证据漂移或晚到响应均阻断，不找其他日期或来源补齐。

代码落点为原 `price_response_capture.py` 的共享精确值解码、新 Application `published_price_source.py` 的 typed 合同/校验、Infrastructure `published_price_source_repository.py` 的原表只读适配、`published_price_source_composition.py` 的一致快照组装和原 Public Port。不新增表或迁移；不调用 manifest 的 `validate()` 写锁路径（其 `select_for_update` 不适用于 PostgreSQL READ ONLY 快照），而复用只读 manifest 解码及既有内容哈希函数核对目标审计。验收扩展现有 exact capture 单元测试和 M1 capture→持久事实→manifest→publication 的真实往返夹具，并补来源缺失/冲突/晚到等反例；这些夹具不构成真实供应商、账户或执行验收。

本事项的时间语义区分会话观测、本地完整响应接收、审计和发布可见时刻；`available_at` 明示 `local_response_body_completion`，供应商发布时间未知时仍为空。`fact_recorded_at` 来自现有模型 `auto_now_add` 首次写入时钟；事实行重用时可早于本次响应，不能冒充抓取时间。审计能力使用原数据集映射 `historical_price`。原精确采集与新读回复用 Decimal 解码及量纲转换，不改变原 float 接口。

本批开发验收以 `9a3e9fad9e3307dc40ca3ea8f78ee792e261f4b5` 为父基线，最终冻结的 5 个生产文件与 3 个变更测试文件在同一输入下完成 **103 通过、0 失败**：新来源、原精确采集、旧发布查询及真实 PostgreSQL M1 往返一起运行。JUnit 记录实际独占测试库及读取期间 `transaction_read_only=on`、`transaction_isolation=repeatable read`，测试断言无 DML/`FOR UPDATE`；迁移和账户权限 flush 守卫保留。Black/isort/Ruff、5 文件增量 mypy、全库 mypy 债务（0）、97 项当前数据合同、模块映射、循环依赖及增量架构（5 文件、798 新增行、0 违规）通过。生成投影由原脚本产生；入口投影在精确 Git 候选树上生成验证，仅登记 source_files 13→16，排除共享工作树中他人未提交路由的行号变化。

保留缺入口的初始 RED、跳过迁移引起的权限清理失败、真实 capability 错误、测试夹具/风格和 mypy 失败及长路径解包失败的原记录；后续结果不覆盖原候选。最终原件索引为 `artifacts/a-share-usability/ash03-order-recovery-2026-10-28/price-source/verification-index.json`，SHA-256 `462e505dce42b60af2640da2369f4e4e7c3fa84ea685165a9a4ca7e2e717d354`，绑定 85 份本机原件、最终源文件哈希及各门禁命令。完整日志不进入 Git；本次仅清理自身两座测试库，原 PostgreSQL 服务与历史库保持。本事项不关闭整个 G2C，不授予生产、真实供应商或交易执行资格；逐日交易状态/涨跌停来源、初仓估值和成交来源适配仍按原依赖继续。


### 独立初仓估值读取验收（2026-10-29）

正式实现为 `initial_position_mark_composition.py` 的显式 builder、`domain/initial_position_mark_policy.py` 和 `infrastructure/published_price_initial_position_mark_reader.py`。新增配置只登记 NORMAL 可选元数据；缺值阻断本 reader，不影响无关 profile 激活。政策和分类必须绑定同一个 profile/snapshot，读前后复核，避免配置 A→B→A 时混用身份。正式日历决定盘中、收盘后及假日的目标日；缺最新已收盘日价格不回退。原未复权精确价格来源增加真实 `publication_as_of` 并校验发布时序。

最终同一冻结输入完成 **196 通过、0 失败、0 跳过**，耗时 499.37 秒：190 项 mark/身份/原 proof/精确来源/配置单元测试，另有 6 项既有 M1 来源组件测试。真实 PostgreSQL capture→fact→manifest→publication 读回继续验证新发布时点，JUnit 记录测试库 `test_ash03_initial_mark_342b_20261029`、`transaction_read_only=on` 和 `transaction_isolation=repeatable read`。mark 组合测试使用类型化依赖替身，不能写成完整真实 PG mark 链或账户用户旅程。策略 Domain 行和分支覆盖率均为 100%；6 生产文件增量 mypy 和全库债务均为 0，Black/isort/Ruff、97 当前数据合同、43 配置定义合同、模块映射、循环依赖及增量架构均通过。

原件保留缺入口的 RED、39 失败的日历哈希格式夹具、1 失败的假日 TTL 夹具、2 项 mypy 错误和可选配置误设全局 critical 导致既有 profile 校验失败的记录。修复没有改变生产 TTL 默认值或放宽门禁。最终原件索引见 `artifacts/a-share-usability/ash03-order-recovery-2026-10-28/initial-mark/verification-index.json`（本机可用；53 份原件；SHA-256 `bf66a624cd17c506043cba8a34e779d4420b2f959a715e79b7d473f2d62296c0`）；完整日志不提交。两座本事项 PG 测试库均在确认无连接后清理，原服务及其他库保持。

整合基于 `1f60441d857821a3b1071f42d38710850c0bc05b`，保留期间进入分支的 favicon 和视频提交。投影由原生成器在精确候选树产生；包含已提交 favicon 引起的 Data Center 挂载行号更新，未纳入他人未提交源码。本批不关闭 G2C/ASH-03，不启用默认 reader、不部署、不写生产；剩余阻塞仍是逐证券逐日交易状态/限额来源、持久成交 producer 与订单发现/恢复的正式接线及实际用户验收。

### 精确涨跌停价格捕获与回放验收结论（2026-10-29）

已实现显式 `build_price_limit_capture_use_case()` 与离线 `build_retained_price_limit_reader()`：每次捕获读取指定供应商配置，真实 adapter 发出单证券/单日 `stk_limit` 请求，核对原始响应和 SDK 表，复读配置后由原 RawPayload 用例留存，再重新读取原件返回精确 Decimal。响应后的配置撤销、额外字段、float/字符串数值、未知/零/反序边界、截断、错请求及损坏引用均拒绝。读取保留原本地响应完成时间；币种、市场观察时刻和供应商发布时间仍未知，结果明确不得用于决策或执行。

最终同一冻结输入 **228 通过、0 失败、0 跳过**，其中本事项合同 92 项、关联原有回归 136 项。三种 Tushare 请求模式通过真实 EgressHttpTransport 的离线 HTTP 流验证；两个组件测试使用真实 PostgreSQL RawPayload 仓储，覆盖新的 composition 回放及损坏请求拒绝。JUnit 记录 `test_ash03_price_limit_002_20261029`、`postgresql` 和原权限时钟 flush 记录；未连接真实供应商，不能作为供应商覆盖或生产资格证据。首轮与最终轮的真实输入和日志分别保留，数据库运行累计 450.72 秒；两座本事项测试库已在零连接后删除，其他数据库和原服务保持。

9 个生产/测试文件的 Black、isort、Ruff，5 个生产文件的增量 mypy，以及全库 mypy 债务检查均通过，类型债务为 0。最终增量架构覆盖 5 文件、847 新增行，边界/审计违规均为 0；原模块、Data Center 架构/入口生成器和循环依赖门禁通过。模块投影仍为 44 模块/210 边；没有新模型、迁移、路由、调度或配置默认启用。修正过程保留初始缺入口、严格性反例、REST 路径夹具、测试导入风格和冗余 cast 失败，未覆盖原记录。

本机精简索引为 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/price-limit-capture/verification-index.json`，SHA-256 `43748e8a45aa5961387bd66531e1a75ccea42a42347fa8f18053e7f5d3f1f4a1`，绑定最终输入、命令、生成投影及 39 份原件；未上传完整日志或另做 ZIP。整合父提交为 `0024531d5e4f7b7949ba85b4415c0618ebc1e8e5`。下一缺口仍是按证券/有效日可发现的正式事实、发布及公开读取，并补逐日交易状态；普通发布对 `observed_at` 的要求必须诚实处理，不能用交易日收盘或抓取时刻代填。此批不关闭 G2C/ASH-03，不授予成交资格、不部署、不写生产。

### 涨跌停事实与发布的实施边界（2026-10-29，按事项分批实施）

先修复 `3708eb2b2` 的实际 CI 文件规模失败：`_provider_adapter_tushare.py` 从 992 增至 1007 个非空行，超过增量门禁的 1000 行限制。按精确响应捕获职责拆分适配代码，保留原公开方法、配置和传输契约，不修改金融计算、持久化或门禁基线；适配器及相邻捕获回归、文件规模、类型、架构和原生成投影通过后独立提交。此失败不否定已记录的本地测试结果，也不能将那些结果称为 CI 全通过。

随后把来源落库与正式发布拆为两个完整事项，由 Root 整合、原 Luna max 代理实现和复核。正式源码直接进入 `apps/data_center/`；不建立临时业务表或第二事实真源。

1. **唯一限额事实及未发布读口。** 沿现有 `ExchangeCalendarSnapshotFactModel` / `DjangoExchangeCalendarSnapshotRepository` 的不可变原件快照方式，新增一个 `PriceLimitSnapshotFactModel`，作为后续发布唯一引用的规范化事实。目标为 `domain/price_limit_snapshot.py`、窄 Application 用例、Infrastructure 模型/仓储及 composition；模型注册和迁移一起交付。每个精确 RawPayload 对应一条事实，以 OneToOne/PROTECT 保留原件；同原件重试返回原行，范围、值或引用冲突拒绝。不同 provider、同证券同有效日的新响应各自保存，禁止覆盖历史；没有供应商修订号时不捏造 revision。上下限保存有界 Decimal 文本并严格解析，复用原捕获的 256 位数字、指数绝对值 512 约束，不经 float 或固定四位小数量化。
2. **限额专属正式发布。** 第一事项通过后，为 `equity.price.limit` 增加明确持久绑定的 nullable-time codec，复用现有 canonical publication、member、pointer、审计和原件治理。普通 `PublicationFactReference`、`PublicationFactIdentity` 及普通 evidence、staging、activation、rollback 都要求观察时间非空；日历 codec 又是专属规则，因此不能冒用日历类型或全局放松观察时间要求。只修改该数据集必需的 codec/policy 约束、事实身份、成员封印、激活、回滚和一致快照读取接缝；不扩展成通用 Vn 平台。发布按有效日精确定位，知识截止用 `as_of`，实际指针可见时刻用 `published_at`，不能用跨日 latest 补缺。

第一事项的字段与读语义如下，实际开发验收见下方“唯一涨跌停事实及未发布读取验收”。第二事项的发布与执行资格仍未完成。

| 信息 | 保存及校验口径 |
| --- | --- |
| 证券、适用日期、供应商 | `asset_code`、`effective_trade_date: date`、显式 `provider_id/provider_name`；完整重建原请求并逐项核对原件 |
| 精确上下限、计价资格 | 原 Decimal 表示；`price_unit=provider_native_price`，`currency=None`，不得据此认定 CNY 或可成交 |
| 时间 | `response_completed_at` 为本次原响应的本地完整接收时刻，不表示全局首次发现；`recorded_at` 为该事实首次落库时刻；源观察、源可用、供应商发布时间保持未知，日期不转换为午夜、9 点或收盘时刻 |
| 身份与原件 | UUID、完整响应引用、RawPayload envelope hash、原 body SHA、内容 hash、含首次落库时间的 record digest；分别校验，不互换哈希含义 |
| 发现与精确回放 | 按证券/有效日/显式供应商和知识截止发现；同时要求本地响应完成与首次落库不晚于截止。零候选为缺失，多候选为歧义，不自动选最新；精确引用可回放历史，但不能解除未发布限制 |
| 输出状态 | 始终 `publication_status=unpublished`、`must_not_use_for_decision=True`、`must_not_execute=True`，发布缺失、歧义、未来可见及原件损坏有稳定原因；读取不访问供应商、不修补事实 |

模型和普通 ORM 写入口保持只追加，读回重算封印并重放原件，防止绕过模型校验后的损坏被接受。迁移只新增该事实表及必要约束/索引，不迁移或修改旧行情表；代码回退保留事实及原件，存在记录时不得通过反向迁移删掉历史。完成标准包含精确采集到真实 PostgreSQL 持久化再到全新 reader 的往返、同原件并发重试、不同来源/响应并存、错误 scope/value/hash、四位以上精度、双时钟截止、缺失/歧义阻断、原件删除保护及保留历史的迁移回退。复用现有 capture、calendar snapshot 和仓储测试设施，类型/架构及模型字典、模块/入口投影用原门禁生成检查；一个事项保留一份输入与原件索引。

第二事项另验正式发布、激活、可见区间、精确读取及回滚；触及共享接缝时回归现有 calendar codec、member evidence、raw-audit manifest、publication activation/rollback 和 read snapshot 测试。第一事项不注册 active publication policy，不接普通 current/published query、风险或执行；第二事项也不自动授予成交资格。逐日交易状态、持久成交 producer、订单发现/恢复与真实用户验收仍是原 G2C 后续依赖。

### Tushare 捕获适配器拆分验收（2026-10-29）

已修复上述规模失败：四个精确捕获方法及配置模式解析移至私有 `_provider_adapter_tushare_capture.py`，公开 `TushareUnifiedProviderAdapter` 仍沿原 Base 初始化，保留配置、部署区域接缝、返回类型和异常透传。主适配器从 1007 降至 942 个非空行；没有抬高上限、修改金融计算或持久化。两名原 Luna max 代理分别实施和只读复核，Root 整合。

冻结的 2 个生产文件和 8 个相关测试文件完成 **171 通过、0 失败、0 跳过**（pytest 5.20 秒）；Black/isort/Ruff、2 文件增量 mypy、全库 mypy 债务（0）、原文件规模门禁、增量架构（2 文件、111 新增行、0 违规）、循环依赖、97 当前数据合同和 11 个凭据入口检查通过。模块投影由原生成器更新，仅 Infrastructure 文件计数 222→223；架构投影再生成无差异。入口原检查在精确生产验证树通过，输出不变，耗时 176.28 秒；最后的测试别名/区域断言和本事项说明不改变入口发现范围。没有模型、数据库或路由变更，未重跑完整 PostgreSQL 验收、未接真实供应商。

保留 `3708eb2b2` 对应 CI job `122997165502` 的规模失败原日志、本地同失败、测试 import 排序失败，以及投影检查 120/180 秒超时；最终通过不覆盖失败。精简索引为 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/tushare-capture-split/verification-index.json`，SHA-256 `33256d37580ce4b5f9a6bd05354b3b1f313dc40b544ee10bbe40ee38c642446a`，绑定最终源码/测试、投影和 34 份本机原件。临时验证树 `.tmp/ts37` 的清理被自动审批以 `blocked by policy` 拒绝，保留且未绕过；它不是业务实现的唯一落点。本批基于 `3708eb2b20468bd3e569da2f3217bab8e08c044c`，仅解除该开发事项的已知规模阻塞，不继承旧 SHA 的 CI，也不代表上节事实/发布已实现或 G2C 关闭。

### 唯一涨跌停事实及未发布读取验收（2026-10-29）

第一事项已落入正式源码：新增唯一 `PriceLimitSnapshotFactModel` 及 `0105_price_limit_snapshot` 迁移，显式 capture/record/reader composition 串接原精确捕获、RawPayload 留存和离线读取。每个原响应只保留一条规范化事实，同原件重试保留原 UUID 和首次记录时间；新响应各自保留，发现多个候选时明确拒绝自动挑选。每次读取重放原始字节、核对请求范围和 Decimal 文本，并验证内容与记录摘要；本地响应完成和首次落库均受显式知识截止限制。普通 ORM 更新/删除和原件删除受到保护，有历史记录时真实反向迁移拒绝删表。币种、源观察/发布时间仍未知，结果始终未发布且不得用于决策或执行。两名原 Luna max 代理分别实现 Domain、仓储和模型，并进行只读复核，Root 负责应用层、组装和整合。

初轮冻结 13 个变更文件及实际依赖，共 30 个输入，在完整原迁移和权限时钟 flush 守卫下取得真实 PostgreSQL **146 通过、0 失败、0 跳过**（pytest 338.55 秒，进程 358.24 秒）。新增组件为仓储 5 项、真实往返/双连接并发 2 项、迁移 1 项；迁移的空库逆向/前向、有历史拒绝等场景同属一个测试节点。配置和 HTTP 响应使用离线夹具，数据库与仓储是真实实现，不能据此声称已连接真实供应商或通过生产验收。

随后核对 CI 选择范围，补验 SQLite 时发现测试 SQL 使用带连字符 UUID，未命中该后端的实际主键表示。首次 300 秒迁移超时与续用本事项隔离库后的 **1 个真实失败**分别保留。仅修改仓储测试，所有 5 次 SQL 注入/恢复改用 ORM 主键字段的数据库参数准备，并断言每次命中 1 行；同文件 5 项在 SQLite 和新建 PostgreSQL 隔离库分别全部通过、零跳过（8.40 秒、259.45 秒）。JUnit 记录实际库名和后端。最后两轮使用 `available_apps=data_center`，没有全局账户权限 flush，不能扩写成账户验收。生产代码及其余测试输入未变；146 项初验和后续双后端定向验证分别绑定输入，不称最终候选重新跑过完整 146 项。

Black/isort/Ruff、7 个生产文件增量 mypy、全库 mypy 债务（0）、原规模门禁、增量架构（含迁移 8 文件、1699 新增行，边界和审计违规均为 0）、循环依赖、97 项当前数据合同和 11 个凭据入口检查通过。`makemigrations --check` 无漂移，初轮真实迁移图 `unapplied=0`。模型字典、模块和架构投影由原生成器更新并验证；入口投影的真实 stale 失败保留，原生成器补入本迁移测试的 1 条 `candidate-review` 证据，原一致性检查最终通过（354.73 秒），无其他工作树入口/行号变化。该条证据状态不代表新增发布入口或交易资格。

本机精简索引为 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/price-limit-fact/verification-index.json`，SHA-256 `32350b9e9cac2d99941d1a30adfb95b041bcb06afb807821b3fffca1a42b311e`，绑定最终输入、原检查命令、生成投影及 76 份原件。缺入口、早期夹具/风格失败、SQLite 超时与真实失败均保留；完整日志不进入 Git，不另建 ZIP。两批专用 PostgreSQL 库均在零连接后删除，原服务和历史库保持；本事项 SQLite 测试库仅本机留存。整合父提交为 `7dd4a3ddd7ff625d85cec2a73ebdbe1faec8f655`，正式提交与推送身份由同目录 `delivery.json` / `push.json` 记录。

本事项不等待第二事项或整单元退出门才交付，也不关闭 G2C/ASH-03。后续先明确限额专属发布的共享接缝、调用方与最小回归范围，再实现发布/激活/精确读取/回滚；逐日交易状态、持久成交 producer、订单发现/恢复及真实用户验收仍未完成。本次未部署、未写生产、未启用默认来源或执行资格。

### 涨跌停发布策略编码前置事项（2026-10-29）

事实事项已正式提交并推送 `5d18f37da9b0bfb765821375b48be29e480f4529`。下一完整小事项先解决既有策略入口不能保存限额专属证据编码的问题：新增 `domain/publication_member_codec.py`，修改 `domain/contracts.py`、`infrastructure/catalog_models.py`、`management/commands/initialize_data_center_catalog.py`、`management/commands/activate_publication_policies.py`，并对 `domain/formal_exchange_calendar_publication.py` 的日历编码属性作精确类型收窄。Root 整合，原 Luna max 代理实施及独立复核，正式源码不滞留临时副本。

新编码仅适用于 `equity.price.limit` 的显式非 legacy 策略，拒绝将未知的源观察、源可用或供应商发布时间列为必需证据。旧 `None`、日历编码、策略身份和哈希保持原契约；普通与日历 evidence 路径继续拒绝误传的新编码策略。原 `PublicationPolicyRepository.save` 已支持枚举序列化及版本不可变，无须新增仓储或管理入口；其隔离数据库测试包含原有激活语义，但本事项不执行真实策略初始化/激活命令，不加入默认策略或种子。

迁移跟随实际最新 `0105_price_limit_snapshot`，仅替换已有策略编码约束，不加表、不改旧策略行。逆向检查须在任何反向约束修改前、同一原子事务内执行；PostgreSQL 锁定策略表，任何 active/inactive 限额编码历史均拒绝回退。空库可逆；历史记录、原约束和迁移状态在拒绝后保持。既有迁移测试必须恢复运行前的真实叶节点，避免将数据库留在 0105。

验收合批包含新 Domain/严格解析/旧哈希及误路由反例、真实仓储不可变和两个 CLI 解析、SQLite/PostgreSQL 正负数据库约束与真实迁移。重 QA 使用原测试设施与隔离资源，预算和实际输入绑定同一事项原件目录 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/price-limit-policy-codec/`；原格式、类型、架构及受影响生成投影检查保持。此处记录实施范围，实际结果随后补入；专属成员封印、正式发布/激活/精确读取/回滚及成交资格仍未实现，不据此前置事项关闭 G2C 或总 Goal。

实施结果：新增迁移为 `0106_price_limit_member_codec_policy`，上述正式路径和相关测试已完成。原 Luna max 实施，另一 Luna max 独立只读复核未发现阻断，Root 统一验收。新入口缺失的首次测试收集失败和错误 pytest 参数均留存，后者不计业务反例。完整轻量兼容回归 **244 通过、5 个数据库节点未选入**；新增 decoder 的 19 个语句、8 个分支覆盖率均为 100%。10 个变更 Python 文件格式检查通过。

SQLite 首次复用旧 PID 测试库取得 **23 通过、2 失败、4 清理错误**：原权限时钟守卫拒绝跨进程文件名，未清理的策略行随后触发迁移历史保护；原件和失败库保留，不改守卫或删除历史行解锁。改用原设置生成的当前进程隔离库并执行全部原迁移，**25 通过、0 失败、0 跳过**（pytest 310.40 秒，进程 331.40 秒）。随后新建 PostgreSQL 独立源库/测试库，同一冻结输入 **25 通过、0 失败、0 跳过**（352.97 秒、375.76 秒）；两个窗口均在修订后的 400 秒预算内且串行执行。JUnit 记录实际后端、库名和原权限时钟清理；真实仓储往返、版本不可变、两个编码的新旧约束、inactive 历史逆向拒绝及拒绝后的约束完整性均通过。原 None/Calendar 策略在迁移往返后全字段不变，旧 0105 测试恢复完整叶节点。本次两个 PostgreSQL 库已在零连接后清理，原服务及全部历史库保持。

7 个生产文件（含迁移）的增量 mypy、全库债务检查均为零；原规模门禁通过，增量架构覆盖 7 文件、166 新增行，边界和审计违规均为零。迁移无漂移，97 项当前数据合同、11 个凭据入口、循环依赖检查通过。由原生成器更新的投影只有策略约束描述、Domain 文件数 47→48、入口清单新增本迁移组件证据 1 条；无公开入口或其他工作树改动混入。入口原一致性检查通过（347.68 秒），该证据仍为 `candidate-review`，不代表发布资格。

本机精简索引为同目录 `verification-index.json`，SHA-256 `6d13a41ace6950ea83c975ec4c0c27df8400b05a9822e29f328ce1f59257ea6c`，绑定 31 个实际源码/测试/支持依赖、3 个投影及 46 份原件，保留全部中间失败，不另建验收包。父提交为 `5d18f37da9b0bfb765821375b48be29e480f4529`；校验对象仅用于增量源码门禁，正式提交及推送身份由后续 `delivery.json` / `push.json` 记录。本事项按 14 个正式路径独立交付，后续成员封印与发布生命周期仍待完成；不关闭 G2C、总 Goal 或正式发布退出门。本次未部署、未写生产。

### 涨跌停受限发布、历史读取与回滚实施范围（2026-10-29）

前置事项已正式提交并推送 `d1aeb1347a8a887c2ca1162e3ffa9f9dea065c96`，七项 CI 全部通过。下一事项交付可调用的完整受限发布链：只读预览、显式确认、当前及历史时点读取、精确编号回读和显式回滚。Root 负责整合与仓储/API，原 Luna max 分别负责 Domain、权限接缝和 Audit。正式源码直接落地；本节是实施范围，不代表验收已通过。

- **领域与来源**：新增 `apps/data_center/domain/formal_price_limit_publication.py` 及必要的同名职责拆分，引用唯一 `PriceLimitSnapshotFactModel` 和原 RawPayload，不另建事实表。范围固定为真实 provider ID/name、证券和有效交易日，发布键由原完整请求哈希服务端派生。封印包含完整 DatasetContract、PublicationPolicy 身份及记录时刻、唯一成员、规范事实行 bare SHA-256、原始 body SHA-256，以及相互独立的 prefixed snapshot/raw 摘要；不混用摘要语义。coverage 只表示本请求的一条事实。查询 cutoff 不进入内容哈希。
- **可见区间**：不可改写首次发布时间；前向发布事件必须带经审计核实的前驱身份，回滚必须同时绑定原 `PublicationRollbackModel`。验证同范围、唯一严格时序、连续前驱、目标原始发布时间和末端 pointer/hash/activation/time；同刻、回拨、断链和伪造前驱拒绝，不用 UUID 排序或人为加微秒。已被替代的同内容只能经显式回滚再次激活。历史 cutoff 不晚于服务端当前时间，读取仍验证当前权限及现行合同资格；不得以当前配置更新时间倒推历史可见性。
- **受限状态**：现有 `CanonicalPublication.PUBLISHED` 禁止 `must_not_use_for_decision=True`，因此不能为落表清掉禁止标记。增加仅限 `equity.price.limit` 的 `reference_published` 与 `reference_superseded` 两个状态，保留普通 `published` 不变量及读取门；两种受限状态都必须带完整发布身份、成员、范围和禁止决策标记。普通 save、candidate stage、activation 和 rollback（含既有 rollback ID 重放）拒绝此专属数据集，避免普通历史读取将被替代的受限记录误认为可决策记录。专属返回始终 `must_not_use_for_decision=True`、`must_not_execute=True`，源观察/可用/发布时间和币种仍未知，不借用 Calendar TTL、不加默认 TTL、不授予成交资格。
- **权限**：新增 `application/price_limit_publication_authority.py`、`infrastructure/price_limit_publication_authority_repository.py` 与 `interface/price_limit_publication_session_adapter.py`；从现有日历权限仓储提取固定三用途的私有 Session/grant 锁定核。原 Calendar facade、错误码、摘要和 ContentType 绑定保持；限额独立绑定 `publish_price_limit`、`pricelimitsnapshotfactmodel`、purpose 和 alias。预览、确认、current/exact/history 和回滚均需真实 Session 及此管理权限，写请求保留 CSRF；不能借定位编号取得授权或暗授全局 Audit 浏览权。迁移跟随实际叶节点，权限 Meta 与状态 choices 同步，无自动授权或种子。
- **审计与事务**：新增 Audit 的限额专用 Domain/Application event/detail、`apps/audit/price_limit_publication_composition.py` 和 `core/integration/price_limit_formal_publication_audit.py`。发布/回滚属于固定的全局来源事件；不伪造 tenant、run 或 RawAudit，不复用 Calendar 事件类型。沿现有 SystemAuditEvent/Outbox 存储、流锁和同 alias 外层事务，事件、outbox、成员、coverage、pointer 和 rollback 原子提交；任一步失败全部回滚。重放只核验原审计对，不补造缺失原件。
- **应用、仓储与入口**：新增 `application/price_limit_publication_operations.py`、`infrastructure/formal_price_limit_publication_repository.py` 及按职责必要的读写支持模块，新增 `price_limit_publication_operations_composition.py` 和 `interface/price_limit_publication_api_views.py`，路由仅进入现有 `interface/api_urls.py`。Interface 只使用 Application/composition，全部字段显式校验。preview 服务端重建源、配置及 expected pointer；confirm 锁内重新核对撤销、原件、配置和完整 CAS，同一身份重试不重复审计。actor、clock、alias 不由客户端指定；current 仅指明确范围的当前发布，不表示实时行情。不新增 Classic 页面或 TUI 第二主任务，最终普通用户 613 旅程仍沿原 TUX 合同验收。

开发门禁合批覆盖新领域正反例、旧 ordinary/Calendar 兼容、真实 Session/CSRF/权限撤销与锁顺序、SQLite/PostgreSQL 持久往返、完整 CAS/并发/历史链、跨源跨日拒绝、损坏与审计/outbox失败原子性、API 状态和 Content-Type。Domain 覆盖率不低于 90%；生产增量 mypy、全库债务、架构/规模、模块/模型/入口投影和 current-data 合同使用原工具。重 QA 在源码冻结后串行使用独立库、缓存/任务通道和端口；预算按完整用例数登记后执行，不复用旧 PID SQLite 库、不降低原权限 flush 守卫。原件集中在 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/price-limit-publication/`，只维护本事项精简索引，保留真实失败。

完成标准是上述实际调用链和相关门禁通过后形成正式提交；仅有 DTO、临时脚本、测试准备或未接线适配器不能算本事项完成。逐日交易状态、成交 producer、订单恢复、真实来源与最终用户旅程不因受限发布通过而关闭。本次不部署、不写生产、不调用真实供应商，不扩展无关生命周期或控制设施。

实施结果：本事项已整合到正式源码，增加六个受权限控制的 JSON 管理入口及迁移 `0107_price_limit_reference_publication`，复用现有事实、发布、回滚和 Audit/Outbox 表。预览不创建候选，确认绑定原会话期限、完整 CAS 与源/配置封印；所有管理读取验证完整历史与审计对。普通发布入口拒绝限额数据，首次发布时间与回滚后的可见时间分开。限额结果的禁止决策、禁止执行标记始终保持。Root 负责整合，三位原 Luna max 分别实施及复核领域、权限与审计接缝。

开发验收：轻量新旧回归 **288 通过**；审计测试导入排序修正后独立复核 **118 通过**。启用分支统计后的综合覆盖率为 PriceLimit Domain **95.8%**、Audit Domain **94.8%**；纯分支命中分别为 **198/202（98.02%）**、**131/144（90.97%）**，均有原报告。PostgreSQL 完整合批 **102 通过、0 失败、0 跳过**（pytest 1146.50 秒，进程 1171.84 秒），仍在原 1200 秒预算内，备用延长窗口未实际用到；随后 SQLite **78 通过、0 失败、0 跳过**（438.34 秒、463.24 秒），9 个 PostgreSQL 专属节点未选入。两批均核对输入未变化，使用真实本地 Session、CSRF、权限表、原迁移和原权限时钟清理；JUnit 记录实际库身份。确认竞争、直接/群组撤权、原日历兼容、普通写入与回滚重放拒绝、缺审计半对不修补、事件/Outbox 失败原子性及迁移约束均通过。

最终 28 个生产 Python 文件增量 mypy 为零，全库类型债务为零；Black/isort/Ruff、27 个非迁移文件的原 1000 行增量规模门、增量及完整架构、循环依赖、治理一致性、98 项当前数据合同和迁移漂移检查通过。受影响投影均由原生成器更新，原统一投影校验通过；模块地图变动只涉及 Audit 与 Data Center。新迁移在空历史时可逆，存在任一种受限发布历史时拒绝逆向并保留原约束；有历史的部署回退须保留此迁移并采用前向修复，不能删除历史或清除禁止标记。

本机精简索引为 `artifacts/a-share-usability/ash03-order-recovery-2026-10-29/price-limit-publication/verification-index.json`，SHA-256 `175cd8021418b998232175ef81a0e31d8a3a65f1995fa6ced0dfd8d6cd5f5203`。原件保留早期 RED、类型收窄和格式化失败；缺少冻结身份的早期 WIP 只作诊断，不拼入最终数据库验收。自有 PostgreSQL 源库/测试库已在零连接后清理，原服务与历史库保留；本次 SQLite 库按原当前 PID 规则创建并留存。正式提交及推送身份由同目录 `delivery.json`、`push.json` 记录；私有校验对象不计交付。本事项通过不关闭 G2C、ASH-03 或总 Goal，真实供应商、普通用户 613 最终旅程及执行资格仍待后续事项，本次没有部署或生产写入。
