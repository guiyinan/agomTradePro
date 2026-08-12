# 活跃计划索引

> 更新日期：2026-08-12
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
- [`terminal-refactor-plan-260709.md`](terminal-refactor-plan-260709.md)
- [`mcp-consolidation-remediation-plan-2026-07-09.md`](mcp-consolidation-remediation-plan-2026-07-09.md)
- [`ai-native/README.md`](ai-native/README.md)

### 外部环境或真实接入阻断

- [`qmt-live-trading-bridge-plan.md`](qmt-live-trading-bridge-plan.md)
- [`macro-sizing-multiplier-outsourcing-2026-03-31.md`](macro-sizing-multiplier-outsourcing-2026-03-31.md)

## 2026-08-12 整理结果

- 归档 44 份已完成文档：29 份顶层计划/证据和 5 个已结束阶段目录中的 15 份文档。
- 保留 51 份活跃文件；其中也包括尚未解除生产门禁的本地完成记录。
- Web → TUI M0–M4 历史证据已归档；M5 readiness、生产 preflight、UAT、回滚与 route closure 继续留在活跃区，直到 cutover 门禁真正解除。
- `implementation-progress-summary.md` 暂保留为总体进度入口，不按阶段总结归档。
