# 数据可靠性修复计划

## Summary
- 不放宽现有 guard：legacy macro、stale quote、stale Pulse、trade-date adjusted Alpha 仍然不能变成 actionable。
- 新增一条“决策数据修复流水线”，先补齐上游数据，再重算 Pulse/Alpha，最后用现有 strict contracts 复验。
- 当前目标日期默认取本地日期 `2026-04-21`；若上游确实未发布当日数据，系统必须明确报告 blocked，而不是用 `2026-04-20` 冒充可交易建议。

## Key Changes
- 在 Data Center 增加 `RepairDecisionDataReliabilityUseCase`，统一执行 macro freshness、quote freshness、pulse stale guard、dashboard alpha readiness 四段修复，并返回 `ready/blocked/failed` 报告。
- 增加默认 provider 引导：若只存在 Tushare，则幂等创建 `AKShare Public`，用于 `CN_PMI`、`CN_CPI_NATIONAL_YOY` 等无 token 公共宏观数据和 EastMoney 行情适配。
- 修复 provider 选择策略：`CN_PMI` 等 AKShare 专属指标必须优先走 `akshare`，不能默认落到 Tushare legacy；`510300.SH`、`000300.SH` stale 时必须通过 `SyncQuoteUseCase`/`SyncPriceUseCase` 持久化刷新结果。
- 改造 Pulse 刷新路径：Pulse 按需重算前先调用 Data Center 决策输入刷新，而不是只刷新旧 macro app；重算后必须复验 `is_reliable`、`stale_indicator_count`、`stale_indicator_codes`。
- 改造 Alpha readiness：若 Qlib calendar 最新日小于目标日，先运行现有 Qlib build 流程刷新到目标日，再对 scoped universe `cn-portfolio_market-4104d1d15fbd0ab9` 重新跑 `qlib_predict_scores`；只有 `asof_date == requested_trade_date` 且 scope verified 时才给 actionable 推荐。

## Interfaces
- 新增管理命令：`python manage.py repair_decision_data_reliability --target-date 2026-04-21 --portfolio-id 366 --strict`。
- 新增只限管理员的 POST API：`/api/data-center/decision-reliability/repair/`，入参为 `target_date`、`portfolio_id`、`asset_codes`、`strict`，出参为四段 readiness 报告。
- SDK/MCP 增加同名 write/unsafe 工具，返回同一报告结构，字段包含 `macro_status`、`quote_status`、`pulse_status`、`alpha_status`、`must_not_use_for_decision`、`blocked_reasons`。
- 文档更新 `docs/development/data-reliability-remediation-checklist-2026-04-21.md` 和 `docs/INDEX.md`，记录真实决策前必须通过的验收口径。

## Test Plan
- Provider bootstrap：无 AKShare 时幂等创建；已有 provider 不重复、不覆盖用户配置。
- Macro freshness：`CN_PMI` 缺失时触发 AKShare sync；成功后默认查询不再返回 `legacy_blocked`；失败时保持 blocked 并报告 provider error。
- Quote freshness：`510300.SH` stale 时触发 quote sync 并持久化；strict freshness 成功返回 200，失败保持 409。
- Pulse guard：Data Center 输入刷新后重算 Pulse；仍有 stale indicators 时 action recommendation 继续 blocked，全部新鲜时才解除。
- Alpha readiness：Qlib 最新日为 `2026-04-20` 时触发 build；若刷新到 `2026-04-21` 则 scoped Alpha actionable，否则保持 research-only 并说明上游未发布。
- E2E/UAT：跑 API、SDK、MCP 三条链路，确认四段报告一致，Dashboard 不再在数据未达标时给 actionable 推荐。

## Assumptions
- 优先修系统的数据修复能力，不通过手工改数据库绕过 freshness。
- 如果 Tushare/AKShare 在 `2026-04-21` 尚未发布当日数据，正确结果是明确 blocked，而不是降级成真实决策。
- 当前本地组合继续以 `portfolio_id=366`、scope hash `4104d1d15fbd0ab9` 作为验收样本。
