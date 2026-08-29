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

- 新增 `apps/audit/application/data_fetch_audit.py`：以 typed
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

### 2026-08-15：M1 Data Center SyncExecution identity persistence boundary

- 新增严格的 Application `SyncExecutionIdentityRepositoryPort` 与
  `PersistSyncExecutionIdentityUseCase`：持久化入口只接受完整、已由 owner 发行的
  `run_id`/`ingested_run_id`/`batch_id`/selector/hash，不创建 UUID、不采样 clock、不接受
  selector-only fallback；相同 canonical identity 可 exact replay，hash/context/ID 冲突
  fail closed。
- 新增 schema-only migration `0071_syncexecutionidentitymodel` 与 dormant
  `SyncExecutionIdentityRepository`。identity 表没有 generated ID/clock；模型的 save/
  save_base、QuerySet/manager update/delete/bulk shortcuts、pre_delete 均由 private
  UOW/insert claim 拦截，repository 才能执行一次 exact insert。migration state、纯
  Application、SQLite component 合计 `16 passed`，`makemigrations --check` 通过；component
  使用独立内存 SQLite 设置，避免全仓 Django fixture 掩盖本切片结果。
- 该批只完成 owner-issued identity 的持久化/不可变证据边界，**没有**接入
  `SyncMacroUseCase` writer、共同 UOW、事实/Health/RawAudit/Publication/event/outbox
  双写、历史回填或生产 PostgreSQL race/rollback；`data.fetch.*` 继续保持
  `planned/not_wired`。

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

### 2026-08-15：AUD-01 composition preflight contract

- 新增纯 Application `system_audit_composition` boundary。未来 durable publisher 必须返回
  `CanonicalSystemAuditPublishReceipt`，逐项保留 event id/version、identity/content hash、
  stream predecessor、sequence、idempotency key 与 canonical payload；dispatcher 遇到缺失、
  替换或 generic/memory 风格返回值时，以 `publisher_contract_violation` 失败关闭。
- 新增注入式 `SystemAuditAuthorityProvider` 与严格 snapshot 投影。缺 provider、非认证、非
  staff、actor/user 未绑定或无效 cutoff 均在 repository 前以稳定 `authority_*` reason code
  阻断；该合同不接受 caller 自带 actor/role，也没有 route/ORM 侧伪造 authority。
- 这仍是本地 composition preflight，不是 production publisher/runtime wiring：现有 runtime
  gate 继续返回 `publisher_not_wired`，没有 durable sink、beat/retry/requeue、authenticated
  scoped lifecycle、生产 PostgreSQL/VPS migration/rollback/observation；AUD-01 未解除，
  AUD-02 继续等待依赖。

### 2026-08-15：AUD-01 canonical receipt malformed-payload hardening

- `CanonicalSystemAuditPublishReceipt.validate_for()` 现在把不可 canonical JSON 编码的
  publisher payload（例如嵌入不可序列化对象）统一转换为
  `SystemAuditPublisherContractViolation`；dispatcher 稳定记录
  `publisher_contract_violation`，不再把 publisher contract 破坏误报成普通
  `publisher_error`。
- composition/dispatcher 定向回归 `25 passed`；Black、isort、增量 mypy、architecture
  与 audit contract checks 均通过。
- 这只是 fail-closed 合同加固：runtime 仍固定 `publisher_not_wired`，没有 durable
  publisher/receipt sink、authenticated scoped lifecycle、beat/retry/requeue 或生产
  PostgreSQL/VPS 证据；AUD-01 未解除，AUD-02 继续等待依赖。

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

M6 中 migration state、outbox backlog/oldest age、bounded metrics、alert/recovery、双写 count/hash/ref 差异、archive manifest/hash 与候选观察时长均应由代理从生产只读接口或快照自动采集。生产 migration/rollback、故障注入、archive/restore 和兼容链切换必须先取得精确授权；负责人签字不得自动生成。若 read model 或 collector 缺失，先在 `AUD-03` 内补 fail-closed collector，再继续观察，不把采集能力缺口当成外部阻塞。

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

## 实施记录（2026-08-15，AUD-01 authority boundary hardening）

在既有 AUD-01 composition preflight contract 基础上，`get_system_audit_reader_context()` 现在
在触碰 provider 前严格拒绝非 `datetime` 或 naive cutoff；provider 抛出异常或返回错误类型时，
统一转为稳定的 `authority_unavailable`，不把数据库、RBAC 或其他内部异常内容泄露到读取边界。

定向 `tests/unit/audit/test_system_audit_composition.py` 为 `15 passed`；增量 mypy、architecture
audit、Black、isort 与 diff-check 通过。该 slice 仍不创建 authority source，也不改变
`publisher_not_wired` runtime gate；真实 authenticated scoped lifecycle、durable publisher/receipt
sink、beat/retry、PostgreSQL/VPS 证据和 AUD-02 Data Center 同 UOW 继续未完成。

## 实施记录（2026-08-15，AUD-01 canonical receipt exact-tree hardening）

`CanonicalSystemAuditPublishReceipt.validate_for()` 现在在 canonical JSON 编码前进行递归的
exact-tree 比对：容器类型、标量类型、序列顺序和字符串 key 类型必须与原始
`SystemAuditEvent.to_payload()` 完全一致；tuple/list 替换、嵌套非原生 mapping 与标量类型
替换均 fail closed，仍统一抛出 `SystemAuditPublisherContractViolation`，dispatcher 记录稳定的
`publisher_contract_violation` 而不是普通 `publisher_error`。新增 composition/dispatcher 覆盖后，
AUD 定向回归为 `30 passed`；audit event contract、增量 mypy、architecture、Black/isort、
compile 与 diff-check 均通过（当前环境未安装 ruff 模块）。

该 slice 仍只是 publisher receipt 的本地合同加固：runtime 固定返回 `publisher_not_wired`，
没有 durable publisher/receipt sink、authenticated scoped authority lifecycle、beat/retry/requeue、
生产 PostgreSQL/VPS 观察或 AUD-02 Data Center 同 UOW；AUD-01 继续保持 planned，AUD-02 继续等待。

## 实施记录（2026-08-15，AUD-01 当前候选部署复核）

包含上述 exact-tree receipt hardening 的 `dev/next-development@cf68dc1e972ecd6e0ae002e4d4f96ff07ef86542`
已以标准 `git-clone`、代码-only、保留数据卷的 `-Upgrade` 模式部署为 release
`20260815182857`；release manifest、OCI revision 与 image ID 绑定一致。部署报告为
`dist/remote-build-reports/remote-build-report-20260815182857.json`，web/Celery worker/beat、
PostgreSQL、Redis、RSSHub、Caddy、迁移、canonical schema、TUI registry、Qlib 与 Celery ping
均复核通过，独立 HTTPS health/ready 均 HTTP 200。

ready 响应仍原样保留 Alpha/Qlib provider degraded、workspace recommendation stale 与
market thermometer partial-stale warnings；本次只证明候选身份和运行健康，不代表 durable
publisher/receipt sink、authenticated scoped authority、beat/retry/requeue、AUD-02 Data Center
双写、M5 UAT、DATA-01 restore/rebuild 或生产回滚已完成。AUD-01 仍未解除。

## 实施记录（2026-08-15，AUD-01 authority snapshot integrity contract）

`SystemAuditAuthoritySnapshot.authority_content_hash` 现在通过
`system_audit_authority_content_hash()` 使用 domain-separated canonical digest 绑定
`actor_id`、`user_id`、`tenant_id`、`owner_id`、认证/staff 标志与 role；
`get_system_audit_reader_context()` 在投影 reader context 前调用
`validate_integrity()`，scope/身份字段被替换或 provider 继续返回占位 digest 时统一
fail-closed 为 `authority_unavailable`。composition 定向回归 `20 passed`，与 query、
dispatcher、dispatch task 合计 `38 passed`；增量 mypy、architecture、Black/isort 与
diff-check 通过。

该 slice 只证明 provider snapshot 的本地完整性边界，不提供 authenticated provider、
tenant/owner RBAC、route composition 或 durable publisher；runtime 仍固定
`publisher_not_wired`，AUD-01 保持 `planned`，AUD-02 继续等待依赖。

## 实施记录（2026-08-15，AUD-01 provider-issued query context boundary）

`SystemAuditReaderContext` 现在只能由 Audit authority composition 通过私有 provider-issued
capability 构造为可读上下文；直接手工构造的同形对象即使字段看似合法，也会在 use case 入口
稳定阻断为 `authority_unavailable`。reader context 同时保留并校验 `tenant_id`、`owner_id`
和 authority content hash，composition 不再丢失这些 scope/integrity 字段。query 与 composition
定向回归为 `39 passed`，增量 mypy、Black/isort 与 diff-check 通过。

该 slice 只封 Application 内的 provider-issued context 边界：尚未提供真实 authenticated
authority provider、tenant/owner lifecycle 或 audit event ledger 的 tenant/owner 过滤列，也
没有接 durable publisher、route、beat/retry 或 production runtime；因此 `AUD-01` 仍保持
`planned`，`AUD-02/03` 继续等待依赖。

## 实施记录（2026-08-15，AUD-01 当前候选部署复核）

提交 `dev/next-development@1835ce0ee42f220756066a21890bcec2b8f1f3e9` 以标准 git-clone、
code-only、`-Upgrade` 模式部署为 release `20260815221000`；远端数据卷保留。部署报告为
`dist/remote-build-reports/remote-build-report-20260815221000.json`，image 为
`sha256:ef43c80ee8b5130775f152dfea0a7cdc62a93a8853ab4ccb8ba258ae83877ad1`，切换前 PostgreSQL
备份为 `/opt/agomtradepro/backups/database/postgres-20260815-161622.dump`。health、迁移、
canonical schema、TUI registry、Qlib、Celery/Caddy 复核通过。

该部署只证明候选身份和运行健康；`/api/ready/` 的 Alpha/Qlib、workspace freshness 与 market
thermometer warnings 原样保留。没有 authenticated tenant/owner authority、event scope/linkage
columns、durable publisher、beat/retry 或 production audit runtime，AUD-01 仍保持 `planned`，
AUD-02/03 继续等待依赖。

## 实施记录（2026-08-15，AUD-01 explicit event scope linkage contract）

新增 `AuditScopeRef(tenant_id, owner_id)` 作为事件唯一的 canonical tenant/主体 scope；
`SystemAuditEvent.owner` 明确继续表示事件 taxonomy/producer owner，禁止被解释成主体 owner。
scope 已进入 Domain identity/content payload 与 strict codec，`SystemAuditEventModel` 以成对 nullable
列和 schema-only migration `0012` 保存，repository/query 以 exact scope selector 过滤；scoped read
遇到历史 NULL scope、scope substitution 或 scope hash 不一致时 fail closed，append 没有显式 scope
直接阻断。scope pair、legacy round-trip、tamper、query selector 和本地 model/repository 回归已通过，
`manage.py check`、`makemigrations --check --dry-run`、增量 mypy（6 files）和 governance checks 均通过。

该 slice 只建立 scope linkage contract，不提供 tenant/owner immutable lifecycle、server-issued scope
provider、Data Center 同-alias authority bundle、durable publisher 或 production backfill；历史 NULL
scope 不会被静默补值，AUD-01/AUD-02 仍保持阻断。

## 实施记录（2026-08-15 23:05，AUD-01 scope contract candidate deployment）

包含 `0012_systemauditevent_scope` 的 `dev/next-development@45281620a8739ee666a1b20e6c6511c0b8101111`
已部署为 release `20260815230537`。远端 `audit` migration 显示 `0012` 已应用，Django check 0
issues、HTTPS health 200、TUI registry、release manifest/OCI/source、Celery 和容器健康均通过。
这只验证 schema contract 在当前候选上可迁移/启动；没有 tenant/owner immutable lifecycle、server-issued
scope provider、同-alias authority bundle、durable publisher 或 production audit runtime，AUD-01 仍阻断。

同一候选的 VPS 只读 inventory 在 `2026-08-15T15:30:22Z` 返回 audit event total/scoped/unscoped
均为 `0`；这证明本次 migration 没有 seed/backfill，不证明 production publisher、authority source
或 Data Center 双写已完成。

## 实施记录（2026-08-16，AUD-01 authority freshness/PIT contract）

`SystemAuditAuthoritySnapshot` 现在要求 provider-issued `source_id/source_version`、
`authority_state`、`recorded_at` 和 `valid_until`；这些字段与 actor/user/tenant/owner、认证/staff
事实一起进入 canonical authority content hash。composition 在 reader context 投影前同时执行
hash 完整性、active 状态和 `recorded_at <= as_of < valid_until` 校验，未来签发、过期或 revoked
snapshot 均统一阻断为 `authority_unavailable`。`SystemAuditReaderContext` 保留来源和有效窗口，
query use case 在实际 PIT 再调用 `can_read_at()`，避免一个曾经有效的 context 被复用于过期 as-of。

Audit composition/query 定向回归 `44 passed`，与 dispatcher/dispatch task 合计 `56 passed`；
增量 mypy（2 个 production files）、Black/isort、py_compile、diff-check、governance 与
architecture audit 均通过。该 slice 仍只提供本地 freshness/PIT 合同：没有 authenticated
tenant/owner lifecycle、source issuer、durable publisher/receipt sink、beat/retry、生产
PostgreSQL/VPS authority 观察；`publisher_not_wired` 和 AUD-01 gate 继续保持阻断。

## 实施记录（2026-08-16，AUD-01 durable delivery receipt contract）

`CanonicalSystemAuditPublishReceipt` 现在除完整保留 event identity、stream predecessor、
idempotency 和 canonical payload 外，还要求 bounded `sink_id`、`delivery_id` 与 timezone-aware
`published_at`。publication clock 早于 event `recorded_at`、缺失 delivery proof、或 sink/delivery
token 非 canonical 时，dispatcher 统一按 `publisher_contract_violation` 失败关闭，不能仅凭事件
字段相等把内存/泛型返回值计为 delivered。负向测试覆盖缺失 proof、clock 倒退和既有 payload/type
替换；AUD composition/dispatcher/task 定向回归 `46 passed`，增量 mypy、Black/isort、py_compile、
diff-check 与 governance consistency 通过。

该 slice 只是本地 receipt 合同强化：没有创建 durable sink、publisher runtime、beat/retry/requeue、
authenticated authority provider 或生产 PostgreSQL 投递证明；runtime 仍固定
`publisher_not_wired`，AUD-01 不解除，AUD-02 继续等待。

## 实施记录（2026-08-16，AUD-01 scoped authority composition preflight）

新增 `apps/audit/application/system_audit_authority_provider.py`：以 server-issued 的 Account
actor source 与 tenant/owner scope source selector 组成 exact bundle，逐项校验 source
identity/version/content hash、actor/user/tenant/owner 一致性、active/staff/authenticated 状态、
PIT 时钟和 final validity；缺 selector、替换、过期、future 或 reader 异常均返回 `None`，由既有
reader boundary 映射为稳定 `authority_unavailable`，不会触碰 outbox claim。纯测试 `6 passed`，
增量 mypy、governance 与 diff-check 通过。

该 slice 只补 typed composition/preflight，不读取 Django User/Profile/session，也没有现场 hash、
request actor、generic/memory fallback 或生产 writer。真实 immutable authority source、scope
lifecycle、durable publisher/receipt sink、beat/retry、production PostgreSQL 观察仍未接线，
因此 `AUD-01` 继续阻断。

## 实施记录（2026-08-16，AUD-01 preflight-to-receipt sink binding）

`inspect_canonical_system_audit_publisher()` 现在只调用一次 durable preflight，并把经校验的
`sink_id` 返回给 dispatcher；每条 `CanonicalSystemAuditPublishReceipt` 在交付前必须与该次
preflight 的 sink 完全一致，sink substitution 统一按 `publisher_contract_violation` 失败关闭，
避免只凭 event identity/hash 将另一个 durable 或泛型 sink 的回执计为 delivered。新增
composition/dispatcher 负例与单次 preflight contract 测试；composition/dispatcher 定向回归
`47 passed`，task/authority 定向回归 `10 passed`，增量 mypy、Black/isort、py_compile、
architecture、audit/celery governance checks 与 diff-check 通过。

该 slice 仍只加固本地 preflight/receipt 绑定：没有创建或接线 durable publisher、authenticated
authority source、Celery beat/retry/requeue、Data Center 同 UOW、生产 PostgreSQL/VPS 观察或
delivery receipt sink；runtime 继续返回 `publisher_not_wired`，AUD-01 仍阻断，AUD-02/03
继续等待依赖。

## 实施记录（2026-08-16，AUD-01 runtime composition preflight boundary）

新增 `apps/audit/application/system_audit_runtime_composition.py`，把未来的 canonical
event/outbox coordinator、dispatch repository/UOW、durable publisher 和 server-issued scoped
authority bundle 绑定到同一 database alias。preflight 只检查注入对象的 exact contract、alias、
publisher durable preflight 与 authority selector 一致性；缺 publisher、authority、storage、
generic/memory sink 或 alias drift 均在 claim 之前以稳定 reason code fail closed，不调用 provider、
不 claim、不 publish、不打开事务。infrastructure coordinator/repository 仅公开只读 alias，
authority provider 仅公开已绑定 selector，未增加 production writer 或 runtime registry wiring。

审计单元回归 `tests/unit/audit`：`175 passed`；Black/isort、Django check、architecture/governance
与增量 mypy 通过（当前本地 Python 未安装 `ruff` 模块，未宣称 Ruff 证据）。该 slice 只是
`composition contract complete / runtime still blocked`：runtime 继续返回 `publisher_not_wired`，
没有 durable publisher/receipt sink、authenticated authority lifecycle、Celery beat/retry、
生产 PostgreSQL 投递观察或 AUD-02 同 UOW 双写；`AUD-01` 状态与 gate 不变。

该提交随后通过四条必需 CI workflow（Security Scan、Architecture Layer Guard、Consistency Check、
CI Fast Feedback，含 Python 3.11/3.13、增量质量与完整 production mypy debt ceiling）；CI 绿仅证明
本地合同和仓库门禁一致，不替代 durable publisher、authenticated authority 或生产投递证据。

## 实施记录（2026-08-18，AUD-01 authority-before-publisher preflight ordering）

收紧 `inspect_system_audit_runtime_composition()` 的检查顺序：缺失或被篡改的
server-issued scoped authority bundle 现在先于 publisher capability preflight 被拒绝，因而不会在
authority 前置条件不满足时触发未来 publisher 的外部能力检查。有效 authority 仍要求通过原有
selector/provider identity 校验；publisher 缺失继续稳定返回 `publisher_not_wired`，没有改变
runtime gate 或 claim 前阻断语义。

新增负向回归覆盖缺 authority 与 forged authority 均不调用 publisher preflight；runtime composition
focused `13 passed`。本切片只强化本地 fail-closed composition ordering，不创建 durable publisher、
authenticated authority source、Celery beat/retry、Data Center 双写或生产 PostgreSQL/VPS 证据，
因此 `AUD-01` 状态与 gate 不变，`AUD-02/03` 继续等待依赖。

## 实施记录（2026-08-19，AUD-01 runtime authority snapshot preflight）

`SystemAuditAuthorityBundleSelector` 现在集中产生 authority source identity/version；新增纯
Application `preflight_system_audit_runtime_authority()` 在未来 outbox claim 前按同一 dispatch
cutoff 读取 provider-issued snapshot，重验 canonical authority hash、active/staff/authenticated、
actor/user 与 tenant/owner scope、有效窗口，并拒绝 snapshot 的 source identity/version 替换。
该 preflight 不 claim、publish、开事务或读取 request/ORM；focused runtime/authority/composition
回归 `60 passed`，增量 mypy、Black、isort、Ruff 通过。

这只是把 authority 的当前快照与 server-issued selector 绑定到一个可调用的本地合同；尚未把它
接入 dispatcher/runtime registry，也没有 authenticated production authority lifecycle、durable
publisher/receipt sink、beat/retry/requeue、Data Center 同 UOW 双写或生产 PostgreSQL/VPS 投递证据。
`AUD-01` gate 保持阻断，`AUD-02/03` 继续等待依赖。

## 实施记录（2026-08-19，AUD-01 authority-before-claim dispatcher wiring）

`DispatchSystemAuditOutboxUseCase` 现在要求注入 server-issued authority preflight，并以 dispatch
command 的同一 `as_of` 严格执行 `authority preflight → durable publisher preflight → claim_due`。
authority 未接线、provider 异常、返回值类型替换或在该 PIT 已不可读时，dispatcher 分别以稳定
`authority_not_wired` / `authority_unavailable` 失败关闭；task 投影为 `outcome=blocked`，且
`claimed=delivered=failed=0`，不会先探测 publisher、不会 claim outbox。publisher 缺失仍保持既有
`publisher_not_wired`，没有引入 memory 或 generic-events fallback。

dispatcher/runtime/task 定向回归 `37 passed`，完整 `tests/unit/audit` 回归 `186 passed`；Ruff、
Black、isort 与增量 mypy 均通过。该切片只完成本地调用顺序和 fail-closed wiring：生产 runtime
仍没有 authenticated authority provider、durable publisher/receipt sink、beat/retry/requeue、
Data Center 同 UOW 双写或 PostgreSQL/VPS 投递证据。因此 `AUD-01` 继续保持 `active`，
`AUD-02/03` 继续等待依赖。

## 实施记录（2026-08-19，AUD-01 dispatcher 候选部署与只读观测）

包含 authority-before-claim dispatcher wiring 的不可变候选
`29cdf14206239c4b36b0d31f07980ef8b5a26855` 在四条 push CI 全部成功后，以
code-only `-Upgrade` 模式发布为 release `20260819133110`，镜像
`sha256:3748a5aa68dd919e2225894a851c41db88a49cd8b16396974bd64d77ff80a88c`。
发布前 PostgreSQL/Redis 备份完成；迁移无新增、canonical Data Center schema 无缺项、
Django deploy check、TUI registry、Qlib、Celery、容器与 TLS verifier 均通过，运行时
release manifest 与 Git commit/image 精确匹配。部署报告为
`dist/remote-build-reports/remote-build-report-20260819133110.json`。

独立公网短窗口观测中，`/api/health/` 8/8 为 HTTP `200`（约 `1.09–3.46s`），
`/api/ready/` 3/3 为 HTTP `200`（约 `4.62–9.94s`）；database、Redis、Celery、
critical data 与 Alpha/workspace consistency 为 `ok`。readiness 同时如实发布两只决策行情
超过 4 小时阈值、`must_not_use_for_decision=true`，以及 `etf_net_flow` stale / market
thermometer degraded，不把部署成功误写成决策数据新鲜。

该记录只证明 dispatcher fail-closed 代码已部署且基础运行面健康；生产 runtime 仍没有
authenticated authority provider、durable publisher/receipt sink、beat/retry/requeue、真实 outbox
claim/delivery 或 Data Center 同 UOW 双写。因此 `AUD-01` 继续 `active`，`AUD-02/03`
继续等待依赖。

## 实施记录（2026-08-20，AUD-01 当前候选只读边界复核）

当前候选 `93b12f3b8c6cc2ce59c7493ae573afa7ace796eb` 发布为 release `20260820130631` 后，
独立公网只读探针记录 `/api/health/` `200`、`/api/ready/` `200`、`/api/` `200`，
`/api/audit/health/` `200`（`overall_status=OK`、failure counter 为 `0`），以及
`/api/audit/metrics/` `200`。未认证 `/api/terminal/runs/` 为 `403`；
`/api/regime/current/` 仍为 `503`，并明确 `must_not_use_for_decision=true` 与
`decision_runtime_blocked`。

这次只读复核证明当前候选的审计健康投影、认证边界和决策 fail-closed 语义，没有改变生产状态，
也没有把 `publisher_not_wired`、空 outbox/backlog 或 metrics `200` 解释为 durable publisher、
真实 claim/delivery、authenticated scoped authority、Data Center 同 UOW 双写、PostgreSQL
并发/回滚或生产 owner/reviewer 签字。因此 `AUD-01` 仍保持 `active`，`AUD-02/03` 继续等待依赖。

## 实施记录（2026-08-21，AUD-01 current HEAD read-only acceptance）

当前已部署代码候选 `a428edaad5cf70e0c47a5649c5f867ae6aeabdd5` / release
`20260821060037` 的 authenticated read-only acceptance 同时复核了 `/api/audit/health/`
与 `/api/audit/metrics/`：两次快照均 HTTP `200`、`overall_status=OK`、累计 operation logs
`541`、failure count `0`、failure rate `0`，`pending/due/claimed/expired/failed` backlog
计数全部为 `0`。原始快照与候选、镜像、健康探针绑定在
[`tar01-current-production-acceptance-2026-08-21-head-a428edaad.json`](../deployment/tar01-current-production-acceptance-2026-08-21-head-a428edaad.json)，
其 SHA-256 为 `9360fa15e8c41348d436a50d4e475c869615e8f5873caf3385e09e965d2f2c16`。

该证据只确认当前候选的只读审计投影健康、空 backlog 和认证边界稳定；它不证明 durable
publisher/receipt sink、authenticated scoped authority、真实 outbox claim/delivery、beat/retry、
Data Center 同 UOW 双写、PostgreSQL 并发/回滚或人工 owner/reviewer 签字。`AUD-01` 继续
保持 `active`，`AUD-02/03` 继续等待依赖，生产 publisher/runtime 仍 fail-closed。

## 实施记录（2026-08-21，AUD-01 current VPS read-only probe refresh）

针对同一已部署候选 `a428edaad5cf70e0c47a5649c5f867ae6aeabdd5` / release
`20260821060037` 的新鲜只读探针显示：公网 `/api/health/`、`/api/ready/`、数据库健康、
`/api/audit/health/` 与 `/api/audit/metrics/` 均为 HTTP `200`；审计总体状态仍为 `OK`，
累计 operation logs `541`、failure `0`，pending/due/claimed/expired/failed/delivered
backlog gauges 均为 `0`。`/api/decision-ready/` 返回 `503`，明确保持 stale decision data
的 fail-closed 语义；匿名 TUI 返回 `403`。原始结构化探针见
[`tar01-current-vps-readonly-probe-2026-08-21-head-a428edaad.json`](../deployment/tar01-current-vps-readonly-probe-2026-08-21-head-a428edaad.json)，
SHA-256 为 `d3a2ac6dedb47b33fe1d76196075bbe904a06e5d972ed41e56825aec5ca87f7b`。

该刷新只证明健康投影、认证边界和决策数据 fail-closed 仍稳定；不证明 durable
publisher/receipt、authenticated authority、真实 claim/delivery、Data Center 同 UOW、
PG 并发/回滚或 owner/reviewer 签字，故 `AUD-01` 仍为 `active`。

## 实施记录（2026-08-23，AUD-01 current candidate database read-only inventory）

在同一 `4cef9040cccc2127c3f8128c8d858bc7958df2a4` / release `20260822134658` 候选上，
以 PostgreSQL 只读 `SELECT` 复核 audit `0012_systemauditevent_scope` 已应用，
`audit_system_event=0`、`audit_system_outbox=0`、outbox 各状态均为 `0`；operation log
为 `555` 条、terminal audit log 为 `134` 条。公网 `/api/audit/health/` 为 `200`，
`overall_status=OK`、failure/pending/due/claimed/expired/failed/delivered 均为 `0`。
同一工件还绑定了 health/readiness `200` 与 decision-ready `503` 的 fail-closed 响应：
[`tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json`](../deployment/tar01-p0-readonly-ledger-inventory-2026-08-23-4cef9040.json)。
SHA-256 为 `7f4e859915e7e0a8399ee75558a12e660b34ef04000f29988291f59d47eaaa55`。

这些是健康投影与空 outbox 的只读事实，不是 durable publisher、receipt sink、authenticated
scoped authority、claim/delivery、beat/retry 或 Data Center 同 UOW 双写证明；没有执行任何
生产写入、publisher 操作、迁移、fault injection、rollback 或 owner/reviewer 签字。因此
`AUD-01` 继续 `active`，`AUD-02/03` 继续等待依赖，production publisher/runtime 仍保持
fail-closed。

## 实施记录（2026-08-24，AUD-03 只读运营观察 recorder 合同）

为补齐 AUD-03 `auto_collect` 的机械采集边界，新增纯 Application parser
`apps/audit/application/aud03_operational_observation_evidence.py` 与服务器侧
`scripts/record_aud03_operational_observation_evidence.py`，输出 schema
`aud03-operational-observation-readonly.v1`。输入必须是外部候选绑定的 `select_only`
快照；每个样本重复封存 commit/version/OCI/matrix，并只允许 migration、outbox、bounded
metrics、alert codes、admin TUI status、recovery timeline/counters 与 archive hashes
白名单字段。parser 拒绝未知/敏感/raw-log 字段、候选漂移、未来或非单调时间、负数与
不一致的 outbox/recovery/archive 数据；不可用 section 必须显式 `unavailable` 并保留
reason，不把缺失指标转换为零。backlog、recovery duration、duplicate/loss 与 archive
integrity 均由已保留的 hashes/counters 派生，不能接受调用方自报 `passed`。

recorder 默认 dry-run；显式 `--write` 只在服务器侧指定的本地目录写
content-addressed append-only artifact。它不连接 publisher/authority/Celery/VPS/DB，不运行
migration、rollback、fault injection、archive/restore，不改变生产状态，报告固定
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`。
AUD focused 回归 `12 passed`，与既有 outbox observability/metrics 回归合计 `27 passed`；
Ruff/Black/isort 与增量 mypy 通过。

本切片只完成“外部运营快照 → fail-closed 观察报告”的自动采集合同，不是 AUD-03 生产
migration/rollback、backlog recovery、metrics/alert、TUI、archive/restore 或 owner/reviewer
签字验收；`AUD-03` 继续 `waiting_dependency`，`AUD-01` publisher/authority gate 与
`AUD-02` 同 UOW 双写不变。

## 实施记录（2026-08-24，AUD-03 当前部署候选只读运营观察复核）

在不重新部署、不触碰生产写入的前提下，对当前受控候选
`94abd76e46eeef4a8e21853799c7d69bcd9bbe3b` / version `20260824133504` /
OCI `sha256:1c560b5fed14964a008c278a88d9f3e3b144444a172ecc239d06cedbd76d6a3e`
执行一次低频 `select_only` 运营观察。公网 `/api/audit/health/` 于
`2026-08-24T07:36:54.575517Z` 返回 `200/OK`，operation logs=`555`、failures=`0`、
failure rate=`0`，outbox pending/due/claimed/expired/failed/delivered 全为 `0`；同一
`default` PostgreSQL alias 的只读 migration 观察为 applied=`495`、pending=`0`、
failed=`0`，migration graph SHA=`142da62cb866ee9ef2a291bd0f1f0edf527615c3d76cf15a1aae02d1cb191c2a`。

原始 envelope [`aud03-operational-observation-select-only-2026-08-24-0736.json`](../deployment/aud03-operational-observation-select-only-2026-08-24-0736.json)
经 `record_aud03_operational_observation_evidence.py --write` 生成 content-addressed report
[`00d9f623008af7d51286e6620fad6dee6e87a741f9439156d7830ab8918cee53.json`](../deployment/aud03-operational-observation/00/00d9f623008af7d51286e6620fad6dee6e87a741f9439156d7830ab8918cee53.json)。
`missing_section_count=4`：alerts、TUI、recovery、archive 仍明确为 `unavailable`，没有把缺失观测转换为零值。

本次仍未运行 migration、claim/publish、Celery、fault injection、archive/restore 或任何生产写入；报告固定
`production_claim=false`、`production_ready=false`、`runtime_enablement=not_authorized`。这只刷新当前候选的只读运行事实，
不证明 durable publisher、authenticated authority、同 UOW 双写、告警/TUI/recovery/archive 完整性或 owner/reviewer 签字；
`AUD-03` 继续 `waiting_dependency`，`AUD-01/AUD-02` 门禁不变。

## 历史记录（2026-08-24，AUD-03 旧候选 SELECT-only 运营观察）

按 active registry 的 `auto_collect` 清单，对同一运行候选
`4cef9040cccc2127c3f8128c8d858bc7958df2a4` / version `20260822134658` /
OCI revision `sha256:cfaf17560df2f85cd8ba2f5db8226a9dd9fe1cce081f30175c2a08737b4908d8`
采集一份 `select_only` envelope。VPS web 容器的同一 `default` alias
`REPEATABLE READ READ ONLY` migration 查询得到 applied=`493`、pending=`0`、failed=`0`，
有序 migration-row digest=`d540e6973cc9885c76d25450d7947da193bc706df6e51e70875f1d892d5e44cb`；
公网 `/api/audit/health/` 于 `2026-08-23T23:57:29Z` 返回 `200/OK`，operation logs=`555`、
failures=`0`、failure rate=`0`，outbox pending/due/claimed/expired/failed/delivered 全为 `0`。

原始 envelope
[`aud03-operational-observation-select-only-2026-08-24-2358.json`](../deployment/aud03-operational-observation-select-only-2026-08-24-2358.json)+经 `record_aud03_operational_observation_evidence.py --write` 生成+content-addressed report+[`56e1ef25819bc2f73df2c78975090494317f1f918bc4238a24d24ff7cec90f82.json`](../deployment/aud03-operational-observation/56/56e1ef25819bc2f73df2c78975090494317f1f918bc4238a24d24ff7cec90f82.json)。
报告 `missing_section_count=4`：alerts、TUI、recovery、archive 未采集并保持+`unavailable`，没有把缺失转成零值；migration/outbox/metrics 是可用只读字段。

本次没有运行 migration、claim/publish、Celery、fault injection、archive/restore 或任何+生产写入；报告固定 `production_claim=false`、`production_ready=false`、+`runtime_enablement=not_authorized`。这只完成一次候选绑定的运营快照派生，不能证明 durable+publisher、authenticated authority、同 UOW 双写、recovery、TUI、archive/restore 或+owner/reviewer 签字；`AUD-03` 继续 `waiting_dependency`，`AUD-01/AUD-02` 门禁不变。

## 实施记录（2026-08-26，AUD-01 MCP delivery identity repair）

将 `sdk/agomtradepro_mcp/audit.py::AuditLogger._send_audit_log()` 的投递身份生成提前到
scoped audit sink 与网络发送的共同边界：每次审计事件先生成一个 `delivery_id`，显式传入的
身份保持不变；本地嵌入式 MCP sink 与网络重试因此使用同一个可重放/幂等身份。此前只有网络
分支补充 `delivery_id`，本地 sink 可能写入没有 delivery identity 的 operation log，不能形成
完整的 final-acceptance replay 线索。

新增/调整 SDK audit contract test，`pytest sdk/tests/test_mcp/test_audit.py -q` 实际结果为
`12 passed`。该修复只补齐本地代码的 delivery identity，不创建 durable publisher、receipt
ledger、authenticated authority 或 production acceptance receipt，也不改变 terminal inline=1、
queued/worker disabled、global deny 或 decision-ready fail-closed 边界。

恢复工作包仍按以下顺序执行：先在受控候选上取得真实 durable MCP audit receipt 与 authority
证明，再完成 DATA-02 的 canonical coverage/publication/freshness 与 reconciliation，之后才由
授权 operator 做 runtime state transition，并重新执行 TAR-01 的有界 inline capacity observation。
当前 EVID-01、DATA-02/03 和 runtime state 仍不能因本地测试通过而解除。

## 实施记录（2026-08-26，AUD-01 durable delivery receipt publisher checkpoint）

新增 `apps/audit/infrastructure/system_audit_delivery_receipt.py` 与 schema-only migration
`0013_systemauditdeliveryreceipt`，形成单一 `audit-system-delivery-receipt-v1` durable sink：publisher
在写入前重验 canonical event hash/tree，以服务端 aware clock 和稳定 delivery identity 追加
append-only receipt；event/version、idempotency 与 delivery first-winner 可 exact replay，持久化行的
payload、hash、chain、sink、delivery 或 publication clock 被替换时 fail closed。Model 的 instance、
`save_base`、QuerySet/manager update/bulk/delete 与绕过 insert permit 路径均被拒绝，publisher 同时
公开只读 database alias，供后续 runtime composition 做 same-alias 绑定。Sol 审查中关闭了冲突恢复
路径在事务外调用 `select_for_update()`、base manager 绕过和 migration encoder 漂移等缺口。

聚焦 SQLite component 与 migration 验证为 `9 passed in 0.47s`；
`makemigrations audit --check --dry-run` 返回 `No changes detected`；Black、isort、Ruff、增量 mypy
（1 个 production file，`0 regressions`）、完整 mypy debt ceiling、audit/Celery contract、active-plan
registry 与全仓 architecture audit（`2964 files / 0 violations`）均通过。计划中旧的
`scripts/check_architecture.py` 已不存在，本次使用当前治理入口
`scripts/verify_architecture.py --include-audit --fail-on-audit-violations`，未把旧命令缺失误报成通过。

该 checkpoint 只关闭 durable receipt publisher 的本地仓库切片，尚未替换
`system_audit_outbox_runtime.py` 的 `publisher_not_wired` gate，也未接 Account actor authority、
owner/tenant scope、Config Center selector、Celery schedule/retry 或生产 PostgreSQL。PostgreSQL
first-winner/并发、真实 outbox claim→receipt→delivered、migration/rollback 和 owner/reviewer 证据仍
未验证；因此 `AUD-01` 保持 `active`，`AUD-02/03` 不晋级。回滚点是在 runtime 接线前移除
`0013`、receipt model/publisher 及其注册；本切片没有部署、生产写入或运行配置变化。

## 实施记录（2026-08-27，AUD-01 authority/config/runtime composition checkpoint）

完成 Account→Audit 的 actor 与 owner/tenant scope typed adapters：actor 通过
`GetCurrentAccountOwnerAssignmentActorAuthoritySourceV3` 读取 exact/current immutable source，scope
通过 `GetCurrentOwnerTenantAuthorityV1` 读取 exact/current owner/tenant authority；两者均保留 source
identity/version/content hash、actor/user、tenant/owner 与有效期，并在 stale、terminal、type substitution
或 alias 漂移时 fail closed。composition root 只接这两个 adapter，不读取 `User/Profile`、session 或
request，也不从请求本地生成 selector。

Config Center 新增三项 CRITICAL/NEXT_TASK runtime definition：`audit.system_event.mode`、
`audit.system_event.outbox_enabled`、`audit.system_event.authority_selector`，不提供 seed/default。新的
runtime loader 只接受同一 active profile 的一份 immutable snapshot，重验 profile/version、snapshot
SHA-256 与 exact six-field selector，生成绑定 snapshot/profile/environment 的 issuer identity；缺项、
跨 profile、hash 漂移或 JSON substitution 都发布稳定阻断原因，禁止独立 active-value 或环境变量回退。

新增唯一 production dispatcher composition root
`apps/audit/infrastructure/system_audit_outbox_runtime.py`：在同一
database alias 上组装 event/outbox coordinator、一个 dispatch repository、复用该 repository 的 UOW、
`audit-system-delivery-receipt-v1` publisher 和 server-issued scoped authority bundle。结构检查先验证
authority 与全部 alias，再做 durable publisher preflight；每次执行保持 authority preflight → publisher
preflight → claim 顺序。`system_audit_outbox_runtime.py` 已从永久 `publisher_not_wired` gate 改为惰性调用
该 root；Config Center 未配置、mode=`off`、outbox disabled 或 authority 不可用仍在 claim 前 blocked，
所有未知异常与非 canonical reason 均脱敏为稳定失败，不存在 generic `apps.events` 或 memory fallback。

同时补齐 publisher alias contract 与 `DjangoSystemAuditOutboxUnitOfWork`，保证 UOW 持有并顺序复用同一
repository transaction；nested、未 enter 即 exit、`atomic()`/context enter/exit 失败、伪 context 与
异常吞噬路径均有 fail-closed 测试。聚焦结果：authority adapters `18 passed`；Config Center runtime
binding/definition reconcile `40 passed`；composition/UOW `31 passed`；production runtime、task、composition
与 UOW 联合回归 `55 passed`。相关生产文件 Ruff、Black、isort 与增量 mypy 均通过，最新 runtime 集合
为 `4 source files / 0 regressions`。

本 checkpoint 尚未声称 `AUD-01` 退出：真实 SQLite outbox claim→receipt→delivered 组件链、可得的
PostgreSQL first-winner/并发证据、全量 debt/architecture/governance gates 与 migration rollback 仍待本轮
验收；生产 runtime profile/selector 数据、Celery schedule/retry、部署和生产写入均未创建或变更。
因此 registry/README 暂不晋级，`AUD-01` 保持 `active`，`AUD-02/03` 继续等待。回滚点为恢复
infrastructure runtime 的 production composition，并移除本 checkpoint 的 Account adapters、
Config Center definitions、publisher alias/UOW 接线；durable receipt schema 的独立回滚点沿用上一记录。

## 实施记录（2026-08-27，AUD-01 repository exit acceptance）

AUD-01 的退出门已闭合。默认 task/provider 入口不再永久返回 `publisher_not_wired`，而是只通过
`apps/audit/infrastructure/system_audit_outbox_runtime.py` 组装一套 production runtime：
`DjangoSystemAuditDeliveryReceiptPublisher` 是唯一 durable publisher；publisher、event/outbox
coordinator、dispatch repository 与复用该 exact repository instance 的 UOW 绑定同一 database alias；
authority selector 来自同一 Config Center immutable snapshot，actor 与 owner/tenant scope 来自 Account
自有 composition root，并在 dispatch cutoff 进行 exact-current authenticated/staff/scoped preflight。
mode/off、outbox disabled、snapshot/hash/profile 漂移、authority stale/terminal、alias 漂移或任何未知
composition failure 均在 claim 前 fail closed，公开结果只保留 canonical reason code。

最终架构复核曾真实发现 `core/integration` 新增 6 条 App Infrastructure import，未通过
`check_governance_consistency.py`。没有抬高 `governance_baseline.json`；修复为 Account 自有
`apps/account/system_audit_authority_composition.py` 负责组装本 App readers，Audit 自有 Infrastructure
负责 production dispatcher composition，`core/integration/system_audit_authority.py` 只保留 typed
adapter。修复后 governance consistency 为 `0 violations`，全仓 architecture 为 `2968 files /
0 boundary violations / 0 audit violations`。

验收证据：

- Audit/Config Center 全单元回归 `290 passed in 155.36s`；系统审计 SQLite component（含 migration、
  ledger/outbox、真实 production factory→claim→receipt→delivered 与 authority-before-claim 负向路径）
  `39 passed in 1.58s`。
- 实际 durable 链得到 `claimed=1 / delivered=1 / failed=0`，receipt 的 event/version、identity/content
  hash、stream/predecessor、idempotency 与 canonical payload 全量等于 outbox event；publisher replay
  不增行，已 delivered outbox 不再次 claim。authority 缺失时 outbox 保持 pending/attempt=0 且
  receipt=0。
- Black、isort、Ruff 对 23 个改动 Python 文件通过；11 个 production Python 文件增量 mypy 为
  `0 regressions`；full mypy debt ceiling 为 `0 errors`。
- `makemigrations audit --check --dry-run` 返回 `No changes detected`；migration forward/backward
  component 已覆盖；Celery contracts 为 91 tasks，audit event contracts 为 20 events；Celery guardrail
  `13 passed`、governance guardrail `29 passed`、active-plan registry 与 governance consistency
  均通过。
- 源码与测试静态证明 runtime 不 import `apps.events`、不构造 memory publisher，也不读取
  `User/Profile/session/request` 作为 authority fallback。

本机没有 `AGOM_AUDIT_PG_CONCURRENCY_EVIDENCE` 或专用
`AGOM_AUDIT_PG_TEST_DATABASE_URL`；现存 PostgreSQL 容器属于 TAR-02/home-lab，不具备 AUD 专用空库
授权，因此未复用、未清空，也不声称 receipt first-winner PostgreSQL 并发通过。生产 profile/selector
数据、migration/deploy、Celery schedule/retry、backlog recovery、alerts/TUI、archive/restore 与生产
签字均未创建或变更；这些证据仍由 AUD-03 的 production exit gate 管理。

机器 registry 已将 `AUD-01=completed`、`AUD-02=active` 并把唯一 repository focus 推进至 AUD-02。
回滚点为恢复 task 的 fail-closed runtime resolution，移除 Account/Audit composition、Config Center
definitions、receipt publisher/schema 与 UOW 接线；任何回滚都不得改接 generic event bus 或 memory
publisher。本轮没有 commit、push、部署、生产写入、容器创建/删除或运行配置激活。

## 实施记录（2026-08-27，AUD-02 Data Center 同 UOW 与精确回放 checkpoint）

AUD-02 已完成 Macro、Price Bar 与 Quote Snapshot 三条 canonical sync 的同事务接线：每次执行由
server-issued `run_id/ingested_run_id` 绑定 RawAudit、事实 `ingested_run_id`、CanonicalPublication、
typed SystemAuditEvent 与 outbox；任一 audit/publication 写入失败会回滚整组事实、evidence、publication、
event 和 outbox。Macro 额外通过 Config Center policy 执行独立 provider 一致性校验；failover 事件已
纠正为注册 taxonomy `started/succeeded/rejected/exhausted`，成功切换在同一 UOW 产生
`started -> succeeded`，超容差、无候选或证据不全保持 fail closed。普通 Interface、management command
和 Decision Reliability Repair 均改由 system-audited composition root 注入，不再直接构造未审计 sync。

本 checkpoint 又补出回放所需的精确身份面：`SyncResult` 在 audited success/noop 保留 run、ingested run
及 exact publication id/version/hash；system audit query 新增 staff/PIT/scoped 的 run 或 publication
单 selector 关联读取，publication 必须唯一解析一个 non-empty run，跨 scope、混 run、缺 run、未来事件或
全局顺序异常均拒绝。repository 从完整 closed-world ledger 恢复后按
`(recorded_at, stream_id, sequence_no)` 返回同一 run；RawAudit 与 CanonicalPublication 增加 exact-id
读取端口。新增 canonical `data.decision_read.recovered/blocked` 构造与 first-winner/outbox writer，读取
事件绑定 exact publication evidence，blocked 为 required/critical 且只接受稳定 reason code。

已验证证据包括：Macro failover/audited sync 单元 `24 passed`，Macro SQLite 同事务回滚/提交
`2 passed in 147.41s`；Price/Quote 聚焦联合回归此前为 `70 passed`，各自 SQLite 同事务测试均
`2 passed`，Decision Reliability Repair component `7 passed`；本次 SyncResult 身份合同 `18 passed`，
decision-read/correlation/system-audit query `42 passed`，system-audit repository component（含
publication -> full run、scope/PIT）`7 passed`。新增 decision-read/query 生产文件 Ruff 与增量 mypy为
`0 regressions`；宏观 taxonomy 修正的组件链仍保持事实、event 与 outbox 同事务。

该 checkpoint 尚未满足 AUD-02 exit gate：仍需完成 `ReplayDataChainUseCase`，以 exact RawAudit hash、
published publication hash/version/run、完整 member 集及每个事实的 `ingested_run_id` 重验持久化证据，
并要求 publication-bound decision-read 事件存在；还需用一条真实 SQLite Macro failover 链证明从
fetch/validation gate/failover/persist/publication/read 到 replay 的缺失或篡改均无 silent loss。完成后再
运行全量 audit/data-center 回归、mypy debt、architecture/governance/registry gates，并同步 registry 与
README；当前 `AUD-02` 保持 `active`，`AUD-03` 仍 `waiting_dependency`。回滚点为移除 AUD-02 三个 audited
composition root、对应 sync identity/fact 字段、Data Reliability typed writers 与关联查询；不得回退到
generic event、memory writer 或无审计直构路径。本 checkpoint 没有 commit、push、部署、生产写入或
外部调用。

## 实施记录（2026-08-27，AUD-02 publication-bound read 与垂直回放 checkpoint）

在上一 checkpoint 的精确关联查询之上，新增 fail-closed `ReplayDataChainUseCase`：以 run 或
publication 二选一 selector 读取完整 scoped/PIT correlation，逐条重验 SystemAuditEvent hash；再以
exact RawAudit id/version/hash、CanonicalPublication id/version/hash/state/run、完整 member snapshot、
重算 publication hash 及白名单事实表的 `ingested_run_id` 交叉核对专业证据。failover 允许无切换或
`started -> succeeded`，并会逐份读取和重验主数据源及独立 verification provider 的 RawAudit；缺 fetch、
published publication、publication-bound decision read、member、事实、identity 或任一 hash 漂移均失败
关闭，不把数据库的全局排序误当作业务 stage 顺序。

Decision Reliability Repair 已在 Macro、Quote batch 和逐资产 Price 的真实 freshness/coverage 复验后，
通过 canonical writer 记录 `data.decision_read.recovered/blocked`。事件精确复用 SyncResult 的 run、
ingested run、publication id/version/hash 与 provider，blocked 只写稳定治理 reason，不写同步异常或
provider payload；writer/identity 缺失使对应 repair section fail closed。Interface 与 management command
均从唯一 composition root 注入 recorder，未新增 memory 或 best-effort fallback。

聚焦验证：decision-read recorder `16 passed`；repair use case `37 passed`，runtime/recorder 联合单元
`35 passed`，repair command component `7 passed in 137.66s`；replay unit（含双 fetch verification）
`26 passed`，真实 ORM fact evidence component `5 passed in 151.32s`。Macro SQLite 垂直链在一次测试中
贯通双源 fetch、failover started/succeeded、fact/RawAudit/publication/member、decision read、6 组
event/outbox 与 publication-selector replay，完整 transaction 文件 `2 passed in 148.72s`。本切片生产
文件 Ruff、Black/isort 与增量 mypy 均为 `0 regressions`。

AUD-02 仍保持 `active`：M2 的 Provider Health/circuit opened/recovered、repair completed parent-run
evidence，以及 freshness/quality/conflict/rollback 等登记状态时间线尚未完成；治理 registry 也不能在
全量 audit/data-center、mypy debt、architecture/governance gates 通过前晋级。下一切片先闭合 provider
circuit/recovery 与 repair-run 事件/回放，再按 registry exit 区分硬阻断和后续 supporting event，禁止把
当前 publication replay 证据扩大解释为整个 M2 完成。本 checkpoint 没有 commit、push、部署、生产写入、
容器或网络操作。

## 实施记录（2026-08-27，AUD-02 Provider Health 与 repair parent-run checkpoint）

Provider Registry 的运行时状态边沿已接入 canonical ledger：只有 healthy/degraded 到 circuit-open 和
degraded/circuit-open 到 healthy 两种已登记跃迁分别产生 `data.provider.circuit_opened` 与
`data.provider.recovered`。事件复用触发该跃迁的 Sync `run_id/ingested_run_id`，引用经脱敏并做 SHA-256
封存的 provider/capability/dataset health snapshot；凭据、provider 异常文本与原始 payload 均不进入
evidence。Macro、Price 与 Quote 的 success/failure/validation/failover health 记录均在原 Sync UOW 内
传递精确身份，writer 缺失或跃迁发生却没有 identity 时失败关闭。真实 Macro SQLite 链预置 degraded
状态后恢复，在 fact、RawAudit、publication、failover、decision-read 同一事务中增加 provider recovered
event/outbox；失败注入仍回滚全部参与者。

Decision Reliability Repair 现先在短事务中持久化 dataset=`decision.reliability.repair`、
provider=`data-center-repair` 的 canonical parent identity，再运行四个 section；结束时把 section
status、`must_not_use_for_decision`、剩余 blocker 数量及所有实际 child SyncResult 的 exact publication
id/version/hash/dataset 去重、排序，写入 REQUIRED `data.repair.completed`。报告公开 parent run、ingested
run、identity hash 与 publication ids；SUCCESS/PARTIAL/FAILED 由四个 section 的稳定状态派生，identity
issuer、UOW 或 audit writer 的替换/失败均不被吞掉。新增 `ReplayRepairRunUseCase` 以 repair run selector
重验 parent event/hash/scope/PIT、持久化 SyncExecutionIdentity 与每个 publication evidence，再逐一调用
`ReplayDataChainUseCase`；任何 child id/version/hash/dataset、RawAudit、member、fact ingestion 或
decision-read 漂移都会关闭整次 parent replay。SUCCESS 缺 publication 被视为损坏，PARTIAL/FAILED 可在
保留 parent outcome 的情况下重放零 child。

聚焦验证：Provider Health/event/runtime 与 audited Sync 联合 `53 passed`，新增真实 Sync 边沿文件
`10 passed`；repair parent event `15 passed`、repair 编排 `43 passed`、parent/child replay 联合
`42 passed`、production runtime composition `19 passed`、management command component
`7 passed in 138.19s`。更新后的 Macro SQLite 垂直链包含双源 fetch、failover、persist/publication、
provider recovery、decision read、repair parent 与按 repair run 的 child replay，共 `8` 组 event/outbox；
事务文件 `2 passed in 142.39s`。相关生产切片 Ruff、Black/isort 通过；repair runtime 10 个 production
files 与 replay 2 个 production files 的增量 mypy 均为 `0 regressions`。

AUD-02 仍不晋级：M2 登记表中的 freshness/quality/conflict/rollback 时间线，以及 failover exhausted 在
所有实际耗尽分支的覆盖仍需逐项核对和闭合；之后还必须运行全量 audit/data-center、mypy debt、
architecture、governance 与 registry gates。回滚点为 repair parent identity/event/replay composition、
provider health writer 及 Sync UOW 注入；不得回退到 memory/best-effort writer 或无 identity 事件。本
checkpoint 没有 commit、push、部署、生产写入、容器或网络操作。

## 实施记录（2026-08-27，AUD-02 failover exhaustion 与 freshness timeline checkpoint）

Macro failover 已补齐此前会静默抛错的真实耗尽分支：零 active provider、primary 与所有 fallback
prepare 失败、以及所有 provider 返回空结果后无候选，都会在返回原有失败语义前，以独立 server-issued
sync identity 写入一份聚合 RawAudit、`data.fetch.failed`、`data.failover.started` 与 REQUIRED/CRITICAL
`data.failover.exhausted`。聚合 evidence 只保存 indicator/window、尝试 provider 名称与数量及稳定
`ProviderCandidatesExhausted` 类别，不保存异常文本、凭据或 payload；四者在同一 sync UOW 中提交，required
writer 失败触发回滚。单候选缺独立验证与双候选缺比较证据仍沿用已有 exact prepared RawAudit 路径，超
容差仍为 rejected，不把业务冲突误报为 exhausted。批处理契约 `8 passed`，failover/audited sync/replay
联合 `62 passed`；真实 SQLite exhaustion 链验证 1 份 identity/RawAudit 与 3 组 event/outbox 的 run、
ingested run、evidence hash 及 predecessor 均一致，`1 passed in 139.38s`。

publication-bound decision read 现同时驱动独立 `data.freshness.changed` 时间线。事件引用 exact canonical
publication id/version/hash，首次状态以前态 `unknown` 建链；后续仅在 freshness status、
`must_not_use_for_decision` 或稳定 blocked reason 实际变化时追加，并保留前态/当前态，未变化不重复写。
freshness writer 失败会阻止 decision-read writer 继续执行；新事件存在时 `ReplayDataChainUseCase` 会交叉
核对 publication evidence、freshness 状态、blocked/recovered outcome 与 decision-read，任一漂移均失败
关闭；历史链缺该新事件仍可回放。事件/recorder/runtime/replay 聚焦回归 `86 passed` 与 replay 联合
`45 passed`，相关 production mypy 均为 `0 regressions`；更新后的真实 Macro repair-run 纵向链包含
freshness event/outbox，`1 passed in 142.50s`。

AUD-02 继续保持 `active`：M2 明示的 conflict detected/resolved 时间线仍未闭合，quality 与 publication
rollback 登记事件需按退出语义完成或形成明确 supporting 处置；完成后还需运行全量 audit/data-center、
mypy debt、architecture、governance 与 registry gates。下一切片以 immutable reconciliation evidence
作为 conflict 专业证据闭合 detected→resolved 转换及同事务失败回滚，不用 failover succeeded 伪装
conflict resolved。本 checkpoint 没有 commit、push、部署、生产写入、容器或网络操作。

## 实施记录（2026-08-27，AUD-02 reconciliation conflict lifecycle checkpoint）

Reconciliation 的 `semantic_conflict` 状态已接入 canonical ledger。维护入口不再只保存一份孤立的
`ReconciliationEvidence`：Application 先在同一个外层 Django transaction 中锁定该 dataset 的最新
evidence，追加当前 immutable evidence，再从持久化后 domain representation 计算 canonical JSON
SHA-256；只有 clean/unknown→semantic conflict 与 semantic conflict→clean 两种真实边沿分别产生
`data.conflict.detected` 和 REQUIRED `data.conflict.resolved`。连续 conflict、连续 clean 与 exact retry
不制造重复状态事件；`data_missing`、`code_defect` 和 expected difference 不被伪装为 semantic conflict。

两类事件均引用当前 reconciliation evidence 的 exact id/version/content hash；存在前态时同时引用前一份
evidence 及其 hash，并在 dataset stream 上保存 sequence/predecessor。repository、conflict writer 与 UOW
必须使用同一 database alias；canonical writer、authority scope 或 outbox 失败都会传播并回滚 evidence，
公开 management/application 入口只从 production composition root 取得该组合。事件 detail 只包含稳定状态、
计数与 evidence 标识/摘要，不包含 snapshot payload、异常文本或凭据。

聚焦验证：conflict event contract 与 runtime authority/alias `12 passed`；reconciliation evidence、命令入口、
detected/resolved、重复状态抑制和 writer-failure rollback `8 passed in 138.61s`；真实 SQLite
detected→resolved 链已验证 2 份 evidence、2 组 event/outbox、精确内容 hash、scope 与 predecessor，成功用例
在 component run 中通过，outbox failure 回滚用例修正测试异常边界后 `1 passed in 145.53s`。8 个相关
production Python 文件增量 mypy 为 `0 regressions`，Black/isort 已执行。

AUD-02 继续保持 `active`，不会因 conflict 子链通过而提前晋级。只读盘点确认下一切片先接入唯一 owner
`RollbackCanonicalPublicationUseCase` 的 `data.publication.rolled_back` 同事务事件与 rollback evidence，
随后再为 `data.quality.changed` 定义不混用 freshness/reconciliation 的真实质量状态边沿；两项完成后仍需
全量 audit/data-center、mypy debt、architecture、governance 与 registry gates。回滚点为移除 conflict
writer/runtime factory 与 reconciliation 外层 UOW 接线，恢复原 evidence-only use case；不得保留事件而
放弃同事务回滚。本 checkpoint 没有 commit、push、部署、生产写入、容器或网络操作。

## 实施记录（2026-08-27，AUD-02 publication rollback lifecycle checkpoint）

唯一 Application owner `RollbackCanonicalPublicationUseCase` 现由 production composition 注入 canonical
rollback writer、同 alias 外层 UOW 与 server clock。repository 仍在事务内锁定 target/current、校验
publication/member/coverage/time evidence，并执行 current→superseded、target→published/reinstated；新增
显式 `rollback_id` 后，exact retry 只有在 request evidence 与当前结果完全一致时才可重放，身份复用或状态已
再次变化会失败关闭。Application 随后读取持久 rollback row 与前后 publication，任一替换、缺失、无 run、
非 SHA-256 publication hash 或 required audit/outbox 失败都会使整组状态更新和 rollback row 回滚。

新增 `data.publication.rolled_back` canonical writer 使用 REQUIRED/WARNING/ROLLED_BACK taxonomy，在既有
`data.publication:{dataset}` stream 上执行 first-winner 与 predecessor CAS。事件 correlations 绑定 target
publication、dataset、target run 与 rollback evidence；三份 evidence refs 分别绑定被恢复 publication、
rollback row 和被替换 publication 的 exact id/version/content hash。rollback row 的 canonical hash 覆盖
target/previous IDs、reason、operator 与 observed time，但自由文本 reason/operator 不进入 event detail；actor
与 owner/tenant scope 仍由 server authority 提供，未把命令参数伪装为 authenticated actor。

`ReplayDataChainUseCase` 在存在 rollback event 时，会读取并重算 rollback row hash，重验目标与前序
publication 的 id/version/hash/dataset/key/state、event resource/correlations/detail/taxonomy，并返回有序
`rollback_ids`；缺行、hash 漂移、前序 publication 缺失或 event 引用漂移均分别以 unavailable/corruption
失败关闭。历史无 rollback 事件的链继续兼容。

聚焦验证：Application/repository rollback 成功、非法目标与 audit failure 原子回滚 `3 passed in 138.16s`；
真实 SQLite 以 2 份 publication/member/coverage 为输入，验证 rollback row、三份 exact evidence、event/outbox、
authority scope、exact retry 与 outbox failure 全回滚，`2 passed in 139.09s`。格式化后 rollback event/runtime
和完整 replay 联合 `46 passed`；相关 10 个 production files 及 replay/control-plane 切片增量 mypy 均为
`0 regressions`。

AUD-02 仍为 `active`。下一切片只处理剩余 `data.quality.changed`：先从 publication member snapshot 定义
可复现的整体质量 evidence 与状态归约，再接入现有 publication 同事务，不把 freshness、conflict 或单个
provider 字段混成质量状态。完成 quality 后才运行全量 audit/data-center、mypy debt、architecture、
governance 与 registry gates，并据真实结果决定 AUD-02 是否满足退出门。回滚点为恢复原 unaudited rollback
composition、移除 rollback writer/evidence replay 与显式 retry 接线；不得保留可见状态切换而丢弃 required
audit。本 checkpoint 没有 commit、push、部署、生产写入、容器或网络操作。

## 实施记录（2026-08-27，AUD-02 repository exit acceptance）

AUD-02 的 Data Reliability 纵向链已达到 repository exit gate。Macro、Price Bar 与 Quote Snapshot
现在都由 server-issued `run_id/ingested_run_id` 贯穿 fetch、validation、failover、fact/RawAudit
persistence、Canonical Publication/member、typed SystemAuditEvent 与 outbox，并在同一 database alias、
同一外层 UOW 中提交；required writer、publication、quality 或 outbox 任一步失败都会回滚整组参与者。
普通 Interface、management command 与 Decision Reliability Repair 只从 system-audited composition root
取得这三条同步链，治理页面的纯 canonicalize 动作则惰性构造 sync runner，不再无关地要求生产审计
runtime 配置，真实同步动作仍保持 fail closed。

最后一条 `data.quality.changed` 子链从持久 Canonical Publication 的完整 member snapshot 重建并校验
publication id/version/hash、member count、唯一 natural key/fact reference 与 provider。`valid/accepted/verified`
显式归约为 `accepted`，`estimated/error/missing/available_at_unverified` 归约为 `degraded`；`stale` 被拒绝为
freshness 语义，未知或空值失败关闭。初始 accepted 不制造事件，初始 degraded 产生 DETECTED，degraded 到
accepted 产生 RECOVERED，同状态不重复写。事件与 outbox 精确引用 publication evidence；质量 writer 失败
会回滚 fact、identity、RawAudit、publication/member/coverage 及全部事件。回放会重算同一 member/hash 投影，
degraded snapshot 缺少质量事件视为 silent loss 并拒绝；历史 accepted 链仍可兼容回放。

最终治理复核还关闭了两个真实回归：`sync_use_cases.py` 曾增至 2167 个非空行，现将 Macro/failover/batch
机械拆到 `sync_macro_use_cases.py`，兼容 façade 保留旧导入路径，两文件分别为 1119/1107 个非空行；
current-data manifest 从旧的直接 publisher 字符串迁到 Macro/Price/Quote audited composition、quality recorder、
same-UOW component 证据。20 个冻结的 Data Reliability 事件均已有 canonical typed writer、运行接线与测试，
因此一次性把 audit event registry 从 `shadow/registry_only + planned/not_wired` 晋级为
`active/wired`；其余 6 个 inventory-only category 继续 pending，不把它们伪装为已实施。

最终验收证据：

- `pytest tests/unit/audit tests/unit/data_center -q`：`1449 passed in 284.22s`。
- `pytest tests/component/audit tests/component/data_center -q`：`231 passed, 8 skipped in 273.12s`；8 个 skip
  均为需要显式 PostgreSQL 测试环境的 opt-in 路径，本轮没有借用或清空现有数据库。
- Black、isort、Ruff 与 `git diff --check` 通过；全部 59 个改动 production Python 文件增量 mypy 为
  `0 regressions / 0 legacy errors`，full mypy debt ceiling 为 `0 errors`。
- 增量与完整 architecture 均扫描 2987 个文件、`0 boundary violations`；governance consistency
  `0 violations`；Celery contracts 为 91 tasks，current-data contracts 为 50 surfaces，audit event contracts
  为 20 events 且 `active/wired`；对应 registry 单元 `5 passed`。
- `makemigrations audit data_center --check --dry-run` 返回 `No changes detected`。migration graph 命令因本地
  未设置专用 `DATABASE_URL` 明确 unavailable；未回退到生产连接，也不把该项写成通过。

据此，`AUD-02=completed`；依赖解除后的 `AUD-03` 进入 `awaiting_production`，只允许继续其声明的
candidate-bound read-only auto-collect。production migration/rollback、fault injection、archive/restore、部署、
运行配置激活与 owner/reviewer 签字仍未执行，必须保留授权边界。按滚动排期，下一条唯一 repository focus
转为 `TUX-04`，不与 AUD-03 形成第二条仓库主线。

回滚点为撤销 Macro 模块拆分兼容 façade、quality recorder/writer、三条 audited composition/UOW 注入与
Data Reliability typed writer/replay 接线，并把 20 项事件 registry 恢复为 shadow；任何回滚不得恢复
memory/generic-event fallback、无 identity 事件或事实与审计分事务写入。本轮因用户已有改动与
`docs/plans/README.md` 重叠，按 Goal 合同不自动 commit；没有 push、部署、生产/外部写入、容器操作或
付费调用。

## 实施记录（2026-08-28，AUD-02 完整 current-data 回归重新打开）

TUX-05 为验证 freshness presentation 将 `run_current_data_contract_tests.py` 改为 Windows-safe 的 28,000
字符顺序分批，首次使当前平台可以启动全部登记 nodeid。首批 242 个登记 nodeid 展开为 300 项后得到
`268 passed / 29 failed / 3 errors`，runner 按 fail-fast 未执行余下 55 个；随后 TUX-05 新增的 4 个
operator freshness nodeid 独立 `4 passed`。失败集中在既有 Equity repository/API/intraday 与 Account
exchange-rate 读取：AUD-02 的 system-audited Data Center composition 在只读断言前 eager 构造 writer，
因测试运行配置未物化 `audit.system_event.mode`、`audit.system_event.outbox_enabled`、
`audit.system_event.authority_selector` 而抛出 `SystemAuditCompositionUnavailable` 或 runtime profile
critical-definition 错误。真实迁移路径单例复核仍同样失败，因此不能归咎于 `--no-migrations`。

该证据推翻了上一节“完整 repository regression 已闭合”的范围判断：当时 1449 个 Audit/Data Center unit
和 231 个 component 未覆盖这些跨 App 现有 consumers。机器注册表据此把 `AUD-02` 从 `completed` 纠正为
`active`，`AUD-03` 回到 `waiting_dependency`，且不创建新的临时 unit。下一切片先确认 audited sync 的
writer composition 是否应在真实写动作前惰性取得，以及 Account 测试 runtime patch 应在哪个 owner 边界
补齐完整 critical profile；必须以失败测试锁定“只读不被无关 writer 配置阻断、真实审计写仍 fail closed”，
不得增加 production fallback、全局 test-only 逃逸或伪造 authority。完成后运行全部 298 个登记 nodeid、
原 AUD-02 Audit/Data Center 包、增量 mypy/debt、architecture/governance/registry gates，再决定是否重新
完成 AUD-02。本 checkpoint 未部署、未写生产、未激活 runtime profile、未运行故障注入或付费调用。

## 实施记录（2026-08-28，AUD-02 corrective repository exit）

纠偏切片将读写组合边界收回 Data Center owner：`OnDemandDataCenterService` 改为接收四个 typed sync
factory，composition root 只传 callable，纯读 `assess_*` 与 Equity repository/API/intraday 构造不再
提前加载 audit writer；只有真正 hydration 才在既有 provider guard 内解析 factory。factory 缺少 critical
Audit runtime 时只产生 `provider_failed`、零记录和稳定错误类型，显式 sync composition 仍由原
`make_system_audited_sync_*` 合同 fail closed，没有新增 production default/fallback。Account 汇率链
本身不依赖 Audit writer；其独立错误由测试 runtime helper 显式补齐 mode=`off`、outbox=`false` 和
typed authority selector 后关闭，未建立全局 fixture 或伪造生产 authority。

验证先完成 On-Demand `9 passed`，再覆盖完整 Equity repository/intraday/API、Account API 与汇率边界
`154 passed in 87.53s`。Windows-safe full registry 在保留真实迁移的最终口径下执行全部 298 个登记
nodeid：第一批 243 个展开为 `301 passed in 206.17s`，第二批 `55 passed in 157.78s`。诊断性
`--no-migrations` 运行只剩 Risk Center 一项 missing seed；该节点启用真实迁移后 `1 passed`，证明
0004/0006 seed 是该合同的一部分，最终验收不得禁用迁移。原 AUD-02 回归重新执行为 Audit/Data Center
unit `1449 passed in 164.18s`、component `231 passed, 8 skipped in 205.61s`；8 项仍是需要专用
PostgreSQL 测试库的 opt-in，不写成通过。

增量 mypy 为 `0 regressions / 0 legacy errors`，full debt ceiling `0 errors`；2987 个生产文件完整
architecture 为 boundary/audit `0/0`，audit/current-data/Celery contracts 分别为 `20/51/91`，
governance `0 violations`，migration dry-run `No changes detected`，Django check、Black、isort、
Ruff 与 diff whitespace 全绿。规范化证据见
[`aud02-corrective-repository-closure-evidence-2026-08-28.json`](../testing/aud02-corrective-repository-closure-evidence-2026-08-28.json)。

据此 `AUD-02` 再次满足 repository exit，`AUD-03` 可回到 `awaiting_production`；但 production
migration/rollback、backlog recovery、alerts/TUI、archive/restore、PostgreSQL opt-in 与双签均仍未完成。
剩余唯一 repository unit `EVID-03` 继续等待 `EVID-01/02` 的真实生产验收，没有 dependency-ready 的
repository unit。为忠实执行 Goal 停止规则，registry 允许 `execution_focus.unit_id=null`，但仅在零
active 且零依赖已满足 repository unit 时通过；任何可执行仓库单元出现时仍 fail closed。回滚点为恢复
旧 eager injection、显式测试 profile seed 和 null-focus validator 合同；不得以恢复 raw Audit fallback、
关闭 current-data 测试或激活被阻断单元替代回滚。本轮没有部署、生产写、runtime 激活、外部/付费调用或
人工签字。
