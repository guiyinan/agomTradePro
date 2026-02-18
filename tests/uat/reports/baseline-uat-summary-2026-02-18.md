# 基线 UAT 测试报告 - 改造前状态

**测试日期**: 2026-02-18
**测试类型**: 改造前基线测试
**测试人员**: QA Engineer
**测试目的**: 建立 M1-M3 改造前的对比基准

---

## 1. 执行摘要

### 1.1 测试范围

| 测试类别 | 测试项 | 状态 |
|----------|--------|------|
| API 路由命名 | 规范合规性 | ✅ 已完成 |
| 用户旅程 | 自动化测试框架 | ✅ 已就绪 |
| 导航链接 | 404 检查 | ⚠️ 待验证 |
| 视觉一致性 | 截图基线 | ⚠️ 待执行 |

### 1.2 关键发现

**发现 #1: API 路由命名模式不一致**
- **问题**: API 路由存在两种混合模式
  - 模式 A: `/api/health/` (符合规范)
  - 模式 B: `/account/api/portfolios/` (不符合规范)
- **影响**: Task #10 需要治理约 400+ API 路由
- **优先级**: P1 (M2 里程碑)

**发现 #2: Django 环境配置问题**
- **问题**: 测试环境初始化时遇到编码和应用注册问题
- **影响**: 部分自动化测试无法正常执行
- **优先级**: P0 (阻塞测试执行)

---

## 2. API 路由命名分析

### 2.1 路由统计

| 指标 | 数值 |
|------|------|
| 总 URL 模式数 | ~1000+ |
| 包含 `/api/` 的路由 | ~410 |
| 全局 `/api/` 前缀路由 | 6 |
| 模块级 `/api/` 路由 | ~400 |
| 需要迁移的路由 | ~400 |

### 2.2 符合规范的路由

以下路由已符合 `/api/module/action/` 规范：

```
/api/health/                      - 健康检查
/api/debug/server-logs/stream/    - 日志流
/api/debug/server-logs/export/    - 日志导出
/api/schema/                      - OpenAPI Schema
/api/docs/                        - Swagger UI
/api/redoc/                       - ReDoc
/api/alpha/                       - Alpha 信号
```

### 2.3 需要治理的路由

**Account 模块** (~45 端点):
```
当前: /account/api/portfolios/
目标: /api/account/portfolios/

当前: /account/api/positions/
目标: /api/account/positions/

当前: /account/api/transactions/
目标: /api/account/transactions/
```

**其他模块**: 需要进一步分析

---

## 3. 用户旅程测试准备

### 3.1 自动化测试覆盖

已创建测试文件: `tests/playwright/tests/uat/test_user_journeys.py`

| 旅程 | 测试用例数 | 状态 |
|------|------------|------|
| A - 新用户入门 | 7 | ✅ 已定义 |
| B - 研究与选标 | 6 | ✅ 已定义 |
| C - 决策与执行 | 6 | ✅ 已定义 |
| D - 交易与持仓 | 5 | ✅ 已定义 |
| E - 复盘与运营 | 5 | ✅ 已定义 |
| **总计** | **29** | **框架就绪** |

### 3.2 测试执行命令

```bash
# 执行全部 UAT 测试
pytest tests/playwright/tests/uat/test_user_journeys.py -v

# 执行特定旅程
pytest tests/playwright/tests/uat/test_user_journeys.py -m journey_a

# 生成 HTML 报告
pytest tests/playwright/tests/uat/test_user_journeys.py --html=uat_report.html
```

---

## 4. 导航链接状态

### 4.1 主导航清单

基于 URL 分析，以下页面路由已定义：

| 页面 | 路由 | 状态 |
|------|------|------|
| Home | `/` | ✅ 已定义 |
| Dashboard | `/dashboard/` | ✅ 已定义 |
| Policy Dashboard | `/policy/dashboard/` | ✅ 已定义 |
| Asset Screen | `/asset-analysis/screen/` | ✅ 已定义 |
| Decision Workspace | `/decision/workspace/` | ✅ 已定义 |
| Ops Center | `/ops/` | ✅ 已定义 |
| Macro Data | `/macro/data/` | ✅ 已定义 |
| Regime Dashboard | `/regime/dashboard/` | ✅ 已定义 |
| Signal Manage | `/signal/manage/` | ✅ 已定义 |
| Policy Manage | `/policy/manage/` | ✅ 已定义 |
| Equity Screen | `/equity/screen/` | ✅ 已定义 |
| Fund Dashboard | `/fund/dashboard/` | ✅ 已定义 |
| Backtest Create | `/backtest/create/` | ✅ 已定义 |
| Simulated Trading | `/simulated-trading/dashboard/` | ✅ 已定义 |
| Audit Reports | `/audit/reports/` | ✅ 已定义 |

### 4.2 待验证项目

- [ ] 实际 HTTP 响应状态码
- [ ] 需要登录的页面跳转
- [ ] 面包屑导航一致性
- [ ] 页面标题与内容匹配

---

## 5. 测试基础设施状态

### 5.1 已完成

| 组件 | 状态 | 备注 |
|------|------|------|
| pytest.ini 配置 | ✅ | 已添加 UAT markers |
| Playwright conftest | ✅ | 已配置 fixtures |
| 页面对象模型 | ✅ | LoginPage, DashboardPage 等 |
| UX Auditor | ✅ | 自动化 UX 问题检测 |
| Screenshot 工具 | ✅ | 支持基线截图对比 |
| UAT 执行器 | ✅ | run_uat.py 脚本 |
| 报告模板 | ✅ | 验收报告模板 |

### 5.2 待完善

| 组件 | 状态 | 阻塞原因 |
|------|------|----------|
| Django 测试客户端 | ⚠️ | 编码/应用注册问题 |
| 数据库测试数据 | ⚠️ | 待准备 |
| 视觉对比基线 | ⚠️ | 待执行截图 |

---

## 6. 风险与问题

### 6.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Django 编码问题 | 阻塞测试执行 | 修复 core/admin.py 编码 |
| 测试数据缺失 | 测试覆盖不足 | 准备完整演示数据 |
| Playwright 依赖 | 环境配置复杂 | 提供安装文档 |

### 6.2 项目风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| API 治理工作量大 | 延期风险 | 按模块分批进行 |
| 前端调用点分散 | 遗漏风险 | 搜索 + 人工审查 |
| 视觉一致性难量化 | 验收困难 | 建立截图对比流程 |

---

## 7. 后续行动

### 7.1 立即行动 (P0)

1. **修复 Django 测试环境**
   - 修复 core/admin.py 编码问题
   - 确保测试可正常执行

2. **准备测试数据**
   - 创建完整的演示数据集
   - 包括各模块的测试数据

### 7.2 M2 里程碑 (P1)

1. **Task #10**: API 路由命名治理
   - 迁移 `/account/api/*` 到 `/api/account/*`
   - 同步其他模块

2. **Task #11**: 前端路由治理
   - 更新前端 API 调用
   - 验证无遗漏

### 7.3 M4 里程碑 (P2)

1. **执行完整 UAT**
   - 运行所有用户旅程测试
   - 生成验收报告

2. **视觉一致性验收**
   - 截图对比
   - 人工评审

---

## 8. 验收基准数据

### 8.1 改造前基线

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| API 路由规范覆盖率 | ~2% | 100% |
| 主导航 404 数量 | 待验证 | 0 |
| 用户旅程通过率 | 待测试 | >=90% |
| P0/P1 缺陷数 | 待统计 | <=2 |

### 8.2 对比基准

本报告数据将作为 M4 验收时的对比基准。改造完成后需要重新执行相同测试并对比结果。

---

## 9. 附录

### 9.1 相关文档

- PRD: `docs/plans/ui-ux-improvement-prd-2026-02-18.md`
- UX 清单: `docs/frontend/ux-user-journey-checklist-2026-02-18.md`
- API 分析: `tests/uat/reports/baseline-api-analysis-2026-02-18.md`
- 执行计划: `docs/plans/uat-execution-plan-2026-02-18.md`

### 9.2 测试文件

- UAT 测试: `tests/playwright/tests/uat/test_user_journeys.py`
- API 测试: `tests/uat/test_api_naming_compliance.py`
- 执行器: `tests/uat/run_uat.py`

---

## 变更历史

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-02-18 | 1.0 | 基线测试报告 | QA Engineer |
