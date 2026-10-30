# 当前身份用途的普通模拟手动交易

`POST /api/simulated-trading/accounts/{account_id}/trade/` 保留既有手动交易路由，BUY 和 SELL 都经同一个当前身份用途的 Application 与 simulated settlement UoW。该入口只向普通模拟账户记账；它不下发券商订单，也不宣称证券在当前盘中可成交。

## 请求与幂等

请求必须给出 `asset_type="equity"`、`action="buy"` 或 `"sell"`、正整数股数和必填的 Decimal `price`。价格来自本次用户请求，不由此入口拉取或保证行情报价。还要传 `Idempotency-Key` 请求头：这是调用方为同一用户操作生成并在网络重试时复用的稳定键，长度最多 128 个字符且不得含空白；服务端不会替客户端随机造键。客户端开始另一笔操作时应使用新的键。

相同 owner/account、相同键和完全相同的用户意图会返回同一条已保存交易，响应 `replayed: true`，不会再读取当前身份或重复记账。相同键绑定不同方向、代码、股数、价格或其他用户可见字段时返回 HTTP 409 和 `SIMULATED_TRADE_IDEMPOTENCY_CONFLICT`。首次成功响应为 HTTP 200，保留原 `trade` 字段并附 `replayed: false`。

缺失/无效 key、无效请求体、缺少当前用途配置或身份证据不可用会返回 JSON HTTP 400 `{success:false,error,code}`。账户不属于当前认证用户时保留既有 owner API 的 HTTP 403 与错误封套。重放仍要求 authenticated owner/account 一致，并核验保存回执与真实 owned trade 行。

## 当前身份配置与来源边界

配置项为 `config_center.market.simulated_current_reference_selection`，schema `normal-simulated-current-reference-selection.v1`，purpose 必须是 `normal_simulated_current_reference`。这是 OPTIONAL、NORMAL 的 Typed JSON 元数据：不设默认值、不 seed 空证券清单、不要求迁移物化。没有显式激活的 selector 时，此手动用途不可用；通用 Config getter 返回缺失，调用方 fail closed。

selector 必须逐证券给出内部 `security_id`、`asset_code`、供应商 `source_code`，并固定一个 snapshot 与 mapping 的 ID、版本、内容 hash 和记录 digest。reader 在同一请求知识 cutoff 读取当前 profile、匹配 snapshot 和 value，核对读取前后 profile/snapshot 未切换，并通过 Data Center 现有 default-alias snapshot/mapping 入口精确读取保存凭据及 retained raw evidence。它不会从代码后缀、资产代码、最新记录或默认值推断映射。配置中的 `max_local_reference_age_seconds` 是明确的本地 reference 年龄上限，不是上游数据来源时钟。

V2 当前用途 identity 保留嵌套 V1 source evidence 的原值。当前 `stock_basic` source 可能 `source_observed_at` 与 `source_available_at` 均为 `None`，`must_not_use_for_decision` 与 `must_not_execute` 也可能保持 `true`；本地 selector、snapshot/mapping seal 或请求时间都不会补写或清除此类上游字段。V2 只建立精确配置用途、known-at cutoff 与所选证券 occurrence 的半开本地年龄窗，让本次普通模拟账本事务使用显式映射的 market/board/exchange。它不把 Data Center source 转成通用决策数据、历史 PIT、行情或券商执行资格。

API serializer 限制 `asset_type` 为 equity；证券的具体范围仍由操作方的精确 selector、记录映射及 Risk 配置共同限定。该入口没有独立的交易所 allowlist，也不读取盘中停牌、ST、涨跌停或实时可成交状态。当前代码路径不自动接入自动交易、QMT 或真实成交导入。

## 结算与兼容

新 BUY 保存普通模拟 Risk V3、费用快照、正式发布日历及 V3 identity binding。CN open-market-session settlement 会把尚未到期的买入数量留在 pending 状态；SELL 受账本锁内 `available_quantity` 和 pending settlement 约束，只能使用已经可卖的数量。未知 legacy/broker holdings lineage 不由本接口推定成可卖；该入口也不回填历史证券映射或重建历史买入时点。

原手动 URL 与成功交易字段继续兼容，但现在必须显式传 header、equity 类型与 Decimal price。这个 endpoint 不回退到旧的 `ExecuteBuyOrderUseCase`/`ExecuteSellOrderUseCase`。Decision Rhythm 的模拟执行也经同一 owner-scoped 用例和结算 UoW，使用决策请求 ID 派生的稳定幂等键；用户必须已登录并拥有目标模拟账户。券商导入与 QMT 仍是独立路径。

实际证据分层：Data Center 原生组件测试覆盖真实 retained source 与实际 Config Center profile；HTTP caller 测试通过真实 Django ledger UoW，但 identity、Risk 与 calendar ports 是测试自有合成对象。两种证据不合并声称已经完成一个生产源、Config、HTTP、日历与交易账本的端到端资格证明。

## 显式分类选择器 V2

选择器还支持 `normal-simulated-current-reference-selection.v2`，purpose 与原 V1 相同。每个 item 除完整证券、snapshot、mapping 固定引用外，还必须显式提供非空字符串 `simulated_asset_type`。不按代码前缀、交易所或 board 推断资产类型，不给缺失项默认值；缺字段、布尔值、额外字段或重复身份均拒绝。原 V1 选择器解析及 canonical hash 保持，V1 不提供分类结果。

`build_current_reference_classification_reader` 返回绑定同一当前选择和原件的分类证据。读取前后仍核对 active profile/snapshot，重读精确来源和 mapping；类型、源引用、配置或本地窗口漂移均阻断。分类只增加显式类型绑定，不接通新的 HTTP、SDK 或交易调用方。未知上游时钟和原禁止标记保持不变。

专用当前用途 V2 identity 的本地窗口校验与嵌套 V1 的通用资格校验分别保留：前者允许已显式选择的普通模拟身份用途，后者仍拒绝受限源。选择器 V2、分类证据 V1、当前用途 identity V2 是三个不同的版本号，不能互相替代或据此认定源已可用于实盘。

## 精确平仓入口与调用方迁移

`POST /api/simulated-trading/accounts/{account_id}/positions/close/` 同样使用上述当前身份和普通模拟结算链路，方向固定为 SELL。现在必须显式给出 JSON 整数 `close_shares`、十进制字符串 `close_price`、`asset_code` 及 `Idempotency-Key` 请求头；例如请求体 `{"asset_code":"600000.SH","close_shares":100,"close_price":"12.3400"}`。可选 `reason` 默认为“平仓”。证券代码示例只说明请求格式。

旧的仅传证券代码、由服务器推算全仓数量或价格的调用需迁移。股数的布尔值、浮点数、数字字符串，价格的 JSON 数字、空白或指数表征，以及旧别名和多余字段均返回 JSON HTTP 400。所有者验证在构造执行用例前完成。缺少当前用途配置不会转入旧平仓服务；可卖量、费用、日历和风险规则仍按同一 UoW 校验。

首次成功为 HTTP 200，含 `success`、持久 `trade`、17 字段 `receipt` 和布尔值 `replayed`。回执绑定交易、账户、原键、请求 hash、方向、证券、数量、价格、金额、四项费用、总费用、结算状态和日期以及重放标志；SELL 的结算状态和日期均为 `null`，`total_cost` 为四项费用之和。此 API 执行回执从已保存的交易重建；手工路径不会因此生成订单预留或来源成交事件。

相同 owner/account、键及原意图返回同一成交与 `replayed=true`，全仓关闭后也可重放；不重新读取当前身份、时钟或日历。同键不同意图为 HTTP 409。输入或配置无效为 400，认证/权限保留原 401/403/404 语义，账本业务阻断为 422。结果或提交后读回无法确定时为 503，并带 `effects_indeterminate=true`；调用方应保存原数量、价格、原因及键进行核对和显式重试。

Python SDK 调用为 `client.simulated_trading.close_position(account_id, asset_code, close_shares, close_price, *, idempotency_key)`，MCP 平仓工具也必须接收明确股数、价格字符串和稳定键。SDK 使用现有单次 POST 机制，禁止自动重试及跟随重定向；真实 3xx/4xx 状态保留为类型化异常。损坏的 200 回执、网络中断或读回未知均不能展示为完成。close 专用 MCP 在未知结果（含已发出 3xx）时保留原确认和键，确定的 4xx 拒绝仍按原拒绝契约处理。

本入口只形成普通模拟账本交易。精确响应与同键重放不构成真实来源、实时行情、生产账户或券商成交资格。
