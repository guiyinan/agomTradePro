# Web → TUI M5 浏览器 UAT 证据（2026-07-27）

## 结论

live-server 浏览器套件 `15 passed`：其中 5 条验证代表性主任务和三个 viewport，矩阵
驱动 deep-link 用例逐一验证 108/108 个 migrated A/B route page 的管理员 TUI
screen/action 可解析；新增角色化直读用例通过普通用户、operator、admin 三类账号真实
执行 71 个无需业务 fixture 的 route page 主 action；参数化读取用例完成 9 个 route；
策略与个人 AI 服务商生命周期分别完成 3 个和 2 个 route；Policy 管理员创建流程覆盖
3 个 route；配额、Beta Gate 与筛选确认流程覆盖 5 个 route；本地可复现夹具支持的详情
与生命周期流程覆盖 11 个 route；最后 2 条通过一次性 Playwright SQLite 中加密保存的
受控 DeepSeek Provider，真实完成 Sentiment 分析和 Terminal Agent chat/config。与原有
代表性任务去重后，机器 cutover gate 的主任务 UAT 覆盖为 108/108。人工复核浏览器
控制台无 error。

本报告已形成 108 个迁移 route page 的计划角色与主路径 UAT 证明，但不替代空态、错误态、
旧 URL、生产遥测、缺陷窗口、registry 备份和审批证据。M5 总体仍为 DENY。

## 自动化范围

测试文件：
`tests/playwright/tests/uat/test_web_to_tui_m5.py`

| 场景 | 结果 |
|---|---|
| 管理员读取账户列表与账户详情 | 通过 |
| 创建账户缺参后进入补填流程 | 通过 |
| 写操作展示影响说明并要求确认 | 通过 |
| 取消确认后账户数量不变且无目标账户 | 通过 |
| operator 可读取智能任务队列 | 通过 |
| 普通用户不能通过深链访问 operator 任务 | 通过 |
| 1440×900 无横向溢出、任务面板可用 | 通过 |
| 1024×768 无横向溢出、任务面板可用 | 通过 |
| 390×844 无横向溢出、任务面板可用 | 通过 |
| 可见按钮均有可访问名称 | 通过 |
| 108/108 个 migrated route 的主 screen/action 深链可解析 | 通过 |
| 71 个无需业务 fixture 的 route 按最小权限角色真实执行主 read action | 通过 |
| 9 个 route 使用合法路径/查询参数完成 read action | 通过 |
| 策略创建→详情→确认式更新 | 通过，覆盖 3 个 route |
| 个人 AI 服务商无密钥创建→详情→确认式更新 | 通过，覆盖 2 个 route |
| Policy 事件、关键词、RSS 源确认式创建并回读 | 通过，覆盖 3 个 route |
| 决策配额配置、Beta Gate 创建/测试、股票/基金筛选 | 通过，覆盖 5 个 route |
| Agent/Alpha/Audit/Backtest/Factor 本地详情与生命周期 | 通过，覆盖 11 个 route |
| Sentiment 通过受控外部 AI 完成文本分析 | 通过，覆盖 1 个 route；非 mock，明确排除 AI 失败结果 |
| Terminal Agent 通过受控外部 AI 返回非空回复 | 通过，覆盖 1 个 route；非 mock，额度门禁生效 |
| 账户 P0 持仓读取不创建或同步默认账户 | 通过；改用 `/api/account/positions/read-only/` |

最终结果：

```text
15 passed in 359.58s
total=15 executed=15 passed=15 skipped=0 failures=0 errors=0
```

可重复执行方式：

1. 为 `core.settings.playwright` 指定一次性 `AGOM_PLAYWRIGHT_DB_PATH`；
2. 对该库执行全量 migration；
3. 预置 `admin`、`operator` group 用户和普通用户；
4. 通过现有 Application UseCase 在该库创建加密的受控外部 AI Provider，并为 Terminal
   测试用户设置系统兜底额度；不得把凭据写入仓库文件或命令输出；
5. 使用 `scripts/run_live_server_pytest.py` 启动受管 live server；
6. 设置 `AGOM_M5_EXTERNAL_AI_UAT=1`，从仓库根 pytest 配置执行下列套件，并传入
   `--reuse-db`：

```bash
python scripts/run_live_server_pytest.py \
  --suite-name web-to-tui-m5-uat \
  --port 8766 \
  --base-url http://127.0.0.1:8766 \
  --settings-module core.settings.playwright \
  --min-tests 15 \
  --junitxml reports/quality/web-to-tui-m5-uat.xml \
  -- \
  tests/playwright/tests/uat/test_web_to_tui_m5.py \
  --reuse-db --browser chromium --screenshot=only-on-failure -q
```

未设置 `AGOM_M5_EXTERNAL_AI_UAT=1` 时，两条外部 AI 用例会显式 skip，不能据此生成
108/108 证据。

Playwright pytest 与 live server 是两个进程；本套件只经真实 HTTP/UI 验证，不在测试
进程内用 ORM 断言 live-server 状态。用户、角色和账户夹具在服务器启动前写入同一个
一次性 SQLite 文件，避免测试数据库与服务器数据库分叉。

矩阵深链巡检对 action execution 做浏览器层拦截，只验证 screen/action 定位，不把
外部数据源速度或模拟响应当作任务成功。它首次执行时发现 `command-center.overview` 的 M4
summary/chart actions 没有 immersive dashboard panels；修复 IA、compiler、published
graph 和 runtime 定位逻辑后，108 条深链全部通过。该巡检不计入下面的主任务完成数。

角色化直读用例不拦截 action execution。它先按矩阵计划受众选择普通用户、operator 或
admin，再从该角色实际可见的 screen metadata 中筛选 `GET + read/admin risk + 无必填参数 +
无确认` 的主 action，最终真实执行 71 个 route page。首次运行发现 4 个矩阵 audience
误标为 `authenticated`，已依据 screen/action 和后端权限修正为 `admin`。

参数化读取用例使用 metadata 已声明的字段和合法值完成资产筛选、Alpha 排名、有效风险
策略、个股估值、宏观趋势、政策事件和模拟盘通知/持仓/交易。资产筛选在隔离库没有
current regime 时会回退到非法 `Unknown`，因此用例显式选择表单允许的 `Recovery` 并
验证正常空态；没有把 500 当作成功。

两个生命周期用例都从真实 action form 打开 F9 任务面板、提交、通过确认对话框并解析
写入回执 ID，再用详情深链和确认式更新验证对象归属及写后结果。个人 AI 服务商首次
运行发现 serializer 允许省略 API Key、Application 用例却要求该关键字参数的 502，已将
Application 默认值统一为空字符串并补 API 契约测试；测试没有写入假密钥。

Policy 管理员用例通过真实确认对话框分别创建事件、关键词和 RSS 源，并重新读取列表
验证持久化结果。治理与筛选用例真实更新决策配额、创建 Beta Gate 配置、执行资产测试、
股票筛选和基金多维筛选。首次执行时发现整个“可执行操作”分组使用 sticky 定位，长分组
会覆盖后续表单并拦截点击；已取消整组 sticky，保留视觉优先级，且未使用 Playwright
`force=True` 绕过产品缺陷。

本地详情与生命周期用例在 Playwright 专用 SQLite 中预置 Agent task/proposal、Alpha
candidate、Audit attribution 和 Factor config；浏览器只通过真实 TUI/HTTP 消费这些
夹具。用例随后真实创建、读取、更新并检查 Alpha Trigger，运行并读取 Backtest，执行
Factor 计算。它发现 Backtest ViewSet 把 Interface 专用 `run_async` 默认字段错误传入
Application DTO 导致 502，现已在 Interface 边界移除并补 API 回归。Factor 夹具使用
合法且总和为 1.0 的权重，空 universe 返回正常 0 行结果，不把业务错误冒充成功。

完整矩阵巡检会在同一用户下执行大量真实 action。Playwright 专用 settings 继续启用
限流类，但提高隔离环境阈值，避免重复证据运行累计触发与业务无关的 429；生产限流配置
未修改。账户首屏用例也改为先等待 workbench 明确进入“读取完成”，再断言 P0 grid，
避免并发 panel 尚未完成时的 5 秒竞态。

完整套件复跑时还发现 `execution.accounts` 的 P0 持仓 panel 使用旧 `/api/account/positions/`
读取会触发 ledger sync，并在只读页面创建“默认组合”。IA、runtime patch、compiler 和
published graph 已统一切换至 `/api/account/positions/read-only/`；账户确认取消用例现在
同时验证刷新前后账户行数不变，避免把读操作副作用误当作用户写入。

外部 AI 首轮 UAT 发现两项非 Provider 协议问题：Sentiment 已真实成功，但断言仍检查旧
英文标签，现改为中文用户界面契约并排除“AI 调用失败”；Terminal 被既有系统兜底额度
门禁拒绝，按现有 Application UseCase 为一次性测试用户配置额度后通过。Provider 使用
chat-completions 模式，凭据仅保存在一次性 SQLite 的加密字段，明文字段为空；未写入仓库、
文档、日志或测试源码。

## 人工复核范围

在同类隔离环境中完成以下浏览器检查：

- 管理员深链
  `execution.accounts + simulated-trading.accounts` 可读取 2 行初始账户；
- 账户详情返回 23 个字段；
- 创建账户缺参进入“补填参数”，补齐后进入“确认操作”，取消后无写入；
- operator 深链
  `ai-ops.terminal + agent-runtime.operator-task-list` 可见空态指引与“读取完成”；
- 普通用户使用相同深链时显示“链接中的任务在当前账号下不可用”；
- F9 在移动视口可打开任务面板；
- 1440×900、1024×768、390×844 均无页面级横向溢出；
- 未发现无可访问名称的可见按钮；
- 浏览器 console error 为 `[]`。

本轮使用独立 Playwright SQLite 与本地 runserver，不读取或修改开发数据库、生产数据或
生产 registry；一次性数据库暂留用于复核本轮证据，完成后按精确路径清理。

## 剩余 M5 证据

108/108 主任务 UAT 已完成。正式 M5 评审仍须补齐稳定候选版本与 14 个完整自然日、
P0/P1 缺陷窗口、101/101 生产任务遥测及两侧最小样本、生产 registry 备份、owner 与
独立 reviewer 审批。各 route 的空态、错误态、旧 URL 和生产行为仍按矩阵与清理 wave
逐项核验，不能仅凭本地 UAT 删除 Classic。

Classic 入口占比样本不足时只能走 owner/reviewer 双签例外；错误率比较仍要求 Classic
与 TUI 各至少 20 个 task request，不能用低频例外或本报告代替。
