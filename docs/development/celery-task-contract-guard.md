# Celery 关键任务契约护栏

> 生效日期：2026-07-24
> 适用范围：直接影响数据新鲜度、批量数据写入或下游业务闸门的 Celery 任务

## 目标

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
