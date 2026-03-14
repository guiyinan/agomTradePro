# API 路由迁移速查表

> **快速查找新旧路由对照关系**

## 一句话迁移规则

```
旧路由: /{module}/api/{resource}/ 或 /api/{module}/api/{resource}/
新路由: /api/{module}/{resource}/
```

## 快速对照表

| 功能 | 旧路由 | 新路由 |
|------|--------|--------|
| Regime 当前状态 | `/api/regime/api/current/` | `/api/regime/current/` |
| Signal 列表 | `/api/signal/api/` | `/api/signal/` |
| Signal 检查资格 | `/api/signal/api/check-eligibility/` | `/api/signal/check-eligibility/` |
| 宏观指标 | `/macro/api/supported-indicators/` | `/api/macro/supported-indicators/` |
| 政策事件 | `/policy/api/events/` | `/api/policy/events/` |
| 实时价格 | `/api/realtime/api/prices/` | `/api/realtime/prices/` |
| 账户组合 | `/account/api/portfolios/` | `/api/account/portfolios/` |
| 持仓明细 | `/account/api/positions/` | `/api/account/positions/` |
| Alpha 评分 | `/api/alpha/scores/` | `/api/alpha/scores/` ✅ 无需迁移 |
| 因子数据 | `/factor/api/` | `/api/factor/` |
| 轮动建议 | `/rotation/api/` | `/api/rotation/` |
| 对冲策略 | `/hedge/api/` | `/api/hedge/` |
| 策略执行 | `/strategy/api/` | `/api/strategy/` |
| 模拟交易 | `/simulated-trading/api/` | `/api/simulated-trading/` |
| 回测 | `/backtest/api/` | `/api/backtest/` |
| 审计 | `/audit/api/` | `/api/audit/` |
说明：新代码一律使用 `/api/audit/`。
| 仪表盘 | `/dashboard/api/v1/` | `/api/dashboard/v1/` |

## 时间节点

| 日期 | 事件 |
|------|------|
| **2026-03-04** | 新路由发布，旧路由标记 deprecated |
| **2026-04-01** | 旧路由进入只读模式（仅 GET） |
| **2026-06-01** | 旧路由完全移除 |

## SDK 用户

**无需修改代码**，升级 SDK 即可：

```bash
pip install --upgrade agomsaaf-sdk
```

## 直接 API 调用

替换 URL 路径：

```python
# Before
url = "http://api.example.com/regime/api/current/"

# After
url = "http://api.example.com/api/regime/current/"
```

## 完整文档

详见 [API 路由迁移指南](./route-migration-guide.md)

---

**最后更新**: 2026-03-04
