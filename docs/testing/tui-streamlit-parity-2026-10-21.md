# TUI 仪表盘等价验收（2026-10-21）

本批基点为 `54cd6b8d411ec6a8ca58424330e94a7971f4ff3e`，对应本提交中的 TUI/API 补丁。Owner 已批准先补齐 TUI 验收，再退出 Streamlit；本页记录开发验证，不代表最终冻结 SHA 的完整 RC、S6 或生产 UAT。未部署、未启动观察 T0，TUI-02 尚未关闭。

## 行为与边界

- 宏观四象限显示四项真实概率、当前标记及增长/通胀轴说明；源观测日与查询截止日分开。过期、阻断或概率不完整时不展示可用于决策的当前分布。置信度明确使用百分数单位。
- 本人组合资产历史使用实际每日记录，支持近 30/90/180/365 天与全部历史，空历史保持为空。金额与收益率单位分开；后创建账户不进入早期收益率分母，未知或非正初始资金使收益率保持未知。
- 本人信号状态与最近最多五项已批准信号复用现有归属查询，与全局管理分开；保持认证、权限及原有接口字段。
- 保留 `/api/dashboard/v1/*`、登录保护的 `/dashboard/` 和 Classic 模板。本批尚未删除 Streamlit、修改依赖或创建 S6 测试身份。

## 实际验证

| 检查 | 结果与限制 |
| --- | --- |
| 第一轮选定回归 | 出现 metadata schema 与旧 mock 兼容问题后主动中断；没有完整终态 JUnit，不计通过 |
| 第二轮同选集 | 437 passed、3 failed；新面板预期及测试间缓存节流污染已修正，生产节流未放宽 |
| 第三轮同选集 | 440 passed、0 failure/error/skip，440 个精确 `(classname, name)` 身份，943.60 秒 |
| 宏观浏览器用例 | 2 passed；包含四项概率、小于 1 的百分数、窄屏与契约漂移关闭行为；使用合成浏览器夹具 |
| 后续方法拆分 | 为满足 1000 非空行增量门禁，将三个宏观方法移入专用 mixin；完整方法 AST、剩余类体与格式化前后 AST 等价；代理回报随后定向回归 3 passed，但该次原始日志未归档，不计为可独立复核证据 |
| 类型与风格 | 修改的生产文件增量 mypy 通过；拆分后全库类型债务 0；Black/isort/Ruff 通过 |
| 合同及生成物 | current-data、TUI 静态合同、metadata 一致性、copy-density、presentation、迁移清单、模块图、架构审计及最终 runtime build/check 通过；统一 Data Center 投影检查通过 |
| 测试层级投影 | 从基点归档加本批七项测试文件覆盖，在私有源执行原 `scripts/test_tier_inventory.py --write --check`；排除共享树中两项外部未提交测试后生成通过 |

440 项完整回归发生在纯 AST 方法拆分之前，不冒称拆分后的完整重跑。第三轮选集为四个 API 文件（dashboard edges/performance parity/signal parity、regime edges）及四个 unit 文件（workbench、performance curve、signal parity、regime parity）。最终发布候选仍需绑定同一干净 SHA 完成全部必需 CI、累计 Manual Full Fast、独立 Publication PostgreSQL、完整正式 RC 与全新 S6。

## 本机原件索引

以下路径均为仓库内 Git 忽略的本机原件，未声称远端持有；完整日志和源码副本不提交 Git。除另列路径外，前缀为 `.tmp/tui-rc4-followup/`。

| 原件 | SHA-256 |
| --- | --- |
| `parity-regression-r1.log` | `d9af89f6c6ac9ce82878d5dad7c204af23109a72b7d166956567ed1dad98f12f` |
| `parity-regression-r2.log` | `339e3885ce3e2e5e09662aaa308dfc18e7fa6ee59d6a744acb55887ca30d22ea` |
| `parity-regression-r3.log` | `bf361cd6d06371ef80de1f7b43f41c518bdd7cad5bce87c1760091b4c5c42511` |
| `.tmp/tui-parity-qa-r3/junit.xml` | `d143848fd3abe61f5212ec51f5138d402994ea8e9e2fec24793632ea1a884602` |
| `regime-mixin-extract-r1/ast-proof.json` | `dbd067ac5895bab72d8605b7b5387849120d36371213ed74994ba1f84f9eed49` |
| `regime-mixin-extract-r1/format-proof.json` | `3e6125b724ca365186ef4c2f3b3247946c35e96933770f89b436db1c2d56a73b` |
| `parity-mypy-debt-after-extract-r3.log` | `def6c561b37227470bcda90c8450d9837ca85dd34af34d05e7d6af2afdf85ab1` |
| `parity-all-projections-r3.log` | `89b87be00e7c7a54e5ade8ea83ecf3953f8e032a5a367d7826ea8ca1931d37ec` |
| `parity-tier-candidate-source-r1/manifest.json` | `537421d46fa50547c1679de3b88c38bdd2054f85d18fb53f8e0079ad6d168144` |

保留失败和中断原件。合成账号及夹具只证明测试行为，不能替代生产逐项验收或独立人类复核；`production_manifest_review_satisfied=false`。后续百分比单位修正、侧车退出与依赖锁更新各自提交，A 股窗口按明确交接执行；新的有限基点必须显式登记，不能拼接不同 SHA 的资格证据。

16 份原件另存本机忽略归档 `artifacts/tui02-parity-evidence-20261021-r1/`，父代理逐项复核原件与副本为 0 mismatch。索引 `.tmp/tui-rc4-followup/parity-evidence-prep-r1/archive-index.json` 的 SHA-256 为 `e23c126418fca42ca53a1eddf32f1579a7e7978e82ef954480bfe0ada5d89444`；原临时副本保留。

## 后续百分比单位修正验证

本批基点为 `26984881f25fa42ebd8d5b39fa111660b56c8d39`。组合摘要明确区分 `fraction` 与 `percent`，不改 API 数值：0.8 置信度显示 80%，0.5 个百分数显示 0.5%。schema 与手动校验一致，未声明单位的旧规则保持兼容。局部字段校验移入已有 helper，主文件从 1131 降至 1108 非空行。

实际回归 39 passed、0 failure/error/skip（339 deselected，696.64 秒），含六种单位校验及三项宏观投影；JUnit 已独立核对 39 个唯一身份。这是新增的可复核结果，不追认原先未归档的三项口头报告。之后仅整理 import，非 import AST 与 import 绑定集合等价。增量类型、全库类型债务、Black/isort/Ruff、407 条静态合同、metadata 一致性、模块图、精准候选测试清单及 runtime build/check 均通过。

新浏览器用例先在旧构建复现 0.5% 显示错误（2 passed、1 failed），保留失败原件；新构建同三项用例为 3 passed、0 failure/skip，96.779 秒。此处仍是合成夹具开发验证，最终同 SHA RC/S6 与生产验收尚待完成。

本机索引 `.tmp/tui-rc4-followup/percent-development-evidence-index-r1.json`，SHA-256 `552927ec493918ab8427653da3af043971ddb6d9ba41b4ff728f0c14a58fe93b`，记录各原件哈希及失败边界。第一批 269 的 push CI 五项成功、Security 失败；对应安全 artifact 实际确认八项均为 Pillow 12.3.0，修复版本 13.0.0。侧车/依赖退出尚未采用，不能宣称安全问题已闭合。

## 卡片区间的实际操作验证

基点 `7525c424193acd9a10c43250c84be8c88c6a7065` 的沉浸式首页隐藏动作栏，组合卡片未配置区间筛选；“打开”默认运行全部历史。新增实际浏览器用例先得到 2 passed、1 failed，确认该交互阻断。当前修复在卡片内提供近30/90/180/365天及全部历史，更新面板并在打开完整图表时保留已应用范围。复用既有 filter_fields/dashboardFilters，只允许明确声明的被动辅助图表与安全 selector，不增加接口、状态机或权限；high/critical 凭据与写入/确认操作保持不可筛选。原列表行为也参与回归。

最终定向单测为 32 个唯一身份、32 passed、0 failure/error/skip；7 项实际浏览器用例全部通过，70.517 秒，覆盖区间提交与打开、空历史无伪点、本人信号面板、原列表筛选、宏观分布和百分比。增量类型和全库类型债务为 0，风格、metadata 一致性、runtime build/check 通过。静态合同从旧的清空参数字面量更新为限定 selector 参数投影及敏感字段隔离，共 409 条通过；没有删除守卫换取通过。

中间浏览器轮次 6 passed、1 failed，原因是夹具遗漏实际 action 的 effect=read；对齐夹具后通过，产品的 read 守卫未放宽。新增单测曾错误读取 IA 根键，31 passed、1 failed 后修正；所有失败原件保留。原始索引 `.tmp/tui-rc4-followup/actionable-development-evidence-index-r1.json`，SHA-256 `fe50beadc60caed3cab7ab9c20d8e48b0b9d7b73aae1bb7521156f0c7d767c4b`。这仍是合成浏览器夹具与真实 owner API 测试分别绑定的开发证据，不等于生产 UAT、独立人类复核或最终同 SHA RC/S6。侧车退出独立提交，具体部署仍须 Owner 确认。

## 累计失败修复：Sector Admin 自动发现（2026-10-22）

累计 Fast 的两种 Python 版本均暴露 Admin 注册入口未被 Django 自动发现。本批增加 `apps/sector/admin.py`，仅导出既有四个类型化 Admin，注册装饰器仍只位于原入口；不重复注册，也不恢复已退役成分编辑。新增自动发现与 Admin app-list 解析反例。

精确 648 隔离基线的原生 PostgreSQL `sector_admin` 组实际 31/31 passed，0 failure/error/skip，151.94 秒；包含原 Admin 失败及三个真实费用管理浏览器用例。R1 整批后来在另一组失败，仍保持 failed，不把这 31 项称为整批通过。最终 R3 中相同生产 shim 的增量 mypy 与默认全库类型债务均为 0，未改基线；八候选 Black 26.10.1、isort、Ruff 通过。共享采用父版本为 `3e379eee7813061024088e787f3425ea8056af9e`，相关前件只读 LF 等价，官方 module map 重建/校验、循环与精确一文件十五新增行架构/audit 检查均通过。

本机原件沿既有事项追加：`.tmp/ash-tux-compat-quality/prepared-r1/results/receipt.json` SHA-256 `28afe28c386ec66f6e1b1853884946bfae335b3b72277bb28f2ba06933356c32`；最终类型回执 `prepared-r3/results/receipt.json` SHA-256 `0034c08c411dc5398f829335f68e069d2ee880e2b1e8427dad3af4ff23e6d17f`；共享采用及生成检查回执 `sector-shared-adoption/receipt.json` SHA-256 `b7c462f817c3df8edc596153637d3965849937d36c5c0b6996108bcbecde4356`。不作为新 SHA 完整 CI、RC/S6 或生产 M1。

## 累计失败修复：任务入口、权限矩阵与 Pulse 时钟

三项测试对齐已交付的四个任务入口和新增 Alpha 管理映射：逐项校验真实 screen/P0、研究参数入口、普通用户权限拒绝与受保护路径全集；浏览器实际点击账户巡检任务，保留只读请求、同源、角色和窄屏断言。事务浏览器复用既有权限时钟保留夹具。Pulse 仓储测试固定本地日期并推进到过期窗口，验证源日期保持不变、年龄增长及 stale 从 false 变为 true；生产新鲜度规则不改。

原生 PostgreSQL R2 对应组实际 7/7 passed，0 failure/error/skip，59.41 秒；实际浏览器覆盖普通用户/管理员与 1440×1000/390×844 四组合。R1 的旧 sidebar 选择器失败仍保留；R2 后续 Qlib 组失败也仍记为整批 failed。R2 通过回执 SHA-256 `9c1f3e76d0eebb654db466ab554187a6cdcdf3304a93a643116ebc35abd43779`。

上述结果绑定精确 648 隔离源码和冻结候选，相关前件与本次采用父版本只读 LF 等价；全量基线恢复、未模拟 HTTP、失败记录及本机归档沿既有事项保留。它们不是新提交的累计 CI、正式 RC/S6 或生产验收。

## 累计失败修复：估值来源与 Qlib 失败关闭夹具

三项测试文件对齐真实合同：估值夹具发布对应事实日的明确时区源时间，保留过期/低质量和旧有效事实回退；非有限复权因子应明确报错并零产物。三项 Qlib builder 测试各自建立所需类型化 csi300 配置，消除执行顺序依赖；预测旧数据测试显式启用仅本测试运行配置，并验证过期检查先于 Pandas 加载。没有启用生产 Qlib、外部抓取或放宽失败关闭。

原生 PostgreSQL 最终 R3 对应组实际 65/65 passed，0 failure/error/skip，13.40 秒；收集与 JUnit 身份一致。此前 R2 的 62 passed / 3 failed 保留。R3 只重跑受改动影响的这一组及未完成的生产 shim 类型门，不重复累加此前 31/7 的通过。最终 manifest SHA-256 `256c00f236b92c9944a8e4f22927923c9a6cab9c448c0e7317ab9cd113f32ab3`，通过回执 SHA-256 `0034c08c411dc5398f829335f68e069d2ee880e2b1e8427dad3af4ff23e6d17f`。

上述结果绑定精确 648 隔离源码和冻结候选，相关前件与本次采用父版本只读 LF 等价；全量基线恢复、未模拟 HTTP、失败记录及本机归档沿既有事项保留。它们不是新提交的累计 CI、正式 RC/S6 或生产验收。
