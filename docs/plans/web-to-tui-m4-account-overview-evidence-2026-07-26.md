# Web → TUI M4 Account Overview Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-account-overview-w45`；覆盖账户资料与组合波动率 1 个 B 类 route
  template，进入 `execution.accounts`。
- 新增 3 个 curated read action：账户资料、波动率摘要和波动率趋势；账户、持仓、
  交易与通知继续复用 W37 已发布的 owner-scoped action，不重复发布。
- Account owner 新增 typed TUI 波动率 adapter，直接调用
  `VolatilityAnalysisUseCase`。30/60/90 日、目标值、目标上下限和建议仓位统一投影为
  百分比，历史按日期排序交给 portable line chart。
- 无活跃组合时返回成功的明确空态和空历史，不把正常初始化状态当作 404；浮点百分比
  在 HTTP 边界做有界舍入，避免用户可见二进制浮点噪声。
- Classic 页面显示准确 `execution.accounts` deep link，并继续保留到 M5。

## 验证与风险

- 定向 API/TUI：`3 passed`，覆盖百分比、空态和元数据列契约。
- Account API edge 与 inventory/static 联合回归：`66 passed`。
- 完整 TUI Workbench：`234 passed`。
- migration inventory：196 templates / 117 route pages；本 wave 后 B 类为
  5 migrated / 12 backlog。
- `black`、`ruff` 通过；4 个 production 文件增量 mypy：
  `0 regressions`、`0 legacy errors`。
- 未完成 live-server 空态、降仓告警、日期密度、键盘和三 viewport UAT；
  Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、旧入口占比、错误率和
  回滚演练门槛约束。
