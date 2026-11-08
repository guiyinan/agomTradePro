# Owner 状态兼容约定

本次经技术审批第 1、2 项 A 后，将两项 Owner 状态加入单元的封闭枚举；未扩展工作流外层状态，也未修改依赖图。

- `deferred`：当前目标范围之外，保留退出条件、依赖、实现与历史证据；不是已完成，不进入可执行候选，也不满足下游完成前置。恢复需新的明确范围决定。
- `archived`：Owner 决定不推进本单元草案，历史记录原位保留；不是已完成、不进入执行候选、不满足完成前置。重新推进需要明确的 Owner 决定。
- 未知状态仍拒绝，不能因为支持这两项就接受任意字符串。
- `execution_focus` 仍只能指向 active 的 repository 单元；不能指向 deferred/archived。

## Authorized completion handoff-pending focus

`execution_focus.handoff_pending` 是可选的交接等待标记，只适用于以下明确授权的完成交接：ASH-03 指向主计划 `docs/plans/a-share-usability-implementation-plan-2026-10-16.md#19.156`，ASH-07 指向同一主计划的 `#19.157`，REF-03 指向 `#19.161`，REF-04 指向 `#19.162`，REF-06 指向 `#19.164`。REF-06 仅适用于主计划 §19.164 记录的本轮授权：原 Goal 全部退出门通过后结束当前焦点并等待正式交接，保留 ASH-08 合格来源恢复优先级，不自动启动后继。标记必须精确包含非空 `completed_unit_id`、`owner_decision_ref`、`reason`；锚定单元必须是已登记且已 completed 的 repository 单元，引用必须精确匹配该单元获准的章节，且目标章节必须存在。其他单元、章节或引用不由此例外授权。

该标记只允许 `execution_focus.unit_id=null` 且没有 active repository 单元时等待下一次正式 Owner 焦点交接，并保留已 eligible 的后续计划。ASH-07 交接不会自动选择或激活 ASH-08、REF 单元或其他后继。完成单元必须同时从 `parallel_preparation` 移除，以符合该字段仅容纳未完成 repository work 的既有规则。标记不修改状态、依赖或 eligibility，不满足任何依赖，也不授予新 Goal、实施、生产或交易权限。没有有效标记时，原有规则仍拒绝以 null 隐藏 eligible repository work；标记与非空焦点、任何 active repository 单元、错误锚点、错误引用或额外/缺失字段并存均拒绝。

12 项延期与 MHD-01 归档仅改变治理处置，不修改运行时权限、TAR 实际部署配置或 Broker 执行闸。生产保持 inline 并发=1 是 Owner 的运行要求，本轮没有用新的 VPS 观察冒充它已被现场复验。

ASH-11 尚保留旧 ASH-06/DATA-18 依赖，瘦身报告等待 Owner 接受后实施；本次不把被延期的前置假标完成。旧 next_gate 原文完整保存在 `registry-application-base.json`，新门槛只发布当前要求和历史引用。
