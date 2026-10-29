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
