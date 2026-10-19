# TUI RC 回归收尾整改（2026-10-20）

本轮基线为 `ecb59591e3696b89d0f66457a66993c07efe7e84`，不可移动标签
`tui02-observation-ecb59591e369`。正式 RC `39288001593` 已失败；该标签只记录验证候选，
不构成部署、生产观察 T0 或 TUI-02 关闭。独立 Publication PostgreSQL `39288001502` 成功。

## 已取得的结果

| 验证 | 实际结果 | 解释边界 |
| --- | --- | --- |
| RC 用户流程 | 89 passed，0 failures/errors/skipped | 包含 ReDoc、TUI 主任务、M5；不能替代完整 RC |
| 独立 Publication PostgreSQL | success | 仅绑定 ecb 候选，不能移用于后续修复 SHA |
| Architecture / Consistency | success | 各 job 的原始结果保留 |
| Secrets Scan | failure | 发现的值必须逐项分类，不能批量忽略或缩小正式扫描历史 |
| Critical PostgreSQL | failure | 用例 call 通过；teardown 缺少显式 TEST.NAME，被已有身份保护拒绝 |
| 增量质量门 | failure | 注册期望遗漏已提交的 AutomaticTradingInvocationModel；不包含未合入 G1 |
| Fast Python 3.11 / 3.13 | 同为 8 failed、9396 passed、353 skipped、119 errors、56 subtests | 119 error 包含 29 flush、7 username 唯一键、83 ContentType 唯一键；不能算作 119 个独立业务故障 |
| Nightly 全量 unit | 25 分钟 step timeout | 最后到 87%，已有 20 个 F；没有最终节点清单或 pytest summary，不能记为通过或仅预算不足 |

## 分批目标及验证边界

1. **历史证据误报**：仅对精确证据路径中完整一行的路径到 SHA-256 映射添加规则级 AND 例外；
   Git 对象等其他已证明项仅用精确历史 fingerprint。保留未证明项、原扫描失败和正式全历史入口。
   同版本 scanner 必须复扫，并用同路径的真实凭据形状、同行额外 key、非 hex、错误字段/路径及新提交
   凭据反例证明仍能检出。当前私有实扫还剩 38 条 generic 命中，整改尚未通过。
2. **测试数据库身份及模型注册**：critical 专用 settings 显式绑定 workflow 预建测试库，拒绝缺失、
   空白、同源库和非 PostgreSQL；保留原数据库身份、singleton 和清理保护。注册列表只补 ecb 已有模型。
   先跑反例/注册契约及增量类型、债务与适用生成投影，再由正式 PostgreSQL 工作流验证清理。
3. **事务测试清理**：在全新 PID 隔离 SQLite 库先跑首个 pending 节点，再跑 CI 紧邻前驱与该节点。
   必须取得实际内层异常，区分缺失 singleton、身份拒绝和 SQL 错误。禁止手动补种 singleton、删除
   ContentType/用户行掩盖问题或移除身份保护。修复后再复测权限与两项迁移失败，确认是否独立问题。
4. **导入投影契约**：对确实意图投影的用例使用真实 preview、显式 excluded 及两个 fingerprint；
   原余额、源时间和幂等断言保留。旧 mock 不再命中的 rollback 用例必须沿当前真实写入或投影边界，
   证明 facts-first 合同及无意外经济副作用，不能修改生产行为来迁就旧断言。
5. **全量 unit 诊断**：保留完整 unit 选择、coverage 和单用例 300 秒上限，增加节点级输出；
   可依据本轮 87% 的实际进度采用有限 35 分钟 step 预算取得完整失败明细。此项只是诊断改动，
   20 个未定位 F 必须取得明细并解决，不能通过延时或省略测试宣布通过。

每组以独立、可回退的 commit 提交直接相关源码、测试、必要投影及精简说明。完整日志、JUnit、
脚本和重复源码仅保存在忽略目录或本机归档，索引必须注明本机可用，不能声称远端已持有。

## 并行约束

- A 股 Root 持有共享 Source/index/Git；TUI 仅在明确列出的短窗口合入自身路径，保护四项已有 WIP。
- 本地重 QA 串行交接；独立私有候选可以做只读静态审计。不得使用 A 股原生 PostgreSQL 测试库。
- 尚未共享的 G1 模型、迁移及 HTTP 入口不进入本轮 TUI 修复候选；后续由 A 股重新验证和合入。
- 旧候选的成功 job 与失败原件均保留。修复改变 SHA 后，必须重新冻结标签并取得该 SHA 的完整证据。

## 完成标准、剩余风险与回滚

本阶段完成标准是：上述失败都有可复现的修复或明确的真实阻断结论；新不可变候选完整 RC、独立
Publication PostgreSQL 和全新 S6 结果均绑定同一 SHA。S6 只在一次全新 prepare 的隔离 PostgreSQL
中创建已获授权的临时 superuser，随机口令仅通过内存及闭合匿名 FD 3 传递，不进入 Git、聊天、文件、
环境或日志。合成身份不构成独立人工复核，不能把 production manifest review 状态伪造为通过。

当前未完成项包括：剩余安全命中定性、SQLite 顺序实证、导入测试修复、污染后三项失败复测、Nightly
20 项失败明细、新候选完整验证及 S6。完整回归通过前，没有部署资格结论。

每组回滚点是该组 commit 的前一 SHA；不改写历史、不破坏外部 WIP。S6 若失败只按 attempt 所有权
清理其隔离资源，不删除生产卷或仅凭 untagged 判断可删镜像。生产服务、账户、迁移、认证和观察 T0
均不在本阶段写入范围；具体部署与回滚方案准备完整后，另交用户确认。
