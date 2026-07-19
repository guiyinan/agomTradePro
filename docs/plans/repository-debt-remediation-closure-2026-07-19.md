# 仓库架构与治理债务阶段收口记录

更新时间：2026-07-19

## 收口结论

本轮整改已完成大文件拆分、provider/adapter 抽象收敛、公共数值解析、依赖真源、仓库卫生、文档对齐与 mypy 历史债务七条主线。运行代码、治理基线、阶段文档和回归证据已同步，不再保留“代码已改、治理仍放行旧债”的双重状态。

## 阶段记录

1. [大文件风险整改](large-file-remediation-2026-07-14.md)：完成 Decision Rhythm 与 Data Center 首批 P1 巨型文件拆分，稳定入口保留为兼容 facade。
2. [Provider / Adapter 抽象收敛](provider-abstraction-convergence-2026-07-18.md)：Data Center 使用 canonical registry/runtime/composition，Macro 旧 adapter、failover 与兼容桥退役。
3. [仓库治理债务收口](repository-governance-debt-2026-07-19.md)：依赖由 `pyproject.toml` 单一维护，requirements 改为生成投影，临时产物和 vendored `tmp/` 代码清理，AGENTS 模块清单对齐。
4. [Mypy 类型债务收口](mypy-debt-remediation-2026-07-19.md)：整模块 `ignore_errors` 与历史错误基线均降为零，第三方无类型边界改用精确行级例外。

## 最终验收

- Decision Rhythm 与 Data Center 已无 1700+ 非空行 Python 文件；治理扫描未发现大文件预算增长。
- Data Center/Macro 旧 provider、registry、adapter 源文件已删除，结构护栏禁止旧路径和旧符号回流。
- App 内 `_safe_float` 重复定义为零，统一入口为 `shared.numeric.safe_float`。
- 依赖投影检查、Ruff、diff check、架构边界和 governance consistency 均通过。
- 本轮最终 Account/Macro 回归为 113 项单元测试与 51 项 API/集成测试通过；零豁免、空基线和治理回归 35 项通过。
- 固定最小回归包已在 provider 与大文件阶段完成，合计 253 项通过。

## 遗留测试债务

Data Center 结构契约与行为测试放入同一 pytest 进程时仍存在共享状态污染，表现为顺序敏感且失败用例漂移。当前验收口径固定为两个独立 pytest 调用；结构契约与行为包分别运行均通过。该问题应作为后续独立测试隔离批次处理，不回滚本轮 provider 收敛结果。

## 回滚边界

- 大文件拆分应连同 facade、owner 模块、结构测试和治理基线条目成组回滚。
- Provider 收敛应连同 canonical registry/runtime/composition、Macro 调用链和旧路径删除成组回滚，不单独恢复兼容桥。
- 依赖真源与 mypy 零豁免由 CI 护栏保护；如需调整必须修改生成器或精确类型边界，不得恢复人工双真源或整模块忽略。
