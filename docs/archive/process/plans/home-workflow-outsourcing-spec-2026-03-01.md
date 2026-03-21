# 首页主流程闭环改造外包实施规格（V1）

> 文档版本: v1.0  
> 日期: 2026-03-01  
> 适用版本: AgomTradePro V3.4+  
> 目标: 将系统主流程收敛为“首页单入口 -> 候选 -> 决策 -> 执行 -> 回写”的可执行闭环

---

## 1. 背景与目标

当前系统功能齐全，但用户主流程仍以模块并列为主，存在以下断点:

1. Alpha 候选可标记 `EXECUTED`，但与真实执行记录无强关联。
2. 决策请求提交后“待办语义”不准确，页面文案与数据状态不一致。
3. 决策工作台未打通执行落地（模拟盘/账户持仓）标准链路。
4. 事件总线联动弱，跨模块状态一致性依赖人工操作。

本项目目标:

1. 首页成为主入口（类似决策工作台，但内嵌主流程）。
2. 支持双执行目标: `模拟盘执行` 与 `账户持仓记录`。
3. 提供全链路状态回写，确保候选/决策/执行/持仓一致。
4. 保持兼容旧接口与旧页面，分阶段切换。

---

## 2. 范围定义

## 2.1 In Scope

1. 首页新增“主流程面板”（可操作，不是只展示）。
2. 新增预检查 API（Beta Gate + Quota + Cooldown + 候选状态检查）。
3. 扩展决策提交 API 支持候选关联与执行目标。
4. 新增决策执行 API，打通模拟盘与账户记录。
5. 扩展 `DecisionRequest`、`AlphaCandidate` 结构与状态机。
6. 事件总线联动完善（批准/拒绝/执行事件回写）。
7. 用户文档 + API 文档 + SDK/MCP 文档同步更新。

## 2.2 Out of Scope

1. 自动实盘下单（券商 API）不在本轮范围。
2. 大规模 UI 视觉重构不在本轮范围。
3. 对历史业务模型大规模重构不在本轮范围。

---

## 3. 业务闭环定义（唯一主链）

1. 用户从首页进入主流程。
2. 选择 `ACTIONABLE` 候选。
3. 执行预检查:
   1. Beta Gate 是否通过。
   2. 配额是否足够。
   3. 冷却期是否通过。
   4. 候选状态是否仍有效。
4. 提交决策请求。
5. 选择执行目标（模拟盘/账户记录）并执行。
6. 系统回写:
   1. DecisionRequest.execution_status
   2. AlphaCandidate.status / last_execution_status
   3. 模拟盘交易或账户持仓记录
7. 首页卡片与待办列表实时反映最新状态。

---

## 4. 数据模型变更

## 4.1 DecisionRequest 扩展（apps/decision_rhythm）

新增字段:

1. `candidate_id` `CharField(max_length=64, blank=True, db_index=True)`
2. `execution_target` `CharField(max_length=16, default='NONE')`
   1. 枚举: `NONE`, `SIMULATED`, `ACCOUNT`
3. `execution_status` `CharField(max_length=16, default='PENDING', db_index=True)`
   1. 枚举: `PENDING`, `EXECUTED`, `FAILED`, `CANCELLED`
4. `executed_at` `DateTimeField(null=True, blank=True)`
5. `execution_ref` `JSONField(null=True, blank=True)`
   1. 示例: `{"trade_id":"...", "account_id":1}` 或 `{"position_id":123, "portfolio_id":9}`

约束:

1. `execution_status='EXECUTED'` 时 `executed_at` 必填。
2. `execution_target='NONE'` 时 `execution_ref` 应为空。

## 4.2 AlphaCandidate 扩展（apps/alpha_trigger）

新增字段:

1. `last_decision_request_id` `CharField(max_length=64, blank=True, db_index=True)`
2. `last_execution_status` `CharField(max_length=16, blank=True)`

规则:

1. 决策提交成功时写入 `last_decision_request_id`。
2. 执行完成后同步 `last_execution_status`。
3. 执行成功才允许自动转 `EXECUTED`。

## 4.3 迁移要求

1. 提供 Django migration（不可手改库）。
2. 为新增枚举字段提供默认值，保证历史数据可读。
3. 提供数据回填脚本:
   1. 旧请求统一设 `execution_target='NONE'`。
   2. 若候选已 `EXECUTED` 但无执行记录，标记 `last_execution_status='UNKNOWN_LEGACY'`。

---

## 5. API 设计与契约

## 5.1 预检查 API（新增）

`POST /api/decision-workflow/precheck/`

请求:

```json
{
  "candidate_id": "cand_xxx"
}
```

响应:

```json
{
  "success": true,
  "result": {
    "candidate_id": "cand_xxx",
    "beta_gate_passed": true,
    "quota_ok": true,
    "cooldown_ok": true,
    "candidate_valid": true,
    "warnings": [],
    "errors": []
  }
}
```

失败约定:

1. 参数错误: `400`
2. 候选不存在: `404`
3. 业务阻断也返回 `200 + success=true`，但 `errors` 非空，前端按阻断处理

## 5.2 决策提交 API（扩展）

`POST /api/decision-rhythm/submit/`

新增字段:

1. `candidate_id`（可选）
2. `execution_target`（可选，默认 `NONE`）

示例:

```json
{
  "asset_code": "000001.SH",
  "asset_class": "a_share",
  "direction": "BUY",
  "priority": "HIGH",
  "trigger_id": "cand_xxx",
  "candidate_id": "cand_xxx",
  "execution_target": "SIMULATED",
  "reason": "来源候选 cand_xxx",
  "expected_confidence": 0.78,
  "quota_period": "WEEKLY"
}
```

兼容性:

1. 不传新增字段时行为与旧版本一致。
2. 旧 SDK/MCP 不应因新增字段失败。

## 5.3 决策执行 API（新增）

`POST /api/decision-rhythm/requests/{request_id}/execute/`

请求:

```json
{
  "target": "SIMULATED",
  "sim_account_id": 1,
  "asset_code": "000001.SH",
  "action": "buy",
  "quantity": 1000,
  "price": 12.35,
  "reason": "按决策请求执行"
}
```

账户路径请求（示例）:

```json
{
  "target": "ACCOUNT",
  "portfolio_id": 9,
  "asset_code": "000001.SH",
  "shares": 1000,
  "avg_cost": 12.35,
  "current_price": 12.35,
  "reason": "按决策请求落地持仓"
}
```

执行成功响应:

```json
{
  "success": true,
  "result": {
    "request_id": "req_xxx",
    "execution_status": "EXECUTED",
    "executed_at": "2026-03-01T10:00:00+08:00",
    "execution_ref": {
      "trade_id": "trd_xxx",
      "account_id": 1
    },
    "candidate_status": "EXECUTED"
  }
}
```

---

## 6. 状态机定义（必须严格执行）

## 6.1 DecisionRequest

1. 创建后: `execution_status=PENDING`
2. 执行成功: `PENDING -> EXECUTED`
3. 执行失败: `PENDING -> FAILED`
4. 手动取消: `PENDING/FAILED -> CANCELLED`

非法迁移（禁止）:

1. `EXECUTED -> PENDING`
2. `CANCELLED -> EXECUTED`

## 6.2 AlphaCandidate

1. `CANDIDATE -> ACTIONABLE`（候选通过）
2. `ACTIONABLE -> EXECUTED`（仅当执行 API 成功）
3. `ACTIONABLE/CANDIDATE -> CANCELLED`（人工取消）
4. 任意活跃态 -> `INVALIDATED/EXPIRED`（规则触发）

硬约束:

1. 仅“状态按钮”不能直接把候选置 `EXECUTED`，必须经过执行 API。

---

## 7. 事件联动设计

事件:

1. `DECISION_APPROVED`
2. `DECISION_REJECTED`
3. `DECISION_EXECUTED`
4. `DECISION_EXECUTION_FAILED`（新增）

处理逻辑:

1. `DECISION_APPROVED`:
   1. 回写 `AlphaCandidate.last_decision_request_id`
2. `DECISION_EXECUTED`:
   1. 回写 `DecisionRequest.execution_status=EXECUTED`
   2. 回写 `AlphaCandidate.status=EXECUTED`
3. `DECISION_EXECUTION_FAILED`:
   1. 回写 `DecisionRequest.execution_status=FAILED`
   2. 保留 `AlphaCandidate=ACTIONABLE`

容错:

1. 主事务成功优先，事件发布失败不回滚主事务。
2. 失败事件写错误日志，支持后续重放。

---

## 8. 前端改造清单

## 8.1 首页新增“主流程面板”

位置: `dashboard/index` 页面中的决策平面区域

新增功能:

1. Step 导航（环境 -> 候选 -> 决策 -> 执行 -> 回写）
2. 候选行 CTA:
   1. 预检查
   2. 提交决策
   3. 执行
3. 执行弹窗:
   1. 执行目标二选一（模拟盘/账户）
   2. 动态渲染目标账户/组合
   3. 数量价格校验

## 8.2 决策工作台修正

文件: `core/templates/decision/workspace.html`

改造点:

1. “待系统处理”改为“待执行落地”。
2. 待办列表改查询条件:
   1. `response.approved=True and execution_status='PENDING'`
3. 每条待办提供:
   1. 去执行
   2. 取消
   3. 失败重试（FAILED 时）

## 8.3 Alpha 候选详情限制

文件: `apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html`

改造点:

1. 移除“直接标记已执行”按钮，替换为“去执行”。
2. 执行后只读展示执行引用（trade_id/position_id）。

---

## 9. SDK / MCP 同步要求

## 9.1 SDK

新增方法:

1. `decision_workflow.precheck(candidate_id)`
2. `decision_rhythm.execute_request(request_id, payload)`

## 9.2 MCP

新增工具:

1. `decision_workflow_precheck`
2. `decision_execute_request`

权限:

1. 默认仅 `admin`、`owner`、`investment_manager` 可执行 `execute_request`。
2. `analyst` 仅可 `precheck/submit`，不可执行落地。

---

## 10. 测试与验收

## 10.1 自动化测试（必须）

1. 单元测试
   1. 预检查组合规则
   2. 状态机合法性
   3. 执行目标分派正确性
2. 集成测试
   1. 候选 -> 决策 -> 执行（模拟盘）闭环
   2. 候选 -> 决策 -> 执行（账户）闭环
   3. 执行失败回写正确
3. E2E
   1. 首页一步步走通双路径
   2. 阻断路径（配额耗尽/冷却中/Beta 拦截）

## 10.2 UAT 验收口径

通过标准:

1. 首页 3 次点击内可到“执行入口”。
2. 任一执行成功后 5 秒内首页计数更新。
3. 候选状态与执行记录一一可追踪。
4. 旧接口调用（不传新增字段）不回归。

不通过条件:

1. 可以绕过执行 API 直接把候选标记 `EXECUTED`。
2. 执行成功但 `DecisionRequest` 仍 `PENDING`。
3. 首页/工作台待办口径不一致。

---

## 11. 任务拆分（外包可并行）

## WP-1 后端模型与迁移（3 人日）

1. 新增字段与迁移
2. 回填脚本
3. 序列化器同步

交付物:

1. migration 文件
2. model/repository 更新
3. 单元测试

## WP-2 决策编排与新 API（5 人日）

1. `precheck` API
2. `execute` API
3. submit 扩展字段兼容

交付物:

1. view/use case/repository 更新
2. API contract 测试

## WP-3 首页与工作台前端（5 人日）

1. 首页主流程面板
2. 工作台待办修正
3. 候选详情执行入口重构

交付物:

1. 模板 + JS + CSS 变更
2. E2E 用例

## WP-4 事件联动与一致性（3 人日）

1. 新增执行失败事件
2. 回写处理器
3. 事件初始化链路核对

交付物:

1. handler/usecase 调整
2. 故障注入测试

## WP-5 文档与 SDK/MCP（3 人日）

1. 用户文档更新
2. API 文档更新
3. SDK/MCP 更新与测试

交付物:

1. docs + sdk + mcp 变更
2. 文档链接可追溯

---

## 12. 里程碑与排期（建议）

1. M1（第 3 天）: 模型迁移 + API 骨架完成
2. M2（第 7 天）: 双执行路径联调完成
3. M3（第 10 天）: 首页主流程 UI 完成
4. M4（第 12 天）: 回归 + UAT + 文档交付

总工期建议: 12 个工作日（2 名后端 + 1 名前端 + 1 名测试）

---

## 13. 提交规范与审查要求

1. 每个 WP 独立 PR，禁止超大 PR。
2. PR 描述必须包含:
   1. 变更点
   2. 接口影响
   3. 回归风险
   4. 测试证据
3. 涉及状态机与执行链路的 PR 必须附 E2E 录像或截图。

---

## 14. 默认决策（本项目已锁定）

1. 主入口: 首页。
2. 闭环深度: 到执行落地。
3. 执行目标: 双入口（模拟盘 + 账户记录）。
4. 改造范围: 页面串联 + 后端事件联动一起改。
5. 不做自动实盘下单，仅做系统内执行落地与回写。

---

## 15. 附录：最小回归清单

1. `/decision/workspace/` 仍可用。
2. `/alpha-triggers/` 列表、详情、创建不回归。
3. `/simulated-trading/api/accounts/{id}/trade/` 正常。
4. `/account/api/positions/` 正常。
5. `POST /api/decision-rhythm/submit/` 旧参数调用成功。

