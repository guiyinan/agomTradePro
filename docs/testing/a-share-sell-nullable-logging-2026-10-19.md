# ASH03 未知盈亏 SELL 日志兼容修复（2026-10-19）

本批基于 `5c2bde1838a63c2070e283efc54c863e1dad7897`。旧 `ExecuteSellOrderUseCase` 在保存成交、更新或删除持仓、保存账户后，对 nullable 盈亏使用 `:.2f`，因此成本未知或百分比分母为零时会在末尾抛出 `TypeError`。本批只把已知值按原精度显示，未知值显示“未知”；已知零仍显示 `0.00`。金额、费用、写入顺序、结算与返回实体均未修改。

失败优先在未修改生产文件时实际取得 **6 failed / 1 passed**：四种 False/None 成本与部分/全部卖出组合、已知零成本且百分比未知，以及原 tracked 部分卖出不变量用例失败；已知盈亏平衡零值通过。修复后六文件 **68 passed**，项目四文件最小回归包 **404 passed**，均无失败、错误、跳过。测试文件的 Black 行包装发生在两轮之间，原 RED 输入和源码原件保留，测试 AST 语义不变。

该生产文件增量 mypy 和默认全库 mypy 债务检查实际均为零错误；Black/isort/Ruff、架构新增行 boundary/audit、文件规模、官方 module map 校验、current-data contracts、governance consistency 和 active-plan registry 九项检查通过。未提高预算、更新债务基线或生成投影。所有命令前后校验同一基线和原始输入字节，保护的五项外来 WIP 未变。独立 Luna max 静态复核在该范围未发现 P1/P2。

原日志、JUnit、命令结果、两个源输入清单及复核原件见 [本批证据](../../artifacts/a-share-usability/ash03-sell-nullable-2026-10-19/evidence.json)。绿色类型、最小包与治理命令的输入清单字节完全相同，证据中的 input_aliases 指向同一归档原件。命令输出保留原工作区路径与行尾，不重写成归档路径。

新用例使用完整实体和内存仓储端口，验证返回值及各端口写入；它们不证明数据库原子性或持久性。本批未运行原生 PostgreSQL，也不修复旧自动模拟绕过结算 UoW、整批重试身份或部分零成本持仓计算问题。没有执行部署、真实账户开关、券商操作或 Owner M1/M2/M3 验收；完整 ASH03、RC/S6 和实际外部对账继续开放。最小包含 SDK 自身本机 HTTP 测试，本批不声称网络围栏或零外部请求证据。


## CI 测试夹具跟进

日志修复已提交为 `e18c796a7413aa2007bfa5545b47f71f39383bc6`。其 Fast Feedback `39171728347` 的 Python 3.11/3.13 均实际出现 2 failed、325 passed、26 skipped：API 的已知零盈亏夹具未声明成本/费用已知，UoW 的成本守恒夹具也未声明成本已知。其他五条工作流实际成功；这不能把该 SHA 的 Fast Feedback 记为通过。

基于随后 TUX 独立提交的 `1a5728c07d11c8647a812a97209353a011366782`，本批先实际复现原两条失败，再仅修正两个测试文件。已知零值和原完整成本分摊公式保留；新增 False/None 成本或费用知识的 null 输出、原数值占位保留，以及部分/全部 SELL 不增加胜场的覆盖。生产默认值、掩码和写入逻辑均未修改。

两个完整模块实际 **84 passed、5 skipped**，0 failed/error；五项为现有 PostgreSQL 专用并发检查，本轮 SQLite 未执行。Black/isort/Ruff 与目标 diff 检查通过，独立 Luna max 静态审查未发现 P1/P2。生产 Python 未变，本批没有重新运行生产 mypy、项目最小包或原生 PostgreSQL，也不借用此前结果作为新一轮执行。原 RED、GREEN、JUnit、冻结输入与审查见[本批证据](../../artifacts/a-share-usability/ash03-nullable-fixtures-2026-10-19/evidence.json)。完整 ASH03、实际 Owner 验收和 RC/S6 继续开放。

本批完整治理和 active-plan registry 检查通过。固定 Gitleaks 8.24.3 配合原配置的变更内容扫描零发现；整文件扫描命中一条未改动的历史测试幂等键，已核对基线与当前第928行字节相同，原失败留存，未扩大 allowlist 或提高基线。
