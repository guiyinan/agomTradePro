# Alpha Refresh And Ignored Filter CTA

## 变更目标

- 首页 Alpha 在“等待账户池推理”或“暂无可信候选”时，直接提供“触发实时推理”按钮，调用既有 `triggerAlphaRealtimeRefresh(10)` 前端逻辑。
- `/decision/workspace/` 的 Step 4 增加“已忽略”快捷筛选按钮，复用现有 `user_action=IGNORED` 与 `include_ignored=true` 查询参数，不新增接口。

## 行为说明

- 首页按钮只是把用户显式引导到已有刷新能力，后端仍然走 `POST /api/dashboard/alpha/refresh/`。
- “已忽略”按钮本质是对 `decision-filter` 的快捷切换：
  - 激活时自动把筛选切到 `IGNORED`
  - 再次点击恢复为“全部用户动作”
- 忽略记录仍然保留在 `UnifiedRecommendationModel`，该按钮只影响查询视图，不改变审计留痕策略。

## 覆盖范围

- `core/templates/dashboard/partials/alpha_stocks_table.html`
- `core/templates/decision/steps/screen.html`
- `core/templates/decision/workspace.html`
- `apps/dashboard/tests/test_alpha_views.py`
- `tests/unit/test_decision_workspace_account_binding_guardrails.py`
