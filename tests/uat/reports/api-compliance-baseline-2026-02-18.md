# API 合规性基线报告

**报告日期**: 2026-02-18
**测试类型**: API 路由命名规范合规性
**测试人员**: QA Engineer

---

## 1. 执行摘要

### 1.1 合规性评估

| 指标 | 目标值 | 当前值 | 状态 |
|------|--------|--------|------|
| API 路由规范覆盖率 | 100% | ~0% | ❌ FAIL |
| 符合规范的路由数 | - | 0 | ❌ |
| 需要治理的路由数 | 0 | ~410 | ❌ |
| 合规性百分比 | 100% | 0% | ❌ FAIL |

### 1.2 关键发现

**发现**: 所有 API 路由使用 `/module/api/` 模式，不符合 PRD 要求的 `/api/module/` 规范。

**影响**:
- Task #10 (API 路由治理) 可能未按预期完成
- 需要重新评估 M2 里程碑的完成状态
- 前端 API 调用需要同步更新

---

## 2. API 路由模式分析

### 2.1 当前模式

所有 API 路由使用以下模式：

```
/account/api/profile/           ❌
/account/api/portfolios/        ❌
/account/api/positions/         ❌
/account/api/transactions/      ❌
/account/api/capital-flows/     ❌
/account/api/assets/            ❌
```

### 2.2 目标模式

PRD 要求的规范模式：

```
/api/account/profile/           ✅
/api/account/portfolios/        ✅
/api/account/positions/         ✅
/api/account/transactions/      ✅
/api/account/capital-flows/     ✅
/api/account/assets/            ✅
```

---

## 3. 模块级分析

### 3.1 Account 模块

| 端点组 | 当前模式 | 目标模式 | 数量 |
|--------|----------|----------|------|
| Portfolios | `/account/api/portfolios/` | `/api/account/portfolios/` | 6 |
| Positions | `/account/api/positions/` | `/api/account/positions/` | 5 |
| Transactions | `/account/api/transactions/` | `/api/account/transactions/` | 4 |
| Capital Flows | `/account/api/capital-flows/` | `/api/account/capital-flows/` | 4 |
| Assets | `/account/api/assets/` | `/api/account/assets/` | 5 |
| Categories | `/account/api/categories/` | `/api/account/categories/` | 9 |
| Currencies | `/account/api/currencies/` | `/api/account/currencies/` | 6 |
| Exchange Rates | `/account/api/exchange-rates/` | `/api/account/exchange-rates/` | 6 |

**Account 模块小计**: ~45 个 API 端点需要迁移

### 3.2 其他模块

需要进一步分析以下模块的 API 路由：
- Policy
- Signal
- Macro
- Regime
- Equity
- Fund
- Backtest
- Simulated Trading
- Audit
- Sector
- Filter
- Strategy
- Factor
- Rotation
- Hedge

---

## 4. 符合规范的路由

以下路由已符合 `/api/module/` 规范：

| 路由 | 模块 | 状态 |
|------|------|------|
| `/api/health/` | core | ✅ PASS |
| `/api/debug/server-logs/stream/` | core | ✅ PASS |
| `/api/debug/server-logs/export/` | core | ✅ PASS |
| `/api/schema/` | core | ✅ PASS |
| `/api/docs/` | core | ✅ PASS |
| `/api/redoc/` | core | ✅ PASS |
| `/api/alpha/` | alpha | ✅ PASS |

**符合规范的路由总数**: ~7

---

## 5. 前端调用影响分析

### 5.1 需要更新的调用点

如果进行 API 路由迁移，需要更新以下位置的调用：

| 位置 | 示例 | 目标 |
|------|------|------|
| JavaScript fetch | `fetch('/account/api/portfolios/')` | `fetch('/api/account/portfolios/')` |
| jQuery ajax | `$.ajax('/account/api/positions/')` | `$.ajax('/api/account/positions/')` |
| 模板 href | `href="/account/api/assets/"` | `href="/api/account/assets/"` |

### 5.2 搜索关键词

建议在代码库中搜索以下模式：
- `'/account/api/`
- `"/account/api/`
- `account/api/`
- 类似的模块级 API 路径

---

## 6. 迁移建议

### 6.1 迁移策略

**阶段 1**: 双路由并行
```python
# 新路由 (推荐)
path('api/', include(router.urls))  # 在 core/urls.py 中

# 旧路由 (保留兼容)
path('account/api/', include(router.urls))  # 标记为 deprecated
```

**阶段 2**: 前端迁移
- 更新所有前端调用
- 添加迁移脚本
- 监控错误日志

**阶段 3**: 移除旧路由
- 发布通知
- 等待一个稳定版本
- 完全移除旧路由

### 6.2 优先级

| 优先级 | 模块 | 理由 |
|--------|------|------|
| P0 | Account | 核心模块，使用频繁 |
| P1 | Signal, Policy | 关键业务模块 |
| P2 | 其他模块 | 按使用频率排序 |

---

## 7. 验收标准对比

### 7.1 PRD 要求

根据 `docs/plans/ui-ux-improvement-prd-2026-02-18.md`:

> **Epic C：页面/API 命名治理（P0，一步到位）**
> - 新增接口 100% 按规范命名
> - 存量接口 100% 完成命名治理（含低频接口），无遗留灰区

### 7.2 当前状态

| 要求 | 状态 |
|------|------|
| 新增接口 100% 按规范命名 | ❌ 未验证 |
| 存量接口 100% 完成治理 | ❌ ~0% 完成 |
| OpenAPI 与接口文档同步 | ⚠️ 需验证 |
| 前后端联调清单无阻塞 | ⚠️ 需验证 |

---

## 8. 风险与问题

### 8.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 大量路由迁移 | 可能引入回归 | 分阶段迁移，充分测试 |
| 前端调用遗漏 | 功能失效 | 全代码搜索 + 人工审查 |
| 文档未同步 | 开发者困惑 | 自动化文档生成 |

### 8.2 项目风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Task #10 完成度不足 | M2 里程碑延期 | 重新评估完成标准 |
| API 路由不一致 | 维护成本增加 | 严格执行命名规范 |

---

## 9. 后续行动

### 9.1 立即行动

1. **与 backend-dev 确认**: Task #10 的实际完成情况和交付物
2. **前端代码搜索**: 查找所有 `/module/api/` 调用点
3. **建立迁移计划**: 按模块分批执行迁移

### 9.2 短期行动

1. **API 路由迁移**: 优先处理 Account 模块
2. **前端调用更新**: 同步更新所有调用点
3. **回归测试**: 确保迁移不影响现有功能

### 9.3 长期行动

1. **建立规范检查**: 将 API 命名纳入代码审查
2. **自动化检测**: CI/CD 中添加 API 路由规范检查
3. **文档同步**: 确保 OpenAPI 文档与实现一致

---

## 10. 附录

### 10.1 相关文档

- PRD: `docs/plans/ui-ux-improvement-prd-2026-02-18.md`
- 路由命名规范: Task #7 输出

### 10.2 测试脚本

- API 合规性测试: `tests/uat/test_api_naming_compliance.py`
- UAT 执行器: `tests/uat/run_uat.py`

---

**报告生成时间**: 2026-02-18
**下次更新**: Task #10 完成情况确认后
