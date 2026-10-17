# TUX09 最终合同静态复核

复核范围限于当前 TUX09 scope、execution、task result projection、runtime action metadata 及其直接接口调用；未运行测试、导入 Django、连接数据库或执行构建。结论只针对当前源码，不替代正式 QA。

## P0：市场环境限制原因没有进入首屏预览

apps/terminal/application/tui_task_focus_result.py 的 project_today_focus_market_context_payload 在 387-440 行保留每行的 blocking_reason 和 must_not_use_for_decision，sections 也在 469-484 行完整保留这些字段。但首屏 fields 的 preview 调用在 451-456 行只取 status、observed_at、freshness、reliability、must_not_use_for_decision，没有取 blocking_reason。442-445 行的 business_summary 只汇总“有多少条带有使用限制”，并没有汇总 owner 已提供的限制原因。

这会让首屏用户看到“受限/不可使用”标记，却必须展开折叠的市场环境记录才能知道具体原因；原因较长或第 5 条以后受限时，首屏更不具备可操作解释，违背任务首页 P0 限制事实可见的要求。它也会削弱 must_not_use_for_decision 的真实含义，虽然没有把数据误判为可用。

最小修复应保持 owner 语义，不推导新的金融结论：

1. 在 preview 的有界字段中加入 blocking_reason；优先使用 owner 已提供的用户可读原因，技术代码继续留在深层/受控详情，不能把内部 API 常量直接当普通主区文案。
2. business_summary 在现有受限条目计数之外，加入 bounded 的 owner 明确原因摘要（去重并设有限量）；无原因时明确显示原因未提供，不凭 must_not_use_for_decision 推造原因。
3. sections 继续完整保留原始受限字段。不要改变 outcome、freshness、reliability 或金融可用性判定。

## 已核对且没有发现新增阻断

- scope 在 apps/terminal/application/tui_workbench_execution.py:145-168 先于 endpoint 绑定和 executor 调用；apps/terminal/application/tui_task_scope_contracts.py:103-161 仅允许六个已声明动作的字段，并将 account_id、pk、page、page_size 收窄为正整数。user_id、default、bool、浮点、超长数字和未声明字段不会进入 owner 调用。
- 正常 task scope 的 resolved_params 在 169-174 行来自纯 scope 结果，之后才在 222-240 行绑定路径和调用 executor；组合 pk 绑定到路径后，原规范化参数仍在 299 行供投影身份校验。当前没有看到 actor 参数覆盖或绕过 scope 的路径。
- TuiWorkbenchActionRunView 在 apps/terminal/interface/api_views.py:745-823 使用 IsAuthenticated，并把当前 request.user 传入 action lookup、run_action 和 executor；run_action:136-143 仍执行当前用户可见 action、risk 和审计策略。专业 target 在 execution:412-446 再按同一 user 查找新鲜可见的 GET/read action，不从客户端接受任意 screen/action/用户 ID。
- task executor 返回缺失、非整数或越界 status_code 时，execution:241-250 将其收窄为 502 和空 payload。task projection 对非 2xx 返回有界 message；HTTP 200 的 malformed owner payload 会在 execution:301-307 采用 projection 的 blocked/failed outcome，不因传输成功而冒充成功。
- task runtime metadata 在 apps/terminal/infrastructure/tui_metadata_runtime_injection_task_focus.py 的 action 定义中将六个任务动作设为 GET/read/read、raw_debug=False。execution:308-321 对这些动作不会暴露 raw_response，即使诊断用户存在；task projection 的 malformed/403/5xx 分支也不复制 owner 原始响应。
- 既有 owner API apps/decision_rhythm/interface/today_queue_api_views.py:22 仍保留 account_id 缺省为 default，这是 owner 旧接口的边界。TUI 的 today-focus.queue 在 scope:112-116 要求显式 account_id，因此当前 TUI 接线不会走该默认分支；不能据此声称旧 owner API 已经全局取消 default。
- TuiTaskFocusProfessionalTarget 当前 published metadata 的 account_id/pk 字段都为 required integer、query/path；execution:430-443 对字段绑定、输入形态、secret/sensitive 和 confirmation/password 进行过滤，projection 只用已选的规范化整数生成下一步参数，且不自动执行。当前 published metadata 下未发现 actor override 或写动作提升。

## 仍待正式验证的边界

本复核没有把既有静态测试、owner fixture 或旧失败轮当作用户验收。仍需父代理在冻结源码上确认：

- P0 修复后的市场环境 preview/business_summary 在普通用户和窄屏首屏可见；
- 正式浏览器中的 scope 拒绝、owner 403/会话失败、选择切换迟到响应和旧 facts 清除；
- 专业预填不自动执行、目标参数绑定和返回路径；
- task/pro、diagnostics、history/deep-link、键盘/移动端以及无 provider/模型/写入副作用。

本轮未发现 scope 默认回退、actor 覆盖、executor 绕过或 task raw response 泄露的新问题；市场限制原因的首屏缺失是当前需要优先修复的具体合同问题。