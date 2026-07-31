# VPS UAT / E2E / MCP 生产问题清单（2026-07-31）

## 1. 状态与边界

- 目标环境：`https://demo.agomtrade.pro`
- 源码基线：`491b0b20fe930760f5d5afcda492c36c9a236e04`
- 最终 VPS release：`20260731084347`；镜像 ID：`sha256:f901b71abfeb29e9bcc35104fdf3f84d8600cf409f2c9b264d1c33226b4f3102`
- 数据策略：保留生产 PostgreSQL；不导入本地 SQLite。
- 凭据策略：管理员密码、MCP token 和 session cookie 不写入本文、仓库或测试产物。
- 当前阶段：**问题清单已冻结、修复已部署、生产复测与测试数据清理已完成**。第 6 节保留逐项验收和清理证据。

## 2. 已完成的发现性测试

| 测试面 | 结果 | 证据摘要 |
|---|---:|---|
| 生产 Playwright smoke | 38 passed | 登录、Classic/TUI/Admin/Broker 页面与多视口基础布局通过 |
| 生产只读 UAT/E2E | 65 passed | 用户旅程、综合页面契约、导航和业务工作流壳通过 |
| Web → TUI M5 专项 | 4 setup errors | 产品断言未执行；被本地 DB 测试夹具的异步上下文错误阻断 |
| 首页人工/DOM 复核 | 已执行 | 发现摘要字段、格式与 warning 文案问题 |
| 生产 API | 10/10 passed | health、ready、API root、Regime、Policy、Signal、Data Center 与 quote 均返回 200 |
| 生产 SDK | 3/3 passed | Regime、Policy、Data Center 指标目录成功 |
| MCP 自助 token 生命周期 | passed | 临时只读 token 创建、使用和撤销成功；未在产物中保留明文 |
| MCP 核心工具 | 9 tools / 5 calls passed | bootstrap、中文搜索、Regime、Policy、宏观工作流均完成 |

浏览器与 MCP 产物位于本地忽略目录 `output/playwright/vps-uat-2026-07-31/`。

## 3. 冻结问题清单

### VPS-UAT-001 — P0 — Web 在快速 TUI 导航/自动读取压力下失去响应

**现象**

- 生产 Playwright 基础套件通过后，按屏快速打开 TUI 并触发默认只读 action，公网 `/api/health/` 开始超时并最终返回 502。
- Caddy 报错：连接 Web 容器 `172.18.0.5:8000` 超时。
- Web 容器仍为 running、无 OOM、服务器内存和磁盘充足，但容器 health 变为 unhealthy。

**证据**

- Web 容器：`OOM=false`、`RESTARTS=0`、health failing streak 达到 54。
- `/proc/net/tcp` 在故障时有 113 个 established 连接。
- Daphne 为单进程；快速切换屏后，前一屏已发出的同步 action 仍可能继续占用服务执行资源。
- 只重启 Web 后服务恢复，PostgreSQL、Redis、Celery 和 Caddy 无需重启。

**验收条件**

- 受控重复导航/自动读取压力下，liveness 始终可在限定时间内返回。
- 慢 action 有明确超时、取消或负载保护，不得阻塞健康探针。
- 压力复测后 Web 保持 healthy，公网无 502。

### VPS-UAT-002 — P0 — Web healthcheck 超时时遗留 `curl` 子进程

**现象**

- `docker/docker-compose.vps.yml` 的 Web healthcheck 调用 `curl` 时没有设置 `--connect-timeout` / `--max-time`。
- Docker healthcheck 外层 10 秒超时后，子 `curl` 没有被回收；故障现场约 50 个 healthcheck `curl` 进程持续挂起，每 40 秒继续增加。

**证据**

- `docker top agomtradepro-web-1` 显示连续 30 分钟以上、每约 40 秒新增的 `/api/health/` curl。
- health 日志连续报告 `Health check exceeded timeout (10s)`。

**验收条件**

- healthcheck 自身设置小于 Docker 外层 timeout 的连接与总超时。
- Web 故意无响应时，healthcheck 失败但不遗留子进程。
- 增加精确部署/Compose 契约测试，防止超时参数被删除。

### VPS-UAT-003 — P1 — Web 重启恢复窗口约 90 秒且期间持续 502

**现象**

- `docker compose restart web` 后，entrypoint 在 Daphne 监听前串行执行 deploy check、迁移、cold-start bootstrap、宏观定时任务设置和 collectstatic。
- 本次恢复约 90 秒；Caddy 在整个窗口返回 502。

**验收条件**

- 明确哪些启动步骤必须阻塞 Web，幂等维护步骤应移出请求服务启动关键路径或设置快速跳过。
- 部署/重启文档与验证脚本发布真实的冷启动预算。
- 恢复窗口有可验证上限，不因无变更的重复初始化持续拉长。

### VPS-UAT-004 — P1 — M5 Playwright 套件无法安全直接指向远端环境

**现象**

- `tests/playwright/tests/uat/test_web_to_tui_m5.py` 的 session autouse fixture 无条件操作本地 Django 测试库。
- 与生产 URL 的 Playwright 会话组合运行时，4 个用例在 setup 阶段触发 `SynchronousOnlyOperation`，产品断言完全未执行。
- 角色用户和业务 fixture 只写本地 DB，却假定远端浏览器能登录或读取这些记录，远端 UAT 语义不成立。

**验收条件**

- 本地 live-server fixture 与远端 UAT actor provisioning 明确分离。
- 远端只读套件不得写本地 DB；角色/测试数据必须使用显式远端、可回收的 UAT provisioning。
- 108 条迁移深链和三种视口可在生产候选环境真实执行并留下报告。

### VPS-UAT-005 — P2 — 首页“投资指挥摘要”泄露内部字段语义且格式粗糙

**现象**

- 面板显示“说明 / 显示名称”“说明 / 当前环境”“说明 / 已投资Ratio比例”“说明 / 待处理Review数量”等内部或中英混合标签。
- 金额和比例以 `1000000.0`、`36.877941` 等原始数值展示，与同页“组合摘要”的货币/百分比格式不一致。

**验收条件**

- 使用面向用户的中文字段标签。
- 金额、比例、数量应用与组合摘要一致的格式规则。
- `business_summary` 不再选用用户名作为首要业务结论。

### VPS-UAT-006 — P2 — 数据治理 warning 与“暂无异常”文案矛盾

**现象**

- 首页“数据与任务”面板 badge 为 warning，后端明确返回 `blocking_reason=打开治理队列查看新鲜度、覆盖率与温度计详情`。
- 面板主体却渲染固定 empty copy“暂无数据与任务异常”。

**验收条件**

- warning/blocked 状态优先展示原因和下一步，而不是 empty copy。
- 状态、badge、正文和目标 action 四者一致。

### VPS-UAT-007 — P2 — 过期 Regime 只显示“暂无环境摘要”，未发布不可决策原因

**现象**

- Operator home 返回 Regime `observed_at=2026-06-30`、severity=warning。
- 首页“环境与脉搏”面板显示“暂无环境摘要，请进入环境与脉搏检查数据”，没有展示观测时间、过期原因或决策阻断语义。

**验收条件**

- stale/blocked 环境数据必须显示观测时间、freshness/reliability 和稳定阻断原因。
- 不能把“有数据但不可用于决策”渲染成普通空状态。

### VPS-UAT-008 — P2 — 生产 `check --deploy` 报告 SecurityMiddleware 缺失

**现象**

- Web 冷启动每次输出 `security.W001`：配置的 HSTS、nosniff、referrer policy、COOP 与 SSL redirect 设置不会生效。
- Caddy 已负责 TLS，但 Django 安全响应头是否全部由反向代理等价覆盖尚未形成可执行证据。

**验收条件**

- 明确安全头责任边界；若由 Django 负责则恢复 `SecurityMiddleware`，若由 Caddy 负责则配置并测试等价响应头。
- `manage.py check --deploy` 不保留未解释的安全 warning。

### VPS-UAT-009 — P3 — OpenAPI 枚举命名存在两条稳定 warning

**现象**

- `drf_spectacular.W001` 报告 `RebalanceFrequencyEnum` 与 `RegimeEnum` 同一 choice set 存在多个名称。

**验收条件**

- 使用 `ENUM_NAME_OVERRIDES` 或统一 serializer choice 命名消除 warning。
- OpenAPI schema 生成回归通过。

## 4. 已确认不是当前产品缺陷

- Windows `playwright-cli` 命名会话在超时后占用执行队列：属于本次测试驱动工具问题；同一生产站点通过 pytest Playwright 103 项，因此不记为 VPS 产品失败。
- MCP 主业务调用未发现失败；其旁路审计投递缺口单独记录为 `VPS-UAT-012`，并已完成修复和实库复验。
- Regime 过期 warning 本身是正确的数据治理结果；缺陷是首页没有向用户说明其不可决策语义。

## 5. 修复顺序

1. `VPS-UAT-002`：先阻止 healthcheck 进程泄漏。
2. `VPS-UAT-001`：为 Web liveness 与 TUI action 压力增加隔离/超时/回归。
3. `VPS-UAT-003`：缩短或约束 Web 冷启动恢复窗口。
4. `VPS-UAT-004`：拆分本地与远端 UAT provisioning，再完成 M5 远端矩阵。
5. `VPS-UAT-005` 至 `VPS-UAT-007`：修复首页用户语义与 freshness 展示。
6. `VPS-UAT-008`、`VPS-UAT-009`：收口部署与 OpenAPI warning。
7. 重新部署，复跑 smoke、UAT/E2E、压力回归、SDK/MCP，并核对临时测试数据已清理。

## 6. 修复与最终验收结果

| 编号 | 最终状态 | 生产复测证据 |
|---|---|---|
| VPS-UAT-001 | 已修复 | TUI action 增加有界并发保护和可恢复 `503`；ASGI liveness 不进入 Django 业务处理。生产 Smoke `38/38`、只读 UAT `65/65`、108 条 M5 深链通过；压力结束后 Web healthy、TCP established `3`、最近 25 分钟 `5xx=0`。 |
| VPS-UAT-002 | 已修复 | healthcheck 增加 `--connect-timeout 2 --max-time 5`；多轮浏览器压力和 Web 重启后遗留 healthcheck `curl=0`。 |
| VPS-UAT-003 | 已修复 | check、migrate、bootstrap、collectstatic、定时任务配置和管理员校验移出普通启动关键路径，仅在部署事务中显式执行。受控重启公网恢复 `23.728s`、Docker healthy `25.985s`，启动副作用计数 `0`；原现场约 `90s`。 |
| VPS-UAT-004 | 已修复 | Playwright 本地 DB fixture 只对 localhost 生效；远端角色和业务 fixture 使用显式、可回收的 provisioning；账户 ID 改为读取远端真实选项。生产写入 E2E `9 passed`；包含三角色隔离、60+ 读取面、完整业务生命周期和真实外部 AI 的 M5 `15 passed`，无 skip。 |
| VPS-UAT-005 | 已修复 | 生产 DOM 显示“当前环境、环境置信度、总资产、累计收益、已投资比例、活跃信号、待复核事项”等用户字段；金额为 `1,000,000.00 元`，比例为 `36.9%/0.0%` 风格，不再展示内部字段名或用户名摘要。 |
| VPS-UAT-006 | 已修复 | warning 面板正文显示“打开治理队列查看新鲜度、覆盖率与温度计详情”及“查看完整数据治理”，不再显示“暂无异常”。 |
| VPS-UAT-007 | 已修复 | 环境面板发布时效、可靠性和观测时间；最终运行态 Regime 为 `Recovery / 新鲜 / 降级 / 2026-06-30 / 置信度 0.37`。当前源契约未判 stale，因此保留“新鲜”，同时明确降级原因，未伪装成空状态。 |
| VPS-UAT-008 | 已修复 | 恢复标准 `SecurityMiddleware`，Caddy 负责边缘跳转；生产 `check --deploy` 为 `no issues (1 silenced)`，静态和动态响应的 HSTS、nosniff、referrer、X-Frame 均恰好一份。静默项仅为由 Caddy 承担跳转后的 `security.W008`。 |
| VPS-UAT-009 | 已修复 | 补齐稳定 `ENUM_NAME_OVERRIDES`；最终部署检查不再出现两条 drf-spectacular enum warning。 |
| VPS-UAT-012 | 已修复 | 审计默认超时改为 5 秒，并加入最多 2 次的有界重试；每次投递携带稳定 UUID，服务端按该 UUID 幂等写入并拒绝不同载荷复用。最终 5/5 MCP 调用均返回审计 log_id，PostgreSQL 按 ID 精确查询 `requested=5, found=5`。 |

### 6.1 部署链路追加发现

#### VPS-UAT-010 — P1 — 源码包膨胀、CRLF 与 SSH 抖动降低热修复可靠性

**发现**

- 首次源码包混入本地 runtime/wheelhouse 数据，远端 release 一度达到约 `4 GiB`，上传和构建超过 55 分钟。
- 精简包第一次遗漏 wheelhouse `.keep`，Dockerfile `COPY` 失败；随后远端 shell 因 CRLF 失败。
- VPS SSH 偶发在协议 banner 阶段断开，客户端退出状态不能单独证明部署是否完成。

**修复与证据**

- 打包改为 `git ls-files --cached --others --exclude-standard`，wheelhouse 默认只保留 `.keep`，实测源码包约 `14.2 MiB`。
- 解包后统一清理 `*.sh` 的 CRLF；SSH 建连增加 4 次有界重试和 30 秒握手上限。
- 最终 deployment report 标记 `deployed=true`，release、镜像 ID、容器镜像、current symlink 和公网 health 交叉一致。

#### VPS-UAT-011 — 测试环境 — 本机 Fake-IP DNS 污染远端 UAT

- 测试机将 `demo.agomtrade.pro` 解析到 `198.18.0.223`，普通探测 8 次仅 2 次成功，导致一轮 Smoke `38 setup errors`；强制解析到真实 VPS IP 后 8/8 成功。
- Playwright 增加可选 `AGOM_PLAYWRIGHT_HOST_RESOLVER_RULES`，测试仍使用正式域名和 TLS/SNI，只绕过本机 Fake-IP；最终 Smoke `38/38`、只读 UAT `65/65`。
- 该项不属于 VPS 产品缺陷，不计入产品失败。

#### VPS-UAT-012 — P1 — MCP 核心调用成功但审计日志因 1 秒超时丢失

**发现**

- 完整写入 E2E 清理后再次执行 MCP token 生命周期和 5 次核心调用，业务结果全部为 `completed`。
- 同一轮客户端连续输出“审计日志发送失败（网络错误）”，请求在生产 TLS 往返超过固定 `1.0s` 后超时。
- 这会形成“能力调用成功、审计证据未可靠送达”的合规缺口，不能以 MCP 主结果成功掩盖。

**修复与证据**

- `AGOMTRADEPRO_AUDIT_TIMEOUT_SECONDS` 默认 `5.0`，`AGOMTRADEPRO_AUDIT_MAX_ATTEMPTS` 默认 `2`，退避默认 `0.25s`；三个参数均可通过环境配置且有安全上下界。
- 客户端为同一次投递生成稳定 `delivery_id`；网络错误、429 和 5xx 使用同一 ID 有界重试。服务端把该 ID 作为日志主键，重复的相同载荷返回原 log_id，不同载荷复用同一 ID 则拒绝。
- SDK 聚焦测试 `10 passed`；内部审计接口 `6 passed`；审计与部署相关回归 `108 passed`；ruff、SDK/生产增量 mypy、架构护栏和 Compose 配置均通过。
- 最终生产 MCP 注册 `9` 个工具，5 次核心调用全部 `completed`；客户端取得 5 个非空审计 log_id，远端 PostgreSQL 精确查询 `requested=5, found=5`，工具名和 request_id 全部匹配，`response_status=200`。
- Web 容器实际环境已核对为 timeout `5.0`、max attempts `2`、backoff `0.25`，最近日志无审计发送失败。

#### VPS-UAT-013 — 测试环境 — UAT 运行器到 VPS 的外部链路间歇重置 TLS

- 最终发布后，UAT 运行器做 30 次独立 HTTPS 连接采样，17 次成功、13 次在 TLS 阶段被重置；同一轮后续 SDK `3/3`、MCP `5/5` 正常。
- VPS 同时经正式域名自测 30/30；系统负载 `0.14`、可用内存约 `5.1 GiB`、conntrack `266/262144`，无 SYN backlog、OOM、Caddy、Django 或容器错误。
- 双端抓包显示 VPS 对每个 SYN 正常返回 SYN-ACK，之后的 RST 从 UAT 运行器出口方向进入 VPS，并非 VPS/Caddy 发出。因此本项归类为运行器出口/中间网络路径问题，不修改生产应用。
- 一次性 UAT 浏览器探针增加有限导航重试；正式验收仍使用真实域名、TLS/SNI 和真实 VPS IP，不放宽证书验证。

### 6.2 最终回归汇总

- 生产浏览器：Smoke `38 passed`；只读 UAT `65 passed, 9 deselected`；生产写入 E2E `9 passed, 34 deselected`；完整 M5 `15 passed`，无 skip，包含角色矩阵和真实外部 AI。
- 生产 API / SDK / MCP：10 个 API 端点均已验证，SDK `3/3`，MCP `9 tools / 5 calls` 全通过；最终 5 条 MCP 审计逐条落库；临时只读 token 已撤销，HTTP `200`。
- 测试数据清理：本轮四个 UAT actor 和 18 类可变业务记录均为 `0`；保留的只有不可变审计证据。
- 本地最小回归包：`330 passed`；本轮审计与部署相关回归 `108 passed`、SDK 审计 `10 passed`、内部审计接口 `6 passed`；远程部署脚本 `11 passed`；此前 JS TUI 回归 `30 passed`。
- 质量门禁：ruff、增量 mypy、全仓 mypy debt ceiling、architecture delta、governance consistency、发布 TUI metadata validation 全通过；大 Python 文件违规 `0`。

### 6.3 清理与保留边界

- 生产写入用例使用独立 run id 和显式远端 fixture；结束后四个 UAT actor、测试账户、策略、信号、回测、Provider、Policy、Beta/Alpha、因子、舆情和决策配额等 18 类记录全部清零。
- 每轮 MCP 自助验证创建的临时 token 均在 `finally` 中撤销；最终一轮撤销 HTTP `200`。
- 审计日志属于追加式合规证据，不作为普通测试数据删除；最终 5 条记录保留 request_id、工具名、状态和服务端 log_id，不包含 token 明文或管理员密码。
