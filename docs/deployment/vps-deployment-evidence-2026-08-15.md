# VPS 候选部署证据（2026-08-15）

## 结论

`dev/next-development` 的提交 `304ce86baa9177cfec27ae59fffb477c2d7ac5dc` 已在 `demo.agomtrade.pro` 完成一次带 provenance 校验的候选部署。当前服务正常运行，M5 观察窗口从本次独立核验时间重新计算；本证据不解除角色化浏览器 UAT、写后回执、14 日观察、恢复演练或数据覆盖门禁。

## 发布身份

| 项目 | 证据 |
|---|---|
| release tag | `20260815125858` |
| current release | `/opt/agomtradepro/releases/source-20260815125858` |
| source commit | `304ce86baa9177cfec27ae59fffb477c2d7ac5dc` |
| image | `agomtradepro-web:20260815125858` |
| image ID | `sha256:72ea6d5b6ea55ae8501a757ba9b1876a914224f29cf8312907efe7d961caf5aa` |
| OCI revision | 与 source commit 完全一致 |
| release manifest | `/opt/agomtradepro/releases/source-20260815125858/.agom-release-manifest.json`，权限 `0444` |
| deploy report | `/tmp/agomtradepro-deploy-report.json`（VPS） |
| SQLite | `INCLUDE_SQLITE=0`；未复制或切换 SQLite volume |

### 构建边界

标准远端 Docker BuildKit 在安装 `pyqlib==0.9.7` 阶段因 builder context cancel 失败，未切换服务。随后使用已运行生产镜像 `agomtradepro-web:20260813021923`（已独立确认 `pyqlib 0.9.7`）作为依赖基底，仅叠加本次 Git clone release 的代码并写入同一 OCI revision；因此本次是 **code-only overlay candidate**，不是一次全量依赖重建证明。后续仍需在可重复构建 runner 上完成标准镜像重建，不能把本次 overlay 当作依赖供应链验收。

## 运行复核

部署脚本 `ACTION=upgrade`、`WIPE_DOCKER=0`、`WIPE_VOLUMES=0`、`INCLUDE_SQLITE=0`、Celery/RSSHub enabled；部署前自动备份成功，随后执行迁移、canonical schema、catalog、Django deploy check、collectstatic、AI catalog、TUI publish 和启动检查。

| 检查 | 结果 |
|---|---|
| `GET https://demo.agomtrade.pro/api/health/` | `{"status":"ok"}`，2026-08-15T05:40:07Z 独立复核 |
| `GET https://demo.agomtrade.pro/api/ready/` | HTTP 200、基础依赖和 Celery 正常；响应同时报告 Alpha/Qlib `degraded` 与 workspace stale warnings，不能据此宣称 decision-data gate 已完成 |
| web / worker / beat | 全部使用 `agomtradepro-web:20260815125858`，web healthy |
| PostgreSQL / Redis / RSSHub | healthy |
| account migrations | `0037`–`0053` 均为 `[X]`；`verify_canonical_schema` 返回 `missing_migrations=[]`, `missing_tables=[]`, `ok=true` |
| `manage.py check --deploy` | 通过（1 项既有 silenced warning） |
| Qlib | `pyqlib 0.9.7` |
| Celery | `inspect ping` 返回 `1 node online` |
| Caddy | `caddy validate` 返回 `Valid configuration` |
| TUI registry | publish/check 均通过；registry `21`、backend `20260815125858`、active source hash 与 expected 完全一致 |
| unauthenticated `/api/tui/` | HTTP 403；这是未登录探针结果，不替代真实浏览器/角色化 UAT |
| release source | 远端 `git rev-parse` 与候选 commit 一致；manifest/Caddy 是部署生成文件，不属于源码漂移 |

## 恢复点

- 备份：`/opt/agomtradepro/backups/database/postgres-20260815-073132.dump`
- 大小：`139155008` bytes
- SHA-256：`ce0e72418640ad154ae95fe67d93e1443839ad181cc3ec9bf0bbfc23b2d2b20e`
- 备份 manifest：`/opt/agomtradepro/backups/meta/manifest-20260815-073132.txt`

该文件证明部署前恢复点已生成并校验；尚未证明下载到外部存储、独立 restore/rebuild、RTO/RPO 或回滚演练。

## 本地发布回归

- `tests/unit/test_remote_build_deploy_vps.py` + `tests/unit/test_deploy_vps_verify.py`：`50 passed`。
- `tests/unit/test_tui_actionability_contract.py`：`10 passed`。
- `tests/unit/test_terminal_agent_service.py`：`13 passed`；`sdk/tests/test_sdk/test_client.py`：`22 passed`；`tests/unit/test_internal_ssl_redirect.py`：`6 passed`。
- 固定整套 `tests/unit/test_tui_workbench.py`：`247 passed, 3 failed`。失败均在 `test_tui_ai_result_maps_provider_runtime_failures_to_actionable_guidance`，表现为 provider failure payload 缺少 `fields` 或错误码为空；本次没有修改该运行逻辑，因此不把整套 Workbench 回归写成通过，M5 继续阻断。
- 发布前门禁复核：current-data `49 surface(s)`、Celery `88 registered task(s)`、架构扫描 `2903 files / 0 boundary violations / 0 audit violations`。

## 未完成门禁

- M5 角色化浏览器 UAT、写后 receipt/refresh、生产错误率/telemetry 与 14 日观察窗口尚未完成；不得清理 Classic 或进入 M5-B。
- Data Center 全市场覆盖、shadow reconciliation、性能/锁预算和真实恢复演练仍未完成。
- AUD-01 durable publisher、authenticated scoped authority 与生产运行时接线仍未完成；本次部署不解除相关 gate。
- overlay 依赖基底的全量可重复构建仍需单独取得成功证据。
