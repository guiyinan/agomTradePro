# TUI 速度、分页与连续操作整改方案

日期：2026-09-08。依据：两份同日 TUI review；用户明确授权制定方案、设置 goal 并落地。

归属现有 `tui-usability-governance` 主线。本次是新增仓库整改，不重开历史 TUX-01～05，不改变生产 TUI-02、Classic 清理或决策门禁。治理归属见 `governance/active_plan_registry.json`；下表只作为本次实施与证据清单。

## 完成标准与实施批次

| 批次 | 对应 review | 本次仓库交付与退出门 |
|---|---|---|
| A 统一分页 | 专项 P1/P2/P3/P5 | 统一页大小/范围/页码控件；未知总量不显示 0；本地筛选标明范围；概览摘要有更多入口，可筛选完整清单本地分段浏览；分页合同风险以测试或显式能力不足状态收口 |
| B 加载体验 | 专项慢体验、原 R8 | 服务端翻页保留表格，失败保留原页；纯翻页不刷新无关徽标；P0 有效内容完成后再启动辅助加载；实际首屏完成计时与部分失败提示 |
| C 工作状态 | 专项 P4、原 R3/R4 | 返回恢复非敏感表单、筛选、页大小和定位；显式对象参数进入目标动作，危险动作只预填；不持久化令牌、密码、文件或缓存敏感结果 |
| D 操作语义 | 原 R1/R2 | F5 仅执行安全读取或观察已有运行；进度称为已操作而非业务完成，业务受阻/失败不计完成；长任务可重新读取同一运行 |
| E 一致性 | 原 R5/R6/R7 | 缺回执的行操作提供同屏回执；下一步说明和流程导航一致；F6/Esc 文案准确；适用 schema/metadata/template 与规范同步 |

先以浏览器回归固定失败场景，再实现通用前端行为；业务语义不进入 terminal。每批验证后记录证据，不以夹具耗时充当线上提速结论。

## 验证

- 前端：`npm run build:tui`、`npm run check:tui`、`npm run test:tui-js`；增补翻页、失败恢复、只读刷新、草稿与筛选保留的浏览器测试。
- TUI/IA 及模板：按改动执行 `tests/unit/test_tui_workbench.py`、IA/metadata 契约、source consistency、`web_template_migration_inventory.py --check`。
- 修改生产 Python 时执行增量 mypy/debt、Black/isort/Ruff 和所属结果投影回归。
- 代表性浏览器视口验证：布局不溢出，分页与操作入口可达；截图仅使用合成测试数据。

## 风险、边界与回滚

状态只保存在当前页面会话内，恢复前仍重新加载已授权 screen；业务结果重新查询，保留原观测时间与决策禁止标记。先不引入跨用户结果缓存和无限滚动。

本次不更改未知的 owner API 分页实现；发现契约不能保证翻页时明确限制入口并记录待办，不伪造后续页。线上请求瀑布、冷/热 P95、真实角色 UAT 与部署属于后续验证边界，不用单元测试制造结果。

回滚以本开发分支的维护源码、生成 bundle、样式及对应 metadata 为同一批次；不涉及数据库恢复或生产配置回退。保留两份原始 review。

## 实施记录

- 初始化：当前基准 `285733cb6`；建立执行 goal；准备浏览器回归与实现。
- 实现分支：`dev/fix-tui-speed-pagination-ux`。本次未提交、未合并、未部署。

### 已完成的仓库整改

| 批次 | 实际交付 |
|---|---|
| A | 通用列表默认 20 条，支持 20/50/100、范围和页码输入；游标不伪造总数；F7 明示当前页/已加载范围；候选范围与浏览页大小分离；摘要可打开完整列表并返回；无分页契约的数组保留全部返回行并标记客户端分页 |
| B | 只读翻页保留当前表格，失败可重试；避免翻页触发无关徽标刷新；P0 返回后调度辅助面板；分开 shell/P0 计时；展示部分失败；补修面板失败后筛选提交事件绑定 |
| C | 当前页面会话内恢复安全草稿、筛选、页大小和列表位置；重新加载权限及业务数据；密码、令牌、文件不恢复；行详情跳转沿用已声明字段/来源映射预填，写入不自动提交 |
| D | F5 只重复安全读取或观察原运行编号；AI 普通请求不因刷新再次提交；进度改为“本次已操作”，按日期区分并在查询上下文变化时清除；HTTP 状态和业务 outcome 分离，blocked/partial/failed 不记为已操作 |
| E | 政策、研究信号、策略风控、资产研究和个人 AI 服务商补充同屏操作回执；每日流程的说明与导航顺序对齐；F6/Esc、页面就绪及数据接收时间文案明确；规范和模板清单同步 |

没有新增 metadata 属性，使用现有 `result_panel_key`/`filter_fields` 等声明；运行结果增加有界 `outcome`，已有 pager 使用 `client_side` 表达完整集合。未引入新的业务完成状态机、跨用户结果缓存或不受控的自动写入。

### 已验证证据

- 前端完整回归：**58 passed**；最终面板失败恢复修正后 focused **1 passed**（属于同一套件的复跑，不与完整套件重复累计）。
- TUI Workbench、IA、面板筛选：**335 passed**，使用 `--nomigrations`。
- Terminal Agent、SDK client、内部 SSL 跳转：**48 passed**，使用 `--nomigrations`。
- build/check、增量 mypy 两个生产文件、mypy debt ceiling、Black/isort/Ruff、metadata source consistency、action copy/density、active plan registry、模板迁移清单均通过。
- 生产 HTML/CSS/JS 加合成响应：1440×1000、1280×800、1024×768 均可完成 45 条候选的 20/20/5 浏览；无页面横向溢出和脚本错误。已人工查看截图。
- 可复核的源码指纹、验证范围和截图索引：[`evidence.json`](../testing/tui-ux-2026-09-08/evidence.json)；[1440px 截图](../testing/tui-ux-2026-09-08/pagination-1440x1000.png)。

### 未完成与剩余风险

- 本次仓库整改完成不等于线上性能已达标。未采集生产冷/热请求瀑布、P95、真实角色操作耗时，也未部署。
- F7 仍为明确标注范围的本地筛选；全数据集搜索仍使用 owner 已有查询能力，没有虚构统一全量搜索。
- 分页合同覆盖通用全数组和已声明分页路径，不代表所有 owner 服务在生产规模下都已逐一压测；游标是否可逆、总数是否精确仍由 owner 提供。
- 返回恢复仅覆盖当前页面会话；关闭标签页/整页重载后不恢复草稿，敏感输入必须重新填写。
- 测试未重放全部历史迁移：诊断确认耗时在 Django migration state 重建后停止了该尝试，改为模型建表。未修改 migration，不能把本次结果作为迁移验收。
- 本机没有约定名称的 `agomtradepro` 环境，使用可用的 Python 3.13 / Django 5.2.12。Python 3.11 CI 和真实生产权限/数据仍需后续验证。
- 不改变生产 TUI-02、Classic cleanup、证据与决策门禁状态。部署后的真实性能测量和候选验收是后续工作。

### 提交与 CI 修正（2026-09-08）

用户随后授权提交、合并和部署。实现提交 `1092b2f46`、报告提交 `a7daddd2c` 已推送，PR #22 包含开发分支已有的候选选择器和估值源时间修复。

CI 发现分页浏览器测试过早读取旧表格，已改为等待目标分页信息，并用延迟响应覆盖该竞争；完整前端复跑 58/58。同步拆分源码的静态合同与模板指纹对应的遥测目录。呈现检查按现行 Task Deep-Link Rules 允许一个带明确标签且可编辑的屏幕地址控件，其他内部地址仍拒绝；新增惰性控件与业务结果泄露反例，6/6 测试、407 条静态合同和呈现检查通过。生产候选绑定与真实观察将随部署单独记录。

完整 main 差异 CI 还发现前置提交的超长文件增长及治理指纹未同步。将 dashboard selector/panel-kind 校验与持久化 JSON 数值解析拆至各自模块，原导入接口兼容；模型结构与迁移不变。19 项定向回归、增量类型与全量债务检查通过。重新生成 Data Center 两份清单；复核 published graph 仅七处下一步提示文案变化后更新 MCP/decision 图指纹，动作集合和写入权限检查通过。估值纯读取 API 的正常样本补齐真实测试源时间，独立回归通过；没有用抓取时间为业务历史数据兜底。

扩大回归定位出账户 inventory 事务测试清除了 `django_migrations` 的 account 记录，却未在结束时恢复，污染随后 MigrationExecutor 的状态图。为该测试模块增加精确记录恢复 fixture；迁移单独运行 1/1，通过原先污染模块后顺序运行 8/8（正常迁移路径，265.85 秒），无需修改生产迁移。拆分后的元数据/actionability/IA 回归 72/72，runtime manifest 重新生成。

真实 Django 浏览器门禁进一步发现：延迟读取的折叠 P2 面板仍保留初始 loading 标记。改为明确的“展开后读取业务数据”，真正开始请求后再显示 loading；不通过放宽浏览器断言绕过。`run_live_server_pytest.py` 的 8 个生产模板布局场景全部通过（32.29 秒）。前述截图及 `evidence.json` 保留最初仓库整改快照，后续发布以部署记录的候选与 runtime hash 为准。

### 合并、部署与候选重绑定（2026-09-08）

PR [#22](https://github.com/guiyinan/agomTradePro/pull/22) 已合并；部署源为 `b79687e46de05725c7cbea2cd135a040141ca331`，release `20260908163105`，镜像 `sha256:22661f49c8ded9b040da18e524e93dba1c24558de7a1f67a8fff2a8b63d06562`。后续证据文档提交不改变线上源码身份。前述“未部署”与环境限制描述属于仓库整改时的历史状态。

从独立、干净的 main 工作区运行 `scripts/deploy-vps.ps1 -Upgrade -GitBranch main`，部署及强制验证退出码均为 0。生产 PostgreSQL/Redis 容器保持原身份，数据卷与密钥保留；部署前备份已下载并核对 SHA-256，未执行恢复。HTTPS health/readiness、迁移与 canonical schema、TUI registry、运行镜像身份、Qlib、Celery 和容器健康检查通过；线上 JS/CSS 内容指纹与部署源码一致。验证细节见[部署记录](../deployment/main-vps-upgrade-2026-09-08-b79687e4.json)。

PR 全部 CI 与合并后的主线 CI 通过，覆盖 Python 3.11/3.13。前端 58/58、真实 Django 浏览器布局 8/8、正常迁移顺序回归 8/8；Data Center Domain 2710/2710（95.23%）、Valuation Domain 1557/1557（97.56%），类型与质量门禁通过。

通过官方脚本重绑定真实部署候选，清除旧候选验收数据。A real retained migration sample is not yet available; the new observation time gate has not started. No previous candidate sample or synthetic zero is inherited. 14 天自然观察、真实角色 UAT、生产冷/热请求瀑布与 P95、完整业务主任务验收仍未完成，不能据部署成功宣称线上性能达标。TUI-02、Classic cleanup 与 DATA-02 决策数据验收继续 DENY；未执行业务数据刷新、权限/审批写入或运行时启用。

只读采集器返回 `migration_series_count_unavailable`；未绑定 retained sample 或精确 14 天到期时间。[待采样记录](../deployment/tui02-production-observation-pending-2026-09-08-b79687e4.json) 保留原始采集输出和门禁结果。候选日期范围仅为发布登记，不等于真实计时已开始。
