# A 股执行规则 V3 与结算参数合同

V3 将冻结的 [V2 执行规则](a-share-execution-constraints-v2.md)与独立版本的结算政策组成一个不可变配置包。它是 Risk-owned 参数合同，不是 Agent 下单协议，也不计算或释放可卖股份。当前实施状态见[计划 19.9](../plans/a-share-usability-implementation-plan-2026-10-16.md#199-原生-postgresql规则退役与-v3-参数检查点)；仓储接线与模拟成交事务分别验收。

实现为 [Domain](../../apps/risk_center/domain/execution_settlement_v3.py)、[Application](../../apps/risk_center/application/execution_settlement_v3.py)和[严格 JSON codec](../../apps/risk_center/infrastructure/ashare_execution_rule_codec.py)。旧 V1/V2 内容及 hash 不因升级而改写，研究优化里的结算参数及禁用标记不发生隐式晋级。

## 身份与内容

导入 manifest 的 schema 必须精确为 `a-share-execution-rules.v3`，顶层只有 `schema` 和 `rules`。每个包只有以下字段：

| 字段 | 含义 |
| --- | --- |
| `bundle_id`、`bundle_version` | V3 外层独立身份，不能借用嵌套 V1 身份表示政策换版 |
| `execution_submission_v2` | 完整冻结的 V2，含其 V1、价格笼子、允许阶段和原 hash |
| `settlement_policy_v1` | 下表规定的完整结算配置 |
| `content_hash` | 包身份、两个完整嵌套对象与各自 hash 的规范 JSON SHA-256 |

结算政策的所有字段都必填，`content_hash` 也须在编码后的外部对象中提供：

| 字段组 | 必需字段与约束 |
| --- | --- |
| 政策身份 | `policy_id`、`policy_version` |
| 精确范围 | `security_id`、`market`、`board`，必须与嵌套 V2 一致 |
| 结算参数 | `settlement_basis=CN_OPEN_MARKET_SESSIONS`，显式整数 `settlement_lag_sessions` |
| 规则绑定 | `bound_execution_rule_v2_hash`，等于完整嵌套 V2 的 hash |
| 来源 | `source_id`、`source_version`、`source_hash` |
| 时钟与有效窗 | `source_observed_at`、`source_available_at`、`effective_from`、`valid_until` |
| 完整性 | `content_hash`，绑定该政策的全部内容 |

lag 没有业务默认值。0 是显式当会话可用的配置值，不从 ETF 或其他资产名称推断；10,000 的上限只限制未来日历展开的资源消耗，不是交易所规则。政策来源与相应资产规则仍须另外验收。

政策有效窗必须包含在嵌套 V1 有效窗内；`source_observed_at ≤ source_available_at < valid_until`。所有标识是有长度限制、不含空白的明确字符串，hash 是小写 SHA-256。外部时间采用规范 UTC `Z` 文本；重复键、未知或缺失字段、非有限数值、布尔 lag、非规范嵌套 Decimal 和 hash 不一致均拒绝。

## 时间与读取

包的 `effective_from/valid_until` 是两个配置有效窗的交集，`source_available_at` 取较晚的来源可获得时间。`latest_source_observed_at` 和 `oldest_source_observed_at` 分别表达最新及最旧观测；这两个聚合不替换嵌套对象中的各自时钟，也不证明输入新鲜。不能以较新政策掩盖旧规则来源。

Application 注入 `ExecutionSettlementV3ReadPort.get_effective_settlement_bundle(security_id, as_of)`，返回 `ExecutionSettlementV3ReadRecord(bundle, recorded_at)`。`recorded_at` 是配置进入本系统的知识时间，与上游观测或可获得时间分开。读取要求证券一致、源观测及可获得时间和 `recorded_at` 不晚于 `as_of`，且 `as_of` 位于包的有效窗内。缺记录发布 unavailable，类型、hash、范围或时间不一致发布 corruption；禁止读取时改时间或重算 hash 掩盖损坏。

单表接线应将 V3 外层身份、交集有效窗与最晚可获得时间映射到既有规则行，冲突检查、历史读取与退役共用相同头字段。V1/V2 读取遇到 V3 不自动剥出旧版本；调用方须显式使用相应版本入口。换版和恢复采用新包版本，不能修改旧行或政策。

## 成交与验收边界

本合同不证明交易日历完整、交易会话存在、账户余额可信或结算已完成。ASH-03 必须按有来源的开市会话计算释放日，在同一受锁事务里处理账户、持仓、待结算成交、现金及费用，并验证重复和并发释放。历史实际成交镜像不得再次计费，旧可卖量也不能通过该配置自动重置。

V3 Domain 的局部覆盖与测试只证明配置行为。正式来源、单表仓储、普通买卖全部调用方、迁移、PostgreSQL 并发和用户任务均须按各自候选验收；不能凭 manifest、包 hash 或本地测试打开研究或实盘权限。
