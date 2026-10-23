# 模拟账户只读调仓预览：有界开发交付索引

日期：2026-10-22。归属：[A 股实施计划 §19.96](../plans/a-share-usability-implementation-plan-2026-10-16.md#1996-m1-first-delivery)。这是 M1 的程序交付，实际业务验收仍开放，整单元状态只读 `governance/active_plan_registry.json`。

## 本批行为

普通用户从现有 TUI 选择本人模拟账户，调用既有账户巡检入口读取只读调仓预览。服务端先检查账户权限，再取得现金、活动委托占用及持仓的同账户快照。预览列出来源、目标、当前/可卖/差额/约束后数量、费用、现金、账户及策略各自的风险限制；缺证据的结果保留未知值和原因。

证券分类沿既有 V2 本地模拟当前参考合同读取，不按代码前缀猜类型，不清除嵌套来源限制或补写上游时钟。报价、Fee V2、Risk V3 各自核验。所有活动现金预留含卖出费用缺口；同计划有可操作卖出时，买入等待卖出完成后重新评估资金和风险，不提前释放容量。零股清仓保持真实股数，负卖出净额不截成零。

规则使用当前价格和实际账户估值重新评估。规则上下文不再合成 ATR、支撑位或风险参数；旧巡检同步复用此上下文，依赖缺失指标的表达式会按原有失败关闭路径受限，须补真实指标后恢复。

`reports[].plan` 是临时预览，不是持久化可执行 TransitionPlan。当前 R9 TUI 可提交本人账户选择及本次临时证券目标，省略 `auto_create_proposal`，依赖接口原有 `false` 默认值并拒绝注入该参数；巡检审计照常留存。没有新增模型、迁移、默认配置、自动交易、生产写入或部署。详细字段与行为见[接口合同](../api/a-share-readonly-rebalance-preview.md)。

## 首批候选与验证（历史记录）

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

## 累计回归的成本状态夹具修正

648 候选的累计 Python 3.11/3.13 回归均暴露相同八项持仓测试错误：fake position 缺少真实模型已有的 `cost_basis_known`。本次仅修改该测试文件，默认值与 ORM 一致为 `None`；断言已实现盈亏的历史部分平仓夹具显式标记成本已知，并增加更新操作保留未知成本的断言。生产成本、权限与执行检查不变。

在精确 648 隔离源码及原生 PostgreSQL 16 上，该完整模块 **13 项全部通过，零失败、错误或跳过**。候选原始字节 SHA-256 为 `65c3cf9f18f2ba41c26b8178fa85963f6a2831a77a1f2299fbd4019bbe1eef6c`，准确 Black 26.10.1、isort 与 Ruff 通过。该模块与来源捕获合批运行；整批实际仍为 91 passed、6 failed、4 teardown errors，因此只采纳这十三项的独立结果，不宣称整批或 M1 通过。没有生产 Python 变更，不重复生产类型检查。

本机忽略原件：`.tmp/ash-m1-source-completion-quality/integration-2/results/junit.xml`，SHA-256 `1b6ad8f789499e749013ff66e07fcb3214b4ca2397d35ad0b22ecc56bae56257`；同目录 `receipt.json` SHA-256 `83dcd50e276030ccfbe1fb31aaab73230fdf58e69ef895eff24e63f31feff77a`。原件记录绑定 manifest `4e71d80b35a33b83eb0c72c66d4a18507140dcd909037d5b2a27003bc6993ef1`、源码完整恢复及失败明细，未声明已上传远端。夹具输入与静态检查索引 `.tmp/ash-unified-position-fixture-fix/hash-manifest.json` SHA-256 `0610c24bd20f62f9db16eb157c25c37ad3dcef3bbf160252e51f47f529a50368`。后续累计 CI 与实际普通用户验收继续独立完成。

## 本地普通用户正向旅程

R8 在精确 `6486369d12db11476e2785e1b79bb7418d98e465` 隔离源码上完成 **1/1 passed，0 failure/error/skip，37.06 秒**。普通非 staff、非 superuser 账户持有人，通过实际 TUI 页面选择账户、确认并提交，进入真实账户巡检接口、投影和渲染链。断言覆盖可操作卖出、等待卖出完成的条件买入、数量、分项费用、现金、六项账户/策略风险限制及未知币种保留；七张财务表不变，巡检审计增加一条，草案增加零条，无执行操作控件。

这是使用合成 typed 来源端口与 Playwright→Django Client 单进程传输的本地开发验证，启用 CSRF 检查；没有证明真实生产来源、部署网络、生产账户 613 或独立人员操作。跨账户拒绝仍由原有负向合同覆盖；成功截图保留了预览内部滚动位置，不能据此宣称全部信息在首屏可见。没有把该诊断测试源码重复提交到生产测试树。

| 证据 | SHA-256 |
| --- | --- |
| R8 候选测试原始字节 | `24ea46dd6dfbbce6199e19ddfc73f3190884b3118cfafb50b678f1507d79ab39` |
| integration-7 manifest | `6596453eda1399582e202f23d9eb5f270a768e3ddc5a5665c1588d92234a08df` |
| integration-7 receipt | `11f6ef7d2c103407830deda3bda1b3bbf758d5e46ebab4afb55587b85461bb19` |
| integration-7 JUnit | `d7534f7ca741831350da6c8b9f14741326c5aa6da84dbcafaf891cb5a6ec1ffe` |
| 本机归档 INDEX.json | `c412b70dd37ffdb9abb3be882ea4702225381a37977c58dd23fddddd1855fde7` |

归档位于同一事项的 `artifacts/ash-m1-readonly-rebalance-preview-2026-10-22/positive-journey/`，181 个实际文件、187 条来源映射，候选按 hash 去重。逐项复读来源与目标 hash/size 不匹配为零；原 ZIP、CI 引用材料未改，没有新 ZIP。保留七轮实际运行和 R1–R8 准备记录，包括登录重定向、错误 import、隐藏容器选择器、旧测试库缺失迁移单例及字段 key/label 错误；失败不改写为通过。

最终使用正常迁移初始化的独立原生 PostgreSQL 测试库，未手工补旧库单例或关闭约束。3,125 个已载入模块按源码 hash 核对，10,403 个基线文件完整恢复；零未模拟 HTTP 请求、额外 Python、恢复失败或遗留自有子进程。归档不含数据库、凭据、环境文件、缓存、浏览器配置或完整工作副本，未声明远端已持有。`production_m1_acceptance=false`；M1 与同 SHA 发布验收继续开放。


## R9 临时目标预览整批开发交付（2026-10-23）

本批允许普通持有人给本次预览填写证券目标权重；已有策略只在通过本人账户授权后读取。无持仓、无已启用策略时，必须确认策略确实不存在，才能使用手工目标；查询失败或权限不明仍阻断。临时目标不写策略配置，不创建调仓草案或订单。现金、持仓、委托预留、来源、Fee V2、Risk V3 和七张财务表的检查保持；未知来源时钟、币种及限制不补成可用值。

结果首屏显示用途与源时点、目标及未分配现金、费用与现金估算、首项标的建议和适用限制，完整数量与审计资料保留在详情。请求由同一公开 Application 解析器规范化，并与返回的目标权重、未分配现金逐值核对；绑定不符时不显示计划。普通用户可返回修改输入。实际浏览器验证同时覆盖已有策略的卖出/条件买入与空账户手工目标买入；使用合成 typed 来源和本地真实 owner 路由、CSRF、生产投影及 Chromium，不代表生产 613 验收。

| 检查 | 本批实际证据 |
| --- | --- |
| 完整本地原生 PostgreSQL 回归 | Source R7：28 个完整模块，993/993 passed，0 failure/error/skip，655.95 秒；18 项诊断为其子集，不重复累计 |
| 类型 | 同一 27 个生产文件增量 mypy 及默认全库债务均 0；不修改 mypy 债务基线 |
| Domain 覆盖 | temporary_rebalance_targets：95.87% 行、94% 分支、95.32% 合并；rebalance_preview_math：行/分支均 100% |
| 浏览器主任务 | Browser R6：两个精确旅程 2/2 passed，77.06 秒；首屏五项 P0 均有实际视口断言，返回重填未新增请求 |
| 静态与增长 | 43 个 Python 候选 Black/isort/Ruff 通过；85 个新增/修改生产函数注解、公共 docstring 与增量边界复核通过，最大 996 条非空行 |
| 官方生成及专项检查 | 18/18 通过：13 个 Python 命令、TUI 构建/一致性/完整 Node 测试、两项接口/SDK 契约检查；11 项输出由官方工具生成 |
| 恢复与网络边界 | 10,403 个基线源文件恢复一致，额外 Python、恢复失败、自有残留子进程和锁均为 0；Node JUnit 原件归档且原路径恢复；Source 完整运行零未模拟 HTTP 尝试，SDK 自有受控 loopback 不冒称零网络 |

运行环境为本机 Python 3.13.5、Django 5.2.12、原生 PostgreSQL 16.15；不替代生产 Python 3.11 或新提交 CI。Schema 生成保留 5 项枚举命名警告、0 错误。新增 Terminal → Simulated Trading 公共 Application 依赖经独立复核后按实际图精确登记：206 条边、Terminal 出边 25、Simulated Trading 入边 5，零循环、零双向依赖、不新增循环例外。

| 身份 | SHA-256 |
| --- | --- |
| Source41：27 生产 + 14 测试 | `d8fb32b9db501512a462f28f26b1b7a9f72efbda8d813aa1f60f388861c9d8af` |
| Browser43：同一 41 文件 + 两旅程 | `6f71984b9ee1c4070c63ef0f73eb20c78366db66b78f0452eeda756678256a93` |
| Source R7 receipt | `3c37c154ceb6a57350364cbf4a60b3bdb59d2d12f2a6cf2d10734f740134219f` |
| Browser R6 receipt | `8514e329344669d7c555c9e34af37376cdd9433192e48d9a118db9396d1e438c` |
| 官方检查准备输入 | `7e013951ae295f662a750426e5a9744391334bc964d5395019807ffe9f801a30` |
| 官方 18 项最终 receipt | `cf295ee10645e74e7ae4a0d6329d0e71e65cbac2add1db996068ba42da2ec543` |
| 同一事项本机未压缩 INDEX.json | `71adfa18f9225ab5096acb8de63e861c25adbff5d46cfe1e3471c00ec9d0f312` |

本批整合父提交为 `cc4c62c3fdeaeac6f8b9ddaab828221648c0e31c`。原件合并在 `artifacts/ash-m1-readonly-rebalance-preview-2026-10-22/r9-business-delivery/`，不新增 ZIP；仓库仅保留本说明、代码、必要投影和专项合同。旧 ZIP、失败原件及历史索引保持，未声称远端已持有本机原件。

历史失败继续保留：旧 Source 完整运行超时、旧浏览器表单/数值断言失败；官方 R2 在 overlay 前因父投影输入/输出重叠受阻；R3 出现 MemoryError 中断及未登记依赖预算失败；R4 首次 Node 在任何测试前因缺少报告目录退出，次轮因来源报告命名未匹配而在文档八项通过后停止，R5 的 Windows 长路径根目录未统一也保留为失败记录。最终同一业务代码的 18 项检查全部重跑通过。冻结准备文件继承的旧静态摘要仍有旧 controller SHA 和 52/2 计数，索引明确披露；实际固定 controller 动态核验 50+3 个输入的父 Git blob/SHA，最终运行证据绑定其真实输入，不以旧摘要证明 53。

生产账户 613 仍待合格当前来源、实际普通用户非空预览及九项业务验收证据，`acceptance_evidence` 保持空；新提交 CI、同 SHA RC/S6 与部署继续独立验收。本批未部署、未下单、未写生产交易账本，不关闭完整 ASH-03/04/07/08、M2/M3 或 Goal。返回按钮的独立样式小修复另行提交，不混入上述候选资格。

### 返回按钮可读性修复（独立事项）

为实际渲染的 `[data-return-dashboard-workspace]` 补上既有按钮的普通与键盘焦点选择器，复用现有配色及焦点边框。只修改两行样式选择器，无业务或生成代码变化。隔离 Chromium 使用实际样式、按钮结构和 A/B/C 三种现有主题验证，文字对比度分别为 13.70、17.08、18.00，焦点边框均可见；已人工查看三张截图。此项为样式与结构验证，未重新运行完整业务旅程。

原件保留于本机 `.tmp/m1-return-button-contrast-preparation-r2/private-contrast-smoke-r1/`；receipt SHA-256 为 `8ba14380880d1811c4dc65568b095b620c742efed5e433fc1a748fdee8d0b2c5`。此修复独立于上述已冻结业务归档，不扩展其生产或发布资格。
