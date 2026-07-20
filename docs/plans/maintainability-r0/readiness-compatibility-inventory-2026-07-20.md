# R0 Readiness 稳定契约清单

> 状态：已冻结
> 目标 owner：`apps.operational_readiness`
> R1B：原路径内部去重；R1C：实现迁入新 owner，旧入口代理一个兼容周期

## 1. 管理命令

以下命令名属于操作契约，R1C 不改名：

| 命令 | 性质 | R1C 处理 |
|---|---|---|
| `collect_personal_readiness_evidence` | 生成 JSON/Markdown evidence | 旧命令 wrapper 代理新 owner |
| `run_personal_readiness_daily` | 日编排入口 | 旧命令 wrapper 代理新 owner |
| `validate_personal_readiness_window` | 连续窗口验证 | 旧命令 wrapper 代理新 owner |
| `show_personal_readiness_status` | JSON/人读状态与 strict gate | 旧命令 wrapper 代理新 owner |
| `inspect_personal_readiness_evidence` | 单文件阻塞诊断 | 旧命令 wrapper 代理新 owner |
| `repair_personal_readiness_evidence` | 带归档 provenance 的修复 | 旧命令 wrapper 代理新 owner |
| `setup_personal_readiness_daily` | django-celery-beat 配置 | 保持命令名，切换 task 字段时幂等更新 |
| `simulate_personal_readiness_checkpoints` | 时点 dry-run | 旧命令 wrapper 代理新 owner |
| `init_scheduler_defaults` | 全局 scheduler composition root | 留在 task_monitor，只调用稳定命令名 |

所有命令的 `--help`、选项名、退出码和 JSON 顶层结构视为契约。

## 2. Celery 与调度身份

| 项 | 当前值 | 冻结结论 |
|---|---|---|
| 旧 task name | `apps.task_monitor.application.tasks.run_personal_readiness_daily_task` | 至少保留一个兼容周期，只做代理 |
| 目标 task name | `apps.operational_readiness.application.tasks.run_personal_readiness_daily_task` | R1C 新增 canonical implementation |
| Beat key | `personal-readiness-daily-evidence` | 永久保持 |
| 默认 schedule | 周一至周五 16:10，Asia/Shanghai | 保持 |
| PeriodicTask name | `personal-readiness-daily-evidence` | 保持；task 字段幂等切换 |
| 默认 kwargs | calendar/workspace/weekly/persistence/repair/closed-date/trigger-source | 保持 |

回滚调度时只需把 `PeriodicTask.task` 和静态 Beat task 字段切回旧 task name；旧代理仍可执行，禁止把手工修库作为唯一回滚路径。

## 3. Evidence provenance

必须继续接受两类历史记录：

- 无 `operation_context` 的 `legacy_without_operation_context` evidence；
- `operation_context.trigger_task_name` 为旧 task 全名的 formal evidence。

R1C 新 evidence 可以记录新 task 全名，但 schema 保持 `operation_context`、`trigger_source`、`trigger_task_id`、`trigger_task_name` 字段。`accepted-readiness-evidence-manifest.v1`、文件 SHA-256、目标日期与历史窗口验证语义保持。

## 4. Runbook、监控与外部引用

| 类型 | 引用 | 结论 |
|---|---|---|
| 主验收文档 | `docs/testing/personal-investment-readiness-2026-06-30.md` | 保持命令与 JSON 契约 |
| 本机监控 | `scripts/check-personal-readiness-monitor.ps1` | 继续调用旧稳定命令名 |
| 稳定化检查 | `scripts/run_post_080_stabilization_checks.py` | 继续调用旧稳定命令名 |
| Dashboard weekly scheduler | `apps/dashboard/management/commands/setup_auto_advisor_weekly_report.py` | 保持与 readiness 时点关系 |
| Task Monitor UI | readiness monitor page/service | UI 可留在 task_monitor，调用新 Application facade |
| 仓储状态 | task_monitor repositories 中 scheduler status | 迁移后只读新 canonical task，同时接受旧 alias |

仓库无法证明第三方监控不存在，因此 R1C 的旧命令和旧 task alias 至少保留到后续明确 sunset 批次。

## 5. Owner 决策

readiness 是跨 account、risk_center、decision、alpha/qlib、scheduler 的生产验收编排，不是“任务执行记录”。目标 owner 固定为无 ORM 模型的 `apps.operational_readiness`：

- Domain：纯 evidence 分类、窗口接受规则；
- Application：collect/run/validate/show/inspect/repair 编排；
- Infrastructure：Django settings、文件、scheduler/PeriodicTask、进程探针；
- Interface：稳定 management command 与 Task Monitor UI facade。

R1C 不创建或迁移数据库模型，不改变 task_monitor 的任务执行记录本职。
