# ASH-08 模拟账户调仓与 TUI 用户旅程验收

状态：ASH-08 与 Goal 继续 active。业务代码及 CI 修复已正式提交并推送，当前代码提交 `ddf16e6d844952409261fd7e9117c52c02fbc5ba` 的五项适用 CI 已实际全部通过。Native 完整整链路、事务/并发、类型和前端均有各自完整通过及未变覆盖输入复用证据。剩余退出仅为合格同日来源上的显式收盘模式及 V8 普通 Owner 完整浏览器验收。

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

2026-11-05 23:33 的国证同日查询为空，未满足 11/06 同日行业来源门。11/06 16:00（上海）前不采集收盘来源；不得用 11/05 报价或旧行业原件回填成 11/06 当前资格。已允许显式 published_close 模拟模式，不再统一等待盘中正例；该模式和完整 V8 真实来源 Owner 浏览器旅程仍须实际通过。

当前剩余退出项：

1. 取得当前日合格行业成员、报价、容量/会话和 M1 原件，通过既有同日、用途、时钟和完整性门；11/05 的空响应不构成 11/06 资格，16:00（上海）前不采集当前收盘批次。
2. 用显式 published_close 模拟模式实际完成 V8 普通 Owner/observer/foreign TUI 旅程并对账，保留权限、原键回读和真实 transport/order key。部分模拟成交必须明确 synthetic 且通过真实 Fill UOW，不能冒称供应商撮合。

当前不向 Owner 索要外部材料。Goal 仍 active；REF-01/05 仅只读，其余 REF 暂无实施窗口；ASH-06/09/12 保持 deferred。

## 边界与原件

REF01/05 保持只读，其余 REF 无正式串行交接不实施；不改变依赖或退出门。ASH06/09/12 保持 deferred。不部署、不写生产配置/账本、不启自动下单。

同名 JSON 索引已更新开发候选、模块与原件哈希；正式提交/CI 和来源验收后据实补齐。R064/R065 原件与格式等价证据继续留在 Git 忽略目录；候选间不得拼接通过。
