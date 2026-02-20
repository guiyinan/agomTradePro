# API 路由格式一致性分析

> **创建日期**: 2026-02-20
> **状态**: 待重构

---

## 问题概述

AgomSAAF 系统当前存在三种不同的 API 路由格式，这可能导致 API 使用者的困惑。

---

## 当前路由格式

### 格式 1: 双层 api 路径 (旧格式)

```
/api/{module}/api/{endpoint}/
```

**示例**:
- `/api/regime/api/` - Regime 列表
- `/api/regime/api/health/` - Regime 健康检查
- `/api/signal/api/` - Signal 列表
- `/api/realtime/api/prices/` - 实时价格

**原因**: 模块内部使用 `api/` 前缀区分 API 路由和页面路由

### 格式 2: 单层 api 路径 (新格式)

```
/api/{module}/{endpoint}/
```

**示例**:
- `/api/alpha/scores/` - Alpha 评分
- `/api/alpha/providers/status/` - Provider 状态

**原因**: 模块设计时直接作为纯 API 模块

### 格式 3: 模块路径下的 api (混合格式)

```
/{module}/api/{endpoint}/
```

**示例**:
- `/rotation/api/` - Rotation 操作
- `/rotation/api/recommendation/` - 轮动建议
- `/factor/api/definitions/` - 因子定义
- `/hedge/api/pairs/` - 对冲配对

**原因**: 通过 `/{module}/` 挂载，内部包含 `api/` 子路径

---

## 统一建议

### 目标格式

推荐统一为 **格式 2** (单层 api 路径):

```
/api/{module}/{endpoint}/
```

### 迁移计划

#### Phase 1: 添加兼容路由 (低风险)

在 `core/urls.py` 中添加兼容路由，支持新旧两种格式：

```python
# 新格式 (推荐)
path('api/regime/', include(('apps.regime.interface.urls', 'api_regime_v2'))),

# 旧格式 (兼容)
path('api/regime/api/', include(('apps.regime.interface.urls', 'api_regime_v1'))),
```

#### Phase 2: 更新模块 urls.py

将模块内的 `api/` 前缀改为直接暴露端点：

**Before**:
```python
urlpatterns = [
    path('api/', include(router.urls)),
    path('api/health/', HealthView.as_view()),
]
```

**After**:
```python
urlpatterns = [
    path('', include(router.urls)),
    path('health/', HealthView.as_view()),
]
```

#### Phase 3: 更新文档和客户端

- 更新 `docs/development/quick-reference.md`
- 更新 `docs/testing/api/API_REFERENCE.md`
- 通知 API 使用者迁移

#### Phase 4: 移除兼容路由

在确认所有客户端迁移后，移除旧格式支持。

---

## 模块路由现状

| 模块 | 当前格式 | 目标格式 | 优先级 |
|------|---------|---------|--------|
| regime | `/api/regime/api/` | `/api/regime/` | P1 |
| signal | `/api/signal/api/` | `/api/signal/` | P1 |
| realtime | `/api/realtime/api/` | `/api/realtime/` | P1 |
| policy | `/api/policy/api/` | `/api/policy/` | P2 |
| macro | `/api/macro/api/` | `/api/macro/` | P2 |
| alpha | `/api/alpha/` | ✅ 已符合 | - |
| rotation | `/rotation/api/` | `/api/rotation/` | P2 |
| factor | `/factor/api/` | `/api/factor/` | P2 |
| hedge | `/hedge/api/` | `/api/hedge/` | P2 |
| sentiment | `/api/sentiment/api/` | `/api/sentiment/` | P2 |

---

## 注意事项

1. **认证**: 所有 `/api/` 路由都应检查是否需要认证
2. **版本控制**: 考虑在路由中加入版本号 `/api/v1/{module}/`
3. **OpenAPI**: 迁移后需更新 OpenAPI 规范文档
4. **测试**: 迁移前确保有足够的 API 测试覆盖

---

## 参考文档

- `core/urls.py` - 主路由配置
- `docs/development/quick-reference.md` - API 快速参考
- `docs/testing/api/API_REFERENCE.md` - API 详细文档
