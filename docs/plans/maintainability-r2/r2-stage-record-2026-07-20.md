# R2 测试收敛阶段记录

> 日期：2026-07-20
> 分支：`dev/refactor-maintainability-r2-r3-lite`
> 状态：完成

## 完成范围

1. API edge 通用认证夹具下沉到 API 测试目录，root 与权限契约改为具名参数矩阵。
2. TUI 纯源码字符串断言迁为版本化声明文件和独立 scanner，并接入 consistency CI。
3. AI capability metadata 以全部 governed manifest 为输入做投影验证，只删除逐 owner 的等价重复；SDK owner 仅合并两个同型 prompt catalog case。
4. readiness final-acceptance 缺失证据和 scheduler 安全约束改为具名矩阵，formal window evidence builder 复用到 support。
5. owner runtime 测试显式隔离 dispatcher staff 角色，移除对环境变量和执行顺序的隐式依赖。

## 规模结果

| 候选族 | 执行前 | 执行后 | 变化 |
|---|---:|---:|---:|
| API edge + 新公共载体 | 9,593 | 9,170 | -423 |
| TUI Python 测试 | 7,765 | 7,161 | -604 |
| TUI scanner + 声明式规则 | 0 | 3,915 | +3,915 |
| AI owner + manifest projection | 8,051 | 516 | -7,535 |
| SDK owner + shared support | 11,124 | 11,131 | +7 |
| Readiness + support | 9,952 | 9,670 | -282 |
| 合计 | 46,485 | 41,563 | -4,922 |

声明式 TUI 规则是可审阅的机器契约，不计作 Python 测试压缩；全仓 Git 变更仍以最终 diff 为准。静态 test function 治理基线由 7,056 收紧为 6,903。

## 语义与回滚

- 详细的原语义到新载体映射见 `r2-test-migration-map-2026-07-20.md`。
- 未修改产品运行代码、SDK/MCP 对外契约或 readiness 生产实现。
- API、TUI、AI capability、SDK owner、readiness 五个测试族均可按路径独立回滚；TUI scanner 与规则文件必须成对回滚。
- 特殊权限、数据库副作用、错误分支、preview/confirm、RBAC、幂等和审计测试没有为了减行而合并。

## 回归证据

专项回归：

- API edge/root/auth：331 passed（另有 167 个非目标 API case deselected）。
- TUI workbench：196 passed；静态 scanner：407 rules / 5 sources；scanner unit：2 passed。
- AI capability：615 passed。
- SDK owner：171 passed；其中角色隔离修复后的高风险子集 34 passed。
- readiness：151 passed。
- governance consistency：0 violation。

固定最小回归包（TUI workbench、terminal agent service、SDK client、internal SSL redirect）：231 passed。

unit/API/integration 广域回归使用 4 worker 首轮得到 6,853 passed、14 skipped；并行 SQLite 建库产生 64 个 `auth_user` 缺表错误及级联失败，因此该轮不作为失败归因依据。串行 `--last-failed` 复核后发现一个 R3-lite 新模块 discovery bridge 缺失，补充 `apps/valuation/models.py` 后专项通过；其余 15 个失败在各自测试文件隔离进程中仍可复现：

- macro data sync：6 failed / 4 passed，表现为同步计数、canonical indicator 查询、PIT 查询契约漂移；
- regime workflow：3 failed / 4 passed，测试数据未进入当前 canonical indicator 查询，最终落入 `No fallback regime available`；
- strategy execute flow：6 failed，旧测试 fixture 使用的 `dominant_regime` 已违反当前数据库 check constraint。

上述三组均未触达 R2/R3-lite 改动路径，作为既有集成测试债务登记，不在本批混入 macro/regime/strategy 业务修复。R2 专项、固定最小回归和治理护栏均为绿色。
