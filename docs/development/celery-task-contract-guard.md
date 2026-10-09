# Celery 关键任务契约护栏

> 生效日期：2026-07-24
> 适用范围：直接影响数据新鲜度、批量数据写入或下游业务闸门的 Celery 任务

## 目标

2026-09-19 全市场刷新：`refresh_full_market_publications_task` 冻结有效 A 股范围，分批执行带审计的 quote/valuation fact-only 同步。全部批次成功且快照、估值源日期等于最近完成交易日后，才原子发布整个 quote/valuation/price 范围；独立财报缺少可用时间不再阻止市场数据发布。日线保留停牌股票真实末次观测，不填充价格，发布成功不表示所有成员可用于决策。计数单位为同步/发布操作，`stored` 为报价/估值事实行（不含日线补录量），部分同步或发布失败必须为 partial/failed，禁止发布中间批次。生产定时在推理前刷新快照并经过中台补录/校验当日日线后发布；`price_scope_verified` 和 `suspended_codes` 单独记录验证范围。

2026-09-26 分母护栏：刷新后的 `active_count` 和规范代码集合 SHA-256 必须与冻结集合精确一致；valuation seed 的返回身份和成功身份必须覆盖完整冻结集合。Provider 未返回证券只能形成 `CURRENT_VALUATION_SCOPE_INCOMPLETE` 阻断和缺失清单，不能自动归类为停牌、未上市或“非交易”，也不能把缩小后的集合传给正式 Publication。显式排除必须另有可验证的交易状态或上市状态证据并进入治理策略。

2026-09-26 财报续批租约：运行互斥使用带 workflow owner 的短租约，TTL 仅覆盖单批任务预算并由同 owner 续租；可恢复 checkpoint 使用独立保留期。`SoftTimeLimitExceeded`、续批 broker 投递失败和 owner 丢失必须返回稳定业务结果并释放当前 owner 的租约，broker 失败仍保留已完成 offset 供新 workflow 恢复。不得把七天 checkpoint 保留期当作运行锁 TTL；测试必须注入隔离 cache，禁止连接生产 Redis。

2026-09-19 Alpha scoped 定时入口：额度耗尽、模型行情契约阻断、刷新返回 failed/blocked 或目标日覆盖不足时，父任务直接发布 blocked、零写入并停止投递子推理，避免各组合重复刷新。普通瞬时异常仍保留既有通用推理重试路径。详见 [排查记录](../reviews/vps-alpha-auto-refresh-2026-09-19.md)。

2026-09-25 Alpha 推理后置工作区同步：评分缓存和账户推荐刷新是两个独立阶段。评分已写入后，交易日历不可用或推荐刷新失败不得重试整段推理；结果必须保留缓存写入成功，发布 `outcome=partial`、两阶段计数、稳定错误码和安全提示，供 Task Monitor 与 Alpha 页面展示。

2026-09-09 Alpha 额度耗尽处理：Qlib builder 遇到 `token daily limit exceeded`
立即抛出 `TUSHARE_DAILY_QUOTA_EXHAUSTED`，停止未开始的并发请求；推理任务发布
`blocked`、`stored=0`，不重试推理或改写缓存。若其他刷新失败导致使用旧交易日，
缓存标为 `degraded`，任务发布 `partial`，阻断下游推荐刷新。

防止以下故障再次进入生产：

- beat、CLI 或其他任务绕过 HTTP Serializer，把非法参数传入任务；
- 循环中每只股票都失败，但任务仍返回 `success=true`；
- “请求了多少股票”“成功了多少股票”“写入了多少记录”混用同一计数；
- 零写入、部分失败和业务阻断都被包装成普通成功；
- Celery 状态为 `SUCCESS` 时，监控忽略返回载荷中的业务失败。

## 结果契约

关键任务的返回载荷必须包含 `outcome`：

| outcome | 含义 | 兼容字段 `success` |
|---|---|---|
| `success` | 请求范围全部完成，且达到任务定义的有效产出 | `true` |
| `partial` | 至少一个项目成功且至少一个项目失败 | `true` |
| `noop` | 合法执行，但没有产生写入或状态变化 | `true` |
| `blocked` | 被明确业务闸门阻止，未继续下游动作 | 按现有 API 兼容口径 |
| `failed` | 输入非法、依赖不可用、全部项目失败或必要产出为零 | `false` |

`success` 仅为兼容字段。Task Monitor、指标、告警和新调用方以 `outcome` 为准。

批量任务还应使用同一统计单位发布以下计数：

- `requested_*_count`：实际进入本次批处理范围的对象数；
- `succeeded_*_count`：业务处理成功的对象数；
- `failed_*_count`：业务处理失败的对象数；
- `stored_record_count`：实际落库记录数。

如果对象计数和记录计数不是同一单位，字段名必须明确区分，不得使用含糊的 `count`。

## 边界校验

校验必须放在 Celery/Application 入口，先于 Repository、Provider 和外部 API 调用。至少覆盖：

- 数值范围与 Python `bool` 冒充整数；
- 枚举值，例如数据源；
- 股票代码格式、空字符串和空列表语义；
- 批量数量上限；
- `None` 表示默认范围时的明确行为。

Interface Serializer 可重复提供更友好的 HTTP 错误，但不能作为唯一防线。

## 失败矩阵

新增或修改关键任务时，应按适用性覆盖：

1. `invalid_input`
2. `all_success`
3. `partial_failure`
4. `complete_failure`
5. `zero_output`
6. `blocked`

“按适用性”以任务当前允许的行为为准。永久 fail-closed 的兼容入口不应登记
`all_success`、`partial_failure`、`complete_failure` 或 `zero_output` 来代表它不再允许的旧路径；
应登记其真实 `invalid_input` 与 `blocked` 契约，并由受控的新任务登记其实际成功/部分失败场景。
例如 `equity.sync_financial_data_task` 仅允许校验参数，合法范围也必须在访问 Repository、Provider
前返回 `FINANCIAL_CAPACITY_RECEIPT_REQUIRED`。其 blocked 测试同时覆盖默认全市场范围与显式证券范围。

每项证据必须是具体测试函数，不接受只登记测试文件。登记真源为
`governance/celery_task_contracts.json`。

示例：

```json
{
  "task_path": "apps.example.application.tasks.sync_data_task",
  "source_file": "apps/example/application/tasks.py",
  "criticality": "freshness_critical",
  "required_cases": {
    "invalid_input": {
      "test_file": "tests/unit/example/test_tasks.py",
      "test_function": "test_sync_data_task_rejects_invalid_days"
    },
    "complete_failure": {
      "test_file": "tests/unit/example/test_tasks.py",
      "test_function": "test_sync_data_task_reports_complete_failure"
    }
  }
}
```

将文件加入 `governed_source_files` 后，该文件内每个 `@shared_task` 都必须登记。CI
还会比较基准提交与当前提交：任何 Application 层新增的 `@shared_task`，即使源文件尚未
加入治理列表，也必须先登记。

## 运行时闭环

`shared.domain.task_outcomes` 是任务业务结果的统一解释器：

- Task Monitor 在 Celery `task_postrun` 时检查返回载荷；业务 `failed` 会记录为任务失败；
- Prometheus 指标使用 `success / partial / noop / blocked / failed` 标签；
- 老任务没有结构化返回载荷时暂按历史成功口径处理，迁移后应显式发布 `outcome`。

## Task Monitor orphan reconciliation

`cleanup_old_task_records` 每日维护时可协调已开始但遗失终态信号的任务。普通 HTTP GET、页面查询和 MCP 查询保持只读，不得触发协调。保留期清理不能将旧 `pending` 或 `started` 行直接改成 timeout；`pending` 的 Celery `PENDING` 状态无法区分仍在 broker 排队与任务已遗失，因此不推断其为 orphan。

只评估有当前 `attempt_id`、worker identity、首次尝试（`retries=0`）和 aware `started_at` 的 `started` 行。任务必须超过其注册 hard time limit、broker `visibility_timeout` 与默认 300 秒 grace 之和；可用 `TASK_MONITOR_ORPHAN_GRACE_SECONDS` 调整 grace，范围为 0–3600 秒。每轮只读快照必须覆盖全部配置队列的 passive ready 数，以及 worker ping、active、reserved、scheduled；worker 响应集合须一致，所有 ready 队列合计必须为零，且任务 ID 不得出现在任何 worker 列表中。Celery backend 的终态阻止 timeout；`PENDING`、`STARTED`、`RETRY` 或 `UNKNOWN` 只能作为非终态证据使用，backend 查询失败或状态无法识别时保留原行。

候选记录的原 worker 必须不在当前 worker 响应集合内；任务专属 domain lease 必须明确 absent，cache 不可用或 owner 输入缺失时保留原行。金融续批 lease 按记录中的 `workflow_id` 精确查验；全市场刷新检查 task-wide lease key。无 domain lease 声明的任务记录为 `not_required`。任何运行中、排队中、ready queue 非空、证据不完整或第 1 次以外的尝试都不做状态转换。

`data_center.refresh_financial_publication_capacity` 使用持久 workflow checkpoint 作为只读 domain lease 真源。完整且未过期的 in-flight slice claim 是 `active`；checkpoint 缺失或不可读、running 状态缺少 claim、claim 过期/不完整，以及任一 `*_outcome_indeterminate` 状态都为 `unknown`，必须保留 Task Monitor 原行。只有校验通过、没有 claim 且带有效完成时间的 workflow 终态 checkpoint 才是 `absent`。此规则不改变兼容任务 `data_center.refresh_financial_publications_batch` 的精确 cache owner 检查。

最终写入使用单条条件更新，同时匹配原 `status=started` 和 `attempt_id`。终态事件或新尝试先到时，CAS 失败。只有确认 orphan 后才写 `timeout`、稳定码 `TASK_ORPHAN_TIMEOUT` 和 `task_monitor_orphan_v1` 安全证据；证据不含任务参数、结果、worker 名称或 lease owner。超时结果保留规范 `outcome=failed`，`requested/succeeded/failed/stored` 均为 `null` 并标记 `counts_unavailable=true`，不虚构业务计数。相关反例与并发测试登记在 `governance/celery_task_contracts.json` 的 Task Monitor cleanup 覆盖说明中。

## 开发与验收命令

```bash
python scripts/check_celery_task_contracts.py
pytest tests/guardrails/test_celery_task_contracts.py -q
pytest tests/unit/ci/test_check_celery_task_contracts.py -q
```

CI 使用差异模式：

```bash
python scripts/check_celery_task_contracts.py \
  --base-ref <base-ref> \
  --head-ref <head-ref>
```

代码评审时还需确认：任务结果是否能让调用方区分“全成功、部分成功、无操作、被阻断和
失败”，以及告警是否会在“函数正常返回但业务失败”时触发。


### 2026-09-09 Qlib 中台数据阻断

`qlib_predict_scores` 的 blocked 用例同时覆盖额度耗尽和 `MODEL_MARKET_*`（过期、切源冲突、参考不足、配置缺失）；均必须 `stored=0`，不得执行预测或写评分缓存。复用 manifest 中该任务的 blocked 用例并参数化测试；详细边界见 [模型行情中台改造](../plans/model-market-data-center-routing-2026-09-09.md)。

2026-09-19 停牌恢复：刷新 summary 发布 suspended_codes 与 warning_messages，stock_count 只计实际构建标的。有逐日全天停牌证据的标的不产生合成行情或评分；未知滞后仍阻断，不能以停牌分支吞掉其他 DataFetchError。

2026-09-19：qlib_predict_scores 执行预测遇到 MODEL_MARKET_* 数据质量/范围错误时，发布 blocked、requested=1/succeeded=0/failed=1/stored=0 和稳定 blocked_reason，禁止进入旧缓存复用分支。账户 scope 缺少目标日模型数据不得静默缩小范围。

2026-09-19：`data_center.refresh_full_market_publications` 冻结有效 A 股全集，按批刷新报价与估值事实；任何批次不完整均保留原 Publication。全部事实齐备且源观测日匹配最近完成交易日后才发布报价、估值、日线全集。停牌日线保留实际日期，财报发布仍独立校验。`setup_full_market_publications` 幂等配置工作日 17:05（项目时区）的 Beat 任务，可用参数调整或禁用；该时间晚于 Tushare `daily_basic` 官方 15:00～17:00 更新窗口，不能在数据源尚未形成当日完整截面时发布前一日数据冒充当期。审计配置/服务身份不可用时，在任何行情请求和写入前返回 `outcome=blocked`、`stored=0` 及稳定原因；不得以关闭审计、空 writer 或临时管理员身份作为恢复措施。

2026-09-27 审计 authority 复验容错：全市场长任务与每 15 分钟续租守卫并发时，
只允许对稳定码 `system_audit_authority_unavailable` 做最多六次有界重读；每次使用新的 UTC
时刻重新验证剩余授权窗口。actor、user、tenant、owner、认证/职员状态、role、来源身份或
有效期真实变化不得重试放行。重读耗尽后立即停止剩余批次，把未执行操作计入失败并只保留
一次稳定根因；禁止把同一 authority 阻断复制成全 universe 异常列表。

2026-09-20 合并前维护：Alpha 的数据阻断结果和旧源评分标记由 `task_outcome_contracts` 统一生成，任务入口及原有 outcome、计数和阻断原因保持不变。

2026-09-24 Tushare 全市场估值修复：`daily_basic.total_mv/circ_mv` 的原始单位为“万元”，Provider 适配器必须在进入 Domain 前转换为存储规范“元”，并在 `extra` 保留原始单位、规范单位和 `10000` 转换倍数；迁移 `data_center.0084` 同步修复既有 Tushare 估值事实。Provider 少返回资产时，任务保持完整 active universe 为 requested 分母；只有激活政策 `allow_partial=true`、覆盖率达到 `minimum_coverage_ratio` 且逐证券缺失原因完整时，才发布合格估值成员并返回结构化 `partial`。低于门槛、缺少政策证据或报价不完整时继续 fail closed，禁止以未捕获异常结束或发布不合格范围。

同日生产验收确认单一 Provider 无法同时覆盖停牌报价与估值，任务按 `quote_source` / `valuation_source` 分别路由。显式选择 AKShare 行情时，报价个别缺失只在 Tencent 同批重叠价格全部处于 1% 容差后补入缺失身份，零重叠或冲突继续失败关闭。兼容参数 `source` 只用于显式单源诊断；估值 partial 规则不能扩展为报价范围放宽。

2026-09-26 估值日期校验：只读生产证据显示，Tushare 缺失的 12 个估值代码由 Tencent 对 2026-09-24 目标日 12/12 返回，且 PE、PB、市值、原始响应哈希和 `available_at` 齐全。AKShare 估值适配器通过 Tencent 批量响应取值，只接受 `snapshot.observed_at.date() == as_of_date`，旧日和未来快照均不进入估值事实；精确目标日事实继续保留 `actual_source`、`available_at`、`fetched_at`、`raw_payload_hash`、`raw_payload_scope` 和 `source_record_id`。全市场任务与 Beat 默认估值源改为该 Tencent 合同，报价继续默认 Tushare；显式 `valuation_source=tushare` 保留用于诊断和回滚。

2026-09-26 估值局部缺失契约：全市场任务顶层 `requested/succeeded/failed` 使用估值证券口径，`stored` 使用实际事实行口径，并另保留 operation 统计；允许 partial 时每只缺失证券记录 `valuation_source_data_unavailable`，Publication 覆盖、scope block、policy identity、publication id/hash 和 run id 必须一致。兼容 `success=false` 不能把明确的 `outcome=partial` 降格为 failed；Task Monitor 以 outcome 为准。

生产 200 只批次实测约 65 秒，全市场约 28 批；全市场任务的 Celery soft/hard limit 为 5400/5700 秒，只作为外层兜底。Redis broker visibility timeout 为 7200 秒，必须严格高于全仓受管任务的最大 hard limit，并保留网络与收尾余量；不得恢复默认约 3600 秒。审计授权预检至少覆盖 6300 秒（严格高于 hard limit 加 300 秒收尾预算）。该调整不放宽 provider 单次请求、重试或锁时限；三者必须保持各自独立，禁止让合法全集刷新在发布前被 visibility 重投或旧预算终止。

2026-09-27 正式行情发布的日线验证只批量准备目标交易日，并让逐证券校验复用该预取结果。只有目标日事实缺失或不可用的证券才扩大到 120 日历史，供 Data Center 继续执行来源一致性和逐日全停牌证据校验；额度、权限、冲突和其他不可信错误不得触发逐证券历史回退。此 120 日窗口服务 Qlib/停牌核验，不是正式 Publication 的全市场预取窗口。

2026-09-28 全市场快照规模契约：一次 `refresh_full_market_publications_task` 对一个 provider 和目标交易日只执行一次全市场 `daily` 快照读取；Application 将响应完成时间、真实可用的原始响应 SHA-256、规范化报价行 hash、provider identity 和冻结 universe hash 放入 task-local `PreparedQuoteSession`。后续有界 fact-write 批次只能读取该冻结响应的子集，不能再次访问 provider；下一任务必须重新读取，禁止跨任务缓存。Provider 拒绝、返回缺失/重复/越界 identity、错误交易日或无来源时间时在任何 quote fact 写入前失败关闭；不得因范围错误缩小全集、把缺行认作停牌或放宽 Publication freshness。

2026-09-28 全天停牌容错契约：provider 缺行仍不能直接解释为停牌。任务只对本次动态
`requested - returned` 集合调用目标交易日全天停牌证据端口；只有每个缺口都得到精确日期证据时，
才把它们记为 `quote_full_day_suspension` 并从 quote eligible scope 排除。完整 requested universe
及其 hash 保持不变，eligible quote 必须 100% 返回；未证实缺口、错日、日内停牌、重复或越界身份
继续在任何 quote fact 写入和 Publication 更新前阻断。成功发布时，停牌证券形成带日期、来源、run、
policy 和 publication identity 的证券级 scope block，其他证券继续可用；任务返回 `partial` 以及完整
`requested/succeeded/failed/stored`、动态排除清单和安全说明，不合成 0 价格或沿用旧报价冒充当日值。

2026-09-28 审计锁竞争容错：长任务在每个写边界仍须复验同一 authority identity。仅当读取返回稳定的 `system_audit_authority_unavailable` 时，允许最多 6 次递增、单次不超过 5 秒的有界重读，以跨过其他受治理写入持有的短事务锁；每次重读都使用新的 UTC 时钟重算有效窗口。authority source、actor、user、tenant、owner、认证/职员状态、role 或有效期发生变化时立即失败关闭，不得重试为成功，也不得跳过最终发布前复验。

2026-09-29 初始 authority 预检容错：任务尚未访问 provider 或写入事实前，初始预检也可能与
续租或其他受治理写入争用 Account authority 表。初始预检与写边界复验共享同一个单次读取和
有界退避原语，但各自独立计数，禁止形成嵌套重试；只对
`system_audit_authority_unavailable` 最多读取 6 次，累计等待不超过 15 秒，并在每次重读时使用新的
UTC 时刻重新计算完整任务授权窗口。配置缺失、identity/actor/role/scope 变化以及有效期不足立即
返回 `blocked` 和 `requested/succeeded/failed/stored=0/0/0/0`。授权有效期必须严格晚于任务窗口
端点；恰好等于端点也按不足处理。

同日阶段诊断整改：市场发布编排结果增加 `phase`、`phase_results`、`target_trade_date` 和 `stored_count_unit=fact_row`。各阶段分别保留 requested/succeeded/failed/stored；事实同步完成而发布失败必须为 partial，并保留前序存储计数和失败阶段。`stored` 沿用 repository 已接受持久化事实数量口径（包括成功幂等 upsert），不表示新增物理行数量，也不包含独立的 valuation seed 计数；`published_members` 独立统计。公开结果只含稳定码，完整异常栈进入运维日志。

2026-09-29 发布 authority 阻断：`publication.execute` 的 Audit composition 异常必须在 Data Center composition root 映射为 `MarketPublicationRefreshBlocked`，不得把 Audit implementation exception 透传到 Celery。刷新协调器在 `phase=publication` 返回稳定 `error_code`/`blocked_reason`、`requested/succeeded/failed/stored` 和 `publication_updated=false`；已有事实时为 `partial`，无已存事实时为 `blocked`，并设置 `must_not_use_for_decision=true`。Task Monitor 读取该业务 outcome，不能只显示技术 failure 或空 payload。

2026-10-02 全市场同步 RawAudit 血缘：成功 quote sync 返回与 `run_id`、`ingested_run_id` 一致的 exact `RawAuditReference`。quote RawAudit 的 `extra.source_type` 保持 provider config 的规范来源。成功 valuation batch 必须在写事实前确认所有返回 fact 具有同一个规范 `source`；RawAudit 的 `extra.source_type` 记录该实际 fact 来源，`extra.provider_source_type` 单独记录 provider config 路由来源，两者都参与内容 hash。空批次或失败 valuation audit 可以用 provider 来源填充 `source_type`，但其非成功状态不得进入 Publication。full-market task 汇总 quote 批次和 valuation seed 的 exact 引用并按 dataset 输出；缺失、身份不符或重复引用阻止 Publication。引用失败发生在事实已写入后时，顶层资产计数保持资产口径，`operation_*` 保持同步操作口径，`stored` 和对应 quote phase 反映已持久化行，但该批不计成功。故障注入覆盖见 `test_task_repairs_missing_price_scope_before_final_publication`。

证券主数据自然刷新对 AKShare 的瞬时 `OSError/RuntimeError/ValueError` 最多尝试 3 次；最终失败返回 `MARKET_UNIVERSE_REFRESH_FAILED`，任务结果和 Alpha 页面只显示稳定错误码，不回显第三方响应。空名单同样阻断，不能用旧名单伪装本次同步成功。

2026-10-08 财报容量与发布隔离：兼容入口 `data_center.refresh_financial_publications_batch` 在请求 provider 前固定返回 `financial_capacity_receipt_required`，不再调用通用 Tushare backfill 或发布 current。一次性资格任务 `data_center.refresh_financial_publication_capacity` 只在独立、reviewed、精确绑定的 qualification ceiling 存在时允许隔离 egress；调用参数不能抬高该 ceiling。其动态 asset/date manifest、累计双 capture 请求预留、RawAudit/typed evidence 与原子写证据进入持久 receipt。每次 task 调用默认最多处理一个 slice，不自续 broker continuation；checkpoint 保存未完成状态，worker 中断后的 in-flight slice 保留为 outcome-indeterminate orphan 证据并阻断重放。正式 stage 启动前、每个 provider slice 前和最终 activation 前都复验同一 DATA-02 authority；精确 production ceiling 由数据库唯一 approval id 单次消费，缺少/漂移/过期 approval 在 provider egress 前阻断。任何部分失败或零输出均不生成 policy-v3 candidate；完整成功才允许原子 activation。现有周期调度仍指向 fail-closed 兼容入口，待业务批准后再将调度切换到显式治理动作。

2026-09-29 全市场 point-in-time universe：`refresh_full_market_publications_task` 保留本次同步的当前 active 候选 count/hash，并将目标交易日 eligible universe 作为独立 requested scope；只有带 `list_date_evidence_status=verified` 与非空来源、且 `list_date > target_trade_date` 的资产才可排除，目标日当天上市资产应纳入。未知、冲突或无来源日期继续计入 requested，普通 provider 缺行仍按未解决缺口阻断。目标日 scope 的候选、requested、排除证据和未知日期证据分别进入结果审计字段；`full_universe_capacity_runner` 与 `market_rehearsal_runner` 使用相同 Application resolver 和同一证据口径，release validator 校验两份容量 receipt 一致。

2026-10-05 全市场 task-wide fail-fast lease：所有人工和 Beat 调用共用
`data_center.refresh_full_market_publications` task 入口。入口在任何 provider、fact 写入或 Publication
动作前，以 cache 原子 `add` 争取唯一 owner lease；已持有时立即返回 `outcome=noop`、四项零计数和稳定
`FULL_MARKET_REFRESH_ALREADY_RUNNING`，cache 不可用时返回 `blocked`、零写入和稳定
`FULL_MARKET_REFRESH_LEASE_UNAVAILABLE`。正常、异常和 `SoftTimeLimitExceeded` 均在 `finally` 尝试仅释放本 owner
的 lease；worker 崩溃时由有限 TTL 回收。hard time limit 保持 5,700 秒、authority window 保持 6,300 秒，
lease TTL 为 hard limit 加 300 秒收尾余量（6,000 秒），并以不变量测试约束其严格长于 hard limit 且短于
authority window。此互斥只覆盖该 full-market task 的人工与周期入口，不声称串行化独立行情写入者。
