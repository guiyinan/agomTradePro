# R2 测试语义迁移映射

> 日期：2026-07-20
> 状态：已完成
> 原则：参数化只替代同型断言；权限、状态码、Content-Type、数据库副作用、错误分支与用户流程不得因减行而消失。

## 1. 执行前基线

| 测试族 | 文件/函数基线 | 结构调查结论 | R2 迁移目标 |
|---|---:|---|---|
| API edge | 31 文件 / 306 test functions | 27 文件重复定义 `api_client/auth_user/authenticated_client`；53 个测试落入 14 个常量差异型结构簇 | 共享 `tests/api/conftest.py`；只把同型 root/auth/validation 契约迁入参数矩阵，保留端点副作用测试 |
| TUI workbench | 1 文件 / 7,765 行 / 209 test functions（218 collected cases） | 仅 17 个函数属于结构重复；主要冗余是资源源码的逐条字符串断言，不是业务行为测试重复 | 静态源码契约迁入独立 scanner + 声明式规则；服务、API、权限、运行时与用户流程测试保留 |
| AI capability owner | 26 文件 / 120 test functions | 74 个测试落入 15 个 manifest 投影结构簇 | 用全量 governed manifest 投影矩阵替代逐 owner 手写 metadata 投影测试；保留路由与业务特例 |
| SDK registry owner | 33 文件 / 164 test functions | 常量归一后仅 2 个测试形成同型簇，其余均验证 owner 特有 handler、preview、RBAC、幂等或审计语义 | 只参数化已证实的同型簇；不为追求删行强并不等价的 owner 行为 |
| Readiness | 8 文件 / 151 test functions | 11 个测试落入 4 个结构簇；其余覆盖不同 evidence、scheduler、repair 与 acceptance 分支 | 参数化 scheduler 安全字段和 final-acceptance 缺失证据矩阵；公共 evidence builder 下沉到 support |

## 2. 原测试语义到新载体

| 原语义 | 新载体 | 必须保持的断言 |
|---|---|---|
| 每个 API edge 文件的用户/client fixture | `tests/api/conftest.py` + 特殊文件局部 override | 用户角色、认证方式、账户审批状态 |
| API root 广告端点 | API root contract matrix | HTTP 200、JSON Content-Type、每个广告 key/value |
| 未认证/非管理员访问 | API permission matrix 或端点特有测试 | 401/403 集合与数据库零副作用 |
| TUI JS/CSS/HTML 静态存在/禁止字符串 | `scripts/check_tui_static_contracts.py` 与版本库声明式规则 | source path、required/forbidden、失败时精确规则 ID |
| TUI 服务、metadata validator、action runner、API | 原行为测试或小型参数矩阵 | 输入、输出、权限、数据库副作用、错误映射 |
| governed MCP → AI catalog metadata | 全量 manifest projection matrix | capability key、legacy replacement、risk、confirmation、idempotency、audit tags、roles、schema |
| SDK owner runtime dispatch | 原 owner 测试 | handler 参数、preview/confirm、RBAC、幂等、审计事件 |
| readiness scheduler 安全变体 | scheduler field matrix | 具体 failure code、operator action、acceptance gate |
| readiness 缺失证据变体 | required evidence matrix | blocking reason、remaining/accepted 状态、历史 evidence 兼容 |

## 3. 删除门槛

原测试只有在以下条件全部满足后才删除：

1. 新载体能指向相同或更强的输入与断言；
2. 新 case 有稳定、可读的 pytest ID；
3. 原测试族与新测试族在替换前后局部回归均通过；
4. collected case 数变化有语义映射说明，不用 case 数替代覆盖充分性；
5. 没有新增 skip/xfail。

## 4. 明确不做

- 不把 SDK owner 特有 handler 行为压成只检查 manifest 字段的弱测试。
- 不删除 TUI 服务、API、权限、运行时或用户主流程测试。
- 不与 R2 并行修改产品运行代码、SDK/MCP 运行契约或 readiness 生产实现。

## 5. 执行结果

| 测试族 | 收敛结果 | 保留的语义边界 |
|---|---|---|
| API edge | 27 组通用 fixture 下沉到 `tests/api/conftest.py`；17 个 root 与 7 个权限 case 迁入矩阵 | 特殊 staff/account/session fixture、验证错误与数据库副作用仍在原文件 |
| TUI workbench | 22 个纯源码字符串测试迁为 407 条带稳定 ID 的静态规则；CI consistency workflow 直接执行 scanner | 服务、metadata validator、API、权限、action runner 与用户流程测试未迁移 |
| AI capability owner | 114 个逐 owner metadata 投影函数由 317 个 governed manifest 参数 case 覆盖；21 个只含重复投影的文件删除 | prompt/realtime/regime/sector/signal 的 owner 特例测试保留 |
| SDK registry owner | 2 个同型 prompt catalog case 参数化；共享 fixture 显式隔离 staff 角色 | 其余 handler、preview、RBAC、幂等与审计行为不合并 |
| Readiness | 11 个同型分支迁为 required-evidence 与 scheduler 矩阵；formal window builder 进入 `tests/support` | repair、checkpoint、inspection、历史 evidence 与 acceptance 特例原位保留 |

仓库静态 test function 治理基线从 7,056 收紧到 6,903；参数 case 数继续由 pytest collection 观察，不以静态函数数量代替覆盖判断。
