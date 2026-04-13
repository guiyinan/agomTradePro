# Dashboard Alpha 决策链收束说明（2026-04-12）

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

### 2. 可行动候选

- 来源：`DecisionPlaneQuery._get_actionable_candidates()`
- 含义：已经进入 Workflow 且状态为 `ACTIONABLE` 的候选
- 回答的问题：`哪些标的已被流程收束到可推进`

### 3. 待执行队列

- 来源：`DecisionPlaneQuery._get_pending_requests()`
- 含义：已形成审批/执行请求，仍处于 `PENDING` / `FAILED` 的队列
- 回答的问题：`哪些标的已进入 Step 5 等待执行`

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
  - 可行动候选和待执行队列显示：
    - 当前是否在 Top 10
    - 当前排名
    - 当前 Alpha 分数

这样页面上不再是两个互不解释的列表，而是同一条链路的不同阶段。

## Canonical API

新增统一读取端点：

- `/api/dashboard/v1/alpha-decision-chain/`

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

## 约束

后续若修改 Dashboard 上这三个区块，必须同步检查：

1. `AlphaDecisionChainQuery` 聚合口径是否仍是唯一事实来源
2. `/api/dashboard/v1/alpha-decision-chain/` 是否仍与页面一致
3. SDK 与 MCP 是否继续调用 canonical 端点
4. 页面是否仍能直接看出 `Top 10 -> Actionable -> Pending` 的关系

## 回归测试

本次变更对应的护栏包括：

- `apps/dashboard/tests/test_alpha_queries.py`
- `apps/dashboard/tests/test_alpha_views.py`
- `tests/api/test_dashboard_api_edges.py`
- `sdk/tests/test_mcp/test_tool_registration.py`
- `sdk/tests/test_mcp/test_tool_execution.py`
