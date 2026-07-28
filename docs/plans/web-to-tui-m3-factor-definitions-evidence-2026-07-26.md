# Web → TUI M3 Factor Definitions Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-factor-definitions-w32`；覆盖因子定义管理 1 个 route template。
- canonical screen：`research.asset-lab`。发布列表、详情、创建、局部更新、启停和删除
  6 个动作，复用 `/api/factor/definitions/**` owner API。
- 创建与更新表单完整覆盖代码、名称、类别、描述、数据来源、数据字段、方向、更新频率、
  启用状态、最小数据点和缺失值策略；列表保留类别、状态和关键字筛选。
- 类别与方向选项直接取 Factor Domain enum；owner serializer 同步改为 ChoiceField，并把
  `min_data_points` 下限收紧为 1，阻止 TUI 之外的 API 调用绕过相同领域边界。
- 写动作沿用既有认证用户权限，均显式确认；Classic 页面增加准确 TUI deep link，
  兼容期内保留。

## 验证与风险

- Factor definition CRUD、枚举/样本边界与 TUI metadata：`6 passed`。
- TUI information architecture：`6 passed`。
- `ruff` 通过；production serializer / metadata mypy：
  `0 regressions`、`0 legacy errors`。
- live-server 列表筛选、创建、局部更新、启停、删除冲突和空态 UAT 尚未完成；
  Classic 删除仍受 M5 稳定发布、14 天兼容窗口和 telemetry 门槛约束。
