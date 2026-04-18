# 首页 Alpha 改造成“账户驱动候选 + 可执行建议 + 历史回溯”方案

## Summary
当前首页 Alpha 固定查 `csi300`，这会把“研究排名”和“账户可执行建议”混在一起。目标改成：

- 首页默认按“当前激活组合”生成 Alpha 池，不再写死 `csi300`
- Alpha 池定义为“当前组合所属市场内的全可交易股票”，v1 默认 `CN A-share + 有最新估值/行情数据的股票`
- UI 严格分为 `Alpha Top 候选/排名`、`可行动候选`、`待执行队列`
- 每只票都显示 `买入理由 + 不买理由 + 证伪条件`
- 每次首页推荐都落库，可按组合、日期、股票、阶段回看历史记录和理由
- 首页保留最近推荐摘要，并新增独立历史页查看完整时间线

## Key Changes
### 1. Alpha 池从固定指数改为账户驱动
- 在 `apps/alpha` 增加 `AlphaPoolScope` 域对象，替代首页直接传 `universe_id="csi300"` 的做法。
- 新增 `PortfolioAlphaPoolResolver` 应用服务，输入 `user_id + portfolio_id + trade_date`，输出：
  - `pool_type=portfolio_market`
  - `market=CN`
  - `instrument_codes`
  - `pool_size`
  - `selection_reason`
  - `scope_hash`
- 池子生成规则固定为：
  - 默认取“当前激活组合”
  - 若用户切换组合，则按所选组合重算
  - 市场范围先按当前组合已持仓市场推断；无持仓时默认 `CN A-share`
  - 股票全集取“有最新估值/行情数据且可标准化代码的股票”
  - 不再按 `csi300/csi500/sse50/csi1000` 这种命名指数池驱动首页
- `QlibAlphaProvider`、cache provider、simple provider 的查询接口统一接受 `AlphaPoolScope`；缓存键改为 `scope_hash + trade_date + model_hash`，不再只依赖 `universe_id`

### 2. 首页改成“三层视图”，不再把排名当推荐
- 首页文案统一改为“候选/排名”，去掉“推荐股票”表述。
- `Alpha Top 候选/排名` 只展示研究层结果：
  - 排名、分数、来源、评分日、缓存/实时状态
  - 当前阶段标记：`仅排名 / 风控阻断 / 可行动 / 待执行`
- `可行动候选` 单独成区，只显示通过执行前风控且有建议仓位的标的。
- `待执行队列` 保持独立，只显示已经进入决策/执行链路的请求。
- 首页增加组合切换入口；切换组合会同时刷新：
  - Alpha 池
  - 风控闸门结果
  - 建议仓位
  - 最近历史摘要

### 3. 每只票补齐“买入理由 + 不买理由 + 证伪条件”
- 不新增 AI 自由生成逻辑，v1 采用“结构化规则 + 模板化解释文本”。
- `买入理由` 来自现有可复用信号：
  - Alpha score / 排名
  - Regime / Policy / Pulse 对齐情况
  - 是否已进入 actionable / pending
  - 现有 `reason_codes`、`human_rationale`
- `不买理由` 统一来自客观阻断项：
  - `PreTradeRiskGate` 不通过
  - 已有高相关持仓或仓位冲突
  - 已在待执行队列
  - 建议仓位为 0 或低于最小可执行阈值
  - Regime / Policy / Pulse 不匹配
  - 数据新鲜度或缓存回退触发降级
- `证伪条件` 统一走可回溯结构化字段：
  - 优先复用 `decision_rhythm` / `alpha_trigger` 已有 invalidation 字段
  - 对仅处于 Alpha Top 的标的，新增规则化默认证伪模板：
    - 分数跌出阈值
    - 跌出 Top N
    - 宏观/政策闸门失配
    - 风控闸门由通过变阻断
- 前端展示同时保留：
  - 结构化 reason code 列表
  - 一段人类可读解释文本

### 4. 增加账户级风控闸门和建议仓位
- 首页候选链路接入现有账户/策略能力，而不是另写一套：
  - `GetSizingContextUseCase`
  - `DecisionPolicyEngine`
  - `SizingEngine`
  - `PreTradeRiskGate`
- 对 Alpha Top 中每只票输出统一评估结果：
  - `gate_status`: `passed / blocked / warn`
  - `gate_reasons`
  - `suggested_position_pct`
  - `suggested_notional`
  - `suggested_quantity`
  - `risk_snapshot`
- “可行动候选”的准入规则固定为：
  - `gate_status=passed`
  - `suggested_position_pct > 0`
  - 不在 pending 队列
  - 证伪条件完整
- 若只满足研究条件但不满足执行条件，则停留在 `Alpha Top`，并明确显示“不买理由”

### 5. 历史回溯改成落库，不再只展示当前页
- 历史不直接复用一张现有表硬塞全部语义，拆成两层持久化：
  - `AlphaRecommendationRunModel`
    - 一次首页评估运行，按 `portfolio_id + trade_date + scope_hash + model_hash + source`
    - 保存池子摘要、评分日期、是否实时/缓存、回退原因、组合上下文
  - `AlphaRecommendationSnapshotModel`
    - 运行内逐票快照
    - 保存 `stock_code`、`rank`、`alpha_score`、`stage`、`buy_reasons`、`no_buy_reasons`、`invalidation_rule`、`gate_status`、`position suggestion`、`source_candidate_id`、`source_recommendation_id`
- `UnifiedRecommendationModel` 继续承载“进入正式 recommendation / request / execution”的后续链路，不替代首页排名快照。
- 首页增加“最近推荐记录”摘要区，默认显示当前组合最近 5 次 run。
- 新增独立历史页，支持按：
  - 组合
  - 日期
  - 股票
  - 阶段（排名/阻断/可行动/待执行）
  - 来源（实时/缓存/simple/etf）
  过滤和查看详情。

## Public APIs / Interfaces
- `AlphaProvider.get_stock_scores(...)`
  - 从 `universe_id: str` 扩展为接收 `AlphaPoolScope`
- Dashboard 新增/调整接口
  - 当前组合切换接口
  - 当前组合 Alpha 候选接口
  - 手动实时刷新接口，接受 `portfolio_id`
  - 推荐历史列表接口
  - 推荐历史详情接口
- 首页 DTO 新增字段
  - `pool_label`
  - `pool_size`
  - `selection_reason`
  - `requested_trade_date`
  - `effective_asof_date`
  - `uses_cached_data`
  - `cache_reason`
  - `buy_reasons`
  - `no_buy_reasons`
  - `invalidation_summary`
  - `gate_status`
  - `suggested_position_pct`
  - `suggested_quantity`
- 新页面路由
  - Dashboard 下新增独立“推荐历史”页
  - 首页历史摘要跳转到该页并带组合筛选参数

## Test Plan
- Unit
  - `PortfolioAlphaPoolResolver` 在有持仓、无持仓、切换组合、空市场数据时的池子解析
  - `AlphaPoolScope` 的 `scope_hash`、代码标准化、缓存键稳定性
  - 买入理由/不买理由/证伪条件的规则化生成
  - `gate_status -> stage` 映射是否正确
- Contract / API
  - 新首页 Alpha 接口返回 `pool_label/pool_size/cache_reason/gate_status` 等字段
  - 组合切换接口状态码与返回结构
  - 历史列表/详情接口内容类型、分页、过滤条件
- Integration
  - 一次 dashboard run 能同时落 `run + snapshots`
  - 实时失败回退到 cache 时，历史里能看到评分日期和回退原因
  - `Alpha Top` 与 `可行动候选` 严格分开，不会重复混排
  - 已进入 `DecisionRequestModel` 的标的只出现在 pending，不再继续显示为 actionable
- Template / UI
  - 首页文案从“推荐”变成“候选/排名”
  - 首页显示组合切换、池子说明、缓存日期/调用原因
  - 历史摘要与历史页链接正确
  - 历史详情中可看到结构化理由、解释文本、证伪条件、建议仓位、风控结果

## Assumptions / Defaults
- 默认组合范围：当前激活组合；如果存在多个激活组合，默认取最近更新的一个，并允许用户切换。
- 默认市场：当前组合持仓所属市场；若组合为空仓，默认 `CN A-share`。
- v1 的“全可交易股”定义为：代码可标准化、存在最新估值/行情数据的股票；不额外引入观察池产品。
- `不买理由` 采用规则化结果 + 模板解释文本，不接 LLM。
- 历史记录默认长期保留在数据库中，列表分页展示，不做自动清理。
- 手动刷新继续保留，但刷新的是“当前组合的账户驱动池”，不是固定指数池。
