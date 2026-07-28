# Web → TUI M1 图表样板证据

> 日期：2026-07-26
> 样板：`macro-regime.overview` / `pulse.history`
> 结论：M1 通过，可作为 M4 的 portable line-chart 基线

## 1. 样板选择

`pulse.history` 满足 M1 的入口条件：

- owner 为 `pulse`，接口为已存在的 authenticated GET；
- API 返回稳定的日期、综合脉搏、增长、通胀、流动性和情绪分数；
- 默认六个月数据量可控，不触发写入、确认或管理员权限；
- 能覆盖时间轴、多序列、缺值、空态、超量采样和移动端布局。

生产 metadata 使用以下通用投影：

- `view_model.kind = chart`
- `rows_path = data`
- `columns[0] = observed_at`，作为横轴
- 其余 `columns` 作为数值序列
- runtime 不包含 `pulse.history`、screen key 或业务字段名判断

## 2. 实现结果

- `macro-regime.overview` 新增 P1 `pulse-trend` chart panel；
- host result projection 支持 ISO 日期升序、非有限值过滤和多序列输出；
- source rows 超过 240 时做确定性均匀采样，保留首尾点，并返回
  `source_row_count` 与 `sampled`；
- common runtime 同一 SVG 渲染多条折线，legend 和可见文本摘要同时给出
  序列名、首末时间和值，SVG 设为装饰性；
- schema description 与用户面设计标准记录 chart、`kpi_trend`、
  `table_chart` 的 portable contract；
- local registry 已幂等发布并通过 active hash 校验。

当前 graph / runtime 证据：

- published graph canonical validator hash：
  `f0946f380557ee4ea81fbd0c6252f055b4056c5668576ae4e2c557c3473b5b8c`
- published file SHA-256：
  `e734b1c6ad07ac15148d8ff1bb018f3ef6de58d84fec42e45c488705e12973f9`
- runtime build：
  `agomtui-runtime-0.2.0+46a2e29a4e8d`
- local registry source hash：
  `da4eec1ba90813c50b80bed7cc30b21bd725ccf42b69c75083e6776b40d3a2e8`

## 3. 验证记录

AgomTradePro：

- promotion 可重复执行：402 actions；
- metadata validator：12 screens / 402 actions / 16 specialized result actions；
- macro smoke：30/30 ok，`pulse.history` 为 HTTP 200、`view_kind=chart`；
- local publish-check：active registry hash matched；
- 图表 Python 契约：4 passed；
- `npm run check:tui`：通过；
- `npm run test:tui-js`：22 passed；
- Playwright chart UAT：
  - 键盘 Enter 可运行动作；
  - 多序列、文本摘要和装饰性 SVG 语义通过；
  - 360×800、768×1024、1440×1000 均无页面横向溢出、图表越界或摘要重叠；
- Ruff：通过；
- 增量 mypy：2 个生产文件 0 errors。

AgomTUI：

- one-way runtime sync check：全部 `UNCHANGED`；
- upstream published graph validator：通过；
- upstream published graph usability：0 errors，316 个既有 warning；
- core 35、compiler 15、runtime 20、Django demo 6，共 76 个 Python 测试通过；
- downstream runtime JS：6 passed；
- `npm run check:runtime`：通过；
- generic runtime business-leakage test：通过。

M0 记录的 panel schema 差异已关闭：AgomTUI core 现接受
`empty_message`、`error_message`、`stale_message`、`audience`、
`row_actions`、chart `columns` 与 result field presentation。

## 4. M4 退出决策

可直接复用：

- 单/多序列时间折线图；
- 第一列横轴、其余列数值序列的 rows/columns 投影；
- 空态、接口错误、部分缺值、240 行采样、文本摘要和三视口布局。

需要单独批准后再迁移：

- 分组/堆叠柱图；
- 多序列饼图；
- 双 Y 轴、蜡烛图、热力图、散点图、框选缩放；
- 超过 240 点且不能采样的审计/交易级精确图。

允许的临时降级：

- 精确数值优先时使用 `table_chart` 或 datagrid；
- 服务端已生成静态图时使用 `image`；
- host-specific 交互仅能进入 `frontend/agomtradepro-host`，不得写入 common runtime。

`kpi_trend` 与 `table_chart` renderer 已存在，但仍要求显式 server/host result
projection；不得仅发布 `rows_path`/`columns` 并假设 runtime 自动合成。

## 5. 回滚点

按以下顺序联动回滚，禁止只回滚 graph：

1. published graph / IA / promotion rule；
2. AgomTradePro host result projection；
3. common runtime source、bundle、CSS 与 manifest；
4. AgomTUI 同步产物及兼容 validator；
5. 重新发布对应版本 graph，并运行 local active-registry check。
