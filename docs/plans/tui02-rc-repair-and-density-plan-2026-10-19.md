# TUI-02 RC 修复与运行时密度收敛

本文件是 TUI-02 的有界实施补充，退出资格仍以既有迁移计划、registry 和真实验收证据为准。它不新增审批层，也不代表已部署、已观察或 Classic 已退役。

## 基线与协作窗口

本轮整合从 A 股已提交的 `fc20f43c13354c9811be9999107672bc40e2893b` 开始。A 股明确交出共享源码、必要官方投影、本地 QA 和 Git 窗口；其下一批只作私有准备，窗口归还时记录精确 HEAD、路径和结果。逐文件核对后，七个既有候选路径与原 `aed7166fe` 基线内容相同，新 Node 测试路径不存在。私有旧结果只作诊断，不沿用为新源码通过。

五项外来改动保持原状：`docs/INDEX.md`、`docs/plans/README.md`、`docs/governance/active-plan-hierarchy.json`、ITA 的 `test_ash01_settlement_regressions.py`、未跟踪的 `test_manual_trade_fee_availability.py`。不顺手修改 A 股新提交的 API、SDK、05/30 前端片段或回执测试。

## 有限批次与完成标准

| 批次 | 范围与问题 | 完成标准 |
| --- | --- | --- |
| A | RC journey 与 consistency 的历史依赖检出 | 完整检出；保留 manifest 哈希及祖先拒绝；两条 workflow 配置校验和既有正反回归通过 |
| B | IA、归属与密度报告的过期总数断言 | 明确认证用户/管理员屏集合、两项任务和六个动作归属、选定行参数映射与默认任务；不靠增加预算使测试通过 |
| C | 结果重绘后立即再次研究被 250ms 同动作 guard 丢弃 | 仅结果区新 DOM 的被动读取可立即提交；同表单、写动作、需确认读取和未知引用仍受原保护；真实研究流程完成，无增加 sleep 或 response timeout |
| D | IA runtime 页预算缺失，报告仅覆盖 published 页 | 运行时预算来自同一 IA 真源；服务端与检查器覆盖相应运行时页；保留两个 P0 主步骤及选定账户的待办行操作，不增加限额、不隐藏必需入口 |
| E | A 股 owner 合法 nullable 估值与 TUI 投影不兼容 | 独立提交；保留真实 unknown/null、合法零、缺币种和权限负例，未知事实可读但不得作估值决策；不更改 owner 响应或伪造 fixture |

A 已提交为 `fd37392af`，两条 checkout 均明确 `fetch-depth: 0`；既有 Node runtime/manifest 回归 6 项通过，完整历史祖先检查通过，错误祖先拒绝仍由原契约测试覆盖。其余批次的执行结果在本文件末尾登记，未完成前不记作通过。

## 实现约束

重复读取修复使用现有 `isPassiveRead` 判定，不改变 pending/controller、确认、幂等或 row-action options。前端产物使用官方 `build:tui` 生成，禁止拷贝旧 bundle 或手工改 manifest。

今日关注保持市场上下文与有权账户选择两个 P0 primary。选定账户的待办采用已有的上下文 supporting row-action 方式，与检查组合的选定行事实操作一致；`account_id` 必填且无默认账户，结果仍进入原 panel。运行时预算投影和 enforcement 先核对其他运行时屏的影响，避免只修统计或盲目折叠必需步骤。生产改动不引入新的配置真源、模块、架构绕过或类型债务。

## 验证、风险与回滚

按批次运行最小相关回归，生产 Python 改动必须通过逐文件增量 mypy 及全库债务检查。对同一最终工作树运行官方前端 build/check、契约与真实研究浏览器流程；不与 A 股共享数据库或队列。回归期间冻结被测源码，不把中途改动后的结果沿用。

部署资格另行冻结新候选并执行其实际 CI/RC/S6、镜像身份、schema 兼容回滚与环境隔离验证。原 RC `39156533793` 失败，其他归属的失败不由本计划冒称已解决。私有 Node 的 8 项通过仅绑定 `aed7166fe` 导出加两个文件 overlay，不是 `fc20f43c` 或后续提交的通过证据。

每批独立提交。应用前保留 preimage 与证据；回滚只针对本批明确文件/提交制定方案，不覆盖五项外来改动，不执行 reset、clean、强推或数据恢复。运行时密度改变可能影响专业模式的动作呈现，须证明 task 模式的 P0 选择与行操作完整可用。真实浏览器、Linux 认证和生产观察未验证前明确保留风险。

## 本轮执行结果

- A：完成，见上文提交与验证。
- B：三份契约测试复验 66 passed；Black/Ruff 通过。首轮 64 passed / 2 failed 的日志保留：遗漏的来源总数改为逐来源映射和唯一性验证；规范化字段默认空串按无有效默认账户核验。无生产逻辑或预算放宽。
- C：官方 build/check 与 Node 14 项通过。旧 runtime 对照为 7 passed / 1 expected failure，恰好拒绝新结果表单的立即再次读取；修复后 8 条 guard 回归全通过。真实 owner 浏览器 4 项通过（305.86 秒，含隔离 SQLite 原生 fixture），覆盖两角色、两尺寸、专业模式往返、partial/missing、网络中断显式重试、403、财务恢复及 stale 限制；4 张摘要截图已目视核对，四组记录均无外部浏览器请求或 JS 错误。证据 `.tmp/tui-rc-fc20-01/c-source-manifest.json`、`research-c.xml`、`node-c.tap`；被测四文件 raw hash 在回归后保持一致。只说明本地夹具功能，不宣称生产速度或发布资格。
- D：在 A 股有限 CI 修复 `5fa01a742e177f14bcf9a2aab67019d7e46fe6b3` 交还窗口后应用。运行时预算、规范化 enforcement 和检查器使用同一 IA 真源，保留两个 P0 操作、行参数和确认策略；未提升限额。独立静态复核批准。5 份生产文件逐一增量 mypy 及全库债务检查均通过，债务为 0。首轮类型检查的 Any 返回错误已用 `object` 参数收窄修复，没有 ignore 或基线变化。
- D 验证过程：首轮聚焦回归 128 passed / 1 failed，修正规范化空串的断言，并补无效预算反例；扩展至工作台及真实任务浏览器后为 486 passed / 4 failed。工作台的一处旧断言把管理员五个写操作全部要求 operation，改为明确的 operation/advanced 映射，确认和密钥字段断言保留。其余三项为真实组合事实返回 blocked 后无详情，须核对 A 股知识字段契约及原生 fixture，未算作通过、不增 timeout、不替换成功响应。原始日志 `density-unit-1.log`、`d-mypy-1.log`、`d-final.log/xml` 保留。
- D 构建与治理：Python 元数据改变使旧 manifest 校验正确拒绝；官方 `build:tui` 后 `check:tui` 通过，仅 manifest 投影变化，JS bundle 无变化。既有 runtime/manifest Node 6 项通过；实际密度报告覆盖 published 12 页、runtime 17 页，超限 0；模块地图及 active-plan registry 检查通过。本补充计划已登记到既有 `web-to-tui-m5` 的 supporting 文档，没有新建治理单元。
- D 最终限定回归：7 份聚焦测试及工作台原失败用例合计 131 passed（296.59 秒），格式检查通过；源码与官方 manifest 的 12 文件 raw hash 保持一致。综合回归中其余 3 条 browser 失败原样保留，不计作 D 浏览器全通过。今日关注与取消迟到响应两条 browser 通过，已检查手机今日关注截图；组合详情问题交由 E 单独修复、复验。
- E：A 股只读协查确认，exact unified 映射缺失时 owner 正确输出 `valuation_known=False` 及估值字段 null，TUI 原有必填数值校验导致整体 blocked。尚未应用修复，不将原生 fixture 改为全部 known，不放宽权限或增加 timeout。
- 未部署 VPS，未开始正式同候选 14 天观察，TUI-02 未关闭。
