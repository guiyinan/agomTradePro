# 仓库治理债务收口计划

更新时间：2026-07-19

## 阶段目标

在 provider/adapter 主线结束后，用独立治理批次收口依赖双真源、生成物污染与 AGENTS 模块清单漂移；类型债务保持独立批次，避免把运行代码重构与治理修改混在一起。

## 完成标准

- `pyproject.toml` 成为运行和开发依赖唯一人工维护真源。
- `requirements-prod.txt` 与 `requirements-dev.txt` 由脚本确定性生成，并有测试阻止漂移。
- 生产 lock 覆盖每个 canonical runtime dependency，且固定版本满足声明范围。
- 根目录不再残留 `test_db_*.sqlite3`、`tmp_tui_*.log` 或 crash dump，`tmp/` 不再承载 vendored 代码。
- SQLite 测试数据库写入系统临时目录，不再污染仓库根目录。
- AGENTS 的模块目录与治理基线一致，不再出现已并入 Data Center 的 Market Data 旧模块。

## 回归范围

- 依赖生成脚本及 requirements/lock 契约。
- `core.settings.development_sqlite` 导入与 SQLite 测试数据库路径。
- 全量 guardrails、governance consistency、Ruff 与 diff check。

## 独立后续主线

- mypy `ignore_errors` 豁免缩减与基线错误修复。
- 其余 P1 大文件按 `docs/archive/plans/large-file-remediation-2026-07-14.md` 继续拆分。

## 验证记录

- 依赖投影、lock 覆盖、AGENTS 模块清单与仓库卫生聚焦护栏：5 项通过。
- 固定最小回归包：253 项通过。
- 全量 guardrails 首轮 138 项通过，仅暴露静态测试计数旧基线；核实当前工作树后将 machine baseline 更新为 6969。
- 重基线后 governance consistency 为 0 违规，原失败的 guardrail 目标用例复跑通过。
