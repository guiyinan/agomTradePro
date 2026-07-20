# 可维护性重构 R1 阶段记录

## 阶段目标

完成 Filter 生命周期收口、readiness 内部重复收敛与工具链归位，同时保持 API、命令、Celery、PeriodicTask 和历史 evidence 契约。

## 已完成项

- R1A：Filter API 全响应发布 `Deprecation`/`Sunset` 与 Agom lifecycle headers，响应 JSON 形状保持。
- R1A：Python SDK 调用发布 `FilterModuleDeprecationWarning`；六个 governed MCP manifest 发布完整 lifecycle metadata。
- R1A：sunset 固定为 2026-09-30；当前仅 deprecated，不删除 Django/API/TUI/SDK/MCP。
- R1B：evidence operation context、quote freshness、workspace core status 的重复常量与规则收敛到单一纯规则模块。
- R1C：新增无 ORM 模型的 `apps.operational_readiness` owner。
- R1C：readiness status/monitor Application 服务、evidence 规则、scheduler/runtime/file adapters、八个 management command 实现迁入新 owner。
- R1C：旧 `apps.task_monitor...` 模块保留 import alias，旧管理命令名及 monkeypatch/import surface 保持。
- R1C：新增 canonical Celery task；旧 task name 仅代理公共执行函数。
- R1C：静态 Beat 与 `setup_personal_readiness_daily` 的 PeriodicTask target 切到 canonical task，原 Beat key/PeriodicTask name/schedule/kwargs 保持。
- R1C：Task Monitor UI 通过新 owner Application service 读取 readiness 状态。

## 未完成项

- Filter 物理删除：未满足生产连续访问日志、登记客户端、离线调度、governed capability 四重门槛。
- 旧 readiness import alias、旧 Celery task alias 的删除：至少保留一个兼容周期，须另立 sunset 批次。
- 已有数据库中 `django_celery_beat_periodictask.task` 的实际切换：部署后运行幂等命令 `python manage.py setup_personal_readiness_daily` 完成；代码和测试已覆盖目标字段。本地只读 smoke 已确认旧字段会被识别为 `unexpected_task_path`，本批未擅自改写用户本地调度数据。

## 已验证测试

- `python manage.py check`：通过。
- 四个核心 readiness 管理命令 `manage.py help` smoke：通过；`show_personal_readiness_status` 实际只读命令 smoke：通过。
- readiness / Filter API / manifest schema / SDK / MCP 专项回归：212 passed；Celery 注册契约补充测试复跑：6 passed。
- 固定最小回归包（TUI / Terminal Agent / SDK client / internal SSL redirect）：253 passed。
- `python scripts/check_governance_consistency.py`：0 violation。
- `python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles`：38 modules、188 edges、0 bidirectional pair、0 cycle component。
- `python scripts/check_mcp_manifest_schema.py`：317 capabilities，contract valid。
- canonical 与 legacy readiness Celery task worker discovery：均已注册。
- 变更 Python 文件 `ruff check` 与 `black --check`：通过。

## 未验证风险

- 本地测试不能代替生产 Nginx/Prometheus 的 Filter 调用观察窗口。
- 部署前数据库中的 PeriodicTask 仍可能指向旧 task；本地只读 smoke 已复现该状态。旧 alias 可执行，因此不会形成即时中断，但部署步骤必须运行幂等 setup 命令。
- 外部脚本可能 import 旧 readiness Python 路径；兼容 alias 已覆盖已知路径，未知第三方消费者需通过一个兼容周期观察。

## 回滚点

- Filter lifecycle metadata 可独立 revert，不影响算法与数据。
- Beat/PeriodicTask 可把 task 字段切回旧 task name；旧 task 仍执行同一 canonical runner。
- `operational_readiness` owner 与旧 alias 分步存在；回滚 app 注册后旧路径仍可恢复到迁移前实现，不需要数据库回滚。
