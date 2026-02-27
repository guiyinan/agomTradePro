# a0049fd 提交验收问题清单

- Commit: `a0049fd`
- 验收结论：`不通过（需修复后复测）`
- 说明：新增测试通过，但存在阻断级运行问题与迁移回归风险。

## 问题 1（P0-1，阻断）
### 标题
RSS 指定源抓取失败

### 现象
在 RSS 管理页手动触发指定源抓取时，传入 `source_id` 报错，抓取无法执行。

### 根因
`fetch_rss_sources` 在同一文件被重复定义，后面的无参定义覆盖前面的有参定义。

### 代码定位
- [tasks.py](D:\githv\agomSAAF\apps\policy\application\tasks.py:289)
- [tasks.py](D:\githv\agomSAAF\apps\policy\application\tasks.py:629)
- [views.py](D:\githv\agomSAAF\apps\policy\interface\views.py:566)
- [views.py](D:\githv\agomSAAF\apps\policy\interface\views.py:582)

### 修复建议
仅保留一个任务定义：`fetch_rss_sources(source_id: Optional[int] = None)`，并统一所有调用参数。

### 验收标准
同步模式和异步模式下，指定源抓取均可成功执行。

---

## 问题 2（P0-2，高）
### 标题
闸门配置 PUT 首次创建资产类返回 500

### 现象
调用 `PUT /api/policy/sentiment-gate-config/` 创建不存在的 `asset_class` 时返回 500。

### 根因
`update_or_create(... defaults={ 'version': F('version') + 1 })` 在插入路径不支持 F 表达式。

### 代码定位
- [views.py](D:\githv\agomSAAF\apps\policy\interface\views.py:1652)
- [views.py](D:\githv\agomSAAF\apps\policy\interface\views.py:1657)

### 修复建议
拆分创建/更新路径：
- 创建：固定 `version=1`
- 更新：`version = F('version') + 1` 后 `refresh_from_db()`

### 验收标准
首次创建和后续更新均成功，版本号按预期递增。

---

## 问题 3（P0-3，高）
### 标题
迁移后当前政策档位可能错误回落为 P0

### 现象
上线后可能出现“当前政策档位异常回落”，与历史业务状态不一致。

### 根因
新查询口径仅统计 `event_type='policy' AND gate_effective=True`，但迁移未对存量数据做回填，`gate_effective` 默认 `False`。

### 代码定位
- [repositories.py](D:\githv\agomSAAF\apps\policy\infrastructure\repositories.py:239)
- [0007_add_workbench_fields.py](D:\githv\agomSAAF\apps\policy\migrations\0007_add_workbench_fields.py:314)

### 修复建议
在迁移中补充 `RunPython` 数据回填逻辑：
- 回填 `event_type`
- 对历史已审核通过事件回填 `gate_effective=True` 与 `effective_at`

### 验收标准
迁移前后，`get_current_policy_level()` 对既有数据口径一致。

---

## 问题 4（P1-1，中）
### 标题
政策档位变化触发信号重评导入路径错误

### 现象
档位变化时重评任务导入失败，逻辑静默失效（仅日志报错）。

### 根因
在 `infrastructure/models.py` 中错误导入 `.tasks`。

### 代码定位
- [models.py](D:\githv\agomSAAF\apps\policy\infrastructure\models.py:735)

### 修复建议
改为正确路径：
`from apps.policy.application.tasks import trigger_signal_reevaluation`

### 验收标准
档位变化后能成功下发 `trigger_signal_reevaluation` 任务。

---

## 问题 5（P1-2，中）
### 标题
任务函数重复定义导致行为不透明

### 现象
`generate_daily_policy_summary` 存在重复定义，后者覆盖前者，实际运行行为难以确定。

### 代码定位
- [tasks.py](D:\githv\agomSAAF\apps\policy\application\tasks.py:156)
- [tasks.py](D:\githv\agomSAAF\apps\policy\application\tasks.py:483)

### 修复建议
合并为单一定义，统一输出字段与调用方契约。

### 验收标准
任务名对应唯一实现，日志与返回结构稳定一致。

---

## 问题 6（P2-1，改进）
### 标题
测试未覆盖关键故障路径

### 现象
本次新增测试通过，但未覆盖“指定源抓取参数兼容”和“闸门配置首次创建”等故障路径。

### 修复建议
新增以下测试：
1. 指定源抓取（同步/异步）成功
2. `sentiment-gate-config` 首次创建资产类成功
3. 迁移后政策档位口径回归测试

### 验收标准
上述测试可稳定发现回归，修复后全部通过。

---

## 复测建议流程
1. 修复 P0 问题并提交补丁。
2. 执行 API/集成回归测试（至少覆盖工作台与抓取流程）。
3. 在迁移后的准生产数据上验证当前政策档位一致性。
4. 验证 Celery Beat 定时任务与手动触发路径都可用。

