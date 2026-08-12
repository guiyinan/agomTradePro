# R2 + R3-lite 稳定性收口记录

> 日期：2026-07-20
> 分支：`dev/refactor-maintainability-r2-r3-lite`
> 状态：完成

## 收口范围

本批只处理 R2 + R3-lite 广域回归中隔离复现的三个既有集成契约债务，不继续展开完整 R3，也不修改估值、宏观或 Regime 金融算法。

## 修复结果

1. Macro integration fixture 显式建立测试源的 indicator catalog/unit rule，避免生产 `akshare` canonical source 配置屏蔽 `source="test"` 事实；多指标 mock 改为按请求指标返回，消除重复计数。
2. Regime 单次与历史批量计算显式透传 `data_source`；`calculate_history` 补齐与 `CalculateRegimeRequest` 一致的可选数据源参数。
3. Strategy integration fixture 写入 canonical `Overheat`，不再用已由 migration 归一化、且违反数据库 check constraint 的 `HG` 写入 `RegimeLog`。策略规则层对历史四象限简码的兼容保持不变。

## 验证证据

- macro data sync integration：10 passed；
- regime workflow integration：7 passed；
- strategy execute flow integration：6 passed；
- regime/application + macro provider + strategy provider 联动单测：27 passed；
- Ruff：0 violation；Black：4 个改动文件格式通过；
- unit/API/integration 全量串行回归：7,022 passed、14 skipped，0 failed（单进程，避免 SQLite 并行建库噪声）。

## 风险与回滚

- 没有 migration、表结构、运行时配置或外部 API path 变更。
- 生产代码仅为 `calculate_history` 增加向后兼容的可选参数并透传到现有请求对象。
- 回滚时可独立撤销本批测试 fixture 与该可选参数，不影响已提交的 R2/R3-lite owner 拆分。
