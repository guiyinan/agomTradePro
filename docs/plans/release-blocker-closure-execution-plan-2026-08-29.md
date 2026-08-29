# 发布阻塞清零综合实施方案（2026-08-29）

> 状态：执行中；`DATA-01` 已关闭，`DATA-02` 候选实现待部署与生产执行，决策总闸仍保持 `blocked`
> 机器状态真源：`governance/active_plan_registry.json`
> 适用 closure units：`DATA-01/02/03`、`AUD-03`、`EVID-01/02/03`、`STRAT-01/02/03`、`TUI-01/02`、`TAR-05`、`AI-01`、`QMT-01/02`
> 原则：本文只编排既有 unit，不建立第二套状态、不降低阈值、不代签、不伪造 PIT/OOS 历史，也不把生产写入授权扩大为实盘交易授权。
> 授权记录（2026-08-30）：用户已授权 A1–A8 动作包继续执行；每个动作仍受其前置门、精确目标、回滚点、外部环境和真实 owner/reviewer 决策约束，授权不等于验收通过。

## 1. 目标与完成口径

本方案把当前“可用但降级”和“部署后仍硬阻断”拆成七条可独立验收的执行轨。整体完成必须同时满足：

1. 最终不可变候选完成 TUI 三角色生产 UAT、108/108 route-page、同 run 写回执、readback 与精确零残留 cleanup；`TUI-01` 关闭，`TUI-02` 的 14 日窗口随后按真实时间完成。
2. 活跃 A 股 canonical quote、price、valuation、financial Publication 覆盖和历史深度达到治理合同，provider freshness 与决策数据均明确为 `ok`；持久化决策门只在其他严格检查全绿后切到 `active`，`/api/decision-ready/` 返回 `200`。
3. 行情 stale 时模拟交易继续禁止发布可信估值；决策数据恢复后重新估值并保留 source observation time。
4. 13 张 authority/evidence 表不再 zero-seed，真实 owner/root/reviewer、append-only approval/current-head、撤销和 rollback 均有 PostgreSQL 证据；随后才启动 `EVID-03`。
5. R1–R8 的 owner definition、policy、calendar、scope、qualification 与样本窗口来自命名业务 owner；真实 PIT/OOS receipts 完成后才 Promotion 和 consumer UAT。
6. AUD-03 完成 migration/rollback、告警、恢复、管理员 TUI、archive/restore 和双签，不再把 unavailable 字段当作零。
7. queued Terminal Runtime 完成 provider、1/5/10/20 容量、chaos、恢复、rollback、观察和双签；legacy inline 仍保持并发 1，只有已验收的 queued worker 扩容。

`strategy.execution_preview` 的 `can_execute=False`、`research_only=true` 是展示契约，不作为待翻转开关。策略执行必须走 Evidence、Promotion、风控、审批和 broker execution 的正式链；QMT 实盘另受 `QMT-01/02` 外部门禁。

## 2. 当前事实与先行纠偏

- `core/middleware/decision_gate.py` 覆盖 11 类决策路径；`core/health_checks.py` 要求 runtime state、核心覆盖、provider capability 与 decision data 四项同时通过。
- 当前 active-A-share fact 与 Publication 不是同一口径：已有只读证据显示底层 fact 可覆盖 5,533 个标的，但 canonical price/financial Publication member 曾仅为 `0/5,533` 与 `1/5,533`，valuation Publication 缺失。第一动作应先区分“事实缺失”和“发布成员缺失”，不能无差别重抓全市场。
- 工作分支 `2e83d161c…` 已是 `origin/main` 的祖先，合并提交为 `003cb58c…`；另有尚未进入当前工作树的候选部署 attestation。执行时先以只读生产 verifier 对账实际 commit/release/OCI/matrix/graph/runtime identity。若生产已经运行含修复的精确候选，只补 canonical evidence 与 UAT；只有身份不符才重新部署。
- TUX-05 本地 production-safe profile 已通过，但 local evidence 不继承为生产 `TUI-01`；canonical `uat` 为空时仍是 DENY。
- authority/evidence 与 R1–R8 owner-ledger 的零行是缺少真实业务/审批输入，不是 migration 或 fixture 问题。

## 3. 总体执行顺序

| 阶段 | 主要 unit | 动作 | 退出门 | 可并行项 |
|---|---|---|---|---|
| P0 候选对账 | TUI-01 | 只读核对 Git/OCI/manifest/production identity；条件式部署 | 唯一候选身份无漂移 | 准备审批包、owner 输入模板 |
| P1 TUI 快速闭环 | TUI-01 | production-safe recorder、三角色、写回执、readback、exact cleanup | recorder 全绿且真实 role owner 确认 | DATA/AUD preflight |
| P2 恢复与审计窗口 | DATA-01、AUD-03 | 备份、维护、shadow restore/switch-back、故障恢复、alert、archive/restore | RTO/RPO、零丢失/重复、回滚和双签 | STRAT/EVID dry-run |
| P3 数据快修与深回填 | DATA-02 | Publication 重建优先；仅补真实 fact/history 缺口；逐数据集对账 | coverage/freshness/reconciliation 全绿 | owner/root 审批采集 |
| P4 决策恢复 | DATA-03 | 严格预检、受控激活、失败自动 re-block、双 readiness 与观察 | decision-ready=200 且无 must-not-use | STRAT-02 receipts 开始积累 |
| P5 Evidence/策略 | EVID-01/02/03、STRAT-01/02/03 | 真实 authority、审批、定义、PIT/OOS、Promotion、consumer UAT | exact-current 与执行前重验通过 | AUD/TUI 观察 |
| P6 Terminal/AI | TAR-05、AI-01 | queued canary、容量、chaos、14 日 telemetry、AI staging/prod UAT | hard SLO 与双签全部通过 | QMT Phase 0（获权后） |
| P7 实盘桥 | QMT-01/02 | XtQuant 探针、5 日仿真、3 日小额实盘 | 券商与业务 owner 验收 | 不阻塞模拟盘或研究展示 |

依赖未满足时阶段顺延。真实观察窗口、PIT/OOS 样本期、券商开权和人工审批不可通过补写时间戳压缩。

## 4. P0/P1：候选与 TUI-01

### 4.1 候选只读对账

1. 对账 `origin/main`、部署 commit、release、OCI revision、matrix SHA、operation graph SHA、runtime manifest SHA。
2. 读取生产 health、ready、decision-ready、migration、TUI registry 和容器 revision；生成 candidate-bound preflight。
3. 若生产 identity 已包含 `003cb58c…` 的 TUI 修复且所有摘要一致，禁止重复部署；把已有 attestation 纳入 canonical 分支即可。
4. 若不一致，先创建并校验 PostgreSQL custom-format backup，再从独立 clean worktree 做 code-only deployment；保留 PostgreSQL/Redis volume，自动失败回滚必须 armed。

### 4.2 生产 UAT

使用固定 profile，不混入外部 AI、queued runtime、authority seed、active RSS、shared quota、load、fault 或 live rollback：

```bash
python scripts/record_web_to_tui_candidate_evidence.py uat \
  --uat-profile production-safe \
  --base-url <production-base-url> \
  --skip-server
python scripts/check_web_to_tui_cutover_readiness.py --json
```

验收必须同时包含：

- regular/operator/admin 三角色边界；
- 108/108 route-page 与 9/9 参数化读取；
- 账户 create/cancel、strategy 与 inactive personal provider 的同 run receipt；
- confirmed mutation 后在 60 秒 settlement SLO 内进入明确完成态；
- 按 run/name/owner/primary key 精确 cleanup，剩余为 0；
- role owner 对业务结果作真实确认。

`TUI-01` 关闭后才启动 `TUI-02` 第 0 天。候选、matrix、graph 或 runtime identity 漂移，或者出现 P0/P1 缺陷，14 日窗口重置。

## 5. P2：一次受控维护窗口关闭 DATA-01 与 AUD-03 的高风险子项

### 5.1 窗口前置

- 生产 owner 指定窗口、操作人、reviewer、RTO/RPO 目标和终止条件。
- 新建 backup（不 prune），下载后核对远端/本地 SHA-256，执行 `pg_restore --list`。
- 记录 writer、Celery、beat、queue、连接数、磁盘/WAL 与当前 release 基线。
- 把 decision runtime 切到 `maintenance` 或 `validating`；这不是解除总闸。

### 5.2 DATA-01 演练

1. 将最新 dump 恢复到隔离 sibling PostgreSQL 数据库，核对表、migration、sequence、逐表摘要。
2. 对隔离数据库执行候选 migration forward/backward；验证 rollback 后 schema/data hash 回到基线。
3. 做受控 connection switch smoke 后切回原生产库，或者按批准的 `vps-restore` 路径完成等价 live rehearsal。
4. 记录实际 restore、verify、switch-back 时间；失败立即保持 maintenance 并回到原 release/DB，不删除恢复点。

### 5.3 AUD-03 演练

在同一窗口但使用独立证据包：

- 注入一条有界 audit/outbox canary fault，验证 metric → alert → acknowledge → recovery；
- 验证 backlog age、duplicate、loss、recovery duration 均来自原始 timeline；
- 管理员 TUI 能定位 P0 事件链且不暴露秘密/任意 JSON；
- 对 canary 时间窗执行 archive，校验 manifest/content/predecessor hash，再恢复到隔离 namespace 并重放查询；
- owner 与独立 reviewer 分别签署 DATA-01、AUD-03，不共用一个“总体通过”占位。

退出门：原生产数据不丢失、恢复点可用、rollback 可重复、audit duplicate/loss 为 0、alerts/TUI/recovery/archive 不再 `unavailable`。任何一项失败时 `DATA-02` 不启动。

## 6. P3/P4：DATA-02/03 与决策 API 恢复

### 6.1 先修 Publication，再补事实

按 `active_a_share` 冻结当次 universe 与 as-of：

1. 只读导出 quote/price/valuation/financial 的 fact count、每标的最早/最晚 observation、历史深度、Publication/member/coverage。
2. 若 facts 已存在且 observation time、natural key、source、unit、quality 均有效，重建 immutable Publication/member/coverage；禁止为了填 member 再抓一遍同样事实。
3. 只有真实缺口才运行受控回填。默认从小批开始：

```bash
python manage.py backfill_active_a_share_core_data \
  --resume-offset <verified-offset> \
  --batch-size 50 \
  --source <approved-provider> \
  --history-days 756 \
  --financial-periods 8 \
  --max-batches <approved-batch-limit>
```

4. 任一 batch 为 `partial/blocked/failed`、零写入伪成功、WAL/磁盘越界、锁预算超限或 provider 跨源差异超过治理容差时立即停在 checkpoint；不得跳过失败标的推进 offset。
5. 每个 dataset 单独生成 legacy/canonical snapshot 与 reconciliation evidence；差异分类必须是 same、source-only、target-only、value mismatch、timestamp mismatch 或 quality mismatch，不能只比总行数。
6. 回填完成后运行 decision reliability repair，刷新宏观、quote、Pulse 与 Alpha；使用 `--strict` 保持失败关闭。

### 6.2 两阶段激活决策门

不允许先执行裸 `set_decision_runtime_state active` 再观察：

1. 在 runtime 仍 blocked/validating 时，对 `core_coverage`、`provider_capabilities`、`decision_data` 做不含 runtime-state 的严格 preflight；三项必须 `status=ok` 且 `must_not_use_for_decision=false`。
2. 通过受审计的 compare-and-set 操作把 runtime state 绑定到精确 release ref 并切为 `active`。
3. 立即请求 `/api/decision-ready/`；必须为 `200`，四项检查完整且全部 `ok`。
4. 若最终探针失败或 candidate 漂移，自动写回 `blocked`，保留原 reason、release ref 和恢复证据。

若仓库当前只有无预检的通用 state command，应先在 `DATA-03` 范围补一个 fail-closed activation wrapper 与契约测试；不能把操作纪律当原子保证。

决策 API 恢复不等于 DATA-03 最终关闭。仍须保留至少行情 3 个交易日加周末、宏观 2 个调度周期的 candidate-bound observation；期间 stale/failover/conflict 必须重新阻断。

## 7. P5：Evidence、R1–R8 与策略执行

### 7.1 首批真实输入包

业务 owner 为每个 R1–R8 capability 提交：owner/tenant identity、definition version/hash、policy、calendar、scope/universe、sample window、qualification、benchmark/cost/liquidity/label 语义、失效条件、回滚条件。系统只做 schema/hash/dry-run 验证，不代填业务值。

独立 root/reviewer 随后完成：

1. 创建真实 owner/tenant authority root；
2. append-only approval first-winner、successor、revocation/current-head 与 rollback；
3. same-alias Evidence composition 和端到端 receipt；
4. 对 13 张表及 EVID-02 head 再做 candidate-bound inventory。

禁止 raw SQL、fixture、User/Profile/session 推断 owner 或自动生成审批。

### 7.2 依赖顺序

- `EVID-01 + EVID-02 → EVID-03`：只有两项真实生产门关闭后，才把 priority Research/Portfolio/Broker consumer 接到 exact-current revalidation。
- `STRAT-01 + DATA-02 → STRAT-02`：历史数据必须保留 source observation time、lineage、receipt 与 PIT/OOS 边界；可回填事实，不能伪造当时可见性。
- `STRAT-02 + EVID-03 → STRAT-03`：Promotion、权限、consumer UAT 与 rollback 使用同一 receipts/evidence hash。

`strategy.execution_preview` 继续 display-only。模拟盘可在决策数据恢复后重新估值；实盘订单只能由已 Promotion 的策略、正式 execution proposal、风控、人工确认和 broker execution 生成。

## 8. P6：TAR-05 与 AI-01

### 8.1 queued runtime 验收

先在同一候选的批准 staging 环境启用 `TERMINAL_RUNTIME_AUTHORIZED`、queued intake 与专用 `terminal_agent_worker`。legacy inline 的 `TERMINAL_AGENT_MAX_CONCURRENCY` clamp 继续为 1；容量扩展只发生在隔离 worker。

顺序执行：

1. 单用户 provider/MCP 成功、审批暂停/恢复、SSE 重连、cancel、idempotency 和费用审计。
2. 1/5/10/20 用户阶梯、15 分钟容量测试与 soak；四档必须绑定同一 commit/release/OCI/runtime/test-matrix。
3. Worker SIGTERM/SIGKILL、Redis down/restart、broker 丢消息、model timeout、Web restart、deploy drain。
4. 队列 drain 到 0，永久 running=0，重复非幂等副作用=0，跨用户泄漏/秘密泄漏=0。
5. staff canary → 小比例普通用户 → 全量 queued；每级单独批准，任一硬门失败即停新接单并回滚 feature flag。

硬 SLO 至少包括 run API p95 ≤ 500 ms；20 用户时普通 Web 5xx=0、p95 劣化 ≤10%；Daphne 因聊天负载重启=0；同幂等键 20 次并发只产生 1 个 run 和 1 次模型调用。

TAR-05 关闭前不退休 inline、不放大全局容量。完成 14 日 telemetry、restore/rollback 与 Operations/Product 双签后，`AI-01` 才运行同候选 staging/production browser UAT、外部模型链路和独立 owner/reviewer sign-off。

## 9. P7：QMT 外部链

`QMT-01/02` 不与“系统决策 API 恢复”绑成一个开关。内部可完成安装包、read-only probe 和证据模板，但以下必须由外部环境提供：

1. 券商允许启动 XtQuantServer，并开通查询、委托和撤单权限；
2. 目标 Windows 主机完成 Phase 0 资金/持仓/委托/成交只读探针；
3. 仿真环境连续 5 个交易日无重复单和未处置差异；
4. 单笔、单日、总资金上限经批准后，连续 3 个交易日小额实盘逐单确认；
5. 四维对账、STOP、重连、撤单、回滚与券商/业务 owner 双签。

在此之前 `blocked_external` 保持正确；模拟盘、研究展示和非实盘功能不应被 QMT 门禁连带关闭。

## 10. 集中授权包

| 授权包 | 精确动作 | 默认回滚 | 人工/外部责任人 |
|---|---|---|---|
| A1 | TUI production-safe UAT 的限定写入与 exact cleanup；条件式候选部署 | 自动回旧 release；删除本 run 测试记录 | Release owner、role owner |
| A2 | 新备份、maintenance、shadow restore/switch-back | 原 DB/release 不动或立即切回 | Production owner、reviewer |
| A3 | DATA-02 分批回填、Publication 重建、reconciliation 写证 | checkpoint 停止；不删旧事实 | Data owner |
| A4 | AUD-03 canary fault、alert/recovery、archive/restore | 停注入、恢复配置、保留 ledger | Audit/Ops owner |
| A5 | owner/root/approval/definition/policy 的真实生产写入 | append-only revoke/successor | Business owner、独立 root/reviewer |
| A6 | queued canary、staging/生产 load/chaos、feature flag | 停接单、drain、flag 回关闭 | Operations、Product |
| A7 | 付费外部模型 UAT及费用上限 | 关闭 provider/canary | AI owner、reviewer |
| A8 | QMT 仿真或真实报撤单 | STOP、撤未成交、关实盘开关 | Broker、business owner |

A1–A8 不互相蕴含。特别是 A1/A3/A6 不能推导 A8 实盘授权。

## 11. 时间与交付节奏

| 工作 | 工程时间目标 | 不可压缩时间 |
|---|---:|---:|
| 候选对账 + TUI-01 recorder | 0.5–1 天 | role owner 确认 |
| DATA-01 + AUD-03 受控窗口 | 1 个准备日 + 1 个窗口 | owner/reviewer 安排 |
| Publication 快修 | 1–3 天 | provider/数据质量异常会顺延 |
| 全市场历史回填与 reconciliation | 3–10 天起 | 配额、WAL、失败标的、真实历史深度 |
| EVID-01/02 + STRAT-01 | 1–3 天工程执行 | 真实业务输入与审批 |
| TAR-05 容量/chaos | 3–4 工程日 | 14 日 telemetry |
| TUI-02 | 证据自动采集 | 14 日无阻断观察 |
| QMT | 少量工程支持 | 最少 5+3 个交易日且先获券商权限 |

每个 material checkpoint 必须同步：规范化 evidence artifact、对应 primary plan 实施记录、`governance/active_plan_registry.json`、`docs/plans/README.md` 和必要的 `docs/INDEX.md`。状态只能在唯一 exit gate 真正满足后晋级。

## 12. 停止线

- 不降低 freshness、coverage、SLO、跨源 1% 默认容差或观察天数来换通过。
- 不清除持久化决策门后再补数据；激活失败自动 re-block。
- 不把 stale price 用于模拟盘可信估值，不用计算时间伪装 observation time。
- 不把 local/SQLite/fixture evidence 写成生产证据。
- 不代替 owner/root/reviewer、券商或真实用户作决定。
- 不通过把 `can_execute` 改为 true 绕过 Evidence/Promotion/QMT。
- 任一写入超出授权包、候选身份漂移、数据/审计 hash 不一致、无法回滚或出现秘密泄漏时立即停止并保留 fail-closed。

## 13. 执行检查点（2026-08-30）

### 13.1 DATA-01 已关闭

在生产候选 `c826f741edc0f12f5e29fa5b0441b34a89f6dac5` 上完成了新建并保留的 PostgreSQL custom-format 备份、下载与 SHA-256 对账、sibling database 恢复、`data_center.0072 → 0071 → 0072` 迁移往返、真实 Web 连接切换和切回。恢复库包含 `542` 张 public 表、`72` 项 Data Center migration 和 `463` 个 sequence，schema SHA-256 为 `d9f761e83e45cf5111af7b76ef546f99d52d3e7198489a03a458ba9e519ca447`。迁移往返后业务表、schema 和 migration 名称集合一致；唯一变化是 `django_migrations` 的正常 ledger id 及 sequence 从 `496` 增至 `497`。

真实切换演练中，恢复库启动 `63s`、原库切回启动 `42s`、外部累计不可用 `217s`；切换前后核心计数保持 `2,784,337 / 167,724 / 441,944 / 2,197 / 171,503 / 173`，WAL 均为 `3/EF274DF0`。切回后 Web health=`200`、Celery 节点=`1`、决策门恢复为原先的 `blocked`，临时恢复库与临时秘密文件均已删除，远端恢复点继续保留。

证据文件及 SHA-256：

- [`data01-live-rehearsal-c826f741-baseline.json`](../deployment/data01-live-rehearsal-c826f741-baseline.json)：`7271832f3f19b8463126a0c54068dcc6007b80978c04080b4071fdc6fad8f6ea`
- [`data01-live-rehearsal-c826f741-migration-roundtrip.json`](../deployment/data01-live-rehearsal-c826f741-migration-roundtrip.json)：`a404d575d6e5252529779b6675d798374a4e009a98c3282d3116564d8fa4afa4`
- [`data01-live-rehearsal-c826f741-migration-classification.json`](../deployment/data01-live-rehearsal-c826f741-migration-classification.json)：`cb51a8f9e87b4bfe4bcdb795b620a5de76599480fa615712b8c7c4cf7d1f79ec`
- [`data01-live-rehearsal-c826f741-connection-switch.json`](../deployment/data01-live-rehearsal-c826f741-connection-switch.json)：`d7e73b6f24ad6ee6660ec24abe5f31ab2cc07f6b3e7f5b12577a95fd663cb526`

### 13.2 DATA-02 候选实现已就绪，尚未宣称生产通过

新增 active-A-share quote/price/valuation/financial Publication 的全量原子重建用例和 dry-run-first 管理命令。候选选择以每个资产的确定性最新真实 fact 为来源，执行前验证 universe 精确一致、时间戳 aware 且不在未来、dataset/table 绑定正确；四类 Publication 在同一外层事务中发布，任一失败整体回滚。标准单标的同步和 backfill 中间批次改为 fact-only，避免局部任务把全市场 current Publication 缩成单标的；只有完整 backfill 成功后才触发全 universe 原子发布，失败返回 `blocked` 并保留 checkpoint。

DATA-02 增加 `repair_active_a_share_current_facts`：默认 dry-run；显式执行时先做 historical-price 与 financial provider 探针，再分批抓取真实 quote/valuation，任何批次不是 frozen universe 精确覆盖即停止；仅将已有 `report_date` 的 null `available_at` 修复为源日期边界，并只从 15:00 后的最近已完成交易日真实 quote materialize 日线。周末/开盘前的日频 price/valuation 使用最近已收盘交易日语义，实时 quote 不继承该放宽。2026-08-30 生产只读 provider 预检得到 Tencent failover `5,533/5,533`、observation date 全部为 `2026-08-28`、OHLC 缺口 `0`；东方财富 batch endpoint 失败被显式记录，未静默改写 source。

DATA-03 同候选新增 `activate_decision_runtime_fail_closed`。通用 runtime update 和 `set_decision_runtime_state` 已禁止写 `active`；唯一激活入口先在 blocked/validating 状态运行 core coverage、provider capability、decision data 三检查，再锁行 compare-and-set 到精确 release ref，随后立即复验，任何失败自动写回 blocked。该实现就绪不等于 DATA-03 解锁；必须先完成 DATA-02 生产执行与 reconciliation。

部署前候选门禁已经统一复跑：DATA-02/03 与相关数据链回归包 `230 passed, 2 skipped`，四个强制高风险包（TUI、Terminal Agent、SDK、内部 SSL）`356 passed`，改写后的四类 latest-fact 选择器及 remediation 组件包 `43 passed`，最终 backfill checkpoint 回退用例包 `9 passed`。Black/isort/Ruff、Django system check、25 个生产 Python 文件增量 mypy、完整 mypy debt ceiling、architecture delta、91 项 Celery task contract、53 项 current-data contract 与 active-plan registry 均通过。最终批次若 Publication 重建失败，checkpoint 的 `next_offset` 会回退到该批次起点，避免后续空批次把未发布状态误报为完成。生产执行仍须先运行 dry-run，随后只对真实 freshness/history 缺口回填并做 canonical reconciliation；在覆盖率、provider capability 和 decision-data 全绿前不得执行激活 wrapper。

### 13.3 仍保持阻断的边界

- `TUI-01` 自动化已经 10/10、108/108，但真实 role-owner 业务确认和后续 14 日窗口仍未完成。
- `EVID-01/02`、`STRAT-01` 仍缺真实 root/reviewer/业务 owner 输入，不能用 fixture 或代理签名补齐。
- `AUD-03` 的 alert、fault recovery、archive/restore 和双签仍需单独生产证据。
- `TAR-05` 的 1/5/10/20、chaos、恢复和观察未完成；inline concurrency clamp 继续为 1。
- `QMT-01/02` 仍缺获批 XtQuant 目标环境；A8 授权不能替代券商环境、回执和交易日观察。
