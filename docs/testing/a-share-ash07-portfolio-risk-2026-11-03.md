# ASH-07 模拟组合风险开发交付与剩余退出门

2026-11-04。ASH-07 与 Goal 保持 **active**；本记录是开发交付，不是整单元关闭或生产资格。范围与状态以主计划 §19.157、registry 为准。

已实现版本化行业/ETF 暴露与未知残余上界、量/额窗口容量、真实现金/持仓/有效预留/拟新增订单的保守投影；计划与普通模拟入口复用政策、来源及账户占用重验，未成交 SELL 不释放暴露或买力。沿用现有账本、RiskPolicyAudit、Scenario 和证据存储；TUI 可选审批情景、确认压力分析并回放原报告。

### 数据库策略

Owner 授权设计多套策略并写系统数据库。实际开发 `db.sqlite3` 已通过 ConfigCenter 通用建档入口创建三套 v1 DRAFT，数值保存在数据库及外部输入数据，算法没有财务默认值。

| 名称 | 行业上限 | 单票上限 | 成交参与率 | 行业覆盖下限 | ETF 覆盖下限 |
| --- | --- | --- | --- | --- | --- |
| 稳健 | 25% | 10% | 1% | 100% | 95% |
| 均衡 | 35% | 15% | 2% | 100% | 80% |
| 进取 | 50% | 20% | 5% | 100% | 40% |

范围限六个既有模拟账户，账本 CNY、容量 share、单 session 累计量。现有 DATE 年龄 45 天与 timestamp 86,400 秒均是政策数据，不能覆盖更严格的来源、当日及用途门。ETF 40% 数值门不解除报告层已有 PARTIAL/未知残余限制，也不使 Q3 季报自动可用于决策。

实际增加 1 definition、3 profile、3 value、3 revision；重复创建返回 created=false。新增 snapshot=0，原有配置行、活动指针及账本未改，一致备份已留。source pins 尚未齐备，三套仍不可执行；修改须创建新版本，后续只通过 active successor patch 替换 Risk key，不能激活仅含 Risk 的 profile 覆盖其他配置。

### 来源时钟与普通执行用途

Owner 允许非影响性的 unknown。现已交付逐来源显式、仅限模拟的三种时钟证明：当日 bounded 行业 DATE 快照、带真实时间戳与单位的估值/单 session 容量快照、经现有 ASH-03 UseCase 资格验证的收盘报价时点状态。未选择模式仍要求原供应商时钟。

供应商 `available_at/valid_until` 保持原始 None；独立记录真实完整收讫时间与政策接纳截止。截止取观察年龄、当日、政策、日历与收盘限制的最早值，不把量窗结束日或报告期当供应商失效期。证明绑定账户、资产/证券、配置版本、snapshot、manifest pin、原件哈希及 cutoff；报告、计划、预留及成交重新核验。来源权限、禁止标记、缺失观察/金额/单位/覆盖等门不放宽。Sina `00` 仅作报价时点供应商状态，完整交易日/交易所停牌状态仍 unknown。

准入 manifest v2 保留完整接收回执及原 Sina transport metadata；Reader 从相同原件重建 exact capture，provider 不重新联网或构造假订单。报告按类型、资产/证券、记录 ID 比较当前 policy 与 Reader 的完整引用；manifest hash 与供应商 body hash 分别验证。

凡本次风险证据带收盘用途或 `close_snapshot_only`，订单实际行情用途必须是收盘模拟。签名预览、锁内预留、幂等查询及并发 writer 分支、确认/恢复和成交读取同一持久化用途，不能给旧订单换用途。普通充分合格来源仍可用于收盘市场，不以两个不同 purpose 枚举强行双向相等。TUI 分开展示供应商未知时钟、已证实收讫与有限接纳截止。

### 验证与复用边界

| 范围 | 实际结果 |
| --- | --- |
| ConfigCenter 建档事项 R39/R41 | 101 项原生配置回归、6 文件增量及全库类型债务 0；投影修复与原始失败保留。 |
| 时钟/用途 R46 静态 | 11 步通过：40 文件增量 0、全库债务 0、Ruff/Black/isort、架构/循环、模块图、TUI/current 契约、正常 settings/同一 Kombu Queue 对象。 |
| R46 完整回归原件 | 2188 passed、12 failed、1 skipped；该轮不是全绿。失败集中在两个新时钟测试文件的嵌套哈希与校验对象夹具。 |
| R48 完整时钟专项 | 23 个文件入口、322 passed；覆盖来源/精度/权限/单位、期限及边界篡改、报告 codec、Reader、普通风险 service、准入和 TUI。 |
| 核实复用 | R48 与 R46 的 40 个生产文件及其余 137 项冻结输入逐哈希相同，仅上述两个测试文件改变并完整复验；复用 R46 已通过的原生 API/匹配/并发、Owner TUI Scenario 原报告回放、账本/权限及四项高风险回归。未把两轮拼成一次完整全绿。 |

同一生产字节的 R46 实测 Risk Domain 行覆盖 90.33%（6421/7108），预留 Domain 96.74%（326/337）；不是夜间 branch readiness。R45 的 27 项失败/类型诊断、R46 的 12 项及 R47 的 2 项失败原件均保留。合批复用同一原生 PG schema，没有重建库；未变前端 JS 的既有 213 项证据可复用，没有重复运行无关前端组。

当前索引 `.tmp/ash07-risk-20261103/integration/clock-purpose-delivery-index.json`，SHA-256 `ea37017c227ad3ea9eee92c4ae15e6e6cb2b5ec5be84205b9bfdd695f8db95b2`。包含各候选、命令/日志/JUnit/覆盖、失败、源快照及精确复用关系；旧业务、来源和数据库策略索引仍被引用。提交后 CI 独立查询，以 `.tmp/ash07-risk-20261103/integration/delivery-ci-observed.json` 的实际 HEAD 回执为准，不以本地结果替代。

### ETF 披露来源与报告期年龄（2026-11-04）

显式 `policy_bounded_disclosed_report` 已贯通 policy、准入 manifest v2、保留原件 Reader、报告/Scenario JSON 回放、当前账户/配置重绑与执行截止。独立保留 PDF 和官方公告 HTML 的 body/hash/完整收讫回执；页面须给出可见发布日期并链接同 HTTPS origin 的精确 PDF。报告期末、发布日期和接收时间分开，供应商 available_at/valid_until 仍为 None。报告期年龄、发布日期年龄、业务日及现有政策边界取最早截止；未知覆盖或禁止用途继续拒绝，PARTIAL 的时钟证明不解除金融覆盖/残余阻断。

既有 `ash07.simulated_portfolio_risk.v1` 支持可选 `etf_report={age_basis: report_period_end, max_report_age_days: <配置值>}`，无生产数值默认。开发库三套草案已新增数据版本 2，报告期年龄显式为 45 天，其余版本 1 参数与空 source pins 不变；旧行、snapshot/active 与账本未改，仍是 inactive DRAFT。新鲜一致备份及逐旧行校验在索引内。

本事项后端 `38bd6a21b6`、TUI `93a718c726`；R54 候选 `163fd94dcf2d2bfa7d2ba6212c7fc07f305d44b84da3499c1e271280e6b1118c` 的 10 文件 113 项通过，新增证明行覆盖 152/157。18 个生产文件与 R52 完整静态门禁相同（增量与全量 mypy 均 0）；R49 未变结构/TUI/current-data 门禁、R51 相同覆盖的 Native 压力回放与四项高风险包有界复用。R49/R50 中止及 R51/R52/R53 失败均保留，不拼成整库全绿。真实华夏公告/PDF 原件离线解析已通过，未将其当作当前金融正例。

原件索引 `.tmp/ash07-risk-20261104/integration/etf-disclosure-delivery-index.json`，SHA-256 `913b122f842d5f4b88bbd2598dc213eefdd065fb4898a7d73a5569a093818ab5`。推送后以实际交付 HEAD 的 CI 回执为准；本地验收不替代 CI。 `42d6cf846` 的两个 CI 门仅发现 Data Center architecture/entrypoint 生成投影过期；Python 3.11、3.13 与 NoDB 套件均通过。本次用既有生成器补齐两投影，生产代码未变，生成命令/原始失败及哈希在同一 JSON 结论内。

### 尚未通过的整单元退出

1. 当日真实来源的完整正向计划/普通模拟/压力旅程仍未实际通过。11 月 3 日行业与报价在 11 月 4 日只能作历史原件，不回拨政策激活/首次已知时间，不把旧报价标 fresh；允许合格真实收盘快照，不统一等待盘中正例。新 opt-in Source Owner 测试已正式交付，但未运行的正例不计通过；其日历/身份/持仓夹具边界明确。
2. 510050 Q3 期末 2026-09-30、发布 10-27，前十 44.56% NAV，余下 55.44% 未知；H1 的 94.78% 覆盖已超过拟定年龄。独立报告期年龄与有限披露时钟证明已交付；当前真实 PARTIAL/未知残余仍未取得金融决策资格，不能用两银行正例或当前分类回填历史持仓来代替。报告日期、发布日期与收讫日期须分开；既有 partial/覆盖/残余门继续。
3. 合格治理日历来源实例尚未接入。默认开发 SQLite 的 calendar catalog 缺 TTL 列；复用原生 source 库无活动合格日历 DatasetContract。未绕过目录调用带凭据服务。新增新浪原始日历响应列出 11 月 4 日，只是供应商计划日期成员证据，不能把缺席日期推为闭市或冒称完整交易所日历。两库诊断及原始抓取均在索引。

这些是后续自主来源/接线事项，不索要实仓或券商持仓凭证。REF-01/05 只读，其他 REF 依原依赖及正式交接；本批未实施 REF。ASH-08 整单执行/续办/重审批、ASH-06/09/12、生产配置、自动下单、部署和同 SHA RC/S6 不在本交付资格内。
