# 活跃计划索引

> 更新日期：2026-08-13
> 本目录只保留仍需开发、真实数据、生产验收或外部依赖闭环的计划。已完成的实施计划、阶段记录、复盘和历史证据统一放在 [`../archive/plans/`](../archive/plans/)；归档记录见 [`../archive/ARCHIVE_INDEX.md`](../archive/ARCHIVE_INDEX.md)。

## 维护规则

- `docs/plans/`：存在未完成交付、真实数据、生产切换、外部验收或明确后续批次。
- `docs/archive/plans/`：仓库范围已实现，或阶段已经验收/被新计划取代；归档文档仅作历史证据，不代表当前运行状态。
- “代码已完成但生产未验收”仍属于活跃计划，不能仅因本地测试通过而归档。
- 归档时必须同步修正 `docs/INDEX.md` 和活跃计划中的引用，不复制第二份文档。

## 当前主跟踪入口

### 策略研究与证据治理

- [`evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md`](evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md)
- [`strategy-research-capability-completion-audit-2026-08-05.md`](strategy-research-capability-completion-audit-2026-08-05.md)
- [`strategy-research-capability-roadmap-execution-2026-08-05.md`](strategy-research-capability-roadmap-execution-2026-08-05.md)
- [`strategy-research-production-data-closure-tracking-memo-2026-08-12.md`](strategy-research-production-data-closure-tracking-memo-2026-08-12.md)
- [`strategy-research-r1-r2-readiness-plan-2026-08-05.md`](strategy-research-r1-r2-readiness-plan-2026-08-05.md)
- [`macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md`](macro-factor-r3-r4-readiness-and-staged-delivery-2026-08-05.md)
- [`strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md`](strategy-research-r5-r8-readiness-and-staged-delivery-2026-08-05.md)

### 数据与生产可靠性

- [`data-center-canonical-architecture-refactor-2026-08-02.md`](data-center-canonical-architecture-refactor-2026-08-02.md)
- [`production-data-reliability-full-remediation-2026-08-01.md`](production-data-reliability-full-remediation-2026-08-01.md)
- [`critical-reliability-test-closure-2026-07-22.md`](critical-reliability-test-closure-2026-07-22.md)
- [`uat-remediation-2026-07-20.md`](uat-remediation-2026-07-20.md)

### 产品界面与运行时

- [`web-to-tui-migration-plan-2026-07-25.md`](web-to-tui-migration-plan-2026-07-25.md) 与 [`web-to-tui-migration-matrix-2026-07-25.csv`](web-to-tui-migration-matrix-2026-07-25.csv)
- [`web-to-tui-m5-readiness-2026-07-27.md`](web-to-tui-m5-readiness-2026-07-27.md)
- [`ai-native/README.md`](ai-native/README.md)

### 外部环境或真实接入阻断

- [`qmt-live-trading-bridge-plan.md`](qmt-live-trading-bridge-plan.md)
- [`macro-sizing-multiplier-outsourcing-2026-03-31.md`](macro-sizing-multiplier-outsourcing-2026-03-31.md)

## 未完成项执行期（重要到次要）

| 期次 | 优先级 | 主线 | 退出条件 |
|------|--------|------|----------|
| 第一期 | P0 | 决策证据硬门禁、策略研究生产数据、Data Center canonical 与可靠性整改 | 决策链不再消费无证据或不新鲜数据，机器门禁和生产数据证据齐全 |
| 第二期 | P0 | Web → TUI M5 readiness、生产 preflight、浏览器 UAT、回滚演练与 route closure | cutover、UAT、回滚和路由关闭均取得最终签字或可复验证据 |
| 第三期 | P1 | AI-Native 人工 UAT/release gate、首页聊天复用前端自动化与浏览器验收 | 任务书验收表、人工签字、自动化资产和发布门禁全部闭环 |
| 外部阻断线 | P2 | QMT 实盘桥接、宏观 sizing multiplier 真实接入 | 外部环境、真实数据和生产接入证据到位后再转入完成验收 |

同一期内先处理会阻断投资决策正确性和生产安全的项目；仅有代码或本地测试、但缺少任务书要求的最终验收证明时，继续保留在活跃目录。

## 分阶段执行记录

| 日期 | 期次 | 阶段 | 完成情况 | 后续 |
|------|------|------|----------|------|
| 2026-08-12 | 基线 | 归档与排期 | 已在 `dev/plan-closure-by-priority` 创建基线提交 `919a9cea7` | 按本表期次继续独立提交 |
| 2026-08-12 | 第一期 P0 | Evidence M1 Domain 首批 | 统一分类、ArtifactRef、Track Record、Envelope、权限交集和 fail-closed 传播已实现；canonical hash、非有限 Decimal 和有效期防线已加固；纯 Domain `19 passed`，standalone strict mypy `0 errors` | 做 M1 persistence、API、审批激活和 adapters |
| 2026-08-12 | 第一期 P0 | Evidence M0 owner/freeze | ADR-0007 owner/接口矩阵已接受；54 个 HTTP、15 个 SDK、25 个发布态 TUI 决策 action、23 个 TUI mutation/AI/admin action 与 32 个 MCP 仓位相关写能力被机器门禁精确冻结，发布图 SHA 漂移也会阻断；聚合验证 `19 passed` | 补输出、raw/governed MCP 与旧 Transition Plan 语义分类，再推进 M1 持久化 |
| 2026-08-12 | 第一期 P0 | Evidence M0 输出分类首批 | 41 个高风险输出（其中 11 个直接影响仓位）被精确冻结；全部如实标记为 legacy boolean/ungated 或 research-only，机器门禁 `5 passed` | 扩展 R1–R8、动态 payload、Broker query API、raw/governed MCP，并逐项接入 Evidence |
| 2026-08-12 | 第一期 P0 | Evidence M1 persistence 首批 | schema-only/zero-seed 的 Operator Spec、Track Record、Envelope append-only ledger，strict codec、公共 exact/PIT reader 和私有幂等 append store 已实现；内存数据库 `8 passed` | 补标准 pytest-django/PostgreSQL 并发验证、审批激活和各 App adapters |
| 2026-08-12 | 第一期 P0 | Evidence M1 exact read API 首批 | Application port/facade 与三个 staff-only detail endpoint 已实现；强制 identity/version/hash/PIT，未来 cutoff 双层拒绝，写方法 405；隔离 Django/DRF `18 passed` | 定义真实用户/租户 scope 后再做 owner-scoped 授权；继续审批激活和 adapters |
| 2026-08-12 | 第一期 P0 | Evidence M1 Operator Spec lifecycle 首批 | ID-only activation、可信 definition provider/Risk Center approval port、双读防漂移、原子 receipt+activation ledger 与完整 supersession replay 已实现；DB 约束阻断双 root/双 successor；纯测试 `11 passed`、隔离仓储 `3 passed` | 实现真实 Risk Center provider/composition，补 PostgreSQL 并发验证和各 App adapters |
| 2026-08-12 | 第一期 P0 | Evidence M0 CI wiring | 决策写面冻结与 Evidence 输出清单两条机器守卫已接入 consistency-check workflow，并纳入 governance wiring 自检 | 继续扩展输出分类与统一 Evidence adapters |
| 2026-08-12 | 第一期 P0 | Evidence M1 summary contract | 紧凑 `EvidenceSummaryDTO` 已固定 hashes/分类/权限/blockers/有效期，并区分 Track Record `not_required/unavailable/empty/available`；纯测试 `5 passed` | 接入各 App 输出 DTO 与 TUI Evidence Strip |
| 2026-08-13 | 第一期 P0 | Evidence M1 Risk approval provider 首批 | Risk Center 专用 immutable subject/approval ledger、human staff 非自审批、server clock、exact/PIT selector、tamper/ORM mutation 防线已实现；纯测试 `10 passed`、隔离 component `6 passed` | 补 Research↔Risk composition、生产人工审核入口和 PostgreSQL 并发验证 |
| 2026-08-13 | 第一期 P0 | Evidence M1 Research↔Risk composition | Research 经 Risk Center Application facade 精确读取审批，二次校验 owner/capability/definition/supersession，并以 approval record hash 封存外部真源；纯单元 `3 passed` | 补 Risk 人工 subject/审批入口、PostgreSQL 并发验证和各 App adapters |
| 2026-08-13 | 第一期 P0 | Evidence M1 Data Center legacy adapter 首批 | `QuoteResponse` 已转成 content-bound legacy Envelope 与统一 summary；精确重建阻断伪造 spec/权限/lineage，始终 `legacy_unverified + DISPLAY_ONLY`；聚合纯测试 `19 passed` | 补真实 Operator Spec/持久化/consumer 接线，并逐项迁移其余 40 个输出 |
| 2026-08-13 | 第二期 P0 | Web→TUI M5 candidate/observation gate 加固 | UAT/cleanup/rollback 改为绑定 commit+matrix+graph+schema+runtime/build/manifest；旧 108/108 与旧 rollback 已改判 FAIL；observation 只接受新鲜、已提交的 production deployment attestation，禁止 caller 回填日期；observation `15 passed` | 补真实候选部署、14 日窗口、生产样本与双签 |
| 2026-08-13 | 第二期 P0 | Web→TUI M5 cleanup wave guard | 修复 post-delete/pre-cleanup SHA 不可达循环；强制双签重放、≤10 route/波、rollback manifest、串行 commit、≥48h+定时周期观察、缺陷与错误率门禁；`15 passed` | 补 cleanup wave/rollback/observation ledger recorder；无真实证据前保持 DENY |
| 2026-08-13 | 第二期 P0 | Web→TUI rollback drill v2 | 从 migration anchor 自动推导 baseline，全部 patch/manifest/graph/schema/runtime 绑定 immutable candidate；真实隔离 reverse/forward 通过 31 artifacts，actions `402→430` | 补 Django registry 往返 runtime、生产备份/恢复和最终候选重跑 |
| 2026-08-13 | 第二期 P0 | Web→TUI candidate evidence recorders | UAT/cleanup 固定执行套件并重解析 JUnit，rollback 只接受 drill v2，报告绑定 exact candidate 且不接受自报 passed；`5 passed` | 建立真实 candidate 后重跑；另补 M5-B wave/48h observation ledger recorder |

## 2026-08-12 整理结果

- 归档 50 份已完成文档：原批次 44 份，加上零循环整改、TUI IA，以及经代码与自动化证据复核完成的 MCP、Capability Catalog 和 Terminal 三条历史任务主线。
- 保留 45 份活跃文件；其中也包括尚未解除生产门禁的本地完成记录。
- Web → TUI M0–M4 历史证据已归档；M5 readiness、生产 preflight、UAT、回滚与 route closure 继续留在活跃区，直到 cutover 门禁真正解除。
- AI-Native 主计划因人工 UAT 签字与 release gate 尚未补齐继续保留；首页聊天复用任务书因前端自动化和浏览器验收资产未闭环继续保留。
- `implementation-progress-summary.md` 暂保留为总体进度入口，不按阶段总结归档。
