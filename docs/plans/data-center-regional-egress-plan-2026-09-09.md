# 数据中台境内出口与 frp 接入规划

状态：首版仓库实现完成（DATA-14），尚未部署；真实境内出口验收待完成。

归属：`data-production-reliability` 工作流，作为 `DATA-02` 数据采集可用性的支撑方案。
唯一执行状态仍由 `governance/active_plan_registry.json` 的 closure backlog 维护；
2026-09-09 用户授权开发后，仓库实现登记为 DATA-14，完成后释放执行焦点；
DATA-02 生产验收状态不变，境内 frps 的真实参数和出口验证仍待提供。

用户已确认境内服务器运行 frps。按“复用该 frps，境内同机增配 frpc/出口代理”规划；
尚未确认管理权限和 frp 版本。若同机不能部署代理，再选择另一台境内出口节点。

## 目标与边界

数据中台根据 provider、dataset、目标域名和部署区域，为行情请求选择直连或境内出口。
Alpha/Qlib、Equity 等消费者继续调用中台公开端口，不感知 frpc、代理地址或凭据。
frp 负责传输隧道；请求规则、错误分类、重试预算、审计由中台负责。
本方案不承诺境内云服务器一定能通过供应商风控，先验证目标出口实际可用。

当前证据：东方财富历史 K 线在海外 VPS 被 RemoteDisconnected 断开，本地成功，
VPS DNS/TLS 正常；不足以断言上游封锁所有境外地址。
RDS 已成功绑定，但已有腾讯参考价格与 RDS 的口径冲突属于另一问题，代理不会修复它。

## 正确的网络拓扑

推荐复用既有 frps，以 STCP 连接境内出口服务：

```text
VPS web / Celery → 中台路由决策 → frpc visitor（独立容器）
                                      ↓
                               既有 frps 中继
                                      ↓
                       境内 frpc → 境内 HTTP CONNECT 代理 → 数据供应商
```

境内 frpc 可使用官方 http_proxy 插件，或转发到同机独立代理服务。
最终访问供应商的进程必须在境内；在海外 frpc 启用 http_proxy 插件仍会从海外出网。
frps 本身是中继服务，不自动成为正向出口代理。
frpc 的 transport.proxyURL 是 frpc 连接 frps 时使用的代理，并非业务请求分流配置。

第一版支持 HTTP/HTTPS 正向代理；已有可安全访问的境内代理可直接注册，无须额外 frpc。
SOCKS5 需要额外客户端依赖和独立验收，本次不启用。
若用户只有 frps 地址和 token，还需要一个境内 frpc/代理服务以及对应配置权限；
单凭 frps 账号不能保证能创建境内出口。

VPS visitor 仅向受控 Docker 网络提供监听，不发布公网代理端口。
独立容器的 127.0.0.1 不能由 web/worker 直接访问；采用内部服务名和网络隔离，
或明确共享网络命名空间，实施时二选一。现有 runtime_ns 的共享 pid 并不共享网络。
代理到上游保持 HTTPS 证书校验，不做 TLS 解密。HTTP 明文供应商接口仍为明文协议。

## 中台设计

| 对象 | 所属职责 | 建议字段 |
| --- | --- | --- |
| 出口节点 | config_center 拥有全局连接配置 | 名称、区域标签、代理协议/地址、凭据引用、启用状态、并发上限 |
| 出网规则 | data_center 拥有采集策略 | provider_id、dataset_key、域名匹配、部署区域、优先级、出口链、允许切换条件 |
| 路由决策 | data_center Domain/Application | 输入明确请求上下文，返回出口与命中规则；纯规则测试，不含网络 I/O |
| HTTP 传输 | data_center Infrastructure | 独立 Session、代理注入、超时、连接池、证书、重定向与目的地检查 |
| 隧道进程 | 部署层 | 固定版本 frpc sidecar、健康检查、重连、受控配置更新 |
| 审计与管理 | 现有中台 TUI/监控 | 当前出口、命中原因、延迟、错误类别、探测时间、启停/测试/回滚 |

通过配置中心公开 Application 接口读取出口与秘密，避免 data_center 直连其 Infrastructure。
复用现有加密凭据机制、权限与审计；不把 token/password 写进 extra_config、日志或前端回显。
Django 不直接启动子进程守护 frpc，不挂载 Docker socket 来操作容器；进程生命周期由部署层管理。
第一版出口隧道静态部署，TUI 可切换已登记出口与规则；自动生成/发布隧道配置放后续。

## 分流规则与执行顺序

建议策略：直连、固定出口、直连失败后备用出口。第一版只支持一个境内备用出口。
同一 provider 内完成允许的出口尝试，再进入现有 provider failover。首版按单次供应商读取
最多两次出口候选尝试；外层供应商切换沿用既有调度，已消耗出口预算的错误不再进入
Tushare 的三次重试。未引入跨全部供应商/全部股票的统一全局请求预算。

| 匹配示例 | 初始策略 |
| --- | --- |
| AKShare 历史行情 + push2his.eastmoney.com + 海外部署标签 | 验证后固定境内出口，或直连失败后境内重试一次 |
| DataHubCo RDS | 直连，保留单独可配置规则 |
| 其他目标 | 保持既有直连默认 |
| 未知或不允许的目标、内部服务/数据库 | 不进入境内出口 |

规则优先级明确且可预览；同优先级冲突在保存时拒绝，避免顺序偶然决定行为。
域名按完整主机名或明确子域匹配，不用字符串包含判断。首版禁止自动跟随重定向，返回明确错误。
优先使用显式部署区域标签（例如海外 VPS / 境内节点），不依赖每次在线查询自身 IP 属地。

“按 IP 分区”拆开处理：

1. **执行节点所在区域**：第一版支持人工登记的区域标签，稳定且可审计。
2. **目标 IP/CIDR**：第二阶段可加显式网段规则，处理 IPv4/IPv6、多 A/AAAA、DNS 缓存。
3. **目标 IP 自动属地**：后续可选，使用带版本和更新时间的 IP 库；属地未知有明确默认。
   域名可能解析到不同 CDN 节点，目标属地不能代表网站对来源 IP 的准入规则。

仅对幂等行情读取的连接断开/连接超时等可重试网络故障切换出口。
401、明确权限拒绝、Token 日额度耗尽不切出口反复尝试；429 按上游等待提示和限流策略处理。
403 分类保留证据，不默认通过换出口重试。POST 仅当供应商端点明确是幂等查询时允许重试。
出口故障可短期熔断，冷却后探测；计数放共享运行状态，避免每个 Celery 进程独立放大重试。
固定出口规则可禁止回退直连；代理不可用时返回明确阻断，不静默改变用户选择。

换出口保留原 provider/source 身份，只增加 egress_id、rule_id、attempt 与失败类别审计。
换供应商仍执行既有重叠一致性、单位/复权、新鲜度检查，不把代理当成新的金融数据源。

## 现有代码的主要适配难点

- 新 RDS/统一中继 Session 使用 trust_env=False 且清空 proxies，需要显式传输配置注入。
- Tushare SDK 路径当前会修改 NO_PROXY；需迁移成明确的连接策略，避免供应商互相影响。
- AKShare stock_zh_a_hist 内部直接 requests.get，不能保证给外层设置代理就生效。
  优先将目标接口接入中台拥有的可注入 Session；必须使用不可注入 SDK 时，放到独立进程
  或专用采集 worker，固定其出网环境。禁止在共享 web/Celery 进程中临时改全局环境或
  monkey-patch requests，以免并发请求串路。
- RSS 等已有局部 proxy_config 应作为后续兼容迁移清单，第一版不扩大到全仓网络重构。

## 分阶段交付与投入估算

以下是单人开发、可管理境内机器且现有 frps 兼容的工作量估算，不是完成承诺。

| 阶段 | 交付 | 估算 |
| --- | --- | --- |
| 0 可行性验证 | 确认 frps/节点版本权限，搭一条隔离出口；验证实际出口与东方财富 raw/hfq、日历请求 | 0.5–1 人日 |
| 1 最小可用 | 单境内出口、provider/域名规则、东方财富历史链路、错误分类/预算、配置关闭开关与审计 | 2–3 人日 |
| 2 可运维版本 | TUI 规则和节点测试、共享熔断/限流、部署/重连/回滚、web/worker 一致性与故障验收 | 2–3 人日 |
| 3 可选扩展 | 多节点、CIDR/属地库、更多 SDK 迁移、隧道配置自动发布 | 另估 2–4 人日起 |

建议先完成阶段 0，再投入 1–2，总体约 5–7 人日；只有一条固定代理连通实验通常半天可验证。
若境内节点同样被限流、只有 frps 租户权限、SDK 无法隔离或网络需额外审批，需重新估算。
实现时将 data_center 传输/策略、deploy/frp、TUI、文档拆为可独立评审的提交组。

## 验收与回滚

实施交付顺序：

| 顺序 | 开发任务与产物 | 完成标准 |
| --- | --- | --- |
| 1 | 境内节点/frps 权限和版本盘点、隔离出口探针记录 | 证明真实境内出口可取得目标数据，或记录不可行原因并暂停后续投入 |
| 2 | 出口节点配置、加密凭据引用、typed 路由协议和规则校验 | 域名/区域匹配、规则冲突、固定出口与回退策略有确定性测试 |
| 3 | 中台 Session 注入、AKShare 历史接口接入、RDS 直连兼容 | 真实数据与复权契约通过，并发请求不串路；保留供应商身份和 asof |
| 4 | frpc 部署配置、共享故障状态、限流与请求预算 | 断网/重连/熔断/超时可验证，配置关闭可恢复原路径 |
| 5 | 现有中台 TUI 的节点与规则管理、连接诊断 | 用户可完成配置、测试、查询命中原因和关闭规则的主任务 |
| 6 | 类型/架构/契约回归、VPS 验收记录及回滚演练 | web/worker 配置一致；出口功能验收明确，不把它等同于 Alpha 恢复 |

- 出口证明：通过受控探针确认实际公网出口，不只检查 frpc 连通或代理端口开放。
- 主任务：同一股票同一窗口，直连/境内出口都经过真实 HTTP 调用；验证行情与复权字段。
- 隔离：并发 RDS 直连与东方财富境内请求互不影响；worker 与 web 命中一致配置版本。
- 故障：frps/frpc/代理断开、DNS/TLS 错误、429、额度错误、重定向、无权限分别有预期行为。
- 正确性：保持总超时与请求预算；没有成功数据不得发布 success，不修改真实 asof_date。
- 用户：在现有数据中台 TUI 能测试出口、查看命中规则与最后错误、关闭规则恢复原路径。
- 工程：类型/边界/契约与相关 Celery/current-data 门禁，更新对应治理清单和部署文档。
- 回滚：先关闭出口规则恢复原策略，再停用独立 sidecar；不回滚生产数据库或清除历史行情。
- 完成标准：功能验收与 Alpha 业务恢复分开；腾讯/RDS 价格口径问题未解决时仍需保留阻断。

## 2026-09-09 仓库实施记录

用户授权先完成本地开发和提交，阶段 0 的真实出口验证作为上线门槛保留。
本次不部署生产，也不把 Alpha 恢复作为出口功能的完成证据。

实现提交：`9e46bd83e`（中台路由与供应商传输）、`c4e202ff3`（FRP 部署与探针）、
`74634438e`（TUI 管理入口）。前置 RDS 请求形态提交为 `3baa6962d`。

- 配置中心保存出口主机、区域、并发限制和加密凭据；数据中台通过公开端口读取。
  列表与修改回执只返回脱敏投影，密码留空保留原值。
- 数据中台保存 provider、dataset、域名、执行区域和优先级规则；创建默认停用。
  保存时锁定既有 provider 行并重新检查冲突，避免多个生产进程同时登记重叠规则。
- 执行节点使用 `DATA_CENTER_DEPLOYMENT_REGION`，缺省为 `unknown`；规则支持明确区域或 `*`。
  行情历史链路的数据集键为 `equity.price.bar`，出口区域和执行节点区域是不同字段。
- 在现有 `api-library.data-center` TUI 工作台增加出口登记/修改/测试、规则登记/修改、
  路由预览和连接诊断。管理操作限定 staff，写入和外部探测沿用现有确认与审计流程。
- 出口测试填写实际数据源、数据集、目标地址和执行区域；必须匹配关联的已登记规则，
  可以在出口和规则都停用时测试。测试只走所选出口，不回退直连，不推测通配域名目标。
- `execute_provider_request` 对一次供应商读取统一计算候选次数，每条候选最多一次、
  合计最多两次；只在允许的网络错误后使用备用出口。审计保存请求关联编号、目标主机、
  出口、规则、尝试次数和错误码，不保存 URL 查询参数、请求头、密码或响应正文。
- 已接入 AKShare 股票 raw/hfq 历史行情，以及 Tushare 的 `sdk_path`、`unified_relay`、
  `rest_path` 三种请求形态。原生 SDK 保留原有 URL 后缀和请求体，逐次查询检查规则。
  模型行情调用显式发布 `equity.price.bar`；其他已接入 Tushare 客户端调用使用
  `tushare.<api_name>`，避免把宏观或基础资料错误标记为价格行情。
  AKShare 的指数、日历和其他不可注入 SDK 接口不在本次股票历史传输适配范围；
  这些接口仍沿用既有 provider 路径，后续迁移应补各自数据集与调用契约。
- DNS 解析使用有界并发和请求时限；单次请求固定校验后的公网 IP，保留原 Host、
  HTTPS SNI 与证书主机名校验。代理使用固定的目标 IP，避免再次解析改变目的地址。
  生产共享状态故障会阻断；错误分类按请求线程隔离，后续请求可在 Redis 恢复后重新获取名额。
- 部署产物见 [FRP 操作说明](../../deploy/frp/README.md)：独立 visitor 容器、
  境内 frpc HTTP 代理插件、STCP 隧道、私有 Docker 网络以及只读连通性探针。

建议操作顺序：登记停用出口 → 登记停用规则 → 填写具体目标测试指定出口 →
确认真实公网出口和 raw/hfq 数据 → 启用出口 → 启用规则 → 预览并执行诊断。
停用规则可退出新出口路径；停用出口但保留固定规则会明确阻断，不会偷偷直连。

尚待真实环境验收：frps 地址/版本/鉴权兼容性、境内 frpc 安装权限、实际出口 IP、
东方财富同窗口 raw/hfq、web/worker 区域配置一致性、Redis 多进程限流和断链恢复。
本地 SQLite 测试不能证明 PostgreSQL 的并发锁效果；上线前应在 PostgreSQL/Redis
环境复验。CIDR/自动 IP 属地、多出口链和隧道配置自动发布仍属于可选后续阶段。

### 本地验证证据

- 临时 SQLite 数据库执行真实迁移：`pytest tests/integration/data_center/test_egress_management.py --migrations --create-db -q`，4 passed。
  覆盖停用登记、显式出口探测、启用顺序、密码保留、规则冲突及直连规则清理出口引用。
- TUI 工作台、信息架构与出口入口回归：338 passed、1 个既有基线失败。
  失败项为 `test_macro_overview_publishes_independent_sentiment_panels`：测试期待“当日”，
  提交前 HEAD 已保存“最新观测”；本次未修改该面板标题。
- 供应商适配、模型行情和 HTTP 隔离回归：60 passed；原 Tushare/RDS 请求契约另行通过。
- Celery task contract：91 tasks、21 exemptions；current-data freshness：56 surfaces，均通过。
  新出口审计属于传输记录，不新增行情/估值事实发布或定时数据写入任务，未增加相关 manifest 条目。
- TUI source consistency：413 published actions / 12 screens、888 runtime actions / 24 screens，0 violations。
- FRP 模板在缺少真实环境配置时返回 `blocked_external`，原生命令退出码 2；
  通过 Python 子进程读取退出码验证，避免 PowerShell 把非零原生命令映射为 1。
  模板/探针单测 7 passed，Compose 合并的四个应用服务均包含私有网络和执行区域，visitor 无主机端口。

最终出口与相关供应商集成回归 147 passed，之后新增 Redis 恢复测试所在 HTTP 集合 15 passed；
DNS/HTTPS helper 集合 13 passed。全部 31 个生产 Python 文件增量 mypy 为 0 regressions，
全仓 mypy debt ceiling 为 0 errors；最后的请求线程状态修复另经单文件 mypy 复验。
Black/isort/Ruff、架构 boundary/audit 与 active-plan registry 检查通过。
这些证据不替代真实境内网络验证。

## TUI 配置页补齐（2026-09-09）

管理员入口为系统治理 → 数据出口配置（`/tui/?screen=data-center.egress-config`），数据中台原页提供跳转。独立页面集中登记出口、数据源选择、路由规则、编辑启停、指定出口测试、预览和诊断；操作说明见 [数据出网配置](../development/data-egress-tui-configuration.md)。

- 出口/规则清单首屏展示，规则显示数据源和出口名称。数据源行可发起新增规则并回填编号。
- 编辑先打开表单，回填非密字段并保留原布尔状态；密码留空保留，可明确清除认证。保存后刷新对应清单。
- 修复通用 dashboard 行编辑依赖未发布 HTTP method 的问题；dashboard 隐藏侧栏时使用可见模态表单，防止编辑按钮直接跳到确认。
- 预览与真实连接结果分开展示；诊断列出尝试顺序、耗时和失败标识，业务失败不因接口响应成功而显示为连接成功。
- 浏览器验收使用 Chromium、真实 Django TUI/出口接口及临时 SQLite 数据库；网络诊断注入可控失败，未向真实行情服务发请求。登记、编辑、状态保持、数据源选择、规则启用与失败展示均作为验收范围。

验收证据：

- 前端 Chromium 工作台回归：49 passed，包含隐藏技术字段时的行编辑、模态表单、确认提交及原有工作流。
- 真实 Django 接口与 Chromium 工作流、出口管理 API 合并验证：18 passed。保存回执展示补齐后，浏览器与结果展示再次验证：5 passed。
- 扩展 TUI 回归初次 400 passed、3 failed；其中布尔原值保留新增字段的断言已同步，单项复验通过。另两项在修改前 `cce1c4f1a` 独立工作树中以相同错误复现：旧情绪标题断言，以及关闭 runtime patches 的 density 测试夹具与筛选字段契约冲突。未将这些既有失败标记为通过。
- 7 个生产 Python 文件增量 mypy 0 regressions；保存回执新增逻辑另经 2 文件 mypy 复验。全仓 mypy debt ceiling 为 0 errors。
- TUI source consistency：889 runtime actions / 25 screens，0 violations；Black/isort/Ruff、runtime build manifest、架构 boundary/audit 和 active-plan registry 检查通过。

本次仅提交本地配置页面和契约修复，未部署 VPS；真实 FRP 连通性和出口 IP 验收仍待部署环境完成。

## MCP / SDK 配置补齐（2026-09-09）

默认 MCP 能力入口已增加出口与规则的清单、详情、登记、修改启停，以及指定出口测试、路径预览和连接诊断。SDK 同步提供 11 个数据中台方法，沿用已存在的后端接口；操作顺序与参数示例见 [MCP 配置说明](../development/data-egress-mcp-configuration.md)。

- 使用 owner manifest 与 native handler 注册，无需启用旧工具列表。管理员权限在 MCP 和后端分别校验。
- 四项配置写入和两项联网测试均要求预览、显式确认和幂等键；预览阶段不会写配置或发起行情请求。确认和幂等记录只在现有 MCP 进程内有效。
- 凭据字段不回显，预览与审计脱敏；SDK 保留省略字段、空密码、显式 false 和 null 的不同语义。诊断保留真实 outcome 和每次尝试结果。
- SDK/MCP 注册、核心调用、权限、确认、幂等、凭据、SDK 客户端回归合计 101 passed。
- MCP → 实际 SDK → Django API → 临时 SQLite 的持久化验收 2 passed：停用登记、确认前无写入、指定出口探测、启用顺序、规则预览、失败诊断、停用和清除凭据；后端拒绝非管理员的断言通过。网络传输使用可控结果，不连接真实行情服务。
- MCP manifest、读写证据、确认、预览、审计、工具预算、catalog 去重、TUI bridge 和 Evidence 输出契约检查通过；能力规模按实际测量更新治理基线，默认顶层工具数不变。
- 最终补齐 URL 审计脱敏：含查询参数、认证或片段的地址在审计中整体隐藏，实际 SDK 请求保持原值；含新增用例的 MCP/审计集合 38 passed。类型增量检查、全仓 mypy debt ceiling、Black/isort/Ruff、架构 boundary/audit、文档路由 SDK 一致性和 active-plan 检查通过。

本次仍是本地实现和提交；VPS 与已运行的 MCP 进程需要部署更新后重启。真实 FRP 连接、出口 IP、行情可用性和 PostgreSQL/Redis 并发验收继续保留为部署环境待办。

## 外部依据

- [frp 客户端插件](https://gofrp.org/en/docs/features/common/client-plugin/)
- [frp 插件配置（HTTP/SOCKS5）](https://gofrp.org/en/docs/reference/client-plugin/)
- [frp STCP 双端配置](https://gofrp.org/en/docs/examples/stcp/)
- [frpc 连接代理与动态更新范围](https://gofrp.org/en/docs/features/common/client/)

实施前确认：境内机器是仅运行 frps 还是可部署 frpc/代理，是否拥有管理权限；版本、端口、
网络访问范围、带宽与并发预算。规划阶段无需提供密码或 token。
