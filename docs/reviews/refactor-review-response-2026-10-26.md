# 数据层与模块边界重构评审回复

评审日期：2026-10-26（Asia/Shanghai）。来源：[原评审](<AgomTradePro refactor review 20261026.md>)。
执行入口：[重构与交付衔接计划](../plans/data-boundary-convergence-plan-2026-10-26.md)。

## 1. 结论与证据范围

**方向成立，删除方案和排期需要修改。** 版本并存、重复生命周期、业务所有权漂移和结构文档失真确实值得收敛。但模型数量不能证明业务价值，重复存储不必然是双真源，单 owner 也不意味着账户隔离、撤销、令牌权限和误操作保护都可以移除。先完成 M1，再逐族停写、迁移调用方、核对历史并退役；不先开展全库搬迁。

本次核对代码、迁移、现有测试定义、机器注册表和 Owner 决策，未连接业务数据库、未读取密钥值、未验证第二用户是否存在，未运行金融回测或重新宣称历史测试通过。开发会话仍在共享树推进，因此源码审阅不是一个已验收的发布候选。

静态快照基于 HEAD `ee63f20200e4fe22a972215f3c602cf5df777e51`；字典 SHA-256 为 `dbd5a9baed1babd974a5da89207fc03f39ffbca4eee3b9c92fdf018962964c85`。原件在本机忽略目录 `artifacts/refactor-review-20261026/source-inventory.json`，SHA-256 `1bd630b0887a69b6cd37bce2aa4cf346a01c7a08e170e6989f893a5ce525060b`；同目录 `inventory.py` 可复算。符号引用清单覆盖 account 模型在 apps 非 migration Python 文件中的静态引用，包含定义/导出，不能替代动态调用、SQL、数据库存量和外部消费者盘点。

字典的 42 个 app、596 个模型声明、9287 个声明字段与评审一致。account 的 71 个声明中有 11 个显式抽象类；research 的 96 个中有 16 个；data_center 的 79 个中有 4 个。**这些不是实际数据库表数，也不是 Django 运行时展开后的字段数。** 动态数量仍以生成投影及 `governance/governance_baseline.json` 为准，这里只留本次审阅快照。

## 2. D1–D9 逐项核对

| 编号 | 结论 | 理由 | 证据（路径 / 表 / 测试） | 建议修改 |
| --- | --- | --- | --- | --- |
| D1 | 部分同意 | 模型与字段统计复现；仅用表数推导治理成本或核心算法薄弱不充分。backtest 有 41 个 Python 文件，2 个模型不代表只有 2 项能力 | `governance/data_dictionary.json`；`apps/backtest/`；上述静态快照 | 补读写路径、改动频率、重复代码、用户流程耗时；业务成效用 OOS 实验验证 |
| D2 | 部分同意 | 30 个 `V\d+Model` 声明确有其事，但包含抽象类。“11 个多版本族”无法按原文口径复现；剔除显式 abstract、将无 V 后缀视作初版后，得到 7 个同名具体模型族 | `account_owner_assignment_*models.py`；`owner_tenant_authority_*models.py`；`simulated_trading/infrastructure/simulated_account_row_source*_models.py` | 先统一计数口径；版本号最高不代表已在生产启用；逐族确认引用与数据后退役 |
| D3 | 部分同意 | 当前主要用户场景确为单 owner；已有 SingleOwnerAuthorityPolicy，并非尚未建模。观察员只读分享实现确实存在，真实使用量未知；令牌撤销、同一人的不同账户、管理员误操作仍有风险 | `apps/account/single_owner_authority_policy_composition.py`；`apps/account/infrastructure/identity_models.py::PortfolioObserverGrantModel`；`owner_tenant_authority_v3_composition.py` | 冻结多租户扩展；保留最小身份/账户范围/只读权限/撤销合同；不凭假设删分享与授权 |
| D4 | 部分同意 | 95/91/91/46 个字段的统计成立，但数量本身不能证明 fail-open。已有 publication、typed reader、Domain 校验和数据库约束，不能概括为只有每个调用者自觉检查 | `apps/data_center/application/control_plane.py`；`publication_policy_activation.py`；`apps/broker_execution/domain/execution_authorization_contracts.py`；`governance/current_data_contracts.json` | 加强唯一读取边界及绕过反例；保留对外限制标记，内部冗余列仅在替代等价后删除 |
| D5 | 部分同意 | 151/138/73/24/22 的字段统计成立。实际存在 payload 解码、结构化投影和 seal 一致性校验，发生冲突会报 corruption，而非任选一份；成本高的判断值得验证 | `apps/account/infrastructure/_owner_tenant_authority_v3_repository_helpers.py::_restore_root`；`account_owner_assignment_evidence_v2_repository.py`；`apps/research/infrastructure/r4_promotion_codec.py` | 按模型明确“原件 / 查询投影 / 校验摘要”；先替换读写再删字段；不以禁止所有 payload 解码为目标 |
| D6 | 同意收敛、部分同意合表 | R4/R5 的 promoted/retired/rolled_back/expired 与前缀重放明显同构；R4 依赖宏观 R3/Portfolio record，R5 依赖固收相对价值结果与 outcome 集，不可丢掉领域差异 | `apps/research/domain/r4_promotion_lifecycle.py`；`r5_relative_value_promotion_lifecycle.py`；对应 `tests/unit/research/test_*lifecycle*.py` | 先提取纯状态转移和重放机制，保留 typed policy/证据与原表；试点等价后再决定合表 |
| D7 | 部分同意 | 业务 owner 需要统一；模拟持仓、真实持仓、券商观测并非同一事实。`StockInfo` 的行业等扩展也不等于重复资产身份 | `AGENTS.md` §3；`apps/account/infrastructure/portfolio_models.py`；`apps/simulated_trading/infrastructure/models.py`；`apps/broker_execution/infrastructure/models.py` | 使用第 5 节修订映射；先公开入口、单写入路径，后物理迁表，不手工写 module_map |
| D8 | 同意 | 文档仍写 8 个 ORM 文件、旧目录树、无条件“生产就绪”，确会误导；表头虽已有生成物链接，正文仍漂移 | `docs/architecture/project_structure.md`（审阅前）；`docs/VERSION.md`；`docs/architecture/MODULE_MAP.md` | 本批直接改为稳定原则与真源导航；历史内容由 Git 保留 |
| D9 | 部分同意 | 明文列及读取 fallback 仍存在，需退役。statement trigger 仅在 PG 安装，SQLite 不提供相同保证；项目已有专门 PG 测试与工作流。broker app 已安装，但默认 paper、自动执行关闭，不能从有表直接推导实盘已开放 | `apps/ai_provider/infrastructure/repositories.py::get_api_key`；`apps/account/migrations/0065_account_authority_generation.py`；`tests/component/account/test_account_authority_generation_postgres.py`；`.github/workflows/ci-publication-postgres.yml`；`core/settings/base.py` | 核验加密迁移和完整下单拒绝链；复用现有 PG 测试。可选 app 拆装须先处理迁移依赖，不能直接从 INSTALLED_APPS 删除 |

## 3. 十个问题的逐条答复

| 编号 | 结论 | 理由 | 证据（路径 / 表 / 测试） | 建议修改 |
| --- | --- | --- | --- | --- |
| Q1 | 部分同意 | 主要计数一致；实表口径、多版本族数量、纯 flag 防护、PG 验证现状及永久不自动下单的判断不成立或不完整 | 本文 §1–2；Owner approval-log 第 8 项后续澄清 | 以源码与后续 Owner 决定纠正推论 |
| Q2 | 部分同意 | 当前源码组合主要通向 Evidence V5 / Authority V3；旧版本仓储与 Facade 仍存在；不能宣布其无调用或可立即删 | 本文 §4；`account_owner_assignment_evidence_v4_composition.py`；`account_owner_assignment_evidence_v5_composition.py` | 静态引用、动态调用/直接 SQL、实际行/FK、归档重放全部核定后确定退役 |
| Q3 | 部分同意 | 代码显示 actor/user/RBAC 来源与 owner 范围绑定，用于防错误账户/撤销后的授权；无法由代码证明历史商业动机或真实第二用户。分享实现存在，使用未知 | `account_actor_authority_raw_source_models_v3.py`；`identity_models.py`；`single_owner_authority_policy_composition.py` | 只读核对配置与匿名计数，不读取 token/密钥值；未知使用量不当作零 |
| Q4 | 部分同意 | Data Center publication/control plane、研究解码/重放、broker execution 合同读取或强制限制。本轮未证实一个具体可利用的绕过路径，也未做全调用图证明 | `control_plane.py`；`publication_policy_activation.py`；`apps/research/infrastructure/r4_promotion_codec.py`；`governance/current_data_contracts.json` | REF-03 必测未发布、撤销、跨账户、过期、未知字段、错误类型及旁路读；静态 rg 无命中不等于全安全 |
| Q5 | 部分同意 | 在抽查 Authority V3 中 payload 反序列化为 typed record，投影与 seal 全量比对，冲突拒绝；不能推断所有模型相同 | `_owner_tenant_authority_v3_repository_helpers.py::_restore_root/_verify_row`；`account_owner_assignment_evidence_v2_repository.py` | 每族确认原件和投影；允许合法重放，不允许冲突时静默择一 |
| Q6 | 同意受限试点 | R4/R5 生命周期机制同构，业务证据不同；R6 Qualification、R7 analogy/scenario 等不能归入无类型万能 payload | `r4_promotion_lifecycle.py`；`r5_relative_value_promotion_lifecycle.py`；`state_model_qualification_repository.py` | 第一提交只抽状态转移/前缀重放，模型新增为 0；领域 schema 与状态机分别测试 |
| Q7 | 部分同意 | owner 表方向正确，但“模拟持仓归模拟模块”应定义为当前执行账本实现；组合/持仓/流水业务 owner 仍按 AGENTS 归 portfolio | 本文 §5；`AGENTS.md` §3；`docs/architecture/MODULE_MAP.md` | 先语义区分、单写入入口；保留旧表名/迁移身份兼容，不把搬文件算收敛 |
| Q8 | 部分同意 | 0065 对 SQLite seed singleton 后跳过 PG statement triggers；SQLite fixture/flush 测试不证明 PG 并发/ACL，已有 PG generation 专项 | `0065_account_authority_generation.py::install_source_triggers`；`tests/unit/test_sqlite_authority_generation_flush.py`；`tests/component/account/test_account_authority_generation_postgres.py` | 不全量切换所有单测；触发器、并发、角色、迁移必须在独立 PG 无 skip 验证 |
| Q9 | 部分同意 | `EXECUTION_MODE=paper`、binding `auto_execution_enabled=False`、can_trade/can_approve=False；取单必须命中已启用 binding。TradingControl 只是 kill switch，缺行不是“已禁止”。本轮未审完所有入口，未确认部署配置 | `core/settings/base.py`；`apps/broker_execution/infrastructure/models.py`；`broker_repository_agent_runtime.py` | 用完整资格链确认 fail-closed；对缺 binding/关闭/撤销/过期/直达端点/重连分别测试；不声称当前生产已安全验收 |
| Q10 | 部分同意 | 静态审阅能估工程拆分，不能给可靠日历工期；实际行数、迁移链和外部消费者仍未知 | 本文 §6；新主计划各退出门 | 按完整事项提交，每次退役一族；WP1/4 的数量上限改为调查后目标 |

## 4. Vn 族的当前源码边界与退役阻塞

下表“当前”指抽查的源码消费链，**不代表生产 current head**。原稿的 11 族定义不明确，因此列出全部可归一的并存具体族及有关单版本链，不遗漏没有 V1 后缀的初版。完整符号引用在本机静态快照；表内列的是代表入口。

| 族 | 当前源码消费 / 旧版状态 | 删除前需要解除的阻塞 | 代表证据 |
| --- | --- | --- | --- |
| OwnerAssignment Evidence | V5 被 Authority V3 组合；初版、V2–V4 仓储/Facade 保留 | 旧公开入口调用方、exact/history 重放、Subject/Receipt/FK、已记录 hash 兼容 | `owner_tenant_authority_v3_composition.py`；`account_owner_assignment_evidence_v[345]_composition.py` |
| OwnerAssignment Subject | V5 与 Evidence V5 配套；初版、V2–V4 保留 | subject 身份及 receipt/evidence 引用不可按新时间重造 | `account_owner_assignment_subject_v5_repository.py`；`account_owner_assignment_evidence_v2_repository.py` |
| OwnerAssignment ProvenanceReceipt | V5 被 Evidence V5 使用；初版、V2–V4 保留 | 来源证明重放、旧版组合入口、外键及归档读取 | `account_owner_assignment_evidence_v5_composition.py`；`account_owner_assignment_provenance_receipt_v4_composition.py` |
| OwnerTenantAuthority | V3 面向 Evidence V5；V1/V2 及撤销表仍有仓储/组合 | 当前身份、撤销/前驱、final fence、PG generation 所依赖关系 | `owner_tenant_authority_v[123]_composition.py`；`migrations/0065_account_authority_generation.py` |
| PhysicalAccountRowObservation | V2 由 V5 组合消费；初版模型仍在 | 新旧 observation 与实际账户行身份、时间和跨库语义 | `account_owner_assignment_evidence_v5_composition.py`；`physical_account_row_observation*_repository.py` |
| SimulatedAccountRowSource | V2 在 simulated_trading；初版仍有仓储 | 不属于 account；与 canonical creation / generation 图共同迁移，不能只删 account 表 | `apps/simulated_trading/infrastructure/simulated_account_row_source*_repository.py` |
| CanonicalAccountCreationBinding | V2 被 Evidence V5 消费；初版 allocation/binding 仍在来源图 | allocation/consumption claim、知识时钟、幂等首写与历史绑定 | `canonical_account_creation_consumption_repository.py`；`migrations/0047*`、`0048*`、`0065*` |
| ActorAuthoritySource / raw auth-user-RBAC source | 显式 V3，不能把同号多种 source 当多个版本 | 原始 actor 身份、认证状态、mutation epoch 与撤销校验 | `account_actor_authority_raw_source_models_v3.py`；`account_actor_authority_capture_composition.py` |
| RbacAuthorityMutationBinding / anchors | V3；没有依据认为是可以换成单一 bool 的旧租户表 | Django 权限变更与快照失效、一致读取 | `account_rbac_authority_mutation_binding_v3_models.py` |
| AllocatedPhysicalObservation / OwnershipReobservation | 分别 V3 / V1，语义不同 | 分配事实、所有权重观测与 Evidence 链 | `allocated_physical_account_row_observation_v3_models.py`；`canonical_account_ownership_reobservation_v1_models.py` |
| SingleOwnerAuthorityPolicy | V1 当前存在 | 服务器选择政策、owner/账户范围及撤销保护 | `single_owner_authority_policy_composition.py` |

不得先删历史 migrations。代码中没有查到调用、没有读取生产数据库、没有配置第二用户是三个不同事实；本次仅完成第一项的静态线索，不把后两项写成已证实。

## 5. 修订后的业务 owner

| 名词 / 事实 | 业务 owner 与写入原则 | 兼容处理 |
| --- | --- | --- |
| 账户身份、令牌、认证偏好 | account | 保留只读/写权限、撤销和显式账户范围；不与资金账户账本混同 |
| 组合、持仓、成交/现金流水 | portfolio | simulated_trading 编排模拟执行，既有模拟结算库先通过唯一适配器保留；真实/模拟账本不得混行；account 遗留表先封装后迁移 |
| 券商持仓/成交观测 | broker_execution 外部事实适配；归账由 portfolio | 观测不等于已对账持仓；手工成交补录保留原始证据、去重与真实发生时间 |
| 风险规则、状态、止损止盈政策 | risk_center | portfolio 保留持仓关联；strategy 提供策略约束；不在 account/TUI 复制规则 |
| 汇率事实 / 资产身份 / 行情 / 宏观事实 | data_center | Currency/资产分类先区分元数据；StockInfo 保留研究扩展；macro_factor 保留派生结果；不机械去掉 realtime 的任务/观测状态持久化 |
| 估值 | valuation 负责算法，data_center 存可溯源事实 | equity 消费并展示；现有值与算法输出逐项核对后迁写 |
| 筛选 | asset_analysis 负责用例，规则按含义归策略/研究 owner | 先盘点 filter/equity 的调用合同，不因同名直接合并 app |
| 研究与发布 | research 拥有研究生命周期；各事实 owner 发布其合格读模型 | publication pointer 不是统一万能授权；用途、时点、账户、来源、撤销和执行许可均须满足 |

`module_map.json` 是代码生成物，不能手工写“名词 → owner”政策。上表是目标职责，不宣称当前实现已满足；实现期通过公开端口、已有 architecture_rules/相关测试表达，生成器再反映实际依赖。

## 6. WP0–WP7 结论、规模与风险

以下为完整开发事项/commit 组的初估，不是发布日期承诺；不强制每组建 PR，也不新增分支。

| 编号 | 结论 | 理由 | 证据 / 执行落点 | 建议修改、估计与最大风险 |
| --- | --- | --- | --- | --- |
| WP0 | 部分同意 | 需要抑制无关结构增长；再造一套模型台账反而重复 | `REF-01`；既有字典生成器、架构增量门与治理基线 | 1–2 组；复用生成差值，区分 abstract/实表；新增模型须有当前用户任务或明确故障及退役替代说明。CI 尚未实现，不宣称已生效 |
| WP1 | 部分同意 | 账户域收敛成立；≤15 表、全部 Vn 两迭代删完缺少存量依据 | `REF-02`；本文 §4；EVID/DATA-18 原合同 | 4–8 组，先一个可退役族；风险为历史绑定、撤销和迁移兼容失效 |
| WP2 | 部分同意 | 唯一合格读取入口正确；publication 不等于执行资格 | `REF-03`；current-data 与架构门 | 2–4 组；风险为旁路/过期/未知类型漏检；API/SDK/MCP 的限制字段继续保留 |
| WP3 | 部分同意 | 消除独立可写的重复真源正确；payload/seal 不可一刀切 | `REF-03`；typed codec 与 corruption tests | 与 WP2 合批 2–3 组增量；风险为重放和完整性证明退化；不承诺封印表≤10 |
| WP4 | 部分同意 | 适合 R4/R5 纯状态机试点；先造七类通用表/JSON 容器可能重复过度设计 | `REF-04`；R4/R5 lifecycle tests | 3–5 组；先不加表，再决定迁表；风险为领域差异被泛化，research≤35 暂不采纳 |
| WP5 | 部分同意 | 单一写入 owner 正确；目标映射需按 §5 修订 | `REF-02/03`，配合 ASH-03/04/07/08 | 3–6 组，逐名词、先端口后存储；风险为跨 app migration/FK/历史账本破坏 |
| WP6 | 部分同意 | 明文退役与 fail-closed 复验应尽早做；已有 PG 能力直接复用 | `REF-06`；key encryption 与 PG/broker 相关现有测试 | 2–3 组；解密可用、幂等迁移、角色/并发与直接端点覆盖；不把数据库列存在等同于密钥已经泄露 |
| WP7 | 同意、修订实验范围 | 文档漂移立即修；Regime 增量价值应独立、可证伪地检验 | `REF-05`；既有 research experiment/MultipleTestFamily、backtest 入口 | 文档 1 组、实验 2–3 组；风险为修订后宏观数据冒充 PIT、窗口挑选、成本/成交假设；资料不足给出不可识别结论 |

如果由我排期：先完成当前 API/权限验证并提交，同时修文档、冻结非必要增长、盘点旧版和 PIT 数据；紧接 M1 普通用户的有内容正例与阻断反例，安全小项可独立插入。随后先统一读取边界和一个账户族的 writer/reader，再做停写与兼容迁移；R4/R5 先去重算法后评估合表。Regime 实验不等待全库重构，也不恢复整套 ASH-06。最终的删表由存量核对、回放、回滚和同候选证据决定，不由表数指标决定。
