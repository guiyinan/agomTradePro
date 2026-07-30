# TUI Regime 数据已返回但未显示：复盘与防复发措施

> 日期：2026-07-30
> 范围：`macro-regime.overview` 的 Regime 象限卡片及相邻脉搏面板
> 责任域：Terminal / TUI 结果投影与浏览器渲染

## 1. 事故结论

`/api/regime/tui/overview/` 已正确返回 `summary.quadrant=Recovery`、`summary.confidence_percent=36.88` 等数据，但 Regime 象限卡片仍按旧字段读取 `regime/confidence/trend/warning`。浏览器随后把缺失象限回退为 `UNKNOWN`，又把空置信度经 `Number("")` 转成 `0%`，形成了“后端有数据、用户看到无数据”的错误结果。

这是契约漂移未被端到端门禁捕获，不是数据源缺失。

## 2. 为什么这是低级失守

1. 接口升级为嵌套 `summary.*` 后，没有同步检查专用象限 renderer 的必需字段。
2. 后端测试只验证了通用 detail 能展开嵌套对象，没有验证象限卡片实际消费的四个字段。
3. 浏览器测试只检查象限标记位置，没有断言“当前判断、置信度、趋势、预警”的最终文字。
4. 前端使用了看似合理的默认值，掩盖了契约错误；尤其空字符串被数值转换为零，制造了虚假精确值。
5. 验收偏向“请求成功、组件出现”，没有把“真实业务值进入首屏”作为 P0 验收条件。

## 3. 五问根因

- 为什么显示 `UNKNOWN/0%`：renderer 没找到旧字段并启用了默认值。
- 为什么没找到：owner API 已迁移到 `summary.*`，TUI 没有稳定投影层。
- 为什么投影缺失：接口与 renderer 被分别测试，没有共享结果契约。
- 为什么测试没报警：mock 仍使用旧的扁平字段，而且只检查 marker，不检查业务文字。
- 为什么上线前没发现：验收没有比较“API 真值”和“页面首屏值”。

根因归类：跨层结果契约缺少单一适配点、失败策略错误、端到端断言不足。

## 4. 已完成整改

- 在后端结果投影层把 Regime `summary.*` 映射为稳定的 `current_regime/confidence/trend/warning`。
- 象限 renderer 对四个必需字段执行 fail-closed；字段不全时显示明确的不完整结果，不再伪造 `UNKNOWN/0%/-`。
- 数值格式化先判断空值，禁止把空字符串转换为零。
- 浏览器回归同时断言正常数据文本和字段漂移时的显式失败状态。
- 审计 76 个 dashboard panel：唯一专用 `regime_quadrant` 已建立稳定投影；4 个 chart panel 均使用 portable chart 契约。
- 审计发现 `pulse-turning` 名称/类型与 `pulse.current` 的指标表契约不一致，已改为“当前脉搏指标” datagrid，并只展示指标、信号、方向和过期状态。
- 验证候选图时发现 generated graph 仍使用已废弃的 `daily_decision/research/assistant` journey 值；已与 published/IA 统一为 `workspace`，恢复 generated 与 published 双图校验。
- 全量 kind 校验发现首页资产配置与组合表现仍由旧 `status` 基线依赖运行时 patch 转成 chart；已把 generated/published 直接同步为正式 portable chart 契约。

## 5. 长期门禁

1. 专用 renderer 必须声明并测试必需字段，缺字段只能显式失败，禁止业务默认值掩盖。
2. owner API 结构变更必须同时提供：API 契约测试、TUI 投影测试、浏览器最终文本断言。
3. P0 dashboard 验收必须使用一组非零、非空的代表数据，比较 API 真值与页面值。
4. panel `kind`、action `view_model.kind` 和 `presentation_semantic` 必须一致；有宿主聚合适配器的例外需在测试中明确登记。
5. 任何空值数值格式化必须先判空；`Number("")`、隐式布尔转换等不得出现在用户结果路径。
6. Metadata validator 对 `datagrid/chart/image/kpi_trend/table_chart/host_slot/custom/regime_quadrant` 执行 panel/action kind 一致性校验，发布前直接拒绝错配。

## 6. 完成标准

- 后端真实数据投影包含象限、置信度、趋势、预警。
- 正常浏览器场景显示真实值；漂移场景不出现 `UNKNOWN` 或 `0%`。
- TUI metadata、生成图、发布图及信息架构测试保持同步。
- TUI 全量单测、浏览器回归、静态契约、增量类型检查全部通过。
