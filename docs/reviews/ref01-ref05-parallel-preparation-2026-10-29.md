# 账户授权退役盘点与 PIT 实验准备结论

2026-10-29（Asia/Shanghai）。本事项按 [收敛计划](../plans/data-boundary-convergence-plan-2026-10-26.md) 和 [registry](../../governance/active_plan_registry.json) 的 `execution_focus.parallel_preparation` 完成 REF-01/05 只读准备。Codex 负责隔离输入、全仓复核和 REF-05；Kimi Code 2.4.0 负责授权模型族盘点，并依据补充调用链完成第二轮修订。这里只记录准备结论，不改变单元状态、M1 验收或生产资格。

## 已确认结论

| 范围 | 结论与实施含义 | 源码依据 |
| --- | --- | --- |
| 授权版本链 | Authority V1/V2/V3 分别组合 Evidence V3/V4/V5；最高版本不证明旧版已退役 | `apps/account/owner_tenant_authority_v{1,2,3}_composition.py` |
| 初版 Evidence | 定向搜索未找到四个初版用例类及 `DjangoAccountOwnerAssignmentRepository` 的额外直接生产消费者，可列为退役调查候选。三个共享异常仍被后续版本和 policy HTTP 入口导入，删除整个模块会破坏兼容 | `apps/account/application/account_owner_assignment_evidence.py:70`、`:525`、`:626`、`:868`、`:905`；`apps/account/infrastructure/account_owner_assignment_evidence_repository.py:71`；`apps/account/interface/single_owner_policy_api_views.py:15` |
| Authority V1 | 与初版 Evidence 是不同族，其 reader 绑定 Evidence V3。selector 缺省或 V1 scope 路径仍有静态消费链，不能据初版 Evidence 的调查结论删除 | `core/integration/system_audit_authority.py:258`；`apps/audit/infrastructure/system_audit_outbox_runtime.py:212`、`:295` |
| 发布消费者 | 数据发布激活、M1 参考价、财务 capacity、execution quote 及 quote pointer rollback 均消费 production authority capture；初始有界快照漏掉这些间接引用，二轮已修订 | `apps/data_center/publication_candidate_activation_composition.py:163`；`m1_reference_price_publication_composition.py:66`；`infrastructure/financial_capacity_publisher_runtime.py:421`；`execution_quote_publication_composition.py:213`；`execution_quote_pointer_rollback_composition.py:51` |
| PG 触发器 | 0065 为 Evidence V5、Authority V3 等 source 表安装 statement 级触发器；非 PG 跳过。旧建表 migration 未见触发器不能推导全链路没有触发器 | `apps/account/migrations/0065_account_authority_generation.py:18`、`:53` |
| PIT 复用 | 已有版本事实、冻结 manifest、精确 Regime receipt 与独立 proxy/label 可得时间，可复用既有能力；实际数据覆盖仍未知 | `apps/data_center/infrastructure/pit_models.py:49`；`pit_repository.py:41`、`:117`；`apps/macro_factor/infrastructure/data_center_pit_projection_adapter.py:168`；`regime_historical_assignment_adapter.py:80` |
| 宏观读取限制 | `get_series(use_pit=True)` 的日期过滤及空发布时间 fallback 本身不足以证明严格历史可得性、原始修订版本或质量。REF-05 不以此参数单独认定输入合格；本结论不声称发现线上绕过 | `apps/data_center/infrastructure/macro_fact_storage_repository.py:94` |

## 下一事项与未验证范围

REF-01 继续只读核对动态加载、SQL、CLI/Admin/SDK/MCP 和归档消费者。实施仍需集成焦点移交；先补用例及异常身份特征测试，保留兼容导出，再核真实行数、历史 hash、归档恢复与停写/切读条件。不能把静态无直接引用写成“无使用”或“可删表”。

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
