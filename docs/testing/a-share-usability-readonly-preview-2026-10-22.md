# 模拟账户只读调仓预览：有界开发交付索引

日期：2026-10-22。归属：[A 股实施计划 §19.96](../plans/a-share-usability-implementation-plan-2026-10-16.md#1996-m1-first-delivery)。这是 M1 的程序交付，实际业务验收仍开放，整单元状态只读 `governance/active_plan_registry.json`。

## 本批行为

普通用户从现有 TUI 选择本人模拟账户，调用既有账户巡检入口读取只读调仓预览。服务端先检查账户权限，再取得现金、活动委托占用及持仓的同账户快照。预览列出来源、目标、当前/可卖/差额/约束后数量、费用、现金、账户及策略各自的风险限制；缺证据的结果保留未知值和原因。

证券分类沿既有 V2 本地模拟当前参考合同读取，不按代码前缀猜类型，不清除嵌套来源限制或补写上游时钟。报价、Fee V2、Risk V3 各自核验。所有活动现金预留含卖出费用缺口；同计划有可操作卖出时，买入等待卖出完成后重新评估资金和风险，不提前释放容量。零股清仓保持真实股数，负卖出净额不截成零。

规则使用当前价格和实际账户估值重新评估。规则上下文不再合成 ATR、支撑位或风险参数；旧巡检同步复用此上下文，依赖缺失指标的表达式会按原有失败关闭路径受限，须补真实指标后恢复。

`reports[].plan` 是临时预览，不是持久化可执行 TransitionPlan。TUI 只提交账户选择，省略 `auto_create_proposal`，依赖接口原有 `false` 默认值并拒绝注入该参数；巡检审计照常留存。没有新增模型、迁移、默认配置、自动交易、生产写入或部署。详细字段与行为见[接口合同](../api/a-share-readonly-rebalance-preview.md)。

## 最终候选与验证

| 身份 | 值 |
| --- | --- |
| 隔离源码与整合父提交 | `bf306da8a2614f9fc9e609db5026e3dfe7c2cb7c` |
| 最终 32 文件 manifest SHA-256 | `1f3ae84067816db1483e7768a6d6c50b3cb0c9cd452aa1113d324a24f3d7b3ab` |
| 原生 PostgreSQL QA receipt SHA-256 | `0754f150d8bcab3f4e1e83e1812446859ecf890479cb8e6be64475c6ae144f65` |
| 投影检查 receipt SHA-256 | `96c32a67aaa46938e55e27c8e393857913cbd7ea3aae605a6bfbc0ba029b0bfd` |
| 架构/浏览器 receipt SHA-256 | `d4346ef5351e4fed95cb95bba6ac9a0384770d111735c703ddba79a68f5b36a4` |
| 验证树 | `6ba28480a3a4359f881cd43bb408c83996ce377d` |

32 文件含 22 个生产 Python、6 个测试 Python、TUI 信息架构 JSON、前端源码及浏览器测试、当前数据合同；官方生成的受影响投影和精简说明随完整事项整合。运行环境为 Python 3.13.5、Django 5.2.12、专属原生 PostgreSQL 16 测试库；不冒充生产 Python 3.11 或新提交 CI 的结果。

| 检查 | 实际结果 |
| --- | --- |
| 最终四个完整模块 | 145 collected / 145 passed，0 failure/error/skip，36.55 秒；owner HTTP、数量/资金 Domain、TUI 投影、旧调仓草案回归 |
| Domain 覆盖 | 237/237 行、82/82 分支，均 100% |
| 资金与权限反例 | 真实资源/预留仓储、实际 owner HTTP 路由；七张财务表前后不变，检查审计与草案边界；合成来源端口不算真实来源验收 |
| 类型 | 22 个生产文件增量 mypy 及默认全库债务均 0；未修改债务基线 |
| 格式/lint | 全部 28 个修改 Python 文件 Black、isort、Ruff 通过 |
| 正式生成与专项合同 | 12 个官方命令通过；模块地图、Data Center 两项清单、测试分层、TUI bundle；92 个 current-data 合同、模块循环、完整架构/audit、Web 迁移清单检查 |
| 增量架构与文件增长 | 22 个修改生产文件、4,830 条新增行的边界/audit 违规均为 0；文件增长门禁通过，最大 999 非空行 |
| 浏览器 | 3/3 通过、0 failure/skip；仅证明 401/403/404 及 reset 后清除旧预览和 raw，不算新风险字段正向业务或实际账户验收 |
| HTTP 与恢复 | 最终原生测试 0 未模拟 Requests/HTTPX 请求；3,054 个已载入仓库模块按候选/基线 hash 核对；10,385 文件完整恢复，无额外 Python、恢复失败或遗留自有子进程 |

此前 integration-2 的 577 项组合运行中，572 passed、5 failed、2 teardown errors，不能称整组通过。其中未变动的 TUI 信息架构、task-focus、workbench、terminal agent、内部 SSL 及旧服务/网关回归已通过；最终修订针对失败的 HTTP、类型和相关旧测试重新验证，不把它写成新的 577 项全绿结果。未修改的 SDK 客户端另有 23/23 通过，1.47 秒；该模块有测试自有的 loopback HTTP 服务，未套用 M1 外部 HTTP 守卫。

## 失败与修正保留

- 数量初诊 15 项通过但覆盖不足，不接受为最终结果。
- integration-1 有 26 项失败及 26 个 teardown 错误：错误关键字、行情 patch 位置、旧测试缺显式策略资料及事务夹具等分别修正；未为生产添加猜测默认值。
- integration-2 的五项失败包含错误的缺价方向断言、三股清仓报价夹具、方向未触发的原因字段断言，以及预留夹具误耦合 Fee V2 registry 写入。保留真实预留用例/仓储，注入 typed 费用读取端口，使用适合本测试的回滚夹具；未削弱数据库时钟守卫。
- integration-3 的 122 项全部通过，但三个生产文件有八项类型错误，因此整轮仍失败。随后只收窄可空类型、状态 Literal 和局部变量名称；最终四模块重跑、增量类型及全库债务通过。
- 旧相关测试文件的格式调整保持整份 AST 相同。准备 manifest 的 hash 拼写错误在 overlay 前发现，原件及显式修正保留，不能改写成业务测试失败或通过。

## 原件与剩余工作

完整原件只在本机忽略目录：`artifacts/ash-m1-readonly-rebalance-preview-2026-10-22/evidence.zip`。

- ZIP SHA-256：`156f265085eb0abcae4cb11042aed28d40e35bc1eb01586a8eb90592a53b02dc`，458 个成员；`INDEX.json` 逐项记录路径、大小和 hash，解包复读核验通过。
- 保留最终与失败候选、命令、日志、JUnit、覆盖率、类型检查、隔离恢复和运行脚本；不含缓存、凭据、数据库或完整工作副本。未声称远端已持有原件。
- 新提交常规 CI、最终同 SHA RC/S6、生产部署与实际用户验收尚未完成；不得拼接历史绿灯作为新 SHA 发布资格。

Owner 选择生产模拟账户 613，并授权 Root 自定只读验收目标。生产只读核验显示账户无持仓、启用策略/仓位规则为空，目标查询所得发布行情已陈旧；正式 `stock_basic` 来源链也未覆盖 510300.SH 的 ETF 身份。原先 ETF 10% 方案未激活；首轮改按合格来源选择普通 A 股 10%、其余现金，代码在来源合格后确定，仅用于流程验证。没有把空表、全阻断、管理员查询或合成正例记作 M1 通过。

后续先补现有来源捕获的实际编排与 fenced finalization，再核对真实行情、身份、费用、数量规则及明确目标，通过普通用户实际入口完成同候选九项 M1 检查。ETF 主数据另行补齐；完整 ASH-03/04/07/08、M2/M3 及 Goal 均未关闭。


## 新提交 CI 的测试引用修复

`6ce511b9b261280ad1e1c901e4527d441211e6e3` 的 Fast Feedback 增量 job `119696932572` 中，bundle 检查之后的完整 Node 测试为 183 passed / 1 failed。生产清屏 helper 已从 `clearFullScreenReadState` 重命名为 `clearFullScreenActionState`，一个未同步测试仍在两处调用旧名，出现 ReferenceError。修复仅同步这两个测试引用；生产代码、断言、bundle 和 manifest 均不变，没有增加兼容别名。

在精确 6ce 隔离源码上修复后，完整同范围 Node 套件 **184/184 passed，0 failure/error/skip，173.029 秒**（本地 Node v24.18.1；不是 Linux Node 22 CI）。10,403 个基线文件恢复一致，零额外 Python 或恢复失败，自有测试进程结束。Manifest SHA-256 `ff41659f3b33044d20dae27d6fe45da1c99b9a4edefebe839674f13535fb6600`，receipt SHA-256 `eac740399a3f03b9bff2e9a7d8c44c3471c6cf74a957d861432d47f3b5fb30e8`，候选测试原始字节 SHA-256 `faf10caab9e1e729ad1d41fddce80770fbe1d3355536045a5796ce632d51336b`。没有生产 Python 修改，无需重复生产类型检查；新提交仍须跑其自身 CI。

同一 6ce 的原完整 NoDB 选择实际 **13,031 passed + 24 subtests**，pytest 84.48 秒、wrapper 94.75 秒，原 120 秒预算通过；未采用性能候选、减选或提高预算。一次结果不证明稳定性能或优化因果，历史 bf 预算失败保持原记录。

本事项原件目录追加 `artifacts/ash-m1-readonly-rebalance-preview-2026-10-22/ci-reference-fix/`，保留两个 CI job 原始日志、修复候选、脚本、JUnit、命令及恢复 receipt。`INDEX.json` SHA-256 `85b2313758397197042975cc42b80c096d1ac41988698561c1114de93c0bdf40`，逐项复读 hash 验证通过。本机原件没有上传声明；原业务 ZIP 原样保留，未为两处修复另建 ZIP 或验收状态表。原 6ce Fast 失败不被后续本地通过改写，实际 M1 和发布仍未完成。
