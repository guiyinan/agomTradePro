# Release 36b72d2f 生产审核团队交接包

> 交接包 ID：closure-review-handoff-36b72d2f-20260830-v1  
> 候选 commit：36b72d2fc01604afdb15d236a1e91d082fb62a5b  
> release：20260830071422  
> image：sha256:09f6491440a4bc16934ac5544c793a0b5b9d22c8ec6f8ab35d61693b0121c94b  
> 状态：pre-execution review；本文件不是批准、签字或生产通过证明。

## 0. 个人项目单一所有者覆盖

本项目现由唯一真人项目所有者以
[`personal-project-single-owner-authorization-2026-08-30-36b72d2f.json`](personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)
（SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`）声明采用
`single_owner_personal_project`。该声明允许同一所有者承担 owner/approver/reviewer 的治理角色，
并以仓库内 owner receipt 代替多自然人、法律姓名、production account 和职责分离材料。下文对应要求
仅作为 team-mode 路径保留。

此覆盖不放宽技术门禁：候选/hash、真实 authority head、实际数据覆盖、retained telemetry、staging、
runtime manifest、业务定义、执行结果和观察时间仍必须真实存在。带匹配 sidecar、候选和明确
missing evidence 的 `DEFER` 可在单一所有者模式下入账；任何 `APPROVE` 仍须满足所选技术分支的全部
非人工字段。自动化是受委托执行者，不冒充另一名真人。

当前动态状态（晚于下文初始交接说明）：AUD/DATA 回传已作为真实 `DEFER` 入账；TUI owner 已确认
既有 UAT，`TUI-01=completed`。唯一所有者已选择新 collector 路径，`TUI-03` 的固定 digest
Prometheus、`21d/4GB` 留存、持久卷、真实 scrape target、M5 rules、health、packaging 和认证 HTTPS
read-query contract 已通过，证据 SHA-256=`8fda79136ae1a3a70afd22ce4b1134f69f5d4af44bd484786ea4fd2f9c9891a7`。
当前不再等待 TUI source 二选一；下一阶段只接收 clean successor 的真实 deployment/target-up/
retention/query/rollback evidence，再重置 14 日窗口。下文 TUI source 审核步骤保留为历史输入合同。

## 1. 请审核团队交付什么

请不要只回复“同意”“已审核”或“一并批准”。适当的审核输出是两份相互独立、逐阶段、有身份和
证据约束的机器可读决定：

1. AUD-03 / DATA-02 生产授权决定：
   - 使用
     aud03-data02-production-review-return-template-2026-08-30-36b72d2f.json；
   - 对 authority、runtime profile、只读 preflight、DATA-02 execute 四个阶段分别给出
     APPROVE、REJECT 或 DEFER；
   - 只批准尚未执行的精确动作，不得提前声明 DATA-02 exit gate 或 AUD-03 生产验收通过。
2. TUI M5 运营决定：
   - 使用
     tui-m5-operations-review-return-template-2026-08-30-36b72d2f.json；
   - 在“提供既有 retained Prometheus source”与“授权新 collector/retention 整改”中明确选择一个；
   - 当前只能批准 source 验证或整改实施。14 日窗口结束后的 telemetry、defect、正式 registry
     attestation 和 cutover 双签必须在真实窗口结束后另行形成，不能预签。

审核团队应把模板复制为新的 final return 文件，将 template_only 改为 false，填完所有获批分支的
必填字段。未审核、不可用或不适用字段保持 null；禁止用 TBD、N/A、unknown、test、admin、
placeholder 等字符串冒充值。

team mode 的每个 final return 文件还必须附：

- 审批系统中的真实 receipt/reference；
- receipt 原文或可复核导出件的 SHA-256；
- final JSON 文件自己的 SHA-256 sidecar；
- 如签名系统不直接签 JSON，须提供“签名文件 SHA-256 → final JSON SHA-256”的明确绑定。

时间一律使用带时区的 ISO-8601 UTC；SHA-256 一律为 64 位小写十六进制。回传材料不得包含密码、
token、cookie、API key、数据库连接串或其他秘密。

## 2. 审核前必须先核对的固定事实

### 2.1 候选不可漂移

审核决定必须精确绑定：

- commit：36b72d2fc01604afdb15d236a1e91d082fb62a5b
- release：20260830071422
- image：sha256:09f6491440a4bc16934ac5544c793a0b5b9d22c8ec6f8ab35d61693b0121c94b
- PostgreSQL alias：default

任一项不一致时，当前审核应输出 DEFER，要求重新生成候选绑定 preflight；不得把批准迁移到后继候选。

### 2.2 AUD/DATA 真源

- 审核源：
  aud03-data02-production-authorization-preflight-2026-08-30-36b72d2f.json
- SHA-256：
  25dc78fd5dfc627460761f7c7aa28c5fef08da8f3cd7ec8b62b81ac3665096d1
- active production profile：59c6575b-872f-43c8-bf20-95a50567eca3，version 2
- active snapshot：f96ceca1-9fb5-4321-9604-0d53da22aa9c
- profile/snapshot hash：
  af164c1ca395916276a5ff0990d699dbee2141a2a1b9e69f2258fbdf4474d80c
- 当前三张 exact authority reader 表均为零；不存在可由自动化推断的 selector。
- 当前 runtime loader 为 unavailable，第一阻断原因 mode_invalid。
- DATA-02 dry-run 没有生产写入；price eligible=0，stale/invalid=5,533。

### 2.3 TUI 真源

- source preflight：
  tui-m5-observation-source-preflight-2026-08-30-36b72d2f.json
- source preflight SHA-256：
  b8b22c64f260d5a2d43de78a2ee30d30637ea741203d3173b1b28fe6fc660bcf
- remediation preflight：
  tui-m5-monitoring-remediation-preflight-2026-08-30-36b72d2f.json
- remediation preflight SHA-256：
  c386ea4552df2af991c2ae824acbef79ccd7dc337bc139994145babdc89c1b76
- 公网 exporter 可读，但只是当前进程 counter，不是 14 日 retained query source。
- VPS 未发现 Prometheus-compatible retained store；外部 source 尚未提供。
- 当前记录窗口为 2026-08-29 至 2026-09-12，但 retention 未证明。
- readiness 为 5/10、总体 DENY；不得用瞬时 scrape、零值或 UAT counter 回填历史。

## 3. Work order A：AUD-03 / DATA-02

### A1. 审核身份模式

个人模式只校验第 0 节的 owner authorization；以下职责分离项仅适用于 team mode：

审核团队必须确认并输出：

- production owner 的真实姓名、生产账号标识、角色和组织；
- independent root approver 的真实姓名、生产账号标识、角色和组织；
- independent reviewer 的真实姓名、生产账号标识、角色和组织；
- root approver 与 reviewer 是不同自然人和不同生产身份；
- 三者对本次候选、authority scope 和 DATA-02 操作具有相应授权；
- 每人的批准 receipt/reference 与 receipt SHA-256。

聊天用户名、通用 admin、fixture user、Profile/session 推导结果和代理身份均不能作为上述身份。

### A2. 审核 Phase 1：真实 authority heads

必须检查：

- actor authority 与 owner/tenant scope authority 均由 Account 正式 Application/composition
  写入口产生或从已经存在的真实 current head 选择；
- 两个 source 都存在、未 supersede、在授权有效期内且为 exact current head；
- actor/user identity 一致，scope 与本次 production owner/tenant 精确匹配；
- source id、source version、content hash 与最终 selector 六字段逐字一致；
- content hash 为真实账本内容 hash，不是审核文档 hash或临时随机值。

必须输出：

- actor_source_id
- actor_source_version
- actor_content_hash
- scope_source_id
- scope_source_version
- scope_content_hash
- authority 发行/选择 receipt 及 SHA-256
- Phase 1 的 APPROVE、REJECT 或 DEFER

当前账本为零，因此在真实 authority 尚未由有权主体签发前，本阶段合适的结论只能是 DEFER，
不能为了解锁任务生成默认 root 或 selector。

### A3. 审核 Phase 2：forward runtime profile successor

必须决定并输出：

- audit.system_event.mode：只能选择 shadow 或 required；off 不能通过 writer preflight；
- audit.system_event.outbox_enabled：若允许 writer preflight，必须为 JSON boolean true；
- audit.system_event.authority_selector：必须等于 A2 的六字段；
- activation actor：真实生产身份；
- activation reason：说明候选、用途、授权单号和回滚约束；
- release_ref：必须为完整 commit
  36b72d2fc01604afdb15d236a1e91d082fb62a5b；
- 预计 successor version 必须大于 2；
- 只允许通过
  apps.config_center.application.runtime_public.activate_runtime_profile_patch
  发布高版本 successor；
- 回滚同样发布更高版本、完整值集的 successor，禁止原地 update/delete active profile。

审核团队不应替系统预先生成 profile id、snapshot id 或 snapshot hash；这些值必须由实际激活事务产生，
随后由只读验证复核。

### A4. 审核 Phase 3：只读 writer/authority preflight

Phase 1、Phase 2 实际完成后，允许自动化执行只读验证。审核输出应要求以下全部通过：

- active successor version 大于 2；
- carried-forward 值完整；
- profile/snapshot id、key、version 和重算 hash 一致；
- changed keys 精确为获批 patch；
- mode 不是 off；
- outbox_enabled 为 true；
- runtime、authority readers 与 DATA-02 使用 database alias default；
- exact current authority context 与 selector 一致；
- 验证过程不 claim、不发布、不消费 outbox row。

任何一项失败，Phase 4 自动保持未授权。

### A5. 审核 Phase 4：DATA-02 controlled execute

必须决定并输出：

- operator_identity：真实、可追责的 DATA-02 操作人；
- source_type：akshare 或 tushare；
- batch_size：1 至 500 的整数；
- 授权有效起止时间；
- 接受既有 rollback point：
  /opt/agomtradepro/backups/database/postgres-20260829T220625Z.dump
- rollback point SHA-256：
  434903ac03c4fd6e4623682c65628f6b3f7be533a279b53fa063d692470e3d95
- 明确认知 provider fact 会在最终四 Publication 事务之前分批写入；
- 同意失败时只对精确受影响事实做另行批准的 reconciliation/compensation，禁止 blanket delete；
- 不批准 freshness、时间戳、5,533 exact coverage、跨源 1% 默认容差或四 Publication 原子性豁免。

最终获批命令必须完整写入回传文件：

    python manage.py repair_active_a_share_current_facts --execute --operator <approved-operator> --source <approved-source> --batch-size <approved-1-through-500>

适当的 Phase 4 批准只授权一次精确候选、精确参数和精确窗口的执行。它不自动授权重试、删改、
容差变更、Publication rollback、数据库 restore、DATA-03 activation 或后继候选。

### A6. 执行后另行形成的验收，不得现在预签

执行后审核团队才可复核：

- 5,533 个资产 provider/observation/timestamp/coverage 全部通过；
- future、naive、stale、missing 和 tolerance breach 均为零；
- quote、price、valuation、financial 四个 immutable Publication id/hash；
- 四 Publication 在同一事务切换；
- partial fact checkpoint、失败标的、retry 和 compensation 记录；
- Audit event/outbox/delivery receipt 完整且无 duplicate/loss；
- rollback point 和回滚路径仍可用。

只有这些真实执行证据存在后，才可以另签 post-execution acceptance；pre-execution APPROVE 不能被
解释为 DATA-02 completed、AUD-03 completed 或 DATA-03 unlocked。

## 4. Work order B：TUI M5

### B1. 先做二选一运营决定

允许的 option 只有：

1. provide_existing_external_prometheus_source
2. authorize_repository_and_production_monitoring_remediation

若选择既有 source，必须输出：

- operations owner 与独立 reviewer 身份和 receipt；
- 不含凭据的 governed HTTPS query origin；
- retention proof 文件及 SHA-256；
- first retained sample 的真实 UTC 时间；
- 从 2026-08-29 起连续、无 gap 的 retention 证明；
- 时钟同步证明；
- 六条固定 PromQL 均可查询；
- 可导出无秘密、候选绑定的 101-task snapshot。

只要不能证明从原窗口起点连续留存，就不能保留当前窗口；应选择整改分支并接受重新计时。

若选择新 collector/retention 整改，必须输出：

- operations owner 与 independent reviewer 的真实身份和 receipt；
- 获批的 pinned Prometheus-compatible image digest；
- 大于完整 14 日查询窗口的 retention period；
- 有上限的 storage budget、volume 名称和容量告警；
- 非公网或明确受控的 query access policy；
- Alertmanager 是部署、对接既有服务还是显式保持 unavailable 的决定；
- 接受新增容器、持久卷、scrape 流量和磁盘增长；
- 接受先分配 bounded repository execution_focus，再单独审核部署；
- 接受 fresh candidate deployment/re-attestation；
- 接受 canonical starter 清空不可继承证据并从首个 retained sample 重置 14 日窗口。

### B2. role-owner 只确认已经发生的业务 UAT

真实 role owner 可以对 run tui01-36b72d2f-20260830-01 的业务结果作出 ACCEPT、REJECT 或 DEFER。
该确认只覆盖既有 10/10、108/108、三角色和两条写回执对应的业务可用性，不等于 14 日 telemetry、
defect、registry attestation 或最终 cutover approval。

### B3. 观察结束后另行终审

最终 TUI 审核只能在有效窗口自然结束后进行，并必须绑定同一候选或明确的新候选：

- 六条固定 PromQL；
- 精确 101 task coverage；
- 每个 task 的 Classic/TUI 最小样本；
- Classic 比例与错误率回退门；
- 完整窗口 P0/P1 defect snapshot；
- payload-free production registry attestation；
- isolated/live rollback 适用证据；
- owner 与独立 reviewer 对同一 review snapshot 的双签。

如果选择整改并重置窗口，2026-09-12 不再是有效结束日；必须使用 canonical starter 实际写出的新窗口。
日历到期本身不构成通过。

## 5. 审核结论判定

每个 phase 只允许：

- APPROVE：所有获批技术分支字段和约束完整，并带个人 owner authorization 或完整 team 身份/receipt；
- REJECT：审核认为动作不应执行，并给出稳定理由；
- DEFER：仍缺真实输入、证据、职责分离或外部状态。

以下情况必须为 DEFER 或 REJECT：

- 只给泛化“审批”或“A1-A8 全部同意”；
- team mode 的身份、生产账号、角色或 receipt 缺失，或 personal mode 的 owner authorization 缺失；
- root approver 与 reviewer 为同一身份；
- authority head 为零、非 current 或 hash 不匹配；
- 试图用默认值、fixture、聊天身份或自动生成值补 authority；
- 候选 commit/release/image 漂移；
- 未接受 partial fact 风险与精确 rollback point；
- TUI retained source、retention、时钟或窗口连续性不可证明；
- 试图预签尚未发生的执行结果、14 日观察或最终 cutover。

## 6. 回传文件建议

建议审核团队返回：

- aud03-data02-production-review-return-<decision_id>.json
- aud03-data02-production-review-return-<decision_id>.json.sha256
- tui-m5-operations-review-return-<decision_id>.json
- tui-m5-operations-review-return-<decision_id>.json.sha256
- 每个外部审批 receipt/export 及其 SHA-256 sidecar

收到后，自动化先验证 JSON、SHA、候选绑定、owner-or-team identity contract 和账本 current head。通过这些只读检查后，
仍按 Phase 1 → Phase 2 → Phase 3 → Phase 4 逐项请求/执行，不把回传文件解释为无限期或跨候选授权。
