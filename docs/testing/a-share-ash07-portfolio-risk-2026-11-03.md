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

### 隔离日历目录单键初始化（2026-11-04）

后端 `990c4645be` 新增公共 Application UOW/仓储/composition，仅创建目标键四表。完整精确重放不保存；部分/漂移历史拒绝；并发完整提交的混合读取可新鲜复读识别，混合新建/既有标志整包回滚，绝不补齐外部部分写入。未调用全目录同步器或改 canonical 十项键。

R56 候选 `c91b17643caf388f21095846ec86ed74653b2f41f36f041a67ae63708c380fee` 的 5 个目标共 52 项通过（0 skip，三种真实 PG 竞争），3 生产文件增量/全量 mypy0、格式/lint通过。R55 仅漏类型导入失败保留，结构/投影输入等价有界复用。已通过正式源代码公共入口在自有 Native source 库实际创建 contract/binding/policy/owner，预先保存并校验 4MB custom-format 备份；未重建数据库。Owner 的 D1/store/consumers 仅原件元数据，未冒称现有 ORM 持久化。

原件索引 `.tmp/ash07-risk-20261104/integration/calendar-bootstrap-delivery-index.json`，SHA-256 `c33ceecb615bc6b0f0deb8c4fe57a7c88b094667b0300c8d652dcabdec703a47`。只读审计实际 ProviderConfig=0，中心 token/mode/URL 已存在；Provider、时区、真实采集与带 session/CSRF 的发布仍待接线。目录就绪不代表当前参考日历或执行资格。ETF 前序 `13f9db16a` 五 CI 已通过，NoDB 首次超时保留、只重试失败 job、预算未改；本次日历提交须另看实际 HEAD CI。

### 真实日历来源、发布与有限消费者验收（2026-11-04）

前序代码 `3c9fadab2` 七项实际 CI 均通过。Root 在自有 Native source 中经已有公共配置及加密秘密入口将 Provider 0→1，配置与中心 token/mode/URL 精确匹配；随后真实请求 Tushare 全日期 SSE 范围 2026-10-26～11-13，保留精确原响应，不从 DataFrame 构造原件。以新建的隔离非 superuser 发布测试主体、唯一专用权限，通过真实 HTTP 登录与 Session/CSRF 执行工作台 prepare 201、confirm 201、current 200 published，未直写指针或伪造授权。

Native 原无 active profile/时区映射，且持久化 critical 定义集合为空；只为已声明的 SSE 范围注册现有 NORMAL 可选定义，并用公共预览/原子首次激活配置 `SSE → Asia/Shanghai`。未运行完整默认目录 reconcile、未替换其他 profile/交易所，也不代表完整系统运行配置资格。未来新增风险值须用保留此 map 的 active successor。

既有模拟交易日历消费者在实际 UTC `2026-11-03T21:04:42.255700` 通过全部验证，对应截止 `21:05:36.485273`；真实时间超过原 900 秒后，同一消费者明确拒绝 `CALENDAR_FORMAL_TTL_EXPIRED`。供应商源时钟仍 unknown，收讫/首次落库/发布时钟分开。当前这份参考已过期，后续真实风险旅程须正常重采/发布，不能延长旧元数据。此验收仅说明日历参考链路，不授予下单或整个风险判断能力。

实际 HTTP 发布对应的原件也按 public RawPayload 精确读归档；body SHA、manifest hash、record digest 分别保留。已有 `risk_center.0013` 双 Scenario 快照迁移只在已备份自有源库应用，没有新迁移或重建库。首轮输入标签长度/工具事务边界错误及随后真实正反结果均留存；未跨候选拼绿。原件索引 `.tmp/ash07-risk-20261104/integration/calendar-source-wiring-delivery-index.json`，SHA-256 `a1b2e2de1b2479fc0e04c7de0b068012ee86445677820379706156c5e580386a`。验收后已安全停止自有 HTTP/PG，保留 schemas 与全部来源状态。

独立 Owner 日历验收适配器与 opt-in smoke 已在隔离测试库实跑：R58 候选 `a8e4f412fab9d652bc7c77f00c77db0d7ba72805a8f5452df36c15cea9304393` 两项通过、零跳过、48.35 秒，包含真实 Tushare 采集、Session/CSRF 工作台发布、正式消费者的原件/manifest/record/时钟验证和历史日期拒绝门。isort、Black、Ruff 通过；生产输入未变，不重复其类型/架构验收。R57 首次 1 失败、1 通过，是辅助代码混比原始请求参数与规范日历范围两种哈希；修正为各自按对应材料校验，失败日志与 15 项精确输入均保留。原件索引 `.tmp/ash07-risk-20261104/integration/owner-calendar-adapter-delivery-index.json`，SHA-256 `9bd69699d7d8e0be6dbb1e6ba3a42079b2b346b976fed8fa80ae04efad811573`。本项仅交付日历适配器；新的 Owner 计划/普通成交及 ETF 调用仍在整合，不将未运行的金融正例计入通过。

### 多证券 M1 参考价完整开发事项（2026-11-04）

R66 候选 `eee6fcdd5310ee996abf494de7ba07a228be7a740825ee62cd6e6a1475c15848` 的四份完整 M1 batch/single 单元与 Native 文件共 37 项通过，0 skip。显式至少两个同日证券逐个精确同步，全部原件/run/ingestion 一一入同一候选，只执行一次既有 CAS；单证券 factory AST 与旧基线完全相同，严格单成员 writer 未改。新适配器按真实激活生命周期接受 CAS 前不可变 CANDIDATE 快照及 PUBLISHED 重放快照，拒绝 superseded/blocked。

Native 实际验证双证券同一发布公共读取、次笔采集失败不封局部候选、CAS 竞争保留获胜单票，以及首个真实质量恢复事件/outbox 已在事务内写入后，第二成员失败使本组恢复/发布审计及指针回滚。先前已提交原件/候选保留，旧 degraded 状态/current/outbox 不变。质量事件按状态迁移产生，不承诺逐 RawAudit 一条事件。provider 和完整权限 fence 为明示合成 fixture；这不是实际来源或整单金融资格。

最终修改 Infra 增量 mypy0、全生产债务0；另两生产文件与 R62 类型验收字节相同。R62 生成/一致性/架构/环检测证据有界复用：一处预期状态表达式 AST 变化，import/入口/签名/字符串及投影哈希未变。R62～R65 失败、候选和脚本均保留，不拼成跨候选全绿。原件索引 `.tmp/ash07-risk-20261104/integration/m1-batch-reference-delivery-index.json`，SHA-256 `2ea64dd219102a17bd717b3b4c633857c5b125dfebc613a83196469e121a157d`。

**M1 CI 后端选择修复。** `67e6b8bb8` 六项 CI success，Fast Feedback 的四项 Native 用例误入 SQLite 而失败（run `41745217176`）；5098 项通过和原失败日志保留。R72 以原生专用 marker 将四项从 SQLite 路由至现有 PostgreSQL CI，两份完整 M1 文件均显式入该执行 step；不只移出快速通道。CI 等效设置下 PostgreSQL 10 passed/0 skip，SQLite 四项按预期 skip（未改默认库字节），YAML 解析/目标校验通过。生产字节与 R66、结构/投影与已验证输入未变，未重跑无关门。索引 `.tmp/ash07-risk-20261104/integration/m1-batch-ci-remediation-index.json`，SHA-256 `208d0a7640896b0b9f0233538482537ce5f7dfec61d14332238e4285dba12e91`；新 HEAD `b906f2e9a` 六项适用 CI 已实际全部通过（Quote Metric PG 依精确路径过滤不触发）；原件 `m1-backend-routing-final-b906f2e9a.json` 保留。

### 尚未通过的整单元退出

1. 当日合格真实来源下的完整正向计划、普通用户预留/成交和压力旅程仍须实际通过，计划须产生正数拟卖出数量并与风险投影一致。多证券 M1、真实 Provider/Account V3/required Audit 来源能力已交付；当天国证空响应不能补造行业映射。允许合格真实收盘快照，不统一等待盘中正例，也不把 11 月 3 日原件标成 11 月 4 日 fresh。
2. 510050 Q3 前十覆盖 44.56% NAV，55.44% 未披露；有限披露时钟已交付，真实 PARTIAL/未知残余的保守金融验收仍须取得当天价格/容量原件并实际运行。两银行映射不能填补其余未知行业；不要求无法取得的完整 Q3 持仓来替代既有部分覆盖门。
3. 实际日历采集、授权发布、消费者正向与原 900 秒到期拒绝已通过；完整金融旅程仍须在有效窗口正常重采。多持仓同行业 Scenario 及三类受阻退出/当前页面验收已交付，详见本记录后续整事项，不再列为待整合。

当前无需 Owner 补实仓、券商凭证或新增业务决定。REF-01/05 只读，其他 REF 依原依赖及正式交接；本批未实施 REF。ASH-08 整单执行/续办/重审批、ASH-06/09/12、生产配置、自动下单、部署和同 SHA RC/S6 不在本交付资格内。

### 真实双证券 M1 来源能力整事项（2026-11-04）

R81 候选 `917a7ff8afca22572f37dcb5388c4d35d8b3b60c99f057bc22ff07606ee55b76` 在复用 Native TEST 库中完整通过：1 passed、0 skip、30.74 秒。真实 Tushare 日历工作台发布、两个银行的 11 月 3 日日线原件、实际 Account V3 授权和必需 SystemAudit、双证券同一 CAS 及公开 published-close 读取均实际通过。供应商发布/可用/失效时钟保留 unknown；本项是参考来源能力，不是当日风险或普通用户金融旅程资格。发布者是明确声明的隔离 staff/admin 测试账户，使用测试 Session，不冒充真实人工登录或普通风险用户。

完整测试使用真实受限 default runtime 登录，现有权限校验器实际通过；退出后管理身份、所有 relation/index/toast/sequence 所有者及有效 ACL 均与原快照相同，两个临时 UUID 角色已删除。保留已有库/schema及 generation clock，零其他客户端后停止 PG。R78 业务断言通过但清理校验失败仍保留失败结论；其原因是验收脚本把 sequence 默认 ACL 类型写为 foreign-server 类型，已按 PostgreSQL 原始契约改正并在 R81 整项重跑，未跨候选拼绿。R79 诊断和 R80 精确零依赖角色清理原件均归档。

测试、原件、候选及恢复证明统一索引位于 `.tmp/ash07-risk-20261104/integration/m1-source-capability/delivery-index.json`。生产代码字节与 R66 相同，类型/债务及不受影响的投影证据有界复用；只更新真正受影响的入口投影。ASH-07/Goal 继续 active：普通 Owner/ETF 的金融流程及同业多持仓 Scenario 尚须完整通过。REF 与 deferred 边界不变。

### 同业多持仓 Scenario 影响与精确重放整事项（2026-11-04）

R85 候选 `7751bbe432c53b2b30ae8449f3bca68efa7ad03f56f6bda4b3cb210203097907` 的八文件完整 Native 包 65 passed、0 skip、17.76 秒。明确的合成普通已批准账户通过真实 Session/CSRF API 完成情景目录、风险读取、压力计算、ORM 证据保存、TUI 投影与同幂等标识原样重放；两只银行各 10000 元持仓及 100000 元现金，初始净值 120000 元，同业下跌 20% 的假设情景净值为 116000 元，账本/订单/成交/预留前后不变。金额、原件哈希和公开/保存文本精确一致；循环小数收益仅按 Decimal 工作精度限定表示舍入。来源、行情与情景假设均为明确测试夹具，不是实盘观察、真实人工登录、浏览器 DOM 或当日市场来源资格。

报告公开既有 Scenario 的真实已存金额/收益、币种、全组合含现金口径及假设标记；币种未知时金额与收益保留 unknown。重放交叉核对已存修订 ID/hash、冲击与评估绑定，三种重算整体 evidence hash 的错绑反例实际拒绝；只有公开影响字段真正缺席才兼容旧显示，实际 v1 完整证据约束保留。R82 样式失败、R83 的 61 pass/3 fail/1 fixture error、R84 的 64 pass/1 末位舍入失败均原样留存，未跨候选拼绿。

四个生产文件在 R83 实际通过增量 mypy0、全量债务0，R84/R85 仅修夹具并强校验生产字节相同后复用，未重复全量类型。实际架构投影生成通过，仅 summary 文本索引增改；其余计数不变。实际 module-map producer 的逐文件入口/依赖/ORM/task 投影相同，复用既有结构证据。原件索引 `.tmp/ash07-risk-20261104/integration/sector-scenario/delivery-index.json`，最终哈希见同名 JSON 结论。

来源交付提交 `8369de409` 的六项适用 CI 已全部实际通过，独立证明 SHA-256 `9eeb633b0c2bee9aa9072affb37f081ec445398551b6efd37dd5c95453c78dc3`。ASH07/Goal 仍 active：普通 Owner/ETF 当前日金融验收候选待实际收盘来源；当日国证单次查询虽 HTTP200 但 data=null、sampleDate 空，不能生成行业映射。仅待供应商实际材料，不需 Owner 补实仓凭证或新增业务决定；不扩大 REF/deferred。

**Scenario CI 误报修复。** 4d4182778 的 Security Scan（41761247855）把公开合成 runtime profile 标识误认为 generic API key；只将夹具标识改成简短测试名，未改生产或扫描规则。R86 新候选八文件完整重跑 65 passed/0 skip，四个生产文件仍逐字节同 R83，类型0证据复用；同 CI 的 gitleaks8.24.3/配置扫描通过，失败原日志保留。精确索引 `.tmp/ash07-risk-20261104/integration/sector-scenario-security/delivery-index.json`，最终哈希见 JSON；新提交仍须核对实际 CI，不把 4d4182778 的失败记成通过。

3ca166853 的五项适用 CI 已全部实际通过；测试夹具/文档修复不匹配两条 PostgreSQL 专项路径，未计作需运行。独立最终证明：.tmp/ash07-risk-20261104/integration/sector-scenario-security-fix-final-3ca166853.json，SHA-256 1b740d0785a4ab547823cc323d9d4e3f5d968d8107eb41c27599243c5b8f484f。该状态更新留待下个完整业务事项随交付，不另起 CI 文档循环。
### 三类退出压力与当前 Owner DOM 整事项（2026-11-04）

R95 冻结候选 `d0d041d8a551f18836fb784ea94e4172db553a6a027a3488fd6205e67a2289d9` 的完整包 68 passed、0 skip、93.31 秒。停牌、连续跌停、流动性下降均经过普通已批准合成 Owner 的真实 Session/CSRF、Scenario/ORM 留证、公开报告、TUI 投影及原样回放；保留受阻退出与未释放持仓数量，账本不变。真实浏览器任务确认和已存已知金额报告验证净值、币种、回报单位、情景名称/版本与假设边界；未知金额用例明确仅替换内部 API 响应来验证通用呈现，保持 unknown/blocked、无证据写入和账本不变，不冒充可成功运行的业务压力测试。两张截图已实际打开核验。

移除用户字段中的内部修订 UUID，JSON/证据精确绑定保留。UI 生产字节同 R91 的增量 mypy0/全生产债务0，另外三生产字节同 R83，核实复用而未重复全量类型；本事项没有模块/路由/模型变化。R92 样式失败、R93 66 pass/2 DOM fail、R94 67 pass/1 DOM fail 均保留，后两轮为 raw 名称/实际字段网格及诊断等待标题断言修正，未改生产渲染器或放宽业务断言。R95 是单一完整通过候选，不跨轮拼绿。

原件仅本机可用，统一索引 `.tmp/ash07-risk-20261104/integration/pressure-owner-closure/delivery-index.json`，SHA-256 `e4c8dbb10b11115f4facdf91a50c79587b0588ced49dcbf2e9550e6801c19904`。当前提交及其适用 CI 须按精确 HEAD 独立核查；ASH-07/Goal 继续 active，尚待上述当天 Main/ETF 金融验收，REF/deferred 边界不变。

### 普通 Owner/ETF 真实来源验收准备交付（2026-11-04）

本项正式保存七文件验收接线与输入资格准备，**不是实际金融八项通过或 ASH07 关闭**。Main 已接普通 Owner 的正数 SELL 计划、真实预览/预留/模拟成交仓储和风险审计，ETF case 明确核对 PARTIAL/未知残余与重复暴露；身份、审批、本地证券/规则和成交事件的合成夹具边界保留。受审数据库 v2 草案参数仅按本次账户、精确 Source pins、真实精度与限制重绑，不从夹具推定财务阈值；政策/来源单位交叉校验，未知单位不补默认值。Q3 facts 从外部 SHA 绑定上下文读取，原 PDF 十行逐项和可视复核，一致改写权重与总量仍拒绝；历史 DTO 与当天金融输入独立。

R96 七文件样式/编译门通过，八用例依赖闭包无缺项；首轮实际 pytest 启动前因隔离库环境变量缺失而失败，原件保留。R97 同字节候选完整来源/单位/历史日期包 6 passed/0 skip，复用 R96 未变样式和闭包，没有建库或重复类型检查。R101 另以真实保留原件计算九个非持久化 manifest，实际绑定受审草案并拒绝错 pin/改动未受审策略，数值/年龄参数不变；这是纯输入/接线检查，不是已持久化 admission 或当前金融通过。gitleaks8.24.3 扫描对应七文件 217193 字节，无泄漏。

实际 16 点后原件核对：Tushare 两银行 `trade_date=20261104` 的精确日线已取得、校验并留档；Source Native 只读配置、无 M1/PriceBar/金融发布，零其他客户端后停止。R99 自有记录钩子提前读流导致截断失败，未记成供应商错误；R100 改为原 SDK 完整校验后观察相同 capture 对象，两证券重取通过。国证当日 09:55、15:01、16:01 查询仍为空；11/03 变体及行业指数样本均只给旧日期，Sina/MSN/SSE/CAPCO/CSRC 路径也未证明合格同日成员。Owner 已明确保留同日契约，未启用 T-1。当前唯一来源缺口是同日行业原件；新浪报价与实际金融八项仍未运行，不用现有准备替代正向验收。

原件仅本机可用，唯一索引 `.tmp/ash07-risk-20261104/integration/owner-source-preparation/delivery-index.json`，SHA-256 `4fc2f27ef4903d3f9d2902ff31ac8a986f1c7c69fb32be86da476c1f6f2dc628`。当前生产字节未改，沿用已验证生产门，不新增模型/入口/路由/生成投影；七测试/辅助文件按整组交付，CI 按新 pushed HEAD 核查。ASH07/Goal 保持 active，REF/CAL/deferred 的既有边界不变。

### 完整覆盖与当前并发退出补齐（2026-11-04）

唯一生产修复是 `PortfolioRiskCoverage`：显式 COMPLETE 项数不等时不能再凭权重 100% 忽略缺项；未知计数仍为 None，合法 PARTIAL 已知权重和残余保留。现有 ETF 行数校验已足够，未加重复分支。普通 Owner ETF 公开断言新增实际现金加持仓的 NAV、币种及行业/证券上下界分母核对；该当前金融用例仍未运行，不能由 Domain 算术代证。

容量调查的放行提案未采用：全局 executed-usage 不完整，即使有已知资产行也不能证明集合完整，继续全资产 unknown；只有集合明确完整才可按行隔离。新增两种边界及 legacy/精确成交真实仓储补证，精确行经既有合成 V3 UOW 构造，未放宽成交绑定约束。当前 Native 双 BUY 实际验证后单锁内读到 `[0,1]` 个活动委托，容量拒绝后仅一 hold/audit；执行规则到期 UOW 回滚亦实际通过。它是 typed synthetic 来源与账户，不是当前市场原件正向。

R104 同一候选 27 完整模块 **345 passed/0 skipped**，含两项 Native、当前普通 Owner 行业同步/三种退出 Scenario 及六项保留来源/单位/历史日期契约；347 项收集依赖闭包无缺项。所有样式通过；R103 实际增量/全生产债务均 0，生产输入与本候选逐字节一致，仅最终测试 fixture 导入不同，按精确范围复用类型证据。Native 零其他客户端后停止，未建库。R102 的 ORM 半绑定夹具及旧 UTC 样式失败、R103 遗漏 ledger fixture 的失败原件保留；只有 R104 计完整运行通过，未拼接多轮测试。

原件唯一索引 `.tmp/ash07-risk-20261104/integration/closure-audit/delivery-index.json`，SHA-256 `6c858f9f1f0dbe82930bf80fd3f0c42de01b479dfdedc6bcd217a6f2a08967c0`，候选 `8066650e3b3752a5eb9000e344f81869256db66540e1e9c24c8f28689b46cdcd`。未变 DOM 呈现按原件范围复用，记录中的旧 pending 提交状态补为已证实的 ab8/db26 CI 事实。后续金融 runner 已绑定最新七文件与本批证明、要求所有实际适用的当前 HEAD CI；尚未执行金融八项。17:00 真实国证当日响应仍为空，Owner 同日契约不变；ASH07/Goal 保持 active，REF/CAL/deferred、实仓/自动下单/部署边界不变。
