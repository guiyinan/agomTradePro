# QMT 实盘交易执行桥阶段计划

> 实施状态（2026-07-22）：仓库范围实现已完成。已交付 `broker_execution` 四层模块、六个迁移版本、服务端权威风控、动作/账户权限、Agent 机器鉴权与账户 scope/租约、登录及机器认证失败审计、恢复交易密码重认证、Fake/QMT Adapter、四维对账、P0 自动停机、告警/readiness/日报、Classic Web、canonical SDK、TUI、MCP governed capability、Windows 脚本和自动测试。目标券商 QMT/MiniQMT 的 Phase 0 兼容性探针、连续仿真和小额实盘仍必须在用户本地 Windows 与券商账户上执行，不能由仓库测试替代。

实现依据：[`ADR-0002`](../architecture/adr-0002-qmt-local-execution-bridge.md)；安装与运维：[`QMT Agent 运行手册`](../operations/qmt-agent-runbook.md)。

> 状态：仓库实现完成；生产启用被 WP0/WP7 外部验收门禁阻断
> 创建日期：2026-07-21
> 最后更新：2026-07-22
> 目标版本：待确定
> 主线类型：交易执行链路
> 推荐服务端 owner：`apps/broker_execution`（新四层业务模块）
> 依赖主线：自动投顾建议单、`risk_center`、真实账户映射、VPS HTTPS 入口

## 1. 阶段目标

在不破坏现有模拟盘链路的前提下，为 AgomTradePro 增加一个本地 Windows QMT 执行桥，使 VPS 负责信号、策略、风控和订单编排，本地 QMT Agent 负责调用券商 QMT API 下单，并将委托及成交结果回传 VPS。

最终目标不是让 VPS 直接运行 QMT，而是形成以下链路：

```text
VPS AgomTradePro
  -> 信号、策略、风控、订单指令
  -> 安全 HTTPS 拉取通道（MVP）
本地 Windows QMT Agent
  -> QMT/MiniQMT API
券商账户
  -> 委托、成交、撤单状态回传 VPS
```

## 2. 当前基线与范围

当前系统已经具备：

- `simulated_trading` 自动交易引擎和模拟账户执行逻辑；
- 风控检查、策略信号和交易记录能力；
- `real` 账户模型，但默认不启用自动交易；
- 券商成交记录手工导入及持仓同步能力。
- `apps/data_center/infrastructure/gateways/qmt_gateway.py` 已接入 QMT 行情、技术快照和历史 K 线，但明确不包含交易能力；
- 自动投顾建议单已经输出只读 `execution_plan`，真实账户当前固定 `broker_execution_enabled=false`；
- `risk_center.application.trade_guard.EvaluatePreTradeRiskUseCase` 已提供账户级交易前风控基础能力。

开始本阶段时系统尚未具备（现均已由本计划交付）：

- QMT/MiniQMT 适配器；
- VPS 到本地 QMT Agent 的订单协议；
- 委托、成交、撤单状态的实时回传；
- 实盘订单幂等、对账和紧急停止闭环。

本阶段包含 VPS 端执行抽象、通信协议、实盘记录、QMT Agent、测试和运维文档；不包含更换策略、扩大交易品种或直接扩大实盘资金规模。

### 2.1 必须保持的架构边界

- QMT 行情继续归 `data_center`，不得把下单、撤单或账户查询继续堆入现有 `QMTGateway`；
- 实盘订单生命周期由新的 `broker_execution` 模块拥有，不以 `simulated_trading` 成交表作为实盘真源；
- `simulated_trading` 保持模拟撮合职责，不直接 import `broker_execution.infrastructure`；
- `account` 只提供账户身份、归属和现有持仓投影，不直接调用 QMT；
- `risk_center` 提供统一风控用例，`broker_execution` 通过 Application API/Protocol 调用；
- 本地 Agent 是执行端，不计算投资信号、不修改策略、不自行放宽风控；
- VPS 是订单意图和审计真源，券商/QMT 是委托、成交、资金和持仓事实真源；两者不一致时进入对账状态，不静默覆盖。

## 3. 前置确认项

- [x] 确认券商名称和客户端版本：国金证券 QMT 交易端 `2.1.19.0`；
- [ ] 确认目标账户类型和实际可交易市场；当前服务端首版只接受 `STOCK`，但尚未通过券商 API 查询验证目标账户；
- [x] 确认当前使用普通 QMT（不是 MiniQMT）；外部 `xtquant` 授权方式仍被券商侧 `QMT_SERVER_NOT_ALLOWED` 阻断，须由国金开通或提供专用客户端；
- [ ] 确认 QMT 是否提供模拟账户或仿真环境；
- [ ] 确认本地 Windows 主机能够在交易时段持续运行；
- [x] 确认本地 Agent 的部署方式、默认运行账户和目录约定；安装包使用当前 Windows 用户、私有 venv、DPAPI Token、滚动日志和 SQLite 状态目录；目标机常驻安装仍待券商权限开通后执行；
- [ ] 确认实盘启用人、人工确认策略和紧急联系人。

### 3.1 本地最小安装清单

本清单按“目标机可正式运行”口径勾选；安装包中已经提供但尚未在目标机常驻启用的能力，不视为生产完成。

- [ ] 受支持的 Windows 主机，交易时段保持开机且时间自动同步；
- [ ] 券商提供的 QMT/MiniQMT 客户端及程序化交易权限；
- [ ] 可用于联调的仿真或低风险测试账户；
- [x] 已在隔离环境验证 Python `3.11.14` 与 `xtquant 250807.1.2` 可导入；与国金客户端的实际 API 兼容性仍受券商权限门禁约束；
- [x] 已交付独立 QMT Agent 安装包，不复用 VPS Django 运行环境；Agent HTTPS 客户端使用标准库，YAML 配置仅额外需要 `PyYAML`；
- [x] 安装包已定义 Agent 配置目录、滚动日志目录和本地 SQLite 状态目录，并通过临时安装 smoke；
- [x] 安装包已提供 Windows 任务计划安装选项；目标机是否启用由正式部署时决定；
- [ ] VPS HTTPS 地址、Agent 凭证和可信 CA 配置；
- [x] 安装包已提供本地 `STOP` 紧急停止文件和启动/停止控制脚本；目标机常驻运行验收待 WP0 通过后执行。

本地依赖边界如下，避免把 VPS 组件整套搬到交易电脑：

| 本地组件 | 是否必需 | 说明 |
| --- | --- | --- |
| 券商 QMT/MiniQMT | 必需 | 由券商提供并完成登录、程序化交易授权；交易时段保持运行 |
| 券商兼容 Python 3.10+ | 必需 | 必须与该 QMT 交付的 `xtquant` ABI 匹配，不能直接假设 VPS Python 可复用 |
| `xtquant` | 必需 | 仅安装在 Windows 执行端；优先使用券商/QMT 交付包，使用迅投官方发布包时必须锁定版本、校验哈希并完成目标客户端实测 |
| Agom QMT Agent | 必需 | 使用仓库 `qmt_agent/` 制品和 Windows 安装/启动脚本 |
| `PyYAML>=6.0.2` | 条件必需 | 使用 YAML 配置时由安装脚本安装；改用 JSON 配置可不安装 |
| 可信 CA/HTTPS 证书链 | 必需 | Agent 只主动出站访问 VPS，不关闭 TLS 校验 |
| Windows 任务计划 | 推荐 | 保证登录后自动启动、异常退出后可恢复；首版不要求额外第三方服务管理器 |
| Django、Redis、Celery、PostgreSQL、`requests` | 不需要 | 这些属于 VPS；Agent HTTPS 客户端使用 Python 标准库，本地状态使用内置 SQLite |

不得在 Agent 配置中保存 QMT 登录密码。QMT 登录和交易权限由券商客户端管理；Agent 只保存执行桥所需的账户标识、`userdata_mini` 路径和 VPS 凭证。

### 3.2 Phase 0 兼容性验证门禁

开发服务端前，先在目标电脑完成一份真实环境探针报告，至少记录：

- Windows 版本、QMT/MiniQMT 名称和版本、券商名称；
- QMT 提供的 Python/`xtquant` 版本及支持的 Python ABI；
- `userdata_mini` 实际路径；
- 普通账户或信用账户类型及账户标识格式；
- 查询资产、持仓、委托、成交是否成功；
- 仿真环境中最小数量报单和撤单是否成功；
- 下单接口是否支持备注字段，并验证 23 字符 Agom UUID Base64URL 紧凑编码能完整回传；官方字段上限为 24 个英文字符，禁止直接写入 36 字符 UUID；
- 回调、主动查询和断线重连行为；
- 券商对程序化交易、频率、品种和时间段的限制。

当前 Agent 的最低语法基线是 Python 3.10。如果目标 `xtquant` 不支持 Python 3.10+，WP0 直接判定不通过，必须把本地 Agent 作为独立兼容制品处理并单独验收，同时先形成依赖声明 ADR；不得为适配 QMT 降低 VPS 主项目 Python 版本，也不得手工修改 `requirements-*.txt`。

### 3.3 当前目标机实测记录（2026-07-22）

本节只记录脱敏兼容性证据，不记录券商账号、资金金额、持仓代码或凭证。

| 项目 | 实测结果 |
| --- | --- |
| 券商与客户端 | 国金证券 QMT 交易端 `2.1.19.0`，安装于 `D:\qmt` |
| 当前客户端模式 | 普通 `XtItClient` 会话；未发现 `XtMiniQmt`、`minibroker`、`miniquote` 进程 |
| 客户端内嵌策略环境 | Python `3.6.8`；该环境用于 QMT 内嵌模型，不作为 Agom QMT Agent 运行时 |
| 独立 Agent 兼容环境 | Python `3.11.14` + 迅投发布 `xtquant 250807.1.2` 可成功导入 |
| SDK 供应链校验 | wheel SHA-256 与发布页记录一致；仅在隔离临时目录验证，尚未安装为常驻 Agent 环境 |
| QMT 数据目录 | 普通端 `D:\qmt\userdata` 存在；`userdata_mini` 和 xtquant 上下行队列文件不存在 |
| 真实只读探针 | 登录后客户端日志明确记录 `The XtQuantServer is not allowed to start.`，归一错误码为 `QMT_SERVER_NOT_ALLOWED`；未进入资产、持仓、当日委托、当日成交查询 |
| 交易副作用 | `submitted_order=false`、`canceled_order=false`，未调用报单和撤单方法 |
| 当前结论 | WP0 尚未通过；国金客户端明确拒绝启动 XtQuantServer，必须由券商开通外部 xtquant/函数查询/函数下单权限或提供专用客户端版本 |

迅投官方资料说明：普通投研端连接目录可使用 `userdata`，MiniQMT 使用 `userdata_mini`。目标国金 QMT `2.1.19.0` 登录页没有“极简模式”，所以安装包必须支持普通端 `userdata`，且不得把“客户端已登录”或“独立交易”选项等同于“外部交易 API 已就绪”。

## 4. 高层分阶段实施计划

### Phase 1：执行模型和通信协议

- 冻结统一执行边界：服务端以订单/租约/事件 Application Port 作为实盘 gateway，本地以 `BrokerAdapter` Protocol 隔离 QMT；
- 保留现有模拟盘执行器，新增实盘执行器边界；
- 定义订单指令、订单状态、成交回报、撤单回报和错误格式；
- 使用全局唯一 `client_order_id`，保证重试不会重复下单；
- 设计 Agent 心跳、断线重连、过期订单和时间窗口校验；
- 确定 Token 或 mTLS 鉴权方案。

交付物：协议文档、接口草图、状态机和异常码表。

### Phase 2：VPS 端订单编排

- 将信号和风控结果转换为待执行订单；
- 实盘账户与模拟账户隔离；
- 订单提交前执行资金、仓位、价格、数量、交易时间和重复订单检查；
- 增加人工确认开关，默认关闭自动实盘；
- 增加订单、委托、成交、撤单和失败记录；
- 增加订单查询、取消和紧急停止接口。

交付物：VPS 端 Application Facade、Infrastructure Repository、API 契约测试。

### Phase 3：本地 QMT Agent

- 实现 Windows 本地 Agent；
- 从 VPS 拉取或接收待执行订单；
- 校验股票代码、市场、方向、价格和数量；
- 调用 QMT/MiniQMT 下单接口；
- 查询委托和成交状态并回传 VPS；
- 支持部分成交、拒单、撤单、超时和重连；
- 提供本地暂停交易和立即停止功能。

交付物：Agent 程序、配置样例、启动脚本、日志规范和安装文档。

### Phase 4：安全与风控收口

- 单笔金额上限；
- 单日交易金额上限；
- 单票仓位和最大持仓数量上限；
- 交易时段和交易日校验；
- 买卖方向与可用持仓校验；
- VPS 端和本地 Agent 双重停止开关；
- 敏感凭证不进入代码、日志和普通 API 响应；
- 本地 Agent 仅主动访问 VPS，不开放公网入站端口；
- 所有实盘动作写入不可抵赖的审计日志。

交付物：风控清单、安全配置说明、停止和恢复流程。

### Phase 5：对账和运维

- 对比 VPS 订单状态与 QMT 委托状态；
- 对比 VPS 持仓与券商实际持仓；
- 处理成交回报丢失、重复回报和人工补录；
- 增加异常告警和交易日运行报告；
- 支持从 QMT 导出成交记录进行人工或自动校准；
- 保留现有手工成交导入作为故障兜底。

交付物：对账任务、异常报告、故障处理手册和回滚方案。

## 5. 测试与验收顺序

1. 单元测试：订单状态机、幂等、数量和价格校验、风控拒绝逻辑；
2. 契约测试：VPS 与 Agent 的订单及回报接口；
3. 离线测试：模拟 QMT API 的下单、成交、拒单和断线场景；
4. QMT 仿真测试：连续运行至少一个完整交易周期；
5. 小额实盘：人工确认、单笔和单日额度严格限制；
6. 自动执行验收：连续运行、订单不重复、成交可回传、持仓可对账；
7. 扩大资金前复核：策略、风控、日志、告警、停止开关和回滚均通过验收。

## 6. 完成标准

- 模拟盘功能和数据不受影响；
- 实盘订单默认不能绕过风控和账户隔离；
- 每笔订单都有唯一 ID、状态变化和审计记录；
- 网络重试不会造成重复下单；
- 委托、成交、撤单和拒单状态能够回传并落库；
- VPS 与券商持仓能够完成对账；
- 本地或 VPS 任一侧均可紧急停止后续下单；
- QMT 仿真和小额实盘通过连续运行验收；
- 未经明确启用，不允许自动实盘。
- Classic Web 能完成连接检查、订单确认、执行跟踪、对账和紧急停止五类主任务；
- TUI 发布面向用户的独立 screen/action，并满足 metadata schema、运行时注入和结果模型门禁；
- MCP 通过 governed capability registry 提供受控查询和高风险写入，不新增散装顶层 raw tools；
- Web、TUI、SDK、MCP 对同一业务动作复用唯一 Application UseCase、权限规则和审计语义。

## 7. 风险与回滚点

| 风险 | 控制措施 | 回滚方式 |
| --- | --- | --- |
| QMT API 或券商接口不兼容 | 先做适配器验证和仿真测试 | 保持仅模拟盘运行 |
| 网络中断导致状态不一致 | 幂等 ID、状态查询、对账任务 | 停止 Agent，改用手工导入 |
| 重复下单 | VPS 和 Agent 双重幂等校验 | 撤销未成交委托并禁用实盘开关 |
| 错误数量或价格 | 交易规则、金额和仓位上限 | 拒绝订单，不进入 QMT |
| VPS 或本地程序异常 | 心跳、过期订单和紧急停止 | 切换为人工确认或模拟盘 |
| 成交回报丢失 | 主动查询和日终对账 | 使用 QMT 成交文件手工校准 |
| 凭证泄露 | 凭证只保存在本地 QMT 环境 | 立即撤销凭证并停止 Agent |

## 8. 明确不做的事项

- 不把 QMT 直接安装到现有 Linux VPS；
- 不把模拟盘执行器直接改造成实盘执行器；
- 不公开暴露本地 QMT 控制端口；
- 不在第一阶段支持多券商、多 Agent 和复杂组合路由；
- 不在技术链路验收前扩大实盘资金；
- 不删除现有手工成交导入和持仓校准能力。

## 9. 相关代码基线

- `apps/simulated_trading/application/auto_trading_engine.py`
- `apps/simulated_trading/application/ports.py`
- `apps/simulated_trading/application/tasks.py`
- `apps/simulated_trading/infrastructure/account_gateway.py`
- `apps/account/application/manual_trade_sync.py`
- `apps/data_center/infrastructure/gateways/qmt_gateway.py`
- `apps/risk_center/application/trade_guard.py`
- `docs/development/unified-financial-datasource-registry.md`
- `docs/plans/auto-advisor-implementation-2026-06-25.md`

## 10. 推荐模块和文件归属

### 10.1 VPS 服务端

建议新增完整四层业务模块 `apps/broker_execution/`：

```text
apps/broker_execution/
├── domain/
│   ├── entities.py          # 订单、成交、状态事件值对象
│   ├── rules.py             # 状态转换、过期、幂等和提交规则
│   └── services.py          # 纯订单状态机
├── application/
│   ├── dtos.py
│   ├── ports.py             # 账户、风控、订单仓储、审计 Protocol
│   ├── use_cases.py         # 建单、审批、租约、回报、撤单、停止
│   ├── query_services.py
│   └── tasks.py             # 对账、过期订单、健康检查
├── infrastructure/
│   ├── models.py
│   ├── repositories.py
│   └── consumer_gateways.py
└── interface/
    ├── serializers.py
    ├── api_views.py
    └── api_urls.py
```

Application 和 Interface 层不得直接 import ORM；跨 App 数据只能通过 Facade、Application UseCase 或注入的 Protocol 获取。

### 10.2 本地 Agent

本地 Agent 应保持为无 Django 依赖的薄客户端，推荐逻辑分层：

```text
qmt_agent/
├── api_client.py            # 与 VPS 通信
├── qmt_adapter.py           # 唯一允许 import xtquant 的位置
├── executor.py              # 租约、校验、提交、查询和回传编排
├── state_store.py           # 本地幂等和恢复状态
├── health.py
├── config.py
└── main.py
```

Agent 最终在本仓库还是独立制品中维护，由 Phase 0 的 Python 兼容性结论决定。无论放置位置如何，`xtquant` 都不得成为 VPS 生产镜像的强依赖。

## 11. 核心领域对象和数据真源

首版建议至少包含以下持久化对象：

| 对象 | 用途 | 唯一性/关键约束 |
| --- | --- | --- |
| `BrokerAgent` | 已授权本地执行端及心跳 | `agent_id` 唯一，凭证只存哈希 |
| `BrokerAccountBinding` | 系统账户与 QMT 账户映射 | 一个实盘账户只能绑定一个生效执行端 |
| `LiveOrder` | VPS 订单意图和生命周期真源 | `client_order_id` 全局唯一 |
| `OrderLease` | Agent 拉单租约 | 同一订单同一时刻最多一个有效租约 |
| `BrokerOrderEvent` | 原始委托状态事件 | `(agent_id, event_id)` 唯一 |
| `BrokerFill` | 券商成交事实 | `(broker_account, broker_trade_id)` 唯一 |
| `BrokerAccountSnapshot` | 资金快照 | 账户、采集时间唯一 |
| `BrokerPositionSnapshot` | 持仓快照 | 账户、标的、采集时间唯一 |
| `ReconciliationRun` | 对账批次和差异 | 保存差异、处置状态和证据 |
| `TradingKillSwitchAudit` | 停止/恢复审计 | 记录操作者、原因和时间 |

所有金额和数量使用 `Decimal`；所有时间使用 timezone-aware datetime；券商原始字段保存在审计 payload 中，但不得包含密码、Token 或其他密钥。

### 11.1 `LiveOrder` 最小字段

- `client_order_id`、`account_id`、`agent_id`；
- `asset_code`、`market`、`side`、`order_type`；
- `quantity`、`limit_price`、`estimated_amount`；
- `source_recommendation_ids`、`source_signal_ids`；
- `risk_policy_version`、`risk_snapshot`、`approval_mode`；
- `status`、`expires_at`、`approved_at`、`submitted_at`；
- `broker_order_id`、`filled_quantity`、`average_fill_price`；
- `failure_code`、`failure_message`；
- `created_at`、`updated_at`、`version`。

订单保存批准时的风险和数据快照，避免后续配置变化导致无法审计当时为何允许下单。

## 12. 订单状态机

建议状态流：

```text
DRAFT
  ├─> RISK_REJECTED
  └─> WAITING_APPROVAL
         ├─> REJECTED
         └─> READY
                ├─> EXPIRED
                └─> LEASED
                       ├─> READY                 # 提交前租约安全过期
                       └─> SUBMITTING
                              ├─> BROKER_REJECTED
                              ├─> FAILED         # 已确认未进入券商
                              ├─> RECONCILIATION_REQUIRED
                              └─> SUBMITTED
                                     ├─> BROKER_REJECTED   # QMT 已受理但柜台后续废单
                                     ├─> PARTIALLY_FILLED ─> FILLED
                                     ├─> FILLED
                                     └─> CANCEL_PENDING
                                            ├─> CANCELED
                                            ├─> PARTIALLY_FILLED
                                            ├─> FILLED
                                            └─> RECONCILIATION_REQUIRED
```

硬规则：

- `RISK_REJECTED`、`REJECTED`、`EXPIRED`、`BROKER_REJECTED`、`FAILED`、`FILLED`、`CANCELED` 为终态；
- `FAILED` 仅用于确认未被券商接受的失败；
- Agent 在提交后超时、崩溃或无法确认结果时，必须进入 `RECONCILIATION_REQUIRED`；
- `RECONCILIATION_REQUIRED` 不得自动重新报单，必须先查询券商委托和成交；
- 已过 `expires_at` 的订单不得被领取或提交；
- 卖单提交前再次读取 QMT 可用持仓，买单提交前再次读取可用资金；
- 状态更新使用版本号或条件更新，防止并发回报覆盖新状态。

## 13. MVP 通信契约

MVP 使用 Agent 主动访问 VPS 的 HTTPS 拉取模式，不要求本地公网 IP，不开放 QMT 或 Agent 入站端口，也不把 WebSocket 作为首版依赖。

建议 Agent 专用契约：

| 动作 | 语义 |
| --- | --- |
| `heartbeat` | 上报 Agent/QMT 连接、账户和版本健康状态 |
| `lease orders` | 原子领取少量 `READY` 订单并返回租约过期时间 |
| `ack submitting` | 提交前确认 Agent 已进入不可盲重试区间 |
| `report events` | 幂等批量回传委托、成交、撤单和错误事件 |
| `sync account snapshot` | 上报资金、持仓、当日委托和当日成交快照 |
| `lease commands` | 领取撤单、暂停、恢复或全量同步命令 |

### 13.1 请求通用字段

- `contract_version`；
- `agent_id`；
- `request_id`；
- `sent_at`；
- `nonce`；
- 请求签名或客户端证书身份。

### 13.2 幂等规则

- VPS 建单幂等键：账户、交易日、最终订单意图 ID；
- Agent 提交幂等键：`client_order_id`；
- 事件回传幂等键：Agent 生成的 `event_id`；
- 成交幂等键：券商账户和 `broker_trade_id`；
- Agent 必须在本地持久化“已进入 SUBMITTING”的订单，进程重启后先查单再决定后续动作；
- 如果 QMT 备注字段可靠，应写入可逆的 23 字符 Agom UUID Base64URL 紧凑编码，并在查询结果中还原 `client_order_id`；禁止直接写入超过官方 24 字符上限的 UUID。如果备注不可靠，必须通过账户、标的、方向、数量、价格和时间窗口进行保守匹配，并将结果标记为需要复核。

## 14. 本地 Agent 配置契约

建议配置项：

```yaml
agent_id: qmt-home-01
server_url: https://example.invalid
qmt_userdata_path: C:/QMT/userdata_mini
broker_account_id: "***"
broker_account_type: STOCK
poll_interval_seconds: 2
lease_seconds: 30
dry_run: true
log_dir: C:/AgomQmtAgent/logs
state_dir: C:/AgomQmtAgent/state
kill_switch_file: C:/AgomQmtAgent/STOP
```

Token、私钥等敏感字段通过 Windows 凭据管理器、受限环境变量或受权限保护的独立密钥文件加载，不写入普通 YAML，不回传到 VPS 日志。

启动顺序：

1. 启动并登录 QMT/MiniQMT；
2. Agent 检查 `userdata_mini`、账户和 API 连接；
3. 查询资产、持仓、委托和成交，建立启动基线；
4. 向 VPS 发送心跳；
5. `dry_run=true` 时只拉单和校验，不调用下单；
6. 通过启用门禁后才允许提交真实委托。

## 15. 风控与执行门禁

每笔订单至少经过两次检查：

### 15.1 VPS 批准前

- 账户归属和 QMT 绑定有效；
- 自动投顾建议单未被数据健康、执行节奏或暴露规则阻断；
- `risk_center` 有效策略检查通过；
- 单笔、单日、单票和总仓位限制通过；
- 订单价格、数量、最小交易单位和涨跌停边界合法；
- 实盘总开关、账户开关和 Agent 开关全部开启；
- 需要人工确认的订单已明确批准。

### 15.2 Agent 提交前

- QMT 在线且目标账户一致；
- 租约有效，订单未过期，订单状态仍允许提交；
- 本地停止开关未触发；
- 买单可用资金足够，卖单可用数量足够；
- 标的、市场、方向、数量和价格与签名 payload 一致；
- 当地时间处于允许提交窗口；
- 本地幂等记录中不存在已提交结果。

Agent 只能收紧限制，不能放宽 VPS 风控。任一关键数据缺失时默认拒绝提交。

## 16. 身份、权限与审计控制（P0）

实盘执行使用“用户身份”和“机器身份”两套独立认证域。现有 `apps.account.application.rbac` 继续作为用户角色的粗粒度入口，但当前 `read/write + domain` 矩阵不足以区分建单、审批、启停和账户绑定，因此 `broker_execution` 必须增加动作级能力检查，不能只判断 `TradingPermission` 或 `is_staff`。

### 16.1 用户角色与动作权限

首版复用现有角色：`admin`、`owner`、`investment_manager`、`trader`、`risk`、`analyst`、`read_only`。推荐权限矩阵如下：

| 动作 | owner | investment_manager | trader | risk | analyst/read_only | admin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 查看本人实盘账户、订单和成交 | ✓ | 授权账户 | 授权账户 | 授权账户 | 只读授权 | ✓ |
| 从建议单生成订单草稿 | ✓ | 授权账户 | 授权账户 | × | × | ✓ |
| 批准普通实盘订单 | 可配置 | ✓ | 可配置 | × | × | ✓ |
| 拒绝或撤销未提交订单 | ✓ | ✓ | ✓ | 风控阻断 | × | ✓ |
| 请求撤销已提交委托 | ✓ | ✓ | ✓ | 风控紧急撤单 | × | ✓ |
| 触发紧急停止 | ✓ | ✓ | ✓ | ✓ | × | ✓ |
| 恢复实盘交易 | × | × | × | 联合批准 | × | ✓＋二次确认 |
| 修改实盘额度和白名单 | × | × | × | 建议/复核 | × | ✓＋二次确认 |
| 绑定或更换 QMT 账户/Agent | × | × | × | × | × | ✓＋二次确认 |
| 开启受限自动实盘 | × | × | × | 联合批准 | × | ✓＋二次确认 |
| 创建、轮换或撤销 Agent 凭证 | × | × | × | × | × | ✓ |
| 授予或撤销非所有者的账户级权限 | × | × | × | × | × | ✓＋二次确认 |

“授权账户”必须是显式账户级授权，不得因角色拥有交易域写权限就访问全部账户。个人单用户部署可以允许 `owner` 审批本人普通订单，但绑定账户、提高限额、恢复交易和开启自动实盘仍保留管理员级二次确认。

### 16.2 动作级能力

建议在 `broker_execution` Application 层定义稳定能力名，并由权限服务映射现有角色：

```text
broker_execution.view
broker_execution.create_draft
broker_execution.approve
broker_execution.reject
broker_execution.request_cancel
broker_execution.trigger_kill_switch
broker_execution.resume_trading
broker_execution.manage_limits
broker_execution.manage_binding
broker_execution.manage_access
broker_execution.enable_auto_execution
broker_execution.manage_agent_credentials
broker_execution.resolve_reconciliation
```

每个写用例必须同时检查：用户已认证、动作能力、账户归属/授权、订单当前状态和资源版本。Interface 层权限类只做入口拦截，Application UseCase 必须再次执行授权，防止任务、SDK、MCP 或内部调用绕过 HTTP 权限。

### 16.3 QMT Agent 机器权限

Agent 不映射成人类用户角色，也不复用普通 MCP/SDK Token。Agent 凭证只允许：

```text
agent.heartbeat.write
agent.orders.lease
agent.orders.submitting_ack
agent.events.write
agent.snapshots.write
agent.commands.lease
```

Agent 明确禁止：

- 创建或批准订单；
- 修改订单标的、方向、价格和数量；
- 修改风险配置、额度、白名单或审批规则；
- 绑定其他券商账户；
- 恢复 VPS 实盘开关；
- 调用普通用户、管理员、SDK 或 MCP 接口；
- 读取其他 Agent 或其他券商账户的数据。

Agent 凭证必须绑定 `agent_id`、允许的 `broker_account_id`、能力集合和有效期。VPS 每次请求都同时验证凭证、Agent 状态和账户绑定，不能只信任请求体中的 `agent_id`。

### 16.4 凭证生命周期和请求安全

- 原始凭证只在创建时显示一次，服务端只保存不可逆哈希或公钥；
- 支持创建、短期重叠轮换、立即撤销和强制失效；
- Agent 被停用、账户解绑或 kill switch 触发时，相关订单租约和提交权限立即失效；
- 请求包含 `request_id`、`sent_at`、`nonce` 和签名，服务端限制允许的时钟偏差并拒绝 nonce 重放；
- 凭证不得出现在 URL、普通日志、错误响应、截图和诊断包中；
- 不使用普通用户会话 Cookie 执行 Agent API；
- 高风险人工动作启用 CSRF、防重放、重新认证和二次确认；
- 若系统尚未具备可靠 MFA，自动实盘不得作为默认启用能力。

### 16.5 审批完整性与双人复核

批准动作必须绑定不可变的订单摘要哈希，至少覆盖账户、标的、方向、订单类型、数量、价格、有效期、风险版本和来源建议。批准后任一关键字段变化都使原批准失效，订单返回 `WAITING_APPROVAL`。

建议提供可配置的双人复核规则：

- 超过单笔金额阈值；
- 提高账户或全局实盘限额；
- 开启自动实盘；
- 恢复因 P0 告警触发的停止状态；
- 更换券商账户或 Agent 绑定；
- 手工处置可能导致补单的对账差异。

双人复核场景中，发起人与最终批准人不得是同一身份。个人单用户模式无法满足双人复核时，应降级为人工逐单确认、较低限额和延迟生效，并在审计记录中明确模式。

### 16.6 紧急停止与恢复权限

- 紧急停止采用宽授权：`owner/investment_manager/trader/risk/admin` 均可触发；
- 停止后禁止新建可执行订单、批准、领取和提交，只保留查询、回报、撤单和对账；
- 本地 STOP 文件可以单方面阻止 Agent 下单，但不能恢复 VPS；
- 恢复采用窄授权：管理员重新认证，必要时由风险角色联合批准；
- 恢复前必须确认 Agent 在线、QMT 账户一致、未知订单已对账、差异已处置；
- 停止和恢复必须记录原因、操作者、来源 IP/Agent、时间和受影响账户。

### 16.7 审计事件

以下事件必须进入只追加审计记录：

- 登录失败、权限拒绝和账户越权尝试；
- Agent 凭证创建、轮换、撤销和认证失败；
- 账户绑定、解绑和执行端变更；
- 订单创建、风险拒绝、批准、拒绝、提交、撤单和状态人工修正；
- 限额、白名单、审批模式和自动实盘开关变更；
- kill switch 触发和恢复；
- 对账差异的确认、忽略、修复和补录。

审计记录至少包含 `actor_type`、`actor_id`、`action`、`account_id`、`resource_type/id`、`before/after` 摘要、`reason`、`request_id`、时间和结果。敏感字段必须脱敏；普通用户不得删除或覆盖审计记录。

### 16.8 权限验收门禁

- 未认证请求全部拒绝；
- 普通用户不能访问不属于自己或未授权的账户；
- `trader` 不能修改风控、账户绑定或启用自动实盘；
- `risk` 可以阻断和停止，但不能自行下单；
- Agent 不能调用任何人类审批或管理动作；
- 被撤销的 Agent 凭证立即无法领取新订单和提交回报；
- 修改已批准订单的任一关键字段会使批准失效；
- 停止状态下所有新提交路径，包括 HTTP、任务、SDK、MCP 和内部 UseCase，均被阻断；
- 恢复操作必须经过重新认证和审计；
- 权限服务、账户授权或身份数据不可用时默认拒绝实盘写操作。

## 17. Classic Web、TUI 与 MCP 交付范围

三类入口共享同一业务 owner 和 canonical 契约：

```text
Classic Web ─┐
TUI ─────────┼─> broker_execution canonical API / Application Facade
SDK ─────────┘

External Agent / Terminal Agent
  -> MCP core tools
  -> broker_execution governed capability
  -> formal SDK / canonical API
```

Classic Web 和 TUI 不经 MCP 调用业务功能。MCP 不复制页面 JSON、TUI metadata、Django View 或内部 Agent 拉单接口；所有入口最终必须落到相同的 Application UseCase、权限检查、幂等规则和审计记录。

### 17.1 共用用户任务和信息优先级

用户侧按以下任务组织，不按数据库表或 API 目录组织：

| 优先级 | 用户任务 | 必须回答的问题 |
| --- | --- | --- |
| P0 | 判断今天能否实盘 | Agent/QMT 是否在线、账户是否匹配、实盘开关和停止开关状态、是否有未知订单或未处置差异 |
| P0 | 确认待执行订单 | 买卖什么、数量/价格、预计金额、来源建议、风险检查、有效期和审批要求 |
| P0 | 紧急停止 | 停止范围、当前未成交委托、停止后仍允许的撤单/对账动作 |
| P1 | 跟踪委托和成交 | 当前状态、已成交数量、均价、券商订单号、状态更新时间和异常原因 |
| P1 | 处理对账差异 | VPS 与券商在哪些订单、成交、资金或持仓上不一致，建议如何处置 |
| P2 | 管理连接和权限 | Agent 版本、绑定账户、凭证状态、额度、白名单和审批模式 |
| P2 | 查看审计 | 谁在何时批准、撤单、启停、改限额或处置差异 |

所有页面和 TUI 首屏先展示 P0 状态，不把 Agent Token、内部 endpoint、HTTP method、裸 path placeholder 或 QMT 本地路径暴露给普通用户。

### 17.2 Classic Web 页面

建议新增以下页面路由，页面路由放 `urls.py`，JSON API 放 `api_urls.py`：

| 页面 | 主任务 | 主要内容 | 主要动作 |
| --- | --- | --- | --- |
| `/broker-execution/` | 判断能否交易 | Agent/QMT/账户状态、开关、待确认数、未知订单、差异和当日成交摘要 | 进入待确认订单、紧急停止 |
| `/broker-execution/orders/` | 管理订单 | 状态、账户、标的、方向、数量、价格、来源、审批和异常筛选 | 预览确认、批准、拒绝、请求撤单 |
| `/broker-execution/orders/<id>/` | 复核单笔订单 | 风控快照、审批摘要、状态时间线、券商事件、成交和审计 | 批准、拒绝、撤单、进入对账 |
| `/broker-execution/reconciliation/` | 处理差异 | 订单、成交、资金、持仓差异及证据 | 标记已核验、接受券商事实、手工校准、升级处理 |
| `/broker-execution/connection/` | 管理本地连接 | Agent 健康、QMT 版本、账户绑定、最后同步和凭证状态 | 测试连接、轮换/撤销凭证、解绑 |
| `/broker-execution/settings/` | 管理实盘策略 | 执行模式、额度、白名单、审批模式和自动实盘门禁 | 预览并确认变更 |
| `/broker-execution/audit/` | 审计追踪 | 权限拒绝、审批、提交、撤单、启停、凭证和差异处置 | 只读筛选和导出 |

#### 首页 P0 区块

`/broker-execution/` 首屏至少包含：

1. “今日能否交易”结论：`READY / REVIEW / STOPPED / OFFLINE`；
2. 本地连接：Agent 心跳、QMT 连接、账户匹配和最后同步时间；
3. 待我确认：订单数量、预计总金额和最早过期时间；
4. 执行异常：`SUBMITTING` 超时、`RECONCILIATION_REQUIRED`、拒单和部分成交；
5. 对账差异：未处置订单、成交、资金和持仓差异；
6. 紧急停止：当前状态、影响范围和可执行按钮。

#### 页面交互规则

- 所有高风险按钮先调用 preview，展示账户、标的、方向、数量、价格、风险版本、影响和不可逆性；
- 批准页必须显示审批摘要哈希对应的业务字段，确认后字段变化则批准失效；
- 紧急停止按钮始终可见，但恢复按钮只对授权管理员显示；
- 轮换凭证只在创建成功后显示一次完整值，使用 `copyable_secret` 语义，离开页面后不再回显；
- 列表筛选不改变状态，刷新不得触发外部 QMT 调用或写数据库；
- 页面空态必须给出下一步，例如“本地 Agent 未连接，请先完成 Windows 端安装并发送心跳”；
- 普通用户看不到其他用户的账户、订单、Agent、对账或审计记录。

### 17.3 canonical API 与前端 ViewModel

建议按任务提供稳定 API，不把 ORM Model 直接序列化给页面：

| API 语义 | 用途 | 副作用分类 |
| --- | --- | --- |
| `overview` | 汇总用户可见账户的交易就绪、连接、订单和差异 | strict read |
| `order catalog/detail` | 查询订单目录、详情、事件时间线和成交 | strict read |
| `approval preview/commit` | 生成批准预览并在确认后批准 | governed write |
| `reject order` | 拒绝尚未提交订单 | governed write |
| `cancel preview/commit` | 预览并请求撤销券商委托 | governed write/workflow |
| `kill-switch preview/commit` | 预览并停止指定账户或全局执行 | high-risk write |
| `resume preview/commit` | 核验恢复条件后恢复 | admin high-risk write |
| `connection status` | 查询 Agent/QMT/账户同步状态 | strict read |
| `credential rotate/revoke` | 管理 Agent 凭证 | admin high-risk write |
| `reconciliation catalog/detail` | 查询对账批次和差异 | strict read |
| `reconciliation resolve` | 处置差异并写审计 | high-risk workflow |
| `audit catalog` | 查询当前用户有权查看的审计记录 | strict read |

所有 strict read 必须只读取持久化快照，不在 GET 中连接 QMT、刷新状态、创建默认对象、投递任务或写缓存。需要主动探测 QMT 的“测试连接/立即同步”按 workflow/write 处理。

页面 ViewModel 应统一输出 `status/summary/data/warnings/next_actions/permissions`，其中 `permissions` 只用于控制界面展示，服务端仍必须在写 UseCase 中重新鉴权。

### 17.4 TUI 模块、screen 与 action

逻辑能力仍使用 `broker-execution.*` 稳定 key；实现按当前 TUI 信息架构收口到两个用户主屏，避免新增六个碎片化导航入口：订单、连接和启停映射到 `execution.accounts`，对账和审计映射到 `execution.audit`。下表中的逻辑 screen 作为 runtime source/action owner 保留：

| Screen key | 主任务 | 默认/P0 Action |
| --- | --- | --- |
| `broker-execution.overview` | 判断今天是否可以安全交易 | `broker-execution.overview` |
| `broker-execution.orders` | 查看和处理待确认/执行中订单 | `broker-execution.order-list` |
| `broker-execution.order-detail` | 复核一笔订单及完整证据 | `broker-execution.order-detail` |
| `broker-execution.reconciliation` | 查看和处置对账差异 | `broker-execution.reconciliation-list` |
| `broker-execution.connection` | 管理 Agent/QMT 连接与账户绑定 | `broker-execution.connection-status` |
| `broker-execution.audit` | 查看实盘审计时间线 | `broker-execution.audit-list` |

建议 Action key：

```text
broker-execution.overview
broker-execution.order-list
broker-execution.order-detail
broker-execution.approval-preview
broker-execution.approve-order
broker-execution.reject-order
broker-execution.cancel-preview
broker-execution.request-cancel
broker-execution.kill-switch-preview
broker-execution.trigger-kill-switch
broker-execution.resume-preview
broker-execution.resume-trading
broker-execution.connection-status
broker-execution.test-connection
broker-execution.reconciliation-list
broker-execution.reconciliation-detail
broker-execution.resolve-reconciliation
broker-execution.audit-list
```

#### TUI metadata 约束

- `broker-execution.overview` 作为 dashboard screen，必须提供可执行 P0 panel；
- 其他 screen 必须声明 `default_action_key`；
- 每个 screen 发布 `user_experience.primary_task` 和 `primary_outcome`；
- `dashboard_panels` 使用 `user_priority=p0/p1/p2` 和明确 `presentation_semantic`；
- Agent Token 仅在管理员创建成功结果中使用 `copyable_secret`，不得放进通用 datagrid；
- 订单风险解释和差异说明使用业务文案，不展示 API endpoint、method 或内部 path；
- 写 Action 必须标注 `risk=write`、`confirmation_required=true`，并区分 preview 与 commit；
- TUI 只调用 canonical API，不通过 MCP 间接调用；
- action 可见性按运行时权限裁剪，但服务端仍进行动作级和账户级鉴权；
- overview 的结果模型应显式突出 `today_readiness`、`kill_switch`、`pending_approvals`、`execution_exceptions` 和 `reconciliation_differences`。

#### TUI 实现文件

实施时至少同步：

- `config/tui/schema/tui_metadata.schema.v3.json`（仅新增类型/语义时修改）；
- `apps/terminal/application/tui_metadata.py`；
- 新的 `apps/terminal/infrastructure/tui_metadata_runtime_injection_broker_execution.py`；
- 对应 runtime screen patch 和 runtime injection 聚合注册；
- `apps/terminal/application/tui_workbench_result_models_specialized.py` 或拆分后的 broker execution result model；
- `tests/unit/test_tui_workbench.py` 的 screen/action/result/permission/confirmation 覆盖；
- metadata compiler、promotion 和 schema validation 证据。

### 17.5 MCP governed capability

MCP 面只通过现有固定 core tools 暴露 capability discovery/schema/call/confirmation，不为 QMT 增加一组新的顶层 raw tools，也不暴露 Agent 拉单、心跳、事件回传或快照同步等机器内部接口。

#### MCP 只读能力

| Capability key | 任务 | 输出 envelope |
| --- | --- | --- |
| `broker_execution.read.overview` | 查询当前用户实盘就绪和异常摘要 | `overview` |
| `broker_execution.read.order_catalog` | 查询当前用户可见订单 | `orders + total_count` |
| `broker_execution.read.order_detail` | 查询单笔订单、审批、事件和成交 | `order` |
| `broker_execution.read.connection_status` | 查询 Agent/QMT/绑定账户健康 | `connections + total_count` |
| `broker_execution.read.reconciliation_catalog` | 查询对账批次和差异 | `runs + total_count` |
| `broker_execution.read.audit_catalog` | 查询有权查看的审计事件 | `events + total_count` |

只读能力只能调用 strict persisted-only canonical GET；不得在读取时连接 QMT、领取订单、刷新快照、回收租约、触发同步或写缓存。

#### MCP 写入/工作流能力

| Capability key | 风险 | 必须满足 |
| --- | --- | --- |
| `broker_execution.approve.order` | high | owner-scoped、preview-first、`expected_version`、confirmation、idempotency、审批摘要哈希、审计 |
| `broker_execution.reject.order` | high | owner-scoped、preview-first、`expected_version`、confirmation、idempotency、审计 |
| `broker_execution.request.cancel` | high workflow | preview 当前成交/可撤数量、`expected_version`、confirmation、idempotency、审计 |
| `broker_execution.trigger.kill_switch` | high | preview 影响账户和未成交单、confirmation、idempotency、审计 |
| `broker_execution.resume.trading` | admin | readiness 复核、重新认证/角色门禁、confirmation、idempotency、审计 |
| `broker_execution.resolve.reconciliation` | high workflow | preview 差异和拟处置结果、confirmation、idempotency、审计 |

首版 MCP 不提供“直接创建任意实盘订单”或“直接调用 QMT 下单”能力。订单必须来自系统已生成并通过风控的 `LiveOrder`；MCP 只能对现有订单执行有权限的批准、拒绝、撤单和治理动作。

#### MCP 注册与实现位置

已实现位置：

```text
sdk/agomtradepro/modules/broker_execution.py
sdk/agomtradepro_mcp/registry/modules/owners/broker_execution_read_capabilities.py
sdk/agomtradepro_mcp/registry/modules/owners/broker_execution_write_capabilities.py
sdk/agomtradepro_mcp/registry/runtime_handlers/owners/broker_execution.py
sdk/tests/test_mcp/test_core_registry_owner_broker_execution.py
sdk/tests/test_sdk/test_broker_execution.py
tests/unit/test_ai_capability/test_mcp_broker_execution_catalog.py
```

能力必须声明唯一 `owner_app="broker_execution"`、稳定 JSON Schema、`required_roles`、`requires_confirmation`、`idempotency="required"` 和 `audit_tags`。写能力使用受控 `internal_handler` 完成 preview/commit，不把业务逻辑写进 MCP handler；commit 仍调用正式 SDK/canonical API，由服务端再次检查权限、状态、风险和停止开关。

#### MCP 治理门禁

- capability search 支持“QMT、实盘、订单、撤单、停止、对账”等中英文任务词；
- schema、正式 SDK 和 canonical serializer 字段完全一致，禁止 `additionalProperties` 漂移；
- 所有写能力首次调用只返回 preview 和确认 token，不产生状态变化；
- `agom_confirmation_resume` 时重新校验身份、权限、订单摘要、TTL 和状态；
- 同一 `idempotency_key` 重放不产生第二次批准、撤单、停止或差异处置；
- MCP 用户 Token 与 QMT Agent Token 完全隔离；
- catalog projection 保留 owner、risk、confirmation、idempotency 和 audit metadata；
- 运行 MCP write/read evidence、manifest schema、catalog dedup、tool budget 和 no-raw-tools 守卫；
- Terminal Agent 如使用这些能力，只通过 `search -> schema -> call -> confirmation_resume` 流程，不枚举或调用 legacy raw tools。

### 17.6 跨入口语义对齐

| 业务动作 | Classic Web/TUI | SDK | MCP | 唯一服务端 UseCase |
| --- | --- | --- | --- | --- |
| 查看交易就绪 | canonical GET | `broker_execution.overview()` | `broker_execution.read.overview` | `GetBrokerExecutionOverviewUseCase` |
| 批准订单 | preview/commit API | `preview/approve_order()` | `broker_execution.approve.order` | `ApproveLiveOrderUseCase` |
| 请求撤单 | preview/commit API | `preview/request_cancel()` | `broker_execution.request.cancel` | `RequestBrokerCancelUseCase` |
| 紧急停止 | preview/commit API | `preview/trigger_kill_switch()` | `broker_execution.trigger.kill_switch` | `TriggerTradingKillSwitchUseCase` |
| 恢复交易 | preview/commit API | `preview/resume_trading()` | `broker_execution.resume.trading` | `ResumeTradingUseCase` |
| 处置差异 | preview/commit API | `preview/resolve_reconciliation()` | `broker_execution.resolve.reconciliation` | `ResolveReconciliationUseCase` |

同一动作不得在 Web View、TUI result model、SDK 或 MCP handler 中复制业务规则。不同入口可以有不同展示 envelope，但必须共享订单状态、权限结果、确认摘要、错误码和审计 `request_id`。

## 18. 可执行工作包与完成门禁

### WP0：目标环境探针

状态：**外部验收进行中，尚未通过**。仓库已提供安装级 `--preflight` 和不报单/不撤单的 `--qmt-read-probe --evidence-file ...`；后者验证 QMT 连接以及资金、持仓、当日委托和当日成交查询，并生成不含券商账号及资金数值的 JSON 证据。2026-07-22 已在目标机完成客户端、Python 和 SDK 导入核验；登录后客户端日志明确拒绝启动 XtQuantServer，探针归一为 `QMT_SERVER_NOT_ALLOWED`。需由国金开通外部 XtQuant 权限或提供专用客户端后重试。仿真报撤单、回调与重连仍待现场验证。

- 输出 QMT/券商/Python 兼容性报告；
- 完成查询、报单、撤单、回调和重连最小实验；
- 决定 Agent 代码位置和依赖管理方式。

退出门禁：能够在仿真环境通过脚本唯一识别一次委托及其成交/撤单结果。

### WP1：ADR、领域模型和契约冻结

状态：**已完成（仓库范围）**。

- 新增 broker execution ADR；
- 冻结模块 owner、状态机、错误码、API schema、幂等规则、动作权限矩阵和 Agent scope；
- 建立 `apps/broker_execution` 四层骨架；
- 先写 Domain 状态机、Application 越权测试和 API 契约测试。

退出门禁：架构扫描通过，契约样例覆盖正常、拒单、超时和部分成交；所有写用例都有明确能力和账户授权要求。

### WP2：VPS 订单与审批闭环

状态：**已完成（仓库范围）**。

- 实现建单、风险快照、人工审批、租约、撤单命令和停止开关；
- 实现 Application 层动作授权、账户级授权、审批摘要哈希和审批失效；
- 实现 Agent 专用凭证、scope、轮换、撤销和请求防重放；
- 将权限拒绝、审批、启停和凭证操作写入审计日志；
- 接入自动投顾 `execution_plan`，但保持真实账户默认禁用；
- 提供管理员只读订单和审计查询入口。

退出门禁：使用 Fake Agent 可完成一笔订单从 `DRAFT` 到 `FILLED` 的全链路，重复请求不产生第二笔订单；跨账户、越角色、已撤销 Agent 和停止状态下的写入全部被拒绝。

### WP3：Fake Agent 和故障注入

状态：**已完成（仓库范围）**。Fake Adapter 支持成功、拒单、未知结果、断线、部分成交、全部成交和撤单；重放、租约、签名、账户隔离、交易时段、双重门禁和未知提交由自动测试覆盖。

- 提供可控的 Fake Broker/QMT Adapter；
- 模拟成功、拒单、部分成交、延迟、断线、重复回报和未知状态；
- 模拟过期凭证、撤销凭证、重放请求、错误账户绑定和权限服务不可用；
- 验证 Agent 重启恢复和 VPS 租约回收。

退出门禁：所有不确定提交均进入对账，不发生自动重复报单。

### WP4：QMT Agent 实现

状态：**代码已完成，外部退出门禁待验证**。真实 `xtquant` 查询、限价报单、撤单、官方 callback 唤醒 + 委托/成交权威轮询、SQLite 防重、本地 STOP、启动基线、运行中重连、滚动日志、暂停/恢复/全量同步命令和保守字段匹配均已实现；券商版本差异以 WP0 实测为准。

- 只在 `qmt_adapter.py` 接触 `xtquant`；
- 实现账户查询、下单、撤单、委托/成交查询和回调归一化；
- 实现本地状态持久化、日志、心跳、自动启动和停止开关；
- 提供 `dry_run` 和仿真模式。

退出门禁：目标 QMT 仿真账户可连续完成报单、部分/全部成交、撤单和重启恢复。

### WP5：对账、告警和运行证据

状态：**已完成（仓库范围）**。Agent 快照包含资金、持仓、当日委托和当日成交；服务端逐项生成 `order/fill/cash/position` 差异，批次和差异均持久化并幂等。P0 差异或未知提交会自动打开账户停止开关，告警转发 `task_monitor`，并生成账户交易日报和 personal operational-readiness 证据。Classic Web 已链接既有 CSV/XLSX 成交导入，MCP 已保留 `account.import.broker_trades` 结构化兜底。真实券商文件列映射仍由 WP0/WP7 现场样本验证，不影响仓库功能闭环。

- 实现盘中增量对账、日终全量对账和差异处置；
- 接入任务监控和 operational readiness；
- 增加 Agent 离线、QMT 断开、订单未知、持仓差异和停止开关告警；
- 保留 CSV/XLSX 手工成交同步兜底。

退出门禁：可生成订单、成交、资金和持仓四类对账报告，所有差异都有处置状态。

### WP6A：canonical SDK/API 与 Classic Web

状态：**已完成（仓库范围）**。

此工作包独立于执行内核提交，先冻结稳定 ViewModel 和 canonical API，再构建页面：

- 实现 broker execution 正式 SDK 模块；
- 实现 overview、订单、连接、对账和审计 strict read API；
- 实现批准、拒绝、撤单、停止、恢复、凭证和差异处置 preview/commit API；
- 构建 overview、orders/detail、reconciliation、connection、settings 和 audit 页面；
- 页面动作接入权限裁剪、二次确认、错误码和审计 `request_id`；
- 普通用户页面不展示 Token、内部 API、HTTP method 或 QMT 本地路径。

退出门禁：用户能通过 Classic Web 完成连接检查、逐单确认、执行跟踪、差异处置和紧急停止；strict GET 经证明无写入和外部调用。

### WP6B：TUI 收口

状态：**已完成（仓库范围）**。

- 发布 `broker-execution` 逻辑能力，并注入 `execution.accounts` 与 `execution.audit` 两个任务型主屏；
- 注入 action、dashboard P0 panel、result model 和权限可见性；
- 写 action 接入 preview/commit 和 confirmation；
- 同步 metadata schema、runtime injection、compiler/promotion 和测试；
- 验证普通用户文案不泄露实现细节。

退出门禁：TUI 中能完成与 Classic Web 等价的核心任务，schema validation、screen/action/result model、权限和确认测试通过。

### WP6C：MCP governed capability

状态：**已完成（仓库范围）**。

- 增加正式 SDK 后，再注册 broker execution read/write capability manifests；
- 增加 owner runtime handler、catalog projection 和中英文检索词；
- 写能力实现 preview-first、confirmation、idempotency 和 lifecycle audit；
- 明确冻结任意下单、Agent 心跳/拉单/回报等不应外放能力；
- 运行 MCP read/write evidence、schema、catalog、tool budget 和 no-raw-tools 门禁。

退出门禁：core-only MCP 模式下可查询实盘状态，并可在两阶段确认后批准、撤单、停止和处置差异；重复幂等键不产生第二次写入，且顶层 raw tool 数量不增加。

### WP7：分级启用

状态：**待外部执行**。代码默认 `dry_run: true`，不得因仓库测试通过而跳过仿真和小额实盘门禁。

- Shadow：只生成订单并与人工操作比对；
- Dry-run：Agent 拉单、校验和回传，不调用 QMT 下单；
- QMT 仿真：自动提交仿真订单；
- 小额实盘：人工逐单确认；
- 受限自动实盘：仅白名单标的、严格额度和交易时段。

建议门禁：至少 5 个连续交易日 QMT 仿真无重复单和未处置差异；小额实盘至少 3 个交易日逐单确认无严重差异；自动实盘前再完成一次独立验收。实际天数可在批准时提高，不应降低到单次联调。

## 19. 测试矩阵

| 层级 | 必测场景 |
| --- | --- |
| Domain | 合法/非法状态转换、过期、Decimal、幂等键、交易单位 |
| Application | 风控拒绝、人工确认、租约并发、停止开关、撤单编排 |
| API 契约 | 鉴权、Content-Type、版本、重复请求、乱序/重复事件 |
| 权限 | 角色矩阵、账户越权、Agent scope、凭证撤销、审批失效、停止/恢复 |
| Classic Web | 页面路由、P0 首屏、空态、权限裁剪、preview/commit、模板渲染和用户主任务 |
| 浏览器验收 | 真实 Chromium 登录、七个 Classic Web 页面、管理员控制项、审计 CSV 下载、控制台错误和 page error |
| TUI | schema、screen、default action、P0 panel、result model、确认、权限和普通用户文案 |
| MCP read | strict GET、SDK/schema 对齐、core-only fallback、catalog replacement、零副作用 |
| MCP write | preview-first、confirmation resume、idempotent replay、权限、摘要失效和 lifecycle audit |
| Agent | QMT 未启动、账户错误、断线、重启、本地状态损坏、STOP 文件 |
| Broker Adapter | 查询、下单、撤单、部分成交、拒单、回调与主动查询一致性 |
| 对账 | 漏回报、重复成交、券商手工交易、资金/持仓差异 |
| 安全 | 失效 Token、重放请求、时钟偏差、日志脱敏、越权账户 |
| 回归 | 模拟盘、自动投顾、risk center、SDK、TUI/Terminal（如改动） |

涉及 `terminal/tui/sdk/deploy` 时，按项目规则补齐对应最小回归包。新增 broker execution 测试建议至少包括：

```text
pytest tests/unit/broker_execution -q
pytest tests/integration/broker_execution -q
pytest tests/playwright/tests/smoke/test_broker_execution.py --browser chromium -q
pytest tests/unit/test_terminal_agent_service.py -q       # 仅涉及 Terminal 时
pytest tests/unit/test_tui_workbench.py -q
pytest sdk/tests/test_sdk/test_client.py -q
pytest sdk/tests/test_sdk/test_broker_execution.py -q
pytest sdk/tests/test_mcp/test_core_registry_owner_broker_execution.py -q
pytest tests/unit/test_ai_capability/test_mcp_broker_execution_catalog.py -q
python scripts/check_mcp_manifest_schema.py
python scripts/check_mcp_read_evidence.py
python scripts/check_mcp_write_evidence.py
python scripts/check_mcp_write_preview.py
python scripts/check_mcp_write_confirmation.py
python scripts/check_mcp_write_audit.py
python scripts/check_mcp_catalog_dedup.py
python scripts/check_mcp_tool_budget.py
python scripts/check_mcp_no_raw_tools.py
python scripts/check_mcp_tui_action_coverage.py
python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles --format text
pytest tests/unit/test_internal_ssl_redirect.py -q        # 涉及 VPS/代理配置时
```

## 20. 可观测性和告警

关键指标：

- Agent 最后心跳时间、QMT 连接状态和版本；
- `READY/LEASED/SUBMITTING/RECONCILIATION_REQUIRED` 订单数量；
- 订单提交延迟、回报延迟和成交回传延迟；
- 重复事件数量和幂等命中数量；
- 当日拒单率、撤单率和对账差异数；
- VPS 与券商资金、持仓、委托和成交差异；
- 实盘开关和停止开关状态。

P0 告警：疑似重复下单、账户映射错误、未知提交状态、停止开关失效。P0 出现后自动冻结新订单，只允许查询、撤单和对账。

## 21. 分支和提交切分

按仓库规则使用 `dev/*` 分支，并至少拆分为以下提交组：

1. `docs`: ADR、协议、状态机和验收清单；
2. `feat`: broker execution Domain/Application/Infrastructure；
3. `test`: Fake Agent、契约和故障注入；
4. `feat`: Windows QMT Agent；
5. `feat`: 对账、告警和 readiness；
6. `feat`: canonical SDK/API 和 Classic Web；
7. `feat`: TUI metadata、result model 和测试；
8. `feat`: MCP governed capability、handler 和治理证据；
9. `docs`: 运维、回滚和验收证据。

不得把执行内核、VPS 部署修复、TUI 大改和治理文档重写放在同一个提交中。

## 22. 最终交付物

- broker execution ADR；
- 用户角色/动作权限矩阵、Agent scope 和权限回归证据；
- VPS-Agent DRF 运行时契约与版本化 JSON Schema 文档投影；
- `apps/broker_execution` 四层模块；
- 本地 QMT Agent 和 Fake Agent；
- Classic Web overview、订单、连接、对账、设置和审计页面；
- broker execution 正式 SDK 与 canonical API；
- TUI `broker-execution` 模块、screen、action、result model 和 metadata 证据；
- MCP broker execution governed capability、runtime handler、catalog projection 和治理证据；
- Windows 安装、启动、升级和卸载说明；
- 风控配置、人工确认和紧急停止说明；
- 盘中/日终对账与故障处置手册；
- 单元、契约、集成、仿真和小额实盘验收证据；
- 生产启用清单和回滚记录模板。

## 23. 待批准决策

- [x] 目标券商及客户端已确定为国金证券 QMT 交易端 `2.1.19.0`；当前不是 MiniQMT，且券商尚未允许启动 XtQuantServer；
- [x] 首版仅支持普通股票账户（`STOCK`）；信用账户在融资融券委托语义完成专门适配和验收前拒绝绑定；
- [x] 首版交易品种由账户白名单约束，默认按 A 股和场内 ETF 的 100 股买入单位校验；
- [x] 首版禁用市价单，只允许正数量、正价格的限价单；
- [x] Agent 首版放在本仓库独立 `qmt_agent/` 制品，`xtquant` 不进入 VPS 依赖；
- [x] Agent 首版采用可轮换/撤销的 scoped Token + HMAC 请求签名 + 时间窗 + nonce 防重放；
- [ ] 是否要求额外 MFA，以及除恢复交易（已固定要求当前登录密码重认证）外哪些高风险动作必须重新认证；
- [ ] 哪些金额和配置变更必须双人复核；
- [x] 个人单用户模式允许 `owner` 审批本人已授权账户订单；恢复交易、绑定、限额和凭证管理仍仅限管理员；
- [ ] 小额实盘的单笔、单日和总资金上限；
- [x] 首版只启用人工逐单确认；自动投顾只能创建经过服务端风控的草稿，Agent 只执行已人工批准且提交前复核仍通过的订单，不提供自动批准实盘订单能力；
- [x] Classic Web 已交付 overview、订单列表/详情、对账、连接、设置和审计七个路由；管理写操作仅管理员可用；
- [x] MCP 首版只允许批准、拒绝、撤单请求、停止/恢复和差异处置；冻结“任意创建订单”和“直接 QMT 下单”；
- [x] Terminal/TUI 通过 governed catalog 发现 broker execution 能力，不暴露 Agent 机器接口；
- [x] TUI 不创建或轮换 Agent 凭证，凭证治理仅在管理员 Classic Web 提供；
- [x] QMT 行情继续由既有 `data_center` 接入作为服务端风控真源；Agent 可读取本地 QMT 行情做提交前防御性复核，但不把它升级为新的行情转发真源；
- [x] 最低连续验收门槛固定为 QMT 仿真 5 个交易日、小额实盘 3 个交易日；正式批准可以提高，不得降低为单次联调。

在剩余关键决策、WP0 探针和 WP7 验收完成前，不启用真实账户自动下单。

## 24. 仓库实现与验证证据（2026-07-22）

### 24.1 已交付

- `apps/broker_execution/` 四层模块、初始/增强迁移、Admin、Celery 维护/四维对账任务；
- 动作级 RBAC、显式账户授权、服务端二次鉴权、权限拒绝审计、管理员管理面；恢复交易在 Web、TUI、SDK 和 MCP commit 均强制当前登录密码重认证；
- scoped Agent 凭证、凭证级允许账户 ID、SHA-256 仅存摘要、HMAC、时间偏差、nonce 防重放、租约和幂等；同一 Agent 下未授权账户的心跳、拉单、回报、快照和命令均默认拒绝；
- 用户登录失败和 Agent 认证失败进入只追加审计，记录受限的用户名/凭据标识、Agent、请求 ID、失败码、来源 IP/User-Agent，不记录密码、Token、签名或 secret；
- 本地 `qmt_agent/`、真实 `XtQuantAdapter`、故障注入 Fake Adapter、SQLite 提交状态、本地 STOP、启动/重连/全量同步和 Windows 安装/启动/卸载脚本；
- 安装级 `--preflight` 与只读 `--qmt-read-probe`；真实探针强制记录 QMT/`xtquant` 版本，查询连接、资金接口、持仓、当日委托和成交，生成不含券商账户号及资金值的 JSON 证据，且不会报单或撤单；
- Classic Web 七个路由、统一 `status/summary/data/warnings/next_actions/permissions` ViewModel、strict persisted-only API、preview/commit 高风险动作；连接页支持异步测试/全量同步、凭证立即撤销和解绑，审计页支持权限内筛选与 CSV 导出；
- 设置页提供管理员专用账户授权管理；授权/撤销必须 preview/commit、原因、幂等键和审计，Django Admin 中的订单、绑定、授权、停止开关和执行事实统一只读，禁止绕过正式用例静默修改；
- 独立 `core.settings.playwright` 浏览器验收配置，使受管 Django 服务和 pytest 仅共享显式指定的一次性 SQLite 文件，不读写开发或生产数据库；
- canonical SDK、TUI 两个 canonical 主屏注入、MCP 6 个只读和 6 个受控写 capability；
- 自动投顾 `execution_plan` 到待审批实盘草稿的内部桥接；创建前重新读取统一 active real account 并调用 `risk_center`，调用方风险快照不被信任；
- 订单批准摘要绑定来源建议/信号；批准、拒绝和撤单 commit 必须携带 preview 返回的 `expected_version`，防止确认作用于已变化订单；
- `SUBMITTING` 前原子复核最新停止开关、绑定、交易时段、有效期、白名单、单笔/单日额度、快照、资金/可卖数量、持仓数和审批摘要；
- QMT 撤单接口成功仅保持 `CANCEL_PENDING`，最终 `CANCELED` 只接受券商状态事实；超额成交和未来快照分别触发自动停止/拒绝；
- Agent 事件幂等按 `(agent_id, event_id)`，QMT remark 使用不超过 24 字节的可逆 UUID 编码；首版仅接受 `STOCK`；
- 委托/成交/资金/持仓四维差异、P0 自动停止、`task_monitor` 告警、实盘日报、readiness 和手工导入兜底；
- ADR、Windows 安装/运行/停止/恢复/升级/卸载手册、正式启用清单、回滚模板和本文档索引。
- Agent v1 请求 JSON Schema 文档投影（运行时仍以 DRF Serializer 为唯一真源）。

### 24.2 已通过自动验证

- `ruff check`：broker execution、QMT Agent 及对应测试通过；
- `python manage.py check`：0 issue；`makemigrations --check --dry-run`：无迁移漂移；
- 架构 full guard：1783 个文件、0 个边界违规、0 个审计违规；模块依赖审计 40 个 App、198 条边、0 个双向依赖、0 个循环，`broker_execution` 预算已登记为治理基线 v14；
- broker execution 单元完整组：64 个测试通过；集成 Fake Agent 全链路：1 个测试通过，合计 65 个。覆盖服务端权威风控、自动投顾桥、账户绑定、账户授权 preview/commit/越权/Django Admin 防旁路、资源版本、交易时段、凭证账户 scope、登录/Agent 认证失败审计、恢复交易密码重认证及来源 IP、Agent 契约与安装/只读 QMT 探针、本地预检、QMT 服务端权限拒绝诊断、四维对账、撤单最终态、超额成交/P0 自动停机、幂等和权限；
- 真实 Chromium Classic Web smoke：1 个浏览器场景通过，顺序验证七个页面、管理员执行门禁/凭证/账户授权控制项、审计 CSV 下载，并断言 JavaScript console error 与 page error 均为零；
- readiness + 自动投顾相关聚焦组：221 个测试通过；
- TUI workbench 194 个测试 + broker metadata 2 个测试，共 196 个测试通过；MCP TUI action coverage 为 506 个唯一 action、0 缺口；
- 本轮 Terminal/SDK/SSL/broker SDK 聚焦组：38 个测试通过；broker MCP/catalog 聚焦组：7 个测试通过；此前完整 broker SDK/MCP/catalog/manifest 聚焦组 16 个测试通过；
- MCP schema、read/write evidence、preview、confirmation、audit、catalog dedup、tool budget、no-raw-tools、TUI action coverage 全部通过。

### 24.3 未由仓库环境验证

- 国金侧外部 XtQuantServer、函数查询和函数下单权限；当前真实只读探针已稳定归一为 `QMT_SERVER_NOT_ALLOWED`；
- 目标账户类型、市场范围、仿真账户能力及券商侧频率/品种限制；
- 真实 QMT 的字段/状态常量差异、回调时序、断线重连、部分成交和撤单结果；
- 连续 5 个交易日仿真、连续 3 个交易日小额实盘及真实券商四类事实对账；
- MFA、双人复核（如生产审批要求）和目标券商 CSV/XLSX 列映射样本。
