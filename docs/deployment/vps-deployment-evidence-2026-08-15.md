# VPS 候选部署证据（2026-08-15）

## 结论

`dev/next-development` 的提交 `96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952` 已在 `demo.agomtrade.pro` 完成一次带 provenance 校验的后续候选部署。该 release 包含 TUI AI provider failure guidance 修复；当前服务正常运行，M5 观察窗口从本次独立核验时间重新计算。本证据不解除角色化浏览器 UAT、写后回执、14 日观察、恢复演练或数据覆盖门禁。

## 发布身份

| 项目 | 证据 |
|---|---|
| release tag | `20260815144517` |
| current release | `/opt/agomtradepro/releases/source-20260815144517` |
| source commit | `96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952` |
| image | `agomtradepro-web:20260815144517` |
| image ID | `sha256:38c68ff15ed4ce09a0a29b15744ac46c5287a5817f418d97666d96a81ad37839` |
| OCI revision | 与 source commit 完全一致 |
| release manifest | `/opt/agomtradepro/releases/source-20260815144517/.agom-release-manifest.json`，权限 `0444` |
| deploy report | `/tmp/agomtradepro-deploy-report.json`（VPS） |
| SQLite | `INCLUDE_SQLITE=0`；未复制或切换 SQLite volume |

### 构建边界

本次使用 `git-clone` 模式完成标准远端 Docker 构建，release manifest 的 `source_mode=git-clone`，并在新 image 中独立验证 `pyqlib=0.9.7`、错误的 `qlib` distribution 缺失。上一次 `20260815125858` 的 code-only overlay 仅作为历史候选保留；本次已完成全量依赖构建，但仍不替代长期可重复 runner、供应链签名和 restore/rebuild 演练。

## 运行复核

部署脚本 `ACTION=upgrade`、`WIPE_DOCKER=0`、`WIPE_VOLUMES=0`、`INCLUDE_SQLITE=0`、Celery/RSSHub enabled；部署前自动备份成功，随后执行迁移、canonical schema、catalog、Django deploy check、collectstatic、AI catalog、TUI publish 和启动检查。

| 检查 | 结果 |
|---|---|
| `GET https://demo.agomtrade.pro/api/health/` | `{"status":"ok"}`，2026-08-15T07:03:26Z 独立复核 |
| `GET https://demo.agomtrade.pro/api/ready/` | HTTP 200、基础依赖和 Celery 正常；响应同时报告 Alpha/Qlib `degraded` 与 workspace stale warnings，不能据此宣称 decision-data gate 已完成 |
| web / worker / beat | 全部使用 `agomtradepro-web:20260815144517`，web healthy |
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

- 备份：`/opt/agomtradepro/backups/database/postgres-20260815-085317.dump`
- 大小：`140079790` bytes
- SHA-256：`f72ea2cff4ff2c137425069a404936e6d24ed8a301533f49bdea943d0334535e`
- 备份 manifest：`/opt/agomtradepro/backups/meta/manifest-20260815-085317.txt`

该文件证明部署前恢复点已生成并校验；尚未证明下载到外部存储、独立 restore/rebuild、RTO/RPO 或回滚演练。

## 本地发布回归

- `tests/unit/test_remote_build_deploy_vps.py` + `tests/unit/test_deploy_vps_verify.py`：`50 passed`。
- `tests/unit/test_tui_actionability_contract.py`：`10 passed`。
- `tests/unit/test_terminal_agent_service.py`：`13 passed`；`sdk/tests/test_sdk/test_client.py`：`22 passed`；`tests/unit/test_internal_ssl_redirect.py`：`6 passed`。
- 固定整套 `tests/unit/test_tui_workbench.py`：`250 passed`。后续修复覆盖 provider failure 原始错误码映射（包括 `terminal_agent_unavailable`）以及结果字段位于 `view_model.fields` 的契约；该修复已随 `96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952` 部署。
- 发布前门禁复核：current-data `49 surface(s)`、Celery `88 registered task(s)`、架构扫描 `2903 files / 0 boundary violations / 0 audit violations`。

## 未完成门禁

- M5 角色化浏览器 UAT、写后 receipt/refresh、生产错误率/telemetry 与 14 日观察窗口尚未完成；不得清理 Classic 或进入 M5-B。
- Data Center 全市场覆盖、shadow reconciliation、性能/锁预算和真实恢复演练仍未完成。
- AUD-01 durable publisher、authenticated scoped authority 与生产运行时接线仍未完成；本次部署不解除相关 gate。
- overlay 依赖基底的全量可重复构建仍需单独取得成功证据。

## 后续候选部署（2026-08-15 15:28 release）

为纳入 `AUD-01` malformed receipt fail-closed 修复，重新以
`dev/next-development@a76db97d4322fd7f6a2323f4f567873e8c53199c` 运行同一套
`-Upgrade`、代码-only、保留数据卷的 VPS 部署。远端 `git-clone` 构建与 provenance
校验成功，且已完成服务重启后的独立复核。

| 项目 | 证据 |
|---|---|
| release tag | `20260815152834` |
| current release | `/opt/agomtradepro/releases/source-20260815152834` |
| source commit | `a76db97d4322fd7f6a2323f4f567873e8c53199c` |
| image | `agomtradepro-web:20260815152834` |
| image ID | `sha256:12c5ce84ecd2d072846bb7777e6e0345e3ed83e98333bdf80ca35108d2a5c385` |
| OCI/source binding | release manifest source commit 与 OCI revision 均等于 `a76db97d4322fd7f6a2323f4f567873e8c53199c` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260815152834.json`（本地下载副本） |
| backup | `/opt/agomtradepro/backups/database/postgres-20260815-093506.dump`；manifest `/opt/agomtradepro/backups/meta/manifest-20260815-093506.txt` |

复核结果：HTTPS `/api/health/` 与 `/api/ready/` 均 HTTP 200；web healthy，Celery
worker/beat、PostgreSQL、Redis、RSSHub 均运行；account migrations 无待应用项，
canonical schema、Django deploy check、TUI publish/check、Qlib `pyqlib=0.9.7`
（错误 `qlib` distribution 缺失）和 Celery ping 均通过。`/api/ready/` 仍报告
Alpha/Qlib provider degraded、workspace recommendation stale，以及市场温度计部分
组件 stale；这些 warning 不得被写成 decision-data 或 M5 完成证据。

该候选只更新部署身份与运行复核，不解除 M5 角色化浏览器 UAT、写后回执、14 日观察、
restore/rebuild，也不解除 AUD-01 durable publisher、authenticated scoped authority
和生产 runtime wiring 门禁。
