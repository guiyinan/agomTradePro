# A 股执行约束 v2 候选合同

v2 在保留 v1 规则及市场证据原始 hash 的基础上，增加明确的交易阶段和连续竞价申报价格范围。它只描述可交易性；账户权限、资金与股份预留、风险授权、审批、全局停止和 Broker Evidence 门禁仍需分别通过。当前阶段与退出门读取[实施计划](../plans/a-share-usability-implementation-plan-2026-10-16.md)及其机器登记。

实现入口为 [价格范围 Domain](../../apps/risk_center/domain/price_submission_range.py)、[v2 组合 Domain](../../apps/risk_center/domain/execution_submission_v2.py)、[owner-read Application](../../apps/risk_center/application/execution_submission_v2.py)及 [独立 Agent 校验器](../../qmt_agent/execution_submission_v2.py)。[JSON Schema](a-share-execution-constraints-v2.schema.json)是格式投影，不能替代来源、时间、hash、规则关系或提交时检查。单表配置目录已支持按 manifest schema 区分 v1/v2，禁止错误版本读取和跨版本生效窗重叠。实际 Provider、全部消费者和真实环境仍须分别接入验收。

独立 Agent 的 [价格算法模块](../../qmt_agent/price_submission_range.py)由 [生成器](../../scripts/build_qmt_price_submission_projection.py)从 Risk Domain 及其 ExecutionSide 枚举生成，只保留标准库依赖，禁止手工改写。Domain 算法变更后运行 `python scripts/build_qmt_price_submission_projection.py`，再用 `--check` 校验精确字节；投影头记录规范 LF 的有效源摘要，输出也固定 LF。Agent 仍需独立核验线上类型、hash、源窗口、真实订单绑定和提交前状态；共享算法不使来源或执行授权自动成立。

## Envelope 与完整性

顶层仍为六个必需字段：`schema/as_of/rule/market_evidence/order/decision`；schema 精确为 `a-share-execution-constraints.v2`。v2 消费者不得把缺失阶段、盘口或参数的 v1 响应补成 v2。Decimal、UTC 时间、证券身份、未知字段及账户绑定继续遵守 [v1 合同](a-share-execution-constraints-v1.md)。

| 对象 | 必需内容 |
| --- | --- |
| rule | `execution_rule_v1`、`price_submission_range`、`allowed_stages`、外层 `content_hash` |
| market_evidence | `market_evidence_v1`、`stage`、`ask/bid/latest/previous_close` 四个报价对象、外层 `content_hash` |
| order | v1 的精确订单及股份证据字段 |
| decision | `status/reason_codes/order_id/rule_content_hash/market_evidence_content_hash`，两个 hash 绑定 v2 外层对象 |

外层 hash 使用排除自身 `content_hash` 后的完整规范 JSON：UTF-8、键排序、紧凑分隔、`ensure_ascii=False`、`allow_nan=False`。嵌套 v1 对象连同其原 hash 原样纳入，再分别重验；不能改写旧对象 hash 来冒充升级。同一基础规则下，笼子参数或允许阶段改变会改变 v2 外层 hash。

v1 `reference_price` 保留原有日边界检查用途；它不能代替四个方向相关报价。新增阶段及四个报价必须属于同一 `market_source` 观测及可用、失效窗口，来源适配器负责从真实原始输入绑定这些事实。把客户端字段或其他时间窗的盘口拼进对象后重算 hash，不能使它变成可信来源。

Application 的两个必需注入端口分别提供 `get_submission_rule` 和 `get_submission_market`，都接收同一个 `account_id/security_id/as_of`。缺少 v2 配置或证据时发布明确不可用错误，不回退到 v1，不替换源时间。输出构造和序列化都会重算判定并核对输入，不能重新绑定不同订单或证据。

Application 输入是未附带股份证据的订单意图：`sell_position_evidence` 必须为 null，BUY 也不能携带自报股份事实。
SELL 还必须注入 `ExecutionSellPositionProvider.get_sell_position(account_id, security_id, as_of)`，在读取市场证据前获取并验证精确账户/证券的 owner 事实。
缺 provider 或缺事实发布 unavailable；错误类型、损坏字段或身份错配发布 invalid；合法但过期、未来、缺完整性或不足的股份仍由 Domain 返回 DENIED。
生成后的 envelope 才包含 owner 读到的原始股份证据，低层 Domain 仍可接收完整类型化输入。
该端口尚未接正式 Broker/Portfolio 来源适配，不能将测试 provider 解释为真实股份验收。

## 配置与报价状态

`PriceSubmissionRangeRule` 显式给出 market、board、price_tick、买卖 deviation_ratio、买卖 widening_ticks、minimum_distance_ticks、lower_floor_ticks 和 rounding_mode。market/board/tick 必须与嵌套 v1 规则一致。参数没有代码业务默认，也不依据板块名称猜测；它们须作为 Risk 配置内容保留来源及有效区间。

每个报价对象只有 `state/value`：

- `PRESENT`：来源明确提供有限正 Decimal 价格。
- `CONFIRMED_ABSENT`：来源明确证明该项无报价，value 为 null。
- `UNKNOWN`：缺字段、不可靠或语义未确认，value 为 null。

四个对象均先验证结构。选择基准价时，BUY 顺序是卖一、买一、最新成交、前收；SELL 顺序是买一、卖一、最新成交、前收。只有 `CONFIRMED_ABSENT` 才继续下一项，遇 `UNKNOWN` 立即拒绝；选定之后，未消费的结构合法 UNKNOWN 不额外阻断。全部确认缺席时仍拒绝。选定价格须符合 tick，在 LIMITED 情形下也须位于当日日边界内。

## 范围计算与阶段边界

按显式配置计算单侧范围：BUY 取 `max(P × (1 + ratio), P + widening_ticks × tick)`；SELL 取 `min(P × (1 - ratio), P - widening_ticks × tick)`。先按 tick 四舍五入，再应用最小距离及卖出价格底限。实现使用精确整数/有理数计算，避免 Decimal 上下文造成隐式舍入。

首批核对依据为上交所 [2026 年修订通知及附件](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml)中的 3.3.14、3.3.17、6.8：普通股票与科创板的比例及 tick 扩展不同；将正价格的“四舍五入”实现为 `HALF_UP` 是明确采用并测试的工程解释。示例参数只是来源核对样本，不能自动成为某证券的启用配置。

价格计算器结果为 `CALCULATED/NOT_APPLICABLE/DENIED`，均不是执行授权。v2 整体评估首期只支持明确配置的 `CONTINUOUS`；允许阶段为空时所有提交均拒绝。集合竞价、临停或 UNKNOWN 不因价格笼子“不适用”而获得整体准许。符合日涨跌停边界的价格，仍可能超出连续竞价申报范围。

## 真实输入与发布限制

XtQuant 适配必须按[官方字段说明](https://dict.thinktrader.net/dictionary/stock.html)核对源时间、盘口与证券详情；日上下限取证券详情的 `UpStopPrice/DownStopPrice`，不能读取未证实存在的 tick 字段。阶段参考[官方 openInt 状态表](https://dict.thinktrader.net/innerApi/data_structure.html)。不同官方页面对 InstrumentStatus=0 的含义存在差异，不能仅据该值证明正常交易；未知代码保持 UNKNOWN 并记录，不映射成已知交易状态。

包版本、Agent wire 协议和 execution-constraints schema 是三个不同身份。新的包版本号不证明服务器已理解 v2；正式租约和提交必须识别实际能力并返回完整匹配合同。实际来源、数据库规则版本生命周期、全部消费者、兼容矩阵以及目标 Windows/XtQuant 验收尚未满足时，继续保留具体阻断；不能通过候选文件、单元测试或 fake 行程打开实盘。

心跳的可选 `execution_constraint_schemas` 是最多 8 个唯一、规范 schema 名称的 JSON 数组。省略时按空能力处理，保留旧 Agent 的健康上报和恢复用途；后续一次旧心跳会清空先前的能力声明，不沿用过期声明。lease 和 submitting 都要求当前已存的声明显式包含 `a-share-execution-constraints.v2`，缺失、错误版本或损坏字段以 `AGENT_EXECUTION_CONTRACT_UNSUPPORTED` 拒绝。包版本号不自动授予该能力，声明本身也不是证明、签名或执行授权；原有 Evidence 门禁保持拒绝。

候选 executor 新提交只消费 v2，不自动降级。缺合同、v1、过期、外层订单不匹配时在本地记账/ACK/券商调用前拒绝。ACK 必须严格确认并回显相同订单；往返后重新检查，本地行情和账户读取结束后再以新 UTC 时钟作一次不含网络 I/O 的最终检查，原租约不被 ACK 延长。

本地附加行情检查只接受明确 `xtdata.get_full_tick.lastPrice/time` 字段证据。源 tick 的毫秒时间需位于“v2 市场源观测时刻 ≤ tick ≤ 本次本地检查时刻”；读取期间产生的新 tick 使用读取返回后的时刻检查，不能用读取前时刻误判为未来，也不以采集时间替代源时间。该条件可能保守拒绝比批准证据更旧的不同来源报价；放宽必须另有显式执行策略。没有源观测日的本地上下限只作诊断，v2 内的日边界与阶段仍独立强制。本地窗口开关只能增加限制，不能绕过 v2 交易会话。
