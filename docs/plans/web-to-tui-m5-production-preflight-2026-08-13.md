# Web → TUI M5 生产 Preflight（2026-08-13）

## 结论

本次只读核查确认公开 health/ready 正常，且生产 release 已不是 2026-07-28 文档记录的旧批次；但是当前运行镜像的 OCI revision 为 `unknown`，release 目录也不包含 `.git` 或可识别的 source manifest。因此无法把运行镜像绑定到当前候选 commit，不能生成结构化 deployment attestation，也不能启动或回填 14 日观察窗口。M5 继续保持 `DENY`。

## 核查范围

- 核查时间：`2026-08-13T01:14:05+08:00`
- 生产入口：`https://demo.agomtrade.pro`
- 方法：公开 HTTP 探针；通过现有受控 SSH 连接执行只读 `readlink`、`find`、`docker compose ps` 与 `docker inspect`
- 变更边界：未部署、未重启、未写 registry、未修改远端文件或数据库
- 安全边界：本文不记录主机地址、凭据、Token、容器 ID 或响应正文；响应仅记录状态与 SHA-256

## 当前生产快照

| 检查项 | 观察结果 | 判定 |
|---|---|---|
| `GET /api/health/` | HTTP 200，`status=ok`；response SHA-256 `a33a88bc785e83187356bc4b5a0cb8186dba3c638016f9463daa81cad883e009` | 健康 |
| `GET /api/ready/` | HTTP 200，`status=ok`；response SHA-256 `ce8906de6d4b52647e0497830e9562e8e4c031eb4132b7cc520b3b3c46e8a984` | 就绪 |
| 当前 release | `/opt/agomtradepro/releases/source-20260813002655` | 证明 7 月 28 日快照已过时；不证明源码身份 |
| Web image tag | `agomtradepro-web:20260813002655` | 与 release 批次一致 |
| Web image ID | 已由 `docker inspect` 取得，但不写入叙事文档 | 仅本机运行身份；不等于源码 commit |
| OCI revision label | `unknown` | **失败：无法绑定 candidate commit** |
| release source identity | release 目录不是 Git worktree；未发现可识别 release/source manifest | **失败：无法独立还原源码 commit** |

## 与历史证据的关系

- `web-to-tui-m5-production-preflight-2026-07-28.md` 是当日真实快照，应保留；其中“生产仍运行 2e399607”不能继续作为当前事实。
- `../development/vps-uat-e2e-findings-2026-07-31.md` 已记录 release `20260731084347` 与源码 `491b0b20…`，证明历史上曾部署过包含 M5 专项测试的版本；该历史发布没有绑定到当前 cutover candidate，也不得反向回填观察窗口。
- 当前 release `20260813002655` 更新于上述两份历史记录之后，但 OCI/source identity 失真，所以仍不满足 `web-to-tui-production-deployment-preflight.v1`。

## 后续阻断项

1. 发布流程必须写入完整 `org.opencontainers.image.revision`，且值与部署的 40 位源码 commit 一致；禁止 `unknown`。
2. release 应包含无秘密、不可变的 source/release manifest，记录 release ID、完整 commit、image ID/revision 与生成时间，供独立核验。
3. 修复发布 provenance 后，需要重新部署一个干净最终候选，并在部署后 30 分钟内重新取得 health/ready 与 OCI/source identity 的结构化 attestation。
4. 观察窗口只能从新证明的 `verified_at` 开始；本文件和 7 月 31 日历史发布均不能用作回填依据。

## 2026-08-13 仓库整改进展

发布工具的 provenance 缺口已在本地代码中关闭，但尚未部署到生产：

- source-upload 模式现在要求工作树完全干净，并拒绝缺失、缩写、大小写不规范或 `unknown` 的源码 commit；git-clone 模式也会锁定调用方给出的完整 commit，并在 clone 后精确复核。
- 两种构建模式都会核对镜像 `org.opencontainers.image.revision` 与源码 commit，并生成只读、字段白名单的 `.agom-release-manifest.json`。
- deploy 在启动 compose 服务或切换 `current` 前核验 manifest 文件类型/权限、release tag、完整 commit、image tag/ID、OCI revision、构建时间和 source mode；部署报告继续保留同一完整身份。
- 相关本地回归 `44 passed`，strict mypy、Black、isort、compileall、生成 shell 的 `sh -n` 与 diff check 均通过；Ruff 在当前环境未安装。

这一步只证明下一次发布能够 fail closed 地形成候选溯源，不改变上文当前生产快照。当前线上 OCI revision 仍是 `unknown`，也没有合格 manifest；在获得发布授权、部署干净候选并重新取得结构化 preflight 前，M5 仍为 `DENY`。

## 2026-08-14 本地验证器收口

`scripts/deploy_vps_verify.py` 现已与 source-upload/git-clone 两种发布模式的只读 `.agom-release-manifest.json` 身份合同对齐：身份检查要求普通 `0444` manifest，并严格核验字段集合、源码 commit、OCI revision 与镜像 ID；不再以 release 目录中的 Git worktree 作为 fallback。发布脚本本身继续在构建/部署阶段核验 release/image 标识、构建时间和 source mode。`tests/unit/test_deploy_vps_verify.py` 与 `tests/unit/test_remote_build_deploy_vps.py` 合计 `50 passed`，增量 mypy 通过。

这仍只是下一次发布的本地 fail-closed 能力，不是生产证明。当前线上仍为 `revision=unknown` 且无合格 manifest；未执行部署、未生成新的 production attestation，M5 观察窗口仍未开始并继续 `DENY`。

## 2026-08-15 候选部署复核

上述 8 月 13 日快照和上一候选 `304ce86baa9177cfec27ae59fffb477c2d7ac5dc` 保留为历史事实。随后已部署后续候选 `dev/next-development@96ce6ee43b06e6eb6ad51528ff8ee783a4bf0952`，并在部署后重新取得可独立核对的 release manifest、image ID 与 OCI revision：

- release tag `20260815144517`，current 为 `/opt/agomtradepro/releases/source-20260815144517`；image ID 为 `sha256:38c68ff15ed4ce09a0a29b15744ac46c5287a5817f418d97666d96a81ad37839`，OCI revision 与 commit 完全一致。
- `/api/health/` 返回 `status=ok`；web、Celery worker/beat、PostgreSQL、Redis、Caddy 均通过部署后运行检查；Qlib 为 `0.9.7`。
- `account` migration `0037`–`0053`、canonical schema、`check --deploy` 和 TUI registry publish/check 均通过；TUI registry `21` 的 active source hash 与 expected hash 一致。
- 部署前 PostgreSQL custom-format 备份已生成：`postgres-20260815-085317.dump`，140079790 bytes，SHA-256 `f72ea2cff4ff2c137425069a404936e6d24ed8a301533f49bdea943d0334535e`。

详细结构化记录见 [`docs/deployment/vps-deployment-evidence-2026-08-15.md`](../deployment/vps-deployment-evidence-2026-08-15.md)。本次使用标准 `git-clone` 构建并独立验证 `pyqlib=0.9.7`；TUI AI provider failure guidance 修复已随该 release 部署。该证据仍不替代角色化浏览器 UAT、写后回执、14 日观察和 restore/rebuild 演练。因此 M5 仍保持 `DENY`，观察窗口只允许从本次 verified_at 之后开始，不能回填历史窗口。

### 2026-08-15 后续候选：AUD-01 fail-closed 修复

随后候选 `dev/next-development@a76db97d4322fd7f6a2323f4f567873e8c53199c` 已完成同样的
标准 `git-clone` 代码-only upgrade 部署：release `20260815152834`，image
`agomtradepro-web:20260815152834`，image ID
`sha256:12c5ce84ecd2d072846bb7777e6e0345e3ed83e98333bdf80ca35108d2a5c385`，OCI/source
revision 完全一致。HTTPS health/ready、容器、迁移、canonical schema、TUI registry、
Qlib/Celery 复核通过；ready 仍有 Alpha/Qlib 与 workspace freshness warnings。

本候选只替换了可复核的部署身份并携带 AUD-01 本地合同加固，不改变 M5 判定：角色化
浏览器 UAT、写后 receipt/refresh、14 日观察、cleanup/rollback 双签仍缺，M5 继续
`DENY`。详细备份与运行证据见部署证据文档的“后续候选部署”节。

### 2026-08-15 当前候选：`cf68dc1e9` / release `20260815182857`

当前 `dev/next-development` 已再次完成标准 `git-clone` 代码-only upgrade 部署，release
manifest、OCI revision 与 source commit `cf68dc1e972ecd6e0ae002e4d4f96ff07ef86542` 完全一致，
image ID 为 `sha256:e04018272c08ef2dec2ffa98619e99ad689649c06da5964cbe93a9493602a552`。部署后
HTTPS `/api/health/` 与 `/api/ready/` 均 HTTP 200，web/Celery/PostgreSQL/Redis/RSSHub/Caddy、
TUI registry、canonical schema、migrations、Qlib 与 Celery ping 复核通过；详细报告见
[`docs/deployment/vps-deployment-evidence-2026-08-15.md`](../deployment/vps-deployment-evidence-2026-08-15.md)
及 `dist/remote-build-reports/remote-build-report-20260815182857.json`。

`/api/ready/` 仍保留 Alpha/Qlib degraded、workspace recommendation stale 和 market
thermometer partial-stale warnings；本次只更新候选身份与运行证据，不启动 M5 角色化浏览器
UAT、14 日观察或 cleanup/rollback 双签，也不解除 AUD-01、DATA-01 等生产门禁。

### 2026-08-15 当前候选：`11594964f` / release `20260815200756`

当前 `dev/next-development` 已再次以标准 `git-clone`、`fresh`、code-only 模式部署，
远端数据卷保留且 Celery enabled。release manifest、OCI revision 与 source commit
`11594964f589c5f0ec3bf6a541d61d471b79b67f` 完全一致；image ID 为
`sha256:2983bd567f4cb86a52ce48d7a1c3f2162fec4cddbaddb007975375b9448052af`。
部署后从 VPS 独立复核 HTTPS health/ready 均 HTTP 200，容器、迁移、canonical schema、
TUI registry、Qlib 和 Celery 检查通过；部署前 PostgreSQL 备份为
`postgres-20260815-141446.dump`。详细报告见部署证据文档及
`dist/remote-build-reports/remote-build-report-20260815200756.json`。

`/api/ready/` 仍报告 Alpha/Qlib provider degraded、workspace recommendation stale、
Alpha rank source stale 与 market thermometer partial-stale；本次只更新候选身份与运行证据，
不启动角色化浏览器 UAT、写后回执、14 日观察或 cleanup/rollback 双签，也不解除 EVID-01、
AUD-01、DATA-01 等生产门禁。

### 2026-08-15 本地角色边界回归

在 disposable SQLite 与 `core.settings.playwright` 下运行
`tests/playwright/tests/uat/test_web_to_tui_m5.py::test_operator_group_can_open_queue_but_regular_user_cannot`：
`1 passed`。该回归证明 operator 可进入 AI 任务队列而普通用户不可见；它是本地浏览器/权限边界
证据，不是 VPS 角色账号、写入回执、人工审批或生产 M5 UAT。候选生产角色化浏览器验证、写后
receipt/refresh、14 日观察和双签门禁继续保持 `DENY`。
