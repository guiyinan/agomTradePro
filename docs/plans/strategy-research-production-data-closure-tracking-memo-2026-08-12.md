# 策略研究真实数据与生产收口跟踪备忘录

> 创建日期：2026-08-12  
> 状态：待开发团队持续执行  
> 适用范围：R1–R8 策略研究能力  
> 软件边界基线：软件侧 P0/P1 已终核为 0；当前 readiness 仍为 `BLOCKED`

## 1. 备忘结论

当前系统已经具备严格的证据校验、PIT 查询、append-only ledger、assessment、monitoring 与 fail-closed 能力，但**仅启动系统并采集普通业务数据，不会自动完成全部研究能力收口**。

开发团队还需要完成以下生产接线：

1. 登记真实且可版本化的 owner definition、policy、calendar、scope 与 qualification binding。
2. 将真实 Publication、PIT vintage、OOS、forecast outcome、reconciliation 等上游数据物化为 canonical receipt/ledger。
3. 建立受控的内部任务编排，驱动“采集 → 校验 → receipt → assessment → monitoring”，不得绕过 inert public mutation façade。
4. 积累满足窗口、周期、覆盖率和新鲜度要求的真实历史数据。
5. 完成人工 Promotion、上线授权与 consumer/UAT 验收。

完成上述工作后，证据评估和监控可以自动运行；缺失、过期、冲突或不可重放的数据仍应自动保持 `BLOCKED`。

## 2. 不可违反的收口原则

- 禁止用 fixture、常量、请求时间或下游结果快照伪造 owner evidence。
- 禁止把“latest”直接解释为“fresh/current”。
- 所有事实必须保留真实 `observed_at / available_at / recorded_at / valid_until`。
- 所有 PIT 查询必须先按 cutoff 过滤，再执行完整性、fork 和 hash-chain 校验。
- Public mutation façade 保持 inert；生产写入只能通过受控内部 composition、任务或管理员流程。
- Promotion、上线授权及 consumer 接入必须保留人工责任，不自动越权。
- 空库、证据缺失、owner 冲突或版本漂移必须零写并返回稳定 `BLOCKED`。

## 3. 开发主线

### A. 权威 owner 与定义登记

- [ ] 为生产环境登记 R1–R8 所需的真实 definition、policy、calendar、scope、sample window 和 qualification binding。
- [ ] 每项登记均包含稳定 ID、version、content hash、有效期和 owner source receipt。
- [ ] 建立受控变更流程：新版本只能追加，不得覆盖历史版本。
- [ ] 对缺失、重叠有效期、同 identity 不同内容和 fork 建立告警。

### B. Canonical receipt 物化

- [ ] Data Center：Publication、PIT manifest、member/vintage、calendar projection。
- [ ] Signal：Forecast Ledger outcome、calibration sample、realization receipt。
- [ ] Regime：historical assignment definition、artifact 与 PIT fact receipt。
- [ ] Portfolio：returns/covariance、cost/liquidity/capacity、monitoring feedback receipt。
- [ ] Broker：execution cost、slippage、reconciliation numerator/denominator receipt。
- [ ] Audit：R2 outcome/fact、审计快照与外部对账证据。
- [ ] Research：Promotion/lifecycle、trial、monitoring、analogy/path raw evidence。

每个 receipt 必须能够从其 owner 真源重新构造并验证，不能只保存一个布尔结果或聚合分数。

### C. 受控自动编排

- [ ] 为每条链建立内部 ID-only command，不允许 caller 传入成品 evidence、score、probability 或 assessment。
- [ ] 所有 provider、clock、store 使用同一动态 UoW，并在事务内执行双读及 append 前最终复读。
- [ ] trusted server clock 与业务 PIT `as_of` 分离记录。
- [ ] 任务输出统一发布 `success / partial / noop / blocked / failed` 及 requested/succeeded/failed/stored 计数。
- [ ] 失败、零写和业务阻断接入 Task Monitor、告警和可追踪审计日志。
- [ ] 为任务设置安全重试与 exact winner replay，禁止重复写和静默 fork。

### D. 数据积累与质量门槛

- [ ] 明确每项能力的最小历史窗口、周期数、样本数和覆盖率。
- [ ] 监测缺失、censored、invalidated、estimated 和 stale 成员占比。
- [ ] 对 Publication 延迟、calendar 漂移、vintage 回填和 source replacement 建立告警。
- [ ] 达不到最小样本或覆盖率时保持 `BLOCKED`，不得降级为伪成功。
- [ ] 保存每次 assessment 使用的完整 member manifest，确保跨进程可重放。

### E. 人工决策与 consumer 验收

- [ ] Research owner 完成人工 Promotion/Retire/Rollback 审批。
- [ ] 风险、组合、信号和执行 consumer 分别签署只读 preflight/UAT 结果。
- [ ] 验证所有研究产物仍带 `research_only / must_not_publish_current / must_not_use_for_decision / must_not_execute`，直到正式授权事件生效。
- [ ] 完成回滚演练、权限复核、PostgreSQL 并发验证和备份恢复演练。
- [ ] 只有 owner、monitoring、authorization 与 consumer evidence 同时完整时，才能更新 readiness 状态。

## 4. R1–R8 跟踪矩阵

| 能力 | 当前主要真实阻断 | 开发团队下一交付 | 自动化完成条件 | 当前状态 |
|---|---|---|---|---|
| R1 Forecast Baseline | Publication、actual member/vintage、真实 trial owner、Valuation consumer 授权 | Data Center actual receipt materializer、Research trial owner 接线、consumer UAT | 季度 forecast-vs-actual 可按 PIT 重放，人工 Promotion 完成 | `BLOCKED` |
| R2 Market Structure | taxonomy/calendar Publication、两个完整周期、Audit outcome/facts | Publication/calendar adapter、cycle receipt、Audit canonical provider | trial 与 monitoring 可由 server-selected 完整 owner graph 重放 | `BLOCKED` |
| R3 Macro Factor | 宏观 vintage、代理资产、Regime/OOS trial、Promotion | Data Center/Regime 真实 source registration、trial/Promotion owner 接线 | inference/trial/monitoring 全图满足 PIT 与 OOS 门槛 | `BLOCKED` |
| R4 Risk/Allocation | 真实 R3 Promotion、returns/covariance/Regime PIT、成本约束 | Portfolio owner receipt materializer、Research Promotion 接线、consumer review | monitoring healthy 且 manual consumer review 通过 | `BLOCKED` |
| R5 Relative Value | 可靠曲线、信用估值、Bond Master/CashFlow/Calendar Publication、Portfolio outcome | Fixed Income/Data Center/Portfolio 真实 owner 接线 | active lifecycle 与 latest complete monitoring 同时可重放 | `BLOCKED` |
| R6 State Model | 真实 simple-baseline shortfall、PIT/OOS、稳定标签、scope binding 数据 | qualification owner registration、monitoring 数据积累、manual activation review | qualification healthy、scope owner 有效、人工激活授权完成 | `BLOCKED` |
| R7 Scenario Research | Risk Center policy、Forecast history/outcome、calibration、analogy/path raw history | Signal/Research owner receipt 定时物化、Promotion 与 family lifecycle 运营流程 | result 与 post-promotion monitoring 完整，人工 Promotion/Retire/Rollback 可审计 | `BLOCKED` |
| R8 Optimization Monitoring | R3/R4/R5 Promotion、Portfolio/Broker 真实 period feedback、consumer 验收 | Promotion adapter 数据接入、Portfolio/Broker receipt 周期任务 | 11 项指标完整、monitoring healthy、人工 consumer review 通过 | `BLOCKED` |

## 5. 每个开发批次的 Definition of Done

每个 owner/source 纵切只有同时满足以下条件才能标记完成：

- [ ] 真源和业务 owner 已明确，不存在反向依赖或重复权威表。
- [ ] ID-only command、strict codec、append-only ORM、schema-only migration 已完成。
- [ ] exact PIT read、winner/fork、rollback、tamper 和 ORM mutation guards 已覆盖。
- [ ] public mutation inert，recursive public object graph 不含 writer/token/clock/atomic/append 能力。
- [ ] 空库与缺失 owner 测试证明 `BLOCKED` 且零写。
- [ ] 真实数据 happy path 已在非 fixture 环境通过，并保存 evidence ID/hash/cutoff。
- [ ] Ruff、Black、isort、增量 mypy、architecture、governance 和 migration drift 全绿。
- [ ] 对应路线图、completion audit 与本备忘录状态已同步更新。
- [ ] 代码、迁移、测试、文档按主题分批提交，不混入用户其他改动。

## 6. 生产验收证据清单

开发团队每次申请把某项能力从 `BLOCKED` 调整为下一状态时，应附：

1. owner identity/version/content hash。
2. PIT cutoff 与完整 member manifest。
3. observed/available/recorded/valid clocks。
4. receipt、assessment、monitoring、Promotion/authorization 的 ledger IDs。
5. exact replay 输出与原输出的 hash 一致性结果。
6. stale、missing、fork、tamper、rollback 和重试测试结果。
7. consumer/UAT 责任人、日期、结论及回滚点。
8. PostgreSQL 并发与权限验证结果。

仅有“任务执行成功”“表里已有数据”或“页面显示正常”不能作为收口证据。

## 7. 推荐执行顺序

1. 先接 Data Center/Signal/Regime 的真实 owner 与 Publication/PIT receipts。
2. 再接 Portfolio/Fixed Income/Broker/Audit 的事实与对账 receipts。
3. 运行 trial、assessment 与 monitoring，积累足够周期。
4. 执行人工 Promotion/qualification/activation review。
5. 最后开展 consumer UAT、权限验证和生产回滚演练。

## 8. 关联文档

- [策略研究能力路线图备忘录](../business/strategy-research-capability-roadmap-memo-2026-08-04.md)
- [策略研究能力完成度审计](strategy-research-capability-completion-audit-2026-08-05.md)
- [策略研究路线图执行计划](strategy-research-capability-roadmap-execution-2026-08-05.md)
- [R1/R2 readiness 计划](strategy-research-r1-r2-readiness-plan-2026-08-05.md)
- [R5–R8 readiness 与分阶段交付](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md)

## 9. 状态更新规则

- 每完成一个真实 owner/source 纵切，在本文件对应清单和矩阵中记录日期、commit、测试和 evidence IDs。
- 只有真实数据证据通过后才允许将 `BLOCKED` 改为后续状态。
- 若发现 owner 语义不足，优先修正 source contract，不得现场猜测或由下游 assessment 反充。
- 未完成项必须保留明确 blocker、owner、下一动作和预计验证方式。

## 11. 2026-08-16 本地机制证据 allowlist 防绕过收口

本批只修复 STRAT-01 readiness 的本地防伪边界，不登记任何真实 owner、definition、policy、PIT/OOS、receipt 或生产数据：

- `OwnerMechanismAttestation` 现在在 Application composition 类型边界直接复用 `is_mechanism_attestable_requirement`，拒绝将 live-data、outcome、snapshot 或 reconciliation requirement 包装成静态“机制证据”。此前 JSON manifest loader 已有同一校验，但直接构造类型可绕过 loader；本修复关闭该绕过路径。
- 新增 `test_mechanism_attestation_type_rejects_live_data_requirements`，覆盖 scenario outcome history、Portfolio canonical snapshot 和 execution feedback 三类不可机制化 requirement；STRAT readiness/runtime 回归 `27 passed`。
- 该切片只证明机制 allowlist 的 fail-closed contract；R1–R8 真实 owner/definition/policy/calendar/scope、PIT/OOS 历史、canonical receipts、Promotion 与 consumer/UAT 仍缺，`STRAT-01`/`STRAT-02` 状态不变。

## 10. 2026-08-15 本地 readiness 防伪收口

本批只加强软件侧的 readiness 边界，不构造任何生产 owner、definition、policy 或历史数据：

- `tests/component/research/test_capability_readiness_runtime.py` 新增 R1/R2 运行时断言，确认 R1 的六项生产要求仍全部保持 `UNVERIFIED`，Forecast Baseline 的真实 specification 仍为 `MISSING`，R2 的五项生产要求仍全部保持 `UNVERIFIED`。
- 定向组件回归为 `8 passed`；断言验证的是“机制 manifest 不能升级为 production readiness”，不是能力已经具备。
- `STRAT-01` 继续等待真实 R1–R8 owner/definition/policy/calendar/scope 登记；`STRAT-02` 继续等待 `STRAT-01` 与 `DATA-02`，不因本地测试变绿而提前解锁 PIT/OOS receipts、对账或 Promotion。

## 12. 2026-08-16：机制 attestation 过期状态收口

本批修复了一个本地 fail-closed 缺口：`AttestedMechanismOwnerAdapter.collect()` 直接被调用时，过去只判断 `observed_at`，可能把已过期的机制 attestation 暴露为 `VERIFIED`。现在在 Application 边界先判断 `valid_until <= evaluated_at`，统一返回 `STALE` 和稳定阻断原因 `*.runtime.attestation_expired`。

- `tests/unit/research/test_capability_readiness_registry.py`：`20 passed`；Research focused 回归 `53 passed`。
- 增量 mypy：`0 regressions`；Black/isort 通过。
- 该切片不创建或回填任何 owner、definition、policy、calendar、scope、PIT/OOS、receipt 或生产数据；`STRAT-01`/`STRAT-02` 状态不变，生产 readiness 仍需真实 owner 与数据证据。

## 13. 2026-08-20：STRAT-01 全能力 readiness inventory contract

本批新增只读 `EvaluateAllCapabilityReadinessUseCase`，按 `ResearchCapability` 的 canonical R1–R8 顺序收集完整 `CapabilityReadinessReport`。每个报告仍由原 owner-scoped provider 独立生成，保留完整 requirement evidence 与 blocker，不把一个能力的机制证据合并到另一个能力，也不把静态机制 evidence 推导为 live-data readiness。

- `tests/component/research/test_capability_readiness_runtime.py` 新增全能力盘点回归；Research readiness/runtime 与既有 registry focused 合计 `29 passed`。
- 该 slice 只证明本地自动盘点和 fail-closed 聚合边界，不读取或写入生产数据库，也不创建 owner、definition、policy、calendar、scope、PIT/OOS、canonical receipt、Promotion 或 consumer UAT 记录。
- `STRAT-01` 仍等待真实 R1–R8 owner/definition/policy/calendar/scope 登记；`STRAT-02` 继续等待 `STRAT-01`/`DATA-02`，`STRAT-03` 继续等待真实 receipts、Promotion 和 consumer UAT。

## 14. 2026-08-21：STRAT-01 VPS canonical inventory 只读验收

在当前 VPS web 容器的 PostgreSQL `default` alias 内执行只读 `SELECT COUNT(*)`，不触发任何
业务写入。`research_r1_` 至 `research_r8_` 共 `65` 张 canonical 表、`portfolio_r4_`/
`portfolio_r5_`/`portfolio_r8_` 共 `7` 张表、四张 `equity_forecast_baseline_*` 表均为零行；
R1–R8 所需的 Data Center evaluation-actual、PIT manifest/fact-version、macro-factor
source/calendar/member-rule 与 market-structure evidence/calendar/series 表也均为零行。
原始只读盘点及运行态绑定见
[`evid-02-strat-01-vps-readonly-inventory-2026-08-21.json`](../deployment/evid-02-strat-01-vps-readonly-inventory-2026-08-21.json)，
其 SHA-256 为 `09d628c3070068e621bc3550bd0d20a70669274c29977c3ddfbc5006fafbf0e5`。

结果是明确的生产 blocker，不是缺少查询器：当前没有可供 R1–R8 使用的 canonical
owner/definition/policy/calendar/scope/qualification rows。现有 Data Center facts 不被现场
hash 或下游 readiness 反充为 owner evidence；不执行 synthetic seed、回填或 promotion。
因此 `STRAT-01` 仍为 `awaiting_production`，`STRAT-02`/`STRAT-03` 依赖不变，PIT/OOS、
receipts/lineage/reconciliation、Promotion、consumer UAT 与 rollback 继续 `BLOCKED`。

## 15. 2026-08-21：STRAT-01 current HEAD 只读 inventory 重绑

为消除旧候选绑定，针对当前运行 `a428edaad5cf70e0c47a5649c5f867ae6aeabdd5` /
`20260821060037` 的 PostgreSQL `default` alias 重新执行只读盘点。Research R1–R8 共 `65`
张 canonical 表、Portfolio R4/R5/R8 共 `7` 张表、四张 Equity baseline 表及全部 Data Center
actual/PIT/macro-factor/market-structure 依赖表均为零行。工件
[`evid-02-strat-01-vps-readonly-inventory-2026-08-21-head-a428edaad.json`](../deployment/evid-02-strat-01-vps-readonly-inventory-2026-08-21-head-a428edaad.json)
绑定相同 commit/release/image，SHA-256 为
`e93fdcef3591aece3d9d9412a9e58b288e9514a759e3a2fe048d2d85bf56f95b`。

这仍是明确的生产 blocker：没有 owner/definition/policy/calendar/scope/qualification rows，
不执行 synthetic seed、回填或 promotion，也不把当前 Data Center facts 现场 hash 成 owner evidence。
因此 `STRAT-01` 继续 `awaiting_production`，`STRAT-02/03` 依赖不变；本次只更新候选绑定，不改变
生产状态或任何 execution gate。

## 16. 2026-08-23：STRAT-01 current candidate owner-ledger recheck

在 `4cef9040cccc2127c3f8128c8d858bc7958df2a4` / release `20260822134658` 上，以同一
PostgreSQL alias 重新执行只读盘点：Research R1–R8 的 `65` 张 canonical 表与
Portfolio R4/R5/R8 的 `8` 张表仍全部为零行，明确的 owner/operator/policy registry 也仍为零；
`data_center` 有实际事实/publication rows，但不能替代 owner-scoped strategy ledger。结构化
工件为 [`tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json`](../deployment/tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json)。
SHA-256 为 `7f4e859915e7e0a8399ee75558a12e660b34ef04000f29988291f59d47eaaa55`。

本轮没有创建、更新、删除、回填、promotion 或审批，也没有把现场 Data Center facts hash 成
definition/policy/scope/qualification evidence。`STRAT-01` 继续 `awaiting_production`；
`STRAT-02/03`、PIT/OOS、canonical receipts、Promotion、consumer UAT 与 rollback 依赖不变。

## 17. 2026-08-23：STRAT-01 当前运行候选 owner-ledger 只读复核

按照 active registry 的 `auto_collect` 清单，在当前 web/celery 镜像
`agomtradepro-web:20260822134658` 上，通过同一 PostgreSQL `default` alias 执行
SELECT-only 盘点；manifest source commit 为
`4cef9040cccc2127c3f8128c8d858bc7958df2a4`。R1–R8 的 `65` 张 canonical 表全为零行，
Portfolio R4/R5/R8 的 canonical 前缀精确命中 `7` 张表且全为零行，Account
owner-assignment 的 `9` 张表与显式 owner/policy/operator registry 也全为零行。结构化
工件为 [`strat-01-owner-ledger-readonly-recheck-2026-08-23.json`](../deployment/strat-01-owner-ledger-readonly-recheck-2026-08-23.json)。
工件 SHA-256 为 `20e1d1c23ad00ab89879c1d2b2a4c93c051b07f9af0286c6df2c4f459c8d5ab6`。

本次仅采集现状，没有创建、更新、删除、回填、promotion 或审批；Data Center 的事实与
publication 不被现场 hash 成 owner evidence。结果仍固定
`STRAT-01=awaiting_production`、`production_claim=false`、`production_ready=false`、
`runtime_enablement=not_authorized`、`human_approval_status=not_collected`；`STRAT-02/03`
及 PIT/OOS、canonical receipts、Promotion、consumer UAT、rollback 与 owner/reviewer 签署
继续等待真实业务输入。

## 18. 2026-08-23：STRAT-01 当前候选 owner-ledger 新鲜只读复核

在仍运行的 `4cef9040cccc2127c3f8128c8d858bc7958df2a4` / release `20260822134658` /
image `agomtradepro-web:20260822134658` 上，通过同一 PostgreSQL `default` alias 执行
SELECT-only 盘点。Research R1–R8 前缀命中 `65` 张表、Portfolio R4/R5/R8 前缀命中 `7`
张表、Account authority/assignment 广义匹配 `15` 张表、owner/policy/operator/assignment
广义匹配 `34` 张表，所有表的 row count 均为 `0`。数据库为 `agomtradepro`、schema 为
`public`，观察时间为 `2026-08-23T13:26:42.792053Z`。

结构化工件为
[`strat-01-owner-ledger-readonly-recheck-2026-08-23-1326.json`](../deployment/strat-01-owner-ledger-readonly-recheck-2026-08-23-1326.json)，
SHA-256 为 `3ea5b041e6f59a2936d0b28aa89ea262eaf70c4f16769094d4d409a16c159849`。Account 与
owner/policy/operator 数量是为新鲜复核增加的广义 selector，既有 canonical 精确 9/9
口径保持不变。本次仍未创建、更新、删除、回填、promotion 或审批；
`STRAT-01=awaiting_production`、`production_claim=false`、`production_ready=false`、
`runtime_enablement=not_authorized`、`human_approval_status=not_collected`，
`STRAT-02/03` 及 PIT/OOS、canonical receipts、Promotion、consumer UAT、rollback 与
owner/reviewer 签署继续等待真实业务输入。

## 19. 2026-08-24：STRAT-01 owner-ledger auto-collect recorder

为让 `STRAT-01` 的已登记 `auto_collect` 证据可重复校验，新增纯 Application
解析器 `apps/research/application/strat_01_owner_ledger_inventory.py` 与离线 CLI
`scripts/record_strat_01_owner_inventory.py`。解析器严格接受现有
`strat-01-owner-ledger-readonly-recheck.v1/v2` 快照，校验候选 commit/release/image、
同一 `default` alias、`select_only`、固定 inventory/query scope、计数/重复项、未知字段、
secret/token 字段和未来时间；默认 dry-run，`--write` 仅追加本地 content-addressed report，
不连接 PostgreSQL/VPS、不创建或修改生产记录。

现有 v1/v2 快照均解析为 `zero_seed`；即使未来观察到非零行，报告也只会是
`nonzero_unverified`，并固定 `production_claim=false`、`production_ready=false`、
`runtime_enablement=not_authorized`。新增回归 `14 passed`，并通过 Ruff、Black、isort、
增量 mypy 与 debt ceiling；本 slice 不改变 `STRAT-01` 的 `awaiting_production` 状态，也不
把 owner/definition/policy/calendar/scope/qualification rows 推导成 authority 或 readiness。

