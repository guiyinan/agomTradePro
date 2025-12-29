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
