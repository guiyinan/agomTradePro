# Ruff Lint 技术债待办清单

> **基线日期**: 2026-05-12
> **基线版本**: `02c577f1` (dev/next-development)
> **当前工作区剩余**: 0
> **本轮总进展**: `303 -> 0`
> **门禁状态**: 已配置 `pyproject.toml` per-file-ignores + pre-commit

---

## 当前状态

`ruff check .` 已通过，当前工作区无剩余 Ruff lint 技术债。

## 本轮完成摘要

| 类别 | 变化 | 处理方式 |
|---|---:|---|
| F405 star-import | `99 -> 0` | 展开显式 import；对 Django settings 使用 per-file ignore |
| UP035 deprecated typing | `6 -> 0` | SDK 模块统一改为现代内建类型标注 |
| F401 unused-import | `123 -> 0` | 删除死导入；对副作用导入使用局部保留说明 |
| E402 import 位置 | `71 -> 0` | 纯风格问题上移；顺序敏感位置使用局部 `noqa` |
| F811 重复定义 | `4 -> 0` | 删除重复导入或保留单一来源 |
| 总量 | `303 -> 0` | 工作区 Ruff 零告警 |

## 本轮代表性处理

| 文件 | 结果 |
|---|---|
| `apps/decision_rhythm/interface/recommendation_api_views.py` | 移除 `workspace_api_support import *` |
| `apps/signal/infrastructure/providers.py` | 移除 `repositories import *` |
| `sdk/agomtradepro/modules/*` | 统一清理 docstring/import 顺序、旧 typing、死导入 |
| `core/settings/development.py` | 通过 `pyproject.toml` 的 per-file ignore 保留 Django settings 约定式导入 |
| `core/settings/production.py` | 同上 |
| `apps/policy/infrastructure/models.py` | 对底部 signal 注册 import 使用局部 `noqa: E402`，保留顺序语义 |
| `shared/infrastructure/*` | 清理通用基础设施中的未使用导入与探测型 import 噪音 |

## 后续维护约定

1. 新增代码继续保持 `ruff check .` 通过，不回退到 per-file ignore 扩散模式。
2. 对具备副作用或顺序语义的导入，优先写清楚注释并使用局部豁免，避免未来误删。
3. 若后续新增 SDK/MCP 模块，保持“模块 docstring 在最前、imports 紧随其后”的结构，避免再次产生批量 `E402`。

## 验证

```bash
ruff check .
```

结果：通过。
