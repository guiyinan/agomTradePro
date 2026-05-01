# `docs/plans/alpha-exit-loop-2026-04-30.md`

## Summary

为“Alpha 知道买什么后，系统如何知道什么时候卖”补一份可直接实施的方案文档，目标路径默认定为 `docs/plans/alpha-exit-loop-2026-04-30.md`。  
本方案按你选的范围执行：`Full Exit Loop`，并采用 `Suggest Then Execute` 模式。

目标是把现有分散在 `alpha / signal / decision_rhythm / simulated_trading` 的退出能力统一成一条闭环：

- 买入时必须带可跟踪的退出契约
- 持仓期间持续跟踪证伪、风控、宏观/Policy/Pulse、Alpha 衰减
- 人工/工作流路径生成 SELL/REDUCE 建议
- 模拟盘自动交易路径在建议成立后自动执行卖出
- 继续保留通知、审计和人工复核入口

## Key Changes

### 1. 统一退出契约，禁止“只知道买入、不知道何时卖出”的可执行单

- 以现有字段作为 v1 标准退出契约，不新增新的外部主字段：
  - `source_signal_ids`
  - `invalidation_rule`
  - `invalidation_description`
  - `stop_loss_price`
  - `target_price_low/high` 作为止盈/减仓价格带
- `BUY / REDUCE / EXIT` 级别的可执行订单必须具备：
  - 非空 `invalidation_rule`
  - 非零 `stop_loss_price`
- 缺失时不允许进入“可执行”状态，只能保留为 `requires_user_confirmation=true` 的待补充计划。
- `dashboard` 里的 Alpha `invalidation_rule` 继续保留研究展示语义；只有当候选被提升为 `signal` 或 `transition order` 时，才进入可执行退出契约。

### 2. Recommendation 生成必须覆盖“当前持仓”，不能只看候选池

- 修改统一推荐生成逻辑：账户级 recommendation 的证券集合改为
  - `active candidates`
  - `current held positions`
  的并集，而不是只看候选。
- 对已持仓证券，沿用现有 `_determine_side()` 与综合分逻辑输出 `BUY / HOLD / SELL`：
  - `SELL` 代表明确退出
  - `HOLD` 且目标数量低于当前数量时，转为 `REDUCE`
- Alpha 衰减不单独发明第二套卖出系统，直接通过 recommendation 生成链路体现：
  - `alpha_score <= sell_alpha_threshold` 或综合分进入 SELL 区间时输出 `SELL`
  - 这样宏观、Policy、Pulse、Beta Gate、Alpha 分数都会落到同一条退出判断链路
- `TransitionPlan` 继续使用现有 `stop_loss_price / invalidation_rule` 生成订单，不新增 v1 新端点。

### 3. 模拟盘自动交易接入统一退出建议，证伪任务继续负责“标记和通知”

- 在 `simulated_trading` application 增加一个退出建议协议，供自动交易引擎注入使用。
  - 建议形态：`should_exit / should_reduce / quantity / reason_code / reason_text / source`
- 默认实现由 `decision_rhythm` 提供，读取当前账户对已持仓证券的 unified recommendation / transition-plan 结果。
- `AutoTradingEngine` 卖出判断优先级调整为：
  1. `position.is_invalidated == True`
  2. 决策层给出 `EXIT / REDUCE / SELL` 建议
  3. 信号状态失效
  4. 禁投池 / Beta Gate / 风控阻断
  5. 现有账户级止损兜底
- `check_position_invalidation_task` 继续只做：
  - 标记持仓已证伪
  - 写原因
  - 发通知
- 真正卖出由模拟盘自动交易任务在下一次执行时完成，不把交易副作用塞进证伪检查任务。

### 4. 修正当前链路中的已知断点，保证 BUY→TRACK→SELL 真实打通

- 修复 `SignalQueryRepositoryProtocol.get_valid_signal_summaries()` 的实现语义。
  - 当前实现过滤的是不存在的 `status='valid'`
  - 应改为“当前有效信号 = `approved`”
- 保证所有从 signal/recommendation 进入模拟盘的 BUY 都传入可追溯 `signal_id`，使持仓稳定继承：
  - `invalidation_rule_json`
  - `invalidation_description`
- 决策执行路径接入模拟盘 BUY 时，不能只传买卖数量和价格；必须把来源 signal 与退出契约一并下传。
- 本期不把 `apps/account` 的独立止损止盈配置体系并入 simulated trading 主链路。
  - 该模块继续作为可选人工风险覆盖层
  - 主退出闭环以 `signal + decision_rhythm + simulated_trading` 为主

## Public Interfaces / Types

- `simulated_trading` 新增内部协议：
  - `PositionExitAdvisorProtocol`
  - 输入：`account_id`, `positions`, `as_of_date`
  - 输出：按 `asset_code` 聚合的退出建议列表
- `simulated_trading` 自动交易引擎新增对退出建议协议的依赖注入；未注入时回退旧逻辑。
- `decision_rhythm` recommendation 生成逻辑的输入语义变化：
  - 当 `request.security_codes` 为空时，不再只取 candidate securities
  - 改为 candidate + held positions
- 不新增新的外部 REST 主接口；复用现有 recommendation / transition plan / simulated trading 执行入口。
- `docs/plans/alpha-exit-loop-2026-04-30.md` 文档应明确记录：
  - SELL 触发来源
  - Suggest vs Execute 责任边界
  - 模拟盘与人工路径的差异行为

## Frontend / MCP 暴露补齐

- Dashboard 首页应新增“持仓退出监控”区域，和 Alpha 候选/待执行分开展示：
  - 已持仓证券当前 `HOLD / REDUCE / SELL`
  - 退出来源（`position invalidation / recommendation / transition plan`）
  - `stop_loss_price`
  - `target_price_low/high`
  - `invalidation_description`
  - 来源 `signal_id`
- Dashboard 导航与 API discoverability 需要补齐：
  - 首页系统导航暴露 `MCP 工具目录`
  - 首页系统导航暴露 `系统文档`
  - `/api/` 根路径暴露 `ai-capability`
  - `/api/` 与 `/api/dashboard/` 暴露 `mcp-tools` / docs 入口，便于 MCP 和文档被前端、测试和外部调用发现

## Test Plan

- `signal` 仓储测试：
  - `get_valid_signal_summaries()` 只返回 `approved`
  - `invalidated / rejected / expired` 不得进入可买候选
- `decision_rhythm` 用例测试：
  - 账户持仓不在 candidate 时，仍会生成 `HOLD / SELL / REDUCE` recommendation
  - `alpha_score` 低于 `sell_alpha_threshold` 的已持仓证券会输出 `SELL`
  - 缺少 `invalidation_rule` 或 `stop_loss_price` 的非 `HOLD` order 不能进入可执行态
- `simulated_trading` 用例测试：
  - BUY 后持仓继承 `signal_id + invalidation_rule_json`
  - `position.is_invalidated=True` 时自动交易任务会优先卖出
  - 决策层给出 `REDUCE / EXIT` 时会产生正确卖单数量
  - 未注入 exit advisor 时仍保持旧卖出逻辑可运行
- 端到端场景：
  - Alpha 生成 BUY → signal approved → simulated BUY → position invalidation 触发 → 下一轮 auto trading 卖出
  - 已持仓证券宏观/Policy/Pulse/Alpha 衰减后 recommendation 变 SELL → 模拟盘自动退出
  - Dashboard research-only 候选仍显示失效摘要，但不会被当成可执行卖出命令

## Assumptions

- 文档目录按仓库现状使用 `docs/plans`，不新建 `docs/plan`。
- 计划文档语言默认用中文，命名沿用仓库现有“语义 slug + 日期”风格。
- v1 不新增全局 `take_profit_price` 字段；止盈沿用 `target_price_low/high` 与 SELL/REDUCE recommendation 表达。
- v1 不合并 `apps/account` 的独立止损止盈模块，只在文档里说明它是可选覆盖层。
- 模拟盘的自动执行发生在自动交易任务内；证伪任务本身不直接落交易副作用。
