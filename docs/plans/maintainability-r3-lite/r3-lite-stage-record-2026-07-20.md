# R3-lite 估值 Owner 拆分阶段记录

> 日期：2026-07-20
> 分支：`dev/refactor-maintainability-r2-r3-lite`
> 状态：完成；专项与固定回归绿色，既有跨模块集成债务已显式登记

## 决策

R3-lite 只修复当前最痛的 valuation 归属错位，不提前拆 advisor/recommendation，也不以追求仓库总行数为目标。估值快照值对象、纯价格带规则、正式估值质量/新鲜度策略以及估值选择/兜底用例归 `apps.valuation`；`decision_rhythm` 只作为现有消费者和冻结 ORM 表的适配方。

## 已完成

1. 新建完整四层模块 `apps.valuation`，Domain 不依赖 Django 或其他业务 app。
2. `ValuationMethod`、`ValuationSnapshot`、`create_valuation_snapshot`、`ValuationSnapshotService` 迁为 canonical 定义；旧 `apps.decision_rhythm.domain.valuation_*` import 保持对象 identity。
3. 将正式估值正值检查、legacy 排除、质量 flag、新鲜度窗口、data-center fact 价格带补全迁入纯 Domain policy。
4. Application 通过 formal valuation、snapshot、valuation fact、market price 四个 Protocol 编排，不直接导入 ORM 或其他 app Infrastructure。
5. asset_analysis/data_center/realtime 访问下沉到 valuation Infrastructure；冻结的 `decision_valuation_snapshot` 表由 decision_rhythm Infrastructure adapter 实现端口。
6. `feature_providers.py` 从 1,236 行降至 796 行，仅保留薄兼容 composition 与 factory；估值实现不再藏在推荐特征聚合文件中。
7. 注册第 39 个业务模块并更新模块形状、依赖边预算与零循环治理基线。

## 明确未做

- 不移动 `ValuationSnapshotModel`、`InvestmentRecommendationModel` 或任何历史 migration；现有 `app_label="decision_rhythm"`、ContentType、权限和表名不变。
- 不修改 `/api/valuation/**`、`decision_rhythm` namespace、route name 或响应契约。
- 不拆 advisor/recommendation，不切 dashboard、terminal、agent_runtime 到新的物理 API owner。
- 不新增双写、数据回填或数据库 migration，因此回滚不依赖恢复数据库。

## 规模与维护性

| 范围 | 执行前 | 执行后 | 说明 |
|---|---:|---:|---|
| `feature_providers.py` | 1,236 | 796 | 估值实现迁出，factory 保持 |
| 旧 valuation entities/services | 1,273 | 886 | 仅保留 recommendation/approval 定义与 valuation 兼容 export |
| 新 valuation owner | 0 | 842 | 四层 owner、纯规则、Protocol 与外部适配器 |
| decision_rhythm valuation adapters | 0 | 95 | 冻结 ORM 端口与兼容 composition |
| 合计 | 2,509 | 2,619 | +110；本批收益是归属、依赖方向和可发现性，不宣称减行收益 |

## 依赖与回滚

- app import graph 为 39 模块、192 条边、0 双向依赖、0 cycle component。
- 方向为 `decision_rhythm -> valuation`；valuation 不 import decision_rhythm。
- 回滚点是新 owner、旧 facade/composition、设置与治理基线同一组代码变更；没有状态变更。

## 回归证据

- 新 valuation owner + 旧 valuation service + feature provider：47 passed。
- decision_rhythm 结构、workspace/recommendation consumer、API guardrail：99 passed。
- Django system check：0 issue。
- Architecture boundary/audit：0 violation。
- Module cycle：0 cycle；governance consistency：0 violation。
- 决策工作台 E2E：29 passed。
- 固定最小回归包：231 passed。
- unit/API/integration 广域回归：4 worker 首轮 6,853 passed、14 skipped；并行 SQLite 建库造成 64 个缺表错误，串行归因后修复了本批唯一问题（valuation Django discovery bridge）。剩余 15 个失败可在未包含本批路径的 macro/regime/strategy 测试文件中隔离复现，详情见 R2 阶段记录，不归因为 valuation owner 拆分。

## 收口结论

R3-lite 的完成边界是 valuation 归位、旧消费者兼容、零状态迁移和架构护栏通过；不是宣称仓库既有集成测试全部无债务。下一步不自动展开完整 R3，优先以独立维护批次修复已登记的 canonical macro fixture、regime fallback fixture 与 strategy 枚举 fixture。
