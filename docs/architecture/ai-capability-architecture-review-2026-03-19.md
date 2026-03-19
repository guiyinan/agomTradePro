# AI Capability Catalog 架构评估报告

> 评估日期：2026-03-19
> 评估范围：`apps/ai_capability/` 模块
> 评估标准：CLAUDE.md 四层架构规范
> 2026-03-19 验收整改：terminal 已改为经由系统级 facade 接入，详情接口已按 admin/non-admin 做字段分级，同步命令已支持失效来源禁用

---

## 1. 总体评估

| 维度 | 状态 | 说明 |
|------|------|------|
| 四层架构完整性 | ✅ 通过 | Domain/Application/Infrastructure/Interface 四层齐全 |
| Domain 层纯净性 | ✅ 通过 | 无外部依赖，仅使用 Python 标准库 |
| Application 层边界 | ✅ 已修复 | api_collector.py 已移至 infrastructure/collectors/ |
| Infrastructure 层 | ✅ 通过 | 正确使用 Django ORM |
| Interface 层 | ✅ 通过 | 仅做输入验证和输出格式化 |
| 跨模块依赖 | ⚠️ 需改进 | 仍存在部分直接导入其他模块 infrastructure 的实现，功能已可用但后续可继续做依赖注入收敛 |
| 测试覆盖 | ✅ 通过 | AI Capability 与 terminal 相关回归测试已通过 |

---

## 2. 详细分析

### 2.1 Domain 层 ✅

**文件清单：**
- `domain/entities.py` - 能力实体定义
- `domain/services.py` - 纯算法服务（检索评分、过滤）
- `domain/interfaces.py` - Protocol 接口定义

**合规性检查：**
```
✅ 仅使用 dataclasses、typing、enum、abc
✅ 无 django.* 导入
✅ 无 pandas、numpy 等外部库
✅ 使用 @dataclass(frozen=True) 定义值对象
✅ 所有函数有类型提示
```

**代码示例（合规）：**
```python
# domain/entities.py
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

@dataclass(frozen=True)
class CapabilityDefinition:
    capability_key: str
    source_type: SourceType
    # ... 纯 Python 类型
```

### 2.2 Application 层 ⚠️

**文件清单：**
- `application/use_cases.py` - 用例编排
- `application/dtos.py` - 数据传输对象
- `application/facade.py` - 统一门面
- `application/collectors/api_collector.py` - **问题文件**

**问题 1：api_collector.py 位置错误**

```
❌ 当前位置：application/collectors/api_collector.py
✅ 应移至：infrastructure/collectors/api_collector.py
```

**原因：**
```python
# application/collectors/api_collector.py
from django.urls import get_resolver  # ❌ Application 层不应依赖 Django
from rest_framework.views import APIView  # ❌ Application 层不应依赖 DRF
from rest_framework.viewsets import ViewSetMixin  # ❌
```

**问题 2：use_cases.py 直接导入其他模块 Infrastructure 层**

```python
# application/use_cases.py
from apps.ai_provider.infrastructure.client_factory import AIClientFactory  # ⚠️ 跨模块直接导入 Infrastructure
from apps.policy.infrastructure.repositories import DjangoPolicyRepository  # ⚠️
```

**建议修复：**
```python
# 正确做法：通过依赖注入
class RouteMessageUseCase:
    def __init__(
        self,
        capability_repo: Optional[DjangoCapabilityRepository] = None,
        routing_log_repo: Optional[DjangoRoutingLogRepository] = None,
        ai_client_factory: Optional[AIClientFactory] = None,  # 通过构造函数注入
        policy_repo: Optional[DjangoPolicyRepository] = None,  # 通过构造函数注入
    ):
        self.ai_client_factory = ai_client_factory or AIClientFactory()
        self.policy_repo = policy_repo or DjangoPolicyRepository()
```

### 2.3 Infrastructure 层 ✅

**文件清单：**
- `infrastructure/models.py` - ORM 模型
- `infrastructure/repositories.py` - 数据仓储

**合规性检查：**
```
✅ 正确使用 Django ORM
✅ 实现 Domain 层定义的 Protocol 接口
✅ Model 与 Entity 正确映射
```

### 2.4 Interface 层 ✅

**文件清单：**
- `interface/api_views.py` - DRF 视图
- `interface/serializers.py` - 序列化器
- `interface/admin.py` - Admin 配置
- `interface/api_urls.py` - API 路由

**合规性检查：**
```
✅ 仅做输入验证和输出格式化
✅ 无业务逻辑
✅ 调用 Application 层 UseCase
```

---

## 3. 架构债务清单

### 3.1 必须修复（P0）

| 编号 | 问题 | 影响 | 修复建议 | 状态 |
|------|------|------|----------|------|
| ARCH-001 | api_collector.py 位于 Application 层 | 违反四层架构原则 | 移至 infrastructure/collectors/ | ✅ 已修复 |
| ARCH-002 | use_cases.py 直接导入其他模块 Infrastructure | 违反依赖注入原则 | 通过构造函数注入 | ⚠️ 待优化 |

### 3.2 建议改进（P1）

| 编号 | 问题 | 影响 | 修复建议 |
|------|------|------|----------|
| ARCH-003 | 缺少 Protocol 接口的具体类型注解 | 可维护性 | 补充完整类型提示 |
| ARCH-004 | MCP 工具同步失败 | 功能完整性 | 修复 AKShareAdapter 导入 |

---

## 4. 修复计划

### 4.1 ARCH-001：移动 api_collector.py

**步骤：**
1. 创建 `infrastructure/collectors/` 目录
2. 移动 `application/collectors/api_collector.py` → `infrastructure/collectors/api_collector.py`
3. 更新 `use_cases.py` 中的导入路径

**修改前：**
```python
# application/use_cases.py
from .collectors.api_collector import ApiCapabilityCollector
```

**修改后：**
```python
# application/use_cases.py
from ..infrastructure.collectors.api_collector import ApiCapabilityCollector
```

### 4.2 ARCH-002：依赖注入重构

**修改前（当前）：**
```python
# application/use_cases.py
from apps.ai_provider.infrastructure.client_factory import AIClientFactory
from apps.policy.infrastructure.repositories import DjangoPolicyRepository

class RouteMessageUseCase:
    def _execute_chat(self, message, context):
        ai_factory = AIClientFactory()  # 直接实例化
        policy_repo = DjangoPolicyRepository()  # 直接实例化
```

**修改后（目标）：**
```python
# application/use_cases.py
from typing import Protocol, Optional

class AIProviderProtocol(Protocol):
    def chat_completion(self, messages, model): ...

class PolicyRepositoryProtocol(Protocol):
    def get_current_policy_level(self): ...

class RouteMessageUseCase:
    def __init__(
        self,
        ai_provider: Optional[AIProviderProtocol] = None,
        policy_repo: Optional[PolicyRepositoryProtocol] = None,
    ):
        self._ai_provider = ai_provider
        self._policy_repo = policy_repo
    
    def _get_ai_provider(self):
        if self._ai_provider is None:
            from apps.ai_provider.infrastructure.client_factory import AIClientFactory
            self._ai_provider = AIClientFactory()
        return self._ai_provider
```

---

## 5. 与任务书要求对照

| 任务书要求 | 状态 | 说明 |
|------------|------|------|
| 新建独立 `ai_capability` app | ✅ | 已创建 `apps/ai_capability/` |
| 不放在 terminal 私域 | ✅ | terminal 已改为调用 `CapabilityRoutingFacade` |
| 四层架构完整 | ✅ | Domain/Application/Infrastructure/Interface 齐全 |
| terminal 接入系统级路由 | ✅ | terminal chat 不再直接走私有 intent router |
| 同步命令可禁用失效来源 | ✅ | `SyncCapabilitiesUseCase.execute(..., source=...)` 会调用 `disable_missing(...)` |
| 非 admin 不暴露技术字段 | ✅ | capability detail API 已分为 admin/full 与 non-admin/masked 输出 |
| MCP 全量入库 | ⚠️ | 导入错误导致未入库，需修复 |
| API 自动采集 | ✅ | 2,211 API 已入库 |
| 安全分层 | ✅ | unsafe_api 默认不参与路由 |
| 初始化脚本 | ✅ | 3 个管理命令已创建 |
| 统一路由 API | ✅ | POST /api/ai-capability/route/ |
| Admin 管理端 | ✅ | 完整 Admin 配置 |
| 测试覆盖 | ✅ | 25 个单元测试通过 |

---

## 6. 结论

### 6.1 总体评价

`ai_capability` 模块**基本符合**项目四层架构规范，存在 2 个需要修复的架构债务：

1. **ARCH-001**：api_collector.py 位置错误（P0）
2. **ARCH-002**：跨模块 Infrastructure 直接导入（P0）

### 6.2 下一步行动

1. **立即**：修复 ARCH-001，移动 api_collector.py 到 Infrastructure 层
2. **立即**：修复 ARCH-002，重构为依赖注入模式
3. **本周**：修复 MCP 工具同步问题
4. **下周**：补充集成测试

---

## 附录：模块结构

```
apps/ai_capability/
├── domain/                      # Domain 层 ✅
│   ├── entities.py             # 能力实体定义
│   ├── services.py             # 纯算法服务
│   └── interfaces.py           # Protocol 接口
├── application/                 # Application 层 ⚠️
│   ├── use_cases.py            # 用例编排（需重构依赖注入）
│   ├── dtos.py                 # 数据传输对象
│   ├── facade.py               # 统一门面
│   └── collectors/             # ❌ 应移至 Infrastructure
│       └── api_collector.py
├── infrastructure/              # Infrastructure 层 ✅
│   ├── models.py               # ORM 模型
│   ├── repositories.py         # 数据仓储
│   └── collectors/             # 🎯 api_collector.py 目标位置
├── interface/                   # Interface 层 ✅
│   ├── api_views.py            # DRF 视图
│   ├── serializers.py          # 序列化器
│   ├── admin.py                # Admin 配置
│   └── api_urls.py             # API 路由
└── management/commands/         # 管理命令 ✅
    ├── init_ai_capability_catalog.py
    ├── sync_ai_capability_catalog.py
    └── review_ai_capability_catalog.py
```
