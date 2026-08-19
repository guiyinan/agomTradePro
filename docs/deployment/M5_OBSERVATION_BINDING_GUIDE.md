# M5 observation 候选绑定简明指南

## 一句话说明

M5 observation 的绑定发生在本地仓库，不是 VPS、数据库或 GitHub 设置中。

入口脚本是：

```text
scripts/start_web_to_tui_observation.py
```

最终绑定结果写入：

```text
config/tui/migration/web_to_tui_cutover_evidence.v1.json
```

其中 `candidate` 节点就是当前 M5 候选的唯一绑定记录。

```text
生产部署与探针 → deployment attestation → observation 启动脚本
                                           ↓
                         web_to_tui_cutover_evidence.v1.json
                                           ↓
                              M5 readiness 逐门禁检查
```

## 绑定了什么

脚本把下面几类证据锁定为同一个候选：

| 内容 | 来源 |
| --- | --- |
| 生产 release、完整 commit、OCI image、health/ready 摘要 | `docs/deployment/web-to-tui-deployment-preflight-<release>.json` |
| Web→TUI 迁移范围 | `docs/plans/web-to-tui-migration-matrix-2026-07-25.csv` |
| 已发布 TUI graph | `config/tui/published/tui_operation_graph.published.json` |
| TUI runtime 版本和构建摘要 | `config/tui/agomtui-runtime.manifest.json` |
| 14 日窗口和后续验收证据 | `config/tui/migration/web_to_tui_cutover_evidence.v1.json` |

因此，“绑定候选”不是写一个版本号，而是证明生产 release、源码 commit、OCI、迁移矩阵、TUI graph 和 runtime manifest 属于同一份候选快照。

## 标准操作

前提是新候选已经部署，生产 `health`、`ready` 都成功，并已生成且提交 deployment attestation。工作树必须干净。

先执行 dry-run，只检查，不写文件：

```powershell
$ReleaseId = "YYYYMMDDHHMMSS"
python scripts/start_web_to_tui_observation.py --deployment-attestation "docs/deployment/web-to-tui-deployment-preflight-$ReleaseId.json" --replace
```

看到 `READY (dry-run)` 后，再正式写入：

```powershell
python scripts/start_web_to_tui_observation.py --deployment-attestation "docs/deployment/web-to-tui-deployment-preflight-$ReleaseId.json" --replace --write
```

然后检查并提交绑定结果：

```powershell
git diff -- config/tui/migration/web_to_tui_cutover_evidence.v1.json
git add -- config/tui/migration/web_to_tui_cutover_evidence.v1.json
git commit -m "docs: start M5 candidate observation"
git push origin dev/next-development
```

最后运行门禁：

```powershell
python scripts/check_web_to_tui_cutover_readiness.py --json
```

新窗口第一天通常仍会得到 `DENY`。只要 `source_consistency` 通过、候选身份正确、窗口日期正确，就表示“绑定成功”；其余 UAT、telemetry、缺陷窗口、回滚、备份恢复和双签需要在观察期内继续积累。

## `--replace` 做了什么

切换到不同候选时必须显式使用 `--replace`。它会清空旧候选绑定的：

- UAT 与 route cleanup；
- P0/P1 缺陷窗口；
- production telemetry；
- rollback 与 registry backup；
- review snapshot 和 owner/reviewer 审批。

这是为了防止旧候选的生产证据被带到新候选。相同候选重复校验时不需要依靠 `--replace` 重置证据。

## 窗口如何计算

- 起点：deployment attestation 中 `verified_at` 的 UTC 日期；
- 终点：起点加 14 天；
- 禁止用部署前时间回填；
- 候选 commit、OCI 或候选相关 P0/P1 修复发生变化时，应重新部署并重新绑定，窗口随之重置。

## 脚本会拒绝哪些情况

- deployment attestation 尚未提交，或当前文件与 `HEAD` 中内容不同；
- 工作树不干净；
- 生产部署已超过 24 小时；
- health/readiness 或 attestation 验证时间已超过 30 分钟；
- health/readiness 不能同时满足 HTTP 200 和 `status=ok`；
- OCI revision 与生产 source commit 不一致；
- 候选 commit 不在当前分支历史中；
- 候选中的 matrix、graph 或 runtime manifest 与当前文件不一致；
- 已绑定另一个候选，但没有提供 `--replace`。

不要通过手工修改 JSON 绕过这些检查，也不要回填观察开始时间。

## 当前候选示例

2026-08-19 启动的当前绑定为：

- release：`20260819195103`；
- candidate commit：`0ad5df129fbc5d0d6c3030287a0a88c83b6ae871`；
- observation：`2026-08-19` 至 `2026-09-02`；
- deployment attestation：`docs/deployment/web-to-tui-deployment-preflight-20260819195103.json`。

查看 `web_to_tui_cutover_evidence.v1.json` 的 `candidate.binding` 和 `candidate.deployment_preflight`，即可核对完整绑定。
