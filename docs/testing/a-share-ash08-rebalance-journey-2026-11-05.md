# ASH-08 模拟账户调仓与 TUI 用户旅程验收

状态：ASH-08因同日来源转blocked_external；原Goal当前blocked、未完成。业务代码及 CI 修复已正式提交并推送，当前代码提交 `ddf16e6d844952409261fd7e9117c52c02fbc5ba` 的五项适用 CI 已实际全部通过。Native 完整整链路、事务/并发、类型和前端均有各自完整通过及未变覆盖输入复用证据。剩余退出仅为合格同日来源上的显式收盘模式及 V8 普通 Owner 完整浏览器验收。

11/07 Owner已开放REF-02首批兼容/事务/恢复窗口，registry v313登记REF-01 completed、REF-02为唯一active整合焦点；ASH-08来源资格恢复后优先串行续办，当前来源/显式模式/V8退出未通过。最新排期见主计划§19.160与收敛计划§2.4。

## 当前实现工作与最近验收身份

- 计划绑定账户、持仓、报价、来源、风险、费用、结算和日历证据；执行仍走普通 Owner 每笔显式预览/确认及锁内重验。未成交 SELL 不提前释放风险或买力，后继版本按真实已成交与账本事实重算。
- 计划级 SELL、部分模拟成交、撤销、后继版本及 BUY 预览/确认已在 R063 Native funding 模块通过一个完整集成用例。该 Native 夹具用于验证数据库事务与执行链，不等于当天公开来源资格或普通真实来源浏览器验收。
- R063 初次三模块共 27 项，26 passed、1 failed；该轮 Native execution 模块不计完整通过。R064 修正测试时钟后，Native execution 完整模块 5 passed / 0 skip；R063 的 sell-buy funding Native 模块 1 项与 portfolio revision asset identity 模块 21 项仍是各自完整通过记录。
- 当前 21 个生产 Python 文件均有增量类型证据；R063 Guard 增量 mypy与全量债务均为 0。R064 的 isort、current-data、architecture-delta、headroom 和 module-map 五项门均为 0；复用的 R062 full architecture、Data Center inventory 与 broker scope 检查也为 0。R065 只做 Black 格式化，AST 等价证据留在 R064 原件中。
- R053 TUI 四个完整模块 143 项与 Node 14 模块 230 项均通过；R057 AUD05 PostgreSQL 竞态模块 20 项通过。R061 四个 preparation/support 模块合计 50 项通过，但同批 Native 模块失败。R062 的六项结构/专项检查无失败；freshness 契约三条测试引用已修正，并由 R064 current-data gate 以零违规通过。
- R051–R059 及后续各轮的完整模块结果均按各自候选身份留存；跨候选汇总不等于同一候选全绿。详见 ignored 原件与候选索引。

- SELL 只按已配置步长向下约束计划办理量，目标推导的非整股差值留在不可变证据中；手工 actionable 数量仍严格校验。TUI 分开解释本版本办理上限、未纳入办理量及未知差值。风险暴露或来源未知仍阻断，不从 SELL 顺序推导全部 BUY 的现金依赖。
- ConfigCenter 在 generated_at 相同时按 profile_version 确定最新运行快照，完整 PostgreSQL 组件与真实竞态均在 R057 通过。旧 Pulse 展示分数只在计划证据中使用显式可逆 hex 标签，其他财务浮点和非有限数仍拒绝；公开 Preview DTO 不变，计划 basis 的 opaque evidence string 可观察该标签。
- Domain 数学模块综合覆盖率 97.5669%；其 R051 源码与测试输入未变。R053 前端 338 项与 R057 ConfigCenter 81 项覆盖输入亦已逐项核实 SHA 未变；只复用该范围的原证据。

## 历史有界证据（仅适用于记录中的候选）

| 完整事项 | 实际结果 | 证据范围 |
| --- | --- | --- |
| 后端、Native、API、SDK/MCP 与 terminal-agent：29 模块 | 527 passed / 0 skip | R009；Source39 历史基线，当前隔离变更另由 R022 验证 |
| TUI 元数据、投影、scope、工作台：4 模块 | 442 passed / 0 skip | R010 历史候选；不再主张当前字节相同 |
| Session-only 正反边界：完整模块 | 2 passed | R011；真实 token 拒绝、真实 Django Session 到达执行器 |
| 完整前端：14 模块 | 229 passed / 0 skip | R021 历史候选；不代表当前 metadata 输入 |
| 旧计划隔离与 Native 交易链：11 模块 | 78 passed / 0 skip | R022 历史候选；不是当前完整金融正向验收 |
| ETF 报告时钟与 runtime 守卫：2 模块 | 23 passed | R029；真实拒绝瞬时时钟，守卫规则不变 |
| 浏览器契约 | 3 passed | 正常确认、HTTP 未知、transport 未知；受控响应，显式同键回读 |
| 生产 Python 增量类型 / 全量债务 | 基线 53 文件；本轮 8 文件及后续 1 文件零新增、全量债务 0 | R010 / R022 / R029，分别记录真实源身份 |
| Domain 覆盖 | 综合 90.8%，行覆盖 95.34% | R009 历史 Domain 输入；不能外推当前 WIP |

R009 至 R029 的旧通过数和覆盖率仅是各自历史候选证据。R051–R063 的模块级结果同样按运行身份分别记录，不能拼成当前整单元通过；R063 的完整模块状态与 Native fixture 修复见上节。

正式交付包含 QMT 可移植修复 `e706a5579`、配置同钟快照修复 `cbf976a29`、ASH-08 业务提交 `6f459d7d9` 与 CI 精确修复 `ddf16e6d844952409261fd7e9117c52c02fbc5ba`。业务提交的 Python 3.11、3.13、无数据库 TDD、PostgreSQL contracts 均实际通过；后继仅修 scanner 的固定夹具标识误报和测试字面量 lint，21 个生产输入不变。精确例外保留 path+whole-line AND 及越界反例，不放宽通用扫描。后继五项正式 CI 已逐项查询全成功：[Consistency Check](https://github.com/guiyinan/agomTradePro/actions/runs/42096287809) / [Engineering progress dashboard](https://github.com/guiyinan/agomTradePro/actions/runs/42096288025) / [Security Scan](https://github.com/guiyinan/agomTradePro/actions/runs/42096287649) / [Architecture Layer Guard](https://github.com/guiyinan/agomTradePro/actions/runs/42096287796) / [CI Fast Feedback](https://github.com/guiyinan/agomTradePro/actions/runs/42096287836)。原失败与本地修复原件继续保留；不把旧 CI 或候选片段外推新代码。

新 revision 使用独立持久 contract family。旧 canonical/Decision workspace 的读取与审批拒绝新 family 或旧 marker 行，最新旧计划查询不会被新计划遮挡；`0028` 仅登记模型 choice/state，不改既有流水、批准状态或自动重分类。旧 canonical 行若已丢 marker，现有列无法恢复身份；仅已核查的两个验收库当时无计划行，不外推其他库。失败时停用新入口并保留异类行，不自动降级或改写历史记录。

## 真实来源与剩余退出门

2026-11-06 16:01至23:47共九次有界同日查询均返回HTTP 200、data=null、total=0，最后原件位于 `.tmp/ash08-journey-20261105/b-execution/capture-date/runs/attempt-20261106-234713/2026-11-06/`；响应SHA-256始终为 `3098a203d487b1886e8a50e92f991e397e1b3d9351f8ec9cee118a2b15e0f3d9`，没有行业成员准入或V8执行。11/07复核成功11/03原件的116行及两银行唯一行，并确认当前官方明细JS与原归档字节相同；成功/失败请求仅dateStr不同，未发现参数缺项。成功响应的sampleDate同样为空，资格依赖逐行tradeDate及真实回执；不能把页面默认日期、HTTP Date、汇总PE或旧成员记录当作当前资格。

留存的Tushare交易日原件明确11/07、11/08为closed，11/09为open；该日历publication在11/04即过期，只作保守排期，不构成当前日历资格。现有ash-goal监控已改为周一至周五上海16:00后唤醒，下一候选为11/09 16:00；节假日、临时休市及当时有效日历仍走原门，不由工作日规则直接放行。已允许显式published_close模拟，不再统一等盘中正例；模式及完整V8仍须实际通过。国证发布说明仅承诺交易日收盘后更新，不能据此虚构精确发布时间；前端previousTradeDay接口也不是行业发布时钟。[官方说明](https://www.cnindex.com.cn/files/syljssm.pdf)

11/06窗口前已把现有隔离快照按c206b40对齐8599项覆盖输入（其中八个相关生产文件先前过旧），复用现有Native库，只读确认canonical M1为0行、2个不可变触发器、570项迁移，未建库。真实空白浏览器及本地HTTP trace、保留原字节的ZIP封装与既有解析器已通过；V8整文件collection及13-App限制下所需reverse/resolve亦通过，未运行金融/来源fixture或完整用户旅程。原IPC目录缺陷猜测被排除（v2已有parents=True），URLConf疑点未复现，因此未改启动器、路由或available_apps。完整失败探针及原件留在原忽略目录，不算V8正向验收。

元数据提交c206b40的五项CI已实际全部成功；Fast Feedback的Python 3.11、3.13、无数据库TDD和增量质量任务亦均成功。这是该精确提交的历史观察，不外推新候选。原件为 `.tmp/ash08-journey-20261105/idle-preparation/validation/ci-latest.json` 与 `ci-fast-feedback-complete.json`；[Fast Feedback](https://github.com/guiyinan/agomTradePro/actions/runs/42134575939)、[Consistency](https://github.com/guiyinan/agomTradePro/actions/runs/42134576025)、[Architecture](https://github.com/guiyinan/agomTradePro/actions/runs/42134576023)、[Security](https://github.com/guiyinan/agomTradePro/actions/runs/42134575900)、[Progress](https://github.com/guiyinan/agomTradePro/actions/runs/42134575902)。

本机诊断与启动准备索引继续附在同一事项下，不声明远端持有；它们不构成整单元关闭。

| 原件索引 | SHA-256 |
| --- | --- |
| `.tmp/ash08-journey-20261105/b-execution/source-contract-diagnostic-20261107/contract-check.json` | `ec506caadf1217a939beb72ef38b3cd398d7f8f094ed33326b0c39cb84f6218c` |
| `.tmp/ash08-journey-20261105/browser-qa/output/pre16-20261106/readiness-index.json` | `df9d6ca98bd6876e8434d9ae68e7d04817ad5a1d70d803c366726a762314c281` |

当前剩余退出项：

1. 行业分类使用能证明覆盖验收业务日的国证分类版本或同口径完整有效变更链。收盘报价单独采集，并将合格容量／会话、M1 原件和有效日历绑定同一候选。实际上海日期 16:00 后采集收盘批次，来源观测时间及有效期按原件校验。
2. 在符合上述真实来源条件的候选上，复验显式 `published_close` 的 V8 权限、原键回读及账本。隔离模拟结果见下节。

当前不向Owner索要外部材料。Goal仍active、未完成；Owner于11/07明确开放REF-01实施窗口并串行交接当前repository focus，详见收敛计划§2.3；REF-05仅只读，其余REF无新窗口，ASH-06/09/12仍deferred。

## 2026-11-09 行业来源资格与历史回放

11 月 9 日上海 16:07，隔离库日历前置通过。国证个股市盈率明细返回 HTTP 200、`data: null` 和 `total: 0`，当次采集未取得可用于提取行业字段的明细行。该结果只描述市盈率查询。

- 当前国证接入采用 `policy_bounded_date_snapshot`。生产资格检查要求源观测日、决策业务日和单日有效区间一致，并核对原始响应、接收时钟及配置绑定。该模式没有要求提供精确的官方发布时间。现有通用来源时钟路径可处理覆盖决策日的成分区间，前提是来源可得、系统已知、有效期、用途及供应商分类版本都有证据。 [日期模式](../../apps/risk_center/application/portfolio_risk_date_snapshot_clock.py) · [成分区间](../../apps/risk_center/domain/portfolio_exposure.py)
- [国证官方分类结果目录](https://www.cnindex.com.cn/zh_information/data_resource/fljg/) 的 2026 年 6 月工作簿有 6,263 条分类记录。`600036`、`601398` 各匹配唯一一行，三级行业均为 `C070101`。原表没有逐证券的生效、失效或后续变更记录。该文件证明该版本的分类，无法单独证明 11 月 9 日仍有效。下一可执行入口是取得同一分类口径的有效期原件或完整变更链，再经既有严格时钟路径验收。Tushare 的 [申万行业成分](https://tushare.pro/document/1?doc_id=335) 有纳入和剔除日期，分类体系与当前策略绑定不同，须独立定版并验收风险暴露差异。
- 复用 11 月 4 日封存原件，现有准入解析器生成 8 份干跑清单，覆盖两只股票的行业成分、估值、容量和会话状态。保留原始响应哈希和接收时间，无持久化。日期证明与行业暴露共 49 项通过。独立 PostgreSQL 测试库的收盘模式浏览器 2 项和权限、部分成交、撤销、后继 BUY 与账本组件 3 项均通过。浏览器与账本组件使用受控测试输入，和历史原件干跑分别记录。首轮浏览器持仓卖出失败定位为临时策略表切换后的 Django 列别名缓存，测试夹具在进入及退出临时表时清理缓存，复验两例同进程通过。

后续真实联验须将合格行业成分、当日收盘报价、容量／会话、M1 原件及有效日历绑定到同一候选和原时限，跑完显式 `published_close` 的完整 V8 顺序。验收原件、初次失败、复验、浏览器 trace 和输入身份统一见本机 `artifacts/ash08-historical-readiness-20261109/validation-index.json`。

### 11 月 9 日分类与行情分开取证

真实 V8 的行业入口改为分类原件准入。接受注明验收业务日适用的国证分类版本，或能从基准版本推演至验收日的同口径完整变更记录。核对发行方、分类体系和版本、证券身份、分类代码、适用区间、可得和接收时钟、原件哈希。旧 `queryStockSylDetail` 采集入口仅供历史复核，退出后续行业验收。来源准入沿用既有时钟与覆盖门。

- 国证公告确认 2026 年 6 月分类版本于 6 月 15 日实施。国证银行指数 `399431` 的 11 月 9 日样本表有 30 条，包含招商银行和工商银行，行业列为「金融」。编制方案以国证二级银行业作为入选条件，样本定期调整。样本表可旁证银行分类，仍缺验收日直接分类或覆盖至该日的完整变更链。 [分类更新公告](https://www.cnindex.com.cn/zh_information/notices_news/2026/202605/P020260529676473592135.pdf) · [指数编制方案](https://www.cnindex.com.cn/docs/gz_399431.pdf) · [当日样本原件](https://www.cnindex.com.cn/sample-detail/download?indexcode=399431&dateStr=2026-11-09)
- 单独取得两份新浪行情原件。供应商标记的观测时间均为 11 月 9 日 15:34:59，招商银行 43.01 元，工商银行 8.61 元。原件用于来源核对，真正续验时按现有时限重新取得仍合格的收盘快照并完成容量、会话、M1 和日历准入。

分类入口仍受阻，真实 V8 未启动。下一触发点是取得两只股票覆盖验收日的直接分类记录或有效变更链。原件、请求范围和哈希索引仅保存在本机 `artifacts/ash08-source-split-20261109/validation-index.json`，SHA-256 为 `2185b7865365cc0c9bfc1418803b3dae7e4d05ed278378474f8f5bdcc726133a`。

### 真实 V8 测试方法和启动记录

1. 固定验收业务日、候选提交和隔离 PostgreSQL、缓存、任务通道与浏览器端口。分类和行情各自留存原始字节、SHA-256、供应商观测与本地接收时间。分类应覆盖两只证券的身份、国证版本、三级代码和有效期。收盘快照按现行时钟核对，并绑定有效日历、容量／会话、M1 发布和费用、结算规则。缺件或过期时记录稳定原因并停在前置。
2. 全部准入后，普通 Owner、observer、foreign 使用同一冻结候选和独立浏览器会话。Owner 从实际 TUI 入口以显式 `published_close` 创建计划、提交复核、预览单笔订单，再以预览返回的原订单键确认和回读。用明示的合成成交事件经正式 Fill UOW 验证部分成交、撤销和后继买入。对账现金、预留、持仓、费用、回执和原版本绑定。observer 可读风险、计划和对账，写操作被拒。foreign 读取被拒且不返回私有标识。核对未授权请求前后的账本。
3. 保存三份 trace、transport 与 order key 绑定、JUnit、退出码、候选前后身份和原件哈希。失败证据留在原运行目录。复核 API、SDK/MCP 契约的已有覆盖，按未变源码、配置和输入身份复用证据，变更部分补做定向验证。合格真实来源上的同候选旅程、账本和适用检查全部通过后才更新整单状态。既有模拟验收按封存身份复用。

11 月 9 日已启动真实 V8 的来源前置，逐份回读分类与行情原件并核对哈希。分类返回 `NO_VERIFIABLE_CLASSIFICATION_VALIDITY_FOR_ACCEPTANCE_DATE`，先前报价收件也已过现行时限。退出码为 2，浏览器阶段未启动。本机启动记录 `artifacts/ash08-source-split-20261109/real-v8-start-20261109.json` 的 SHA-256 为 `011727760b0d565905740f159c1f436f3615fe61bcafdd7baa1566d6911c5cd4`。

收盘行情可独立做只读原件校验。使用隔离测试 settings，候选只需 `business_date`、`unit_mapping` 和 `sina_quotes`，报价条目仍绑定各自的原始字节、接收回执、证券映射和单位证据。

```powershell
python -m tests.support.ash07_public_risk_sources --quotes-only --candidate artifacts/ash08-source-split-20261109/quote-admission/quote-only-candidate.json --output artifacts/ash08-source-split-20261109/quote-admission/quote-manifests-replay.json
```

11 月 9 日两份真实行情生成了六份 dry-run 清单，覆盖估值、单会话容量和会话状态。把容量起点改成另一业务日后，校验拒绝且未输出清单。报告未检查分类、当前身份和时限，数据库未写入。只读行情报告 SHA-256 为 `df08ec072be0cd6d8cc63702f90f3df7e4bd8e2ed257ab7cdccf0d8570f2e986`。

## 2026-11-09 V8 隔离模拟验收通过

按 Owner 批准的测试假设，招商银行和工商银行沿用国证 2026 年 6 月工作簿中的 `C070101`。第 19 次候选在隔离 PostgreSQL 内发布受控收盘价，用同一份 `published_close` 发布记录贯穿三个普通用户浏览器会话。旅程通过浏览器发起真实 TUI 动作请求，成交使用明确标记为 synthetic 的事件并经正式 Fill UOW 入账。

- Owner 从账户列表生成第一版，提交人工复核，以原订单键确认并回读卖单，成交 100 股后撤销剩余预留，再对账并生成第二版。第二版买单预留 100 股，成交后账面现金为 1,497.48 元，买单预留占用 1,010.02 元。第一版回读保留原身份、依据和订单绑定，状态反映已提交复核。
- observer 可读风险、计划和对账，确认提交复核后收到 403。foreign 读取风险和指定计划均收到 403，未返回计划原键。未授权请求未产生订单或成交写入。
- JUnit 为 1 通过、0 失败。三份浏览器 trace、候选开始与结束身份、原键哈希、账本和早期失败日志已登记在本机 `artifacts/ash08-approved-simulation-20261109/validation-index.json`，SHA-256 为 `55988fc81e62aed730f50b6cf9aacda5cdaaca4067264affd71bf7567ede496c`。模拟验收已收口，真实来源退出门继续由本页上一节记录。

## 边界与原件

REF01仅按11/07新授权实施既有差值门和所需单族证据；REF05保持只读，其余REF无正式窗口不实施，原依赖及退出门不变。ASH06/09/12 保持 deferred。不部署、不写生产配置/账本、不启自动下单。

同名 JSON 索引已更新开发候选、模块与原件哈希；正式提交/CI 和来源验收后据实补齐。R064/R065 原件与格式等价证据继续留在 Git 忽略目录；候选间不得拼接通过。
