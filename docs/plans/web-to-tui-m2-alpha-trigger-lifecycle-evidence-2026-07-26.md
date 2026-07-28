# Web → TUI M2 Alpha Trigger Lifecycle Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M2-alpha-trigger-lifecycle-w18`；Classic routes：创建、编辑和
  证伪规则构建器，共 3 个 route templates。
- TUI：发布 9 个确认型 mutation，覆盖创建、编辑、暂停、恢复、软取消、
  证伪检查、触发评估、候选生成和候选状态更新。
- 原 Classic 页调用但后端缺失的 PATCH、暂停、恢复和 DELETE 契约已补齐；
  DELETE 使用 `CANCELLED` 软取消语义，保留审计历史。
- 生命周期允许关系下沉 Domain；Application 用例负责校验和编排；
  Infrastructure repository 持久化完整可编辑状态，Interface 只做输入输出。
- ORM 增加 `PAUSED` 状态及迁移
  `0004_alter_alphatriggermodel_status.py`；`makemigrations --check --dry-run`
  无漂移。
- 证伪条件以 typed JSON list 合并进创建/编辑任务，独立构建器不再成为
  完成主任务的必经页面；硬编码指标示例没有提升为运行时真源。

## 验证与风险

- Alpha Trigger API + Domain `49 passed`；新增生命周期/TUI 定向 `4 passed`。
- TUI 页面定向与 IA `7 passed`。
- ruff、增量 mypy、migration drift、inventory 与 static contract 均通过。
- 真实 live-server 创建→编辑→暂停→恢复→证伪检查→候选生成→软取消 UAT
  待 M2 合并前补齐。
- Alpha Trigger 7 个 Classic route templates 均已具备 TUI 任务等价入口，
  但仍受 M5 的 14 日稳定窗口、访问量和回滚门槛约束，当前不删除。
