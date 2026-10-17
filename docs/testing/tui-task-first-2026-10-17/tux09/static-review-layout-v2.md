# TUX09 task/dashboard layout v2 静态审查

审查范围：当前共享 `frontend/tui-workbench/src/20-dashboard.js`、`38-task-focus-panels.js`、`40-views.js` 与 `static/css/tui-workbench.css`。本轮只读；未运行测试、浏览器、构建、导入、数据库、Git 或网络操作，也未修改共享源码。

## 结论

服务器授权边界基本正确：`38-task-focus-panels.js:359-364` 的 `isTaskDashboardScreen()` 同时要求当前 screen 的 `entry_state.mode === "dashboard"`，并要求该 screen 出现在服务器发布并经当前 catalog 过滤后的 `experienceEntries("task")` 中。没有业务 screen/action key 硬编码，public screen 的 `entry_state.mode` 也被按 metadata 读取。

CSS 布局隐藏边界也正确：`static/css/tui-workbench.css:4175-4208` 先要求 `data-active-experience-mode="task"`，再要求 `.tui-action-entry-form` 或 `[data-task-dashboard]`；因此 professional mode 不会因为同一 screen 的 task entry marker 而隐藏 rail、actions、inspector，原有 professional grid 规则仍生效。

有两个需要修正或至少补浏览器证据的实质问题：

1. `isTaskDashboardScreen()` 没有检查 `state.experienceMode === "task"`。因此 professional mode 打开一个同时发布为 task entry 的 screen 时，`20-dashboard.js:27` 仍会写入 `data-task-dashboard`，`40-views.js:789` 仍会写入同名 marker；更重要的是 `40-views.js:762,792` 仍会调用 `renderTaskDashboardSummary()`，让 professional 结果使用 task 专用摘要。CSS 因为有 mode 前缀不会隐藏布局，但 professional 的 DOM/摘要语义仍发生变化。若产品要求专业模式完全保留旧输出，最小修正是让 task summary/marker 具备当前 mode 条件，或拆成“服务器 task 身份 marker”和“当前 task presentation”两个窄 predicate；不要用客户端业务 key 绕过 server catalog。
2. `38-task-focus-panels.js:366-371` 的摘要只在 `business_summary` 非空时输出“当前结果/事实与限制”，没有读取顶层 `blocking_reason` 或 `restriction_message`。`40-views.js:792` 使用 `taskSummary || renderDecisionCue(viewModel)`，所以一旦 `business_summary` 存在，通用 cue 中的“当前阻断”行（`40-views.js:869-870`）会被跳过；若只有 `blocking_reason` 而没有 `business_summary`，task summary 为空，而 `renderDecisionCue()` 在没有 context/objective 时也会提前返回（`40-views.js:856`），P0 阻断可能完全不可见。`20-dashboard.js:657-665` 的 dashboard panel 路径会显示并 escape `blocking_reason`，但 full-screen detail/message 路径不对齐。应在 task summary 中优先显示安全的服务器 restriction/blocking 文案，并在没有 business summary 时仍显示 status 与限制；保留 raw code 在不可见模型中即可，不要让 UI 依赖 raw code。

## 分路径核对

### Dashboard 首屏与 panel

- `20-dashboard.js:18-27` 的 quiet home 仍只渲染任务选择占位，不生成 task dashboard marker，也不会触发 panel action。非 quiet dashboard 只有 `isTaskDashboardScreen()` 成立时才带 `[data-task-dashboard]`。
- `20-dashboard.js:657-665` 的 panel body 对 `blocking_reason` 使用 escaped notice，并把 `business_summary` 作为标题；这条路径不会把 owner error/raw exception 直接放入 HTML。
- `20-dashboard.js:1020-1054` 的 `renderPanelDetail()` 复用 `renderTaskDashboardSummary()`、通用 sections、pager 与 next steps；旧 datagrid/detail/panel semantics 仍有原来的 fallback。需要补上上一节所述 restriction fallback，否则 panel 与 full-screen 的阻断首屏不一致。
- `38-task-focus-panels.js:426-464` 对目标 envelope 以 nested `response.status_code` 与 `outcome` 判定失败，并在 `401/403/scope invalid` 清理 selector；`38:485-513` 的错误路径清除 panel VM、展开错误 disclosure、滚动到错误并独立绑定 recovery/retry。它不会把 error envelope 送进 `renderTaskDashboardSummary()`，因此未见跨 panel 错误复用旧 summary 的直接路径。

### Full-screen detail/message 与跨屏

- `40-views.js:754-811` 的 detail renderer 对研究 snapshot 仍优先走既有 evidence renderer；普通 detail 才加入 task marker、task summary、generic cue、sections、pager 和 next steps。旧 research 六段 renderer 没有被 generic summary 覆盖。
- `40-views.js:818-850` 的 message renderer 没有 task summary，只使用 generic decision cue 和 message sections。遇到 task screen 的 message/blocking-only envelope 时，上一节的早退条件会使顶层 restriction 不出现；这是与 detail 同源的 P1 可见性缺口，应由统一安全摘要 helper 处理，而不是复制另一套业务 renderer。
- marker/summary 以 `state.screen` 为依据而不是从 view model 猜 screen；在既有 stale-request/generation 保护成立时，未看到跨屏响应主动写入旧 screen marker 的路径。仍应在真实浏览器中覆盖：task dashboard → explicit professional screen → 返回 task dashboard，以及旧 panel 的迟到 error；确认错误不会重新显示上一个 screen 的 `business_summary`。
- 当前 summary 值均通过 `escapeHtml`，section/detail body 也通过已有 escaped renderer；没有发现这片新增 HTML 直接拼接 owner message 的 XSS 路径。`renderDetailSectionMarkup()` 对 `restriction_message/limitation/blocking_reason` 也会 escape，但它位于折叠 detail disclosure，不能代替 P0 摘要。

### CSS 与旧路径兼容

- `static/css/tui-workbench.css:4175-4208` 的 `data-active-experience-mode="task"` 前缀保证 professional layout 不被 marker 触发；`[data-task-dashboard]` 在 task mode 的 dashboard 和 detail 都能维持单主区布局。
- `:has(.tui-action-entry-form, [data-task-dashboard])` 仍保留旧 task-entry 触发器，因此非 dashboard 的既有 research entry/result 继续获得 focused CSS；该旧触发器没有替换成客户端业务 screen map。
- CSS media rules 在小屏继续让 inspector 隐藏并允许 main body 滚动；task marker 不会改变 professional 的原有 mobile grid。需要实际浏览器断言 marker 缺失/撤权时恢复 professional geometry，以及 task → professional 切换后焦点不落入隐藏 panel。
- legacy catalog 没有 `experienceEntries("task")` 时，marker helper 返回 false，20/40 继续旧 `renderDashboardHome`、`renderPanelDetail`、`renderDecisionCue` 路径；这是静态兼容证据，但未在本轮运行验证。

## 最小验证建议

1. server catalog 仅给一个 task dashboard entry：打开 task mode，断言 grid/detail 有 marker、CSS 隐藏三栏；切到 professional，断言 marker 不影响布局，并明确检查是否应保留/移除 task summary。
2. task detail 结果分别返回：`business_summary + blocking_reason`、仅 `blocking_reason`、`restriction_message`、HTML 特殊字符；首屏必须显示限制且不显示 raw exception。
3. 先读 task panel，再切换另一个 screen，制造旧请求迟到的 error/partial envelope；断言当前 screen 不出现旧 summary/限制，且 401/403/scope-invalid 保持重选入口。
4. legacy catalog 与普通 professional screen 各走 datagrid、detail、message，确认没有 marker、task CSS 或 task-only summary。

未发现需要扩大到新的 frontend segment 的问题；优先修正当前 mode predicate 与 restriction summary，或由父代理在正式 QA 中明确接受其语义差异。
