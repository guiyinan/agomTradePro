# AgomSAAF 开发禁令

> **版本**: V1.0
> **基线日期**: 2026-03-18
> **文档性质**: 治理约束规范
> **强制执行**: 所有代码变更

---

## ⚠️ 核心原则

**为什么需要禁令？**

1. 防止系统失控（32个模块已足够复杂）
2. 保持架构边界清晰
3. 避免重复造轮子
4. 确保单一叙事来源

**违规后果**：
- ❌ PR 拒绝合并
- ❌ 回滚代码
- ❌ 架构评审

---

## 🚫 禁令清单

### 禁令 1：暂停新增横向模块

**内容**：禁止新增独立的业务模块

**现状**：32个业务模块已覆盖所有核心场景

**例外**：
- ✅ 允许拆分现有模块（如 `account`）
- ✅ 允许新增技术性组件（放到 `shared/`）
- ✅ 允许新增 AI Agent 工具（通过 MCP 扩展）

**理由**：
- 当前模块数量已达到临界点
- 新增模块会增加依赖复杂度
- 优先优化现有模块

**执行时间**：即日起生效

---

### 禁令 2：shared/ 禁止堆放业务实体

**内容**：`shared/` 目录只允许放置纯技术性组件

**允许的内容**：
- ✅ Protocol 接口定义（`RepositoryProtocol`, `FilterProtocol`）
- ✅ 纯算法实现（`KalmanFilter`, `HPFilter`）
- ✅ 配置管理（`secrets.py`, `settings_loader.py`）
- ✅ 工具函数（`date_utils.py`, `validators.py`）

**禁止的内容**：
- ❌ 业务实体（`AssetScore`, `RegimeState`）
- ❌ 业务规则（`RegimeMatcher`, `PolicyMatcher`）
- ❌ Django Model（ORM 模型）
- ❌ API 视图（DRF ViewSet）

**理由**：
- `shared/` 应该是无状态的、可复用的技术组件
- 业务实体必须在 `apps/*/domain/` 中定义
- 避免循环依赖

**检查方式**：
```bash
# 检查 shared/ 是否导入了 apps/
grep -r "from apps\." shared/
```

**执行时间**：即日起生效

---

### 禁令 3：规则不得散落在多个模块重复定义

**内容**：业务规则必须在唯一位置定义

**违规示例**：
```python
# ❌ 错误：在多个模块重复定义
# apps/regime/domain/rules.py
REGIME_THRESHOLDS = {"growth": 0.5, "inflation": 0.3}

# apps/signal/domain/rules.py
REGIME_THRESHOLDS = {"growth": 0.5, "inflation": 0.3}  # 重复！
```

**正确做法**：
```python
# ✅ 正确：在单一位置定义，其他模块导入
# apps/regime/domain/rules.py
REGIME_THRESHOLDS = {"growth": 0.5, "inflation": 0.3}

# apps/signal/domain/rules.py
from apps.regime.domain.rules import REGIME_THRESHOLDS
```

**例外**：
- ✅ 允许模块内部规则（私有规则）
- ✅ 允许配置化规则（从数据库读取）

**理由**：
- 避免规则不一致
- 方便统一修改
- 保持单一叙事

**检查方式**：
```bash
# 检查是否有重复的规则定义
grep -r "THRESHOLD\|THRESHOLDS\|RULES" apps/*/domain/
```

**执行时间**：即日起生效

---

### 禁令 4：外部能力统一走 SDK/MCP/API 收口

**内容**：所有外部能力接入必须通过统一接口

**已收口的能力**：

| 能力 | 收口方式 | 位置 |
|------|----------|------|
| **市场数据** | `market_data` 统一接口 | `apps/market_data/` |
| **AI 服务** | `ai_provider` 统一管理 | `apps/ai_provider/` |
| **Python SDK** | `sdk/agomsaaf` | `sdk/agomsaaf/` |
| **MCP Server** | `sdk/agomsaaf_mcp` | `sdk/agomsaaf_mcp/` |

**禁止的做法**：
- ❌ 直接调用第三方 API（如 `requests.get("https://api.xxx.com")`)
- ❌ 直接使用外部库（如 `import openai`）
- ❌ 在多个模块重复实现相同功能

**正确做法**：
```python
# ✅ 正确：通过统一接口
from apps.market_data import MarketDataProvider

data = MarketDataProvider().get_price("000001.SZ")
```

**理由**：
- 统一错误处理
- 统一监控告警
- 方便切换实现
- 避免重复代码

**检查方式**：
```bash
# 检查是否有直接的外部 API 调用
grep -r "requests\\.get\|requests\\.post" apps/ --exclude-dir=infrastructure
```

**执行时间**：即日起生效

---

### 禁令 5：account 模块重构前禁止新增依赖

**内容**：`account` 模块当前依赖 14 个模块，禁止继续增加依赖

**现状**：
```
account (依赖 14 个模块)
    ↓ 依赖
audit, backtest, decision_rhythm, equity, events, factor, 
hedge, macro, prompt, regime, rotation, signal, 
simulated_trading, strategy
```

**建议拆分方案**：
```
account (当前)
    ↓ 拆分为
├── user/           # 用户管理 (依赖: 0)
├── portfolio/      # 投资组合管理 (依赖: 3-4)
├── position/       # 持仓管理 (依赖: 2-3)
└── capital/        # 资金管理 (依赖: 2-3)
```

**临时规则**：
- ❌ 禁止在 `account` 中新增对其他模块的依赖
- ✅ 允许通过依赖注入使用其他模块
- ✅ 允许通过事件系统解耦

**理由**：
- 单一模块依赖过多违反单一职责原则
- 变更影响面大
- 测试困难

**执行时间**：直至 account 模块重构完成

---

## 📋 执行检查清单

每次 PR 提交前，请确认：

- [ ] ✅ 未新增独立业务模块（禁令 1）
- [ ] ✅ 未在 `shared/` 放置业务实体（禁令 2）
- [ ] ✅ 未重复定义业务规则（禁令 3）
- [ ] ✅ 未直接调用外部 API（禁令 4）
- [ ] ✅ 未在 `account` 新增依赖（禁令 5）

---

## 🔍 自动化检查

### CI 门禁（建议添加）

```yaml
# .github/workflows/governance-check.yml
name: Governance Check

on: [pull_request]

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      
      - name: Check shared/ imports
        run: |
          if grep -r "from apps\." shared/; then
            echo "❌ shared/ 不应依赖 apps/"
            exit 1
          fi
      
      - name: Check external API calls
        run: |
          if grep -r "requests\\.get\|requests\\.post" apps/ --exclude-dir=infrastructure; then
            echo "❌ 禁止直接调用外部 API"
            exit 1
          fi
      
      - name: Check account dependencies
        run: |
          # 统计 account 的依赖数
          deps=$(grep -r "from apps\." apps/account/ | wc -l)
          if [ $deps -gt 14 ]; then
            echo "❌ account 依赖数超过 14"
            exit 1
          fi
```

---

## 📚 相关文档

| 文档 | 说明 |
|------|------|
| `docs/governance/SYSTEM_BASELINE.md` | 系统基线 |
| `docs/governance/MODULE_CLASSIFICATION.md` | 模块分级表 |
| `docs/development/module-ledger.md` | 模块账本（边界规则） |
| `docs/architecture/MODULE_DEPENDENCIES.md` | 模块依赖关系 |
| `CLAUDE.md` | 项目开发规则 |

---

## 📝 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-18 | V1.0 | 初始版本，建立 5 条核心禁令 |

---

**维护者**: AgomSAAF Team
**最后更新**: 2026-03-18
**执行状态**: 即日起生效
