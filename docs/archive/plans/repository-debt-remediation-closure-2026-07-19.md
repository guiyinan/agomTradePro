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

## 遗留测试债务（已收口，2026-07-19 测试隔离批次）

Data Center 结构契约与行为测试混跑时的顺序敏感污染已定位并修复，验收口径不再要求拆成两个独立 pytest 调用。

- 根因：`tests/unit/data_center/test_phase3_provider_adapters.py` 多个用例 `monkeypatch.setattr("apps.data_center.infrastructure.legacy_sdk_bridge.get_akshare_module", ...)`；`apps/data_center/infrastructure/_provider_adapter_akshare.py` 在方法内延迟导入 `akshare_eastmoney_gateway` / `akshare_general_gateway`，而这两个 gateway 模块顶层以 `from ...legacy_sdk_bridge import get_akshare_module` 绑定该名称。若 gateway 模块的进程内首次导入恰好落在 monkeypatch 窗口内，就会永久绑定假 callable（模块进入 `sys.modules` 缓存），此后所有依赖真实绑定的用例按顺序随机失败，失败用例随测试排序漂移。
- 修复：新增 session 级 autouse fixture（初始位于 `tests/unit/data_center/conftest.py`，同日上移至顶层 `tests/conftest.py`，见下），在任何测试运行前抢先导入上述两个 gateway 模块，把真实绑定钉在 patch 窗口之外。纯测试侧改动，未改 `apps/` 代码，未删测、未 skip、未降断言。
- 验证：修复前以随机排序复现失败（种子 6/8 失败 `test_capital_flow_uses_bj_market_for_bj_stocks`，且"投毒用例 + 受害者"配对正向必败、反向通过）；修复后 12 个随机种子混跑全部 311 项通过，混合命令连续 3 次（含一次 `-p no:randomly`）通过，`tests/unit/data_center` 单独运行通过，4 个结构契约文件回归通过。
- 通用化收口（2026-07-19 后续）："monkeypatch 窗口内首次延迟导入"的 seam 预热 fixture 已上移至顶层 `tests/conftest.py`（`tests/unit/equity/test_market_data_repository_adapter.py` patch 同一 seam，曾面临同型风险）；`provider_runtime._global_registry` 进程级单例改由顶层 conftest 的函数级 autouse fixture 在每个测试前后调用 `reset_registry()` 隔离，治理台 admin_client 在测试库上构建的 registry 不再跨测试泄漏。验证：`tests/unit/data_center` + 结构契约 268 项、含 equity 的混合批次 430 项、registry 直接引用套件（api/integration/events/provider abstraction）66 项全部通过。

## 回滚边界

- 大文件拆分应连同 facade、owner 模块、结构测试和治理基线条目成组回滚。
- Provider 收敛应连同 canonical registry/runtime/composition、Macro 调用链和旧路径删除成组回滚，不单独恢复兼容桥。
- 依赖真源与 mypy 零豁免由 CI 护栏保护；如需调整必须修改生成器或精确类型边界，不得恢复人工双真源或整模块忽略。
