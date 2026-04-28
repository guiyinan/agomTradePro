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
