# 账户授权退役盘点与 PIT 实验准备结论

2026-10-29（Asia/Shanghai）。本事项按 [收敛计划](../plans/data-boundary-convergence-plan-2026-10-26.md) 和 [registry](../../governance/active_plan_registry.json) 的 `execution_focus.parallel_preparation` 完成 REF-01/05 只读准备。Codex 负责隔离输入、全仓复核和 REF-05；Kimi Code 2.4.0 负责授权模型族盘点，并依据补充调用链完成第二轮修订。这里只记录准备结论，不改变单元状态、M1 验收或生产资格。

## 已确认结论

| 范围 | 结论与实施含义 | 源码依据 |
| --- | --- | --- |
| 授权版本链 | Authority V1/V2/V3 分别组合 Evidence V3/V4/V5；最高版本不证明旧版已退役 | `apps/account/owner_tenant_authority_v{1,2,3}_composition.py` |
| 初版 Evidence | 定向搜索未找到四个初版用例类及 `DjangoAccountOwnerAssignmentRepository` 的额外直接生产消费者，可列为退役调查候选。三个共享异常和 `AccountOwnerAssignmentServerActor` 仍被后续版本使用，policy HTTP 入口还导入异常，删除整个模块会破坏兼容 | `apps/account/application/account_owner_assignment_evidence.py:70`、`:83`、`:525`、`:626`、`:868`、`:905`；`apps/account/infrastructure/account_owner_assignment_evidence_repository.py:71`；`apps/account/interface/single_owner_policy_api_views.py:15` |
| Authority V1 | 与初版 Evidence 是不同族，其 reader 绑定 Evidence V3。selector 缺省或 V1 scope 路径仍有静态消费链，不能据初版 Evidence 的调查结论删除 | `core/integration/system_audit_authority.py:258`；`apps/audit/infrastructure/system_audit_outbox_runtime.py:212`、`:295` |
| 发布消费者 | 数据发布激活、M1 参考价、财务 capacity、execution quote 及 quote pointer rollback 均消费 production authority capture；初始有界快照漏掉这些间接引用，二轮已修订 | `apps/data_center/publication_candidate_activation_composition.py:163`；`m1_reference_price_publication_composition.py:66`；`infrastructure/financial_capacity_publisher_runtime.py:421`；`execution_quote_publication_composition.py:213`；`execution_quote_pointer_rollback_composition.py:51` |
| PG 触发器 | 0065 为 Evidence V5、Authority V3 等 source 表安装 statement 级触发器；非 PG 跳过。旧建表 migration 未见触发器不能推导全链路没有触发器 | `apps/account/migrations/0065_account_authority_generation.py:18`、`:53` |
| PIT 复用 | 已有版本事实、冻结 manifest、精确 Regime receipt 与独立 proxy/label 可得时间，可复用既有能力；实际数据覆盖仍未知 | `apps/data_center/infrastructure/pit_models.py:49`；`pit_repository.py:41`、`:117`；`apps/macro_factor/infrastructure/data_center_pit_projection_adapter.py:168`；`regime_historical_assignment_adapter.py:80` |
| 宏观读取限制 | `get_series(use_pit=True)` 的日期过滤及空发布时间 fallback 本身不足以证明严格历史可得性、原始修订版本或质量。REF-05 不以此参数单独认定输入合格；本结论不声称发现线上绕过 | `apps/data_center/infrastructure/macro_fact_storage_repository.py:94` |

## 下一事项与未验证范围

REF-01 的初版族续查已补动态加载、SQL、归档记录和共享类型线索，结果见下节。实施仍需集成焦点移交；先补用例、异常和 actor 身份特征测试，保留兼容导出，再核真实行数、历史 hash、归档恢复与停写/切读条件。不能把静态无直接引用写成“无使用”或“可删表”。

REF-05 在独立登记的数据/资源窗口核原始发布日期、修订版本、股票池历史成分、价格/公司行为、日历及可交易时点的真实 PIT 交集。实验须预先固定既有策略/配置、同输入无/有 Regime 对比、基准、walk-forward、费用和缺失处理；HP 仅使用扩张前缀。资料不足时交付不可识别范围，不补造历史、不恢复 deferred ASH-06。

本批未运行测试、数据库查询、回测、provider 调用或部署。实际行数/FK 存量、动态或外部消费、生产 selector/流量、触发器实装、历史 PIT 覆盖及 OOS 效果均未验证。正式工作树存在其他未提交事项并继续变化，本批静态输入不等于冻结发布候选。

## 输入身份与原件索引

输入 HEAD：`2417741d658edc9ac0e31b366be7ab4719e4502a`，带当时工作树内容；各文件以 manifest 哈希绑定。初始 571 项、调用链补充 25 项、REF-05 13 项分别完成 SHA-256 复核，均未变动。关键符号行号另经 AST 核对。

原件仅本机保留于 `D:/githv/kimi-collaboration/20261029-ref01-ref05/`，不宣称远端持有。首轮错误结论由二轮修订，首轮原件保留；完整日志、源码快照和脚本不入库。

| 原件 | SHA-256 |
| --- | --- |
| `source-manifest.json` | `9953ccf61b3308189f8c8b419ff34d74f4b9982e5453029ec967111cb32b8f66` |
| `review-supplement-manifest.json` | `f267f1a305dd6393a4404ffffac7b629df94aca9b70b283d0325a7aa635696bb` |
| `kimi-ref01-corrected.txt` | `62b52d4f802a7bdb3ee70a47954d2a725abce9881c82ef9428b5b01cb093077e` |
| `ref05-findings.txt` | `7eec877e37bf2fc498b502a2ba7070cc6acc942dabfe1b5c7f1b7c302a530e9c` |
| `evidence-index.json` | `7993b1c2bea2148b243e73caaf6d30d3195e3460e913f6324ff2bb3d3ca60f56` |

命令及结果：两轮 `kimi -p <任务>` / `kimi -S <session> --add-dir <补充源> -p <复核任务>` 均退出 0，session 为 `session_44d1ae1e-28dd-4628-ab93-6dd4e57814ca`；`rg` 定向全仓补证、stdlib `ast.parse` 行号核对与 SHA-256 逐项复核结果见该目录 `verified-symbols.json`、`review-integrity.json` 和 `evidence-index.json`。原始任务文本保留实际参数，索引列出完整原件哈希。

## 初版族续查与兼容条件

首批结论提交为 `771de3045c1f19d1bd0c9b853155e555520f89b6` 后，Kimi 继续同一 session 做只读续查，Codex 独立复核。续查输入 HEAD 为 `93b272f1c682d90baceb55dc9d79da61a8ae69c1`，仍带当时工作树内容；词边界扫描得到 157 个文件、389 行命中，复用哈希相同的已有快照，只保存 23 个新增/变化文件。157 项输入哈希再次全部通过，不与首批输入拼接为候选验收。

- **共享 actor 也是保留面**：`account_owner_assignment_evidence.py:83` 的 `AccountOwnerAssignmentServerActor` 被后续 receipt application/codec 和 Authority V1 使用。`application/account_owner_assignment_provenance_receipt_v3.py:66`、`:621` 明确检查 `type(value) is AccountOwnerAssignmentServerActor`；只处理三个异常而复制或删除该类型，会破坏现有类型身份。后续特征测试必须保留类身份、拒绝类型替换、actor 载荷及 codec/hash 等价。
- **旧身份字符串并非物理 FK**：`infrastructure/account_identity_raw_source_models.py:216`、`:225` 的 `acct_raw_src_assign_ck` 检查旧 `assignment_evidence_artifact_type`。这是需保留的语义约束，不证明存在指向旧 Evidence 表的物理外键或当前行数据。
- **历史记录不等于当前消费**：12 份 `docs/deployment/**/*.json` 记录含旧表项，部分 Evidence/Subject 历史 `rows` 为 0；它们只能说明当次记录的表清点，不能证明当前空表、当前归档调用方或现行恢复流程。真实备份/恢复消费者和三表现存数据仍需独立核验。
- **复用既有退役规则**：[retention floor](../../governance/versioned_surface_retention_floor.json) 的 policy、no-suffix 族及 `legacy_tracked_marker_floor` 已保留初版用例、模型和仓储；[retirement registry](../../governance/versioned_surface_retirement.json) 要求真实行清点、历史 hash 和归档恢复证明。此次未改变 baseline、digest、版本集或注册状态。
- **动态扫描结论有界**：Codex 对选中目录中 1134 个 Python 文件作 AST 解析，无解析错误；检查 3655 处目标动态调用的直接字符串参数，未命中初版族字面量。其中 1130 处调用没有直接字符串参数，组合字符串、配置或仓外路径仍未知。这不是“无动态调用”的证明。157 文件语料内的绝对 `ImportFrom` 清单另有 80 条语句（42 production、38 test），不代表完整 import 闭包；相对模型注册入口另核于 `infrastructure/models.py:11`、`:15`。

后续最小特征用例还须覆盖实际仓储方法各自的缺失/损坏/时钟/scope 合同及零写入，而非统一假设均抛 `Unavailable`；保留旧迁移身份、模型注册与恢复表/hash 身份。在源码移交与退役证明前，本事项继续只交付静态准备。

续查命令：同一 `kimi -S` 配合 `--add-dir <continuation-01>` / `-p <任务>`，退出 0；全仓 `rg` 精确符号/表名扫描、定向动态调用 AST 参数检查及输入 SHA-256 复核均已完成，未运行业务测试或数据库。完整命令、逐文件身份和未采纳的 Kimi 推断保留于原件，以下为本机目录 `D:/githv/kimi-collaboration/20261029-ref01-ref05/continuation-01/` 的追加索引。

| 原件 | SHA-256 |
| --- | --- |
| `source-index.json` | `1d6561695d9ebeea3ab2ed8707be7c7842d778c78dd3d6690d8800f0848261ad` |
| `kimi-output.txt` | `05f5608507ca87a151951f1df6a71f3833f464c6fc5ef525c090720f19bd88fc` |
| `dynamic-literal-audit.json` | `e43a69de46c8f11daaf728b4e717f7deafa3fae128f06ba3de61a1f4d1398f18` |
| `reviewed-findings.json` | `687a5127531c9e74e23fd26dae75053e3b5d8d7351ddbce21a2f175f1a863dd4` |
| `evidence-index.json` | `1435a3c01b875a04d4247634715861b3e246f3a6a47e2d3a45f3cfe51048c0be` |

## 2026-11-06 ASH-08 等待窗口内的差值续核

输入为正式提交 `71fc46602e1600b136bdd96c6de9bcfd95bb151d`；三位 Luna max 分别复核授权族差值、PIT可行性与实验设计、依赖/后继整单元。所有检查仅源码与既有本机原件，不查数据库或provider、不运行实验/业务测试；历史输入与原件保留，不能把不同批次拼成运行验收。

**REF-01 实际差值。** 相对既有 `ff91e8749c89e8fac66311816e7508fdffb6c291` 盘点，选定身份/authority族没有账户模型或迁移增改。相关三处代码差值是 V4 assignment Evidence、Authority V2 的单对象图成功验证/解码缓存包装，以及 Reobservation V1 锚点行自身锁定；后者 append 仍先分别锁定 Binding 与 Physical 父证据，未取消父锁。V1 provenance receipt 的 Issue/GetExact/GetCurrent、单append仓储及System Audit相关复用与原索引一致，不能因最大Vn存在就判定旧族可删除。

ASH-08 的 `RebalanceJourneyAccountAuthorizer` 委托现有risk resource scope reader；`DjangoPortfolioRiskResourceRepository.read_account_scope`读取 `SimulatedAccountModel.user_id` 与只读observer grant，写入仍只允许owner。本范围未发现直接使用Account owner-assignment/authority receipt族作为计划执行授权的证据，因此没有需先插入REF-02/03的实证阻塞；REF-02/03本身仍缺REF-01退出与正式窗口。唯一后续候选保留为原V1 provenance receipt单族；实际使用/旧部署、行数、保留期限和归档恢复消费者均未知，本次没有停写、迁读或删表结论。

**REF-05 可复用契约与证据缺口。** PIT manifest已有as_of、knowledge_scope、calendar/query版本、选中版本与质量/哈希绑定；PUBLIC available_at和SYSTEM ingested_at是不同口径。MacroFact的reporting_period不是发布日期，`get_series(use_pit=True)`本身不能证明修订与历史可得；PriceBar的fetched_at是本地采集时钟，不是供应商历史available_at。覆盖率必须显式给定非空expected keys/session grid并验证质量，不能把未给required_keys时的默认100%或空选择当真覆盖。既有历史Regime、时序split和ResearchExperiment/MultipleTestFamily/trial登记机制可复用，但本次未核实对应DB行或历史输入清单。

当前不能识别Regime的真实增量价值。待独立登记的只读输入窗核实宏观首发/修订/first-known，日价格可得性/公司行为及历史成分、日历交集，和精确已有策略/Regime/基准/费用及family校正规则。现有10/29资料是代码/来源manifest，不是这些真实历史数据的证明；未知保持未知，不要求Owner为M1采购数据。

预注册草案已固定方法：同一既有策略和历史股票池，无/有精确版本Regime规则；另列既有宽基持有和已有动量/均线定义。统一费用、现金/不可成交、次一合格session成交与缺失剔除；按真实PIT交集固定expanding训练/验证和不重叠forward OOS，不看OOS后调参，HP只算扩张前缀。费用或比较器没有精确版本则保留不可用，不以源码默认值代替批准政策。报告净OOS超额/回撤/换手/成本/样本/不确定性；未来版本、缺时钟、空覆盖或无法绑定策略即不可识别，负结果也有效，不自动晋级。当前不运行回测、不恢复ASH-06/STRAT-03，也不满足STRAT-02或ASH-11。

**REF-01 完整后继候选。** GOV-03目前completed；ASH-08全部退出后才可正式交接。完整REF-01除了区分抽象声明、具体模型、继承字段与物理表、收齐current/exact/history/writer/外部与归档消费者、选一个可实施族，还须在已有字典/CI入口补实际base/head模型/版本差值与既有计划说明校验；新增无说明、伪装移动、未清引用删除等必须拒绝，合法说明与抽象/同身份移动须按合同处理。没有新baseline/审批服务，也不手改生成投影。A负责口径/族证据，B负责消费者与兼容边界，C负责既有增量门/正反例及验证，Root串行整合；只在实际改生产Python/ORM/结构时跑相应类型、投影和结构门。后续REF-02/03迁移或退役不混入REF-01。

本机原件位于Git忽略目录 `.tmp/ash08-journey-20261105/idle-preparation/`，不声明远端持有；以下hash由程序计算并已核对。资料准备不构成任何REF单元关闭。

| 原件 | SHA-256 |
| --- | --- |
| `a-ref01/handoff.json` | `95bbab76d1f43536120a5e4baeffb61a10107891b28222d7893a2849018abb01` |
| `b-ref05/handoff.json` | `d568ed1b7a3a537563a1ee34d2840096c06470b23298158ff240c91c3016c199` |
| `c-order/post-ash08-next-goal-candidate.json` | `f4a91c6a4727bdd24e73adacd9c70cac529a3a3f3adad7dc28ccc30b56d26e43` |

## 2026-11-08 PUBLIC 数据诊断

Owner 已授权必要推进。本节接续上面的准备记录，受限范围与源时间规则以[收敛计划 REF-05](../plans/data-boundary-convergence-plan-2026-10-26.md#ref-05regime-增量价值的有界实验wp7-验证)为准。精确首发未知不再作为所有 PUBLIC 用途的共同前置；SYSTEM 仍需真实系统接收历史。此次仅复用既有 Domain 做本机确定性诊断，没有新增算法、生产代码、模型、写库或策略收益实验。

- **真实输入：** 6 份国家统计局具名公告，提取 4 条 2024-07 至 10 月制造业 PMI 和 5 条 2024-06 至 10 月全国 CPI 同比。PMI 四个月都属于 10/31 公告的同一表格版本，只从 11/01 零点后可用，不能借该表倒推它们更早的公开版本。CPI 用各月公告，全国同比列与正文双重核对，未混入 CPI 指数水平、环比或累计同比。
- **规则：** 官方发布日期保留为来源断言，按次日上海零点起使用；这不等同于独立历史字节捕获。开户数另用已核验 CDX/正文摘要的存档时间 2024-11-06 19:36:07，证明 739.40 万户这一总开户 proxy 的 PUBLIC 可得上界，首发与系统历史接收仍为空。两类原件均冻结 SHA-256；源修订史不作完整性承诺。
- **结果：** 固定两个观察时点 2024-11-08、11-11 的 09:00，分别选入 CPI 0.4%、0.3%，PMI 均为 50.1；现有 V2 均给出 Recovery。两组各 8 个预先列明的必需键完整，PUBLIC Domain manifest 完整性通过。所有历史 SYSTEM 选择均为空；没有以当前接收时钟回填 2024。当前配置在计算前冻结，不声明为当年部署参数。结果为本机诊断，非 canonical 研究登记或投资结论。
- **验证：** 27 项功能与边界校验通过，覆盖发布前排除/准入边界、SYSTEM 分离、原件篡改、manifest 篡改及既有源码身份；66 项原件/输入完整性核验通过。SSE 英文日历请求 TLS 失败原件保留且未采纳，本例观察网格不声称具备成交日历资格。没有生产 Python 改动，未据此重跑生产类型或数据库测试；治理交付命令及实际状态追加在下列目录的 `delivery.json`。

原件仅在本机 `.tmp/ref05-single-month-source-20261108/continuation-03-public/`；`frozen-case.json` 固定规则/参数/必需键，`public-fact-versions.json`、两个 `manifest-*.json`、`diagnostic-results.json` 与 `account-public-candidate.json` 提供可复核结果。唯一证据索引 `evidence-index.json` SHA-256 为 `2b43244b5df01a27e05f097e8b1b2bf49a44b11ba6ec1e3f99c48c08501f2f69`，数据/算法候选为 `8acf659ba3c0cc86f937ae45ad2e46ca21c83762`；既有封存目录未改。不得把这些本机原件声明为已同步远端。

已解决的是受限 PUBLIC 数据选择与计算路径；未完成的是足够长的实际必需输入覆盖、完整市场/公司行为/日历及策略/比较器/费用/split/family 绑定，因而 REF-05 整单实证退出仍未满足。后续优先扩大这条已跑通的文档路径，按实际缺口补齐，不再把开户数精确首发当成该 V2 的前置，也不将一个样例的完整覆盖率推广为整段历史覆盖率。

### 可复用成果进入正式分支

`dbb4f3aa0` 只提交了本节、计划和 registry，`.tmp` 中的一次性解析/重放脚本并未随仓库交付。该缺口在本次修正：正式入口为 `scripts/replay_ref05_public_evidence.py`，契约测试为 `tests/unit/test_replay_ref05_public_evidence.py`，具名来源、9 条提取值、参数、非空输入网格及源码/原件哈希由 [ref05-public-replay-20261108.json](ref05-public-replay-20261108.json) 绑定。来源层级与原研究限制保持不变，脚本只有本地只读输入与新增结果文件能力，不访问网络或数据库。

必要网页、HTTP 原件、原始输出和交付记录共 57 份、1,914,909 字节，已经逐文件核对后复制到本机 `artifacts/ref05-public-20261108/`。该目录是忽略的持久证据归档，不是业务实现位置；`archive-index.json` 的摘要写入正式 JSON 索引。原 `.tmp` 目录保留作历史封存来源，正式重放不再读取它。新机器需要另行恢复这些相同哈希的原件；仅克隆 Git 即可审查规则和运行无数据库合成契约测试，不能声称已取得本机原件。

```text
python scripts/replay_ref05_public_evidence.py --evidence-dir artifacts/ref05-public-20261108 --output artifacts/ref05-public-20261108/replay-new.json
```

输出文件必须不存在；缺件或错件返回非零退出码，不覆盖旧报告。正式入口已用归档真实原件复跑，两个时点的全部 V2 输出与原报告一致。验证覆盖未来版本排除、SYSTEM 时钟分离、数值/原件/代码摘要篡改、重复业务键、空预期集合、无时区时间、路径越界、缺件 CLI 和输出覆盖拒绝，并登记脚本单独变更时的 CI 测试选择。最新命令、真实退出码及源码身份保留在归档目录的 `delivery/`；不把原报告旧候选的通过结果冒充新入口的验收。

代码身份使用显式声明的 LF 规范化摘要，与 Git blob 一致，兼容 Windows CRLF 和 Linux LF 检出；网页及归档原件仍逐字节校验，不能借换行转换改变其身份。机器可读样例由 `.gitattributes` 固定 LF；跨平台契约验证两种源码换行得到相同结果，并拒绝原始证据换行篡改。

### 2026-11-08：2024 年十二点来源资格交付

接收基线 `d2dcb627f48944d2fe82d107507586a24d1709e6` 的五项精确 CI 全部成功后才修改共享源码。本次只完成 REF-05 的有界来源资格 Goal；单元仍按 registry 的 active 状态及原退出门推进，不构成整单退出或生产资格。ASH-08 原 Goal 与 11/09 上海 16:00 后候选窗保持，真实来源资格恢复时优先串行交还资源。

**预冻结范围。** 2024 年每月 15 日上海 09:00 一个观察点，PMI／全国 CPI 同比均要求此前四个连续月；因此实际原文范围是 2023-09 至 2024-11，各 15 月、30 个唯一必需键，全年共 96 次选择。不是交易日历，也不包括 2024-12 统计期。冻结文件 `artifacts/ref05-monthly-2024-20261108/grid-freeze.json` 的 SHA-256 为 `e5673f6576ad83c860ba574f6a8124d277b10c7bb5d675557844368a7052fbd9`。缺键、未来可得、摘要不符或正文／表格矛盾拒绝重放；不补值、不挪观察点。CLI 校验冻结网格、角色与参数，当前参数不冒充 2024 年部署配置。

**来源清单与时钟。** [机器可读配方](ref05-monthly-2024-replay-20261108.json) 逐项列出 30 份具名当月官方公告的 URL、标题、页面发布时间、当前抓取时间、原件 SHA-256、值、原单位和版本身份。全部从国家统计局原文核对，全国 CPI 取同比列并与正文核对；PMI 保留原表百分数值，如 49.0，不除以 100。当前捕获字节不宣称是当年首发字节。

取证发现 17 个旧版页面没有 PubDate 元数据，配方明确记为 null，以页面标题区的可见时间验证；存在元数据时必须一致。保留原冻结文件，网格、缺失规则与“源日期次日上海零点可用”的阈值没有改变。四份 PMI 公告的 URL 日期与页面时间不同：2023-09（09/28 与 09/30）、2023-12（12/29 与 12/31）、2024-02（03/18 与 03/01）、2024-03（04/11 与 03/31）。尤其后两份 URL 的较晚日期不能证明当前字节在较早观察时点已存在；本次只按获准的**来源自述日期**层级纳入，未授予严格历史版本资格。没有把 URL 日期、搜索抓取日或本次接收时钟当首发日。最初三个错误入口的 404 记录保留，随后由官方目录定位原文。

| 2024 观察点（均 15 日 09:00） | 两指标各自必需统计期 | PUBLIC 来源日期规则覆盖 | PMI / CPI 同比（原数值 %） | V2 诊断 |
| --- | --- | --- | --- | --- |
| 01 月 | 2023-09～12 | 8/8 | 49.0 / -0.3 | Deflation |
| 02 月 | 2023-10～2024-01 | 8/8 | 49.2 / -0.8 | Deflation |
| 03 月 | 2023-11～2024-02 | 8/8 | 49.1 / 0.7 | Deflation |
| 04 月 | 2023-12～2024-03 | 8/8 | 50.8 / 0.1 | Recovery |
| 05 月 | 2024-01～04 | 8/8 | 50.4 / 0.3 | Recovery |
| 06 月 | 2024-02～05 | 8/8 | 49.5 / 0.3 | Deflation |
| 07 月 | 2024-03～06 | 8/8 | 49.5 / 0.2 | Deflation |
| 08 月 | 2024-04～07 | 8/8 | 49.4 / 0.5 | Deflation |
| 09 月 | 2024-05～08 | 8/8 | 49.1 / 0.6 | Deflation |
| 10 月 | 2024-06～09 | 8/8 | 49.8 / 0.4 | Deflation |
| 11 月 | 2024-07～10 | 8/8 | 50.1 / 0.3 | Recovery |
| 12 月 | 2024-08～11 | 8/8 | 50.3 / 0.2 | Recovery |

**覆盖与缺口分开计量。** 来源日期规则下缺失必需键为 0/96；首发时间、修订完整性与历史 SYSTEM 时钟为 30/30 未知；独立历史字节与 SYSTEM 历史接收的已证明覆盖均为 0/30，不能把前一个 100% 转述为严格 PIT 全覆盖。PIT 对象的本地 `revision_number=0` 只是该单文档诊断的技术序号，来源修订号另以 null 发布。宏观诊断之外，市场价格／公司行为／历史成分／成交日历和策略、比较器、费用、split、family 绑定仍未完成，未运行收益或 OOS 实验。

**复现与验证。** 原件、逐键覆盖／缺口矩阵、完整日志与候选身份统一索引在 `artifacts/ref05-monthly-2024-20261108/validation-index.json`（仅本机可用，未上传原件）。两次独立 CLI 输出 `replay-6.json`、`replay-7.json` 逐字节相同，SHA-256 均为 `675fe57bd6f55269909ee8b3e8616125c989d188e2d76e9ba7912135500f9fb5`。旧九值／两点配方仍可重放。契约覆盖上涨、下降、持平、插入说明的同比段落、旧版可见时间、元数据冲突、URL 日期差异、冻结输入被改动、缺键与未来输入；完整开发检查和失败轮次见同一索引。解析器不访问网络或数据库。

```bash
python scripts/replay_ref05_public_evidence.py --recipe docs/reviews/ref05-monthly-2024-replay-20261108.json --evidence-dir artifacts/ref05-monthly-2024-20261108 --output artifacts/ref05-monthly-2024-20261108/replay-new.json
```

## 2026-11-09 六公告独立历史版本核验

本轮仅核验已冻结的六份公告及最早相关观察点，不运行 Regime、收益或 OOS 计算。[正式配方及逐请求矩阵](ref05-history-six-20261109.json) 绑定原配方、查询冻结、CDX、正文及执行源码；完整原件和唯一验收索引位于 `artifacts/ref05-history-six-20261109/validation-index.json`（仅本机持有，未上传原件）。截止与下表可得时钟均为上海时间。

| 目标／目标值 | 冻结截止点（09:00） | 截止前独立历史资格 | 截止后查询与缺口 |
| --- | --- | --- | --- |
| PMI 2023-09／50.2 | 2024-01-15 | **已证明**：HTTP 2023-10-02 06:39:03、HTTPS 2024-01-07 06:06:40 两份正文摘要匹配；选择后者 | HTTPS 2025-06-13 20:31:38 正文匹配，拒绝提前使用；HTTP 无匹配行 |
| PMI 2023-12／49.0 | 2024-01-15 | **已证明**：HTTPS 2024-01-10 11:10:42 正文摘要匹配；HTTP 无匹配行 | HTTPS 2024-04-25 22:09:10 正文匹配，拒绝提前使用；HTTP 无匹配行 |
| PMI 2024-02／49.1 | 2024-03-15 | **未知**：两址截止前均无匹配行，不证明不存在旧址或未收录版本 | HTTPS 返回 HTTP 200 空正文，无法解析 CDX；HTTP 无匹配行；当前 URL 日期 03-18 不替代页面自述 03-01 |
| PMI 2024-03／50.8 | 2024-04-15 | **未知／受阻**：两址截止前均无匹配行 | HTTPS 有 2025-01-23 15:23:05 CDX 行，但正文两次 TLS 失败；HTTP 查询两次 TLS 失败。只有 CDX 不授予正文资格 |
| 全国 CPI 同比 2023-09／0.0% | 2024-01-15 | **受阻**：两址截止前查询均 TLS 失败，重试一次仍失败 | 两址截止后查询同样失败，历史版本未知 |
| 全国 CPI 同比 2024-01／-0.8% | 2024-02-15 | **受阻**：两址截止前查询均 TLS 失败，重试一次仍失败 | 两址截止后查询同样失败，历史版本未知 |

范围在首次 GET 前冻结：六目标、十二个精确 URL（已核验 HTTPS 及 HTTP 等价址），未增加无目录证据的旧址。每址各查截止前最近一行与截止后最近一行；每侧至多获取一份正文，网络错误最多重试一次，不分页、不无限追溯。共 24 个 CDX 查询：5 个取得正文、8 个成功但无匹配行、1 个空响应不能解析、1 个取得 CDX 后正文受阻、9 个查询受阻。错误、响应头、CDX 原件、下载时间及哈希均保留；TLS 失败不转写为“存档不存在”。

5 份正文的 CDX SHA-1/base32 摘要均逐字节匹配，并分别记录 SHA-256；与当前正文比较，具名版本的标题、页面发布日期及目标数值一致，5 个历史字节哈希均与当前版本不同。这只证明已捕获版本中的指定事实，不能证明完整正文无变化、修改发生日期、首发时间或修订史完整。PMI 2024-03 的 CDX 候选没有可验证正文，不计入 5 份合格捕获。

同一离线入口按 PUBLIC 的 `available_at` 和 SYSTEM 的 `ingested_at` 区分时钟，历史 PUBLIC 取来源次日零点与独立捕获时钟的较晚者，并在截止点选最新合格版本。六项来源自述 PUBLIC 保持 6/6；严格独立历史 PUBLIC 选择为 **2/6**，两个真实后发版本均返回 `after_cutoff`，六份当前字节均返回 `independent_capture_unproved`。已取得但较早的同键捕获保留为候选并标为已被后一个合格版本取代。历史 SYSTEM 选择为 **0/6**；真实本次下载时钟没有倒填为 2024 系统接收。首发、修订完整性与历史 SYSTEM 时钟六项均仍未知；不外推至原 96 次选择或收益结论。

```bash
python scripts/replay_ref05_public_evidence.py --recipe docs/reviews/ref05-history-six-20261109.json --evidence-dir artifacts --output artifacts/ref05-history-six-20261109/replay-new.json
```

新配方使用显式 history schema；上述旧十二点配方保留验收时的入口源码哈希，需匹配其原验收代码身份，不能在更新后静默跳过源码校验。新核验独立绑定当前入口和原配方字节，原 30 份来源、12 点网格及参数没有重写；旧封存索引中的 171 份原件全部核对一致。真实后发拒绝与双跑结果见本轮索引；边界时刻、改值修订、摘要／身份／时间矛盾和空捕获的负例明确为测试夹具，不计历史覆盖。检查、失败轮次、最终候选与精确 CI 同在该索引，未把旧候选检查当成新候选通过。

结论限于六项的已证明／未知／受阻范围。四项的独立历史资格、全部首发／修订完整性／旧 SYSTEM 时钟仍待新证据；本窗口已触发冻结停止规则，不继续请求。没有 canonical/provider/生产写入、购买、部署或 deferred 恢复。REF-05 整单退出和原 ASH-08 Goal 均未由本轮关闭。

## 2026-11-09 十二观察点独立历史资格投影

本阶段仅将已封存的五份具名历史正文投影到原十二点／96 次必需键，没有新请求、来源或月份。[派生配方](ref05-history-grid-20261109.json) 复用同一离线入口和 PIT manifest，原 30 份来源、参数、两份旧配方及其源码哈希不变。接收时逐项复核前阶段及正式交接附件共 201 个文件，哈希全部一致；旧检查只用于其原候选及未变输入。

| 上海时间观察点（2024 年每月 15 日 09:00） | 来源自述 PUBLIC | 独立历史合格键 | missing／unknown 键 | PUBLIC manifest | SYSTEM manifest |
| --- | --- | --- | --- | --- | --- |
| 01 月 | 8/8 | 2/8 | 6／6 | 受阻 | 受阻，0/8 |
| 02 月 | 8/8 | 1/8 | 7／7 | 受阻 | 受阻，0/8 |
| 03 月 | 8/8 | 1/8 | 7／7 | 受阻 | 受阻，0/8 |
| 04 月 | 8/8 | 1/8 | 7／7 | 受阻 | 受阻，0/8 |
| 05 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |
| 06 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |
| 07 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |
| 08 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |
| 09 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |
| 10 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |
| 11 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |
| 12 月 | 8/8 | 0/8 | 8／8 | 受阻 | 受阻，0/8 |

独立历史选择合计 **5/96**：1 月选择 PMI 2023-09 的 2024-01-07 06:06:40 捕获（SHA-256 `36927af7c210d6251b2ac2b62a621c0c682a8dce61adc5c78e652070b84f70cc`）；1–4 月选择 PMI 2023-12 的 2024-01-10 11:10:42 捕获（`e38370b75968f6d7258ecc3a7b1266f652005e53886fecbb4b101b2c50b49545`）。两个真实后发版本在所有需要对应键的截止点仍被拒绝；后续月份该键已退出冻结必需窗口，不能用后发版本补入别的月份。PMI 2023-09 的较早合格捕获保留为未选候选。五份捕获不是五个合格键，也不是五个合格观察点。

其余 **91 次**均无合格历史版本；missing 表示无可选版本，unknown 记录同一必需键尚未解决的证据问题，两列重叠，不相加。六目标中四项原缺口（PMI 2024-02、2024-03，全国 CPI 同比 2023-09、2024-01）在各自原窗口保持受阻；其余未核验键标记 `unknown_not_audited`，不能解释为已查无存档。所有当前字节仍返回 `independent_capture_unproved`。来源自述层保持 **96/96**，SYSTEM 历史选择 **0/96**；全部首发、修订完整性与历史系统时钟仍未知，首发未知没有被重新作为所有 PUBLIC 用途的前置。

逐点逐键版本选择／拒绝、原件身份、两个知识范围的 manifest 与确定性双跑结果保存在本机 `artifacts/ref05-history-grid-20261109/validation-index.json` 所指原件。每个缺口都进入 manifest 的 missing／unknown，部分覆盖不能得到 verified；本次 **0/12** 个观察点可验证，**零次**下游计算。完整覆盖、截止相等、改值后发版本、空捕获、摘要／谱系／路径篡改反例仅是自动化测试夹具，不增加历史证据覆盖。

```bash
python scripts/replay_ref05_public_evidence.py --recipe docs/reviews/ref05-history-grid-20261109.json --evidence-dir artifacts --output artifacts/ref05-history-grid-20261109/replay-new.json
```

新 schema 校验本次执行源码，同时按旧配方的原哈希校验归档提交源码；后者只验证谱系、不执行旧计算。直接使用两份旧配方仍要求原验收源码身份，不跳过校验、不重写旧配方。原件、失败诊断、候选身份、适用检查与精确 CI 均在该阶段唯一索引；仅本机持有原件，未宣称远端持有。本阶段完成仅意味着冻结范围的资格与阻断结论可重放，REF-05 仍 active，收益／OOS、市场链路及整单退出未完成。ASH-08 原 Goal、监控和真实合格来源优先规则保持。

## 2026-11-09 历史资格缺口实质补证

Owner 要求实际解决缺口后，开启新的有界获取窗口。保留原 30 份公告、12 个截止点和 96 次必需键，复用前阶段五份捕获；新增 **23 份摘要／正文／时钟通过的历史捕获**，合计 28 份具名版本。独立历史 PUBLIC 覆盖由 **5/96 提升到 75/96**，完整 PUBLIC manifest 由 **0/12 提升到 5/12**。这五点只通过已捕获版本的历史 PUBLIC 资格，不代表首发／完整修订链、历史 SYSTEM 或生产／收益资格。

| 上海时间观察点（2024 年每月 15 日 09:00） | 独立历史合格键 | 尚缺必需键 | PUBLIC manifest |
| --- | --- | --- | --- |
| 01 月 | 8/8 | 无 | verified |
| 02 月 | 8/8 | 无 | verified |
| 03 月 | 7/8 | PMI 2024-02 | blocked |
| 04 月 | 5/8 | PMI 2024-02、03；CPI 2024-03 | blocked |
| 05 月 | 3/8 | PMI 2024-02、03、04；CPI 2024-03、04 | blocked |
| 06 月 | 3/8 | 同 05 月 | blocked |
| 07 月 | 4/8 | PMI 2024-03、04；CPI 2024-03、04 | blocked |
| 08 月 | 6/8 | PMI 2024-04；CPI 2024-04 | blocked |
| 09 月 | 8/8 | 无 | verified |
| 10 月 | 7/8 | CPI 2024-09（最早找到的捕获晚于本点） | blocked |
| 11 月 | 8/8 | 无 | verified |
| 12 月 | 8/8 | 无 | verified |

CPI 均指全国同比；missing／unknown 各 21 次，记录同一批缺口，不能相加。来源自述层仍为 96/96，所有当前下载字节仍不自动获得独立历史资格。全部 SYSTEM manifest 受阻，历史 SYSTEM 为 0/96；首发、修订完整性和历史 SYSTEM 时钟仍全部未知。

**四项原缺口保留历史并逐项更新。** CPI 2023-09 新增 2023-12-09 14:09:47（上海）捕获，CPI 2024-01 新增 2024-02-09 12:06:01 捕获，均早于各自最早必需截止点，历史 PUBLIC 缺口已补证。PMI 2024-02、03 仍未解决；各增加一个由真实官方正文确认的旧址，截止前及剩余必需窗口的查询均无匹配。原记录与失败原件不删除，两个已补证 CPI 的首发／修订完整性／SYSTEM 仍未知。

**获取与时钟规则。** 改用系统验证 TLS 的 curl 解决此前 Python 传输失败；28 个原路径完成 35 次有界 CDX 查询，21 次直接匹配且正文合格，11 次无匹配，3 次正文返回 302。后者涉及两个公告：PMI 2024-07、11 各按真实 Location 取回一次正文，摘要与原成功 CDX 完全相同，较早 Memento 不晚于原索引时钟。资格保守使用较晚的原 CDX 时间（上海 2024-08-13 22:29:31、2024-12-09 09:17:57），没有倒推到较早正文时钟。此前对较早重放时间的独立 CDX 查找失败保留；该规则及两条目标在取正文前另行封存，未静默放宽日期相等条件。旧址另有四次有界查询均无匹配；空结果只代表本次窗口，不声称全球不存在记录。

**正式交付与复用。** [本次派生配方](ref05-history-recovery-20261109.json) 绑定新的历史配方、获取原件清单和重定向时钟规则；生产代码、测试、旧配方与旧原件不变。复用 `463f641e493254e139fcdde2f8c47c029ca05bc4` 对应的 46 项契约测试及未变代码的格式／类型检查，本次仅重放新证据、检查新治理输入与精确提交 CI。完整命令、原件哈希、双跑输出、复用身份、候选与精确 CI 收于 `artifacts/ref05-history-recovery-20261109/validation-index.json`；原件仅本机持有，Git 中交付配方和精简结论。离线复现不联网、不查数据库：

```bash
python scripts/replay_ref05_public_evidence.py --recipe docs/reviews/ref05-history-recovery-20261109.json --evidence-dir artifacts --output artifacts/ref05-history-recovery-20261109/replay-new.json
```

余下是五份公告的独立历史版本，以及 CPI 2024-09 更早捕获；再扩大获取时须先绑定真实来源身份与截止窗口。此次没有 Regime／收益／OOS 计算、canonical/provider/生产写入、购买或部署，不恢复 deferred、不关闭 REF-05 整单。ASH-08 原未完成 Goal 和监控保持，真实日历与同日来源合格时优先安全保存 REF-05、串行交回焦点／资源；16:00 候选窗不替代实际来源资格。

## 2026-11-09 剩余二十一次必需键缺口补证

本轮从已交付的 75/96 继续恢复，新增五份不同原址的合格官方历史正文，**解决 20/21 次缺口**：独立历史 PUBLIC 为 **95/96**，完整观察点 **11/12**。原 30 来源、十二个截止点、96 次必需键和参数保持不变；33 份具名历史捕获进入显式派生配方。剩余一次为 `CN_CPI_NATIONAL_YOY:2024-09` 在 **2024-10-15 09:00（上海）** 前的历史资格，本轮没有证明其可用，不宣称全部解决。

| 新增合格公告 | 历史官方原址尾段 | 独立捕获时钟（上海） | 恢复的必需键次数 |
| --- | --- | --- | --- |
| PMI 2024-02 | `202403/t20240301_1947971.html` | 2024-03-02 06:39:14 | 4 |
| PMI 2024-03 | `202403/t20240329_1954065.html` | 2024-03-31 23:33:48 | 4 |
| PMI 2024-04 | `202404/t20240430_1955162.html` | 2024-05-11 14:06:24 | 4 |
| 全国 CPI 同比 2024-03 | `202404/t20240411_1954446.html` | 2024-04-11 09:50:46 | 4 |
| 全国 CPI 同比 2024-04 | `202405/t20240511_1955441.html` | 2024-05-13 07:19:53 | 4 |

所有原址均在 `https://www.stats.gov.cn/sj/zxfb/` 下；真实原址由历史索引或捕获的官方目录确认，再核对 CDX 摘要、正文、时钟及同一公告身份。历史可用时间仍取公告次日规则与捕获时钟的较晚者，表中捕获时间没有直接冒充首发或系统接收时间。3 月 PMI 的原 URL 使用 3 月 29 日建稿路径，公告日期仍为 3 月 31 日；仅按发布日期拼 URL 会漏掉它。两份同日 PPI 正文因标题／指标不符被拒绝，未用相近数字代证 CPI。

**受限旧址契约。** 现有离线入口增加 `alternate_documents`：完整文档描述须列入哈希绑定的目标冻结清单；捕获原 URL 必须等于文档 URL 的 HTTP/HTTPS 等价形式，并列入允许地址；标题、公告日期须与原公告相同，指标、单位、解析器及唯一目标键仍严格核验。正文摘要、CDX、时间顺序与截止拒绝规则不变。保留真正原址作为 `source_record_id`，没有把旧址正文伪装成当前 URL，也没有让当前下载字节自动合格。[新派生配方](ref05-history-gap21-20261109.json) 绑定当前代码和新增证据；旧配方、旧原件及其源码身份保持只读。

**唯一剩余缺口。** 2024 年 1–9 月、11–12 月观察点均为 8/8、PUBLIC manifest verified；10 月为 7/8、blocked，missing／unknown 各 1 次且重叠。9 月 CPI 既有 10 月 27 日捕获仍晚于该截止点。新核对的国家统计局政务服务、信息公开入口和英文发布索引均未给出合格截止前捕获；英文页面自述日期 10 月 14 日不等于已证明当时字节。Common Crawl `CC-MAIN-2024-42` API 发生 504 后，使用同一公开索引的 17 次有界 Range 请求定位并验证完整目标 CDX 分块，未找到该精确原址；未下载整个索引或 WARC，未关闭 TLS。这些结果仅说明所查地址／窗口／抓取批次没有提供合格证据，不推断全球不存在存档。后续须提供该键在截止前的具名、可校验官方历史正文；本轮不继续盲重试，也不倒用 10 月 27 日正文。

**验证及交付。** 新增 11 项旧址契约测试；正例先真实失败，实施后 11 项新测试与 21 项受影响既有测试共 **32 项通过**，其余 **25 项未变化测试复用**。Black 仅改排版，AST 哈希证明语义未变，未因此重跑测试。Ruff、Black、isort、增量 mypy 与债务上限均针对本次改动验证。新原件哈希、双次确定性重放、治理检查、候选／提交一致性和精确 CI 统一进入 `artifacts/ref05-history-gap21-20261109/validation-index.json`；完整原件仅本机持有，Git 中交付代码、契约测试、派生配方及本节结论。

```bash
python scripts/replay_ref05_public_evidence.py --recipe docs/reviews/ref05-history-gap21-20261109.json --evidence-dir artifacts --output artifacts/ref05-history-gap21-20261109/replay-new.json
```

四项原缺口的历史记录均保留：前轮两项 CPI、本轮 PMI 2024-02、03 现已取得历史 PUBLIC 资格；它们及其余来源的首发、修订完整性和历史 SYSTEM 时钟仍未知。来源自述 96/96 与独立历史 95/96 分开；SYSTEM 仍为 0/96、全部 SYSTEM manifest 受阻。没有 Regime／收益／OOS 计算、canonical/provider/生产写入、购买、部署或 deferred 恢复；REF-05 active 和整单退出门不变。ASH-08 原 Goal／监控不变，真实日历与同日来源合格时优先安全保存并串行切回，候选时间窗本身不构成资格。

### 2026-11-09 唯一剩余 CPI 截止点的增量取证交接

接续已交付 `2ebd8ea21fe297bc021b74806f70e6d2ef40935d`，只查询 `CN_CPI_NATIONAL_YOY:2024-09` 在 2024-10-15 上海 09:00 前的新证据路线。**未取得新的合格历史正文，最后一次缺口仍未补齐**；独立历史 PUBLIC 仍为 95/96、完整观察点 11/12，10 月仍为 7/8、blocked。原配方、33 份历史正文、源码、测试、参数及 registry 均未修改。

| 新查路线 | 实际结果及适用限制 |
| --- | --- |
| 原公告附带 Excel、三张图表；统计局同期解读；政府网客户端解读及英文报道 | 七个精确 Wayback 地址及一个解读目录查询未返回截止前捕获。附件地址从已有官方正文提取，未用文件名日期代替捕获时钟。 |
| Common Crawl 2024-42 | 同期解读、当前英文公告、两处政府转载及英文发布月目录共五项查询返回 404／无捕获。另复用已下载 CDX 分块检查中文月目录，无匹配；未重复下载分块。 |
| Arquivo.pt | 中文发布、解读两个月目录的限定窗口查询返回 200 空结果；只说明这两个查询未取得原件。 |
| Archive.today | 该 CPI 精确地址只列出 2025-07-11 存档，晚于截止；月目录两页共 23 个地址未提供截止前候选。解读页、英文公告、英文月目录及政府英文转载查询无结果；未将晚存档纳入配方。 |
| ALFRED | 中国全国 CPI 同比序列历史下载入口两次连接超时，未取得 vintage 正文，资格未知；搜索摘要和当前序列页面不作历史证据。 |

[Internet Archive 官方恢复公告](https://blog.archive.org/2024/10/18/internet-archive-services-update-2024-10-17/)确认该月曾因攻击停服，随后恢复 Wayback、Archive-It 和抓取。这是与目标窗口重合的服务背景，**不能推出全球无存档，也不能替代目标正文及独立时钟**。后续只在出现新的具名历史正文／可信版本档案及其截止前时钟时继续接入；不重复此次已穷尽地址查询，不放宽截止或把独立转载的当前日期当作捕获证明。

本轮只交付两份既有 Markdown 中的增量结论及本机原件索引 `artifacts/ref05-cpi-sep-final-20261109/validation-index.json`。索引绑定前次交付、当前未变输入和新查询原件；复用前次 32 项通过测试、25 项未受影响测试、类型／格式门禁及确定性重放，不重跑它们。本次只核验新增取证记录、文档差异及新提交的五项精确 CI；没有新生产实现或新合格配方，取证交接不等于缺口解决或 REF-05 整单完成。四项原历史缺口记录、首发／修订完整性／SYSTEM 未知全部保留，SYSTEM 仍为 0/96。ASH-08 原 Goal／监控与真实合格来源优先切回规则保持，不以候选时间窗替代资格。

### 2026-11-09 正式停止重复补证与受限研究输入评估

Owner 明确按“工程已交付、最后一项外部历史证据受阻、无新线索不再重查”正式收口。接收提交 `e49cd8760f66fb77b7839116e35d3185e96e1584` 的五项精确 CI 和交接索引；registry v332 登记停止条件，REF-05 整单仍 active，原退出门不变。唯一 CPI 缺口保持 `blocked_external`，不因新 session、日期变化或一般性服务恢复重复查询。只有新的具名历史正文、可核验捕获／版本档案或可信历史交付记录，才触发该键的定向核验；不得把当前页面日期、数值相同或晚存档作为解除依据。

**已接续并完成的有界事项：受限研究输入一致性评估。** 冻结并核验前次交付索引、历史投影、十二点来源自述诊断、原配方／网格及算法身份，只对已有结果做逐键比较。本轮没有新网络请求，没有重新解析全部原件、重跑测试／重放或计算 Regime／收益／OOS。

| 核对项 | 结果 |
| --- | --- |
| 原十二观察点、96 次必需键与单位 | 全部一一对应，网格和参数未变 |
| 有独立历史资格的输入数值与既有诊断输入 | 95/95 相同，0 项不同；另 1 项比较仍未知 |
| 完整观察点的输入向量 | 11/11 相同，可引用既有数值诊断，未新建或晋级 manifest |
| 既有来源自述标签的描述性计数 | 十二点为 Deflation 8、Recovery 4；其中历史输入完整的十一点为 7、4；10 月单列为来源自述 Deflation |

上述标签计数只描述既有输出，不是收益、时间占比、样本外表现或 Regime 增量价值。晚于截止的 CPI 版本与当前数值相同，也不能证明截止前的可用性；全部修订史和精确首发继续未知。十一点是原十二点中的完整子集，原观察网格没有删去 10 月，亦没有把十二点结果改写成全通过。

**历史数据的适度豁免按用途实施。** 沿用本计划 11/08 已授权的来源自述 PUBLIC 研究政策：允许具名官方公告、单位／内容校验和保守来源自述时间支持探索性诊断，报告必须区分来源自述与独立历史证据，并单列缺口。本轮没有授予新的概括性豁免；不豁免真实数值／单位／来源完整性，不将未知改成已证明，不回填 SYSTEM 时钟，不由此取得严格历史 PIT、完整十二点历史资格、OOS 增量价值或生产资格。四项原历史缺口记录及所有首发／修订完整性／SYSTEM 未知原样保留。

本机唯一新增索引为 `artifacts/ref05-research-use-20261109/validation-index.json`，包含冻结输入、逐键比较 `assessment.json`、执行脚本原件、适用治理检查、候选和精确 CI；旧阶段原件只读。本轮没有待整合生产实现。后续有界事项应转向原预注册方案的市场价格／公司行为／交易日历／成本／比较器可行性和缺口，不再围绕同一 CPI 空查询循环；当前仍不能识别 Regime 增量价值。ASH-08 原 Goal／监控保持，真实日历与同日来源合格时优先安全保存并串行切回，原显式 `published_close` 和完整 V8 门不变。

### 2026-11-09 最小市场链路与比较器可行性验收

接收正式头 `6abf6394ac4efb5566eb5ddbb4fb70f9b05a64c4`，实际设置独立有界 Goal。结论：**既有存量数据的只读贯通核对已完成；所核材料不足以运行合格的无／有 Regime 比较，增量价值仍不可识别。** 本结论仅覆盖下列冻结本机快照及所列源码／配置入口，其他未检快照、远端数据和历史原件的覆盖仍未知，不宣称全系统没有这些数据。

**冻结场景 `REF05-MARKET-FIRST-INTERVAL-2024`。** 在查看目标窗口的市场价格前，选择原十二点网格的首个区间：2024-01-15 与 02-15 上海 09:00。读取窗口固定为 2023-10-01 至 2024-02-20，供既有 `ma_cross` 最少 60 点的预热候选及下一 session 核对；不假定窗口中有 60 个真实交易日，不因结果更换区间。策略候选为既有 `StockSelectionBacktestEngine`／`StockScreener`，绑定本机四条 `config_stock_screening_rule`（id 1–4）及评分配置原件；四条规则创建于 2026 年，只是当前研究定义候选，不冒充 2024 年部署版本。历史池非空成员清单、无 Regime 对照规则、配对处理版本、批准资金／仓位参数均未绑定，冻结为 `null` 并阻断，不凭默认值补齐。

双方合同要求使用同一历史股票池、评分与持仓方法、现金／不可成交处理、输入版本、成交规则及费用，仅允许精确版本的 Regime 处理有差异。宽基候选 `000300.SH` 来自既有配置；简单比较器候选为已有 `ma_cross` 因子，短长周期、进出场／持仓／现金规则与批准版本仍为 `null`。因子元数据和日线的 MA 字段不能自动成为一套择时策略。未运行这些候选，也未注册 experiment／family／trial。

时间合同为：决策输入须在截止前可得；成交须使用截止后第一个真实合格常规 session 的开盘，并核对标的停牌、涨跌停、上市／退市、可卖数量等约束。实际 session／成交时间未证明即为 `null`；观察网格、星期规则和下一条价格日期都不能代替交易日历，不用同一根日线收盘价回填开盘成交，不把 `fetched_at` 当历史可得时间。费用须绑定有效期、佣金与最低额、卖出税、过户费、滑点及计费位置；双方使用同一政策。唯一现有账户费用行仅作证据，不采用其值或源码默认费率作为已批准研究政策。任一共同必需输入缺失即阻断配对场景，保留原因，不静默删日期、前填、补零或用空集合获得覆盖率；真实日历／池分母未知时覆盖率也为 `null`。

| 材料 | 已证明的真实证据 | 未知／受阻及含义 |
| --- | --- | --- |
| 宏观参考 | 只引用原评估中两点各 8/8 的已核输入及既有 Deflation 数值诊断，原件 hash 绑定；没有新计算 | 首发、完整修订史、历史 SYSTEM 仍未知；两点同一状态不支持增量价值或样本充分性结论 |
| 底层策略与配对 | 源码有 Regime→筛选规则路径；本机四条当前规则与评分配置可读取 | `strategy`、参数版本、脚本配置均 0 行；没有精确中性对照／同策略 treatment 绑定，不能把固定某一 Regime 当“无 Regime” |
| 历史股票池 | `equity_stock_pool_snapshot`、`data_center_asset_group_revision` 均 0 行 | 非空历史成员、退市与进出池证据缺失；当前存量两只股票不是冻结研究池，不据数据存在选择幸存者 |
| 价格／来源 | 实际快照有 49,782 条 canonical 价格；固定窗口有 `002493.SZ`、`600660.SH` 各 90 条、90 个观测日期，均标记 `tushare/1d/none/accepted`；OHLC 有限正值及区间关系通过，无自然键／修订号重复 | 180 条原始响应 hash、来源记录 ID、采集批次全部缺失；采集时间在 2026-05-13。只能证明真实存量行及其自述来源，不能证明原始 provider 字节、历史可得性或修订完整性；`accepted` 不替代这些证据 |
| 复权／公司行为 | 窗口内仅不复权日线；旧 `equity_stock_daily` 同窗口 0 行；基准公司行为表 0 行 | 分红／拆并股／复权因子有效版本与可得时钟未证明，不假设“无事件”或复权因子为 1 |
| 日历／可交易时点 | 源码已有 `ExchangeCalendarSnapshotFactModel`；此本机快照缺其物理表，基准日历表 0 行。1 月 15 日有价格，2 月 15 日无价格，后一个观测日期为 2 月 19 日 | 缺真实交易 session、盘中时间与标的可交易限制；未迁移／补表，未把 2 月 19 日认定为合格成交日。源码能力不等于此快照可用 |
| 宽基持有 | active development runtime profile v2 与旧设置均指向 `000300.SH` | 固定窗口内该代码 0 条价格；核过的两个常见别名也无窗口覆盖。现有该代码 134 条记录在 2026 年；基准定义表 0 行，价格／全收益口径、分红处理及可交易代理未绑定，指数不能直接充当成交标的 |
| 简单比较器 | `factor_definition` id 27 为 `ma_cross`，最少 60 点、`allow_missing=false`；源码初始化有同名元数据 | 在所核定义及策略／脚本表中没有完整周期、信号、仓位与现金／成交版本；不从 `ma5/20/60` 自行拼出策略 |
| 费用／登记 | `trading_cost_config` id 1 创建于 2026-03-15，可读到佣金 0.00025、最低 5 元、卖出税 0.001、过户费 0.00002 | 这是本机账户配置值，未核为 2024 年政策、统一研究批准或实际费率；滑点和现金处理未绑定。基准成本表、experiment／family／trial 及历史 Regime definition／receipt 表均 0 行 |

**真实只读贯通结果。** 对既有 `db.sqlite3` 使用 `mode=ro`、`PRAGMA query_only=ON`，SQLite backup 到本事项新目录后只查该快照，未启动 Django 或 provider。将两点既有宏观参考与冻结窗口的实际 180 条价格逐项连接核对：每只股票在两截止日前分别有 69／88 个观测日线，但没有可验证 session 分母；两个检查点均输出 `blocked`、9 个稳定缺口原因、`fill_eligible=false`，没有下单、收益、OOS 或 Regime 计算。这是读数／缺口检查的完成，不是交易链路或投资实验通过。没有合成夹具、外部采集、数据库迁移或生产／canonical 写入。

下一有界输入应是已存在且具名的历史池与市场原件快照（含日历、公司行为、价格版本／可得时钟、基准），或精确已有的中性／Regime 配对、简单比较器和有效费用合同。任何一类单独补齐都不解除其他阻断；即使本区间全部可读，仍须原预注册样本／walk-forward／OOS 门。本次停止在上述缺口，不扩采、不采购、不恢复 deferred 事项，也不重开 CPI 旧存档路线。

唯一验收索引为 `artifacts/ref05-market-feasibility-20261109/validation-index.json`，记录本机原件、真实候选、命令、失败／缺表结果、适用治理检查与最终精确 SHA 的五项 CI；本机快照和完整日志不入库、不声明远端持有。固定关键原件如下；未变生产代码、配方、测试和历史数据的旧验收按交接身份复用，本次不重跑旧重放、计算或业务测试。正式提交只包含本节、现有计划及 registry 的范围登记，没有待整合生产实现。

| 本机原件 | SHA-256 |
| --- | --- |
| `artifacts/ref05-market-feasibility-20261109/local-readonly.sqlite3` | `9f78b26f7e81dbe66ea5b284b8ab519307fb768ff1bbccdbd0f9e3aff420d9c5` |
| `artifacts/ref05-market-feasibility-20261109/freeze.json` | `f2939319abd3ebe14d75a47d8ac10db029f0d560a3ccd21b9759a381edb2d5d5` |

本事项完成不关闭 REF-05 整单；历史 PUBLIC 独立 95/96、来源自述 96/96、SYSTEM 0/96、原四项记录及 CPI 单项 `blocked_external` 不变。ASH-08 原 Goal／监控与真正合格来源优先串行切回规则保持，上海 16:00 仅候选窗，不因本研究合同放宽实时门；不部署或授予生产资格。
