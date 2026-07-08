# VPS 自动化投研系统检视报告（2026-07-07）

> 检视对象：`https://demo.agomtrade.pro` 对应 VPS 运行态  
> 检视时间：`2026-07-07 Asia/Shanghai`  
> 检视方式：远端容器/配置抽查 + 公网 API 验证 + `admin / Aa123456` 页面实测 + 本地代码与文档对照  
> 特别说明：操作者已在 `2026-07-07` 明确说明“当前生产端仍使用 SQLite”，因此本报告**不把 SQLite 本身记为运行故障**；但会把“运行态 / 基线文档口径不一致”记为治理缺口。

---

## 1. 执行摘要

当前 VPS 已具备“个人自用自动化投研工作台”的**基本可用性**：

- 域名入口可用，`/api/health/`、`/api/ready/` 正常。
- Web、Celery worker、Celery beat、Redis、Caddy 均在运行。
- `TUI` 可登录并加载主要工作台。
- `CLI Terminal` 的 `/help`、`/mcp-tools` 可执行。
- 使用 `UserAccessTokenModel.key` 的外部 API 调用可正常读取 Regime、Policy、Signal、Data Center 等核心数据。

但从“自动化投研系统”而不是“能打开页面”的标准看，仍有几类明显缺口：

- **外部接入契约漂移**：MCP/SDK/技能文档大量使用过期 token 来源与过期路径。
- **运维检查口径漂移**：文档和脚本引用的部分 health/metrics 端点在线上不存在。
- **CLI 交互闭环不完整**：`/status` 无法在页面内正常完成回显。
- **数据语义治理仍有污染**：策略/政策/信号面仍混入测试数据与非目标业务事件。
- **运行与治理证据未完全统一**：多个入口对 MCP/能力规模、生产口径、环境分类的表达并不一致。

---

## 2. 本次检视确认到的运行态事实

- 远端主机：`62.171.144.39`
- 对外正式域名：`demo.agomtrade.pro`
- 容器实况：
  - `agomtradepro-web-1`
  - `agomtradepro-celery_worker-1`
  - `agomtradepro-celery_beat-1`
  - `agomtradepro-redis-1`
  - `agomtradepro-caddy-1`
- `web` 当前镜像：`agomtradepro-web:manualfix-20260707121435`
- 当前 `DATABASE_URL`：`sqlite:////app/data/db.sqlite3`
- `celery worker` 当前为单 worker，监听 `celery,qlib_infer,qlib_train`
- 线上 readiness：
  - `/api/health/` 返回 `200`
  - `/api/ready/` 返回 `200`
  - readiness 内显示 `database/redis/celery/critical_data` 均为 `ok`
- 页面入口：
  - `/` 登录后默认进入 `/tui/`
  - `/terminal/` 可访问
  - `/admin/` 可访问

---

## 3. 主要缺口

### P1. 对外接入契约已经发生漂移，MCP/SDK 文档与技能说明不能直接代表线上真相

- `.agents/skills/mcp-remote-agomtradepro/SKILL.md` 仍使用旧示例：
  - 旧 token 变量：`AGOM_REMOTE_API_TOKEN`
  - 旧路径：`/api/signal/`、`/api/macro/supported-indicators/`
- 实测线上真相是：
  - 可用 token 来自 `UserAccessTokenModel.key`
  - 正常 header 仍是 `Authorization: Token <token>`
  - 当前模块根路径来自 `/api/`，例如 `signal` 实际根是 `/api/signal/`，`data_center` 实际根是 `/api/data-center/`
- 直接使用 `rest_framework.authtoken.Token` 会得到 `403 Invalid token`
- 直接照旧技能/旧文档发起若干请求，会拿到 `404`

影响：

- 外部 Agent、SDK、MCP 客户端容易“看起来有文档，实际上第一次就接错”。
- 集成成本被转移到人工试错，不符合自动化投研平台的接入预期。

建议：

- 把 `.agents/skills/mcp-remote-agomtradepro/SKILL.md`、`docs/mcp/*`、`docs/sdk/*`、`docs/testing/api/API_REFERENCE.md` 统一改成**当前线上真实 token 来源 + 当前模块真实路径**。
- 给 `/api/` 根返回增加“推荐 token 来源 / 示例 curl / 常用子路径示例”，减少接入歧义。

### P1. 运维检查口径与线上实现不一致

- 线上 `https://demo.agomtrade.pro/api/health/`、`/api/ready/` 可用。
- 但 `https://demo.agomtrade.pro/api/health/db/` 返回 `404`。
- `https://demo.agomtrade.pro/api/metrics/` 返回 `404`。
- 仓库内多个脚本/文档仍把这些路径当成现成可用检查项。

影响：

- 自动化验收脚本、部署后门禁、外部监控配置容易“按文档失败”。
- 发生真实故障时，团队会先花时间分辨“系统坏了”还是“文档错了”。

建议：

- 明确选择：
  - 要么补回这两个端点并纳入正式契约。
  - 要么清理所有 runbook、postdeploy、playbook 中的旧引用。

### P1. CLI Terminal 的系统状态命令闭环不完整

- `/help` 正常。
- `/mcp-tools` 正常，并能展示 `187` 个“Synced MCP Tools”。
- 但 `/status` 在等待 `8s` 后页面内仍只停留在 `Fetching system status...`，未形成可读结果回显。
- 同一页面侧栏仍显示 `Session ID: -`、`Messages: 0`、`Tokens: 0`，即使已执行多条命令。

影响：

- CLI 作为“系统运维入口”时，最基础的 readiness 查询不闭环。
- 会削弱用户对 Terminal 的信任，逼迫用户回退到 TUI、Admin 或直接 API。

建议：

- 优先修复 `/status` 的前端回显链路。
- 同步修复 Session/Usage 统计展示，让 Terminal 至少能对只读命令产生最基本的执行反馈。

### P1. 业务语义治理还存在污染数据

- `/api/policy/status/` 返回的 `latest_event` 是一条 `2026-07-07` 的印度 `BSE Sensex` 盘中快讯。
- `/api/signal/` 列表中仍有大量 `UATSIG...` 测试信号。

影响：

- Policy 层的“最新事件”在语义上并不等于“当前最 relevant 的中国政策事件”。
- Signal 面被测试数据污染，会降低真实研究和审批面的可信度。

建议：

- 给 Policy 事件流增加更强的国家/主题/政策相关性过滤。
- 对信号池增加“测试数据隔离 / UAT 标记 / 默认隐藏非生产信号”。

### P2. 入口体验仍偏“专家后台”，缺少更轻量的自动化投研入口

- 根路径默认跳转登录后进入 `/tui/`。
- `TUI` 功能完整，但明显是重操作、重模块导航、重工作台概念。
- `CLI` 视觉完成度高，但当前更像操作壳，不是“每日决策摘要入口”。
- `Admin` 覆盖广，但本质仍是 Django admin，不是收敛后的运营控制台。

影响：

- 对熟悉系统的人可用。
- 对“每天只想快速判断环境-仓位-候选-风险是否异常”的个人操作者仍偏重。

建议：

- 补一个真正的 operator home：
  - 今日环境结论
  - 今日风险例外
  - 今日待处理审批/任务
  - 最新 Alpha / Pulse / Quote freshness
  - 一键进入 TUI/CLI/Admin

### P2. 域名入口可用，但 IP 入口行为不干净

- `http://62.171.144.39` 会 `308` 跳到 `https://62.171.144.39/...`
- 直接访问 `https://62.171.144.39` TLS 握手失败
- 域名 `https://demo.agomtrade.pro` 正常

影响：

- 自动化脚本如果错误使用 IP，会得到难以理解的 TLS 失败。
- 当前 `ALLOWED_HOSTS` 又包含 IP，容易给操作者造成“IP 应该也能直接用”的错觉。

建议：

- 明确域名是唯一正式入口。
- 对 IP 入口返回更明确的 domain redirect 策略，或从文档里彻底移除 IP 直连示例。

### P2. 运行规模与治理指标跨界面表达不一致

- `docs/governance/SYSTEM_BASELINE.md` 写 MCP tools 基线为 `368`
- Terminal `/mcp-tools` 页面展示 `187`
- 运行库里 `CapabilityCatalogModel` 实际记录数为 `3488`

这三者并非一定互相矛盾，但缺少统一解释：

- 哪个是“全部 capability”
- 哪个是“可治理 MCP tool”
- 哪个是“终端当前放行工具”

建议：

- 在 capability / MCP 治理文档里给出明确计数口径。
- 在 UI 上把“总 catalog / MCP subset / terminal enabled / routing enabled”分开展示。

### P2. 单 worker 承担多类队列，个人自用可接受，但仍是自动化链路脆弱点

- 当前只有 `1` 个 Celery worker
- 队列同时覆盖 `celery, qlib_infer, qlib_train`

影响：

- 一旦训练、推理或长任务堆积，会直接影响 readiness、日常刷新与交互时效。
- 在 SQLite 仍被保留的情况下，长任务与大表增长叠加，后续脆弱性会更明显。

建议：

- 至少把“个人自用单 worker”明确标注为当前运行策略，而不是默认让人误判为正式稳态。
- 中期应拆出训练/推理与日常运维队列。

### P3. 文档基线与当前运行分类尚未统一

- `docs/governance/SYSTEM_BASELINE.md` 把 `0.8.0` 正式生产口径写成 `PostgreSQL`
- 当前 VPS 实际仍跑 `SQLite`
- 操作者已明确说明这是当前有意选择

本项不是“系统坏了”，而是：

- 运行分类
- 发布口径
- 环境命名

三者尚未完全统一。

建议：

- 把当前 VPS 明确标为：
  - personal production
  - operator production
  - transitional production
  - demo production

至少选定一种，不再同时混用“正式生产推荐”和“当前实际生产”。

---

## 4. 结论分层

### 4.1 已经可以做的事

- 作为个人自用的自动化投研工作台，系统已经能跑。
- Regime / Policy / Signal / Data Center / TUI / CLI / Admin 都不是空壳。
- 外部 API 也能真实读到核心业务数据。

### 4.2 当前最需要优先补的，不是“大重构”，而是“契约对齐”

优先级最高的不是再加一个新模块，而是把以下三条对齐：

- 文档写什么
- 接口实际上怎么接
- 页面/CLI 实际怎么回显

如果这三条不统一，系统就会长期停留在“功能很多，但外部接入和日常操作成本偏高”的状态。

### 4.3 从自动化投研系统角度，当前真正的短板

- 不是“没有能力”
- 而是“能力已经很多，但入口、契约、治理证据没有完全收束成一个低摩擦系统”

---

## 5. 建议的后续动作顺序

1. 修正 MCP/SDK/技能文档中的 token 来源、示例路径、curl 样例。
2. 统一运维健康检查口径，清理 `/api/health/db/`、`/api/metrics/` 的文档漂移。
3. 修复 Terminal `/status` 回显和 session telemetry。
4. 清理 `UATSIG` 测试信号，强化 Policy 事件过滤。
5. 给根入口补一个“今日结论 + 风险例外 + 数据新鲜度”的轻量 operator 首页。
6. 明确当前 VPS 的环境分类和数据库口径，避免继续与正式基线叙事冲突。

---

## 6. 本次检视附加证据摘要

- 线上 token 实测：
  - `UserAccessTokenModel.key` 可用
  - `rest_framework.authtoken.Token` 不可作为当前外部接入凭据
- 线上 API 实测：
  - `/api/regime/current/` 正常
  - `/api/policy/status/` 正常
  - `/api/account/profile/` 正常
  - `/api/backtest/` 正常
  - `/api/signal/` 正常
  - `/api/data-center/indicators/` 正常
- 页面实测：
  - `/tui/` 可登录并展示工作台
  - `/terminal/` 可执行 `/help`、`/mcp-tools`
  - `/terminal/` 的 `/status` 未在页面内闭环
  - `/admin/` 可正常进入并加载主要管理分组
