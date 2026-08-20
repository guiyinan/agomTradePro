# VPS 候选部署证据（2026-08-15）

## 结论

`dev/next-development` 的提交 `96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952` 已在 `demo.agomtrade.pro` 完成一次带 provenance 校验的后续候选部署。该 release 包含 TUI AI provider failure guidance 修复；当前服务正常运行，M5 观察窗口从本次独立核验时间重新计算。本证据不解除角色化浏览器 UAT、写后回执、14 日观察、恢复演练或数据覆盖门禁。

## 2026-08-19 04:46 TAR-01 baseline identity guard 候选部署与只读观测

提交 `dev/next-development@a837c728012197c4ce27a31a883048b3233f7460` 使用标准
`git-clone`、`-Upgrade`、code-only 模式发布为 release `20260819044629`；保留
PostgreSQL/Redis 数据卷并启用 Celery。该候选只加强 dormant TAR-01 baseline 证据合同：
1/5/10/20 样本必须绑定同一 commit/release、OCI revision、runtime manifest digest 与
test-matrix digest；没有启用 queued intake、Worker、容量或业务写入口。

| 项目 | 证据 |
|---|---|
| release/source | `20260819044629` / `a837c728012197c4ce27a31a883048b3233f7460` |
| image | `agomtradepro-web:20260819044629` / `sha256:d4374a18d3a9be797b9c588531fdf85de16c8fa81a2492490ce1158fa449d1e1` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819044629.json` |
| mode/volumes | `ACTION=upgrade`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema/checks | `No migrations to apply`；canonical schema `missing_migrations=[]`、`missing_tables=[]`、`ok=true`；Django check 无新增问题 |
| TUI runtime | registry `id=28`、publish 为 `noop`；active/backend version `20260819000530`、source hash `cf064268fa7ee2263bcb2355d12bdd98bedd83076288272a6997ff5af7cacf8c` 匹配；本次未改 published graph |
| HTTPS/health | `demo.agomtrade.pro` Caddy domain、TLS valid；随后 8 次 `https://demo.agomtrade.pro/api/health/` 均 `200`（21:02:46–21:03:08 UTC，约 `1.08–2.25s`） |
| containers | web healthy；Caddy、PostgreSQL、Redis、RSSHub、Celery worker/beat、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL custom-format backup：`/opt/agomtradepro/backups/database/postgres-20260818-225303.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |

本节是当前候选的 release/source/image、迁移、健康与短窗口只读证据，不是 TAR-01 真实
1/5/10/20 容量、SLO、chaos、队列/Worker、角色化 UAT、业务写后 receipt/refresh、14 日
telemetry、restore/rollback、owner/reviewer 双签或 AUD-01/EVID-01 authority/publisher 证明；
相关生产门禁继续 fail-closed。

## 2026-08-19 03:41 当前 DATA-01 口径 fail-closed 候选部署与只读观测

提交 `dev/next-development@4040d98916dc2527ba5d60ce8b4433c0bdad10f3` 使用标准
`git-clone`、`fresh`、code-only 模式发布为 release `20260819034120`；保留
PostgreSQL/Redis 数据卷并启用 Celery。该 release 包含最终的 A 股涨跌停“不含 ST”
口径：Tushare/AKShare 对名称缺失、`NaN` 或含 `ST` 的行均 fail closed；同时保留
Data Center/Pulse 元数据与 0072/0007 回滚迁移。未改变 TUI published graph、角色授权
或业务写入门禁。

| 项目 | 证据 |
|---|---|
| release/source | `20260819034120` / `4040d98916dc2527ba5d60ce8b4433c0bdad10f3` |
| image | `agomtradepro-web:20260819034120` / `sha256:99a8bc5ddab1197c8d25db834ce5f470d47b1859bb06d61a17dd7f83035b2d05` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819034120.json` |
| mode/volumes | `ACTION=fresh`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema/checks | `No migrations to apply`（0072/0007 已在上一候选应用）；canonical schema `missing_migrations=[]`、`missing_tables=[]`、`ok=true`；Django check 无新增问题 |
| TUI runtime | registry `id=28`、publish 为 `noop`；active/backend version `20260819000530`、source hash `cf064268fa7ee2263bcb2355d12bdd98bedd83076288272a6997ff5af7cacf8c` 匹配；本次未改 published graph |
| HTTPS/health | `demo.agomtrade.pro` Caddy domain、TLS valid；部署 verifier HTTP `200`；随后 8 次 `https://demo.agomtrade.pro/api/health/` 均 `200`（19:57:17–19:57:39 UTC，约 `1.09–1.82s`） |
| containers | web healthy；Caddy、PostgreSQL、Redis、RSSHub、Celery worker/beat、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL custom-format backup：`/opt/agomtradepro/backups/database/postgres-20260818-214815.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |

本节是当前 release 的部署、版本、健康与数据口径只读证据，不是角色化浏览器 UAT、生产业务写入或写后 receipt/refresh 证明。没有执行登录、角色化权限走查、业务写入、14 日 telemetry/defect、registry backup/restore、rollback 双签、owner/reviewer 双签或 AUD-01/EVID-01 durable authority/publisher 验证；相关 gate 继续 fail-closed。

## 2026-08-19 02:43 当前 DATA-01 口径修复候选部署与只读观测

提交 `dev/next-development@09e8e5ed11fd56c39b1090f28159a59d1ad4c6a4` 使用标准
`git-clone`、`fresh`、code-only 模式发布为 release `20260819024316`；保留
PostgreSQL/Redis 数据卷并启用 Celery。该 release 将 A 股涨跌停指标的“不含 ST”口径
同时落到 Data Center、Pulse、Tushare/AKShare provider 与可回滚迁移；未改变 TUI
published graph、角色授权或业务写入门禁。

| 项目 | 证据 |
|---|---|
| release/source | `20260819024316` / `09e8e5ed11fd56c39b1090f28159a59d1ad4c6a4` |
| image | `agomtradepro-web:20260819024316` / `sha256:38f3b7156d3fde8f2c8579578939189206bc9b34452eeb4593dc1089728bf219` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819024316.json` |
| mode/volumes | `ACTION=fresh`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema/checks | `data_center.0072_note_non_st_price_limit_scope` 与 `pulse.0007_note_non_st_price_limit_scope` 均应用成功；canonical schema `missing_migrations=[]`、`missing_tables=[]`、`ok=true`；Django check 无新增问题 |
| TUI runtime | registry `id=28`、publish 为 `noop`；active/backend version `20260819000530`、source hash `cf064268fa7ee2263bcb2355d12bdd98bedd83076288272a6997ff5af7cacf8c` 匹配；本次未改 published graph |
| HTTPS/health | `demo.agomtrade.pro` Caddy domain、TLS valid；部署 verifier HTTP `200`；随后 8 次 `https://demo.agomtrade.pro/api/health/` 均 `200`（18:00:01–18:00:22 UTC，约 `1.06–2.57s`） |
| containers | web healthy；Caddy、PostgreSQL、Redis、RSSHub、Celery worker/beat、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL custom-format backup：`/opt/agomtradepro/backups/database/postgres-20260818-204950.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |

本节是当前 release 的部署、迁移、版本、健康与 Data Center/Pulse 口径只读证据，不是角色化浏览器 UAT、生产业务写入或写后 receipt/refresh 证明。没有执行登录、角色化权限走查、业务写入、14 日 telemetry/defect、registry backup/restore、rollback 双签、owner/reviewer 双签或 AUD-01/EVID-01 durable authority/publisher 验证；相关 gate 继续 fail-closed。

## 2026-08-19 01:28 当前 TUX-02 dead-patch cleanup 部署与只读观测

提交 `dev/next-development@72061c6857571ab4a3de891d2ae5ad8d5ad19a6c` 使用标准
`git-clone`、`fresh`、code-only 模式发布为 release `20260819012839`；保留
PostgreSQL/Redis 数据卷并启用 Celery。该 release 删除了已被 full-IA canonical runtime
证明无效的 `research.signals` Python screen patch；未改变 M5 candidate binding、角色授权或业务写入。

| 项目 | 证据 |
|---|---|
| release/source | `20260819012839` / `72061c6857571ab4a3de891d2ae5ad8d5ad19a6c` |
| image | `agomtradepro-web:20260819012839` / `sha256:6d3ae5463d93f1788f5271bae75a337b1125d061113bb9986efb5ba514ef2261` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819012839.json` |
| mode/volumes | `ACTION=fresh`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema/checks | `No migrations to apply`；canonical schema `missing_migrations=[]`、`missing_tables=[]`、`ok=true`；Django check 无新增问题；部署前 TUI JS `34 passed` |
| TUI runtime | registry `id=28`、publish 为 `noop`（active/backend version 仍为 `20260819000530`，source hash 匹配）；本次只变更 Python runtime patch，不改 published graph |
| HTTPS/health | `demo.agomtrade.pro` Caddy domain、TLS valid；部署 verifier HTTP `200`；随后连续 8 次 `https://demo.agomtrade.pro/api/health/` 均 `200`（17:45:48–17:46:00 UTC） |
| containers | web healthy；Caddy、PostgreSQL、Redis、RSSHub、Celery worker/beat、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL custom-format backup：`/opt/agomtradepro/backups/database/postgres-20260818-193539.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |

本节是当前 release 的部署、版本、健康与 TUI runtime 只读证据，不是角色化浏览器 UAT、生产业务写入或写后 receipt/refresh 证明。没有执行登录、角色化权限走查、业务写入、14 日 telemetry/defect、registry backup/restore、rollback 双签、owner/reviewer 双签或 AUD-01/EVID-01 durable authority/publisher 验证；相关 gate 继续 fail-closed。

## 2026-08-19 00:22 当前 TUX-02 runtime action-copy 部署与只读观测

提交 `dev/next-development@413c67f3ba2cfd1117356d129961e39958979017` 使用标准
`git-clone`、`fresh`、code-only 模式发布为 release `20260819000530`；保留
PostgreSQL/Redis 数据卷并启用 Celery。该 release 包含 TUX-02 runtime action-copy
边界和对应 manifest 刷新；没有改变角色授权、业务写入或 M5 candidate binding。

| 项目 | 证据 |
|---|---|
| release/source | `20260819000530` / `413c67f3ba2cfd1117356d129961e39958979017` |
| image | `agomtradepro-web:20260819000530` / `sha256:e807ca97a61b9b5455d7ae92de64d24df7a3ed9d940aacd7ce313111c15e6152` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819000530.json` |
| mode/volumes | `ACTION=fresh`、code-only、PostgreSQL/Redis 数据卷保留、Celery enabled |
| migration/schema | `No migrations to apply`；canonical schema `missing_migrations=[]`、`missing_tables=[]`、`ok=true`；Django check 无新增问题 |
| TUI runtime | registry `id=28`、`backend_version=20260819000530`；active/source hash 均为 `cf064268fa7ee2263bcb2355d12bdd98bedd83076288272a6997ff5af7cacf8c`；6 个 action copy replacement 变更已 publish/check 匹配 |
| HTTPS/health | `demo.agomtrade.pro` Caddy domain；TLS valid；`https://demo.agomtrade.pro/api/health/` HTTP `200` |
| containers | web healthy；Caddy、PostgreSQL、Redis、RSSHub、Celery worker/beat running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | 部署前 PostgreSQL custom-format backup：`/opt/agomtradepro/backups/database/postgres-20260818-181338.dump`；本次未执行 restore/rebuild 或 RTO/RPO drill |

本节是当前 release 的部署、版本、健康与 TUI runtime 只读证据，不是角色化浏览器 UAT、生产业务写入或写后 receipt/refresh 证明。没有执行登录、角色化权限走查、业务写入、14 日 telemetry/defect、registry backup/restore、rollback 双签、owner/reviewer 双签或 AUD-01/EVID-01 durable authority/publisher 验证；相关 gate 继续 fail-closed。CI Fast Feedback 的 Python 3.11 浏览器安装任务在本次记录时仍为外部 runner 观测项，不能由 VPS 健康结果替代。

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

## 2026-08-19 06:00 TUX-02 dead-patch cleanup deployment and observation

提交 `0c50dfafc24fe47ee68ac93933d6c48a81e8c3fd` 在 Security、Architecture、Consistency 与 Fast Feedback 四条 CI 全部成功后，使用标准 `git-clone`、`-Upgrade`、code-only 模式发布；PostgreSQL/Redis 数据卷保留，Celery 保持启用。本次是普通 TUX-02 运行身份/健康观测，不重绑 `web-to-tui-m5` 候选，也不构成角色化 UAT 或业务写入证据。

| 项目 | 证据 |
|---|---|
| release tag | `20260819054217` |
| release dir | `/opt/agomtradepro/releases/source-20260819054217` |
| source commit | `0c50dfafc24fe47ee68ac93933d6c48a81e8c3fd` |
| image | `agomtradepro-web:20260819054217` |
| image ID | `sha256:316b92f03a03b9bc328680ec8fa05c8e8e77ce2abce8d68be3b337f43810379a` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819054217.json` |
| mode | `ACTION=upgrade`、code-only、数据卷保留、Celery enabled |
| migration/schema | `No migrations to apply`；canonical schema `missing_migrations=[]`、`missing_tables=[]`；Django deploy check 无 issues（1 silenced） |
| TUI registry | publish/check 通过；registry `28`、active source hash 与 expected 一致；backend version 保持 reviewed release `20260819000530` |
| HTTPS/TLS | Caddy 使用 `demo.agomtrade.pro`；证书 expiry check 通过；`/api/health/` 8 次均 HTTP `200`（约 `1.10–1.77s`）；`/api/ready/` 3 次均 HTTP `200`（约 `5.02–5.69s`） |
| containers | web healthy；celery worker/beat、PostgreSQL、Redis、Caddy、RSSHub、runtime namespace running；Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`；错误 `qlib` distribution absent；module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime identity | release manifest `runtime_match=true`；`source_mode=git-clone`；`short_commit=0c50dfafc24f` |
| readiness observation | `/api/ready/` body 保留现有数据 freshness/degraded 提示；本次未用部署成功掩盖数据状态 |
| backup | `/opt/agomtradepro/backups/database/postgres-20260818-234905.dump`；部署前备份已创建并通过 verifier |

本次仅做启动、版本、迁移、TUI registry、Qlib、Celery、HTTPS 与短时只读健康复核，没有登录、角色化浏览器 UAT 或业务写入。写后 receipt/refresh、14 日 telemetry/defect、registry backup/restore、rollback drill、owner/reviewer 双签以及 AUD-01/EVID-01 durable authority/publisher 仍未完成，相关 gate 继续 fail-closed。

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

## 2026-08-19 07:05 TAR-01 reserved queued route guard candidate

The route-level fail-closed boundary was deployed in code-only upgrade mode from the
immutable `dev/next-development` candidate. PostgreSQL/Redis data volumes were preserved;
Celery remained enabled. The queued intake and worker feature flags remain disabled, so this
deployment does not enable durable runs or Agent execution through the new routes.

| Item | Evidence |
|---|---|
| release tag | `20260819064907` |
| release directory | `/opt/agomtradepro/releases/source-20260819064907` |
| source commit | `3ba46b2f06bce4cf11cc0293903a54193be7b4ef` |
| image | `agomtradepro-web:20260819064907` |
| image ID | `sha256:232faecb1f69c69778085aee69d90f66dcbfd5c54085ed13f27ab181c0c0e12c` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819064907.json` |
| mode | `ACTION=upgrade`, code-only, data volumes preserved, Celery enabled |
| migrations/schema | `No migrations to apply`; canonical schema `{"missing_migrations": [], "missing_tables": [], "ok": true}` |
| HTTPS/TLS | `demo.agomtrade.pro` Caddy domain; TLS verifier passed |
| containers | web healthy; Celery worker/beat, PostgreSQL, Redis, Caddy, RSSHub and runtime namespace running; Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`; wrong `qlib` distribution absent; module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | pre-deploy PostgreSQL backup `/opt/agomtradepro/backups/database/postgres-20260819-005522.dump` created and verifier passed |

Short public read-only observation after deployment:

- `https://demo.agomtrade.pro/api/health/`: 8/8 HTTP `200`, approximately `1.09–1.85s`.
- `https://demo.agomtrade.pro/api/ready/`: 3/3 HTTP `200`, approximately `4.61–11.55s`; database,
  Redis, Celery and critical-data checks were `ok`. The response still exposed the existing
  data-freshness degradation (`etf_net_flow` stale / `market_thermometer` data source degraded),
  which was not hidden by the deployment.
- Anonymous `POST /api/terminal/runs/` returned HTTP `403` from the authentication boundary. No
  authenticated role account was provisioned in this observation, so the post-authenticated
  `503 DISPATCH_UNAVAILABLE / queued_runtime_not_wired` response was not claimed as production
  UAT evidence. No business write, receipt/refresh, role browser UAT, capacity/chaos, 14-day
  telemetry, restore/rollback drill, or owner/reviewer sign-off was performed.

This is a short-window runtime identity and read-only health observation only. TAR-01 remains
active; TAR-02 and production gates remain fail-closed.

## 2026-08-19 08:22 current f9f31700a candidate deployment and read-only observation

After all four GitHub checks for the immutable candidate succeeded, `dev/next-development`
was deployed in code-only upgrade mode. PostgreSQL/Redis data volumes were preserved and
Celery remained enabled. The deployment did not restore local SQLite or enable the queued
Agent runtime.

| Item | Evidence |
|---|---|
| release tag | `20260819080800` |
| release directory | `/opt/agomtradepro/releases/source-20260819080800` |
| source commit | `f9f31700accf1c1dd1786631823898fec50e4ec3` |
| image | `agomtradepro-web:20260819080800` |
| image ID | `sha256:1c462f1456477f83b4cf5bdcf54ecb6ef5ca14bd363b8de250472e5cd842e03a` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819080800.json` |
| mode | `ACTION=upgrade`, code-only, data volumes preserved, Celery enabled |
| migration/schema | `No migrations to apply`; canonical schema `{"missing_migrations": [], "missing_tables": [], "ok": true}`; Django system check reported no issues (one silenced) |
| TUI registry | registry `28`, published, active source hash matched expected; TUI preflight/JS suite passed before deploy |
| HTTPS/TLS | `demo.agomtrade.pro` Caddy domain; TLS verifier passed |
| containers | web healthy; Celery worker/beat, PostgreSQL, Redis, Caddy, RSSHub and runtime namespace running; Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`; wrong `qlib` distribution absent; module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | pre-deploy PostgreSQL custom-format backup `/opt/agomtradepro/backups/database/postgres-20260819-021459.dump` created and verifier passed |

Independent post-deploy HTTPS samples from the VPS all returned HTTP `200`: `/api/health/`
was `8/8` (about `0.013–0.200s`) and `/api/ready/` was `3/3` (about `3.48–8.17s`). The
ready payload reported database, Redis, Celery and critical-data checks as `ok`; it also
retained the existing decision-data freshness/degraded-source observations (including stale
`etf_net_flow` and a degraded market-thermometer source) rather than hiding them.

This is a candidate identity, deployment and short-window read-only observation only. No
login, role-specific browser UAT, business write, post-write receipt/refresh, 1/5/10/20
capacity or chaos run, 14-day telemetry, registry backup/restore, rollback drill,
owner/reviewer sign-off, or AUD-01/EVID-01 durable authority/publisher verification was
performed. TAR-01/TAR-02, TUX-02/TUX-04, M5 and the related production gates remain
fail-closed.

## 2026-08-19 13:31 AUD-01/DATA-01 current candidate deployment

After all four GitHub push workflows succeeded for the immutable candidate,
`dev/next-development@29cdf14206239c4b36b0d31f07980ef8b5a26855` was deployed in
code-only upgrade mode. PostgreSQL and Redis data volumes were preserved, Celery remained
enabled, and the standard deployment rollback guard remained active.

| Item | Evidence |
|---|---|
| release tag | `20260819133110` |
| release directory | `/opt/agomtradepro/releases/source-20260819133110` |
| source commit | `29cdf14206239c4b36b0d31f07980ef8b5a26855` |
| image | `agomtradepro-web:20260819133110` |
| image ID | `sha256:3748a5aa68dd919e2225894a851c41db88a49cd8b16396974bd64d77ff80a88c` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819133110.json` |
| CI | Architecture `32219241014`, Security `32219241060`, Consistency `32219241034`, Fast Feedback `32219241038`: all `success` |
| migrations/schema | `No migrations to apply`; canonical schema had no missing migrations or tables; Django deploy check passed |
| TUI | local preflight and 34 JS tests passed; registry `28` remained published and active source hash matched expected |
| Qlib | `pyqlib=0.9.7`; wrong `qlib` distribution absent |
| runtime | Web healthy; PostgreSQL, Redis, Caddy, RSSHub, runtime namespace and Celery worker/beat running; Celery ping `1 node online` |
| TLS | `demo.agomtrade.pro` certificate verifier passed |
| backup | PostgreSQL `/opt/agomtradepro/backups/database/postgres-20260819-073827.dump`; metadata manifest `/opt/agomtradepro/backups/meta/manifest-20260819-073827.txt` |

Independent post-deploy HTTPS sampling returned HTTP `200` for `/api/health/` 8/8
(`1.09–3.46s`) and `/api/ready/` 3/3 (`4.62–9.94s`). Database, Redis, Celery,
critical data and Alpha/workspace consistency were `ok`. Decision readiness remained
fail-closed: the two configured quotes were about 243 minutes old against a four-hour
threshold and published `must_not_use_for_decision=true`; `etf_net_flow` also remained stale
and the market-thermometer source degraded.

This is immutable release identity plus short-window read-only health evidence. It does not
prove authenticated audit authority, durable audit delivery, production restore/RTO/RPO,
live rollback, backfill/reconciliation, role browser UAT, post-write receipt/refresh, 14-day
telemetry, or owner/reviewer sign-off. AUD-01 stays active, DATA-01 stays
`awaiting_production`, and dependent gates remain fail-closed.

## 2026-08-19 09:12 AUD-01 authority preflight candidate deployment

The AUD-01 runtime authority snapshot preflight contract was deployed from the immutable
`dev/next-development` candidate in code-only upgrade mode. PostgreSQL/Redis data volumes
were preserved and Celery remained enabled. The preflight remains dormant: it does not wire
the dispatcher, claim events, publish to a durable sink, or create production authority.

| Item | Evidence |
|---|---|
| release tag | `20260819091201` |
| release directory | `/opt/agomtradepro/releases/source-20260819091201` |
| source commit | `fbf0901522f6310cb66b2571f5400fede1d2e646` |
| image | `agomtradepro-web:20260819091201` |
| image ID | `sha256:24987a71875c1156ced5d796eeb0cda0dec011439d382c7c511e360f409b5272` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819091201.json` |
| mode | `ACTION=upgrade`, code-only, data volumes preserved, Celery enabled |
| migrations/schema | `No migrations to apply`; canonical schema `{"missing_migrations": [], "missing_tables": [], "ok": true}`; Django system check reported no issues (one silenced) |
| TUI registry | registry `28`, published, active source hash matched expected |
| HTTPS/TLS | `demo.agomtrade.pro` Caddy domain; TLS verifier passed |
| containers | web healthy; Celery worker/beat, PostgreSQL, Redis, Caddy, RSSHub and runtime namespace running; Celery ping `1 node online` |
| Qlib | `pyqlib=0.9.7`; wrong `qlib` distribution absent; module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| backup | pre-deploy PostgreSQL custom-format backup `/opt/agomtradepro/backups/database/postgres-20260819-031937.dump` created and verifier passed |
| CI | Fast Feedback `32203625294`, Security `32203625328`, Architecture `32203625280`, Consistency `32203625295` all `success` |

Independent post-deploy HTTPS samples all returned HTTP `200`: `/api/health/` was `8/8`
with approximately `1.118–1.896s` response times, and `/api/ready/` was `3/3` with
approximately `4.526–9.824s` response times. Database, Redis, Celery and critical-data
checks were `ok`. The ready payload retained the existing decision-data freshness
disclosures, including stale `etf_net_flow` and a degraded market-thermometer source.

This is deployment identity and short-window read-only observation only. No authenticated
authority lifecycle, durable publisher/receipt sink, dispatcher claim, beat/retry/requeue,
Data Center same-UOW dual-write, role browser UAT, business write/receipt refresh, capacity
or chaos run, 14-day telemetry, registry backup/restore, rollback drill, or owner/reviewer
sign-off was performed. AUD-01 remains fail-closed; AUD-02/03, TAR/TUX production gates,
M5 and EVID-01 authority gates remain unchanged.

## 2026-08-19 15:44 TAR-01 immutable candidate authenticated boundary acceptance

After the four push workflows succeeded for `dev/next-development@da04c053aa16bd940a45896a531ee567a8a2a892`,
the immutable candidate was deployed in code-only `-Upgrade` mode. PostgreSQL and Redis
volumes were preserved, Celery remained enabled, and the standard pre-deploy backup and
automatic rollback guard remained active.

| Item | Evidence |
|---|---|
| release tag | `20260819145227` |
| release directory | `/opt/agomtradepro/releases/source-20260819145227` |
| source commit | `da04c053aa16bd940a45896a531ee567a8a2a892` |
| image | `agomtradepro-web:20260819145227` |
| image ID | `sha256:cc6fe35e4e14643223cbb9f97953ef5499ce47f844bdd97eb6e4d319ba952b3b` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260819145227.json` |
| CI | Architecture `32224685464`, Security `32224685486`, Consistency `32224685553`, Fast Feedback `32224685685`: all `success` |
| migrations/schema | no pending migrations; canonical schema, Django deploy check and TUI registry verification passed |
| backup | PostgreSQL `/opt/agomtradepro/backups/database/postgres-20260819-085915.dump`; manifest `/opt/agomtradepro/backups/meta/manifest-20260819-085915.txt` |
| runtime | Web/PostgreSQL/Redis/RSSHub healthy; Caddy/runtime namespace/Celery worker and beat running; Celery ping found one node; Qlib `0.9.7`; TLS verifier passed |

An existing authenticated production test account was used without printing credentials,
cookies or tokens. The reserved route was exercised at concurrency `1/5/10/20` with exactly
`1/5/10/20` requests. All `36/36` calls returned the expected dormant response: HTTP `503`,
`code=DISPATCH_UNAVAILABLE`, `reason_code=queued_runtime_not_wired`, and `Retry-After=60`.
The diagnostic external-HTTPS latency was:

| concurrency | responses | p50 | p95 | p99 | max |
|---:|---:|---:|---:|---:|---:|
| 1 | 1/1 expected 503 | 1331.92 ms | 1331.92 ms | 1331.92 ms | 1331.92 ms |
| 5 | 5/5 expected 503 | 1632.41 ms | 1700.88 ms | 1700.88 ms | 1700.88 ms |
| 10 | 10/10 expected 503 | 1995.00 ms | 2108.57 ms | 2108.57 ms | 2108.57 ms |
| 20 | 20/20 expected 503 | 2651.99 ms | 3116.70 ms | 3236.60 ms | 3236.60 ms |

Five health samples before and after this staircase were `200`; their external-HTTPS p95 was
`1317.05 ms` and `1300.87 ms`. A second mixed observation issued 20 dormant route requests and
20 health requests concurrently. It returned `20/20` expected `503` and `20/20` health `200`,
but route p95 was `4786.71 ms` and health p95 was `4026.08 ms`. This diagnostic result is not
promoted into `run_api_p95_ms`: the route is deliberately dormant and did not admit or execute
a run. It also exceeds the future hard latency/degradation criteria, so it cannot be used to
issue a capacity-ready report.

The mixed observation was bracketed by read-only Docker/resource snapshots. Web memory was
`331.1 -> 331.7 MiB` of `1 GiB`; Redis was `12.48 -> 12.70 MiB` of `300 MiB`; PostgreSQL was
`179.5 -> 181.3 MiB` of `768 MiB`. Web, Celery worker, Redis and PostgreSQL all remained
running with restart count `0` and `OOMKilled=false`; Redis reported `blocked_clients=0`.
However, a pre-existing Qlib prediction task held the Celery worker near `100%` CPU and its
memory rose from `1.153 GiB` (`78.69%`) to `1.284 GiB` (`87.64%`) of `1.465 GiB`. That
background load is preserved as a confounder and resource-pressure observation, not hidden or
attributed to the dormant Terminal requests.

Acceptance outcome: the authenticated fail-closed and no-restart/OOM boundary is verified for
this immutable candidate, but queued capacity is **not accepted**. No durable admission, queue
depth/age, worker lease/orphan recovery, SSE replay, cancellation, idempotency, provider/MCP
call-count or chaos evidence exists; six canonical matrix scenarios remain `planned`. TAR-01
stays active, TAR-02 remains waiting, queued intake/worker flags stay off, and no inline
concurrency limit is raised.

## 2026-08-20 `41005ea22` current-candidate deployment and read-only observation

After the four push workflows succeeded for `dev/next-development@41005ea223621689033ab38b8d9a77353dcf26ed`,
the current candidate was deployed in code-only `-Upgrade` mode. PostgreSQL and Redis data
volumes were preserved, Celery remained enabled, and the standard pre-deploy backup plus
automatic rollback guard remained active.

| Item | Evidence |
|---|---|
| release tag | `20260820012016` |
| release directory | `/opt/agomtradepro/releases/source-20260820012016` |
| source commit | `41005ea223621689033ab38b8d9a77353dcf26ed` |
| image | `agomtradepro-web:20260820012016` |
| image ID | `sha256:0834950788c4575ae702f701505697d77c43933a48ca445496a714934b95213e` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260820012016.json` |
| mode | `ACTION=upgrade`, code-only, data volumes preserved, Celery enabled |
| CI | Fast Feedback `32280081761`, Security `32280081728`, Architecture `32280081676`, Consistency `32280081708`: all `success` |
| migrations/schema | no migrations to apply; canonical schema had no missing migrations/tables; Django check passed |
| TUI | local preflight and 34 JavaScript tests passed; registry `28` published and active source hash matched expected |
| Qlib | `pyqlib=0.9.7`; wrong `qlib` distribution absent; module `/usr/local/lib/python3.11/site-packages/qlib/__init__.py` |
| runtime | web healthy; PostgreSQL, Redis, Caddy, RSSHub, runtime namespace and Celery worker/beat running; Celery ping `1 node online` |
| TLS/backup | `demo.agomtrade.pro` Caddy/TLS verifier passed; pre-deploy PostgreSQL backup and manifest created on VPS |

Independent post-deploy HTTPS sampling (without a production API token) returned HTTP `200` for
`/api/health/`, `/api/ready/`, and `/api/`. Protected `/api/tui/`, `/api/terminal/`,
`/api/terminal/runs/`, `/api/policy/status/`, `/api/signal/active/`, and `/api/data-center/`
returned the expected unauthenticated `403`. `/api/regime/current/` returned the existing
fail-closed `503 decision_runtime_blocked` payload, so no decision output was used. The ready
payload reported database, Redis, Celery (one worker), critical data and decision-data checks;
existing freshness/degraded-source disclosures remain visible.

This is immutable deployment identity and short-window read-only observation only. No
authenticated role browser UAT, business write/receipt-refresh, 14-day telemetry, production
restore/RTO/RPO, live rollback, backfill/reconciliation, capacity/chaos run, or owner/reviewer
sign-off was performed; TUX-02/TUX-04, STRAT, DATA-01, TAR, AUD and EVID production gates remain
fail-closed where previously recorded.

### Independent verifier rerun (2026-08-20, read-only)

The repository verifier was rerun against the active release directory with
`--expected-commit 41005ea223621689033ab38b8d9a77353dcf26ed` and Celery checks enabled. It
returned exit code `0`: Caddy/domain, HTTPS health `200`, TLS expiry, container state, Django
deploy check, migrations, canonical Data Center schema, TUI registry, Qlib identity, release
identity, secrets/backup, resources, healthcheck, both Celery containers, and Celery ping all
passed. The release identity remained `git_sha=41005ea223621689033ab38b8d9a77353dcf26ed` with
image `sha256:0834950788c4575ae702f701505697d77c43933a48ca445496a714934b95213e`.

Fresh public HTTPS samples at the same observation window returned `/api/health/`, `/api/ready/`
and `/api/` as `200`; unauthenticated `/api/tui/`, `/api/terminal/`, `/api/terminal/runs/`,
`/api/policy/status/`, `/api/signal/active/` and `/api/data-center/` returned `403`. The
unauthenticated `/api/regime/current/` response remained `503` with
`block_reason_code=decision_runtime_blocked` and `must_not_use_for_decision=true`. This confirms
the deployed read-only and fail-closed boundary only; it is not role/browser/write acceptance.

### Current-candidate PostgreSQL read-only inventory (2026-08-20)

Inside the running web container, a read-only Django/PostgreSQL query confirmed account
migrations `0050` through `0054`, `agent_runtime.0004_terminal_agent_run`, and audit migration
`0012_systemauditevent_scope` are applied. The authority/evidence/root-lock ledgers for the
current candidate remain zero-seed (all twelve governed tables returned `0` rows). The same
snapshot returned `audit_system_outbox=0` and `audit_system_event=0`; this is an empty-backlog
observation, not evidence that a durable publisher or authenticated authority is wired. No rows
were inserted, updated, deleted, or backfilled.

## 2026-08-20 `9341789db` latest-candidate deployment and HTTPS acceptance

After the four push workflows completed successfully for
`dev/next-development@9341789dbaf1f4e0239ee6c7aa63b42e0136286f`, the candidate was
deployed in code-only `-Upgrade` mode. PostgreSQL/Redis data volumes were preserved and the
standard pre-deploy backup and rollback guard remained enabled.

| Item | Evidence |
|---|---|
| release tag | `20260820025103` |
| release directory | `/opt/agomtradepro/releases/source-20260820025103` |
| source commit | `9341789dbaf1f4e0239ee6c7aa63b42e0136286f` |
| image | `agomtradepro-web:20260820025103` |
| image ID | `sha256:02a4a5b7098aec6ba3c152d05442a6316e1428bc3feee652e8f82ff672b4a200` |
| deployment report | `dist/remote-build-reports/remote-build-report-20260820025103.json` |
| deployment verifier | built-in post-deploy verifier exited `0`; release/image identity, Caddy/TLS, health, containers, Django deploy check, migrations/schema, TUI registry, Qlib, backup, resources, Celery and ping all passed |
| TUI preflight | `npm run check:tui` and 34 JavaScript tests passed before deployment; runtime manifest/source identity matched |
| runtime | web healthy; PostgreSQL, Redis, Caddy, RSSHub, runtime namespace and Celery worker/beat running; Celery ping `1 node online` |

Public HTTPS sampling after deployment returned `200` for `/api/health/`, `/api/ready/`, and
`/api/`. Protected `/api/tui/`, `/api/terminal/`, `/api/terminal/runs/`,
`/api/policy/status/`, `/api/signal/active/`, and `/api/data-center/` returned the expected
unauthenticated `403`. `/api/regime/current/` remained the existing fail-closed `503
decision_runtime_blocked` response with `must_not_use_for_decision=true`; no decision output was
used. The ready payload reported database, Redis, Celery and critical-data checks as healthy,
while existing freshness/degraded-source disclosures remain visible.

This is immutable deployment identity plus a short-window, read-only HTTPS acceptance only. No
authenticated role browser UAT, business write/receipt-refresh proof, 14-day telemetry,
production restore/RTO/RPO, live rollback, capacity/chaos run, backfill/reconciliation, or
owner/reviewer sign-off was performed. TUX-02/TUX-04, M5, TAR, AUD and EVID production gates
therefore remain fail-closed where previously recorded. A second standalone verifier invocation
was not used as evidence because the local shell safety policy blocked its credential bootstrap;
the deployment-integrated verifier above is the accepted verification record.

## 2026-08-19 20:58 当前候选部署与观测

`dev/next-development@f3881a04cf0b5d5bff5d2b7e5a6bf25d523667e2` was deployed in code-only
`-Upgrade` mode as release `20260820043710`; PostgreSQL/Redis volumes were preserved and
Celery remained enabled. The release report is
`dist/remote-build-reports/remote-build-report-20260820043710.json`; the immutable OCI image
is `sha256:ac621fb9cd594045e211e5a4e7cc16c11fea10ca8c34fb5bea148572b4347dc5`, and the
runtime source/image identity matched the expected commit. Deployment verification passed for
migrations/schema, Django checks, TUI registry, Qlib (`pyqlib=0.9.7`, wrong distribution absent),
Celery worker/beat/ping, containers, TLS, resources and backup.

Independent HTTPS read-only probes returned `/api/health/` `5/5=200`, `/api/ready/` `5/5=200`
and `/api/` `5/5=200`. The unauthenticated reserved route `/api/terminal/runs/` returned the
expected `403`; `/api/regime/current/` remained `503 decision_runtime_blocked`, so execution
and decision fail-closed boundaries remained intact. No authenticated role browser UAT,
business write receipt/refresh, capacity/chaos, 14-day telemetry, restore/rollback or
owner/reviewer sign-off was performed.

The candidate binding is `web-to-tui-candidate-binding.v1`: candidate version
`20260820043710`, candidate commit `f3881a04cf0b5d5bff5d2b7e5a6bf25d523667e2`, matrix
`bf7a6234a473c354b923d56793dd0c5b6eba8970e0ca0d212e14ed68bdc39ded`, published graph
`5a2234c84d4156001a8bde73a7fe9a5c86534b77a6e87da68764043b55d7b597`, schema `tui-metadata.v3`,
runtime `0.2.0`, build `agomtui-runtime-0.2.0+b00df1fa9186`, and manifest
`7d2d059828553fec11b83df19e09698a1025fd818c103c630d2f432d6550000f`. The M5 observation
window is reset to this candidate and no prior UAT or telemetry is inherited.

## 2026-08-19 22:07 UTC TAR-01/M5 read-only follow-up

The same manifest-bound candidate `f3881a04cf0b5d5bff5d2b7e5a6bf25d523667e2` / release
`20260820043710` remained reachable over public HTTPS. Independent samples returned
`/api/health/` `5/5=200` (approximately `1.20–2.18s`), `/api/ready/` `3/3=200`
(approximately `4.92–5.17s`), and `/api/` `3/3=200` (approximately `1.11–1.61s`).
The unauthenticated `/api/terminal/runs/` route returned `403` with the expected missing
authentication error. `/api/regime/current/` returned the existing `503`
`decision_runtime_blocked` response with `must_not_use_for_decision=true`.

This is a short-window, read-only observation only. No authenticated reserved-route
`503`, 1/5/10/20 admission or capacity run, queue/worker/SSE/idempotency/cancel/provider-
MCP/chaos metric, business write receipt, role UAT, restore/rollback or owner/reviewer
evidence was collected; TAR-01/TAR-02/TAR-05 and the M5 production gates remain
fail-closed.

## 2026-08-19 22:39 UTC `80ea441e2` deployment and independent HTTPS observation

The pushed `dev/next-development` HEAD `80ea441e2fc83059415c46124b0676fd1705b3d0` was
deployed in code-only `-Upgrade` mode as release `20260820062052`; PostgreSQL and Redis
volumes were preserved and Celery remained enabled. The local deployment report is
`dist/remote-build-reports/remote-build-report-20260820062052.json`; the deployed image is
`sha256:7c6c96a7e771641a011b6521d0c2901131e0dbc2c478cbeaa27cb716e8107720`.

The built-in verifier exited `0`: release/image identity, Caddy/TLS, health, containers,
Django deploy check, migrations/schema, TUI registry, Qlib (`pyqlib=0.9.7`, wrong `qlib`
distribution absent), PostgreSQL backup, resources, Celery worker/beat and Celery ping all
passed. Independent public HTTPS probes after the switch returned:

| probe | result |
|---|---|
| `/api/health/` | `5/5` HTTP `200`, approximately `1.26–2.42s` |
| `/api/ready/` | `3/3` HTTP `200`, approximately `4.91–10.16s`; database/Redis/Celery/critical-data checks reported healthy |
| `/api/` | `3/3` HTTP `200`, approximately `1.08–1.11s` |
| protected `/api/tui/`, `/api/terminal/runs/`, `/api/policy/status/`, `/api/signal/active/`, `/api/data-center/` | HTTP `403` with the unauthenticated boundary |
| `/api/regime/current/` | HTTP `503`, `decision_runtime_blocked`, `must_not_use_for_decision=true` |

This is deployment identity plus a short-window read-only observation. No authenticated role
browser UAT, business write/receipt-refresh proof, 1/5/10/20 capacity or chaos run, queue/
worker/SSE/idempotency/cancel/provider-MCP metrics, 14-day telemetry, restore/rollback drill,
backfill/reconciliation, or owner/reviewer sign-off was performed; TAR-01/TAR-02/TAR-05 and
the M5 production gates remain fail-closed.
## 2026-08-20 00:05 UTC `39992992c` policy-PENDING fix deployment and authenticated read-only acceptance

The pushed `dev/next-development@39992992cadc1c261f5dd8ffb06b64708a19397f` was deployed in
code-only `-Upgrade` mode. PostgreSQL/Redis volumes were preserved, the standard pre-deploy
backup and rollback guard remained enabled, and old Docker images were pruned only within the
`agomtradepro-web` image family after the first deployment attempt exhausted the VPS root disk.
Database volumes were not removed.

| Item | Evidence |
|---|---|
| release | `20260820075124` at `/opt/agomtradepro/releases/source-20260820075124` |
| source/image | `39992992cadc1c261f5dd8ffb06b64708a19397f`; `agomtradepro-web:20260820075124`; `sha256:0d08887db56e2367264950efe00fca71b8c34e97d2643e425decabb2ef190ad4` |
| report | `dist/remote-build-reports/remote-build-report-20260820075124.json` |
| verifier | exit `0`; Caddy/TLS, HTTPS health, containers, Django check, migrations/schema, TUI registry, Qlib (`pyqlib=0.9.7`, wrong distribution absent), backup, resources, Celery worker/beat/ping all passed |
| TUI preflight | `npm run check:tui` plus 34 JavaScript tests passed |

Authenticated read-only HTTPS acceptance used the supplied login account and did not invoke any
business write endpoint. Login succeeded; `/api/tui/operator/home/` returned `200` (the prior
PENDING-policy traceback no longer occurs), `/api/policy/status/` returned `200` with level `PX`,
`level_name=待分类`, `requires_manual_approval=true`, and safe normal-operation semantics. The
TUI catalog/bootstrap/registry/provider screen, signal, data-center, health and readiness probes
returned `200`. `/api/regime/current/` remained the expected fail-closed `503`.

Remote web logs after the probes showed `GET /api/tui/operator/home/ - 200` and no
`Unknown policy`, traceback, or home-endpoint `500`. This is immutable deployment identity plus
short-window authenticated read-only evidence only: no business writes, role-matrix browser UAT,
write receipts/refresh, 14-day telemetry, restore/rollback drill, capacity/chaos run, or
owner/reviewer sign-off was performed. TAR-01/TAR-02/TAR-05, TUI/M5, AUD and EVID production
gates remain fail-closed where previously recorded.

### Authenticated TAR/AUD boundary and backlog observation (2026-08-20 00:19 UTC)

On the same release, the supplied login account was used only for GET probes. The authenticated
`/api/terminal/runs/` boundary returned HTTP `503` with
`reason_code=queued_runtime_not_wired`, confirming that the dormant queued runtime remains
explicitly unavailable. `/api/audit/health/` returned `overall_status=OK`: database and audit
tables were accessible, total audit failures were `0), and the outbox snapshot reported
`pending=0`, `due_pending=0`, `claimed=0`, `expired_claimed=0`, `failed=0), and
`delivered=0). `/api/audit/metrics/`, `/api/metrics/`, and `/metrics/` all returned
HTTP `200`.

These are read-only health/backlog observations, not proof of a durable publisher, dispatcher
delivery, authenticated audit authority, queued admission, worker, SSE, idempotency/cancel
behavior, or production PostgreSQL race evidence. TAR-01, AUD-01/AUD-03, and their dependent
production gates remain fail-closed.

## 2026-08-20 00:44–00:47 UTC post-deploy verifier rerun and authenticated read-only acceptance

The active runtime remained the immutable `39992992cadc1c261f5dd8ffb06b64708a19397f` candidate
(`agomtradepro-web:20260820075124`, image
`sha256:0d08887db56e2367264950efe00fca71b8c34e97d2643e425decabb2ef190ad4`). A full independent
`scripts/deploy_vps_verify.py --expected-commit ... --expect-celery` rerun exited `0`: Caddy/TLS,
health, containers, Django deploy check, migrations, canonical schema, TUI registry, Qlib,
release/image identity, backup, resources, healthcheck, worker/beat and Celery ping all passed.
The first verifier invocation had a transient Celery inspect timeout; a direct 20-second ping
returned `1 node online`, and the complete verifier rerun then passed. No restart, image or
volume change was made during this observation.

Using the supplied authenticated account, read-only HTTPS probes returned `200` for health,
readiness, TUI root/catalog/bootstrap/operator home/governance queue/registry/provider screen,
policy status, signal, data-center, audit, audit metrics and Prometheus metrics. Policy status
continued to expose the safe PENDING contract (`PX`/`待分类`, manual approval required, normal
operation, zero cash adjustment). `/api/regime/current/` remained `503 decision_runtime_blocked`
with `must_not_use_for_decision=true`; authenticated `/api/terminal/runs/` remained the explicit
`503 queued_runtime_not_wired` boundary. Audit health remained `OK` with no recorded failures and
an empty outbox snapshot. No business write, role-matrix browser UAT, receipt/refresh proof,
capacity/chaos, restore/rollback, 14-day telemetry or owner/reviewer sign-off was performed.
The related TAR/AUD/TUI/M5 production gates therefore remain fail-closed.

## 2026-08-20 01:33–01:37 UTC `05970a925` TUI patch cleanup deployment and acceptance

The pushed `dev/next-development@05970a925f0b348574a1805c243d7d9140d3e243` was deployed in
code-only `-Upgrade` mode as release `20260820091752`; PostgreSQL/Redis data volumes were
preserved and Celery remained enabled. The deployment report is
`dist/remote-build-reports/remote-build-report-20260820091752.json`; the running image is
`sha256:33007a77bda880e302c75d3cf09f4b338adcd15e4711c9dde4d33eb30462b217`. Local TUI
preflight passed `npm run check:tui` and 34 JavaScript tests.

The built-in verifier and an independent expected-commit verifier both passed: Caddy/TLS,
HTTPS health, containers, Django deploy check, migrations, canonical schema, published TUI
registry, Qlib (`pyqlib=0.9.7`, wrong `qlib` distribution absent), release/image identity,
backup, resources, healthcheck, Celery worker/beat and `1 node online` ping. Authenticated
read-only HTTPS probes then returned `200` for readiness, TUI catalog/bootstrap/operator and
governance surfaces, provider screen, policy status, audit and metrics. Policy remained the
safe PENDING contract (`PX`/`待分类`, manual approval required, normal operation, zero cash
adjustment); `/api/regime/current/` remained `503 decision_runtime_blocked` with
`must_not_use_for_decision=true`; `/api/terminal/runs/` remained `503 queued_runtime_not_wired`.
Audit health was `OK` with zero recorded failures. No business write, role browser UAT,
receipt/refresh, capacity/chaos, restore/rollback, 14-day telemetry or owner/reviewer sign-off
was performed; production gates remain fail-closed.

## 2026-08-20 production role/browser UAT on the active `05970a925` release

The active VPS remained `dev/next-development@05970a925f0b348574a1805c243d7d9140d3e243`,
release `20260820091752`, with the code-only upgrade and preserved PostgreSQL/Redis volumes
described above. HTTPS Playwright UAT used two dedicated production users provisioned for this
controlled run: `m5_uat_operator` (user id `5`, operator group) and `m5_uat_regular` (user id
`6`, no operator group). Credentials were supplied only through the local test environment and
are not recorded here.

Isolated production runs passed:

- `test_operator_group_can_open_queue_but_regular_user_cannot` (`1 passed`): operator queue
  visibility was allowed and the regular user was denied.
- `test_strategy_create_detail_update_lifecycle_completes` (`1 passed`): a strategy was created,
  read back, updated, and read back again.
- `test_personal_ai_provider_detail_update_lifecycle_completes` (`1 passed`): the provider was
  created and updated under the user-owned screen. The sensitive API-key field was deliberately
  not URL-prefilled; the browser filled an inert run-scoped placeholder in the explicit
  `补填参数` dialog before confirmation, and the detail/update readback completed.
- `test_account_read_missing_fields_and_confirmation_cancel`,
  `test_parameterized_read_primary_tasks_complete`, and
  `test_role_appropriate_direct_read_primary_tasks_complete` (`3 passed`): confirmation/cancel,
  parameterized primary reads, and the least-privileged direct-read matrix completed.

The two controlled business rows created by the write checks were verified before deletion and
then removed by exact owner/name selectors: strategy id `2` (`M5 UAT 策略 20260820`) and provider
id `9` (`M5 UAT 服务商 20260820`, owner user id `6`). The post-cleanup query returned zero rows for
both selectors. The dedicated UAT users remain provisioned for any separately authorized
observation window; no password or secret is persisted in the repository.

After cleanup, `scripts/deploy_vps_verify.py --expected-commit
05970a925f0b348574a1805c243d7d9140d3e243 --expect-celery` was rerun at approximately
`2026-08-20T02:46Z` and exited `0`: HTTPS health, Caddy/TLS, containers, Django/migrations,
canonical schema, TUI registry, release/image identity, backup, healthcheck and Celery ping
remained green.

This is real HTTPS role/write/readback evidence against the active VPS release, but it is not the
formal M5 candidate gate: the registry/readiness binding still names the separately bound
`f3881a04...` / release `20260820043710`. No 14-day telemetry, write-receipt/refresh audit,
registry backup/restore, live rollback, capacity/chaos run, or owner/reviewer sign-off was
performed. M5/TUI, TAR, AUD and EVID production gates therefore remain fail-closed.

## 2026-08-20 `28e0c2608` deep-link form fix deployment and final role/browser acceptance

The pushed `dev/next-development@28e0c2608eea1c0a4aed51c3a54eed80220db503` was deployed
code-only with `-Upgrade`; PostgreSQL/Redis volumes were preserved and Celery remained enabled.
The release was `20260820114848` at `/opt/agomtradepro/releases/source-20260820114848`, with
image `sha256:2eaeffd5a1653c3133b09c8d02880f39128ee9ae50acd658819078fed775208d`. The local
deployment report is
`dist/remote-build-reports/remote-build-report-20260820114848.json`.

The deploy script and an independent `scripts/deploy_vps_verify.py --expected-commit
28e0c2608eea1c0a4aed51c3a54eed80220db503 --expect-celery` both exited `0`: Caddy/domain TLS,
HTTPS health, containers, Django check, migrations/canonical schema, published TUI registry,
Qlib (`pyqlib=0.9.7`, wrong `qlib` distribution absent), release/image identity, PostgreSQL
backup, resources, healthcheck, Celery worker/beat and `1 node online` ping all passed. Local
TUI preflight passed `npm run check:tui`, 34 JavaScript tests, 44 focused Python metadata/
actionability/IA tests and the source guard (`12/24` screens, `430/889` actions, `0` violations).
All four push workflows for this commit (Fast Feedback, Consistency, Architecture and Security)
completed successfully.

The production browser regression found and then verified the real defect fixed by this commit:
deep-linked action forms could be rendered below the scrollable action panel after layout, so a
create/update row could appear present but could not be reached by a normal click. The workbench
now performs a post-layout form scroll/focus and the browser regression asserts viewport
visibility. With a unique run suffix, HTTPS Playwright completed all three final checks (`3
passed`): operator queue visibility versus regular-user denial, strategy create/detail/update/
readback, and user-owned AI-provider create/detail/update/readback. The provider API key was
entered only in the explicit browser `补填参数` dialog and never URL-prefilled.

The first short attempt used a reused date-only fixture suffix and exposed duplicate test data;
diagnostics showed the operator grid and provider detail eventually returned HTTP `200`. The
rerun used the unique suffix `R0820A01`, then exact owner/name cleanup removed the controlled
strategy/provider rows (including rows left by the failed/retry attempts); the post-cleanup query
returned zero matching rows for user id `6`. No password or secret is recorded here.

This is current-release HTTPS role/write/readback evidence, not a formal M5 candidate rebind: the
registry/readiness binding still names `f3881a04...` / release `20260820043710`. It does not prove
write-receipt/refresh audit, 14-day telemetry, registry backup/restore, live rollback,
capacity/chaos, external AgomTUI portability or owner/reviewer sign-off. TUX-02/TUX-04 and the
M5/TAR/AUD/EVID production gates remain fail-closed where those independent requirements are
still outstanding.
