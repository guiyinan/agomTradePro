# AI 模块边界与依赖

更新时间：2026-03-18

## 目标

明确 `apps/ai_provider`、`apps/prompt`、`apps/terminal` 以及相关 AI 消费模块的职责边界，避免再次出现跨模块接口层依赖、模型残留和命名混乱。

## 当前边界

### `apps/ai_provider`

职责：
- 管理 AI 服务商配置、密钥、可用模型、预算和调用适配
- 提供统一客户端工厂 `AIClientFactory`
- 负责单 provider 客户端和 failover 客户端装配

### `apps/prompt`

职责：
- 管理 Prompt 模板、链式编排、执行日志
- 消费 `ai_provider` 提供的 AI 客户端
- 通过 `provider_ref` 选择 AI 服务商

约束：
- 不定义自己的 `AIClientFactory`
- 不承载 `terminal` 的 ORM 模型

### `apps/terminal`

职责：
- 管理终端命令定义和执行
- 支持 `prompt` 类型命令和 `api` 类型命令
- 自己持有 `TerminalCommandORM`

约束：
- 不依赖 `apps.prompt.interface`
- 仅在数据层通过 `PromptTemplateORM` 与 `prompt` 建立可选关联
- AI 能力统一从 `ai_provider` 获取

## 允许的依赖方向

```text
prompt -> ai_provider
terminal -> ai_provider
terminal -> prompt (仅限 PromptTemplateORM 关联和 Prompt 概念复用)
strategy -> ai_provider
simulated_trading -> ai_provider
```

禁止的依赖方向：

```text
terminal -> prompt.interface
terminal -> prompt 内部 AIClientFactory
prompt -> terminal
```

## Provider 选择器约定

统一使用 `provider_ref` 表示“AI provider 选择器”。

允许值：
- provider 名称，例如 `openai-main`
- provider 主键 ID，例如 `1`
- 空值，表示由 `AIClientFactory` 自动走 active providers failover

兼容规则：
- 旧字段 `provider_name` 暂时保留，仅作为兼容别名
- 新代码一律优先使用 `provider_ref`

## 本次整改结果

- `TerminalCommandORM` 已迁移到 `apps/terminal/infrastructure/models.py`
- `AIClientFactory` 已统一迁移到 `apps/ai_provider/infrastructure/client_factory.py`
- `prompt`、`terminal`、`strategy`、`simulated_trading` 已改为统一依赖 `ai_provider`
- `prompt` 执行相关请求对象开始统一使用 `provider_ref`
