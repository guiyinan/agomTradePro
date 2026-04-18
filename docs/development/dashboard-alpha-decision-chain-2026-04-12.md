# Dashboard Alpha 决策链收束说明（2026-04-12）

> 补充更新：2026-04-18

## 目标

把 Dashboard 上原本并行展示的两个板块统一为一条可追踪的业务链：

`Top 10 选股结果 -> 可行动候选 -> 待执行队列`

这次收束覆盖四层：

- 后端查询：统一聚合为 `AlphaDecisionChainQuery`
- 前端页面：用同一份链路数据渲染 Top 10 和 Workflow
- API / SDK：暴露统一 canonical 读取入口
- MCP：提供同名只读工具，避免继续拼接旧接口

## 业务口径

### 1. Top 10 选股结果

- 来源：`AlphaVisualizationQuery`
- 含义：当前交易日 Alpha 排名结果
- 回答的问题：`现在谁分高`
- 首页账户视角只读取账户池 `scope_hash` 专属缓存或真实账户池推理结果；如果专属结果缺失，不回退到硬编码股票池、静态名单或默认 ETF，Top 区块保持为空并提示触发实时推理。

### 2. 可行动候选

- 来源：`DecisionPlaneQuery._get_actionable_candidates()`
- 含义：已经进入 Workflow 且状态为 `ACTIONABLE` 的候选
- 回答的问题：`哪些标的已被流程收束到可推进`

### 3. 待执行队列

- 来源：`DecisionPlaneQuery._get_pending_requests()`
- 含义：已形成审批/执行请求，仍处于 `PENDING` / `FAILED` 的队列
- 回答的问题：`哪些标的已进入 Step 5 等待执行`
- 它不是当前 Alpha Top 排名的产物，而是历史决策请求的执行状态视图；测试、MCP smoke 或历史 workflow 生成的请求也会出现在这里，直到执行、失败后重试或取消。
- Dashboard 上的“丢弃待执行”会调用 `POST /api/decision-rhythm/requests/{request_id}/cancel/`，将状态改为 `CANCELLED`；记录不删除，仍可通过决策请求和 Alpha 历史回溯。

## 收束后的逻辑关系

不是把两个列表强行合并，而是引入同一条链路视图：

1. `Top 10` 保留研究层排序
2. `Actionable` 保留流程层状态
3. `Pending` 保留执行层状态
4. 由聚合查询判断三者交集和差集

聚合后统一输出：

- Top 10 中哪些已经进入 `ACTIONABLE`
- Top 10 中哪些已经进入 `PENDING`
- 哪些可行动候选已经脱离当前 Top 10
- 哪些待执行请求已经脱离当前 Top 10

## 后端实现

统一入口：

- `apps/dashboard/application/queries.py`
  - `AlphaDecisionChainData`
  - `AlphaDecisionChainQuery`
  - `get_alpha_decision_chain_query()`

核心行为：

- 复用 `AlphaVisualizationQuery` 和 `DecisionPlaneQuery`
- 对股票代码做别名归一化，支持 `000001` / `000001.SZ` 匹配
- Top 10 与 `Actionable / Pending` 的关系匹配，基于同一次 `DecisionPlaneQuery` 已加载结果完成，不再在 `AlphaDecisionChainQuery` 内额外直连下层 ORM
- 为 Top 10 股票补充 `workflow_stage`
- 为候选和待执行请求补充：
  - `is_in_top10`
  - `current_top_rank`
  - `current_top_score`
  - `origin_stage_label`
  - `chain_stage_label`

## 页面可视化

Dashboard 现在按同一链路展示：

- `Top 10 选股结果`
  - 增加 `Alpha 决策链` 汇总条
  - 每只股票增加 `链路状态`
  - 明确显示它是：
    - `仅在 Alpha Top 排名`
    - `可行动候选`
    - `待执行队列`

- `决策 Workflow`
  - 增加 `Alpha 决策链收束` 关系条
  - 增加 `Alpha 推荐资产` 首屏区块，优先展示 Top 排名
  - 当 Top 排名为空时，首屏明确显示“暂无可信 Alpha 推荐资产”，不使用可行动候选或待执行请求顶替
  - 待执行资产显示来源原因，并提供“丢弃待执行”操作
  - 可行动候选和待执行队列显示：
    - 当前是否在 Top 10
    - 当前排名
    - 当前 Alpha 分数

这样页面上不再是两个互不解释的列表，而是同一条链路的不同阶段。

## Canonical API

新增统一读取端点：

- `/api/dashboard/v1/alpha-decision-chain/`
- `/api/dashboard/alpha/stocks/?format=json`
- `/api/dashboard/alpha/refresh/`

返回结构：

```json
{
  "success": true,
  "data": {
    "overview": {},
    "top_stocks": [],
    "actionable_candidates": [],
    "pending_requests": [],
    "top_n": 10,
    "max_candidates": 5,
    "max_pending": 10
  }
}
```

## SDK / MCP

### SDK

- 文件：`sdk/agomtradepro/modules/dashboard.py`
- 方法：`DashboardModule.alpha_decision_chain_v1(...)`

### MCP

- 文件：`sdk/agomtradepro_mcp/tools/dashboard_tools.py`
- 工具：`get_dashboard_alpha_decision_chain_v1`
- 首页账户视角工具：`get_dashboard_alpha_candidates`
- 历史回溯工具：`get_dashboard_alpha_history`、`get_dashboard_alpha_history_detail`
- 实时刷新工具：`trigger_dashboard_alpha_refresh`

## 首屏性能约束

- 登录到首页不得同步触发 Qlib 推理。
- 缺少账户池 cache 时可以自动投递后台 Qlib 推理任务，但必须异步执行，且任务参数必须来自当前账户池 `scope_payload`，不能使用硬编码 universe。
- Dashboard Alpha metrics 使用 Provider 注册状态，不在首屏执行深度 `health_check()`。
- AI 建议默认使用本地规则，不在首屏等待外部 AI API；需要同步外部 AI 时显式开启 `DASHBOARD_SYNC_AI_INSIGHTS_ENABLED=True`。
- 手动实时推理只通过页面刷新按钮、`/api/dashboard/alpha/refresh/` 或 MCP `trigger_dashboard_alpha_refresh(...)` 进入 Celery 异步链路。
- 前端只显示轻状态和轮询刷新；后台任务完成前，推荐区保持“暂无可信 Alpha 推荐资产”。

## 约束

后续若修改 Dashboard 上这三个区块，必须同步检查：

1. `AlphaDecisionChainQuery` 聚合口径是否仍是唯一事实来源
2. `/api/dashboard/v1/alpha-decision-chain/` 是否仍与页面一致
3. SDK 与 MCP 是否继续调用 canonical 端点
4. 页面是否仍能直接看出 `Top 10 -> Actionable -> Pending` 的关系
5. 登录到首页是否仍保持轻量，不同步初始化 Qlib 或调用外部 AI

## 回归测试

本次变更对应的护栏包括：

- `apps/dashboard/tests/test_alpha_queries.py`
- `apps/dashboard/tests/test_alpha_views.py`
- `tests/api/test_dashboard_api_edges.py`
- `sdk/tests/test_mcp/test_tool_registration.py`
- `sdk/tests/test_mcp/test_tool_execution.py`
