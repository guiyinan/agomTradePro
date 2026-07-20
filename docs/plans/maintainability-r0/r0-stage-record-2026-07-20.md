# 可维护性重构 R0 阶段记录

## 阶段目标

在不改变运行行为的前提下冻结 Filter、Readiness、Decision Rhythm、Account/Risk Center、SDK/MCP 五组边界和稳定契约，为 R1-R5 提供不可临时改口的实施输入。

## 已完成

- Filter 消费者、观察窗口、sunset 四重门槛与稳定身份已冻结；结论为 R1A 只弃用。
- Readiness 命令、task、Beat/PeriodicTask、evidence provenance、runbook/监控引用已冻结；目标 owner 为 `operational_readiness`。
- Decision Rhythm 文件族、13 个 ORM 模型、API/task/event 身份与目标 owner 已冻结；R3 第一阶段不迁 ORM identity。
- Account/Risk Center 字段语义、单位、作用域、消费者、优先级和迁移目标已冻结。
- canonical manifest vNext 字段、生成边界、DB projection/override 分层和确定性门槛已冻结。

## 未完成

- 生产 Filter 访问日志的连续观察窗口尚未形成；这阻止物理删除，但不阻止弃用。
- R3/R4/R5 尚未开始，本记录不授权提前实施。

## 回归范围

R0 文档本身不改运行代码。治理一致性检查与 module cycle check 作为机器基线；R1 代码变更另见 R1 阶段记录。

## 风险与回滚

R0 是文档/inventory 批次，可独立调整。任何后续实现若偏离这里的 owner 或身份决策，必须先更新矩阵并单独评审，不能在实现 PR 中临时决定。
