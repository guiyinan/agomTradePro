# R0 Filter 生命周期与消费者清单

> 状态：已冻结；R1A 结论为“只弃用，不删除”
> 取证日期：2026-07-20
> 稳定身份：Django app `filter`、API `/api/filter/**`、SDK `client.filter`、MCP owner `filter`

## 1. 已登记消费者

| 消费面 | 当前证据 | 冻结结论 |
|---|---|---|
| Django | `core/settings/base.py` 注册 `apps.filter` | 弃用期保持 |
| HTTP API | `core/urls.py` 暴露 `/api/filter/`，含 apply/get-data/compare/indicators/config/health | 路径与响应体保持；增加弃用 header |
| TUI | generated/published operation graph 含 filter root、indicators、health、config | 仍是明确消费者；sunset 前不得移除 |
| Python SDK | `sdk/agomtradepro/modules/filter.py`，通过 `client.filter` 暴露 | 保持兼容；调用时发出 FutureWarning |
| legacy MCP | `filter_tools.py` 注册 list/get/create/update/delete/health 六个工具 | 保持注册；不得新增调用方 |
| governed MCP | 三个 read manifest + 三个 write manifest | 保持 enabled，显式发布 lifecycle metadata |
| 自动测试 | API edges、SDK endpoints、MCP owner/read matrix、TUI workbench | 作为兼容基线保留 |

全仓业务源码未发现除路由、TUI/SDK/MCP 接入层之外的 `apps.filter` 业务依赖；HP/Kalman 的可复用算法真源仍是 `shared/infrastructure/calculators.py` 与 `shared/infrastructure/kalman_filter.py`。这只能证明“内部业务未依赖”，不能证明外部客户端无调用。

## 2. 访问日志观察窗口

- 弃用契约首次进入可部署代码的日期：2026-07-20。
- 最短观察窗口：弃用版本生产发布后连续 30 天，且必须覆盖一个完整发布周期。
- 公示 sunset：2026-09-30；该日期不是自动删除授权。
- Prometheus 查询口径：对 `api_request_total` 中 endpoint 匹配 `/api/filter/` 及其子路径的增量，按 method/endpoint/status_code 汇总。
- Nginx 复核口径：访问日志中 request path 匹配 `^/api/filter(?:/|$)`；排除部署 smoke、监控健康检查和已登记的内部探针后单列真实调用。
- SDK/MCP 口径：服务端 API 日志为最终调用证据；同时复核 MCP audit/capability call 中 owner/capability key 为 `filter` 的记录。

仓库内没有可证明生产连续窗口的访问日志快照，也没有外部客户端登记库。因此 R0 不宣称“零调用”。

## 3. 物理下线四重门槛

只有以下条件同时满足，才允许另立 R1A 删除批次：

1. 生产访问日志在完整观察窗口内零真实调用；
2. 已登记 API/SDK 客户端清单中零 active 消费者；
3. Celery、Cron、离线脚本和运维 smoke 中零 filter 调用；
4. TUI 与 governed MCP inventory 已先移除或迁移 filter 能力，且对应治理检查绿色。

删除必须与本次 deprecated commit 分离，可整体 revert。sunset 前如果任一门槛不满足，只延长弃用期，不删除。

## 4. 稳定身份决策

| 身份 | R1A | 后续删除批次 |
|---|---|---|
| `app_label=filter`、既有表 | 保持 | 单独设计 migration/归档，不随代码直接消失 |
| API path/namespace | 保持 | sunset 后一次性移除并更新 inventory |
| SDK 属性与方法 | 保持并 warning | 下一个明确的破坏性版本才移除 |
| MCP tool/capability key | 保持 enabled + deprecated | 先从发现面下线，再移除 legacy alias |
| TUI action key | 保持 | 先发布替代用户任务，再删除生成物 |
