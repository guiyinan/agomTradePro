# Web → TUI M5 逐 Route 清理证据（2026-07-27）

## 当前结论

本证据是 M5-B 前逐 route closure 的增量台账，不是 Classic 清理授权。

- `primary_task`：108/108，沿用受控 live-server 浏览器 UAT 证据。
- `legacy_url`：108/108，本轮新增矩阵驱动的全量旧 URL 与迁移目标验证。
- `permission`：108/108。已验证 108 route 的匿名认证边界；其中 33 个管理员/operator
  route 至少有一个经复核的受限目标 action，且普通用户不可见、直达 action runner 返回
  403/404；另有 23 个纯 `login_required` route 已验证认证用户目标 action 可见且匿名
  action runner 返回 401/403；AI Provider、Simulated Trading、Strategy 的 15 个 route
  已验证本人正例、他人对象列表隔离或 403/404、拒绝写入不落库及适用的 staff override。
  Audit、Risk Center、Ops、Signal、Terminal 的 9 个混合/特殊边界 route 也已通过实际
  owner、staff、管理员写入与普通用户拒绝契约；另有 11 个无 owner 对象语义的共享研究
  route 完成认证后端边界与 owner app 契约验证；最后 17 个业务后端授权 route 已通过
  Alpha、Audit、Broker Execution、Decision Rhythm、Account、Dashboard、Decision、
  Factor、Hedge、Prompt 的实际角色/对象契约。
- `empty_state`：108/108。矩阵驱动测试按每条 route 的计划角色加载真实 runtime screen，
  验证至少一个目标任务可见、任务标签非空，并要求 `empty_state_hint` 与
  `next_step_hint` 同时存在且不泄露 API/path/HTTP 等实现细节。运行层已把这两项
  screen 指引注入空结果投影；列表、详情、图表均输出 `暂无数据` 状态、任务级
  `empty_message` 和可执行引导，浏览器实际渲染为空态组件，不再退化为硬编码
  “暂无摘要数据”。
- `error_state`：108/108。矩阵驱动测试按每条 route 的计划角色选择真实可见目标
  action，并在实际 action runner HTTP 边界注入受控异常；108 条 route 均返回有界
  `tui_action_unavailable` envelope、任务标签、trace id 和指回原工作区的恢复动作，
  内部异常文本不进入响应。数据库 readiness 503 使用相同任务上下文；Workbench
  浏览器显示任务级标题/说明/追踪编号、重试按钮和恢复按钮。
- `rollback`：108/108。89 个 A 类 route 指向实际模板迁移提交
  `f05399dde14d93671e61e2c7ecf7b759acd4bfd5`，17 个 B 类 route 指向图表迁移提交
  `2f0e8cce24243ade60036cfd221c514cc2451bec`；管理员决策链与旧 Terminal 配置两个
  未直接改动模板的 route 指向包含运行时任务与精确重定向的后端提交
  `5554caf11d80aa0fa13340d4e187946743659c1a`。`build_web_to_tui_rollback_catalog.py`
  已验证三个完整 commit 均存在且属于当前分支历史，并把精确的 108 条映射同步到
  cutover evidence；没有把当前 `HEAD`、占位值或无关历史提交批量写入矩阵。

因此逐 route 的六类 scope 已完整达到 108/108，`route_cleanup_readiness` 为 `PASS`。
M5 总判定仍为 `DENY`，候选稳定窗口、生产缺陷/遥测、生产 registry 备份和独立审批
尚未完成，仍不得删除 Classic 页面。

## 本轮自动化证据

测试文件：`tests/component/test_web_to_tui_route_closure.py`

```text
8 passed in 89.51s
```

空态结果投影（列表、详情、图表）：

```text
3 passed, 239 deselected in 100.17s
```

Workbench 浏览器渲染（含详情/图表任务级空态）：

```text
18 passed in 42.01s
```

Action runner 503/502 任务级错误 envelope：

```text
2 passed, 241 deselected in 81.47s
```

完整 Workbench Python 回归：

```text
243 passed in 293.44s
```

完整 TUI JavaScript 回归：

```text
28 passed in 51.90s
```

Rollback catalog 生成器单元测试：

```text
3 passed in 0.64s
```

Owner/object 权限契约：

```text
77 passed in 183.40s
```

Audit owner/admin 定向权限：

```text
5 passed, 13 deselected in 101.93s
```

混合角色 metadata/runner 定向权限：

```text
1 passed, 4 deselected in 107.30s
```

Risk Center、Signal、语义治理、Terminal 与 Audit 管理写入权限：

```text
73 passed in 151.04s
```

Capability Gateway 角色感知兼容导流：

```text
3 passed, 4 deselected in 97.54s
```

共享研究 route 认证边界：

```text
1 passed, 5 deselected in 94.24s
```

共享研究 owner app 组合契约：

```text
162 passed in 164.40s
```

最后 17 route 的业务后端权限契约（第一组）：

```text
162 passed in 234.28s
```

最后 17 route 的业务后端权限契约（第二组）：

```text
140 passed in 160.74s
```

执行文件：

- `tests/api/test_ai_provider_api_edges.py`
- `tests/api/test_strategy_api_edges.py`
- `tests/api/test_simulated_trading_api_edges.py`
- `tests/integration/simulated_trading/test_account_api_scope.py`
- `tests/integration/simulated_trading/test_account_create_api.py`
- `tests/integration/simulated_trading/test_account_delete_api.py`

覆盖内容：

1. 从迁移矩阵读取 108 个 active A/B route page，并展开 118 个实际 URL pattern；
2. 为 `int`、`str`、`slug`、`uuid`、`path` 参数生成无副作用测试值；
3. 匿名访问必须返回登录跳转、401 或 403，不允许在认证前执行页面业务；
4. 递归读取模板 `extends` / `include` 图，验证兼容页面发布审核后的 TUI screen/action；
5. 对已退役的 `/terminal/config/` 使用 staff 会话验证真实、精确的 TUI redirect；
6. 同时验证迁移提示明确说明 TUI 去向和 Classic/经典页面兼容期。
7. 为 regular、operator、admin 建立独立会话；36 个管理员/operator route 中，33 个
   route 的受限目标 action 对计划角色可见、对普通用户隐藏，且普通用户绕过 UI 直达
   action runner 仍返回 403/404。
8. 对 23 个权限规则精确为 `login_required` 的 route，验证认证用户至少可见一个审核后
   目标 action，并逐一验证匿名用户不能绕过 Classic 登录入口直接执行这些可见 action。

本轮 `permission` 计入的 33 个 route：

- `apps/agent_runtime/templates/agent_runtime/operator_proposal_detail.html`
- `apps/agent_runtime/templates/agent_runtime/operator_proposal_list.html`
- `apps/agent_runtime/templates/agent_runtime/operator_task_detail.html`
- `apps/agent_runtime/templates/agent_runtime/operator_task_list.html`
- `apps/audit/templates/audit/operation_logs_admin.html`
- `apps/beta_gate/templates/beta_gate/config_form.html`
- `apps/beta_gate/templates/beta_gate/config.html`
- `apps/config_center/templates/config_center/qlib_center.html`
- `apps/data_center/templates/data_center/governance.html`
- `apps/data_center/templates/data_center/market_thermometer.html`
- `apps/data_center/templates/data_center/publishers.html`
- `apps/data_center/templates/data_center/universe.html`
- `apps/decision_rhythm/templates/decision_rhythm/quota_config.html`
- `apps/rotation/templates/rotation/assets.html`
- `apps/rotation/templates/rotation/configs.html`
- `apps/task_monitor/templates/task_monitor/readiness_monitor.html`
- `apps/task_monitor/templates/task_monitor/scheduler_console.html`
- `core/templates/account/system_settings.html`
- `core/templates/account/token_management.html`
- `core/templates/account/user_management.html`
- `core/templates/ai_provider/manage.html`
- `core/templates/ai_provider/quota_manage.html`
- `core/templates/data_center/monitor.html`
- `core/templates/data_center/providers.html`
- `core/templates/equity/config.html`
- `core/templates/ops/admin_console.html`
- `core/templates/ops/mcp_tools.html`
- `core/templates/policy/keyword_form.html`
- `core/templates/policy/policy_event_form.html`
- `core/templates/policy/rss_keywords.html`
- `core/templates/policy/rss_logs.html`
- `core/templates/policy/rss_manage.html`
- `core/templates/policy/rss_source_form.html`

本轮第二批 `permission` 计入的 23 个纯登录权限 route：

- `apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html`
- `apps/alpha_trigger/templates/alpha_trigger/create.html`
- `apps/alpha_trigger/templates/alpha_trigger/detail.html`
- `apps/alpha_trigger/templates/alpha_trigger/edit.html`
- `apps/alpha_trigger/templates/alpha_trigger/invalidation_builder.html`
- `apps/alpha_trigger/templates/alpha_trigger/list.html`
- `apps/alpha_trigger/templates/alpha_trigger/performance.html`
- `apps/audit/templates/audit/attribution_detail.html`
- `apps/audit/templates/audit/indicator_performance.html`
- `apps/audit/templates/audit/report_list.html`
- `apps/audit/templates/audit/review_page.html`
- `apps/beta_gate/templates/beta_gate/test_asset.html`
- `apps/beta_gate/templates/beta_gate/version_compare.html`
- `apps/rotation/templates/rotation/account_config.html`
- `apps/rotation/templates/rotation/signals.html`
- `core/templates/asset_analysis/screen.html`
- `core/templates/backtest/create.html`
- `core/templates/backtest/detail.html`
- `core/templates/backtest/list.html`
- `core/templates/policy/policy_events.html`
- `core/templates/policy/rss_reader.html`
- `core/templates/policy/workbench.html`
- `core/templates/sentiment/analyze.html`

第三批 `permission` 计入的 15 个 owner/object route：

- `core/templates/ai_provider/detail.html`
- `core/templates/ai_provider/form.html`
- `core/templates/ai_provider/my_providers.html`
- `core/templates/ai_provider/usage_logs.html`
- `core/templates/simulated_trading/account_detail.html`
- `core/templates/simulated_trading/dashboard.html`
- `core/templates/simulated_trading/inspection_notify.html`
- `core/templates/simulated_trading/my_account_detail.html`
- `core/templates/simulated_trading/my_accounts.html`
- `core/templates/simulated_trading/my_positions.html`
- `core/templates/simulated_trading/my_trades.html`
- `core/templates/strategy/create.html`
- `core/templates/strategy/detail.html`
- `core/templates/strategy/edit.html`
- `core/templates/strategy/list.html`

本批通过真实 owner API 契约验证：个人 Provider 列表与日志不泄露他人数据，详情和更新
他人 Provider 返回 404 且对象不变；模拟账户列表排除他人账户，详情、持仓、交易、绩效、
巡检和通知拒绝跨账户读取，删除和批量删除不影响他人账户；Strategy 列表/详情、规则、
脚本、AI 配置、仓位规则和执行日志均保持 owner scope，跨 owner 写入拒绝，staff override
仅在既定读取边界生效。

第四批 `permission` 计入的 9 个混合/特殊权限 route：

- `apps/audit/templates/audit/decision_traces_admin.html`
- `apps/audit/templates/audit/my_decision_traces.html`
- `apps/audit/templates/audit/my_operation_logs.html`
- `apps/audit/templates/audit/threshold_validation.html`
- `apps/risk_center/templates/risk_center/console.html`
- `core/templates/ops/capability_gateway.html`
- `core/templates/ops/center.html`
- `core/templates/signal/manage.html`
- `core/templates/terminal/config.html`

本批验证普通用户只能读取自己的操作日志和决策链、伪造 `user_id` 无法越权、他人 trace
详情返回防枚举 403/404，管理员保留全量证据访问；阈值/验证和 Signal 管理写入保持
staff-only；Risk Center 的全局写入、账户策略、交易前/投后检查和日报均保持账户或 staff
边界；语义治理、Terminal 旧配置入口及审批/审计入口保持各自 staff/operator 边界。

第五批 `permission` 计入的 11 个共享研究 route：

- `core/templates/dashboard/alpha_history.html`
- `core/templates/dashboard/alpha_ranking.html`
- `core/templates/equity/detail.html`
- `core/templates/equity/pool.html`
- `core/templates/equity/screen.html`
- `core/templates/equity/valuation_repair.html`
- `core/templates/filter/dashboard.html`
- `core/templates/fund/dashboard.html`
- `core/templates/macro/data.html`
- `core/templates/regime/dashboard.html`
- `core/templates/sentiment/dashboard.html`

这些任务消费共享研究/市场数据，不定义用户所有权对象；权限闭环按其真实规则验证认证用户
目标 action 可见、匿名 Classic 与 action runner 均拒绝，并复跑对应 Dashboard Alpha、
Equity、Valuation、Macro/Regime、Fund、Sentiment owner app 的 162 项 API/组件契约。

第六批 `permission` 计入的最后 17 个业务后端授权 route：

- `apps/alpha/templates/alpha/ops/inference.html`
- `apps/alpha/templates/alpha/ops/qlib_data.html`
- `apps/audit/templates/audit/manual_trade_review.html`
- `apps/broker_execution/templates/broker_execution/workbench.html`
- `apps/decision_rhythm/templates/decision_rhythm/quota.html`
- `core/templates/account/mcp_guide.html`
- `core/templates/account/profile.html`
- `core/templates/account/settings.html`
- `core/templates/dashboard/index.html`
- `core/templates/decision/workspace.html`
- `core/templates/factor/calculate.html`
- `core/templates/factor/manage.html`
- `core/templates/factor/portfolios.html`
- `core/templates/hedge/alerts.html`
- `core/templates/hedge/pairs.html`
- `core/templates/hedge/snapshots.html`
- `core/templates/prompt/manage.html`

本批验证 Alpha 读操作 staff-only、触发动作 superuser-only；手工交易 CSV 预览拒绝他人组合；
Broker Execution 强制账户 grant、角色、签名、nonce、幂等和 preview/commit；Decision Rhythm
读操作需认证、配额写入需管理员；账户/MCP/Profile/Settings 保持当前用户与 foreign
portfolio 隔离；Dashboard 和 Decision Workspace 保持用户/账户范围；Factor 仅向认证用户
开放受验证 CRUD/计算契约；Hedge 和 Prompt 的读取/执行与 staff mutation 明确分层。

## 发现并修复的问题

- 为 Filter、Macro、Regime、Simulated Trading dashboard/account detail 五个页面补认证边界；
- 修复 Policy RSS source/keyword 编辑页在认证前查询对象并返回 404 的可枚举性问题；
- Broker Execution、Factor、Fund、Hedge 共七个页面改用统一
  `classic_tui_migration_banner.html`，消除手写兼容提示漂移；
- 接受 Django Admin 的 `/admin/login/` 作为管理员页面的有效认证入口，同时继续拒绝匿名 200；
- 角色动态 AI Provider deep link 和 Ops role-aware 多目标按矩阵的完整 screen 集合核对，
  不把占位符误判为实际 action。
- 修复 `operator.governance.data_center_summary` 仅在 screen 层隐藏、但普通用户可绕过 UI
  直接执行的问题；runtime metadata 真源现在把该 action 明确限定为 `admin`。
- 修复 Ops 两个混合角色矩阵行遗漏管理员目标 screen：Capability Gateway 增列
  `capability-router.mcp-center`，Ops Center 增列 `api-library.data-center`，从而让矩阵完整
  表达普通用户自助与管理员治理两个真实目的地。
- 修复 Regime 宏观适配器永久缓存 Data Center 指标目录元数据的问题；`period_type` 与
  `extra` 现在读取动态治理真源，长生命周期 provider 能立即观察目录更新。
- 修复 Regime `interface_services` 在首次懒加载时捕获临时 resolver patch 的顺序依赖；
  改为调用时解析模块函数，并以 Equity→Regime 组合回归证明不再泄漏 `SimpleNamespace`
  替身。

以下三个管理员 Classic route 的目标 action 当前全部与普通用户共享，因此未计入本轮
`permission` 分子，后续必须以 owner/backend 授权反例独立取证：

- `apps/audit/templates/audit/decision_traces_admin.html`
- `apps/risk_center/templates/risk_center/console.html`
- `core/templates/terminal/config.html`

## 逐 Route 条件收口

权限、空态、错误态、旧 URL 与回滚均已补齐到 108/108。回滚映射只接受完整、可解析且
属于当前分支历史的 commit，并由 `build_web_to_tui_rollback_catalog.py --write-evidence`
从矩阵同步；随后无写入校验返回 `routes=108 commits=3`。这只关闭逐 route 清理证据，
不替代候选稳定窗口、生产证据、registry 备份或切换双签。
