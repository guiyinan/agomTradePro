# Celery 关键任务契约护栏

> 生效日期：2026-07-24
> 适用范围：直接影响数据新鲜度、批量数据写入或下游业务闸门的 Celery 任务

## 目标

2026-09-19 全市场刷新：`refresh_full_market_publications_task` 冻结有效 A 股范围，分批执行带审计的 quote/valuation fact-only 同步。全部批次成功且快照、估值源日期等于最近完成交易日后，才原子发布整个 quote/valuation/price 范围；独立财报缺少可用时间不再阻止市场数据发布。日线保留停牌股票真实末次观测，不填充价格，发布成功不表示所有成员可用于决策。计数单位为同步/发布操作，`stored` 为报价/估值事实行（不含日线补录量），部分同步或发布失败必须为 partial/failed，禁止发布中间批次。生产定时在推理前刷新快照并经过中台补录/校验当日日线后发布；`price_scope_verified` 和 `suspended_codes` 单独记录验证范围。

2026-09-19 Alpha scoped 定时入口：额度耗尽、模型行情契约阻断、刷新返回 failed/blocked 或目标日覆盖不足时，父任务直接发布 blocked、零写入并停止投递子推理，避免各组合重复刷新。普通瞬时异常仍保留既有通用推理重试路径。详见 [排查记录](../reviews/vps-alpha-auto-refresh-2026-09-19.md)。

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

2026-09-19：`data_center.refresh_full_market_publications` 冻结有效 A 股全集，按批刷新报价与估值事实；任何批次不完整均保留原 Publication。全部事实齐备且源观测日匹配最近完成交易日后才发布报价、估值、日线全集。停牌日线保留实际日期，财报发布仍独立校验。`setup_full_market_publications` 幂等配置工作日 16:30（项目时区）的 Beat 任务，可用参数调整或禁用。审计配置/服务身份不可用时，在任何行情请求和写入前返回 `outcome=blocked`、`stored=0` 及稳定原因；不得以关闭审计、空 writer 或临时管理员身份作为恢复措施。

2026-09-20 合并前维护：Alpha 的数据阻断结果和旧源评分标记由 `task_outcome_contracts` 统一生成，任务入口及原有 outcome、计数和阻断原因保持不变。

2026-09-24 Tushare 全市场估值修复：`daily_basic.total_mv/circ_mv` 的原始单位为“万元”，Provider 适配器必须在进入 Domain 前转换为存储规范“元”，并在 `extra` 保留原始单位、规范单位和 `10000` 转换倍数；迁移 `data_center.0084` 同步修复既有 Tushare 估值事实。停牌等原因造成 Provider 少返回资产时，严格身份校验仍然拒绝写入该批估值，但全市场任务必须返回结构化 `partial`、保留上一版 Publication，并把 `PROVIDER_ASSET_IDENTITY_MISMATCH` 暴露给 Task Monitor/Alpha 告警，禁止以未捕获异常结束或发布不完整范围。

同日生产验收确认单一 Provider 无法同时覆盖停牌报价与估值：全市场调度按能力固定选择 Tushare 报价与 AKShare 估值，两个来源各自仍须精确返回冻结批次身份。兼容参数 `source` 只用于显式单源诊断；自然调度写入独立的 `quote_source` / `valuation_source`，不得因某一能力缺口放宽全集校验。
