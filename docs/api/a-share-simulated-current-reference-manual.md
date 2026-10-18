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

原手动 URL 与成功交易字段继续兼容，但现在必须显式传 header、equity 类型与 Decimal price。这个 endpoint 不回退到旧的 `ExecuteBuyOrderUseCase`/`ExecuteSellOrderUseCase`。其他旧用例调用方、自动模拟、券商导入与 QMT 仍是独立路径，本合同不声称它们已切换。

实际证据分层：Data Center 原生组件测试覆盖真实 retained source 与实际 Config Center profile；HTTP caller 测试通过真实 Django ledger UoW，但 identity、Risk 与 calendar ports 是测试自有合成对象。两种证据不合并声称已经完成一个生产源、Config、HTTP、日历与交易账本的端到端资格证明。
