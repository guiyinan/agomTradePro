# AI接口管理器 - 需求文档

## 1. 概述

### 1.1 背景

AgomSAAF系统需要集成AI能力用于数据分析和决策支持。当前主流AI服务提供商（OpenAI、DeepSeek、通义千问等）大多采用OpenAI API兼容范式，可以通过统一的接口规范进行访问。

### 1.2 目标

构建一个统一的AI接口管理器，实现：
- 支持多个AI提供商的配置和管理
- 统一的调用接口和错误处理
- 使用量追踪和成本控制
- 灵活的故障转移机制

## 2. 功能需求

### 2.1 提供商配置管理

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 添加提供商 | 支持添加新的AI提供商配置 | P0 |
| 编辑配置 | 修改提供商的API Key、Base URL等 | P0 |
| 启用/禁用 | 控制提供商的可用状态 | P0 |
| 优先级设置 | 设置提供商的调用优先级（用于故障转移） | P1 |
| 预算控制 | 设置每日/每月消费限制 | P1 |

### 2.2 API调用

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 聊天补全 | 支持chat completion接口 | P0 |
| 模型选择 | 指定使用的模型 | P0 |
| 参数配置 | temperature、max_tokens等参数 | P1 |
| 流式输出 | 支持stream模式（暂不实现） | P2 |

### 2.3 使用统计

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 调用日志 | 记录每次API调用 | P0 |
| Token统计 | 记录输入/输出token数量 | P0 |
| 成本估算 | 根据token计算预估成本 | P0 |
| 响应时间 | 记录API响应时间 | P1 |
| 成功率统计 | 统计成功/失败比例 | P1 |

### 2.4 前端界面

| 功能 | 描述 | 优先级 |
|------|------|--------|
| 管理页面 | 查看和编辑提供商配置 | P0 |
| 统计展示 | 展示使用统计和成本 | P0 |
| 日志查看 | 查看API调用日志 | P1 |
| 详情页面 | 单个提供商的详细统计 | P1 |

## 3. 非功能需求

### 3.1 架构约束

- **四层架构**: 严格遵循Domain-Application-Infrastructure-Interface分层
- **Domain层**: 只使用Python标准库
- **依赖注入**: Application层通过依赖注入使用Infrastructure层

### 3.2 性能要求

- API调用响应时间记录精确到毫秒
- 日志查询支持分页和索引优化

### 3.3 安全要求

- API Key存储在数据库中（生产环境应加密）
- 日志中不记录敏感请求内容

### 3.4 可扩展性

- 支持添加新的AI提供商（只需配置Base URL）
- 支持自定义模型定价

## 4. 预设提供商

系统预设以下主流AI提供商的配置模板：

| 提供商 | 类型 | Base URL | 默认模型 |
|--------|------|----------|----------|
| OpenAI | openai | https://api.openai.com/v1 | gpt-3.5-turbo |
| DeepSeek | deepseek | https://api.deepseek.com/v1 | deepseek-chat |
| 通义千问 | qwen | https://dashscope.aliyuncs.com/compatible-mode/v1 | qwen-turbo |
| Moonshot | moonshot | https://api.moonshot.cn/v1 | moonshot-v1-8k |

用户可以基于这些模板创建自己的配置，或添加自定义提供商。

## 5. 数据模型

### 5.1 AI提供商配置 (AIProviderConfig)

| 字段 | 类型 | 说明 |
|------|------|------|
| name | string | 配置名称（唯一） |
| provider_type | string | 提供商类型 |
| is_active | boolean | 是否启用 |
| priority | int | 优先级（越小越优先） |
| base_url | string | API Base URL |
| api_key | string | API密钥 |
| default_model | string | 默认模型 |
| daily_budget_limit | decimal | 每日预算限制 |
| monthly_budget_limit | decimal | 每月预算限制 |
| extra_config | json | 额外配置 |

### 5.2 AI调用日志 (AIUsageLog)

| 字段 | 类型 | 说明 |
|------|------|------|
| provider | foreignkey | 关联提供商 |
| model | string | 使用的模型 |
| request_type | string | 请求类型 |
| prompt_tokens | int | 输入token数 |
| completion_tokens | int | 输出token数 |
| total_tokens | int | 总token数 |
| estimated_cost | decimal | 预估成本 |
| response_time_ms | int | 响应时间（毫秒） |
| status | string | 状态 |
| error_message | text | 错误信息 |
| created_at | datetime | 创建时间 |

## 6. 用户角色

| 角色 | 权限 |
|------|------|
| 管理员 | 查看和管理所有AI提供商配置 |
| 普通用户 | 仅查看统计信息（暂不实现） |

## 7. 未来扩展

- [ ] 支持函数调用 (Function Calling)
- [ ] 支持多模态（图片、语音）
- [ ] 支持Embedding接口
- [ ] 实现流式输出
- [ ] API Key加密存储
- [ ] 自动故障转移
- [ ] 提供商健康检查

# AI接口管理器 - 实施文档

## 1. 架构设计

### 1.1 四层架构

```
apps/ai_provider/
├── domain/           # Domain层：纯Python实体和业务规则
│   ├── entities.py   # 值对象定义
│   └── services.py   # 成本计算服务
├── infrastructure/   # Infrastructure层：ORM和外部适配器
│   ├── models.py     # Django ORM模型
│   ├── repositories.py # 数据仓储
│   └── adapters.py   # OpenAI兼容适配器
└── interface/        # Interface层：视图和模板
    ├── views/
    │   └── page_views.py
    ├── urls.py
    ├── admin.py
    └── serializers.py
```

### 1.2 技术选型

| 组件 | 技术 | 说明 |
|------|------|------|
| ORM | Django ORM | 与现有项目保持一致 |
| HTTP客户端 | openai (官方SDK) | 支持OpenAI兼容API |
| 前端 | Django模板 | 与现有项目保持一致 |

## 2. 核心实现

### 2.1 Domain层

**entities.py** - 纯Python值对象
```python
@dataclass(frozen=True)
class AIProviderConfig:
    name: str
    provider_type: AIProviderType
    base_url: str
    api_key: str
    default_model: str
    is_active: bool
    priority: int
    ...
```

**services.py** - 成本计算
```python
class AICostCalculator:
    MODEL_PRICING = {
        "gpt-4": {"input": 0.03, "output": 0.06},
        "deepseek-chat": {"input": 0.0001, "output": 0.0002},
        ...
    }
```

### 2.2 Infrastructure层

**adapters.py** - OpenAI兼容适配器
```python
class OpenAICompatibleAdapter:
    def __init__(self, base_url: str, api_key: str):
        self.client = OpenAI(base_url=base_url, api_key=api_key)

    def chat_completion(self, messages, model, ...):
        response = self.client.chat.completions.create(...)
        return {...}
```

**repositories.py** - 数据仓储
```python
class AIProviderRepository:
    def get_active_providers(self):
        return AIProviderConfig.objects.filter(is_active=True)

class AIUsageRepository:
    def log_usage(self, provider, ...):
        return AIUsageLog.objects.create(...)
```

### 2.3 Interface层

**page_views.py** - 页面视图
```python
def ai_manage_view(request):
    providers = provider_repo.get_active_providers()
    # 获取统计信息
    return render(request, 'ai_provider/manage.html', context)
```

## 3. 数据库表结构

### 3.1 ai_provider_config

```sql
CREATE TABLE ai_provider_config (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(50) UNIQUE NOT NULL,
    provider_type VARCHAR(20) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    priority INT DEFAULT 10,
    base_url VARCHAR(500) NOT NULL,
    api_key VARCHAR(500) NOT NULL,
    default_model VARCHAR(50) DEFAULT 'gpt-3.5-turbo',
    daily_budget_limit DECIMAL(10,2),
    monthly_budget_limit DECIMAL(12,2),
    extra_config JSON,
    description TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_used_at DATETIME,

    INDEX idx_provider_active (provider_type, is_active),
    INDEX idx_priority (is_active, priority)
);
```

### 3.2 ai_usage_log

```sql
CREATE TABLE ai_usage_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    provider_id BIGINT NOT NULL,
    model VARCHAR(50) NOT NULL,
    request_type VARCHAR(20) DEFAULT 'chat',
    prompt_tokens INT DEFAULT 0,
    completion_tokens INT DEFAULT 0,
    total_tokens INT DEFAULT 0,
    estimated_cost DECIMAL(10,6) NOT NULL,
    response_time_ms INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    request_metadata JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (provider_id) REFERENCES ai_provider_config(id),
    INDEX idx_provider_created (provider_id, created_at),
    INDEX idx_model_created (model, created_at)
);
```

## 4. API接口

### 4.1 页面路由

| 路由 | 功能 |
|------|------|
| /ai/ | 管理页面 |
| /ai/logs/ | 日志页面 |
| /ai/detail/<id>/ | 详情页面 |

### 4.2 Django Admin

- AI提供商配置：`/admin/ai_provider/aiproviderconfig/`
- AI调用日志：`/admin/ai_provider/aiusagelog/`

## 5. 使用示例

### 5.1 添加提供商配置

1. 访问 `/admin/ai_provider/aiproviderconfig/add/`
2. 填写配置信息：
   - 名称: `deepseek-primary`
   - 类型: `deepseek`
   - Base URL: `https://api.deepseek.com/v1`
   - API Key: `your-api-key`
   - 默认模型: `deepseek-chat`
3. 保存

### 5.2 调用AI接口

```python
from apps.ai_provider.infrastructure.adapters import OpenAICompatibleAdapter
from apps.ai_provider.infrastructure.repositories import (
    AIProviderRepository,
    AIUsageRepository
)

# 获取提供商配置
provider_repo = AIProviderRepository()
provider = provider_repo.get_by_name('deepseek-primary')

# 创建适配器
adapter = OpenAICompatibleAdapter(
    base_url=provider.base_url,
    api_key=provider.api_key,
    default_model=provider.default_model
)

# 调用API
result = adapter.chat_completion(
    messages=[{"role": "user", "content": "你好"}],
    temperature=0.7
)

# 记录日志
usage_repo = AIUsageRepository()
usage_repo.log_usage(
    provider=provider,
    model=result['model'],
    prompt_tokens=result['prompt_tokens'],
    completion_tokens=result['completion_tokens'],
    total_tokens=result['total_tokens'],
    estimated_cost=...,
    response_time_ms=result['response_time_ms'],
    status=result['status']
)
```

## 6. 部署清单

### 6.1 依赖安装

```bash
agomsaaf/Scripts/pip install openai
```

### 6.2 数据库迁移

```bash
agomsaaf/Scripts/python manage.py makemigrations ai_provider
agomsaaf/Scripts/python manage.py migrate ai_provider
```

### 6.3 验证

1. 启动开发服务器: `python manage.py runserver`
2. 访问管理页面: `http://127.0.0.1:8000/ai/`
3. 添加一个AI提供商配置
4. 访问Django Admin确认配置

## 7. 故障排查

### 7.1 常见问题

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| ImportError: No module named 'openai' | 未安装openai库 | 运行 `pip install openai` |
| 401 Authentication Error | API Key错误 | 检查API Key配置 |
| 连接超时 | Base URL错误或网络问题 | 检查Base URL和网络 |

### 7.2 调试

```python
# 检查适配器是否可用
adapter = OpenAICompatibleAdapter(...)
print(adapter.is_available())  # 应返回True
```

## 8. 更新记录

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2025-12-29 | 1.0 | 初始版本 |
