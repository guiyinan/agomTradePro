# Web → TUI M3 Task Monitor Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M3-task-monitor-w21`；覆盖计划任务中心和验收监视器 2 个管理员
  route templates。
- `api-library.data-center` 新增 10 个管理员 action：任务健康概览、计划任务目录、
  执行记录/详情/统计、Celery 健康、readiness 状态、readiness 调度读取/更新和
  默认计划任务初始化。
- 新增管理员 owner API：
  `/api/system/scheduler/console/`、`/api/system/scheduler/bootstrap/`、
  `/api/system/readiness/monitor/` 和 `/api/system/readiness/schedule/`。
  接口复用 Task Monitor Application service，计划任务目录限制为 1–200 行，
  Interface 不直接访问 ORM。
- readiness 时间更新继续使用既有 Domain/Application 校验顺序；所有写动作要求
  staff 权限并在 TUI 中显式确认。任务列表的详情入口使用 IA 原生 row action。
- Classic 页面发布精确 TUI deep link，并在稳定期继续保留；原页面的刷新脚本没有
  被复制进 metadata。

## 验证与风险

- Task Monitor API 与 Classic 页面全文件：`20 passed`。
- Task Monitor metadata 与 IA 定向：`7 passed`。
- TUI Workbench 全文件：`212 passed`。首次全文件运行发现 5 个历史 IA 面板
  期望未同步，修正为当前 M2/M3 canonical IA 后全绿。
- ruff 通过；6 个变更生产文件增量 mypy 为 `0 regressions`、`0 legacy errors`。
- migration inventory 为
  `templates=195 route_pages=117 A=130 B=17 C=41 D=7`；TUI static contract
  `407 rule(s), 5 source(s)` 通过。
- 真实 live-server 计划目录→任务详情→严格 readiness→时间更新→默认任务初始化
  UAT 尚未执行；Classic 路由删除仍受 M5 稳定期、访问量和回滚门槛约束。
