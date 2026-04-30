# Alpha / Qlib 运维台 V1

最后更新：2026-04-28

## 目标

把 Alpha 推理运维和 Qlib 基础数据运维从普通 Dashboard 中拆出来，放到独立的 staff 运维入口中，避免把“推理状态”“缓存状态”“Qlib 本地数据状态”混在一个按钮里。

## 页面入口

- `GET /alpha/ops/inference/`
- `GET /alpha/ops/qlib-data/`

入口整合方式：

- superuser 在 `管理控制台` 中看到：
  - `Alpha 推理管理`
  - `Qlib 基础数据管理`
- staff 用户在右上角用户菜单中看到：
  - `Alpha 运维`

## API 端点

- `GET /api/alpha/ops/inference/overview/`
- `POST /api/alpha/ops/inference/trigger/`
- `GET /api/alpha/ops/qlib-data/overview/`
- `POST /api/alpha/ops/qlib-data/refresh/`

权限规则：

- `overview` 端点：`is_staff`
- `trigger/refresh` 端点：`is_superuser`

## 推理页职责

`Alpha 推理管理` 负责：

- 当前激活模型摘要
- Qlib runtime / Celery 健康状态
- 当前进行中的 Dashboard Alpha refresh lock
- 最近推理任务
- 最近 Qlib cache
- 最近 Alpha alert
- 手动触发：
  - `general`
  - `portfolio_scoped`
  - `daily_scoped_batch`

不负责：

- 模型训练
- 模型导入
- 模型激活

上述模型管理动作继续保留在 Django Admin `QlibModelRegistry`。

## Qlib 数据页职责

`Qlib 基础数据管理` 负责：

- Qlib runtime config 摘要
- 本地最新交易日与 lag
- 最近 Qlib data refresh 任务
- 最近 build summary
- 手动刷新：
  - `universes`
  - `scoped_codes`

不负责：

- 删除本地 Qlib 数据
- 手改 provider 路径
- 编辑系统配置

## 实现说明

### 0. 告警语义修正（2026-04-30）

`/dashboard/` 与部分查询服务会按 `qlib -> cache -> simple -> etf` 逐个传 `provider_filter`
做单点探测。

从 `2026-04-30` 起：

- 这类“单 provider 探测失败”不再写入 `provider_unavailable`
- `provider_unavailable` 只表示完整自动降级链已经全部失败
- 因此运维页里的“所有 Alpha Provider 不可用”不再出现 `尝试顺序: simple`
  这类误导性单点失败告警

配套回归入口：

- `python scripts/run_alpha_ops_regression.py`

当前回归套件覆盖：

- Qlib data refresh 投递后，overview/page 立刻可见 `pending` 任务
- Dashboard Alpha 手动 refresh / 自动补推理在 `delay()` 后立刻写入 `task_monitor`
- Policy RSS 手动抓取接口在返回 `task_id` 时立刻写入 `task_monitor`
- Data Center decision reliability repair 触发 scoped Alpha 推理时立刻写入 `task_monitor`
- `provider_filter` 单点探测失败不再误报全局 `provider_unavailable`
- Dashboard Alpha 查询仍保持现有 fast-path / fallback 语义

### 1. Qlib 数据刷新逻辑抽取

原先 `apps.alpha.application.tasks` 中的：

- `_refresh_qlib_runtime_data`
- `_refresh_qlib_runtime_data_for_codes`

现在统一委托到 `QlibRuntimeDataRefreshService`，这样：

- 定时任务
- 运维页手动触发

共用同一套 Qlib recent build 逻辑。

### 2. 运维专用 Celery 任务

新增任务：

- `apps.alpha.application.tasks.qlib_refresh_runtime_data_task`
- `apps.alpha.application.tasks.qlib_refresh_runtime_data_for_codes_task`

任务返回标准化 summary dict，供 `task_monitor` 保存和页面展示。

从 `2026-04-30` 起，Ops 页和 Dashboard Alpha 异步入口在 `delay()` 成功后都会立刻写入一条 `pending` 的 `task_monitor` 记录。

效果：

- `/alpha/ops/qlib-data/` 底部“最近刷新任务”不再需要等 worker 真正 `prerun` 后才出现
- 刷新后页面可以立即看到刚投递的任务 ID 和 `pending` 状态
- Dashboard 手动 refresh / 自动补推理在 `task_monitor` 中也不再出现“排队成功但暂时查不到任务”的观察盲区
- worker 开始执行后，`task_monitor` 的 `task_prerun/task_postrun` 信号会继续把同一条记录更新为 `started/success/failure`

### 3. 防重复语义

Alpha 运维页的单次推理触发复用了 Dashboard 同 scope/date/top_n 的防重语义。

效果：

- 同一时间同一 scope 的 Dashboard 手动 refresh 和 Ops 手动 trigger 不会并发重复投递
- 命中锁时接口返回 `409`

同时新增了：

- 批量 scoped inference 的单独锁
- Qlib data refresh 的单独锁

如果 `delay()` 本身失败，锁会立即释放，避免 stale lock。

## 架构落点

- 页面与 API：`apps.alpha.interface`
- 运维编排：`apps.alpha.application.ops_use_cases`
- 概览查询与 Qlib build service：`apps.alpha.application.ops_services`
- 防重锁：`apps.alpha.application.ops_locks`

这样保持：

- Interface 只做权限校验、参数校验、响应格式化
- Application 负责任务编排和聚合查询
- Infrastructure 仍然只做 ORM / Qlib builder / Task Monitor 持久化
