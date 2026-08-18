# VPS 候选部署证据（2026-08-15）

## 结论

`dev/next-development` 的提交 `96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952` 已在 `demo.agomtrade.pro` 完成一次带 provenance 校验的后续候选部署。该 release 包含 TUI AI provider failure guidance 修复；当前服务正常运行，M5 观察窗口从本次独立核验时间重新计算。本证据不解除角色化浏览器 UAT、写后回执、14 日观察、恢复演练或数据覆盖门禁。

## 2026-08-18 21:07 当前 TAR-01 boundary guard 候选部署与短窗口只读观测

提交 `dev/next-development@d238091d9e7e3aa1324baf92199100e800122ed7` 使用标准
`git-clone`、`-Upgrade`、code-only 模式发布为 release `20260818210752`；保留
PostgreSQL/Redis 数据卷并启用 Celery。该候选包含 TAR-01 queued API composition boundary
纯合同，仍不启用 queued intake/worker，也没有改变生产 authority 或业务写入门禁。

| 项目 | 证据 |
|---|---|
| release/source | `20260818210752` / `d238091d9e7e3aa1324baf92199100e800122ed7` |
| image | `sha256:3dd6401b8e8b757087e3d99e1e91dc1ebf539f33bc5148fd7198925717e5cdc3` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260818210752.json`（本地忽略产物） |
| mode/volumes | `ACTION=upgrade`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema/checks | `No migrations to apply`；missing migrations/tables 为空；Django check、TUI registry、Qlib、Celery、容器与 TUI JS 预检通过；TUI registry source hash 与 active hash 匹配 |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL custom-format backup 已生成：`/opt/agomtradepro/backups/database/postgres-20260818-151515.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |
| HTTPS observation | `https://demo.agomtrade.pro/api/health/` 连续 8 次 HTTP `200`；短窗口延迟约 `1.17–2.08s` |

这只是不可变候选的短窗口只读运行证据，不是角色化浏览器 UAT 或生产写入证明。没有执行登录、
角色化权限走查、业务写入、写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、
rollback 双签、owner/reviewer 双签或 AUD-01/EVID-01 durable authority/publisher 验证；TAR-01
仍 active，TAR-02 继续等待，相关 gate 保持 fail-closed。

## 2026-08-18 20:14 当前 TAR-01 候选部署与短窗口只读观测

提交 `dev/next-development@6e217afdd7599086f25f7100a92ae34324e5df73` 使用标准
`git-clone`、`-Upgrade`、code-only 模式发布为 release `20260818201455`；保留
PostgreSQL/Redis 数据卷并启用 Celery。该部署承载 TAR-01 runtime configuration freeze，
不启用 queued intake/worker，也没有改变任何生产 authority 或业务写入门禁。

| 项目 | 证据 |
|---|---|
| release/source | `20260818201455` / `6e217afdd7599086f25f7100a92ae34324e5df73` |
| image | `sha256:667b500fdcb4024eb5c63c9e9a6af119d2b4012532683a8f8f861654126df6f1` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260818201455.json`（本地忽略产物） |
| mode/volumes | `ACTION=upgrade`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema/checks | `No migrations to apply`；missing migrations/tables 为空；Django check、TUI registry、Qlib、Celery 与容器预检通过 |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL custom-format backup 已生成：`/opt/agomtradepro/backups/database/postgres-20260818-142546.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |
| HTTPS observation | `https://demo.agomtrade.pro/api/health/` 连续 8 次 HTTP `200`；短窗口延迟约 `1.10–1.86s` |

这只是不可变候选的短窗口只读运行证据，不是角色化浏览器 UAT 或生产写入证明。没有执行登录、
角色化权限走查、业务写入、写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、
rollback 双签、owner/reviewer 双签或 AUD-01/EVID-01 durable authority/publisher 验证；TAR-01
仍 active，TAR-02 继续等待，相关 gate 保持 fail-closed。

## 2026-08-18 13:25 当前 TAR-01 候选部署与恢复后只读观测

提交 `dev/next-development@1b80034dc8cde602274e88265169b826c7962271` 已使用标准
`git-clone`、`-Upgrade`、code-only 模式构建；PostgreSQL/Redis 数据卷保留，Celery 启用。
远端构建预检、迁移、Django check、Data Center catalog、TUI publish/check 与部署前备份均执行。
首轮 verifier 因 web 重启窗口把迁移/schema/TUI/Qlib 等检查判为失败，自动回滚尝试又在
180 秒内超时；随后确认旧 release 健康，再把已生成且 provenance 完整的新 release 手动切回
`current`，以同一 compose 和保留数据卷重建服务。本节把 verifier 失败与人工恢复都如实记录，
不把它写成标准部署 verifier 全绿。

| 项目 | 证据 |
|---|---|
| release tag | `20260818130903` |
| release dir/current | `/opt/agomtradepro/releases/source-20260818130903`（最终只读观测时 `current` 指向该目录） |
| source commit | `1b80034dc8cde602274e88265169b826c7962271` |
| image | `agomtradepro-web:20260818130903` |
| image ID | `sha256:90294d9b85fdf237fc84dbe1b0f46eea651a1bc80ba9b92a0e4afc61bcb6e803` |
| deployment report/manifest | `dist/remote-build-reports/remote-build-report-20260818130903.json`；远端 `.agom-release-manifest.json` `0444`、OCI revision 与 source 完全一致 |
| migration/schema/preflight | `No migrations to apply`；`missing_migrations=[]`、`missing_tables=[]`、`ok=true`；Django system check 无新增问题；catalog sync 与 TUI publish/check 均成功 |
| HTTPS/health | 手动切换后稳定观测 `https://demo.agomtrade.pro/api/health/` 与 `/api/ready/` 均 HTTP 200（2026-08-18 13:25 左右） |
| containers | web `healthy`、`restarts=0`；Caddy、Celery worker/beat、PostgreSQL、Redis、RSSHub、runtime namespace 均 running/healthy |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL 备份已生成：`/opt/agomtradepro/backups/database/postgres-20260818-070934.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |

本次纯契约代码没有接入新 Web/TUI queued intake，也没有登录、角色化浏览器 UAT、业务写入、写后
receipt/refresh、authority 回填或生产 publisher。`/api/ready/` 的 freshness warnings 仍需按原样
处理；M5 的角色化写回执、14 日 telemetry、registry backup/restore、rollback 双签以及
AUD-01/EVID-01 authority/publisher 继续 fail-closed。旧 release
`20260818115436` 仍保留，可作为回滚目标；本节的手动切换不是生产 rollback drill 证据。

## 2026-08-17 00:34 当前候选部署与只读观测

候选 `dev/next-development@3ceafaf193e87626be7458531c66e96b11f7df84` 已使用标准
`git-clone`、`-Upgrade`、code-only 模式发布到 `demo.agomtrade.pro`；PostgreSQL/Redis
数据卷保留，Celery 启用。本节记录部署脚本返回的可复核身份与只读检查，不把健康检查
或 CI 通过误写成生产授权、角色化 UAT 或数据恢复演练。

| 项目 | 证据 |
|---|---|
| release tag | `20260817002134` |
| release dir | `/opt/agomtradepro/releases/source-20260817002134` |
| source commit | `3ceafaf193e87626be7458531c66e96b11f7df84` |
| image | `agomtradepro-web:20260817002134` |
| image ID | `sha256:2669efe86996c2e2ca54937fd7abc3064f9b97f6823bbfff40dd12c5891676db` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260817002134.json`（本地忽略产物） |
| migration/schema | `No migrations to apply`；canonical schema `{"missing_migrations": [], "missing_tables": [], "ok": true}` |
| HTTPS/health | `demo.agomtrade.pro` Caddy/TLS 校验通过；`/api/health/` HTTP 200，响应 `{"status":"ok"}` |
| containers | web healthy；Celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub、runtime namespace running |
| Django/Celery | deploy check 无新增问题；Celery ping `1 node online`；worker/beat running |
| TUI registry | publish/check 通过；registry `25`、backend `20260816151607`、active source hash 与 expected 一致 |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL/Redis backup hook 成功；本次未执行 restore/rebuild、RTO/RPO 或 rollback drill |

部署日志还记录迁移、catalog 同步、静态文件、AI capability catalog 与冷启动 dry-run 均完成；
没有执行登录、角色化浏览器 UAT、业务写入或 authority 回填。`/api/ready/` 的 Alpha/Qlib
与 workspace freshness warnings 仍按原样保留，AUD-01/EVID-01 durable publisher/authority、
M5 角色化写回执、14 日 telemetry、registry backup/restore、rollback 与 owner/reviewer 双签
继续 fail-closed。

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

## 2026-08-18 当前候选部署与恢复观测

提交 `dev/next-development@84293272218725c286aed29db68bd3dae9cb4b16` 以
`git-clone`、`-Upgrade`、code-only 模式重新部署到 VPS，保留 PostgreSQL/Redis 数据卷并启用
Celery 与 RSSHub。首轮 release `20260818112302` 的部署后验证未通过，自动回滚在远程命令超时；
未删除数据卷。随后确认旧 release 已恢复但 web/Caddy/Celery 处于回滚中间态，使用同一 compose
配置重建服务并验证健康后再次部署为 `20260818115436`。本节只把第二次候选的稳定观测作为当前
运行证据，首轮失败不会被计入成功门禁。

| 项目 | 证据 |
|---|---|
| release tag | `20260818115436` |
| release dir | `/opt/agomtradepro/releases/source-20260818115436` |
| source commit | `84293272218725c286aed29db68bd3dae9cb4b16` |
| image | `agomtradepro-web:20260818115436` |
| image ID | `sha256:5ddac69a78c7242f0c0bac4ce1a8cc2c7f9c638d7f5088cec139d28648227540` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260818115436.json` |
| migration/schema | `No migrations to apply`；`missing_migrations=[]`、`missing_tables=[]`、`ok=true`；Django check 无 issues |
| TUI registry | publish `noop=true`；active source hash 与 expected hash 匹配；backend version 保持 reviewed release `20260818083157` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；TLS 有效；外部 `/api/health/` 和 `/api/ready/` 均 HTTP `200` |
| containers | 最终重建后 web `healthy`、`restarts=0`；Caddy、Celery worker/beat、PostgreSQL、Redis、RSSHub、runtime namespace 均运行 |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL 备份成功，manifest `2026-08-18 05:55:10`；数据卷未清理 |
| observation | 最终重建后连续约 2 分钟 Docker health `healthy/restarts=0`，外部 HTTPS health/ready 仍 200；未执行登录或业务写入 |

部署验证器曾在首轮/切换中报告 migration/schema/TUI/Qlib/resources/healthcheck 失败，原因是共享
PID namespace 下临时 compose 操作触发 Daphne 退出并导致自动回滚超时；镜像本身启动日志无
traceback，隔离启动可返回 health 200。最终候选是在所有一次性检查结束后最后重建 web，随后仅用
外部 HTTPS 与 Docker 状态观测，故本节不把那次验证器失败改写为“全项通过”。

`/api/ready/` 的数据 freshness/degraded warning 原样保留；本次没有角色化浏览器 UAT、登录、
业务写入、写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill
或 owner/reviewer 双签。M5、AUD-01、EVID-01、DATA-01 等生产门禁继续 fail-closed。

## 2026-08-18 10:20 当前候选部署与观测

CI 全部通过的 `dev/next-development@bc91641f737fb34b12afb28b93a6a19a1f934c29` 使用标准
`git-clone`、`-Upgrade`、code-only 模式发布为 release `20260818102057`；PostgreSQL/Redis
数据卷保留，Celery worker/beat 启用，部署前 PostgreSQL/Redis/metadata 备份成功。

| 项目 | 证据 |
|---|---|
| release tag | `20260818102057` |
| release dir | `/opt/agomtradepro/releases/source-20260818102057` |
| source commit | `bc91641f737fb34b12afb28b93a6a19a1f934c29` |
| image | `agomtradepro-web:20260818102057` |
| image ID | `sha256:96b3dac7efc8d378573f1e52eeec3eda13880824f5271e825ca6d70945546ce8` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260818102057.json` |
| migration/schema | `No migrations to apply`；canonical schema `missing_migrations=[]`、`missing_tables=[]`、`ok=true` |
| HTTPS | `https://demo.agomtrade.pro/api/health/` 与 `/api/ready/` HTTP `200`；Caddy/TLS 证书校验通过，HTTP 入口 `308` 重定向 HTTPS |
| health/readiness | health `{"status":"ok"}`；readiness database/redis/celery/critical_data/decision_data 均 `ok`，Celery `1` worker；quotes age 约 `21` 分钟且 `fresh` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub、runtime namespace running |
| TUI runtime | publish `noop=true`，active registry hash 与 expected hash 匹配；backend version 保持 reviewed release `20260818083157` |
| unauthenticated boundary | API root HTTP `200`；未认证 `GET /api/tui/` HTTP `403`（不泄露 TUI payload） |

`/api/ready/` 同时暴露了 market thermometer 的 `etf_net_flow` stale/fallback proxy 观察项；该数据新鲜度
告警没有被部署成功掩盖。本次没有登录、角色化浏览器 UAT、业务写入或写后 receipt/refresh。
M5 的角色化 UAT、14 日 telemetry/defect、registry backup/restore、rollback drill、owner/reviewer
双签，以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate 继续 fail-closed。

## 2026-08-17 13:15 当前候选部署与观测

本节只记录仓库侧 runtime manifest 重新生成后的 source-side binding；**未执行新的 VPS
部署、登录、业务写入或角色化浏览器 UAT**。已部署 release `20260816223921` 的 OCI、HTTPS
健康与只读运行证据保持不变，M5-A、AUD-01/EVID-01 继续 fail-closed。

binding version 为 `web-to-tui-candidate-binding.v1`。

| 项目 | 证据 |
|---|---|
| candidate version/commit | `20260816223921` / `443658d33159dd80a35b3001ae2c8505113e3fff` |
| matrix/graph | `bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded` / `42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba` |
| runtime binding | schema `tui-metadata.v3`; runtime `0.2.0`; build `agomtui-runtime-0.2.0+21ef64c7a7e5`; manifest SHA `ade5109f97ee15d78987e1f63fe511f23ad2043f49aa43f1a2051da71687e378` |
| production scope | source-side rebind only; no new VPS deployment or production write evidence |

## 2026-08-16 22:39 当前候选部署与观测

`dev/next-development@443658d33159dd80a35b3001ae2c8505113e3fff` 使用标准
`git-clone`、`-Upgrade`、code-only 模式发布为 `20260816223921`，保留 PostgreSQL/Redis
数据卷并启用 Celery。远端 release dir 为
`/opt/agomtradepro/releases/source-20260816223921`，OCI image ID 为
`sha256:c5930a8eb13a8ff4d09880698ceab2d9ee4758b48e8e8cdf1adbb61607b56f73`；部署报告
`dist/remote-build-reports/remote-build-report-20260816223921.json`，结构化运行摘要为
`docs/deployment/vps-runtime-verification-2026-08-16-2258.json`，deployment preflight 为
`docs/deployment/web-to-tui-deployment-preflight-20260816223921.json`。

| 项目 | 证据 |
|---|---|
| release/source | `20260816223921` / `443658d33159dd80a35b3001ae2c8505113e3fff` |
| mode | `ACTION=upgrade`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema | `No migrations to apply`；canonical schema `missing_migrations=[]`、`missing_tables=[]`、`ok=true` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；TLS valid；`/api/health/` 与 `/api/ready/` HTTP `200` |
| runtime observation | health SHA `cd2a7891e4df7b35f9878d245df36f39c567ef36507d2a58928abe076f06da78`；ready SHA `59c346cf007900a025101deaf1c6a58a64ecb5963081a8352ee092c00e409b41` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub、runtime namespace running；Celery ping `1 node online` |
| TUI metadata | registry published/matched；registry id `25`；backend version `20260816151607` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | `/opt/agomtradepro/backups/database/postgres-20260816-164649.dump`；成功 pre-deploy hook 创建；未执行 restore/rebuild |
| authority inventory | `evid-01-authority-inventory-2026-08-16-2258.json`；0050–0053 已应用，12 个 authority/evidence 表均为 `0` 行，`blocked_zero_seed_authority` |

`/api/ready/` 仍报告 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale` 与 `market_thermometer_partial_stale`；这些数据新鲜度
观察项没有被部署成功掩盖。本次仅做启动、健康、版本、迁移、TUI registry、Qlib、Celery、
authority row-count 与 HTTPS 只读复核，没有登录或业务写入。角色化浏览器 UAT、写后
receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、owner/reviewer
双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate 继续 fail-closed。

该候选完整 binding 为 `web-to-tui-candidate-binding.v1`：candidate version
`20260816223921`、candidate commit `443658d33159dd80a35b3001ae2c8505113e3fff`、matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph SHA
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest SHA
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。观察窗口需随该候选
重新绑定为 `2026-08-16..2026-08-30`，不跨候选继承 UAT 或 telemetry。

## 2026-08-16 18:11 当前候选部署与观测

`dev/next-development@5a13125bb84eb1b20e623d7c1388a0d7632294cb` 已以标准 `-Upgrade`、
code-only、保留数据卷并启用 Celery 发布为 release `20260816181141`。

| 项目 | 证据 |
|---|---|
| release tag | `20260816181141` |
| release dir | `/opt/agomtradepro/releases/source-20260816181141` |
| source commit | `5a13125bb84eb1b20e623d7c1388a0d7632294cb` |
| image ID | `sha256:1add6e57714a6ee41e3a3153a46e0c6e578f29a8374ea18e91cb53b65a7e2632` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260816181141.json` |
| migration/schema | `No migrations to apply`；canonical schema missing lists empty；Django check 无问题（1 silenced） |
| HTTPS | `demo.agomtrade.pro` Caddy/TLS；`/api/health/` 与 `/api/ready/` HTTP `200` |
| containers | web healthy；Celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime observation | health SHA `bacab80cf37e6f8c94189606184a9d3a040ec8e56cf820b1e768cda207522fb3`；ready SHA `a3afe4e633840aadb84d0c730004c9f40ba114531ef8fc4d130db306ae1e5ed4` |
| backup hook | `/opt/agomtradepro/backups/database/postgres-20260816-121912.dump`；本次未取得尺寸/SHA，不扩大证据范围 |

结构化 preflight 为 `docs/deployment/web-to-tui-deployment-preflight-20260816181141.json`，SHA
`b449240339413578c0aaea9d2868f4f826e4454d51c9d5dcb607a87aefd343a2`；运行摘要为
`docs/deployment/vps-runtime-verification-2026-08-16-1811.json`。候选完整 binding 为：version
`web-to-tui-candidate-binding.v1`、candidate version `20260816181141`、candidate commit
`5a13125bb84eb1b20e623d7c1388a0d7632294cb`、matrix `bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、
graph `42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。

`/api/ready/` 仍报告 Alpha/Qlib、workspace recommendation、Alpha rank source 与 market
thermometer freshness warnings。本次仅完成代码部署和只读运行复核，没有登录、角色化浏览器
UAT 或业务写入；写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、
rollback、owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关
门禁继续 fail-closed。

## 2026-08-16 16:24 当前候选部署与观测

本次部署继续采用标准 `git-clone`、`-Upgrade`、code-only 模式，保留
PostgreSQL/Redis 数据卷并启用 Celery。候选身份已绑定到
`dev/next-development@07d5d1d338c70ebc1d347663b48b09b38335fce5` / release `20260816160127`。

| 项目 | 证据 |
|---|---|
| release tag | `20260816160127` |
| release dir | `/opt/agomtradepro/releases/source-20260816160127` |
| source commit | `07d5d1d338c70ebc1d347663b48b09b38335fce5` |
| image | `agomtradepro-web:20260816160127` |
| image ID | `sha256:57fbe5504cbec2a2c9c072b3434460aceae5a9b74cd0fc83f5d7be6dba7dab56` |
| preflight | `docs/deployment/web-to-tui-deployment-preflight-20260816160127.json`；SHA `8cd0c8c659fc5a85db782f74180458dd848de7532b6b85dd379a959ebec1d691` |
| migration/schema | `migrate --check` clean；canonical schema `{"missing_migrations": [], "missing_tables": [], "ok": true}` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；`/api/health/` 与 `/api/ready/` HTTP `200` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime observation | health SHA `513084211e3334448dbfcae2f0af9b1d14b406c51e0eb6e8d539b26e34bae00f`；ready SHA `5177675f73c49b6ce76e223d4c0764d0424e0cbf586852c93c1c4eb66398731a` |
| backup | `/opt/agomtradepro/backups/database/postgres-20260816-100924.dump`；size `140804438`；SHA256 `06e52b33c637c17cae4c9f0223246e0e09af84254717196d904f67044e7b2cba`；`pg_restore --list` `7167` entries |

结构化只读摘要见 `docs/deployment/vps-runtime-verification-2026-08-16-1624.json`。
`/api/ready/` 仍报告 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale` 与 `market_thermometer_partial_stale`；这些 freshness
warnings 没有被部署成功掩盖。本次没有登录、角色化浏览器 UAT 或业务写入；写后
receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、
owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate
继续 fail-closed。PostgreSQL archive 只完成 SHA 与 `pg_restore --list` 检查，没有 restore/rebuild、
RTO/RPO 或 rollback drill。

该候选的 candidate binding 为 `web-to-tui-candidate-binding.v1`：matrix SHA
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、published graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest SHA
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。观察窗口为
`2026-08-16..2026-08-30`，不跨候选继承 UAT、telemetry 或 cleanup 证据。

## 2026-08-16 17:21 当前候选部署与观测

当前 `dev/next-development@fc145423c4de04cae20c3a6a2e94780505aa5938` 已使用标准
`git-clone`、`-Upgrade`、code-only 模式发布为 release `20260816170851`，保留
PostgreSQL/Redis 数据卷并启用 Celery。首次部署尝试在远端预部署备份钩子阶段返回
`Exit=-1` 且无 stderr，未切换运行容器；随后独立下载并校验远端最新 custom-format
备份，再以该恢复点重试并显式跳过重复钩子，部署成功。

| 项目 | 证据 |
|---|---|
| release tag | `20260816170851` |
| release dir | `/opt/agomtradepro/releases/source-20260816170851` |
| source commit | `fc145423c4de04cae20c3a6a2e94780505aa5938` |
| image | `agomtradepro-web:20260816170851` |
| image ID | `sha256:04d08b5d3e1b1032abfbbefbeb4d9df0f4a6f8c33c706981056c1f36031112eb` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260816170851.json` |
| mode | `ACTION=upgrade`、code-only、数据卷保留、Celery enabled；重复预备份钩子跳过，原因已记录在结构化摘要 |
| migration/schema | `No migrations to apply`；canonical schema `missing_migrations=[]`、`missing_tables=[]` |
| HTTPS | `demo.agomtrade.pro` Caddy domain；TLS valid；`/api/health/` 与 `/api/ready/` HTTP `200` |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime observation | health SHA `374ce1945abfd549b08ce103c5155004f5f83317b08a4e9b5ac16e7ed3b6a469`；ready SHA `7874fdb8c615d532d0da953a4d2f7df0d3d6511e0d3d8c6fb717706bda2f7007` |
| backup | `/opt/agomtradepro/backups/database/postgres-20260816-110120.dump`；`140820006` bytes；SHA256 `43f7b2fb8d0d565831021a1cd0a8fb7adda2809954c3df343597c8f884452565`；`pg_restore --list` `7167` entries |

结构化只读摘要见 `docs/deployment/vps-runtime-verification-2026-08-16-1721.json`。
`/api/ready/` 仍报告 `alpha_qlib_provider_degraded`、`workspace_recommendations_stale`、
`workspace_alpha_rank_source_stale` 与 `market_thermometer_partial_stale`；这些 freshness
warnings 没有被部署成功掩盖。本次没有登录、角色化浏览器 UAT 或业务写入；写后
receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、
owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate
继续 fail-closed。PostgreSQL archive 仅完成下载、SHA 与 `pg_restore --list` 检查，没有
restore/rebuild、RTO/RPO 或 rollback drill。
该候选完整 binding 为：version `web-to-tui-candidate-binding.v1`、candidate version
`20260816170851`、candidate commit `fc145423c4de04cae20c3a6a2e94780505aa5938`、matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`、graph
`42a20ddb5bca62cbdb6a9ff1eda2ced91515354662e406428a2a6c40840390ba`、schema `tui-metadata.v3`、
runtime `0.2.0`、build `agomtui-runtime-0.2.0+8e5b1ff43be5`、manifest
`98494ca640c4f4dfb6f1e8b08778d669228d4dc1a85947b582a33e1c8036ee6c`。

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
