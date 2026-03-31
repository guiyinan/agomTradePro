# API 路由格式一致性分析

> **创建日期**: 2026-02-20
> **状态**: 已完成 ✅
> **更新日期**: 2026-03-31

---

## 概述

AgomTradePro 系统已统一 API 路由格式为 `/api/{module}/{endpoint}/`，预发布阶段不再保留历史兼容路径。

---

## 统一路由格式

### 标准格式 (推荐)

```
/api/{module}/{endpoint}/
```

**示例**:
- `/api/regime/` - Regime 列表
- `/api/regime/health/` - Regime 健康检查
- `/api/signal/` - Signal 列表
- `/api/realtime/prices/` - 实时价格
- `/api/alpha/scores/` - Alpha 评分

### 已废弃格式

以下历史格式已在预发布阶段移除，访问应返回 404：

1. **双层 api 路径**: `/api/{module}/api/{endpoint}/`
2. **模块路径下**: `/{module}/api/{endpoint}/`
3. **拼写或单复数旧路径**: 例如旧的单数命名、错误别名路径

---

## 实施状态

### Phase 1-2: 已完成 ✅

- ✅ 更新模块 urls.py 移除内部 `api/` 前缀
- ✅ 所有模块切换到 canonical 路径
- ✅ 预发布阶段已删除旧格式路由

### Phase 3: 已完成 ✅

- ✅ 更新 `docs/development/quick-reference.md`
- ✅ 更新 `docs/testing/api/API_REFERENCE.md`

### Phase 4: 已完成 ✅

- ✅ 当前代码、模板、SDK、MCP 统一只引用 canonical 路径
- ✅ 历史兼容路径已从运行时移除

---

## 模块路由迁移状态

| 模块 | 标准格式 | 历史格式类型 | 状态 |
|------|---------|--------------|------|
| regime | `/api/regime/` | module-first / double-api | ✅ 完成 |
| signal | `/api/signal/` | double-api | ✅ 完成 |
| realtime | `/api/realtime/` | double-api | ✅ 完成 |
| policy | `/api/policy/events/` | module-first | ✅ 完成 |
| macro | `/api/macro/supported-indicators/` | module-first | ✅ 完成 |
| alpha | `/api/alpha/` | N/A | ✅ 原本符合 |
| rotation | `/api/rotation/` | module-first | ✅ 完成 |
| factor | `/api/factor/` | module-first | ✅ 完成 |
| hedge | `/api/hedge/` | module-first | ✅ 完成 |
| sentiment | `/api/sentiment/analyze/` | `/api/sentiment/api/analyze/` | ✅ 完成 |

---

## 迁移示例

### Signal 模块

```python
# 已废弃
GET /api/{module}/api/{endpoint}/
POST /api/{module}/api/{endpoint}/
GET /api/{module_plural}/

# 当前 canonical
GET /api/signal/
POST /api/signal/
GET /api/signal/health/
```

### Policy RSS 模块

```python
# 已废弃
GET /api/{module}/api/{resource}/
GET /api/{module}/{legacy-status-endpoint}/

# 当前 canonical
GET /api/policy/rss/sources/
GET /api/policy/status/
```

---

## 注意事项

1. **认证**: 所有 `/api/` 路由都需要认证
2. **版本控制**: 当前使用 implicit v1，未来可考虑 `/api/v1/{module}/`
3. **OpenAPI**: OpenAPI schema 已自动更新
4. **测试**: 所有 API 测试已更新

---

## 当前约束（2026-03-31）

- 文档、模板、测试、SDK、MCP 只能引用 canonical 路径
- 历史兼容别名不得重新加入 `urls.py` 或 `api_urls.py`
- API discoverability 仅通过明确的 canonical root 提供，例如 `/api/`、`/api/pulse/`
- 新增路由时必须同步补充“旧路径 404、canonical 路径可用”的测试

---

## 参考文档

- `core/urls.py` - 主路由配置
- `docs/development/quick-reference.md` - API 快速参考
- `docs/testing/api/API_REFERENCE.md` - API 详细文档
