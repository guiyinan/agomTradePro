# M5 observation 候选绑定简明指南

## 一句话说明

M5 observation 的绑定发生在本地仓库，不是 VPS、数据库或 GitHub 设置中。

候选与 retained sample 分两步绑定，入口脚本是：

```text
scripts/start_web_to_tui_observation.py
scripts/web_to_tui_retained_observation.py
```

最终绑定结果写入：

```text
config/tui/migration/web_to_tui_cutover_evidence.v1.json
```

其中 `candidate` 节点就是当前 M5 候选的唯一绑定记录。

```text
生产部署与探针 → deployment attestation → candidate 启动脚本
真实 retained sample → hash-bound checkpoint → retained 绑定脚本
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
| 首个真实 retained sample、精确 14 日 eligible instant | `docs/deployment/tui02-production-observation-checkpoint-*.json` |
| 14 日窗口和后续验收证据 | `config/tui/migration/web_to_tui_cutover_evidence.v1.json` |

因此，“绑定候选”不是写一个版本号，而是证明生产 release、源码 commit、OCI、迁移矩阵、TUI graph 和 runtime manifest 属于同一份候选快照。

## 标准操作

### 生产监控查询凭据

生产部署在任何容器移除、迁移或指针切换之前，校验 `$TARGET_DIR/prometheus-query-client.secret`
及服务端配置。客户端文件只含 `PROMETHEUS_QUERY_USER`、`PROMETHEUS_QUERY_PASSWORD`；服务端持久文件为
`$TARGET_DIR/prometheus-query.env`，只含用户名和 `PROMETHEUS_QUERY_PASSWORD_HASH`。两者及已有 release
副本必须为 root 所有、0600 的普通单链接文件；不能使用禁用后备账号、空值、重复字段或不匹配的密码。

若只有现有客户端文件，部署在 VPS 内存中派生 bcrypt，不轮换密码。该受控 VPS 的 host Python/libcrypt
必须支持 bcrypt，否则预检拒绝，不回退成弱哈希。密码要求 16 字符以上、UTF-8 不超过 bcrypt 的 72 字节，
不得含控制字符。密码和哈希不进入命令参数、日志、构建包或仓库。

验证备份后、移除容器之前，部署将服务端配置原子持久化到 release 外，并恢复新 release 与旧回滚 release
的 `deploy/prometheus-query.env`。hash 使用单引号保护 `$`，避免 Compose 展开；不得将它复制到公开输出。
compose 文件的 optional 设置仅兼容本地运行包，不意味着生产可以跳过认证预检。

既有 `--skip-predeploy-backup` 是独立的应急选项；本次 TUI-02 部署计划禁止使用。它不能因认证修复或测试环境身份而被隐式启用。

本地测试不代表生产认证已恢复。获准发布后还须只读核对活动配置及 HTTPS：匿名/错误凭据为 401，正确凭据
query/query_range 为 200 且结果有效，内部 up=1，9090 未公开；再确认真实迁移指标存在。不得用内部查询
绕过正式受保护的 retained checkpoint，也不得把空向量改写为零。

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

部署候选绑定后，从真实 Prometheus query-range 生成只读 checkpoint。先 dry-run，再写入 retained binding：

```powershell
$Checkpoint = "docs/deployment/tui02-production-observation-checkpoint-YYYY-MM-DD-<commit>.json"
python scripts/web_to_tui_retained_observation.py --checkpoint $Checkpoint
python scripts/web_to_tui_retained_observation.py --checkpoint $Checkpoint --write-evidence
```

retained 绑定器会核对 checkpoint SHA、candidate/release/image、target、rules、retention、storage、
authenticated query、Prometheus restart/window reset、backfill 和 synthetic zero。然后检查并提交绑定结果：

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

新窗口第一天通常仍会得到 `DENY`。只有 `retained_source=true` 且 detail 中的
`first_retained_sample_at` / `eligible_at` 与 checkpoint 一致，才表示精确时间门绑定成功；其余 UAT、
telemetry、缺陷窗口、回滚、备份恢复和 attestations 需要在观察期内继续积累。

## `--replace` 做了什么

切换到不同候选时，candidate 启动脚本必须显式使用 `--replace`。它会清空旧候选绑定的：

- UAT 与 route cleanup；
- P0/P1 缺陷窗口；
- production telemetry；
- rollback 与 registry backup；
- review snapshot 和 owner/reviewer 审批。

这是为了防止旧候选的生产证据被带到新候选。相同候选重复校验时会保留已经验证的 retained
binding。若同一候选的 Prometheus 重启或 retained source 改变，retained 绑定脚本的 `--replace` 只清空
defect、telemetry、post-window backup、review 和 approvals；仍绑定同一候选的 UAT/cleanup/rollback drill
不会被误删。

## 受控重启后的窗口重置

候选已经绑定 retained sample 后，如果发生受控 Web 重启，旧窗口必须作废，不能沿用旧 sample
或旧的 post-window 证据。先保存候选绑定的只读 reset artifact（必须包含同一 commit/release/image、
容器实际启动时间、health/ready=200、decision-ready=503 和旧 checkpoint 的 canonical SHA），再执行
dry-run：

```powershell
$ResetArtifact = "docs/deployment/tui02-production-observation-reset-<date>-<commit>.json"
python scripts/reset_web_to_tui_observation.py --reset-artifact $ResetArtifact
```

确认 `READY (dry-run)` 后才写入候选证据：

```powershell
python scripts/reset_web_to_tui_observation.py --reset-artifact $ResetArtifact --write-evidence
```

该操作只更新本地 candidate evidence：清除 retained window、observation end、缺陷/telemetry、
post-window backup、review 和 approvals；不会部署、重启、写数据库或启用 runtime。随后必须等待
重启后的首个真实 retained sample，并重新计算精确 14 日 eligible instant。

## 窗口如何计算

- 候选名义日期：deployment attestation 的 UTC 部署/验证日期；
- 真实起点：hash-bound checkpoint 中首个 retained raw sample 的 UTC timestamp；
- 精确终点：真实起点加 `1,209,600` 秒；
- telemetry 的 `collected_at` 和 defect 的 `queried_at` 必须使用 v2 UTC timestamp，日期字符串无效；
- 禁止用部署前时间回填；
- 候选 commit、OCI 或候选相关 P0/P1 修复发生变化时，应重新部署并重新绑定，窗口随之重置。

## 低频任务逐项验收（2026-10-18 获批）

Owner 已批准一次正式 14 天观察冻结例外，以及低频任务逐项验收与独立复核。现有 VPS 是测试/演示环境，
普通测试升级不以 Classic 退役或正式观察完成为前置；正式观察另明确目标、资格及冻结候选。测试升级如果
改变观察对象，真实重置或结束该轮，不追认旧时间。具体发布仍按当次用户授权和协调窗口操作。

统计足够的 v2 普通快照保留原门槛；旧式 `reason/owner/reviewer` 三字符串例外不再放行。新的逐项验收使用
`web-to-tui-production-telemetry-snapshot.v3`，执行结构契约统一由
`scripts/build_web_to_tui_production_telemetry.py` 校验，readiness 重建并精确比对该结果。
没有新增审批服务、业务数据库或另一份任务范围清单。

v3 在原快照上增加：

- `acceptance_wave_id`：本次验收适用的明确波次，不能用默认值替代单项范围。
- `collection.query_at`：真实 `retained_observation.eligible_at`。六条 approved query 请求都显式传
  Prometheus `time=<eligible instant>`，即使实际采集稍晚，也查询同一个完整 14 天窗口。
- `collection.raw_results`：`{evidence: repo_relative_path, sha256: raw_bytes_sha256}`，引用
  `web-to-tui-prometheus-results.v1`。该 JSON 携带完整 `candidate_binding`、`window_start/end`、实际
  `collected_at`、`query_at`、credential-free `endpoint`、原样 `queries` 和六项 `results`。
  results 是 Prometheus 原始 success/vector 响应；样本时间与 query_at 只容许毫秒精度差异。
- 逐 task 的六项计数必须与原始响应逐项相等。明确返回的 0 可以是 0；没有对应 series 的字段必须为
  JSON `null`。字段不能省略；不得把缺失改写为 0。全局采集故障不能被逐项例外覆盖。

低频记录的 `low_frequency_exception` 引用一个 hash-bound JSON，版本为
`web-to-tui-low-frequency-task-acceptance.v1`，包含：

- 完整 `candidate_binding`、精确 `task_key`、该 task 对应全部 `route_pages`、`wave_id`、具体 `reason`；
- `sample_status=insufficient_sample`、`error_comparison=not_applicable`，不能称作统计通过；
- `performed_by/performed_at`、`expires_at`；UAT 必须发生于候选发布后，实际采集后才可接受统计不足并复核，
  复核不晚于检查时刻，检查时记录不能过期；
- `owner={actor, risk_accepted: true, accepted_at}`；
- `reviewer={actor, approved: true, reviewed_at}`，reviewer 不能与 owner 或执行 UAT 者相同（忽略大小写和首尾空白）；
- `uat` 精确覆盖 `primary_task/clear_result/error_recovery/permission`。每项为
  `{passed: true, evidence: {evidence: repo_relative_path, sha256: raw_bytes_sha256}}`；证据必须真实存在、非空、
  位于仓库内且摘要匹配，可以引用同一份包含各项步骤和观察结果的实际 UAT 记录或截图。

每个低频任务仍须有真实 TUI 执行序列，观测到错误时拒绝，不能借低频掩盖故障。入口样本足够时仍检查
Classic 占比不超过 5%；普通统计仍检查两侧请求至少 20、错误数不超请求数、TUI 错误率增幅不超 0.5 个百分点。
builder 派生并保留样本状态、比较状态和真实计数；readiness 不接受修改后的结果投影。

上述姓名与会签字段是可审阅的人工证明，不是数字签名或身份认证。实际任务责任人、执行者与独立复核者
必须真实完成并确认记录，由最终 Owner 审阅；填入不同字符串不能代替实际会签。通用政策批准不等于所有任务
已通过验收。本次实现未生成任何实际任务的验收批准。

最终授权运行 `--require-allow` 时使用当前真实 UTC，不允许同时传 `--evaluated-at`；历史重放可单独指定时间，
不能作为当前切换授权。readiness 还从当前矩阵重建完整 catalog 并精确比对，不能保留 source hash 却删减任务。
旧候选、过期文件、错误哈希和未同步的 catalog 都应 DENY，而不是自动换绑或回填。

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
- retained checkpoint SHA、candidate/image 或任一 monitoring gate 不匹配；
- 最终 snapshot 只提供日期，或 timestamp 早于精确 14 日 eligible instant。

不要通过手工修改 JSON 绕过这些检查，也不要回填观察开始时间。

## 历史候选示例（非当前 binding）

以下是 2026-08-30/31 启动并复核的旧绑定，仅用于说明 checkpoint 格式。2026-09-02 的受控
web-only restart 已使该 retained window 作废；当前候选为 `aa7127ff4…` / release
`20260901232812`，需按 reset artifact 重新取得首个真实样本，不能继承以下时间：

- release：`20260830215638`；
- candidate commit：`80ea002bf910110621022a70e4f1ec5c1b704a56`；
- first retained sample：`2026-08-30T15:09:35.034000Z`；
- exact eligible instant：`2026-09-13T15:09:35.034000Z`；
- deployment attestation：`docs/deployment/web-to-tui-deployment-preflight-20260830215638.json`；
- retained checkpoint：`docs/deployment/tui02-production-observation-checkpoint-2026-08-31-80ea002b.json`。

查看 `web_to_tui_cutover_evidence.v1.json` 的 `candidate.binding`、`candidate.deployment_preflight` 和
`candidate.retained_observation`，即可核对完整绑定。
