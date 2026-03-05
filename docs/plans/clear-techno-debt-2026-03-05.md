# 技术债务清理计划

## Context

AgomSAAF V3.4 功能已完成，但在代码质量扫描中发现以下技术债务：
- 48 个文件、141 处 `datetime.now()` 违反 `USE_TZ=True`（会触发 RuntimeWarning）
- 6 个 Celery task 文件缺少 `time_limit`/`soft_time_limit`（任务可能永久挂起）
- Signal 模型 3 个废弃字段仍在使用（invalidation_logic, invalidation_threshold, invalidation_rules）
- ai_provider 明文 api_key 字段标记废弃但未清理
- 重复的 `encrypt_api_keys.py` 命令（两个位置）
- 遗留的 `management/commands/test_data_connections.py`（根目录）
- 20+ 条 legacy 路由（sunset date 2026-06-01，已进入倒计时）
- 废弃的 `GetCurrentRegimeUseCase`（已有替代 `resolve_current_regime()`）

**原则**：只改确定安全的、不影响业务逻辑的清理。跳过高风险项（migration squash、跨 app 重构、100+ 处 import 重构）。

---

## D1: datetime.now() → timezone-aware（48 个文件，141 处）

### 策略
- **Domain 层**（不能导入 Django）：`datetime.now()` → `datetime.now(timezone.utc)`
- **Application/Infrastructure/Interface 层**：`datetime.now()` → `timezone.now()`（从 `django.utils import timezone`）
- **纯字符串格式化场景**（如 `datetime.now().strftime("%Y%m%d")`）：用 `timezone.now()` 替换

### 文件清单（按模块分组）

**高频模块**（>5 处）：
- `apps/decision_rhythm/domain/entities.py` (27 处)
- `apps/events/application/tasks.py` (9 处)
- `apps/decision_rhythm/domain/services.py` (7 处)
- `apps/alpha_trigger/domain/entities.py` (6 处)
- `apps/events/domain/rules.py` (5 处)
- `apps/realtime/infrastructure/repositories.py` (5 处)
- `apps/realtime/application/price_polling_service.py` (5 处)

**中频模块**（2-4 处）：
- `apps/decision_rhythm/application/use_cases.py` (4)
- `apps/alpha_trigger/application/use_cases.py` (4)
- `apps/beta_gate/domain/entities.py` (4)
- `apps/events/domain/services.py` (3)
- `apps/alpha/application/tasks.py` (3)
- `apps/alpha_trigger/domain/services.py` (3)
- `apps/sentiment/application/services.py` (3)
- `apps/equity/interface/views.py` (3)
- `apps/alpha/management/commands/train_qlib_model.py` (3)
- 以及其余 30+ 文件各 1-2 处

### 注意
- Domain 层文件（`domain/entities.py`, `domain/services.py`, `domain/rules.py`）必须用 `datetime.now(timezone.utc)`，不能导入 Django
- 部分 Domain 层文件已有 `from datetime import timezone` 导入，直接改即可
- 未导入 timezone 的需添加导入

---

## D2: Celery 任务加固（6 个文件）

以下 task 文件缺少 `time_limit`/`soft_time_limit`，需补齐：

| 文件 | 任务数 | 建议 time_limit |
|------|--------|----------------|
| `apps/account/application/tasks.py` | ~10 | 600/570 |
| `apps/macro/application/tasks.py` | ~8 | 900/850（数据同步），300/280（检查） |
| `apps/policy/application/tasks.py` | ~3 | 600/570 |
| `apps/regime/application/tasks.py` | ~3 | 600/570 |
| `apps/signal/application/tasks.py` | ~3 | 600/570 |
| `apps/task_monitor/application/tasks.py` | ~5 | 300/280 |

---

## D3: 废弃字段与重复命令清理

### D3.1 重复 encrypt_api_keys 命令
- `apps/ai_provider/management/commands/encrypt_api_keys.py` (92 行)
- `apps/ai_provider/infrastructure/management/commands/encrypt_api_keys.py` (171 行)
- **操作**：保留更完整的 infrastructure 版本，删除 management 版本

### D3.2 废弃的 GetCurrentRegimeUseCase
- `apps/regime/application/use_cases.py` 中 `GetCurrentRegimeUseCase` 已标记 deprecated
- 检查调用方，如无则删除；如有则更新调用方

---

## D4: 文件清理

- `management/commands/test_data_connections.py` → `core/management/commands/test_data_connections.py`

---

## D5: Legacy 路由清理

Sunset date 2026-06-01，当前 2026-03-05，进入倒计时。删除所有 `_legacy` 路由：
- `apps/macro/interface/urls.py`：12 条
- `apps/policy/interface/urls.py`：1 条
- `apps/realtime/interface/urls.py`：4 条
- `apps/regime/interface/urls.py`：1 条
- `apps/signal/interface/urls.py`：1 条
- `apps/dashboard/interface/urls.py`：1 条
- 保留 `core/middleware/deprecation.py` 作为兜底

---

## 不做的事项

| 跳过项 | 原因 |
|--------|------|
| 跨 app import 重构（100+ 处）| 需要为每个调用创建 use case，工作量巨大 |
| Migration squash | 需全团队协调，squash 后无法回退 |
| Signal 废弃字段删除 | 需要数据迁移验证，先标注后续版本删除 |
| ai_provider api_key 字段删除 | 同上，先确认所有代码已切换到 encrypted |
| 所有 bare except 替换 | 部分是合理 catch-all，需逐个判断 |
| TODO 实现 | 功能需求，非技术债务 |

---

## 验证

```bash
# 1. datetime.now() 违规应该为 0
grep -rn "datetime\.now()" apps/ --include="*.py" | grep -v "timezone" | wc -l

# 2. 所有 Celery task 有 time_limit
for f in apps/*/application/tasks.py; do echo "$f"; grep -c "time_limit" "$f"; done

# 3. 全量测试通过
pytest tests/unit/ tests/integration/ -v --tb=short -q

# 4. legacy 路由数量为 0
grep -rn "_legacy" apps/*/interface/urls.py | wc -l
```
