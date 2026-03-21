# 决策平台功能完善计划

**计划日期**: 2026-02-04
**版本**: 1.0
**状态**: 待审阅

---

## 一、项目概述

### 1.1 目标

完善 AgomTradePro 决策平台三个模块的功能，提升用户体验和管理效率。

### 1.2 涉及模块

| 模块 | 功能描述 | 当前完成度 |
|------|----------|------------|
| **beta_gate** | Beta 闸门 - 基于宏观环境的资产可见性过滤 | 80% |
| **alpha_trigger** | Alpha 触发器 - 离散、可证伪的信号触发机制 | 85% |
| **decision_rhythm** | 决策配额 - 决策频率约束与配额管理 | 80% |

### 1.3 当前状态

**已完成**：
- ✅ 完整的四层架构（Domain → Application → Infrastructure → Interface）
- ✅ 三个模块都有基本的展示页面
- ✅ RESTful API 大部分已实现
- ✅ Django Admin 后台可管理

**关键缺失**：
- ❌ Alpha Trigger 完全没有创建/编辑界面
- ❌ Beta Gate 缺少资产测试工具
- ❌ Decision Rhythm 缺少配额配置界面
- ❌ 所有模块缺少版本对比、可视化等增强功能

---

## 二、功能需求清单

### 2.1 P0 - 高优先级（核心功能）

| ID | 功能 | 模块 | 预计工期 |
|----|------|------|----------|
| P0-1 | Alpha Trigger 创建/编辑界面 | alpha_trigger | 5 天 |
| P0-2 | Beta Gate 资产测试工具 | beta_gate | 3 天 |
| P0-3 | Decision Rhythm 配额配置和重置 | decision_rhythm | 4 天 |
| P0-4 | 补全 API 端点（CREATE/UPDATE/DELETE） | 全部 | 3 天 |

### 2.2 P1 - 中优先级（用户体验）

| ID | 功能 | 模块 | 预计工期 |
|----|------|------|----------|
| P1-1 | Beta Gate 配置历史版本对比 | beta_gate | 4 天 |
| P1-2 | Alpha Trigger 证伪规则可视化配置 | alpha_trigger | 5 天 |
| P1-3 | Decision Rhythm 配额使用趋势图 | decision_rhythm | 3 天 |
| P1-4 | 候选/触发器详情页面 | alpha_trigger | 4 天 |

### 2.3 P2 - 低优先级（增强功能）

| ID | 功能 | 模块 | 预计工期 |
|----|------|------|----------|
| P2-1 | 统一决策工作台 | 全部 | 6 天 |
| P2-2 | 告警通知功能 | 全部 | 4 天 |
| P2-3 | 触发器性能追踪 | alpha_trigger | 4 天 |

---

## 三、实施计划

### Phase 1: 核心缺失功能补全 (2 周)

#### P0-1: Alpha Trigger 创建/编辑界面

**目标**: 用户可以通过界面创建和编辑触发器，无需依赖 Django Admin

**需要创建的文件**:
```
apps/alpha_trigger/templates/alpha_trigger/
├── create.html          # 创建触发器页面
├── edit.html            # 编辑触发器页面
└── detail.html          # 触发器详情页面
```

**需要修改的文件**:
- `apps/alpha_trigger/interface/views.py` - 添加视图函数
- `apps/alpha_trigger/interface/urls.py` - 添加路由

**核心功能**:
1. **创建页面** - 表单包含：
   - 触发器类型选择（THRESHOLD_CROSS, MOMENTUM_SIGNAL, REGIME_TRANSITION 等）
   - 资产代码和类别输入
   - 方向选择（LONG/SHORT/NEUTRAL）
   - 触发条件配置（支持 JSON 或表单化配置）
   - 证伪条件配置器（多条件支持 AND/OR 逻辑）
   - 置信度滑块 (0-1)
   - 投资论点文本框
   - 过期天数设置

2. **编辑页面** - 加载现有数据，支持修改

3. **详情页面** - 显示完整信息和相关候选

**验收标准**:
- [ ] 用户可以通过界面创建触发器
- [ ] 创建的触发器能正确保存到数据库
- [ ] 可以编辑现有触发器
- [ ] 详情页面显示完整信息

---

#### P0-2: Beta Gate 资产测试工具

**目标**: 用户可以快速测试特定资产在当前配置下是否能通过 Beta Gate

**需要创建的文件**:
```
apps/beta_gate/templates/beta_gate/test_asset.html
```

**需要修改的文件**:
- `apps/beta_gate/interface/views.py`
- `apps/beta_gate/interface/urls.py`
- `apps/beta_gate/application/use_cases.py`

**核心功能**:
1. **测试页面** - 包含：
   - 资产代码输入框
   - 资产类别选择器
   - 当前 Regime/Policy 显示
   - 测试按钮
   - 结果展示区域（显示哪个约束拦截了资产）
   - 支持批量测试（最多 10 个资产）

**验收标准**:
- [ ] 可以输入资产代码进行测试
- [ ] 显示清晰的通过/拦截结果
- [ ] 显示拦截原因（哪个约束、为什么）
- [ ] 支持批量测试

---

#### P0-3: Decision Rhythm 配额配置和重置

**目标**: 管理员可以配置配额参数并手动重置配额

**需要创建的文件**:
```
apps/decision_rhythm/templates/decision_rhythm/
├── quota_config.html     # 配额配置页面
└── quota_history.html    # 配额使用历史
```

**需要修改的文件**:
- `apps/decision_rhythm/interface/views.py`
- `apps/decision_rhythm/interface/urls.py`

**核心功能**:
1. **配额配置页面** - 包含：
   - 配额周期选择（DAILY/WEEKLY/MONTHLY）
   - 最大决策次数设置
   - 最大执行次数设置
   - 每个优先级的配额权重

2. **配额重置功能** - 在 quota.html 添加重置按钮

3. **配额使用历史** - 显示最近 30 天的配额使用情况

**验收标准**:
- [ ] 可以配置不同周期的配额
- [ ] 可以手动重置配额（需要确认）
- [ ] 显示配额使用历史趋势

---

### Phase 2: 用户体验优化 (2 周)

#### P1-1: Beta Gate 配置历史版本对比

**目标**: 管理员可以查看配置历史版本，对比不同版本间的差异

**需要创建的文件**:
```
apps/beta_gate/templates/beta_gate/version_compare.html
```

**核心功能**:
- 选择两个版本进行对比
- 高亮显示差异字段
- 显示版本变更时间
- 支持回滚到旧版本

---

#### P1-2: Alpha Trigger 证伪规则可视化配置

**目标**: 用可视化界面替代 JSON 配置，降低配置门槛

**需要创建的文件**:
```
apps/alpha_trigger/templates/alpha_trigger/invalidation_builder.html
```

**核心功能**:
- 条件类型选择（阈值穿越/时间衰减/Regime 不匹配等）
- 操作符选择（大于/小于/等于/包含等）
- 支持 AND/OR 逻辑组合
- 预览生成的 JSON
- 测试规则功能

**参考实现**: `core/templates/signal/manage.html` 的条件构建器

---

#### P1-3: Decision Rhythm 配额使用趋势图

**目标**: 可视化展示配额使用历史趋势

**实现方式**:
- 在 `quota.html` 添加趋势图区域
- 使用 CSS flex 绘制简单条形图
- 显示最近 7/30 天的使用趋势
- 标记超限日期

---

#### P1-4: 候选/触发器详情页面

**目标**: 提供详细的信息查看页面

**需要创建的文件**:
```
apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html
```

**核心功能**:
- 显示候选完整信息
- 显示来源触发器
- 显示状态转换历史
- 操作按钮（批准/拒绝/标记已执行）

---

### Phase 3: 增强功能 (2 周)

#### P2-1: 统一决策工作台

**目标**: 集成三个模块的概览和快速操作

**需要创建的文件**:
```
core/templates/decision/workspace.html
```

**核心功能**:
- 三个模块的概览卡片
- 当前可操作的候选列表
- 配额剩余情况
- 快速操作入口
- 决策待办列表（优先级排序）

---

#### P2-2: 告警通知功能

**目标**: 关键事件及时通知

**告警类型**:
- 配额即将耗尽（剩余 < 20%）
- 配额已耗尽
- 触发器即将过期
- 候选即将过期
- Regime/Policy 变化通知

**实现方式**:
- 页面顶部显示告警横幅
- 支持邮件通知（可选）

---

#### P2-3: 触发器性能追踪

**目标**: 帮助用户评估触发器质量

**需要创建的文件**:
```
apps/alpha_trigger/templates/alpha_trigger/performance.html
```

**核心功能**:
- 触发次数统计
- 证伪率统计
- 平均持仓时间
- 转化为执行的比例

---

### Phase 4: 测试和文档 (1 周)

#### 测试补充
- 单元测试补充（目标覆盖率 ≥ 80%）
- 集成测试

#### 文档更新
- 决策平台开发文档
- 决策平台用户指南
- 决策平台 API 文档

---

## 四、技术约束

### 4.1 架构约束

严格遵守**四层架构**：

| 层级 | 允许使用 | 禁止使用 |
|------|----------|----------|
| **Domain** | Python 标准库、dataclasses、typing、enum | django.*、pandas、外部库 |
| **Application** | Domain 层、Protocol 接口 | 直接调用 ORM Model、外部 API |
| **Infrastructure** | Django ORM、Pandas、外部 API | - |
| **Interface** | DRF、模板引擎 | 业务逻辑 |

### 4.2 前端技术栈

- Django 模板引擎（服务端渲染）
- HTMX（动态交互）
- Alpine.js（轻量级前端逻辑）
- Bootstrap CSS（样式）
- Bootstrap Icons（图标）

### 4.3 参考实现

- `core/templates/signal/manage.html` - AI 助手、条件构建器
- `core/templates/strategy/` - 创建/编辑页面布局
- `apps/beta_gate/templates/beta_gate/config.html` - 现有实现

---

## 五、依赖关系

### 可并行开发
- Phase 1.1 和 1.2 可以并行
- Phase 2.1 和 2.3 可以并行
- Phase 3 的三个子任务可以并行

### 必须串行
- Phase 1 → Phase 2 → Phase 3 → Phase 4

### 关键路径
```
Phase 1.1 (Alpha Trigger 创建界面)
  ↓
Phase 1.3 (配额配置)
  ↓
Phase 2.2 (证伪规则可视化)
  ↓
Phase 3.1 (统一工作台)
  ↓
Phase 4 (测试和文档)
```

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 前端复杂度超预期 | 延期 | 第一版简化实现，使用 HTMX + Alpine.js |
| 四层架构约束增加开发时间 | 延期 | 复用现有模块的实现模式 |
| 测试覆盖率不足 | 质量风险 | 每完成一个功能立即编写测试 |
| 与现有功能集成问题 | 兼容性问题 | 保留 Django Admin 作为备选 |

---

## 七、验收标准

### Phase 1 验收
- [ ] Alpha Trigger 有完整的创建/编辑/详情界面
- [ ] Beta Gate 有资产测试工具
- [ ] Decision Rhythm 有配额配置界面和重置功能
- [ ] 所有新功能有基本的单元测试

### Phase 2 验收
- [ ] Beta Gate 支持版本对比
- [ ] Alpha Trigger 证伪规则可视化配置
- [ ] Decision Rhythm 有配额使用趋势图
- [ ] 所有详情页面实现

### Phase 3 验收
- [ ] 统一决策工作台可用
- [ ] 告警通知功能正常
- [ ] 触发器性能追踪可用

### Phase 4 验收
- [ ] 单元测试覆盖率 ≥ 80%
- [ ] 集成测试通过
- [ ] 文档完整更新

---

## 八、关键文件清单

### 需要创建的模板文件（11个）

**Alpha Trigger**:
1. `apps/alpha_trigger/templates/alpha_trigger/create.html`
2. `apps/alpha_trigger/templates/alpha_trigger/edit.html`
3. `apps/alpha_trigger/templates/alpha_trigger/detail.html`
4. `apps/alpha_trigger/templates/alpha_trigger/invalidation_builder.html`
5. `apps/alpha_trigger/templates/alpha_trigger/candidate_detail.html`
6. `apps/alpha_trigger/templates/alpha_trigger/performance.html`

**Beta Gate**:
7. `apps/beta_gate/templates/beta_gate/test_asset.html`
8. `apps/beta_gate/templates/beta_gate/version_compare.html`

**Decision Rhythm**:
9. `apps/decision_rhythm/templates/decision_rhythm/quota_config.html`
10. `apps/decision_rhythm/templates/decision_rhythm/quota_history.html`

**统一**:
11. `core/templates/decision/workspace.html`

### 需要修改的核心文件（5个）

1. `apps/alpha_trigger/interface/views.py`
2. `apps/alpha_trigger/interface/urls.py`
3. `apps/beta_gate/interface/views.py`
4. `apps/decision_rhythm/interface/views.py`
5. `apps/decision_rhythm/interface/urls.py`

---

## 九、预期成果

完成本计划后，决策平台将具备：

1. ✅ **完整的 CRUD 界面** - 用户无需依赖 Django Admin
2. ✅ **直观的可视化** - 证伪规则、配额使用、版本对比
3. ✅ **统一的工作台** - 集中管理所有决策相关任务
4. ✅ **主动的告警** - 及时通知重要状态变化
5. ✅ **性能追踪** - 帮助用户优化触发器配置
6. ✅ **完整的文档** - 开发文档和用户指南

---

## 十、详细实现步骤

### Phase 1.1: Alpha Trigger 创建/编辑界面（详细）

#### 视图函数 (`apps/alpha_trigger/interface/views.py`)

需要添加三个模板视图函数：

```python
def alpha_trigger_create_view(request):
    """Alpha 触发器创建页面 - 参考 signal/manage.html 模式"""

def alpha_trigger_edit_view(request, trigger_id):
    """编辑触发器页面"""

def alpha_trigger_detail_view(request, trigger_id):
    """触发器详情页面 - 显示相关候选和事件"""
```

需要添加两个 API 视图类：

```python
class CreateTriggerFormView(APIView):
    """处理触发器创建表单提交"""

class UpdateTriggerFormView(APIView):
    """处理触发器更新表单提交"""
```

#### URL 路由 (`apps/alpha_trigger/interface/urls.py`)

```python
path("create/", alpha_trigger_create_view, name="create"),
path("edit/<str:trigger_id>/", alpha_trigger_edit_view, name="edit"),
path("detail/<str:trigger_id>/", alpha_trigger_detail_view, name="detail"),
```

#### 模板结构

- 复用 `signal/manage.html` 的样式和交互模式
- AI 助手集成（使用现有的 `ai_provider` 模块）
- 证伪条件构建器（参考条件构建器实现）
- HTMX + Alpine.js 实现动态表单

---

### Phase 1.2: Beta Gate 资产测试工具（详细）

#### 视图函数

```python
def beta_gate_test_view(request):
    """资产测试工具页面"""

class BetaGateTestAPIView(APIView):
    """资产测试 API - 支持批量测试"""
```

#### 功能实现

- 获取当前 Regime/Policy 状态显示
- 支持输入多个资产代码（每行一个）
- 调用 `EvaluateGateUseCase` 进行评估
- 返回每个资产的通过/拦截结果及原因

---

### Phase 1.3: Decision Rhythm 配额配置和重置（详细）

#### 视图函数

```python
def decision_rhythm_config_view(request):
    """配额配置页面"""

class UpdateQuotaConfigView(APIView):
    """更新配额配置"""

class ResetQuotaView(APIView):
    """重置配额"""
```

#### 功能实现

- 显示所有周期的配额配置
- 支持修改 max_decisions 和 max_executions
- 重置按钮（带确认对话框）
- 配额使用历史页面（最近 30 天趋势图）

---

## 十一、API 端点完整清单

### Alpha Trigger 模块

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/alpha-triggers/create/` | 创建页面 |
| GET | `/alpha-triggers/edit/<id>/` | 编辑页面 |
| GET | `/alpha-triggers/detail/<id>/` | 详情页面 |
| POST | `/api/alpha-triggers/form/create/` | 创建触发器（表单） |
| POST | `/api/alpha-triggers/form/update/<id>/` | 更新触发器（表单） |
| DELETE | `/api/alpha-triggers/triggers/<id>/` | 删除触发器 |
| POST | `/api/alpha-triggers/triggers/<id>/pause/` | 暂停触发器 |
| POST | `/api/alpha-triggers/triggers/<id>/resume/` | 恢复触发器 |

### Beta Gate 模块

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/beta-gate/test/` | 资产测试工具页面 |
| POST | `/api/beta-gate/test/` | 测试资产（支持批量） |
| GET | `/beta-gate/version/compare/` | 版本对比页面 |
| POST | `/api/beta-gate/config/rollback/<id>/` | 回滚到指定版本 |

### Decision Rhythm 模块

| 方法 | 路径 | 描述 |
|------|------|------|
| GET | `/decision-rhythm/config/` | 配额配置页面 |
| GET | `/decision-rhythm/history/` | 配额使用历史页面 |
| POST | `/api/decision-rhythm/quota/update/` | 更新配额配置 |
| POST | `/api/decision-rhythm/quota/reset/` | 重置配额 |
| DELETE | `/api/decision-rhythm/requests/<id>/` | 取消请求 |

---

## 十二、验收测试用例

### Alpha Trigger 创建界面

1. **创建成功测试** - 输入完整信息，验证创建成功并跳转详情页
2. **AI 助手测试** - 输入自然语言描述，验证生成正确的证伪条件
3. **表单验证测试** - 输入空资产代码，验证显示错误提示

### Beta Gate 测试工具

1. **单个资产测试** - 输入 000001.SH，验证显示通过/拦截结果
2. **批量测试** - 输入 10 个资产代码，验证所有结果正确显示

### Decision Rhythm 配额

1. **配置更新测试** - 修改配额值，验证更新成功
2. **配额重置测试** - 点击重置，验证 used_decisions 归零

---

## 十三、下一步行动

**立即开始: Phase 1.1 - Alpha Trigger 创建界面**

### 第一天任务

1. 添加视图函数 (`alpha_trigger/interface/views.py`)
2. 添加 URL 路由 (`alpha_trigger/interface/urls.py`)
3. 创建基础模板 (`alpha_trigger/templates/alpha_trigger/create.html`)

### 第二天任务

1. 添加表单 API 端点
2. 实现证伪条件构建器

### 第三天任务

1. 创建编辑和详情页面
2. 端到端测试

**预计完成时间**: 3-5 个工作日
