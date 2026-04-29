# UAT 验收报告模板

**项目**: AgomTradePro UI/UX 改进
**版本**: v3.4
**测试日期**: {DATE}
**测试人员**: QA Engineer
**报告类型**: UAT Release Gate 验收

---

## 1. 执行摘要

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 关键旅程通过率 | >= 90% | {PASS_RATE}% | {STATUS} |
| 主导航 404 数量 | 0 | {404_COUNT} | {STATUS} |
| P0/P1 缺陷数量 | <= 2 | {DEFECT_COUNT} | {STATUS} |
| API 命名规范覆盖率 | 100% | {API_COVERAGE}% | {STATUS} |

### 验收结论
{CONCLUSION}

---

## 2. 用户旅程测试结果

### 旅程 A：新用户入门

| 测试项 | 状态 | 备注 |
|--------|------|------|
| A1.1 注册页字段说明清楚 | {STATUS} | {NOTES} |
| A1.2 协议与风险提示可读 | {STATUS} | {NOTES} |
| A1.3 登录后跳转符合预期 | {STATUS} | {NOTES} |
| A1.4 未登录跳转登录页 | {STATUS} | {NOTES} |
| A2.1 Dashboard 首屏回答3问题 | {STATUS} | {NOTES} |
| A2.2 导航分组命名一致 | {STATUS} | {NOTES} |
| A2.3 关键卡片颜色状态一致 | {STATUS} | {NOTES} |

**小计**: {A_PASS}/{A_TOTAL} 通过

### 旅程 B：研究与选标的

| 测试项 | 状态 | 备注 |
|--------|------|------|
| B1.1 Regime 页支持切换时点 | {STATUS} | {NOTES} |
| B1.2 Policy 页显示当前档位 | {STATUS} | {NOTES} |
| B1.3 Macro/Filter 页加载状态明确 | {STATUS} | {NOTES} |
| B2.1 资产筛选条件分组清晰 | {STATUS} | {NOTES} |
| B2.2 筛选结果更新及时 | {STATUS} | {NOTES} |
| B2.3 返回列表筛选不丢失 | {STATUS} | {NOTES} |

**小计**: {B_PASS}/{B_TOTAL} 通过

### 旅程 C：决策与执行

| 测试项 | 状态 | 备注 |
|--------|------|------|
| C1.1 策略创建流程顺序合理 | {STATUS} | {NOTES} |
| C1.2 信号页面动作入口清晰 | {STATUS} | {NOTES} |
| C1.3 关键动作有确认反馈 | {STATUS} | {NOTES} |
| C2.1 决策平面三块状态可读 | {STATUS} | {NOTES} |
| C2.2 告警显著且可操作 | {STATUS} | {NOTES} |
| C2.3 Beta Gate 结果解释清晰 | {STATUS} | {NOTES} |

**小计**: {C_PASS}/{C_TOTAL} 通过

### 旅程 D：交易与持仓管理

| 测试项 | 状态 | 备注 |
|--------|------|------|
| D1.1 模拟盘入口快速到账户 | {STATUS} | {NOTES} |
| D1.2 账户详情核心指标明显 | {STATUS} | {NOTES} |
| D1.3 持仓交易表格支持操作 | {STATUS} | {NOTES} |
| D2.1 Profile与Settings边界清晰 | {STATUS} | {NOTES} |
| D2.2 资金流水状态同步及时 | {STATUS} | {NOTES} |

**小计**: {D_PASS}/{D_TOTAL} 通过

### 旅程 E：复盘与运营

| 测试项 | 状态 | 备注 |
|--------|------|------|
| E1.1 回测列表到详情路径清晰 | {STATUS} | {NOTES} |
| E1.2 审计页术语一致 | {STATUS} | {NOTES} |
| E1.3 应用回测结果确认明确 | {STATUS} | {NOTES} |
| E2.1 Settings Center 聚合入口完整 | {STATUS} | {NOTES} |
| E2.2 管理类页面操作闭环完整 | {STATUS} | {NOTES} |

**小计**: {E_PASS}/{E_TOTAL} 通过

---

## 3. 视觉一致性验收

### 核心页面检查

| 页面 | 按钮风格 | 表格风格 | 状态标签 | 整体评估 |
|------|----------|----------|----------|----------|
| Dashboard | {STATUS} | {STATUS} | {STATUS} | {OVERALL} |
| Decision Workspace | {STATUS} | {STATUS} | {STATUS} | {OVERALL} |
| Policy | {STATUS} | {STATUS} | {STATUS} | {OVERALL} |
| Signal | {STATUS} | {STATUS} | {STATUS} | {OVERALL} |

### 组件一致性检查

| 组件类型 | 统一样式 | 一致性评分 | 备注 |
|----------|----------|------------|------|
| 按钮 | {STATUS} | {SCORE}/10 | {NOTES} |
| 输入框 | {STATUS} | {SCORE}/10 | {NOTES} |
| 表格 | {STATUS} | {SCORE}/10 | {NOTES} |
| 标签 | {STATUS} | {SCORE}/10 | {NOTES} |
| 告警 | {STATUS} | {SCORE}/10 | {NOTES} |
| 空状态 | {STATUS} | {SCORE}/10 | {NOTES} |

---

## 4. 导航可用性验收

### 主导航检查

| 导航项 | URL | 状态 | 问题 |
|--------|-----|------|------|
| Dashboard | /dashboard/ | {STATUS} | {ISSUE} |
| 宏观数据 | /macro/data/ | {STATUS} | {ISSUE} |
| 环境判定 | /regime/dashboard/ | {STATUS} | {ISSUE} |
| 政策管理 | /policy/manage/ | {STATUS} | {ISSUE} |
| 信号管理 | /signal/manage/ | {STATUS} | {ISSUE} |
| 资产筛选 | /asset-analysis/screen/ | {STATUS} | {ISSUE} |
| 回测 | /backtest/create/ | {STATUS} | {ISSUE} |
| 模拟交易 | /simulated-trading/dashboard/ | {STATUS} | {ISSUE} |
| 审计报告 | /audit/reports/ | {STATUS} | {ISSUE} |
| 设置中心 | /settings/ | {STATUS} | {ISSUE} |

**404 链接**: {404_LIST}

### 面包屑检查

| 页面 | 面包屑存在 | 层级正确 | 文案一致 |
|------|------------|----------|----------|
| Dashboard | {STATUS} | {STATUS} | {STATUS} |
| Macro Data | {STATUS} | {STATUS} | {STATUS} |
| Regime Dashboard | {STATUS} | {STATUS} | {STATUS} |

---

## 5. API 命名验收

### API 路由规范检查

| 模块 | 页面路由 | API路由 | 符合规范 | 备注 |
|------|----------|---------|----------|------|
| account | /account/* | /api/account/* | {STATUS} | {NOTES} |
| macro | /macro/* | /api/data-center/macro/series/ | {STATUS} | {NOTES} |
| regime | /regime/* | /api/regime/* | {STATUS} | {NOTES} |
| signal | /signal/* | /api/signal/* | {STATUS} | {NOTES} |
| policy | /policy/* | /api/policy/* | {STATUS} | {NOTES} |
| backtest | /backtest/* | /api/backtest/* | {STATUS} | {NOTES} |
| simulated_trading | /simulated-trading/* | /api/simulated-trading/* | {STATUS} | {NOTES} |

**覆盖率**: {API_COVERAGE}%

### 文档同步检查

| 检查项 | 状态 | 备注 |
|--------|------|------|
| OpenAPI 文档已更新 | {STATUS} | {NOTES} |
| 接口类型边界说明完整 | {STATUS} | {NOTES} |
| 前后端联调清单无阻塞 | {STATUS} | {NOTES} |

---

## 6. 缺陷记录

### P0 缺陷

| ID | 标题 | 位置 | 严重程度 | 状态 |
|----|------|------|----------|------|
| {ID} | {TITLE} | {LOCATION} | P0 | {STATUS} |

### P1 缺陷

| ID | 标题 | 位置 | 严重程度 | 状态 |
|----|------|------|----------|------|
| {ID} | {TITLE} | {LOCATION} | P1 | {STATUS} |

### P2 缺陷

| ID | 标题 | 位置 | 严重程度 | 状态 |
|----|------|------|----------|------|
| {ID} | {TITLE} | {LOCATION} | P2 | {STATUS} |

---

## 7. 截图证据

### 关键页面截图

- Dashboard: {SCREENSHOT}
- Decision Workspace: {SCREENSHOT}
- Policy: {SCREENSHOT}
- Signal: {SCREENSHOT}

### 问题截图

- {ISSUE_TITLE}: {SCREENSHOT}

---

## 8. 建议与后续工作

### 需立即修复 (P0)

1. {P0_ITEM_1}
2. {P0_ITEM_2}

### 建议优化 (P1)

1. {P1_ITEM_1}
2. {P1_ITEM_2}

### 下版本改进 (P2)

1. {P2_ITEM_1}
2. {P2_ITEM_2}

---

## 9. 验收签字

| 角色 | 姓名 | 签字 | 日期 |
|------|------|------|------|
| QA 测试工程师 | {QA_NAME} | {SIGN} | {DATE} |
| 产品负责人 | {PO_NAME} | {SIGN} | {DATE} |
| 技术负责人 | {TECH_LEAD} | {SIGN} | {DATE} |

---

## 附录

### 测试环境

- 环境: {ENV}
浏览器: {BROWSER}
分辨率: {RESOLUTION}
测试数据: {TEST_DATA}

### 测试执行记录

- 测试开始时间: {START_TIME}
- 测试结束时间: {END_TIME}
- 总测试用时: {DURATION}
- 执行测试用例数: {TOTAL_CASES}
