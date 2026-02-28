# Policy 工作台模块指南

> **模块路径**: `apps/policy/`
> **最后更新**: 2026-02-28
> **状态**: ✅ 生产就绪

---

## 概述

Policy 工作台是一个统一的事件管理平台，整合了 **RSS 抓取**、**政策事件管理**、**热点情绪监控**、**审核流程** 和 **闸门生效** 等功能。

### 核心设计理念

**双闸并行机制**：
1. **Policy Gate（政策闸门）**: P0-P3，反映宏观政策风险
2. **Market Heat/Sentiment Gate（热点情绪闸门）**: L0-L3，反映全资产热点与情绪风险

**关键约束**：
- 热点情绪事件不会通过“单独覆盖字段”直接写死 P0-P3 档位
- 政策当前档位按“全部已生效事件”（`gate_effective=True`）计算，不再限制 `event_type='policy'`

---

## 架构设计

### 四层架构

```
┌─────────────────────────────────────────────────────────────────┐
│ Interface Layer                                                 │
│  - views.py: WorkbenchSummaryView, WorkbenchItemsView, etc.    │
│  - api_urls.py: /api/policy/workbench/*                        │
│  - serializers.py: WorkbenchSummarySerializer, etc.            │
│  - templates/policy/workbench.html                             │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Application Layer                                               │
│  - use_cases.py: GetWorkbenchSummaryUseCase, ApproveEventUseCase│
│  - tasks.py: auto_assign_pending_audits, monitor_sla_exceeded   │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Domain Layer                                                    │
│  - entities.py: EventType, GateLevel, HeatSentimentScore       │
│  - rules.py: calculate_gate_level, should_auto_approve         │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│ Infrastructure Layer                                            │
│  - models.py: PolicyLog, SentimentGateConfig, etc.             │
│  - repositories.py: DjangoPolicyRepository, WorkbenchRepository │
└─────────────────────────────────────────────────────────────────┘
```

---

## 数据模型

### PolicyLog 扩展字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_type` | CharField | 事件类型：policy/hotspot/sentiment/mixed |
| `asset_class` | CharField | 资产分类：equity/bond/commodity/fx/crypto/all |
| `asset_scope` | JSONField | 受影响资产范围 |
| `heat_score` | FloatField | 热度评分 (0-100) |
| `sentiment_score` | FloatField | 情绪评分 (-1.0 ~ +1.0) |
| `gate_level` | CharField | 闸门等级：L0/L1/L2/L3 |
| `gate_effective` | BooleanField | 是否已生效 |
| `effective_at` | DateTimeField | 生效时间 |
| `effective_by` | ForeignKey | 生效操作人 |
| `rollback_reason` | TextField | 回滚原因 |

### 新增配置模型

**PolicyIngestionConfig（单例）**:
- `auto_approve_enabled`: 启用自动生效
- `auto_approve_threshold`: 自动生效置信度阈值 (默认 0.85)
- `p23_sla_hours`: P2/P3 SLA 时限 (默认 2 小时)
- `normal_sla_hours`: 普通 SLA 时限 (默认 24 小时)

**SentimentGateConfig（按资产类）**:
- `heat_l1/l2/l3_threshold`: 热度阈值
- `sentiment_l1/l2/l3_threshold`: 情绪阈值
- `max_position_cap_l2/l3`: 仓位上限

**GateActionAuditLog（审计日志）**:
- `action`: 操作类型（approve/reject/rollback/override）
- `before_state`/`after_state`: 操作前后快照
- `reason`: 操作原因

---

## 业务规则

### 热点情绪闸门等级计算

```python
def calculate_gate_level(heat_score, sentiment_score, thresholds) -> GateLevel:
    """
    规则：热度或情绪任一触发即升级
    - L3: 热度 >= L3阈值 OR 情绪 <= L3阈值
    - L2: 热度 >= L2阈值 OR 情绪 <= L2阈值
    - L1: 热度 >= L1阈值 OR 情绪 <= L1阈值
    - L0: 其他情况
    """
```

默认阈值：
| 等级 | 热度阈值 | 情绪阈值 |
|------|---------|---------|
| L1 | 30 | -0.3 |
| L2 | 60 | -0.6 |
| L3 | 85 | -0.8 |

### 自动生效规则

```python
def should_auto_approve(policy_level, ai_confidence, config) -> Tuple[bool, str]:
    """
    规则：
    1. auto_approve_enabled = True
    2. policy_level >= auto_approve_min_level (P2/P3)
    3. ai_confidence >= auto_approve_threshold (0.85)
    """
```

### SLA 监控

| 事件档位 | SLA 时限 | 超时标记 |
|---------|---------|---------|
| P2/P3 | 2 小时 | 红色 |
| P0/P1 | 24 小时 | 黄色 |

---

## API 端点

### 工作台 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/policy/workbench/summary/` | 工作台概览 |
| GET | `/api/policy/workbench/items/` | 事件列表（支持筛选） |
| POST | `/api/policy/workbench/items/{id}/approve/` | 审核通过 |
| POST | `/api/policy/workbench/items/{id}/reject/` | 审核拒绝 |
| POST | `/api/policy/workbench/items/{id}/rollback/` | 回滚生效 |
| POST | `/api/policy/workbench/items/{id}/override/` | 临时豁免 |

### 配置 API

| 方法 | 端点 | 说明 |
|------|------|------|
| GET/PUT | `/api/policy/ingestion-config/` | 摄入配置 |
| GET/PUT | `/api/policy/sentiment-gate-config/` | 闸门配置 |
| GET | `/api/policy/sentiment-gate/state/` | 闸门状态 |

### 查询参数

`/api/policy/workbench/items/` 支持以下筛选参数：
- `tab`: pending / effective / all
- `event_type`: policy / hotspot / sentiment / mixed
- `level`: P0 / P1 / P2 / P3
- `gate_level`: L0 / L1 / L2 / L3
- `asset_class`: equity / bond / commodity / fx / crypto / all
- `search`: 标题关键词搜索
- `page`: 分页页码

---

## Celery 定时任务

| 任务 | 调度频率 | 说明 |
|------|---------|------|
| `fetch_rss_sources` | 每 6 小时 | RSS 源抓取 |
| `auto_assign_pending_audits` | 每 15 分钟 | 自动分配审核 |
| `monitor_sla_exceeded` | 每 10 分钟 | SLA 超时监控 |
| `refresh_gate_constraints` | 每 5 分钟 | 刷新闸门约束 |

---

## 前端页面

### 工作台页面

**路由**: `/policy/workbench/`

**页面结构**:
```
┌─────────────────────────────────────────────────────────────┐
│ 顶部概览卡（4列网格）                                         │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │
│ │ 政策档位  │ │ 全局热度  │ │ 待审核数  │ │ SLA超时   │        │
│ │ P2-预警   │ │ 65 (L2)  │ │ 12       │ │ 3        │        │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘        │
├─────────────────────────────────────────────────────────────┤
│ 主工作区（Tab 切换）                                          │
│ [待审核队列] [已生效事件流] [约束矩阵]                          │
│ ┌─────────────────────────────────────────────────────────┐│
│ │ 筛选器：[事件类型▼] [状态▼] [档位▼] [日期范围] [搜索]      ││
│ ├─────────────────────────────────────────────────────────┤│
│ │ 表格：[✓] | 日期 | 类型 | 档位 | 标题 | AI置信度 | 操作    ││
│ └─────────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────────┤
│ 快捷动作：[立即抓取全部] [指定源抓取▼] [刷新]                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 测试覆盖

### 测试文件

| 文件 | 测试数 | 覆盖内容 |
|------|-------|---------|
| `tests/unit/test_policy_rules.py` | 41 | Domain 层规则函数 |
| `tests/integration/test_workbench_use_cases.py` | 15 | Application 层用例 |
| `tests/api/test_workbench_api.py` | 19 | API 契约测试 |

### 关键测试用例

```python
# Domain 层
test_l3_triggered_by_high_heat()           # 热度触发 L3
test_l2_triggered_by_sentiment()           # 情绪触发 L2
test_auto_approve_p2_high_confidence()     # P2 高置信度自动生效
test_no_auto_approve_low_confidence()      # 低置信度不自动生效

# Application 层
test_only_effective_events_count()         # 仅已生效事件计入档位
test_mixed_events_affect_policy_level()    # 非 policy 事件可影响政策档位
test_approve_sets_effective()              # 审核通过设置生效状态

# API 层
test_summary_returns_correct_structure()   # 概览返回结构正确
test_items_filter_by_event_type()          # 事件类型筛选
test_reject_requires_reason()              # 拒绝必须填写原因
```

---

## 迁移说明

### 迁移 0007_add_workbench_fields

**新增字段**: PolicyLog 11 个字段 + 3 个新模型

**数据回填**:
1. `event_type`: 所有存量记录设为 `policy`
2. `gate_effective`: 已审核通过记录设为 `True`
3. `effective_at`: 使用 `reviewed_at` 或 `created_at`

**执行命令**:
```bash
python manage.py migrate policy
```

---

## 常见问题

### Q: 哪些事件会影响政策档位（P0-P3）？

A: 只要事件已生效（`gate_effective=True`），都可参与当前政策档位计算，不再按 `event_type='policy'` 限制。热点/情绪闸门（L0-L3）仍按其独立规则计算。

### Q: 如何修改自动生效阈值？

A: 通过 API `/api/policy/ingestion-config/` 修改 `auto_approve_threshold` 字段。

### Q: SLA 超时后会发生什么？

A: SLA 超时会在工作台显示红色/黄色标记，并记录日志。可配置告警通知。

---

## 变更历史

| 日期 | 版本 | 变更内容 |
|------|------|---------|
| 2026-02-27 | 1.0 | 初始版本，工作台功能完整实现 |
| 2026-02-28 | 1.1 | 同步导航收口口径（工作台入口/API文档唯一入口/我的投资账户）并修正 P0-P3 计算说明 |

---

## 导航与入口规范（2026-02-28）

1. 顶部导航“宏观环境”入口统一为：`政策/情绪/热点工作台`，页面路由：`/policy/workbench/`。
2. 顶部导航“投资管理”账户入口文案统一为：`我的投资账户`。
3. API 文档入口只保留“系统”菜单中的 `/api/docs/`；不再在右上角重复展示。
4. 页面模板导航应使用 Django `{% url %}` 反解，不使用硬编码业务页面路径。
5. 页面导航不得直接跳转业务 API（`/api/*`），仅文档入口 `/api/docs/` 例外。
