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

## 后续候选部署（2026-08-15 16:24 release）

为纳入 Account Physical v2 migration-state drift 修复（`0054`）与 DATA-02 控制面
run/batch/checkpoint 原子快照修复，`dev/next-development@ae1e5e532e51b67731563b21b2224372752ee15b`
再次以 `-Upgrade`、代码-only、保留数据卷方式部署。远端 git-clone 构建、provenance
校验、迁移步骤、canonical schema check 与服务启动均完成。

| 项目 | 证据 |
|---|---|
| release tag | `20260815162419` |
| current release | `/opt/agomtradepro/releases/source-20260815162419` |
| source commit | `ae1e5e532e51b67731563b21b2224372752ee15b` |
| image | `agomtradepro-web:20260815162419` |
| image ID | `sha256:619a0f24a5ada39a2aa3f8af1391a7143026784bae56fbdc8f69a88a0a513a77` |
| OCI/source binding | release manifest 与 OCI revision 均绑定到 `ae1e5e532e51b67731563b21b2224372752ee15b` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260815162419.json`（本地下载副本） |
| pre-deploy backup | `/opt/agomtradepro/backups/database/postgres-20260815-103019.dump` |

独立复核：`GET https://demo.agomtrade.pro/api/health/` 在 2026-08-15T08:39:04Z
返回 HTTP 200 `status=ok`；`/api/ready/` 在 2026-08-15T08:39:14Z 返回 HTTP 200，
database/Redis/Celery（1 worker）/critical data 均 `ok`。web healthy，Celery
worker/beat、PostgreSQL、Redis、RSSHub 运行，TUI registry publish/check、Qlib
`pyqlib=0.9.7`（错误 `qlib` distribution 缺失）和 Celery ping 均通过；部署输出的
迁移步骤无待应用项，canonical schema `missing_migrations=[]`、`missing_tables=[]`。

本次 `/api/ready/` 仍明确报告 Alpha/Qlib provider degraded、workspace recommendation
stale、market thermometer 部分组件 stale；这些 warning 不能写成 decision-data gate
或 M5 完成证据。该候选也不解除 DATA-01 restore/rebuild/维护态回滚、DATA-02 生产回填与
coverage/reconciliation、AUD-01 publisher/authority/runtime wiring 或 TUI 角色化 UAT。

## 恢复点（2026-08-15 16:24 candidate）

部署后用 `scripts/backup-vps-postgres.ps1 -DownloadLatest` 重新下载并验证远端 custom-format
归档：

- 远端：`/opt/agomtradepro/backups/database/postgres-20260815-103019.dump`
- 本地：`backups/vps-postgres/postgres-20260815-103019.dump`
- 大小：`140112628` bytes
- SHA-256：`46dd5003de2943ac23d8ab599c24454e3e770b7828b088857be355fa4f5a364d`
- 远端 `pg_restore --list`、SFTP 完整下载、尺寸与本地 SHA-256 均通过；prune 未启用

这仍只是恢复点证据，不是 restore/rebuild、RTO/RPO 或维护态回滚演练。

## 当前候选部署（2026-08-15 18:28 release）

为部署当前 `dev/next-development`（含 AUD-01 canonical receipt exact-tree hardening），
再次执行标准 `git-clone`、`-Upgrade`、代码-only 发布并保留远端 PostgreSQL 数据卷。部署脚本
在切换前生成远端 PostgreSQL/Redis 备份，迁移与 canonical schema 检查通过，未应用新的 migration。

| 项目 | 证据 |
|---|---|
| release tag | `20260815182857` |
| current release | `/opt/agomtradepro/releases/source-20260815182857` |
| source commit | `cf68dc1e972ecd6e0ae002e4d4f96ff07ef86542` |
| image | `agomtradepro-web:20260815182857` |
| image ID | `sha256:e04018272c08ef2dec2ffa98619e99ad689649c06da5964cbe93a9493602a552` |
| OCI/source binding | release manifest source commit、image revision 与 `cf68dc1e972ecd6e0ae002e4d4f96ff07ef86542` 完全一致 |
| deployment report | `dist/remote-build-reports/remote-build-report-20260815182857.json`（本地下载副本） |
| pre-deploy backup | `/opt/agomtradepro/backups/database/postgres-20260815-123539.dump`；manifest `/opt/agomtradepro/backups/meta/manifest-20260815-123539.txt` |
| mode | `ACTION=upgrade`、code-only、`WIPE_DOCKER=0`、`WIPE_VOLUMES=0`、Celery enabled |

部署后独立复核：`GET https://demo.agomtrade.pro/api/health/` 于
`2026-08-15T10:44:06Z` 返回 HTTP 200 `status=ok`；`/api/ready/` 于
`2026-08-15T10:44:16Z` 返回 HTTP 200 `status=ok`，database/Redis/Celery/critical data
均为 `ok`，web、Celery worker/beat、PostgreSQL、Redis、RSSHub 均运行，Caddy TLS 检查通过。
TUI registry publish/check、`pyqlib=0.9.7`（错误 `qlib` distribution 缺失）、Celery ping、
account migration 与 canonical schema 复核均通过。

`/api/ready/` 仍报告 Alpha/Qlib provider degraded、workspace recommendation stale，以及
market thermometer 的部分组件 stale；这些 warning 继续禁止 decision-data gate、M5 角色化
UAT 或 14 日观察窗口被写成完成证据。部署身份更新也不解除 AUD-01 durable publisher、
authenticated scoped authority、runtime wiring、DATA-01 restore/rebuild 或 rollback 门禁。

## 当前候选部署（2026-08-15 20:07 release）

为部署当前 `dev/next-development`（含 EVID-01 scope provider 异常边界加固），执行标准
`git-clone`、`fresh`、代码-only 发布；远端数据卷保留，未带入本地 SQLite，Celery enabled。
构建、迁移、canonical schema、TUI registry、服务启动和 provenance 校验均通过。

| 项目 | 证据 |
|---|---|
| release tag | `20260815200756` |
| current release | `/opt/agomtradepro/releases/source-20260815200756` |
| source commit | `11594964f589c5f0ec3bf6a541d61d471b79b67f` |
| image | `agomtradepro-web:20260815200756` |
| image ID | `sha256:2983bd567f4cb86a52ce48d7a1c3f2162fec4cddbaddb007975375b9448052af` |
| OCI/source binding | release manifest source commit、image revision 与上述完整 commit 一致 |
| deployment report | `dist/remote-build-reports/remote-build-report-20260815200756.json`（本地下载副本） |
| pre-deploy backup | `/opt/agomtradepro/backups/database/postgres-20260815-141446.dump`；manifest `/opt/agomtradepro/backups/meta/manifest-20260815-141446.txt` |
| mode | `ACTION=fresh`、code-only、项目 Docker cleanup、`WIPE_VOLUMES=0`、Celery enabled |

部署后独立复核：从 VPS 执行 HTTPS `GET https://demo.agomtrade.pro/api/health/` 与
`/api/ready/` 均 HTTP 200，时间分别为 `2026-08-15T12:24:40Z` 与
`2026-08-15T12:25:33Z`；Caddyfile 首行保留 `demo.agomtrade.pro {`，Caddy 自动 TLS 日志正常。
web、Celery worker/beat、PostgreSQL、Redis、RSSHub 运行且 web/PostgreSQL/Redis/RSSHub healthy；
`pyqlib=0.9.7`，错误 `qlib` distribution 缺失，Celery ping 为 `1 node online`。迁移无待应用项，
canonical schema、Django deploy check 与 TUI registry publish/check 通过。

`/api/ready/` 继续保留 Alpha/Qlib provider degraded、workspace recommendation stale、
Alpha rank source stale 和 market thermometer partial-stale warnings；这些 warning 不得写成
decision-data gate 或 M5 完成证据。该候选只更新部署身份与运行复核，不解除 EVID-01 immutable
owner/tenant authority、AUD-01 durable publisher/authority/runtime、M5 角色化浏览器 UAT/14 日
观察、DATA-01 restore/rebuild 或 rollback 双签门禁。

本机随后尝试 Playwright 访问同一 HTTPS TUI 入口，仍收到 `net::ERR_CONNECTION_CLOSED`；
这只能记录为本地外部浏览器传输阻断，不能替代角色化 UAT。当前没有使用生产凭据，也没有执行
登录、写操作、写后回执或权限角色验证。

从 VPS 发出的未认证 `GET /api/tui/` 返回 HTTP `403`；这只证明匿名访问边界仍在，不能计入
普通用户、owner、operator 或 admin 的角色化 screen/action UAT。

为排除本机到公网入口的单一路由问题，本机又通过一次临时 SSH 本地端口转发访问同一
Caddy 443，并用 Playwright 请求 `https://demo.agom.pro:8443/tui/`；TLS 握手返回
`net::ERR_SSL_PROTOCOL_ERROR`，隧道随后关闭。该探针没有使用生产凭据，也没有执行登录或
写操作；因此仍只保留匿名 403 与浏览器传输阻断证据，角色化浏览器 UAT、写后回执和 14 日
观察窗口继续未完成。

## 当前候选部署（2026-08-15 22:10 release）

为部署 `dev/next-development` 当前提交（包含 AUD-01 provider-issued query context
boundary），执行标准 `git-clone`、`-Upgrade`、code-only 发布；远端 PostgreSQL/Redis 数据卷
保留，未恢复本地 SQLite，Celery enabled。构建、provenance、迁移、canonical schema、TUI
registry、服务启动和健康复核均通过。

| 项目 | 证据 |
|---|---|
| release tag | `20260815221000` |
| current release | `/opt/agomtradepro/releases/source-20260815221000` |
| source commit | `1835ce0ee42f220756066a21890bcec2b8f1f3e9` |
| image | `agomtradepro-web:20260815221000` |
| image ID | `sha256:ef43c80ee8b5130775f152dfea0a7cdc62a93a8853ab4ccb8ba258ae83877ad1` |
| OCI/source binding | release manifest source commit、image revision 与 `1835ce0ee42f220756066a21890bcec2b8f1f3e9` 完全一致 |
| deployment report | `dist/remote-build-reports/remote-build-report-20260815221000.json`（本地下载副本） |
| pre-deploy backup | `/opt/agomtradepro/backups/database/postgres-20260815-161622.dump`；manifest `/opt/agomtradepro/backups/meta/manifest-20260815-161622.txt` |
| mode | `ACTION=upgrade`、code-only、`WIPE_DOCKER=0`、`WIPE_VOLUMES=0`、Celery enabled |
| candidate binding | `web-to-tui-candidate-binding.v1`; matrix SHA `bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`; published graph SHA `fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84` |
| runtime binding | schema `tui-metadata.v3`; runtime `0.2.0`; build `agomtui-runtime-0.2.0+a2553996be22`; manifest SHA `a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854` |

## 当前候选部署（2026-08-15 23:05 release）

为 `dev/next-development` 提交 `45281620a8739ee666a1b20e6c6511c0b8101111` 执行标准
`git-clone`、`-Upgrade`、code-only 发布；远端 PostgreSQL/Redis 数据卷保留，Celery enabled。

| 项目 | 证据 |
|---|---|
| release tag | `20260815230537` |
| current release | `/opt/agomtradepro/releases/source-20260815230537` |
| source commit | `45281620a8739ee666a1b20e6c6511c0b8101111` |
| image | `agomtradepro-web:20260815230537` |
| image ID | `sha256:77fffa7e224b103d44d19d79acfc41ea297ab4f9acccd675716def4d24dbe07b` |
| OCI/source binding | release manifest source commit、image revision 与 `45281620a8739ee666a1b20e6c6511c0b8101111` 完全一致 |
| deployment report | `dist/remote-build-reports/remote-build-report-20260815230537.json`（本地下载副本） |
| pre-deploy backup | `/opt/agomtradepro/backups/database/postgres-20260815-171200.dump` |
| mode | `ACTION=upgrade`、code-only、`WIPE_DOCKER=0`、`WIPE_VOLUMES=0`、Celery enabled |
| candidate binding | matrix SHA `bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`; graph SHA `fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84`; runtime manifest SHA `a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854` |
| migration proof | remote `audit` migrations show `[X] 0012_systemauditevent_scope` |
| audit scope inventory | remote read-only ORM count at `2026-08-15T15:30:22Z`: total `0`, scoped `0`, unscoped `0`; no backfill or seed observed |

部署后复核：Django `check` 0 issues；HTTPS `/api/health/` HTTP 200；web/Celery worker/beat、
PostgreSQL、Redis、Caddy、RSSHub healthy/running；TUI registry check matched；Qlib `pyqlib=0.9.7`
且错误 `qlib` distribution absent；Celery ping OK。该部署不等于角色化生产 UAT、写后回执、
14 日 telemetry/defect、registry backup/restore、rollback 或双签完成。

部署复核：HTTPS `/api/health/` 返回 HTTP 200；web healthy，Celery worker/beat、PostgreSQL、
Redis、RSSHub 运行；account migrations 无待应用项，canonical schema、Django deploy check、
TUI registry publish/check、Qlib `pyqlib=0.9.7`（错误 `qlib` distribution 缺失）和 Celery ping
均通过。TUI 本地 preflight 的 `check:tui` 与 34 项浏览器契约也通过；这不等于生产角色化
浏览器 UAT。

`/api/ready/` 继续保留 Alpha/Qlib provider degraded、workspace recommendation stale 和
market thermometer partial-stale warnings；本次候选只更新 AUD-01 Application context 的
运行身份与健康证据，不解除 authenticated scoped authority、durable publisher/runtime wiring、
M5 角色化 UAT/14 日观察、DATA-01 restore/rebuild 或 rollback 双签门禁。

## 当前候选部署（2026-08-16 00:41 release）

包含 AUD-01 authority freshness/PIT contract 的 `dev/next-development@e167ab2fc748e4c93d2622f93fa8cc75442b2bb6`
执行标准 `git-clone`、`-Upgrade`、code-only 发布；远端 PostgreSQL/Redis 数据卷保留，未恢复
本地 SQLite，Celery enabled。部署前验证了工作区 clean、GitHub 分支已推送、TUI runtime
`check:tui` 与 34 项 JavaScript 浏览器契约通过。

| 项目 | 证据 |
|---|---|
| release tag | `20260816004134` |
| current release | `/opt/agomtradepro/releases/source-20260816004134` |
| source commit | `e167ab2fc748e4c93d2622f93fa8cc75442b2bb6` |
| image | `agomtradepro-web:20260816004134` |
| image ID | `sha256:151801bdbacecc8bc8d3f19c43817be1ff58ed06981cbdba9a49692289bbc0ac` |
| build window | `2026-08-15T16:41:38Z` → `2026-08-15T16:48:00Z` |
| OCI/source binding | release manifest source commit、image revision 与 `e167ab2fc748e4c93d2622f93fa8cc75442b2bb6` 完全一致 |
| deployment report | `dist/remote-build-reports/remote-build-report-20260816004134.json`（本地下载副本） |
| pre-deploy backup | `/opt/agomtradepro/backups/database/postgres-20260815-184803.dump`；size `140318641` bytes；SHA-256 `4760a38fdfc7ef8570323cfb5dde92ab01eb933cd60d4f6dd08700fc34772752` |
| backup proof | PostgreSQL 16 container `pg_restore --list` exit `0`；archive header `2026-08-15 16:48:04 UTC` |
| mode | `ACTION=upgrade`、code-only、`WIPE_DOCKER=0`、`WIPE_VOLUMES=0`、Celery enabled |
| candidate binding | `web-to-tui-candidate-binding.v1`; matrix SHA `bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`; published graph SHA `fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84` |
| runtime binding | schema `tui-metadata.v3`; runtime `0.2.0`; build `agomtui-runtime-0.2.0+a2553996be22`; manifest SHA `a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854` |
| migration proof | remote audit migration `0012_systemauditevent_scope` applied；deploy reported `No migrations to apply` and canonical schema check `{"missing_migrations": [], "missing_tables": [], "ok": true}` |

部署后只读复核：Caddy 首行仍为 `demo.agomtrade.pro {`，HTTPS `/api/health/` HTTP 200，
HTTPS `/api/ready/` HTTP 200；web healthy，Celery worker/beat、PostgreSQL、Redis、RSSHub
运行且 Celery ping `1 node online`；TUI registry check matched；Qlib `pyqlib=0.9.7`、错误
`qlib` distribution absent，module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py`。

`/api/ready/` 仍原样报告 Alpha/Qlib provider degraded、workspace recommendation stale、
Alpha rank source stale 与 market thermometer partial-stale warnings。该候选只证明当前
代码身份、部署启动、schema/backup/health 和本地 TUI 契约，不证明 authenticated tenant/owner
authority、durable publisher/receipt sink、生产角色化浏览器 UAT、写后回执/刷新、14 日 telemetry、
registry restore、rollback 或 owner/reviewer 双签；AUD-01、EVID-01 和 TUI M5 gate 继续阻断。

部署后已提交并验证 Web→TUI deployment preflight attestation
`docs/deployment/web-to-tui-deployment-preflight-20260816004134.json`（SHA-256
`a8bd41a0372bf587239fafc33c4c2e478c6a94a02cce4be8cb3cfa98ed7dd3b`），并由观察启动器写入
候选窗口 `2026-08-15..2026-08-29`。该动作仅记录观察起点；新候选尚无角色化 UAT、写后
receipt/refresh、生产 telemetry、rollback、registry restore 或 owner/reviewer 双签，机器
cutover gate 仍返回 `DENY`。

## 2026-08-16 当前候选只读运行复核

未重新部署文档提交；针对仍在观察窗口内的 `e167ab2fc748e4c93d2622f93fa8cc75442b2bb6` /
`20260816004134` 候选执行部署后只读验证。结构化摘要见
[`vps-runtime-verification-2026-08-16.json`](vps-runtime-verification-2026-08-16.json)。

复核结果：Caddy domain `demo.agomtrade.pro` 与 TLS 有效，HTTPS health HTTP 200；web、
Celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub 均运行且 web healthy；Django check 0
issues（1 silenced），migration/canonical schema 无缺失，TUI registry published/matched；
`pyqlib=0.9.7`、错误 `qlib` distribution absent，Celery ping 为 `1 node online`。

这次复核是只读的，没有重建镜像、切换 release、写数据库或执行登录/写操作。它补强当前候选
的运行身份与启动证据，但不证明角色化浏览器 UAT、写后 receipt/refresh、immutable authority
lifecycle、durable publisher、14 日 telemetry、registry restore、rollback 或 owner/reviewer
双签；AUD-01、EVID-01 与 TUI M5 的 production gate 继续保持 fail-closed。

同一复核周期又以 `scripts/backup-vps-postgres.ps1 -DownloadLatest` 重新下载并验证了该候选的
PostgreSQL custom-format 归档：远端 `pg_restore --list` 通过，完整下载 `140318641` bytes，
本地 SHA-256 与远端记录一致（`4760a38fdfc7ef8570323cfb5dde92ab01eb933cd60d4f6dd08700fc34772752`）。
这只证明备份下载/校验子步骤，不解除 DATA-01 的 restore/rebuild、维护态 rollback、RTO/RPO 或
reconciliation 门禁。

## 2026-08-16 13:35 当前候选部署与观测

本次按用户要求先发布最终已推送代码，再进入只读观测。`dev/next-development@b051c369e97732ea10f7293d923aa8882a3a691c`
使用标准 `git-clone`、`-Upgrade`、code-only 模式发布，保留 PostgreSQL/Redis 数据卷并启用 Celery。

| 项目 | 证据 |
|---|---|
| release tag | `20260816131435` |
| release dir | `/opt/agomtradepro/releases/source-20260816131435` |
| source commit | `b051c369e97732ea10f7293d923aa8882a3a691c` |
| image | `agomtradepro-web:20260816131435` |
| image ID | `sha256:e65b8ef05fb3cdd3417830dbe7c233fedbab4e7254f45440cc8cd23159cb00cb` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260816131435.json` |
| mode | `ACTION=upgrade`、code-only、数据卷保留、Celery enabled |
| migration/schema | `No migrations to apply`；canonical schema `{"missing_migrations": [], "missing_tables": [], "ok": true}` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；TLS valid；`/api/health/` 与 `/api/ready/` HTTP `200` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime observation | health SHA `00ba29755f44ba617967d1f6665543870d80432d61daf5db45f58b53556d9eb0`；ready SHA `f7534f8dd768c453aca2bfb28a5ab804809c0cbcc1e77ae7aff1d5ab0831ca20` |
| backup | `/opt/agomtradepro/backups/database/postgres-20260816-072224.dump`；本次创建，未执行 restore drill |

`/api/ready/` 继续报告 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale`；这些数据新鲜度观察项没有被部署成功掩盖。本次仅做启动、
健康、版本、迁移、TUI registry、Qlib、Celery 与 HTTPS 只读复核，没有登录或业务写入。角色化
浏览器 UAT、写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、
owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate 继续 fail-closed。

该候选的 candidate binding 为 `web-to-tui-candidate-binding.v1`：matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph SHA
`c45ab376e2297ab235ed08621663bfe721b6a5c254fcc2097b7a2201deae0e98`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest SHA
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。

## 2026-08-16 00:46 当前候选部署与观测

本次按用户要求先发布已验证代码，再进入只读观测。`dev/next-development@516f4e228699231831222613ffe56b9f6b5f0713`
使用标准 `git-clone`、`-Upgrade`、code-only 模式发布，保留 PostgreSQL/Redis 数据卷并启用 Celery。

| 项目 | 证据 |
|---|---|
| release tag | `20260816082603` |
| release dir | `/opt/agomtradepro/releases/source-20260816082603` |
| source commit | `516f4e228699231831222613ffe56b9f6b5f0713` |
| image | `agomtradepro-web:20260816082603` |
| image ID | `sha256:6bb3bec1d83b165c902654d031d636fc60374567aa4afec2cc927dd055832d8a` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260816082603.json` |
| mode | `ACTION=upgrade`、code-only、数据卷保留、Celery enabled |
| migration/schema | `account.0035`–`account.0054` applied；`verify_canonical_schema`=`{"missing_migrations": [], "missing_tables": [], "ok": true}` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；`/api/health/` 与 `/api/ready/` HTTP `200` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime observation | health SHA `c528a9827687047b8c99e903db7f383ae0985d4dfa99019f0f3de6e6beb1cf47`；ready SHA `6ce355d88dc8d794c877cc2ae905413f2a59cfd6479f28ea9b0f722ce0d3a75f` |

`/api/ready/` 仍原样报告 Alpha/Qlib provider degraded、workspace recommendation stale、Alpha rank
source stale 与 market thermometer partial-stale warnings；这些是数据新鲜度观察项，不被部署成功掩盖。
本次仅做启动/健康/版本/迁移/运行时只读复核，没有登录、角色化浏览器 UAT 或业务写入。角色化
UAT、写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、
owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate 继续 fail-closed。
candidate binding 仍为 `web-to-tui-candidate-binding.v1`：matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph SHA
`fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+a2553996be22`、manifest SHA
`a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854`。

## 2026-08-16 15:34 当前候选部署与观测

本次部署包含 TUI release identity、reviewed metadata artifacts 与 AUD-01 durable-publisher contract guard，再进入只读观测。`dev/next-development@e29e15b09b47e07d9724b9cbc750ae2882310693`
使用标准 `git-clone`、`-Upgrade`、code-only 模式发布，保留 PostgreSQL/Redis 数据卷并启用 Celery。

| 项目 | 证据 |
|---|---|
| release tag | `20260816151607` |
| release dir | `/opt/agomtradepro/releases/source-20260816151607` |
| source commit | `e29e15b09b47e07d9724b9cbc750ae2882310693` |
| image | `agomtradepro-web:20260816151607` |
| image ID | `sha256:7663b1a13f0f6ca61b36cc3f8a673b25b08480b6a0c8c5d62c9eed840a7e40ae` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260816151607.json` |
| mode | `ACTION=upgrade`、code-only、数据卷保留、Celery enabled |
| migration/schema | `No migrations to apply`；canonical schema `{"missing_migrations": [], "missing_tables": [], "ok": true}` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；TLS valid；`/api/health/` 与 `/api/ready/` HTTP `200` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime observation | health SHA `e09691a05aefead4e9d1b0e17c00e3340ebfe8e8ec32caff35ebd0f4d6e4ba06`；ready SHA `91df358a1f19328ab1087a433941076469454a6270887c6339502a03283e5afc` |
| backup | `/opt/agomtradepro/backups/database/postgres-20260816-092304.dump`；本次创建，未执行 restore drill |

`/api/ready/` 继续报告 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale`；这些数据新鲜度观察项没有被部署成功掩盖。本次仅做启动、
健康、版本、迁移、TUI registry、Qlib、Celery 与 HTTPS 只读复核，没有登录或业务写入。角色化
浏览器 UAT、写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、
owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate 继续 fail-closed。

该候选的 candidate binding 为 `web-to-tui-candidate-binding.v1`：matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph SHA
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest SHA
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。

部署完成后，`scripts/start_web_to_tui_observation.py --write --replace` 读取已提交的
`docs/deployment/web-to-tui-deployment-preflight-20260816151607.json` 并启动新候选窗口；
attestation SHA-256 将在该文件提交后生成，
窗口为 `2026-08-16..2026-08-30`。该动作只重置候选绑定和未验证区块，机器 readiness 仍为
`DENY`（UAT `0/108`、telemetry `0/101`、rollback/backup/审批缺失）；没有执行登录、业务写入
或角色化浏览器 UAT。

## 2026-08-16 01:09 当前候选部署与观测

最终代码候选 `dev/next-development@6c4086231a19005c750c856e78613b766bfd3609` 使用标准
`git-clone`、`-Upgrade`、code-only 模式发布，保留 PostgreSQL/Redis 数据卷并启用 Celery。

| 项目 | 证据 |
|---|---|
| release tag | `20260816085250` |
| release dir | `/opt/agomtradepro/releases/source-20260816085250` |
| source commit | `6c4086231a19005c750c856e78613b766bfd3609` |
| image | `agomtradepro-web:20260816085250` |
| image ID | `sha256:1d84d3db8d991eee385e4bfcf9160d0271cc8262924555c23346ade28a091c89` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260816085250.json` |
| mode | `ACTION=upgrade`、code-only、数据卷保留、Celery enabled |
| migration/schema | `account.0035`–`account.0054` applied；`verify_canonical_schema`=`{"missing_migrations": [], "missing_tables": [], "ok": true}` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；`/api/health/` 与 `/api/ready/` HTTP `200` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime observation | health SHA `ea5df20cfd0517f50a2b282f35a41a6fd96490a22667012694c3b5d91b42ff4d`；ready SHA `fc610dccc2634c0b493f034f8f1ba7b4fb527466269dcc4ade5ee4b0cbb70de0` |

`/api/ready/` 仍原样报告 Alpha/Qlib provider degraded、workspace recommendation stale、Alpha rank
source stale 与 market thermometer partial-stale warnings；这些是数据新鲜度观察项，不被部署成功掩盖。
本次仅做启动/健康/版本/迁移/运行时只读复核，没有登录、角色化浏览器 UAT 或业务写入。角色化
UAT、写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、
owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate 继续 fail-closed。
candidate binding 仍为 `web-to-tui-candidate-binding.v1`：matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph SHA
`fc4c19fbb0fc90e931a16223fffd9a4bd782e380afb86893a499874e6b644c84`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+a2553996be22`、manifest SHA
`a3c59ed3453610fc708355bbf7d290eb92e23f699333cf36cbdf19a6769ec854`。
