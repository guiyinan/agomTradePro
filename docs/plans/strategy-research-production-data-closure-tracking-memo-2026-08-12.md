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

## 10. 2026-08-15 本地 readiness 防伪收口

本批只加强软件侧的 readiness 边界，不构造任何生产 owner、definition、policy 或历史数据：

- `tests/component/research/test_capability_readiness_runtime.py` 新增 R1/R2 运行时断言，确认 R1 的六项生产要求仍全部保持 `UNVERIFIED`，Forecast Baseline 的真实 specification 仍为 `MISSING`，R2 的五项生产要求仍全部保持 `UNVERIFIED`。
- 定向组件回归为 `8 passed`；断言验证的是“机制 manifest 不能升级为 production readiness”，不是能力已经具备。
- `STRAT-01` 继续等待真实 R1–R8 owner/definition/policy/calendar/scope 登记；`STRAT-02` 继续等待 `STRAT-01` 与 `DATA-02`，不因本地测试变绿而提前解锁 PIT/OOS receipts、对账或 Promotion。

