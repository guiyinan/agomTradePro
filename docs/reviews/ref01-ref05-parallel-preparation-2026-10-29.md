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
