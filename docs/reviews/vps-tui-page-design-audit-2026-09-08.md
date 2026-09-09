# VPS TUI 全入口设计巡检记录（2026-09-08）

巡检对象：https://demo.agomtrade.pro 。时间约 22:45–22:53（Asia/Shanghai）。登录角色：admin。部署页显示 release 20260908163105，commit 短码 b79687e46de0，应用版本 0.8.0。

> 下文为 9 月 8 日原始巡检证据；修复进度与验收见文末，原问题描述保留用于对照。

## 范围与证据口径

- 已逐一打开生产导航中的全部 24 个 canonical TUI screen（12 published + 12 runtime），读取实际渲染内容、面板几何和截图；对政策页进行完整列表翻页验证；补查 Classic 首页与 Classic 政策页。
- 默认浏览器视口 1280×720、STYLE B、导航展开；政策页另在设计规范要求的 1440×1000 下复现。测试后已恢复视口。
- 本记录的“全量”限于 TUI 一级入口。不是所有 Classic 路由、每个 action、每条数据详情、Django Admin、所有角色及全部响应式断点的穷举验收。未访问的页面不能标为通过。
- 证据来自生产浏览器，不把本地 metadata 当作已部署事实。API 成功、DOM 中存在字段、截图上能看清字段是不同层次。
- 未主动执行创建、审批、交易、删除、训练、连通性测试或 AI 提交。例外是导航 cli.terminal 后页面自行进入助手请求流程并失败，见 UX-01；是否产生账单或服务端任务需另查审计，不能声称巡检完全没有副作用。
- 只新增巡检文档和本地证据，没有修复或部署。凭证正文证据已脱敏；接入页截图未保留，避免把凭证收录到报告。

依据：[TUI 用户界面规范](../development/tui-user-facing-design-standard.md)。本报告是问题记录，不更改任何生产验收状态或治理基线。

## 优先整改清单

| 编号 | 优先级 | 已观察现象与影响 | 建议与验收标准 |
|---|---|---|---|
| UX-01 | P0 | cli.terminal 仅通过屏幕地址进入，就显示“加载中 / 发送助手请求”，随后显示“AI 服务调用失败”；巡检没有点击启动分析。 | 默认 AI action 只能展示待输入表单，导航/恢复/刷新不得自动提交。检查实际请求与审计区分真正调用和错误状态生成；以零 AI 提交请求验收。 |
| UX-02 | P0 | 我的 MCP 接入：独立令牌为圆点，但完整接入包的渲染正文含明文 Token，未点击显示也可读。遮罩在同屏失效。 | 完整包预览也须遵循显示/隐藏语义；复制仍可生成完整内容，但默认正文不暴露凭证。不要在测试产物中保存明文。 |
| UX-03 | P1 | 政策、账户、系统服务商、用户配额等表中，固定操作列过宽，覆盖左侧数据。截图出现“表头下面全是按钮”，不是单纯需要横向滚动。 | 主表全宽；操作列紧凑化，只留查看及主要动作，其余放行菜单。验证标题、对象、状态和操作能同时辨认，sticky 列不能占满可视宽。 |
| UX-04 | P1 | 多个业务工作区强制三列等宽。政策表可视 263px / 内容 1399px；Alpha 表 263/1866px；账户 263/978px；轮动配置 263/1339px。 | 宽表独占一行；摘要使用紧凑卡片；按内容决定布局，而非按面板数量均分。1280×720 与 1440×1000 都要验收。 |
| UX-05 | P1 | 创建卡、空回执、已折叠 P2 卡仍占很大面积。政策创建区与主表同高；Alpha 空候选与主清单同宽；AI 助手折叠回执约半屏。 | 创建变为工具栏入口；无回执时收起；折叠面板只占标题高度。主任务应获得主要面积。 |
| UX-06 | P1 | policy 主表实际只有事件 ID、日期、类型、档位、闸门、标题、操作；未显示审核状态、是否生效和审核理由。 | 补充审核必需列并保证可见，批准/拒绝/回滚必须有状态上下文。当前本地 registry 虽声明这些列，生产显示仍不完整；尚未确定是发布漂移还是投影裁剪。 |
| UX-07 | P1 | 政策摘要“正常”与待审核 29511、SLA 超时 1263 同屏；实盘就绪“正常”下方却只有“阻断原因代码：1 行”。 | 区分请求成功、服务健康、业务可执行。阻断状态与原因直接置顶，不能用集合长度代替。 |
| UX-08 | P1 | 政策完整列表可翻页，但显示列变为 ID、事件日期、类型、等级、闸门、标题、说明、证据链接，没有概览的行审核按钮及审核状态。 | 全量队列保留同样的筛选、状态和行操作；不要求用户回到概览或到任务区手工找 ID。 |
| UX-09 | P1 | Alpha 卡筛选表单、分页控件和内部滚动叠加；1280×720 首屏主卡看不到股票行。 | 筛选横排、分页放表尾；主工作区统一滚动；保证首屏至少看到若干股票及评分日/禁止决策标记。 |
| UX-10 | P1 | 当日情绪首条为 2026-08-13，仅供诊断列却在横向远端；脉搏 2026-08-28 仍显示未过期。 | 时效、禁止决策、观测时间与结论绑定展示。另核对排序与 freshness 阈值；本次未判定具体算法错误。 |
| UX-11 | P1 | 总览的活跃信号一个面板为 0、另一个为 6；未解释账户、组合或信号口径。宏观图“衰退”和当前判断“通缩”混用。 | 显式标注范围、时间与统计定义；同一个业务概念统一词汇。不能在缺乏证据时直接归为数据库错误。 |
| UX-12 | P1 | 资产研究统计为“2 个字段”、策略数据质量为“7 个字段”、阻断为“1 行”，关键业务含义未展开。 | 对任务关键嵌套对象定义明确展示字段与可展开详情。默认摘要要能回答数量、结果和原因。 |
| UX-13 | P1 | 每日决策流没有上下文时首屏无明确创建/恢复入口；资产研究空态没有直接检索/新建任务入口；AI 助手说直接输入却只给启动分析。 | 空态提供一个明确主操作；把输入框与任务放在首屏，避免必须借助 F9/任务菜单寻找基本操作。 |
| UX-14 | P1 | 系统健康首屏被版本信息占用，下方才显示严重调度问题和一条 qlib_predict_scores failure（耗时约 3600s）。 | 严重业务阻断与失败任务升为首屏 P0；版本详情折叠。区分基础 HTTP 健康与任务/数据就绪。 |
| UX-15 | P1 | QMT 指引高 1044px，连接/门禁/绑定分别从 y=1170/1350/1530 开始；Qlib 模型范围 y=736。 | 顶部显示当前状态、阻断与下一步，详细安装指引折叠或分步；不能把所有信息都标为 P0 后顺序堆到底部。 |
| UX-16 | P2 | 系统设置 Require用户Approval、AI 合计CostToday、准入 approved、审计 Actor/Resource 等混合代码文案；0/- 流程计数。 | 使用完整用户词汇；没有流程总数就不要显示步骤计数；实现术语保留在诊断区。 |
| UX-17 | P2 | 配额 1.0/10.0、费用 0.0、费率 0.00025/2e-05 未清楚表达量纲。 | 显示货币、次数或比例单位；费率用明确百分比/万分比，数据与存储值不变。 |
| UX-18 | P2 | AI 个人调用日志优先投影用户 ID、数据源 ID 等；提示词模板只提供更新、测试、删除，缺清晰只读预览；长机器名不利于查找。 | 列表优先时间、业务名称、状态、模型和消耗；提供可读名称及只读预览，再展示次要标识。 |
| UX-19 | P2 | 准入已批准仍显示批准/拒绝；零令牌仍显示撤销全部；轮动同时显示启用/停用；重复说明占空间。 | 根据当前状态聚焦有效动作，保留后端授权校验；合并重复提示。 |
| UX-20 | P2 | “实盘操作审计”展示的是 login_failed 用户认证记录。 | 明确表的实际范围或按实盘行为过滤；不要让标题承诺与记录含义不符。 |

## policy.workbench 专项结论

该页面确实显示不完整，至少有三个独立问题：宽度分配错误、固定操作列遮住业务数据、审核字段没有进入实际表格。1440×1000 时主表仍只有约 316px 可视宽，对应 1399px 内容；单纯放大窗口不能解决。

不是“后台只返回 8 条”：概览明确标注“前 8 条，共 29512 条”，完整列表为每页 50 条、591 页，本次成功从第 1–50 条切到第 51–100 条。真正缺口是全量队列缺少与概览一致的审核上下文和就地操作。

建议结构：顶部紧凑政策档位/积压/超时摘要及创建按钮；中部全宽待审队列，带状态、日期、档位、搜索；选中事件在同屏详情/回执区显示证据与审核结果；RSS 阅读作为按需展开的支撑区。Classic 政策页已有类型、档位、闸门、日期、搜索和队列切换，TUI 概览没有同等直接入口；应迁移任务能力，而非仅迁移 API 菜单。

[政策页截图](../../artifacts/ui-audit-2026-09-08/policy.workbench.png) · [完整列表截图](../../artifacts/ui-audit-2026-09-08/policy-full-list.png) · [Classic 对照](../../artifacts/ui-audit-2026-09-08/classic-policy.png)

## 逐页覆盖表（24/24）

| 页面 | 观察结果 | 证据 |
|---|---|---|
| 今日总览（`screen:command-center.overview`） | P1：三列宽表遮住阻断结论；“投资指挥摘要/活跃信号 0”与“账户与信号/信号 6”口径未解释；今日待办仅显示优先级、状态、事项，缺少下一步。 | [截图](../../artifacts/ui-audit-2026-09-08/command-center.overview.png) |
| 环境与脉搏（`screen:macro-regime.overview`） | P1：脉搏和情绪宽表被压缩；当日情绪实际首条为 2026-08-13；2026-08-28 脉搏观测仍标“是否过期：否”，时效阈值需核对。图中“衰退”与当前判断“通缩”术语不统一。 | [截图](../../artifacts/ui-audit-2026-09-08/macro-regime.overview.png) |
| 政策与热点（`screen:policy.workbench`） | P1：主表被操作列覆盖、审核关键列缺失、创建区过大；摘要“正常”掩盖积压；完整列表无同样的行操作。 | [截图](../../artifacts/ui-audit-2026-09-08/policy.workbench.png) |
| 每日决策流（`screen:command-center.decision-flow`） | P1：没有聚合上下文时只有空态与阻断说明，首屏没有清晰的发起决策操作；折叠趋势占据整块空白。 | [截图](../../artifacts/ui-audit-2026-09-08/command-center.decision-flow.png) |
| Beta 态势与 Alpha 选股（`screen:research.signals`） | P1：Alpha 主表可视宽 263px、内容宽 1866px；筛选与固定分页条挤占表格高度，首屏看不到股票行；空候选占同等宽度。 | [截图](../../artifacts/ui-audit-2026-09-08/research.signals.png) |
| 账户与持仓（`screen:execution.accounts`） | P1：账户表被操作按钮覆盖；创建与空回执占首排；“实盘就绪总览：正常”却仅以“阻断原因代码：1 行”交代阻断。 | [截图](../../artifacts/ui-audit-2026-09-08/execution.accounts.png) |
| 策略与风控（`screen:macro-regime.strategy`） | P1：轮动配置宽 1339px 放入 263px 区域，六个行操作挤掉业务字段；数据质量显示“7 个字段”；空 Beta Gate 没有直接恢复路径。 | [截图](../../artifacts/ui-audit-2026-09-08/macro-regime.strategy.png) |
| 事件与复盘（`screen:execution.audit`） | P2：健康表横向溢出；“实盘操作审计”实际显示登录失败事件；Actor/Resource/login_failed 等术语没有面向用户的转换。 | [截图](../../artifacts/ui-audit-2026-09-08/execution.audit.png) |
| 资产研究（`screen:research.asset-lab`） | P1：资产池/回测均为空，首屏没有资产检索或新建回测的直接主入口；统计显示“2 个字段”代替数量与比例。 | [截图](../../artifacts/ui-audit-2026-09-08/research.asset-lab.png) |
| AI 任务助手（`screen:ai-ops.terminal`） | P1：页面说“直接输入问题”，首屏却没有输入框，只有“启动分析”和两块空队列；折叠回执占半屏。未提交 AI。 | [截图](../../artifacts/ui-audit-2026-09-08/ai-ops.terminal.png) |
| 我的 AI 服务商（`screen:ai-ops.providers`） | P2：我的 AI 日志 P0 表仅显示 ID、数据源、范围、配额、用户，缺调用时间、结果、模型、用量等用户关心的信息。 | [截图](../../artifacts/ui-audit-2026-09-08/ai-ops.providers.png) |
| 数据与系统健康（`screen:api-library.data-center`） | P1：首屏版本占 354px，严重调度问题和失败任务在很下方；“系统健康：正常”没有合并业务就绪性；下方直接展示修复命令。 | [截图](../../artifacts/ui-audit-2026-09-08/api-library.data-center.png) |
| 命令行任务台（`screen:cli.terminal`） | P0：仅导航进入即出现发送助手请求加载，随后 AI 服务调用失败；未点击启动分析。P1：同步、流式、排队三种实现模式并列，中心正文空间小。 | [截图](../../artifacts/ui-audit-2026-09-08/cli.terminal.png) |
| 我的 MCP 接入（`screen:capability-router.self-service`） | P0：独立令牌字段已遮罩，但完整接入包正文直接包含同一明文凭证，无需点击“显示”。P1：已有可用令牌仍把创建放第一；完整包复制控件位于较低处。 | [脱敏文本](../../artifacts/ui-audit-2026-09-08/capability-router.self-service.json) |
| 系统 AI 服务商治理（`screen:ai-ops.system-providers`） | P1：操作列覆盖服务商名称等内容；概览出现“合计Providers/合计CostToday”，费用无单位。 | [截图](../../artifacts/ui-audit-2026-09-08/ai-ops.system-providers.png) |
| AI 用户配额（`screen:ai-ops.user-quotas`） | P1：左半屏配额表被操作列遮挡，右半屏空回执；日/月额度 1.0/10.0 没有货币或次数单位。 | [截图](../../artifacts/ui-audit-2026-09-08/ai-ops.user-quotas.png) |
| MCP 工具治理（`screen:capability-router.mcp-center`） | P2：全宽表明显优于三列卡片，但主工具列表起始 y=518，首屏主要被统计占据；工具使用机器标识，缺少简短业务用途。 | [截图](../../artifacts/ui-audit-2026-09-08/capability-router.mcp-center.png) |
| MCP 用户与令牌（`screen:capability-router.admin-access`） | P2：全宽列表与同屏回执较合理；零令牌用户也展示“撤销全部令牌”，说明重复；筛选未置于主表上方。未验证写入。 | [截图](../../artifacts/ui-audit-2026-09-08/capability-router.admin-access.png) |
| 用户准入治理（`screen:identity-access.user-governance`） | P2：全宽布局可用，但 approved 未翻译；已批准用户仍同时展示批准/拒绝，状态相关操作不聚焦；长时间戳扩大表宽。 | [截图](../../artifacts/ui-audit-2026-09-08/identity-access.user-governance.png) |
| 个人资料与交易设置（`screen:account.self-service`） | P2：个人资料优先展示内部 ID；交易费率使用小数和科学计数法 2e-05，最低佣金无货币单位，组合只有 ID。 | [截图](../../artifacts/ui-audit-2026-09-08/account.self-service.png) |
| 系统设置（`screen:system.settings`） | P1：Require用户Approval 等混合字段名难读，协议长文与运行开关混在大详情表；流程显示 0/-。 | [截图](../../artifacts/ui-audit-2026-09-08/system.settings.png) |
| Qlib 配置与训练（`screen:system.qlib-center`） | P1：无激活 profile 的提示和“Qlib 运行配置：正常”并列但不解释可否训练；第三个 P0 模型范围起始 y=736，首屏不可见。 | [截图](../../artifacts/ui-audit-2026-09-08/system.qlib-center.png) |
| QMT 接入与设置（`screen:broker-execution.qmt-setup`） | P1：1044px 接入说明置顶，连接状态 y=1170、门禁 y=1350、绑定操作 y=1530，关键状态/下一步远离首屏。 | [截图](../../artifacts/ui-audit-2026-09-08/broker-execution.qmt-setup.png) |
| 提示词模板与执行链（`screen:prompt.workbench`） | P2：全宽主表基本可读，但模板名/分类/执行模式多为代码；只有更新/测试/删除，没有清晰的只读预览；流程显示 0/-。 | [截图](../../artifacts/ui-audit-2026-09-08/prompt.workbench.png) |

## Classic 补查

只补查首页和政策页，不将其扩展为所有 Classic 路由验收。

- 首页既展示 Alpha Top 5，又在后面声称“首页不再加载 Alpha 排行数据”，口径自相矛盾；应解释不同摘要与排行的范围，或清理过时说明。
- 首页当前配置显示现金 1.0%，而页面账户为全现金、无持仓；这是比例表达疑点，需核对原始比例到百分数的转换，本次不修改金融计算。
- Classic 政策页有完整筛选工具，但“待审核队列”中的可见行主要出现“回滚/详情”；需核对队列状态与审核动作是否匹配。不能仅凭标题判定这些记录真实审核状态。

## 已验证与未验证

已验证：24 个 TUI 入口实际加载；政策在两种桌面尺寸下复现遮挡；完整列表第 2 页可达；Classic 两页对照；系统健康下方的调度阻断与失败任务；命令行进入后的失败反馈。浏览器最后一次 error/warn 日志读取为空，这不代表业务无失败。

未验证：普通角色、移动端、所有隐藏 action 和记录详情、每一条 Classic 路由、AI 请求是否计费/生成任务、真实交易与审批写回、问题代码根因。本轮没有执行生产代码改动，因此未运行 Python/mypy 或业务回归测试；文档不构成修复验收。

建议整改顺序：先关闭导航自动 AI 与默认凭证明文问题；再修复共用表格操作列遮挡/布局；以 policy 和 Alpha 为首批验收页；随后补齐状态、时效、空态与单位文案。验收要求不仅是字段存在于 DOM，而是用户能看清对象、理解状态并完成主任务。


## 修复阶段与验收（2026-09-09）

目标：修复本报告列出的界面缺陷，并将审核对象、业务阻断、数据时效和下一步操作呈现在可读、可操作的页面中。业务数据本身的积压、任务失败与历史缺数不以视觉修改伪装为已解决。

已实现：UX-01/02 被动导航与凭证隐藏；UX-03/04/05/09 共用内容布局、全宽表、紧凑行菜单和按内容收缩；UX-06/07/08 政策审核字段、积压状态、全量筛选与行操作；UX-10/11 最新情绪观测、Pulse 时效重算与统计口径说明；UX-12 嵌套业务字段和阻断原因；UX-13 资产筛选/发起分析/AI 输入表单；UX-14/15 关键状态优先、接入说明按需展开；UX-16/17 术语和单位；UX-18 日志列与提示词只读预览；UX-19 条件行操作；UX-20 操作审计范围标题。Classic 百分比、Alpha 入口文案和按事件状态显示审核动作同步修复。

回归范围：TUI 配置加载、表单/行操作/分页、模板与凭证投影、Pulse current 读契约、Classic 政策动作状态、桌面布局。浏览器插件不可用，使用仓库现有 Playwright 浏览器测试。

本地验证：

- `pytest tests/unit/test_tui_workbench.py tests/api/test_pulse_api.py --nomigrations --reuse-db`：**342 passed**。较早的启用迁移回归覆盖 338 项中的 335 项，3 项旧配置预期随后修订；最终关闭迁移运行用于缩短重复数据库准备时间，并非新增数据库迁移。
- `npm run test:tui-js`：**62 passed**，包含实际 Chromium 的分页、确认、空态、凭证和布局回归。
- `npm run check:tui`：构建产物与当前源文件、manifest 一致。
- 17 个生产 Python 文件 Black/isort/Ruff/mypy 增量检查通过；最终两项详情/文案改动追加 mypy 回归通过。全量 mypy 债务为 0。
- current-data freshness：**53 surface(s)**；模板迁移清单 **196 templates / 117 route pages**，通过。

生产验证：

- 两轮遍历全部 **24/24 canonical TUI screen**；页面脚本异常 0、面板加载错误 0、整页横向溢出 0、默认可见凭证明文 0。入口覆盖数据见 [coverage.json](../../artifacts/ui-audit-2026-09-08/after/coverage.json)。本结论不等于业务数据全部就绪。
- 政策主表可视宽从约 **263px** 增至 **953px**（1280×720）；摘要改为一行四项关键状态卡，审核对象/状态/操作在首屏可见，完整的 9 列可横向滚动查看。1440×1000 同步验证。
- 在线操作链通过：行菜单可见并能展开；完整列表服务端翻页；只读事件详情返回本页并展开回执；按标题/正文关键词与待审状态筛选；提示词全文只读预览；CLI 输入表单与刷新无 AI 提交。
- AI 助手进入页面只读取待处理队列，未提交聊天/推理；MCP 接入包默认遮罩，未将凭证明文写入截图。
- Pulse 2026-08-28 指标已显示过期；情绪摘要为 2026-09-07 最新观测并标注仅供诊断；健康页首屏显示调度预警和 Qlib 评分失败。
- HTTPS 健康检查全部返回 **200**；web、PostgreSQL、Redis、Celery 等容器运行正常。
- TUI 与 Classic 政策页静态资源版本更新为 `20260909-audit`，已有页面需整页刷新（Ctrl+Shift+R）。

[新版政策页](../../artifacts/ui-audit-2026-09-08/after/policy.workbench.png) · [1440px 验收](../../artifacts/ui-audit-2026-09-08/after/policy-1440.png) · [在线交互证据](../../artifacts/ui-audit-2026-09-08/after/interactions.json)

完成项：本报告 UX-01～UX-20 对应的页面整改及 Classic 补查缺陷已实现并热更新。没有待上线的页面修复。未做生产审批/删除/交易写回；写操作的参数、确认、回执与刷新通过本地模拟回归，不以只读线上巡检代替真实成交验收。普通角色与移动端全入口仍未穷举。

业务状态保留：29511 条待审、1263 条超时、历史数据不足与每日验收调度阻断属于后台业务/运维事项。本次修复其可见性与文案，没有批量审批事件、伪造数据或隐去失败。

部署与回滚：采用 selected-file code-only 热更新，未运行迁移、恢复数据库或重建 Docker。原文件保存在 VPS `/opt/agomtradepro/manual-file-backups/`：

- `/opt/agomtradepro/manual-file-backups/20260909001601`（deploy.log）
- `/opt/agomtradepro/manual-file-backups/20260909001808`（deploy-manifest.log）
- `/opt/agomtradepro/manual-file-backups/20260909002805`（deploy-refinement.log）
- `/opt/agomtradepro/manual-file-backups/20260909003226`（deploy-search-label.log）
- `/opt/agomtradepro/manual-file-backups/20260909003455`（deploy-menu.log）
- `/opt/agomtradepro/manual-file-backups/20260909003900`（deploy-cache-version.log）

需要整体回滚时按上述备份的时间倒序恢复对应文件，覆盖 release 与容器中的文件，恢复匹配 staticfiles 文件后重启 web；仅恢复最后一批不能撤销整轮修复。文件清单与 SHA-256 验证记录保留在 `artifacts/ui-audit-2026-09-08/deploy*.log`。工作分支：`dev/fix-tui-page-audit`；用户既有 `.gitignore` 改动未修改。
