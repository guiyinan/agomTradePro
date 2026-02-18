# UAT 路由测试结果报告

**测试日期**: 2026-02-18
**测试类型**: 路由定义验证 (独立于视觉改造)
**测试人员**: QA Engineer

---

## 1. 测试摘要

| 测试类别 | 通过率 | 状态 |
|----------|--------|------|
| 主导航路由 | 100% (6/6) | ✅ PASS |
| 用户旅程路由 | 94% (15/16) | ⚠️ PARTIAL |
| 总体路由定义 | 96% (21/22) | ✅ PASS |

---

## 2. 主导航路由测试

### 2.1 测试结果

| 路由 | URL | 状态 | URL Name |
|------|-----|------|----------|
| Home | `/` | ✅ PASS | index |
| Dashboard | `/dashboard/` | ✅ PASS | index |
| Policy Dashboard | `/policy/dashboard/` | ✅ PASS | policy-dashboard |
| Asset Screen | `/asset-analysis/screen/` | ✅ PASS | asset-screen |
| Decision Workspace | `/decision/workspace/` | ✅ PASS | decision-workspace |
| Ops Center | `/ops/` | ✅ PASS | ops-center |

**覆盖率**: 6/6 (100%)

---

## 3. 用户旅程路由测试

### 3.1 旅程 A: 新用户入门

| 路由 | URL | 状态 |
|------|-----|------|
| Home | `/` | ✅ PASS |
| Login | `/account/login/` | ✅ PASS |
| Register | `/account/register/` | ✅ PASS |
| Dashboard | `/dashboard/` | ✅ PASS |

**覆盖率**: 4/4 (100%)

### 3.2 旅程 B: 研究与选标

| 路由 | URL | 状态 | 备注 |
|------|-----|------|------|
| Macro Data | `/macro/data/` | ✅ PASS | |
| Regime Dashboard | `/regime/dashboard/` | ✅ PASS | |
| Policy Manage | `/policy/manage/` | ❌ FAIL | 不存在 |
| Equity Screen | `/equity/screen/` | ✅ PASS | |

**覆盖率**: 3/4 (75%)

**问题分析**:
- `/policy/manage/` 路由不存在
- Policy 模块实际路由:
  - `/policy/events/` - 政策事件列表
  - `/policy/rss/manage/` - RSS 源管理
- **建议**: 更新 UX 检查清单，使用实际存在的路由

### 3.3 旅程 C: 决策与执行

| 路由 | URL | 状态 |
|------|-----|------|
| Signal Manage | `/signal/manage/` | ✅ PASS |
| Decision Workspace | `/decision/workspace/` | ✅ PASS |

**覆盖率**: 2/2 (100%)

### 3.4 旅程 D: 交易与持仓

| 路由 | URL | 状态 |
|------|-----|------|
| Simulated Trading | `/simulated-trading/dashboard/` | ✅ PASS |
| Profile | `/account/profile/` | ✅ PASS |
| Settings | `/account/settings/` | ✅ PASS |

**覆盖率**: 3/3 (100%)

### 3.5 旅程 E: 复盘与运营

| 路由 | URL | 状态 |
|------|-----|------|
| Backtest Create | `/backtest/create/` | ✅ PASS |
| Audit Reports | `/audit/reports/` | ✅ PASS |
| Ops Center | `/ops/` | ✅ PASS |

**覆盖率**: 3/3 (100%)

---

## 4. API 路由合规性检查

### 4.1 全局 /api/ 前缀路由

| 路由 | 状态 |
|------|------|
| `/api/health/` | ✅ PASS |
| `/api/schema/` | ✅ PASS |
| `/api/docs/` | ✅ PASS |
| `/api/redoc/` | ✅ PASS |
| `/api/alpha/` | ✅ PASS |

### 4.2 模块级 API 路由

当前仍使用 `/module/api/` 模式:
- `/account/api/portfolios/`
- `/account/api/positions/`
- 等约 400 条

**状态**: ⚠️ 需要迁移到 `/api/module/` 模式

---

## 5. 缺陷记录

### P1 缺陷

| ID | 标题 | 位置 | 状态 |
|----|------|------|------|
| UAT-001 | UX 检查清单引用不存在的路由 | `/policy/manage/` | 已记录 |

**描述**: UX 检查清单中引用的 `/policy/manage/` 路由在系统中不存在。

**影响**: 旅程 B 测试覆盖率显示为 75% 而非 100%

**建议**:
1. 更新 UX 检查清单使用实际路由
2. 或者添加 `/policy/manage/` 路由作为管理页面的统一入口

---

## 6. 验收标准对比

| 标准 | 目标值 | 当前值 | 状态 |
|------|--------|--------|------|
| 主导航 404 | 0 | 0 | ✅ PASS |
| 用户旅程路由可达性 | >= 90% | 94% | ✅ PASS |
| API 命名规范覆盖率 | 100% | ~5% | ❌ FAIL |

---

## 7. 建议

### 7.1 立即行动

1. **修复 UX 检查清单**: 更新 `/policy/manage/` 为实际存在的路由
2. **API 路由治理**: 继续推进 `/module/api/` 到 `/api/module/` 的迁移

### 7.2 后续改进

1. **建立路由清单**: 维护一个完整的系统路由清单
2. **自动化路由检查**: 将路由验证纳入 CI/CD 流程

---

**报告生成时间**: 2026-02-18
**测试执行环境**: Django URL 解析 (无需服务器运行)
