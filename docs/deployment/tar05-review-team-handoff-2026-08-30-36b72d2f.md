# TAR-05 Terminal Runtime 审核团队交接

> 候选 commit：`36b72d2fc01604afdb15d236a1e91d082fb62a5b`  
> release：`20260830071422`  
> image：`sha256:09f6491440a4bc16934ac5544c793a0b5b9d22c8ec6f8ab35d61693b0121c94b`  
> 当前结论：最终候选没有 1/5/10/20 容量、chaos、真实 provider/MCP、production canary、观察窗口或双签证据；queued runtime 与容量提升继续 fail-closed。

## 0. 个人项目单一所有者覆盖

候选绑定的
[`personal-project-single-owner-authorization-2026-08-30-36b72d2f.json`](personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)
（SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`）允许唯一项目所有者承担
Operations/Product/QA/Operator/Rollback 的治理角色，不再要求制造多名自然人或 production account。
下文多角色身份和职责分离要求只适用于 team mode。

环境、runtime manifest/flags、专用 Worker/resources、traffic/fault/cost/duration envelope、19 项 hard
SLO、真实 provider/MCP、canary 和 retained observation 仍不可豁免。缺少这些事实的候选绑定报告可以
作为有效 `DEFER` 入账，但不能变成 load、fault、model、flag、canary 或 rollout 授权。

当前动态状态（晚于下文初始交接说明）：TAR05-P1 回传已通过候选/sidecar/缺失事实校验并作为真实
`DEFER` 入账；不再因 Operations/Product/QA 由同一 owner 承担而拒收。staging、最终 runtime
manifest/flags/resources、专用 Worker、retained metrics 和 provider/MCP profile 仍缺，因此 P2–P7
没有解锁。下一步由唯一 owner 定义一个真实 staging envelope 后再运行 P1/P2；不得把当前 DEFER
解释为 load、chaos、model、canary 或 rollout 授权。

本交接要求提供真实环境、边界和逐阶段决定；个人模式使用 owner authorization，team mode 另提供身份。
它不要求审核方直接修改生产
flag、启动 Worker、生成负载、注入故障或执行 rollback。泛化“全部同意”不能执行；每次 final
report 只能决定当前依赖已满足的 phase，尚未发生的结果必须保持 `null` 或 `DEFER`。

## 1. 先核对材料

- TAR-05 候选绑定 preflight：
  `tar05-production-authorization-preflight-2026-08-30-36b72d2f.json`
  - SHA-256：`0e07657152230a52e431e76d899d1527588f7556a3146d8b247a78ac54ea9ed6`
- 审核回传模板：
  `tar05-operations-review-return-template-2026-08-30-36b72d2f.json`
  - SHA-256：`06c71dc80c8196e0273a8eca77be5f91ba2fa3f024464376fb573dc5b5276b3f`
- Terminal Runtime 机器合同：
  `governance/terminal_agent_runtime_contracts.json`
  - SHA-256：`55f5e975b79fd16f673e6ebff516e60ffcd27d5a61b3a63a0af1b852deeb5f3c`
  - canonical matrix digest：`6272ea6606ebbf3c0791e48d807b733cbc6d9a4ce7d945d95c5e3a16c22aea64`

最终 release identity 已有候选绑定部署证据；但部署报告只显示 Web、通用 Celery worker/beat、
PostgreSQL、Redis 等基础服务，没有发现专用 Terminal Agent Worker。最终候选的 runtime manifest
digest、完整 flag snapshot、真实 staging、provider/MCP profile、retained metrics source 仍须由
Operations 提供并重新 attestation。

旧的 `71e62773…` 生产 capacity artifact 只证明历史候选曾在受控窗口接收 `4`、拒绝 `32` 个请求并
恢复安全 flag；它不能跨候选复用，也不满足当前 hard SLO、真实 provider、chaos 或观察窗口。

## 2. 当前可审核项：P1 环境与候选

当前 dynamic checklist 只有 `TAR05-P1-ENVIRONMENT-CANDIDATE` 可接收正式报告。审核团队必须提供：

- 真实 Operations owner、Product owner、QA/Security reviewer、bounded operator、rollback owner；
- 每人的真实姓名、组织、角色、production account、identity receipt 与 SHA-256；
- Operations owner、operator、QA/Security reviewer 的职责分离证明；
- 已批准的 staging environment identity、隔离属性和无秘密 access receipt；
- 精确 commit/release/image、重新计算的 runtime manifest digest 与固定 matrix digest；
- Web、专用 Worker、Redis、PostgreSQL 的资源/隔离 manifest；
- 当前 flag snapshot，以及 dedicated Terminal Worker 是否真实存在；
- provider/model profile 与 MCP registry 的身份/hash，不得包含 credential；
- request、duration、model-call、token、cost 和 retention 上限；
- stop owner、rollback owner 和授权有效期。

P1 批准后只允许只读环境/候选 re-attestation。它不授权 load、fault、外部模型调用或生产 flag
变更。P1 证据完成并由治理流程验证后，才允许分别审核 P2 和 P3。

## 3. 后续阶段

### P2：staging 1/5/10/20 capacity 与 soak

必须单独批准真实 staging、四档并发、样本数、warmup、measurement、soak、最大请求和费用预算。
输出必须包含全部 baseline metrics、全部 `19` 项 hard SLO、普通 Web baseline/loaded 对比、queue/
fairness/idempotency/isolation、Worker/Redis/PostgreSQL/Web/provider/MCP timelines，以及 raw snapshot、
recorder artifact 和 sidecar。任何 unavailable 或阈值超限都保持 BLOCK。

### P3：staging chaos/recovery

以下场景逐项决定，不得以一个通用 chaos 批准代替：Redis down/restart、broker message loss 与
reconciliation、Worker SIGTERM、Worker SIGKILL、model 429/5xx/timeout、MCP timeout、SSE
disconnect/reconnect、Web restart、deployment drain。每项必须有 fault envelope、stop condition、
rollback action、单调 UTC timeline 和恢复/重复/泄漏 counters。本阶段不授权 production fault。

### P4：真实 provider/MCP 与角色 UAT

只有 P2/P3 通过后才能审核。必须给出 provider/model profile、MCP registry digest、tool allowlist、
role accounts、owner-scoped test data、proposal/approval policy，以及 model calls/tokens/cost 上限。
要求 provider/MCP 成功与失败路径、审批恢复、角色生命周期、费用/审计对账和 secret occurrences=0。
本阶段不授权 production canary 或 live trading。

### P5：production staff canary

只有 P4 与 `TUI-01` 真实完成后才能审核。必须绑定重新 attested 的生产候选、命名 staff accounts、
流量/并发/run/时长/费用上限、精确 flag values、专用 Worker、queue limits、recovery point、监控
origin/retention、停止条件、drain 与 rollback receipt。安全回滚目标固定为 queued intake/worker/runtime
authorization 关闭、legacy inline 保留且 concurrency=`1`。不得删除 durable run/timeline/proposal/
approval/audit ledger。

### P6：观察、一般用户与 inline 退役

必须等真实 canary 和完整 retained observation window 自然结束后再审核。报告需包含同候选 capacity、
chaos、provider/MCP UAT、canary、defect/incident、费用/审计、restore/rollback 与 Operations/Product/
QA-Security sign-off。一般用户 rollout 与 legacy inline retirement 是两个后置决定，不能预签。

## 4. 回传文件

不要覆盖模板。复制为：

- `tar05-operations-review-return-<decision_id>.json`
- `tar05-operations-review-return-<decision_id>.json.sha256`

将 final report 返回：

    docs/reviews/release-36b72d2f/reports/terminal-runtime/

每份 final JSON 必须设 `template_only=false`、精确绑定候选并附同名 SHA-256 sidecar。个人模式引用第 0
节 owner authorization；team mode 填写 identity/account/receipt/有效期。一次报告只
决定当前 dependency-ready phase；后续 phase 保持 `null` 或 `DEFER`。

## 5. 禁止事项

- 不使用 `TBD`、`N/A`、`unknown`、`test`、`admin` 或 placeholder 冒充值；
- 不把本地 load/chaos 测试、旧候选 artifact、瞬时 scrape 或零值当作最终容量/观察证据；
- 不在报告中放密码、token、cookie、provider key、连接串或秘密 URL 参数；
- 不跨候选拼接 capacity、chaos、UAT、canary 或 telemetry；
- 不预签 production flag、fault、rollback、一般用户 rollout 或 inline retirement；
- 不直接修改 dynamic checklist、active registry 或生产配置；
- 不清除 global decision/execution deny，不提升 inline concurrency。

报告进入目录本身不等于授权。项目治理流程必须先校验 JSON/schema、sidecar、候选、owner-or-team
identity contract、phase 依赖、bounded envelope 和无秘密要求，才允许更新对应 work order。
