# AgomTradePro 系统级统一审计日志收口计划

> 状态：**M0 机器合同与 M1 Domain/codec/schema-only/repository/query/outbox-claim 合同已落盘；业务双写及 M2+ 待评审实施**
> 创建日期：2026-08-13
> 优先级：P0（数据可靠性纵向链路）+ P1（其余系统审计面）
> 建议 Owner：`audit`（统一事件账本）/ 各业务 App（事件语义）/ `task_monitor`（聚合告警）
> 范围声明：本计划只定义收口架构、迁移批次和验收门禁；当前文档批次不修改运行代码、数据库或生产配置。

## 1. 执行摘要

AgomTradePro 已有结构化运行日志、MCP/SDK 操作审计、Data Center Raw Audit、Provider Health、Canonical Publication、Coverage、Rollback、Task Monitor 告警和 Prometheus 基础指标，但这些能力分属不同链路，尚不能稳定回答以下系统级问题：

- 一次数据抓取、校验、failover、入库、发布和决策阻断是否属于同一条链；
- 某次 `stale / missing / conflict / failed` 从何时开始、因何发生、何时恢复；
- 某个 Provider 健康状态变化是否影响了 Publication 或最终决策读取；
- 某次 MCP、SDK、API、Celery 或人工操作是否触发了数据或决策状态变化；
- 审计事件是否持久、不可变、可校验、可按稳定 reason code 检索，并能统一驱动指标与告警。

本计划采用“**统一事件账本 + 专业证据表保留**”的收口方式：

1. `apps/audit` 建立系统级 append-only `SystemAuditEvent` 账本，负责统一事件身份、时钟、关联键、内容哈希、不可变存储和查询。
2. 各业务 App 继续拥有事件语义和专业证据；`data_center` 继续拥有 freshness、quality、provider、publication 和 decision-safety 判断。
3. `RawAudit`、Canonical Publication、Coverage、Rollback、OperationLog 等现有表不被泛化 JSON 替代；统一事件只保存必要摘要和 exact evidence reference。
4. 数据可靠性作为第一个完整纵向试点，先贯通 fetch → validate → failover → persist → publish → read gate → repair。
5. Prometheus、Task Monitor 和 TUI 从统一 Application Query/Projection 读取，不各自重新推导业务结论。

## 2. 当前基线与主要缺口

### 2.1 已有能力

| 能力 | 当前真源 | 可继续复用的部分 |
|------|----------|------------------|
| Django/Celery 运行日志 | `core/settings/production.py`、`core/logging_utils.py` | JSON formatter、trace/request context、滚动文件、Sentry 接入 |
| 管理员实时日志 | `core/log_buffer.py`、`core/admin_log_views.py` | 受限实时排障与导出 |
| MCP/SDK 操作审计 | `apps/audit/infrastructure/models.py::OperationLogModel` | 操作者、来源、工具、资源、响应状态、耗时、checksum |
| 数据抓取审计 | `apps/data_center/infrastructure/fact_and_operational_models.py::RawAuditModel` | Provider/capability、请求哈希、结果行数、耗时、错误、抓取时间 |
| 可靠性契约 | `shared/domain/reliability.py` | `fresh/stale/missing/partial/conflict/maintenance/failed` 与 fail-closed 语义 |
| Provider 健康 | `apps/data_center/application/provider_health*.py` | 最近成功、连续失败、平均延迟、熔断状态 |
| Canonical 发布证据 | `apps/data_center/infrastructure/publication_rollback_models.py` | Publication、成员、覆盖率、冲突、回滚及决策阻断标志 |
| 任务与运营告警 | `apps/task_monitor` | 聚合、展示和通知 |
| Prometheus | `core/metrics.py`、`/metrics/` | API、Celery、数据库、审计写入基础指标 |

### 2.2 需要收口的问题

1. 管理员服务器日志是进程内环形缓冲，重启丢失，多进程不共享，不能作为持久审计真源。
2. 结构化 formatter 解决了输出格式，但大量业务日志仍是自由文本，缺少稳定 `event_type / reason_code / dataset_key / evidence_ref`。
3. Provider Health 主要保存可变聚合状态，不能完整重放健康状态转换历史。
4. `trace_id`、`request_id`、`task_id`、`run_id`、`ingested_run_id`、`publication_id` 已分别存在，但未形成强制、统一的关联合同。
5. Raw Audit、事实行、Publication 和 Decision Gate 之间存在字段基础，但常规路径并未保证 exact ID 全链贯通。
6. Data Center 的 freshness、coverage、conflict、failover 和 publication blocker 尚未完整进入统一 `/metrics/`。
7. Task Monitor 能记录运营告警，但不应自行重算 Data Center 的业务可靠性结论。
8. 当前没有统一的事件注册表和 CI 守卫，新增关键写入、数据可靠性变化或决策阻断可能只留下普通日志。

## 3. 目标与非目标

### 3.1 目标

- 建立系统级、append-only、可校验、可关联、可检索的审计事件账本。
- 为关键事件建立稳定 taxonomy、reason code、typed detail contract 和 owner。
- 首先闭环数据可靠性事件，完整保留源观测时间，不用请求时间洗白历史数据。
- 让运行日志、专业证据、统一事件、指标和告警各自只有一个明确职责。
- 支持按 trace、请求、任务、运行批次、Provider、dataset、Publication、资源和 actor 重放事件链。
- 将关键审计写入纳入 fail-closed 或受控 outbox 策略，禁止静默丢失。
- 提供 staff-only Application Query、SDK 管理读取能力和 TUI 系统观测入口。
- 用机器注册表和 CI 守卫冻结关键审计面，防止后续重新散落。

### 3.2 非目标

- 不用统一事件表替代 RawAudit、Canonical Publication、Evidence Envelope、订单审批或其他领域证据表。
- 不把全部 `logger.info/debug` 转存数据库，也不把运行日志当业务审计证据。
- 不在事件 payload 中保存 Provider 原始响应、行情全量数据、Token、credential、Cookie、完整 prompt 或未脱敏异常内容。
- 本计划不直接引入 ELK、Loki、OpenTelemetry Collector 等外部平台；外部 sink 作为后续可插拔出口。
- 不新增 Classic Django 主任务页面；新用户面只进入 TUI。
- 不因审计链落地而解除任何 Evidence、Portfolio、Risk 或 Broker 执行硬闸。

## 4. 术语与真源边界

| 名称 | 职责 | 是否业务真源 |
|------|------|--------------|
| Runtime Log | 人工排障、异常堆栈、进程状态 | 否 |
| System Audit Event | 记录“谁在何时对什么做了什么、结果和关联证据是什么” | 是，负责事件发生与关联身份 |
| Domain Evidence | 保存领域完整事实，如 RawAudit、Publication、Approval、Envelope | 是，负责专业内容 |
| Metric | 低基数聚合趋势和 SLO | 否，可由事件/状态投影生成 |
| Alert | 对已判定异常的通知和处置状态 | 否，不拥有业务判断 |

统一事件与专业证据不得复制成两个可独立修改的真源：事件保存 exact reference、必要摘要和 hash；完整领域内容仍从 owner 的专业 ledger 重读。

## 5. 目标架构与 Owner 边界

```mermaid
flowchart LR
    A["API / SDK / MCP / Celery / CLI"] --> B["业务 Application Use Case"]
    B --> C["业务 Domain 判断"]
    C --> D["专业证据 Ledger"]
    B --> E["Audit Application Port"]
    D --> E
    E --> F["SystemAuditEvent append-only ledger"]
    F --> G["Audit Query / Projection"]
    G --> H["TUI 系统观测"]
    G --> I["Prometheus bounded metrics"]
    G --> J["Task Monitor 聚合告警"]
    F --> K["Archive / optional external sink"]
```

### 5.1 `apps/audit`

- Domain：事件 envelope、事件分类、结果、严重度、actor/source/resource reference、内容哈希和不可变规则。
- Application：append/query/export use case、幂等、写入策略、outbox 恢复、访问控制 DTO。
- Infrastructure：PostgreSQL/SQLite repository、append-only guard、archive adapter、Prometheus projection adapter。
- Interface：staff-only REST 读取；写入入口不对普通 HTTP 调用者开放。
- 禁止反向 import `data_center`、`portfolio`、`broker_execution` 等业务 infrastructure。

### 5.2 各业务 App

- 拥有何时产生事件、业务状态和 reason code 的判断。
- 通过 Audit Application Port 提交 typed event，不直接写 Audit ORM。
- 事件 payload 在进入 Audit 前完成脱敏和类型收窄。
- 关键领域 evidence 必须先成功持久化，再提交包含 exact reference/hash 的事件。

### 5.3 `data_center`

- 继续作为 freshness、quality、provider health、failover、coverage、publication 和 `must_not_use_for_decision` 的唯一业务 owner。
- 统一审计层只记录 Data Center 已作出的结论，不在 Audit 或 Task Monitor 中重算 freshness。

### 5.4 `task_monitor`

- 只负责聚合、去重、升级、确认、通知和恢复展示。
- 不拥有 `stale / conflict / publication blocked` 的业务判断。

### 5.5 `shared/` 与 `core/`

- `shared/` 最多承载纯技术性的 sink Protocol、JSON/clock/hash 工具，不放 Django Model、业务 taxonomy 或默认策略。
- `core/integration` 负责 composition 和跨 App adapter，不把业务规则搬入 composition root。

## 6. Canonical System Audit Event 合同

### 6.1 必需字段

| 字段组 | 必需字段 | 规则 |
|--------|----------|------|
| 身份 | `event_id`、`event_version`、`schema_version` | UUID/稳定版本；禁止就地改版 |
| 分类 | `category`、`event_type`、`owner` | 必须登记在机器注册表；未知类型拒绝写入 |
| 结果 | `outcome`、`severity`、`reason_codes` | 使用稳定枚举/代码，不以自由文本作为唯一依据 |
| 时钟 | `occurred_at`、`recorded_at`、可选 `observed_at/fetched_at` | 全部 timezone-aware；保留源时间，`recorded_at` 取服务端权威时钟 |
| 操作者 | `actor_type`、`actor_id`、`actor_display` | 系统、用户、任务、Agent 明确区分；展示字段脱敏 |
| 来源 | `source_app`、`source_component`、`source_surface` | 标识 Application Use Case 和入口，不保存敏感 URL 参数 |
| 关联 | `trace_id`、`request_id`、`task_id`、`run_id`、`ingested_run_id` | 可空但必须经过格式校验；适用路径必须填写 |
| 资源 | `resource_type`、`resource_id`、`resource_version` | 指向业务资源；不得仅靠文本 message 识别 |
| 数据 | 可选 `dataset_key`、`provider_key`、`capability`、`publication_id` | 数据可靠性事件按适用范围强制填写 |
| 证据 | `evidence_refs` | owner/type/id/version/hash 的有序 typed reference |
| 内容 | `detail_contract`、`detail`、`content_hash` | detail 使用登记的 closed schema；`Any` 只能停留在 codec 边界 |
| 链 | `stream_id`、`sequence_no`、`predecessor_hash` | 同一 logical stream 可重放并检测 fork/tamper |
| 幂等 | `idempotency_key` | 重试只能返回同一事件，不得生成重复流水 |

### 6.2 写入策略

事件注册表为每类事件声明：

- `write_policy=required`：审计追加失败则业务 mutation 失败关闭；适用于审批、发布、回滚、决策授权、执行、权限和关键配置变化。
- `write_policy=transactional_outbox`：业务事实与 outbox 同事务提交，由受监控 dispatcher 追加统一事件；适用于高频数据同步和批任务。
- `write_policy=best_effort`：只允许非关键诊断事件，失败必须形成 bounded metric，不得用于满足审计验收。

业务调用者不能自行把 required 事件降级为 best-effort。

### 6.3 内容与隐私

- 事件只允许登记后的 typed detail；禁止任意深度、任意 key 的 JSON dump。
- 密钥、凭证、授权头、Cookie、连接串用户密码、原始订单/审批 payload、完整异常消息必须在 owner 边界删除或变成稳定分类。
- 大内容只保存 hash、大小、schema fingerprint 和专业 evidence reference。
- `actor_display`、资源名称和错误摘要设置长度上限；导出再次执行字段白名单。

## 7. 事件分类与数据可靠性首批范围

### 7.1 顶层分类

- `system.operation`：关键 API/SDK/MCP/CLI/Celery 操作结果。
- `system.security`：认证、授权、Token 生命周期、访问拒绝和敏感配置变化。
- `system.configuration`：Config Center、Provider、策略参数和运行时 desired state 变化。
- `system.task`：关键批任务业务 outcome、重试、超时和恢复。
- `data.reliability`：抓取、校验、质量、新鲜度、冲突、failover、Provider、Publication 和读取阻断。
- `decision.governance`：Evidence、Promotion、决策硬闸和人工审批状态变化。
- `execution.control`：订单意图、Risk 授权、Broker 提交/拒绝/停止和对账状态变化。

M0 必须先完成全量 inventory；未登记事件不能被宣称已纳入统一审计。

### 7.2 Data Reliability 首批事件

| 事件类型 | 触发条件 | 必需关联 |
|----------|----------|----------|
| `data.fetch.completed` | Provider 抓取并产生有效输出 | provider、capability、dataset、RawAudit ref、run/ingested_run |
| `data.fetch.noop` | 请求完成但零产出/零写入 | 同上 + 稳定原因 |
| `data.fetch.failed` | 超时、异常或所有 Provider 失败 | 同上 + error class/reason code |
| `data.validation.rejected` | schema、单位、范围、PIT、数值或质量校验失败 | dataset、validator、source evidence |
| `data.quality.changed` | 事实质量状态发生转换 | fact/publication ref、old/new status |
| `data.freshness.changed` | fresh/stale/missing 等状态发生转换 | dataset scope、source times、threshold contract |
| `data.conflict.detected` | 多源或版本冲突达到治理条件 | sources、tolerance/policy version |
| `data.conflict.resolved` | 冲突经 canonical 规则或人工流程解除 | conflict ref、resolution evidence |
| `data.failover.started` | 主源不可用/过期后开始尝试后备源 | ordered provider refs、原因 |
| `data.failover.succeeded` | 后备源通过一致性和 freshness 校验 | from/to provider、validation evidence |
| `data.failover.rejected` | 后备源存在但校验不通过 | provider、stable reason |
| `data.failover.exhausted` | 所有候选均失败/过期/不合格 | attempted provider refs |
| `data.provider.circuit_opened` | 连续失败达到治理阈值 | provider、capability、threshold policy |
| `data.provider.recovered` | 熔断后重新成功且输出有效 | provider、capability、success evidence |
| `data.publication.published` | Canonical Publication 成功发布 | publication、coverage、member/hash refs |
| `data.publication.blocked` | coverage/conflict/freshness/policy 阻断发布 | candidate/coverage refs、reason codes |
| `data.publication.rolled_back` | 显式回滚成功 | target/previous publication、operator evidence |
| `data.decision_read.blocked` | current/latest 决策读取失败关闭 | dataset/publication、reliability contract |
| `data.decision_read.recovered` | 同 scope 从 blocked 转回可用 | previous event、fresh publication evidence |
| `data.repair.completed` | 可靠性修复流程结束 | repair run、各 section outcome、remaining blockers |

高频读取不得为每次相同 blocked 结果生成无界事件；按 `stream_id + state` 只记录首次转换、恢复和受治理的周期摘要。

### 7.3 Reason code 治理

- 直接复用 `governance/reliability_contracts.json` 已登记的稳定状态和原因。
- 新增 `governance/audit_event_contracts.json`，登记事件类型、owner、detail schema、write policy、严重度边界、必需关联字段和测试证据。
- 新增 reason code 必须声明 owner、触发条件、恢复条件和用户可见文案 key。
- 动态错误消息不能作为 reason code；异常只允许发布类名或受控分类。

## 8. 持久化、不变性与关联完整性

### 8.1 建议模型

- `SystemAuditEventModel`：统一不可变事件头、低基数索引字段、typed detail JSON、content hash。
- `SystemAuditOutboxModel`：同事务待投递事件；只允许状态机式 claim/dispatch，不允许修改已封存 payload。
- `SystemAuditExportRunModel`：受控导出申请、范围、操作者、结果 hash 和保留期。

### 8.2 Append-only 约束

- 公共 repository 只暴露 `append / get_exact / list_by_*`，不暴露 update/delete。
- instance、QuerySet、manager、bulk、conflict-update 和 raw mutation shortcut 均加守卫。
- 数据库约束覆盖非空身份、aware 时钟可表达范围、序号、幂等键和 hash 格式。
- PostgreSQL 验收必须包含并发 first-winner、同 stream predecessor CAS、重复幂等和 fork 阻断。
- 生产角色权限禁止 UPDATE/DELETE 已封存事件；清理只能走受治理 archive/retention 流程并留下 export/retention receipt。
- SQLite 仅用于本地开发和合同测试，不作为并发不可变性的最终证据。

### 8.3 关联规则

- HTTP：Middleware 生成/接收合法 trace/request ID；Application 事件继承同一上下文。
- Celery：任务 envelope 显式传递 trace/request/root task ID，禁止只依赖线程本地变量。
- 数据同步：每次 batch 先生成 `run_id/ingested_run_id`，RawAudit、事实行、Publication 和统一事件使用同一批次身份。
- Publication：事件必须引用 exact publication hash、coverage 和 member count，不以“发布成功”文本代替。
- MCP/SDK：保留 OperationLog 的 request ID，并将稳定 operation identity 关联到统一事件。

## 9. 现有能力的迁移策略

### 9.1 Runtime Log

- 继续输出 stdout/JSON、Celery 滚动文件和可选 Sentry。
- 只有登记为 audit-worthy 的状态变化才同时产生 System Audit Event。
- 禁止通过离线解析自由文本日志补造 canonical 审计事件。
- 管理员实时服务器日志保留为兼容排障入口，但明确标注“进程内、非持久审计”。

### 9.2 `OperationLogModel`

- 第一阶段保留现表，新增 adapter 将受治理的 operation metadata 发到统一账本。
- 不复制任意 `response_payload/response_text/traceback`；统一事件只保存白名单摘要、checksum 和 OperationLog exact ref。
- 完成观察窗口后，再决定 OperationLog 是保留为专业详情表还是收缩为兼容投影；不得提前删除历史证据。

### 9.3 `RawAuditModel`

- 继续作为每次数据抓取尝试的专业真源。
- 新增稳定 audit row identity 返回值，并贯通 `ingested_run_id`。
- 统一事件引用 RawAudit ID/hash，不复制请求参数或错误全文。
- `noop`、失败和恢复必须与 Provider Health、Publication 事件共享 run/dataset/capability 关联。

### 9.4 Provider Health 与 Circuit Breaker

- 可变聚合状态继续服务当前查询。
- 仅在健康状态转换、熔断开启、恢复和阈值策略变化时写不可变事件。
- 聚合状态可从事件和当前配置复核，但事件写入路径不得依赖管理员页面访问。

### 9.5 Publication/Coverage/Rollback

- 专业表继续为发布真源。
- candidate、blocked、published、superseded、reinstated 和 rollback 产生 content-bound 事件。
- Publication mutation 与 required 审计事件必须在同一受控 Unit of Work，避免“已发布但无审计”。

## 10. 指标、告警与用户入口

### 10.1 Prometheus 指标

统一使用 `prometheus_client` 并进入现有 `/metrics/`，不再建立与核心端点断开的第二套内存 Prometheus 文本：

- `system_audit_events_total{category,event_family,outcome,severity}`
- `system_audit_write_failures_total{owner,event_family,write_policy}`
- `system_audit_outbox_pending{owner}`
- `system_audit_outbox_oldest_age_seconds{owner}`
- `data_reliability_events_total{dataset_key,event_family,outcome}`
- `data_reliability_blocked{dataset_key,reason_family}`
- `data_provider_health_status{provider_key,capability}`
- `data_publication_blocked_total{dataset_key,reason_code}`
- `data_publication_coverage_ratio{dataset_key}`

禁止把 asset code、用户 ID、request ID、run ID、publication ID 或原始错误消息放入 Prometheus label。所有 label 值来自 bounded registry。

### 10.2 Task Monitor 告警

- Audit/Application projection 根据 Data Center 已发布的事件和状态产生告警候选。
- Task Monitor 负责去重、持续时间、升级、通知、确认和恢复记录。
- 告警阈值、持续窗口和路由进入 Config Center/治理合同，不散落硬编码。
- 审计写入失败、outbox 积压、事件链 fork/tamper、长期 stale、failover exhausted、Publication blocked 是首批 P0 告警。

### 10.3 TUI 系统观测入口

遵守 Web → TUI 冻结规则，新建或扩展 TUI 管理员 screen，不新增 Classic 业务模板：

- `primary_task`：定位一次系统操作或数据可靠性异常的完整事件链。
- `primary_outcome`：明确当前状态、阻断原因、影响范围、证据引用和恢复进度。
- P0 panel：当前 critical/blocked、审计写入健康、outbox 积压、Provider/Publication 异常。
- 专门视图：trace/run/publication 事件时间线、data reliability 状态转换、actor/resource 操作历史。
- 默认 action：查看事件详情或复制事件/trace/run ID；不得默认执行修复或 mutation。
- 事件详情只展示白名单字段；秘密、原始 payload 和内部任意 JSON 不进入 TUI metadata。

## 11. 分阶段实施计划

### M0：Inventory、ADR 与机器合同

交付：

- 盘点现有 runtime logger、OperationLog、RawAudit、Provider Health、Publication、业务日志表、Task Alert 和审计指标。
- 按 owner/category/event_type/write policy 标记所有 P0/P1 审计面。
- 新增 ADR，确认统一账本 owner、专业证据边界、跨 App 依赖方向和失败策略。
- 新增 `governance/audit_event_contracts.json` 与 `scripts/check_audit_event_contracts.py`。
- CI 差异扫描关键 mutation、`@shared_task`、current/latest read gate 和 provider/publication 状态变化；新增未登记面失败。

退出条件：P0 分母被机器冻结；未知 owner、symbol、event type、detail contract 或测试引用均由守卫拒绝。

### 2026-08-14：M0 事件注册表与 CI 守卫（shadow）

- 新增 `governance/audit_event_contracts.json`，冻结 7 个顶层 category 的 M0 分母：首批 20 个 Data Reliability 事件具备 owner、write policy、severity、outcome、required correlations、detail schema、reason code 与测试引用；其余 6 类以 source-file inventory 标记 `inventory_only/pending`。所有事件条目明确为 `planned/not_wired`，不冒充运行覆盖。
- 新增 `scripts/check_audit_event_contracts.py` 与 `tests/unit/test_audit_event_contracts.py`，守卫重复/未知 event type、非法 reason/detail schema、未登记关联字段、缺失测试文件，以及 `active`/`wired` 状态不一致；已接入 `.github/workflows/consistency-check.yml` 与治理 wiring 自检；定向测试 `4 passed`、治理 wiring `29 passed`，命令在当前 shadow registry 下稳定返回 `OK`。
- 该批只完成机器合同与静态 inventory，不创建 Event Model、migration、outbox、运行写入口或生产配置；Data Reliability 事件仍未接入统一账本，M1 继续待评审。

### 2026-08-14：M1 Audit Domain/codec 最小合同

- 新增纯标准库 `SystemAuditEvent` envelope：固定 category/outcome/severity/write policy，typed actor/resource/evidence refs，bounded correlations，source observation/recorded clocks，stream sequence/predecessor 与 idempotency key。
- 新增 strict canonical codec：完整 key set、UTC-Z 微秒时间、bool/int 分离、敏感 detail key 拒绝、domain-separated identity/content SHA-256、篡改与非 canonical payload fail closed；`tests/unit/audit/test_system_audit_event.py` `5 passed`，增量 mypy `0 regressions`，architecture `2883 files / 0 violations`。
- 本批不创建 Django Model/migration/repository/outbox，不读取 registry 外部文件，也不接任何运行写入口；因此只证明 Domain/codec 合同，不代表统一事件账本已启用或 Data Center 已双写。

### 2026-08-14：M1 schema-only ledger/outbox 基座

- 新增 `apps/audit/infrastructure/system_audit_models.py` 与 `system_audit_outbox_models.py`：统一事件表和事务 outbox 表均为 zero-seed、append-only/immutable payload 边界；事件表只允许未来 repository 通过私有 non-nested UOW + exact insert claim 写入，outbox 只允许未来 dispatcher 更新 claim 状态，payload/identity/idempotency/创建时钟不可改写或删除。
- 新增迁移 `apps/audit/migrations/0011_systemauditeventmodel.py`，仅包含两个 `CreateModel`，无 `RunPython`、`RunSQL`、默认记录或现场 User/Profile 回填；`makemigrations audit --check --dry-run` 返回 `No changes detected`。
- 隔离 Django 5.2 SQLite component：事件模型 `3 passed`、outbox 模型 `3 passed`；unit Domain/codec 回归 `10 passed`；增量 mypy `0 regressions`，architecture `2885 files / 0 violations`，治理一致性与 audit registry guard 通过。
- 本批仍不提供 repository、query、dispatcher、Data Center 双写、业务 runtime wiring 或生产数据迁移；SQLite 只证明 schema/guard 软件契约，PostgreSQL 并发、真实 migration/rollback、outbox backlog/恢复和生产审计覆盖继续未验证，所有业务写入口与 execution gate 保持原状。

### 2026-08-15：M1 ledger repository 与 staff-only query 合同

- 新增 `apps/audit/infrastructure/system_audit_repository.py`：同 alias private atomic append、exact insert claim、first-winner replay、stream predecessor CAS、strict codec/逐列 header 恢复、全表 closed-world predecessor 图校验，以及 exact/PIT/list/head 读取；future/损坏/替换状态 fail closed，expired 语义不回退旧链。隔离 component `5 passed`，与模型 guards 合计 `8 passed`。
- 新增 `apps/audit/application/system_audit_query.py`：不依赖 ORM 的 staff-only reader context、ID/version/hash/PIT exact command、stream 分页 DTO 与 repository Protocol；非 staff 在触碰 repository 前拒绝，repository selector substitution/无序结果 fail closed；纯 unit `5 passed`，增量 mypy `0 regressions`，architecture `2887 files / 0 violations`。
- 本批仍未提供 outbox dispatcher/claim worker、Data Center 双写、业务 runtime wiring 或生产 composition；SQLite component 不证明 PostgreSQL 空链并发/first-winner，真实 migration/rollback、backlog 恢复、staff authority source 与生产审计覆盖继续未验证。

### 2026-08-15：M1 staff query actor binding

- `SystemAuditReaderContext.can_read` 现在除 authenticated/staff 外，还必须满足 `actor_id == django-user:{user_id}`；不允许把任意 service/actor 字符串与 staff 标志拼成可读上下文。该约束只校验请求上下文的内部绑定，不冒充权威 RBAC/authority source。
- 新增未绑定 actor 的 repository-before-call fail-closed 回归，query unit `6 passed`，增量 mypy `0 regressions`。具体 authenticated user、staff/RBAC authority source、owner scope 与生产 composition 仍待后续。

### 2026-08-15：M1 outbox claim/dispatcher 合同

- 新增 `apps/audit/infrastructure/system_audit_outbox_repository.py`：严格恢复全表 outbox payload 与事件 codec，private exact-insert claim，enqueue first-winner/idempotency replay，private non-nested UOW，due-row claim、worker/token ownership、delivered/failed 状态机和 immutable payload/hash 校验；claim/transition 只更新允许的状态列，不删除或重写事件。
- 新增 `apps/audit/application/system_audit_outbox_dispatcher.py`：无 ORM/外部 publisher import 的 dormant Protocol/use case，按 bounded batch 发布 `requested/claimed/delivered/failed/outcome`，publisher 异常只落稳定 `publisher_error`，业务双写和真实 publisher composition 仍关闭。
- 隔离 component `7 passed`、dispatcher unit `3 passed`；增量 mypy `0 regressions`，与已有 outbox model 回归合计 `10 passed`。本地证据仍只覆盖 SQLite/纯 fake；PostgreSQL claim race/lease、真实 backlog 恢复、Data Center 双写、runtime wiring、生产 authority 与迁移回滚继续未验证。

### 2026-08-15：M1 outbox transition guard 收口

- 收紧 `apps/audit/infrastructure/system_audit_outbox_models.py`：现有行的 `save/save_base`、QuerySet/manager `update/bulk_update` 均不能绕过 repository 私有 state-transition capability；payload、identity、idempotency 和创建时钟继续不可变，删除仍被阻断。
- `DjangoSystemAuditOutboxRepository` 的 claim/delivered/failed 只能在同一 private UOW 中取得精确行、字段和值绑定的 transition capability 后写入；直接 ORM 状态修改测试改为 fail-closed。定向模型/repository/dispatcher 回归 `10 passed`，增量 mypy `0 regressions`。
- 该批只关闭“可绕过 repository 改状态”的本地软件契约；expired claimed lease reclaim、mixed batch/failure accounting、真实 PostgreSQL race/lease、backlog recovery、业务双写和生产 publisher 仍未完成，不能据此解除 M1 PostgreSQL gate。

### 2026-08-15：M1 outbox expired-lease recovery

- `DjangoSystemAuditOutboxRepository.claim_due()` 现在接受正的 `lease_duration`（默认 5 分钟）：pending 且到期的行照常首次领取，claimed 且 `claimed_at + lease_duration <= as_of` 的行可由新 worker 在同一锁/UOW 中重新领取；每次回收都会生成新 token、递增 attempt，旧 worker 的 token 稳定冲突，避免 worker 崩溃造成永久 `claimed`。
- component 新增 lease 未到期不回收、到期回收、旧 token 不能 finalize、新 token 可完成的闭环；outbox repository/model/dispatcher 定向回归 `11 passed`，增量 mypy `0 regressions`，仍未把 SQLite 结果计为 PostgreSQL race 证据。
- lease TTL 仍是 repository 配置而非生产调度证明；mixed batch/failure accounting、真正 PostgreSQL 双连接竞争、backlog 观测/告警、真实 publisher、业务双写和生产迁移继续未完成。

### 2026-08-15：M1 dispatcher mixed-batch accounting

- 扩展 dormant dispatcher 的 unit contract：同时处理成功与 publisher failure 时，`requested/claimed/delivered/failed` 精确分别计数并发布 `partial`；空 claim 批次稳定发布 `noop`，每条成功/失败 transition 都保留自己的 outbox identity。
- dispatcher 与 event helper 定向回归 `10 passed`；这只是纯 Application fake 证据，不代表真实 publisher、批量事务、PostgreSQL lease race 或生产 backlog 观测已接通。

### 2026-08-15：PostgreSQL 并发证据 harness（本地 disposable run）

- 新增 `tests/component/audit/test_system_audit_postgres_concurrency.py` 与独立 `tests/settings_audit_postgres_concurrency.py`；覆盖空 stream first-winner、同 predecessor CAS、outbox claim lease ownership，以及 claim transaction rollback 后的重新 claim。
- harness 默认沿用 SQLite 配置时只 `skip`；只有同时设置 `AGOM_AUDIT_PG_CONCURRENCY_EVIDENCE=1`、专用 `AGOM_AUDIT_PG_TEST_DATABASE_URL` 并显式选择独立 settings 才可运行。URL 必须是 PostgreSQL 且数据库名同时含 `audit`/`test`；运行库必须是 pytest 隔离库，禁止回退 `DATABASE_URL` 或复用生产配置。
- 模块级 schema fixture 显式依赖 `django_db_setup`，并在数据库身份检查/建表时使用 `django_db_blocker.unblock()`；这样不会在 pytest 建立隔离数据库前误读原始连接，也不会被项目级 Data Center fixture 拉入最小设置。fixture 直接执行 migration `0011` 的 `database_forwards/database_backwards`，同时覆盖 PostgreSQL DDL forward/backward。
- 本地使用 Docker `postgres:16-alpine` 临时容器 `agom-audit-pg` 与 `audit_test` 数据库，运行命令为：`$env:AGOM_AUDIT_PG_CONCURRENCY_EVIDENCE="1"; $env:AGOM_AUDIT_PG_TEST_DATABASE_URL="postgresql://agomtest:agomtest@127.0.0.1:55432/audit_test"; $env:DJANGO_SETTINGS_MODULE="tests.settings_audit_postgres_concurrency"; python -m pytest tests/component/audit/test_system_audit_postgres_concurrency.py -q --tb=short --create-db --confcutdir=tests/component/audit`；pytest 隔离数据库为 `test_audit_test`，结果 `4 passed`（194.64s）。容器已在测试后删除，未接触生产配置或数据。
- 该结果是本机真实 PostgreSQL 隔离库的 race/rollback 软件证据，不是生产 PostgreSQL/VPS 证据；完整生产迁移回滚、backlog/恢复、Data Center 双写、publisher/runtime wiring、staff authority source 与生产审计覆盖仍未验证，registry 的生产 gate 继续保持阻断。

### 2026-08-15：M1 migration forward/backward 本地证据

- 新增 `tests/component/audit/test_system_audit_migration.py`，以迁移 `0011_systemauditeventmodel` 的 `ProjectState` 和真实 SQLite `SchemaEditor` 执行两个 `CreateModel` 的 forward/backward，断言 `audit_system_event` 与 `audit_system_outbox` 均能创建并完整回滚；系统审计 component 回归 `16 passed`。
- 该批只关闭本地 schema operation 的回滚盲区，不等价于完整历史 migration chain、PostgreSQL DDL/rollback 或生产数据库演练；registry 的 PostgreSQL concurrency/rollback gate、outbox backlog recovery、Data Center 双写和 M2 仍保持阻断。

### 2026-08-15：M1 outbox backlog/recovery observability contract

- 新增只读 Application `SystemAuditOutboxBacklogSnapshot` 与 `GetSystemAuditOutboxBacklogUseCase`，固定观察 cutoff、pending/claimed/failed/delivered 计数、due pending、expired claim、最老 backlog/claim 时钟与非负 age；不暴露 worker token，不执行 claim、lease reclaim、publish 或状态写入。
- `DjangoSystemAuditOutboxRepository.get_backlog_snapshot()` 先对全表执行既有 strict codec/closed-world restore，再按 repository lease TTL 聚合 backlog；SQLite component 新增 pending/claimed/failed/delivered、expired claim 和无状态变更证据，Application unit `9 passed`、outbox repository component `7 passed`、增量 mypy `0 regressions`，black/isort 通过。
- PostgreSQL opt-in harness 另加入同一 backlog 聚合的 closed-world/只读断言（pending/claimed/expired/failed/delivered 与 token/status 不变）；本批未启动 disposable PostgreSQL，因此只登记测试资产，不把未运行结果计入 PostgreSQL 证据。
- 该批只是本地可观测性契约与聚合读取，不是 Prometheus/health endpoint、publisher/runtime wiring、生产告警或 backlog 自动恢复；真实 PostgreSQL backlog 观察窗口、生产 migration/rollback、Data Center 双写、publisher 和 authority source 仍由 registry next gate 阻断。

### 2026-08-15：M1 outbox closed-world clock/state hardening

- 收紧 outbox restore：`available_at`、claim、delivery/failure、`updated_at` 的时序必须闭合；pending/claimed/delivered/failed 各状态不得残留另一状态的 terminal/claim 字段，避免 raw SQL 篡改后被 backlog 聚合静默接受。
- 新增 SQLite raw-tamper component 覆盖 available/claim/delivery/failure 时钟倒置、pending terminal 残留、pending `updated_at` 漂移和 future observation cutoff；outbox model/repository/dispatcher 相关回归 `32 passed`，增量 mypy `0 regressions`，black/isort 通过。
- 该批只加强本地 closed-world fail-closed；不替代 PostgreSQL 双连接竞争、生产 backlog 观察窗口、publisher/runtime wiring、自动恢复或生产审计覆盖。

### 2026-08-15：M1 outbox backlog health projection wiring

- `AuditHealthChecker` 现在可注入只读 `SystemAuditOutboxBacklogReader`，并把 pending/due/claimed/expired/failed/delivered 与 oldest-age 投影为 `audit_outbox_backlog` health check；expired claim 或 failed row 标记 `WARNING`，读失败只发布受控 `ERROR` 类型，不暴露 token、payload 或连接串。
- `check_audit_health()`/health-check provider 已组装同 alias 的 outbox reader；unit/API 回归 `16 passed`，覆盖 recovery warning、healthy snapshot、观察 cutoff 和公共响应脱敏。
- 这只是 health projection wiring，不是 Prometheus 指标、publisher/runtime、自动 reclaim、生产 migration/rollback 或真实 PostgreSQL 观察窗口；Data Center 双写和 M2 仍保持阻断。

### 2026-08-15：M1 event/outbox atomic composition contract

- 新增 `AppendSystemAuditEventOutboxUseCase` 与同 alias 的 `DjangoSystemAuditEventOutboxCoordinator`：事件账本 append 和 outbox enqueue 嵌在同一个 outer transaction，二者使用同一 canonical payload/content hash；exact retry 返回同一 pair，任一 outbox 异常整体回滚事件。
- Application unit `5 passed`、SQLite schema component `3 passed`，覆盖 exact replay、writer failure、event substitution 和 outbox failure rollback；增量 mypy `0 regressions`、architecture audit `0 violations`、Black/isort 通过。
- 该批只建立 dormant atomic composition，不接 Data Center sync、业务事件注册状态、publisher/runtime 或生产 route；`data.fetch.*` 仍保持 `not_wired`，真实 PostgreSQL race、迁移回滚、业务双写与生产审计覆盖继续阻断。

### 2026-08-15：M1 Data Center fetch-event envelope contract

- 新增 `apps/data_center/application/data_fetch_audit.py`：以 typed
  `DataFetchAuditObservation` 和 `build_data_fetch_audit_event()` 固定
  `data.fetch.completed/noop/failed` 的 outcome、reason、provider/capability/dataset、
  `run_id/ingested_run_id` 与 RawAudit exact evidence ref；事件 ID/idempotency key
  由批次身份稳定派生，stream sequence/predecessor 必须由同 alias coordinator 提供，
  不允许 builder 现场伪造。
- 定向 unit `8 passed`，增量 mypy `0 regressions`，architecture/audit `0 violations`，
  Black/isort/diff-check 通过。
- 这只是 Data Center Application envelope 合同，**没有**给现有
  `SyncMacroUseCase` 接入 writer：当前同步请求没有稳定 `run_id/ingested_run_id`，
  RawAudit 也没有可直接复用的 content-bound identity；事实、Provider Health、RawAudit、
  Publication 与 event/outbox 还没有共同 UOW。故治理 registry 仍保持
  `planned/not_wired`，不得把本地 builder 测试宣称为业务双写或生产审计覆盖。

### 2026-08-15：M1 bounded outbox backlog Prometheus projection contract

- `apps/audit/infrastructure/metrics.py` 新增固定 `owner=audit` 标签的
  `system_audit_outbox_pending`、`system_audit_outbox_oldest_age_seconds` 及
  due/claimed/expired/failed/delivered gauges；投影只接受已验证的
  `SystemAuditOutboxBacklogSnapshot`，不接受任意资源、用户、run 或错误文本作为标签。
- `record_system_audit_outbox_backlog()` 是纯指标 sink，不读取数据库、不 claim/renew/publish，
  空 backlog 的 oldest age 明确投影为 `0.0`；metrics safety 与 backlog Application contract
  定向回归 `23 passed`。
- 本批保持 dormant：没有把 `/metrics/` scrape 绑定到数据库 reader，也没有接 health scheduler、
  Celery task、publisher sink 或 failed-row retry；因此不能宣称 Prometheus runtime observation、
  自动恢复、生产告警或 PostgreSQL backlog 观察已完成。Data Center 双写仍保持
  `planned/not_wired`，生产 migration/rollback 与 publisher/runtime gate 继续阻断。

### 2026-08-15：M4 `/metrics/` lazy backlog projection wiring

- `apps/audit/application/repository_provider.py` 新增只读 projection facade：固定使用
  `default` 数据库 alias、`django.utils.timezone.now()` 作为观察 cutoff，调用既有 backlog
  Application use case 后投影到 bounded gauges；读库、strict restore 或 metric sink 异常只记录
  `error_type` 并返回 `False`。
- `core/urls.py::metrics_view` 在生成通用 Prometheus payload 前 lazy 调用该 facade；导入或投影
  失败均被隔离，通用 `/metrics/` 仍返回 200，且不把异常文本、连接串、token 或高基数 ID 写入日志/label。
- provider + `/metrics/` view 定向回归与既有指标测试 `33 passed`，增量 mypy `0 regressions`，
  architecture audit `0 violations`。本批不接 publisher、Celery、retry/requeue、Task Monitor
  或 Data Center 双写；生产 PostgreSQL/backlog 观察与真实告警仍待完成。

### 2026-08-15：M1 Data Center RawAudit identity boundary

- `RawAudit` 现在可携带稳定 `raw_audit_id`、服务端批次 `run_id`、`ingested_run_id` 与
  canonical `content_hash`；新增 `RawAuditReference` 只接受完整 identity、lowercase
  SHA-256 和两级批次关联，历史缺字段行无法提升为统一 fetch event。
- `RawAuditRepository.log()` 在持久化前重算 content hash，拒绝 caller 提供的错误 hash，
  通过 UUID 边界拒绝非法批次身份；`0070_rawaudit_identity_and_content_hash` 仅增加
  nullable 字段，不回填历史行、不把数据库主键伪造成批次身份。定向 RawAudit/SyncMacro/
  Macro publication 回归 `15 passed`，`makemigrations --check`、Django check、增量 mypy
  均通过。
- 该批只建立可供未来事件引用的 identity-bearing evidence boundary，**没有**给
  `SyncMacroUseCase` 接入 run issuer、共同 UOW、事实/Health/RawAudit/Publication/event/outbox
  双写；`data.fetch.*` 仍保持 `planned/not_wired`，生产 migration/backfill 与 PostgreSQL
  双写证据继续阻断。

### 2026-08-15：M1 Data Center SyncExecution identity contract

- 新增纯 Application `SyncExecutionIdentity` 与 `SyncExecutionIdentityIssuer` port，固定
  server-issued `run_id`、`ingested_run_id`、`batch_id`、dataset/provider selector 及
  domain-separated identity hash；`IssueSyncExecutionIdentityCommand` 只接受路由字段，
  不接受 caller UUID、request clock、随机 fallback 或 hash。
- `raw_audit_correlation` 原样返回 run/ingested-run pair；8 个纯单元测试、增量 mypy、
  architecture、Black/isort/diff-check 均通过。
- 该批仍是 dormant boundary：没有实现 issuer persistence、SyncMacro 共同 UOW、事实/
  Health/RawAudit/Publication/event/outbox 双写、迁移回填或生产 PostgreSQL 证据；
  `data.fetch.*` 继续保持 `planned/not_wired`。

### 2026-08-15：M1 outbox dispatch task fail-closed contract

- 新增受治理的 Celery task `apps.audit.application.tasks.dispatch_system_audit_outbox_task`，
  在 canonical durable publisher 尚未组装时于 claim 前返回 `outcome=blocked`；不导入通用
  Events bus、不使用 memory/eager fallback、不伪造 `delivered`。输入、composition failure
  与 blocked 结果均为 bounded counters/reason code。
- 新增显式 `publisher_not_wired` infrastructure gate、blocked result DTO 与 4 个 task
  contract tests；`check_celery_task_contracts.py` 通过（88 registered tasks，22 governed
  files），定向 task tests `4 passed`。
- 这不是 publisher/runtime wiring 或自动恢复：没有 claim、retry/requeue、beat schedule、
  业务双写或生产 broker/PG 证据；system-audit 的 production publisher/runtime gate 继续阻断。

### M1：Audit Domain、append-only ledger 与 Query

交付：

- frozen typed Domain entities、event taxonomy、actor/resource/evidence refs、canonical codec/hash。
- schema-only、zero-seed migration；append-only repository、幂等 append、exact/stream/PIT query。
- transactional outbox 与 dispatcher claim contract。
- staff-only Application Query DTO；暂不新增最终 TUI screen。

退出条件：纯 Domain、codec、schema-only SQLite component 和 PostgreSQL 并发/不可变性测试通过；dispatcher claim contract 与业务双写仍需独立批次，无跨层 ORM 或 App 循环依赖。

### M2：Data Reliability 纵向试点

交付：

- Sync Macro/Price/Quote 首批贯通 run/ingested_run/RawAudit/fact/publication/event identity。
- Provider Health、circuit breaker、failover adapter、validation、freshness gate、Publication、repair workflow 产生登记事件。
- `fresh/stale/missing/conflict/failed` 状态转换、block/recovery 具备可重放时间线。
- RawAudit 和 Publication 专业证据保持真源，统一事件只引用 exact evidence。

退出条件：给定任一 repair run 或 publication ID，可重放 fetch → validate → failover → persist → publish → read gate 全链；缺任何关键 evidence 时失败关闭。

### M3：系统操作与关键治理面接入

交付：

- MCP/SDK OperationLog adapter、关键 API/CLI/Celery outcome、配置变化和权限/Token 生命周期事件。
- Evidence/Promotion/decision gate、Portfolio/Risk/Broker 只接入已获各 owner 批准的 P0 状态变化。
- required/best-effort/outbox 策略按机器合同生效。

退出条件：关键 mutation 不再只留下自由文本日志；审计写入失败策略可自动测试。

### M4：Metrics、Alert 与运行取证

交付：

- 核心 `/metrics/` 发布 bounded audit/data-reliability 指标。
- Task Monitor 告警、恢复、确认和通知闭环。
- 审计链完整性、outbox age、Provider/Publication blocker readiness probe。
- 生产日志/Sentry 配置状态进入 readiness，但不冒充业务审计完整性。

退出条件：故障注入可稳定触发 metric → alert → recovery；相同持续状态不会产生无界事件或告警风暴。

### M5：TUI 查询、导出与权限

交付：

- 管理员 TUI 系统观测 screen、事件时间线、过滤、详情、复制 ID。
- staff-only REST/SDK query；分页、时间窗、owner/category/outcome/reason/关联 ID 过滤。
- 受治理 JSONL/CSV 导出，包含导出 receipt/hash；限制范围、大小和敏感字段。
- 普通用户、staff、superuser 和自动化 token 权限矩阵。

退出条件：管理员可以在一个主任务中定位 P0 事件链；越权、枚举、导出泄密和大查询均被测试阻断。

### M6：双写观察、切换与旧链收缩

交付：

- 双写一致性报告：旧专业日志/状态变化与统一事件数量、hash/ref、缺失和重复对账。
- 生产观察窗口、容量/延迟、告警噪声、恢复演练和 archive/restore 演练。
- 只收缩已由统一链替代的兼容查询或重复聚合；专业证据表不删除。
- 更新运行手册、数据字典、治理基线、索引和归档记录。

退出条件：观察窗口无 P0 丢事件、重复、秘密泄漏、链路断裂或性能回退；回滚演练和负责人签字完成。

## 12. 配置、保留与回滚

### 12.1 配置真源

运行策略进入 Config Center/治理合同，建议至少包括：

- `audit.system_event.mode=off|shadow|required`
- `audit.system_event.outbox_enabled`
- `audit.system_event.owner_write_policy`
- `audit.system_event.retention_policy`
- `audit.system_event.export_policy`
- `audit.system_event.alert_policy`

不得在业务代码新增保留天数、告警阈值或 owner 例外硬编码。配置快照本身也必须被审计。

### 12.2 Retention

- 事件按 category/severity/compliance class 使用治理策略，不采用单一全局天数。
- 热数据、归档数据和专业 evidence 的保留策略分离。
- 清理前必须生成 manifest、范围、count/hash 和 retention run receipt；失败不允许部分静默删除。
- Archive 恢复必须重验 event content hash、stream predecessor 和 evidence reference 可解析性。

### 12.3 回滚

- 关闭新事件 emission 或 dispatcher 不删除已写事件。
- `shadow` 模式允许恢复旧查询/告警入口，但 required 关键事件一旦正式切换，不得通过普通配置静默降级。
- 数据库 migration 回滚仅在无生产事件时允许；已有事件后采用前向修复。
- 历史回填仅允许受控 metadata import，必须标记 `legacy_import` 和 coverage，不得伪造当时不存在的 trace/run/evidence。

## 13. 测试与验收矩阵

| 层级 | 必测内容 |
|------|----------|
| Domain | 枚举、时钟、actor/resource/evidence ref、hash、stream、reason code、脱敏边界 |
| Application | required/outbox/best-effort、幂等、权限、分页、过滤、恢复和 export policy |
| Infrastructure | append-only shortcut、transaction、outbox claim、archive、hash/tamper、PostgreSQL 并发 |
| Data Center | success/noop/partial/all failed、stale/fresh、failover、conflict、publication block/rollback、时间保真 |
| Integration | HTTP→Application→evidence→event、Celery context、MCP/SDK OperationLog ref、Task Monitor alert |
| Security | Token/credential/Cookie/PII/异常内容脱敏、越权、枚举、导出范围、日志注入 |
| Metrics | label bounded、counter/gauge 语义、进程重启、重复投递、告警持续/恢复 |
| TUI | primary task/outcome、P0 panel、默认 action、分页、复制 ID、无 Classic 新页面 |
| Performance | 批量同步事件量、索引查询、outbox backlog、写放大、retention/archive 窗口 |

实施阶段至少运行：

```bash
python scripts/check_audit_event_contracts.py
python scripts/check_current_data_contracts.py
python scripts/check_celery_task_contracts.py
python scripts/check_architecture.py
python scripts/check_mypy_regression.py <changed-production-python-files>
python scripts/check_mypy_debt_ceiling.py
pytest <audit/data-center/task-monitor focused suites> -q
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/test_terminal_agent_service.py -q
pytest sdk/tests/test_sdk/test_client.py -q
pytest tests/unit/test_internal_ssl_redirect.py -q
```

涉及 PostgreSQL append-only、first-winner、outbox claim 和 archive/restore 的验收不能只用 SQLite 代替。

## 14. Definition of Done

- [ ] P0/P1 审计面 inventory 有明确 owner、symbol、event contract、write policy 和测试证据。
- [ ] 所有新增关键事件只能使用登记 taxonomy；未知类型、未知 reason code 和任意 payload 失败关闭。
- [ ] 给定 trace/request/task/run/ingested_run/publication/resource ID 可查询完整有序事件链。
- [ ] 数据可靠性首批链路可重放 fetch、validate、failover、persist、publish、read block 和 recovery。
- [ ] Source observation time、fetch time、record time 不被互相覆盖或洗白。
- [ ] 专业 evidence 与统一事件 exact ref/hash 可双向核对，无双真源。
- [ ] required 事件无静默丢失；outbox 可恢复且积压可观测。
- [ ] append-only、幂等、fork/tamper、PostgreSQL 并发和 archive/restore 验证通过。
- [ ] `/metrics/` 包含 bounded 系统审计和数据可靠性指标，且无高基数/敏感 label。
- [ ] Task Monitor 告警只消费 owner 结论，具备去重、升级、确认和恢复闭环。
- [ ] TUI 完成管理员定位主任务；不新增 Classic 主页面，不暴露秘密或任意 JSON。
- [ ] 双写观察、容量评估、故障注入、回滚演练和生产签字完成。
- [ ] 相关治理 JSON、CI、运行手册、数据字典、`docs/INDEX.md` 与归档索引同步更新。

## 15. 风险与控制

| 风险 | 控制 |
|------|------|
| 泛化事件表变成无约束 JSON 垃圾桶 | typed detail contract + registry + unknown schema 拒绝写入 |
| 与 RawAudit/Publication/OperationLog 形成双真源 | 统一事件只保存摘要和 exact evidence reference/hash |
| 高频读取造成事件风暴 | 状态转换事件、周期摘要、幂等键和 bounded stream |
| 审计写入拖慢数据同步 | 同事务 outbox、批量 append、受控 dispatcher；关键 mutation 仍 required |
| 跨 App 依赖形成循环 | Audit 不反向 import 业务 App；composition 位于 `core/integration` |
| 错误消息或 payload 泄密 | owner 边界白名单、稳定错误分类、codec/export 双重脱敏 |
| Prometheus 高基数 | label registry；资源/trace/run/publication ID 只进入日志查询字段 |
| “有事件”被误当成“数据可决策” | 决策安全只由 Data Center/Evidence owner 判断；Audit 不授予权限 |
| SQLite 测试掩盖生产并发问题 | PostgreSQL first-winner/outbox/archive 为强制验收项 |
| 为做控制台违反 Web→TUI 冻结 | 只建 TUI 管理员任务；现有 Classic 日志页只兼容维护 |

## 16. 建议实施顺序

1. 先执行 M0，不在 inventory 和 ADR 前直接创建“大而全”的 Event Model。
2. M1 只建立最小 canonical envelope、append-only ledger、outbox 和 query。
3. M2 选 Macro/Quote/Publication/Decision Reliability Repair 做完整纵向链，不同时扩散到所有 App。
4. 数据可靠性链通过后，再在 M3 接 MCP/SDK、配置、Evidence 和执行控制面。
5. Metrics/Alert、TUI、双写切换分别作为独立提交组，避免功能、治理、界面和生产切换混在一个批次。

本计划完成前，现有运行日志、RawAudit、OperationLog、Provider Health、Publication、Task Monitor 和 `/metrics/` 均继续保留；任何一项现有证据或硬闸不得仅因“统一审计正在建设”而提前退役或放宽。
