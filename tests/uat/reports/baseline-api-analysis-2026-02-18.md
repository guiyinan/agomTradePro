# API 路由命名基线分析报告

**分析日期**: 2026-02-18
**分析类型**: 改造前基线
**分析人员**: QA Engineer
**目标**: 建立 API 路由命名规范的现状基线，为 M4 验收提供对比数据

---

## 1. 执行摘要

### 1.1 关键发现

| 指标 | 现状 | 目标 | 差距 |
|------|------|------|------|
| 全局 /api/ 前缀使用 | 部分 | 100% | 需治理 |
| API 路由总数量 | ~410 条 | 规范化后 | - |
| 模块 API 模式一致性 | 混合 | 统一 | 需治理 |

### 1.2 主要问题

1. **混合命名模式**: API 路由同时存在两种模式
   - `/api/health/` - 全局 API 前缀
   - `/account/api/...` - 模块级 API 路径

2. **缺少统一规范**: 不同模块的 API 路由结构不一致

---

## 2. 现有 API 路由模式分析

### 2.1 模式一：全局 /api/ 前缀

符合规范的 API 路由（已在 `core/urls.py` 中定义）：

```
/api/health/                    - 健康检查
/api/debug/server-logs/stream/  - 日志流
/api/debug/server-logs/export/  - 日志导出
/api/schema/                    - OpenAPI Schema
/api/docs/                      - Swagger UI
/api/redoc/                     - ReDoc
/api/alpha/                     - Alpha 信号（专用）
```

**评价**: ✅ 符合 PRD 要求的 `/api/module/action/` 模式

### 2.2 模式二：模块级 /api/ 路径

不符合规范的 API 路由（在模块 `urls.py` 中定义）：

```
/account/api/portfolios/        - 投资组合 API
/account/api/positions/         - 持仓 API
/account/api/transactions/      - 交易 API
/account/api/capital-flows/     - 资金流水 API
```

**评价**: ❌ 与 PRD 要求不一致，应该是 `/api/account/portfolios/`

---

## 3. 模块 API 路由清单

### 3.1 已识别的 API 模块

| 模块 | 当前模式 | 目标模式 | 状态 |
|------|----------|----------|------|
| account | `/account/api/*` | `/api/account/*` | 需迁移 |
| alpha | `/api/alpha/*` | `/api/alpha/*` | ✅ 已符合 |
| core | `/api/health/`, `/api/schema/` | `/api/health/` 等 | ✅ 已符合 |

### 3.2 API 路由密度

**Account 模块** (示例分析):
- portfolios: 6 个端点
- positions: 5 个端点
- transactions: 4 个端点
- capital-flows: 4 个端点
- assets: 5 个端点
- categories: 9 个端点
- currencies: 6 个端点
- exchange-rates: 6 个端点

**估计**: Account 模块约 45+ API 端点需要迁移

---

## 4. 治理建议

### 4.1 迁移策略

**阶段 1**: 保持向后兼容的双路由模式
```python
# 新路由（推荐）
path('api/account/portfolios/', PortfolioAPIView.as_view())

# 旧路由（标记为 deprecated，保留 N 个版本）
path('account/api/portfolios/', DeprecatedPortfolioAPIView.as_view())
```

**阶段 2**: 更新前端调用
- 搜索所有 `/account/api/` 调用
- 替换为 `/api/account/`

**阶段 3**: 移除旧路由
- 发布公告
- 等待一个稳定版本
- 完全移除旧路由

### 4.2 模板位置

**需要更新的文件**:
- `apps/account/interface/urls.py`
- 其他模块的 `interface/urls.py`

---

## 5. 基线数据记录

### 5.1 路由统计

| 类型 | 数量 |
|------|------|
| 全局 /api/ 路由 | 6 条 |
| 模块 /api/ 路由 | ~410 条 |
| 需要迁移的路由 | ~400 条 |

### 5.2 前端调用点

**需要搜索的关键词**:
- `fetch('/account/api/`
- `$.ajax('/account/api/`
- `axios.get('/account/api/`
- 模板中的 `href="/account/api/`

---

## 6. 验收标准对比

### 改造前（当前基线）

| 标准 | 状态 | 说明 |
|------|------|------|
| API 路由有 /api/ 前缀 | ❌ | 混合模式 |
| 路由符合 /api/module/action/ | ❌ | 部分为 /module/api/ |
| 文档与实现一致 | ⚠️ | 需验证 |
| 前后端联调无阻塞 | ⚠️ | 需验证 |

### 改造后（目标）

| 标准 | 状态 | 说明 |
|------|------|------|
| API 路由有 /api/ 前缀 | ✅ | 统一前缀 |
| 路由符合 /api/module/action/ | ✅ | 规范化 |
| 文档与实现一致 | ✅ | OpenAPI 同步 |
| 前后端联调无阻塞 | ✅ | 清单验证 |

---

## 7. 后续行动

1. **Task #10 (backend-dev)**: 治理 API 路由命名
   - 更新 `apps/*/interface/urls.py`
   - 统一为 `/api/module/action/` 模式

2. **Task #11 (frontend-dev)**: 治理前端路由命名
   - 更新前端 API 调用
   - 验证无遗漏

3. **Task #14 (qa-tester)**: 验收测试
   - 运行 API 合规性测试
   - 验证覆盖率 100%
   - 确认文档同步

---

## 8. 附录

### 8.1 相关文档

- PRD: `docs/plans/ui-ux-improvement-prd-2026-02-18.md`
- 路由命名规范: Task #7 输出

### 8.2 测试脚本

- API 合规性测试: `tests/uat/test_api_naming_compliance.py`
- UAT 执行器: `tests/uat/run_uat.py`

---

## 变更历史

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-02-18 | 1.0 | 基线分析 | QA Engineer |
