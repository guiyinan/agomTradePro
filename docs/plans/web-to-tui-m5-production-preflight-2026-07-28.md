# Web → TUI M5 生产 Preflight（2026-07-28）

## 结论

本次只读核查确认生产服务健康，但生产环境**尚未部署 Web → TUI M5 候选版本**。
因此不能启动或回填 14 日观察窗口，也不能把本文件用作
`stable_version_window`、`production_telemetry`、`production_registry_backup` 或
`cutover_approvals` 的放行证据。M5 继续保持 `DENY`。

## 核查范围

- 核查时间：`2026-07-28T14:46:27+08:00`
- 生产入口：`https://demo.agomtrade.pro`
- 方法：公开 HTTP 探针，以及通过 SSH 执行的只读 `readlink`、`git`、`docker ps` 和
  `docker inspect` 查询
- 变更边界：未部署代码、未重启服务、未写 registry、未读取或保存 registry payload，
  未修改任何远端文件或数据库
- 安全边界：本文件不记录主机地址、认证凭据、Token 或其他秘密值

## 生产状态快照

| 检查项 | 观察结果 | 判定 |
|---|---|---|
| `GET /api/health/` | HTTP 200，`status=ok` | 健康 |
| `GET /api/ready/` | HTTP 200，数据库、Redis、Celery、关键数据与决策数据检查返回 `ok` | 就绪 |
| 未认证 registry 请求 | HTTP 403，返回“身份认证信息未提供” | 认证边界符合预期；不证明 registry 备份或 active metadata |
| 当前 release | `/opt/agomtradepro/releases/source-20260721222254` | 仍为 2026-07-21 发布批次 |
| 部署分支 | `dev/next-development` | 不是当前 M5 开发分支 |
| 部署 commit | `2e399607977fea260436992952fae64565153213` | 不是已选定的 M5 候选 |
| commit 时间与主题 | `2026-07-21T22:21:52+08:00`；`fix: harden nightly valuation refresh` | 早于本轮 M5 实现 |
| Web image | `agomtradepro-web:20260721222254` | 与 release 批次一致 |
| OCI revision label | `2e399607977fea260436992952fae64565153213` | 与部署 commit 一致 |
| 容器状态 | Web、PostgreSQL、Redis、RSSHub 为 healthy；Caddy、Celery worker/beat 与 runtime namespace 均为 Up | 运行面正常 |

## 与本地 M5 实现的比较

核查时本地分支为 `dev/feat-tui-design-review-implementation`，HEAD 为
`03d815ac60234b3fdc6c4677c87799f671bba92e`，相对其远端跟踪分支领先 3 个提交。
生产 commit `2e399607…` 虽然是该本地 HEAD 的祖先，但其 Git tree 中不存在
`docs/plans/web-to-tui-migration-matrix-2026-07-25.csv`。它无法满足候选 commit
必须包含当前精确迁移矩阵的 `source_consistency` 约束。

本地 HEAD 仅用于说明核查时的实现基线，不等于已经选定、推送或部署的稳定候选。
本文件生成后 HEAD 还会因文档提交变化，真正候选必须在发布时重新记录完整 commit。

## 对 M5 的影响

1. `2026-07-26` 只能保留为历史上的预定基线，不能作为当前候选的有效 `released_at`。
2. 14 日窗口只能从真实 M5 候选成功部署并经 release owner 确认后，由
   `start_web_to_tui_observation.py` 绑定；禁止追溯或回填。
3. 当前生产健康只证明发布前基础设施可用，不证明 101 个可比较任务已产生候选窗口样本。
4. 未认证 registry 403 只证明访问控制工作，不替代生产 registry bundle、sidecar、
   generation/hash、恢复 dry-run 与 payload-free attestation。
5. 在候选部署前，不得生成候选缺陷窗口、生产遥测证据、最终 review snapshot 或人工审批。

## 后续授权点

仓库内实现和取证工具已经就绪。下一步需要 release owner 明确选定候选版本，并授权按正式
发布流程推送和部署该完整 commit。部署核验通过后，才可先 dry-run、再显式写入观察窗口。
本次只读核查不包含该授权，也未替用户作出发布决定。
