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
