# A 股执行约束 v1

本合同定义 Risk Center 与独立 QMT Agent 共同使用的可交易性输入。它不是资金、账户权限、审批或实盘授权合同。正式 Broker Evidence 门禁仍独立生效。

实现入口为 [Risk Domain](../../apps/risk_center/domain/execution_trading_constraints.py)、[Application 查询](../../apps/risk_center/application/execution_trading_constraints.py)和 [Agent 校验器](../../qmt_agent/execution_constraints.py)；[JSON Schema](a-share-execution-constraints-v1.schema.json)提供字段格式投影，时效、哈希及业务关系仍由运行时校验。当前实施状态见 [A 股实施计划](../plans/a-share-usability-implementation-plan-2026-10-16.md)，不能由本文推定已完成真实供应商接入或正式交易验收。

## 线格式与数值

Envelope 的 schema 为 `a-share-execution-constraints.v1`，只允许以下六个顶层字段：

| 字段 | 含义 |
| --- | --- |
| `schema` | 精确版本；未知版本拒绝 |
| `as_of` | 服务端本次评估的知识截止时刻，不覆盖任何源观测时刻 |
| `rule` | 精确证券的规则及来源、有效区间、规范化内容哈希 |
| `market_evidence` | 同证券、市场、板块的日历、会话、状态和报价证据及内容哈希 |
| `order` | 精确订单字段及可选的股份证据 |
| `decision` | 由上述输入重算的状态、原因、订单身份和两个证据哈希 |

所有嵌套对象同样拒绝未知或缺失字段。时间使用带 `Z` 的规范 UTC ISO 8601，日期使用 `YYYY-MM-DD`。`security_id` 在本版执行合同中指精确的券商市场后缀证券代码，不能以数据库主键代替；未来若引入其他稳定证券 ID，必须增加明确的映射合同。

Decimal 在线上只使用规范固定点字符串，不使用浮点数或科学计数法；去除小数尾零，不保留负零，展开后最长 257 个字符。规则数量下限、步长、上限以及订单/股份数量必须是整数股。该长度限制是协议解析边界，不能作为证券单笔申报上限；实际数量上限来自规则配置。

XtQuant 价格参数最终使用 vendor float。适配边界先拒绝 float 原始输入和非整数数量，并核对 Decimal 到 vendor float 的十进制往返值；无法保持原申报价格的值在调用券商前拒绝，不能静默截断股份或舍入价格。

`content_hash` 为排除对象自身 `content_hash` 字段后，按键排序、紧凑 JSON、UTF-8、`ensure_ascii=False`、`allow_nan=False` 计算的 SHA-256。嵌套金额、数量和时间先按本合同规范化。Agent 对原字段及哈希重新校验，不能先丢掉未知字段再验哈希。哈希锚定内容，不证明供应商原文、操作员身份或执行授权。

## 规则与证据

`rule` 包含 `rule_id/rule_version/security_id/market/board`、买卖各自的 `minimum/step/maximum`、`sell_odd_lot_mode`、`price_tick`、规则来源 ID/版本/哈希以及 `source_observed_at/source_available_at/effective_from/valid_until`。业务值没有代码默认；未配置规则不能回退到全市场统一 100 股。

`market_evidence` 独立记录日历来源和有效窗、交易日、IANA 时区、会话开闭时刻及状态、证券状态、市场来源及源时刻、价格边界模式与参考价。证券、市场、板块必须与规则匹配。会话关闭、停牌、退市或未知状态均拒绝。当天没有行情记录不能推断为停牌。

源观测时刻必须不晚于可用时刻；本次知识截止点必须已获得证据且仍在有效期内。`effective_from <= as_of < valid_until`，会话区间也使用左闭右开边界。交易日以证据的市场时区解释。Agent 既核对原 `as_of`，又在本地提交时重验；本地时钟早于 `as_of` 时拒绝，不能把旧源时间改成本次计算时间。

价格边界状态必须显式区分：`LIMITED` 要求上下限均有可靠正值；`UNRESTRICTED` 表示来源明确证明无该类日边界；`UNKNOWN` 拒绝。`UNRESTRICTED` 不代表免除价格档位、申报价格笼子、会话、状态或其他检查。

本切片实现价格档位和日价格边界，尚未实现逐板块连续竞价价格笼子、全部订单阶段和真实来源读取；这些仍属于 ASH-02 退出条件。因此，当前 `ALLOWED` 只表示本版已表达的检查通过，不能自行成为正式 Broker 的准许依据。

## 订单与可卖股份

`order` 精确包含 `order_id/account_id/security_id/side/quantity/limit_price/sell_position_evidence`。只支持已声明范围内的整数股限价单，买卖方向只能为 `BUY/SELL`。Agent 接线时必须将这些字段与外层 leased order 精确绑定，不能只校验一份与实际委托不同的有效 envelope。

新 Agent 的提交路径要求 lease 携带 `execution_constraints`，以及明确带时区的订单和租约截止时间 `expires_at/lease_expires_at`；旧服务器缺少这些字段时拒绝新提交，不回退到星期判断或统一手数。服务端 ACK 必须明确接受同一订单；ACK 往返后再次核对约束、原租约/订单期限和本地 STOP。恢复查询、券商事实回传与对账仍独立处理已发生的事实，不因新单缺字段而丢弃成交。

所有卖出均需股份证据，内容包括 `account_id/security_id`、可卖和受限数量、完整性、来源 ID/版本/哈希及观测/可用/失效时刻。`COMPLETE` 必须显式给出两种数量；未知不能填零。证据必须属于本订单账户和证券，并在评估及提交时均有效；数量不得超过可卖量。

普通数量按该侧的 minimum、step、maximum 检查。`SELLABLE_BALANCE_TO_ZERO` 仅为低于 minimum 或不满足 step 的卖出提供余额例外：必须一次性申报全部已证明的可卖余额且受限数量为零，不能超过 maximum。`minimum=200/step=1/available=150/quantity=150` 也属于余额例外；只检查 step 会错误拒绝这种清仓。

`SELL_ODD_REMAINDER_ONCE` 为另一个明确配置的模式，要求该规则的 sell minimum 等于 step。卖出完整零股余数时，已证明的可卖余额减去本次数量必须恰为 step 的整数倍，同时受限数量为零；普通整手卖出继续按原数量限制检查，maximum 不能绕过。150 股可卖余额中的 50 股余数可一次卖出，299 股余额可卖 99、199 或 299 股，25/198/298 等拆分余数的数量不能据此放行。该算法没有交易所或板块默认启用值；规则入库必须绑定适用范围和正式来源。当前核对来源及此前错误测试的更正见[零股勘误](../testing/a-share-usability-ash01-odd-lot-erratum-2026-10-16.md)，不能据上交所示例自动启用其他市场。

BUY 可以携带结构正确的可选股份对象，但本版不消费其账户、证券或时效业务语义；资金、持仓数和组合约束由相应 owner 的独立检查负责。两端必须保持这一行为一致，不能一端把不参与买入判定的字段作为额外放行依据。

## 失败与授权边界

格式、类型、非有限数值、哈希损坏和结构不一致属于合同错误；结构正确但过期、未知或违反规则的输入产生拒绝结果。原因码稳定，不能用任意已有状态冒充未知状态。

服务端从受信任的 owner 端口读取规则、市场及账户事实后评估；客户端提交的 envelope 或风险快照不能成为 owner 事实。Agent 的独立重验用于缩小错误面，不能替代服务端重算。创建、审批、领取和提交时的当前身份、审批、风险授权、停止开关及券商事实检查仍须分别通过。

生产支持矩阵、当前源数据完整性和真实 QMT 能力必须另行验收。无规则、无源时间、无可靠状态或未验证板块时，应保留具体阻断原因，不能为了通过演示补造事实。
