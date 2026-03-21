# API 路由格式一致性分析

> **创建日期**: 2026-02-20
> **状态**: 已完成 ✅
> **更新日期**: 2026-02-21

---

## 概述

AgomTradePro 系统已统一 API 路由格式为 `/api/{module}/{endpoint}/`，同时保持向后兼容。

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

### 向后兼容格式

以下格式仍可用，但建议迁移到标准格式：

1. **双层 api 路径**: `/api/{module}/api/{endpoint}/`
   - 示例: `/regime/api/` 或 `/api/regime/api/` → 请使用 `/api/regime/`

2. **模块路径下**: `/{module}/api/{endpoint}/`
   - 示例: `/rotation/api/` → 请使用 `/api/rotation/`

---

## 实施状态

### Phase 1-2: 已完成 ✅

- ✅ 更新模块 urls.py 移除内部 `api/` 前缀
- ✅ 保留旧格式路由以保持向后兼容
- ✅ 所有模块已更新

### Phase 3: 已完成 ✅

- ✅ 更新 `docs/development/quick-reference.md`
- ✅ 更新 `docs/testing/api/API_REFERENCE.md`

### Phase 4: 待定

- ⏳ 通知 API 使用者迁移到新格式
- ⏳ 确认所有客户端迁移后移除旧格式支持

---

## 模块路由迁移状态

| 模块 | 标准格式 | 旧格式 (兼容) | 状态 |
|------|---------|--------------|------|
| regime | `/api/regime/` | `/regime/api/`、`/api/regime/api/` | ✅ 完成 |
| signal | `/api/signal/` | `/api/signal/api/` | ✅ 完成 |
| realtime | `/api/realtime/` | `/api/realtime/api/` | ✅ 完成 |
| policy | `/api/policy/events/` | `/policy/api/events/` | ✅ 完成 |
| macro | `/api/macro/supported-indicators/` | `/macro/api/supported-indicators/` | ✅ 完成 |
| alpha | `/api/alpha/` | N/A | ✅ 原本符合 |
| rotation | `/api/rotation/` | `/rotation/api/` | ✅ 完成 |
| factor | `/api/factor/` | `/factor/api/` | ✅ 完成 |
| hedge | `/api/hedge/` | `/hedge/api/` | ✅ 完成 |
| sentiment | `/api/sentiment/analyze/` | `/api/sentiment/api/analyze/` | ✅ 完成 |

---

## 迁移示例

### Regime 模块

```python
# 旧格式 (仍可用，但不推荐)
GET /api/regime/
GET /api/regime/health/
GET /api/regime/current/

# 新格式 (推荐)
GET /api/regime/
GET /api/regime/health/
GET /api/regime/current/
```

### Signal 模块

```python
# 旧格式 (仍可用，但不推荐)
GET /api/signal/api/
POST /api/signal/api/
GET /api/signal/api/health/

# 新格式 (推荐)
GET /api/signal/
POST /api/signal/
GET /api/signal/health/
```

### Rotation 模块

```python
# 旧格式 (仍可用，但不推荐)
GET /rotation/api/
GET /rotation/api/assets/

# 新格式 (推荐)
GET /api/rotation/
GET /api/rotation/assets/
```

---

## 注意事项

1. **认证**: 所有 `/api/` 路由都需要认证
2. **版本控制**: 当前使用 implicit v1，未来可考虑 `/api/v1/{module}/`
3. **OpenAPI**: OpenAPI schema 已自动更新
4. **测试**: 所有 API 测试已更新

---

## 参考文档

- `core/urls.py` - 主路由配置
- `docs/development/quick-reference.md` - API 快速参考
- `docs/testing/api/API_REFERENCE.md` - API 详细文档
