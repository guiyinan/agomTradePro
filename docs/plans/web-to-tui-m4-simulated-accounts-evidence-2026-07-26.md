# Web → TUI M4 Simulated Accounts Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M4-simulated-accounts-w51`；覆盖模拟交易 dashboard、旧 account detail、
  我的账户和我的账户详情 4 个 B 类 route template，完成最后一批 B 类实现。
- 四个页面均引入 Chart.js，但仓内没有 `<canvas>`、`new Chart` 或图表实例，M0 的
  B 分类属于依赖标记的保守静态命中。迁移没有虚报旧图表复刻；在
  `execution.accounts` 复用 owner equity-curve API 发布真实 portable line。
- 新增账户列表、详情、创建、删除、批量删除、绩效、净值曲线、策略选项、绑定和
  解绑 10 个 action，并复用 W37 的持仓、交易和巡检通知 4 个 action。所有账户
  owner scope 和策略 owner scope 继续由最终 API 授权，mutation 显式确认并审计。
- 正式 IA 真源新增 `simulated-accounts` P0 面板，提供账户详情和删除 row action；
  runtime screen patch 同步保留非 IA payload 的兼容投影。Classic dashboard 的
  硬编码定时状态没有提升为运行时事实。
- 分享链接继续使用 `execution.share`，手动成交流水继续使用 `execution.audit`，
  实时行情继续由 Data Center 承载；不在模拟交易屏复制同义任务。
- 四个 Classic 页面均显示准确 action deep link，并继续保留到 M5；页面 hash、
  兼容消费者和回归证据已回写迁移矩阵。

## 验证与风险

- Simulated Trading 账户 API、创建/删除/隔离集成与 Strategy owner API：
  `56 passed`；定向 TUI metadata + 全量 IA/幂等：`7 passed`；AGENTS.md 固定
  其余三组最小回归：`35 passed`；完整 TUI Workbench：`239 passed`。
- migration inventory：196 templates / 117 route pages；inventory/static：
  `5 passed`；本 wave 后 B 类为 17 migrated / 0 backlog。
- `black`、`ruff`、Django system check 和全仓 architecture verify（1912 files /
  0 boundary violations）通过；3 个
  production 文件增量 mypy：`0 regressions`、`0 legacy errors`。
- 未完成 live-server 账户 CRUD/批量删除、策略绑定/解绑、净值曲线、空态、键盘和
  三 viewport UAT；Classic 删除继续受 M5 稳定版本、不少于 14 个自然日、旧入口
  占比、错误率和回滚演练门槛约束。
