# AgomTradePro 全站 UI/UX 与功能清单（2026-02-18）

## 1. 盘点范围与方法

- 扫描范围：`core/urls.py` 与 `apps/*/interface/urls.py` 中所有页面路由。
- 模板范围：`core/templates`、`apps/*/templates`、`templates` 中 HTML 模板。
- 盘点目标：
  - 列出当前可访问页面（HTML）；
  - 列出每个页面的核心功能；
  - 标注 UI/UX 现状与主要问题。
- 说明：本次为代码与模板级盘点，不包含逐页人工点击测试与视觉验收截图。

---

## 2. 页面总览（信息架构）

### 2.1 核心入口

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/` | 首页入口 | 重定向到 `/dashboard/` |
| `/dashboard/` | 投资指挥中心入口 | 根据配置进入 Streamlit 或 Django Dashboard |
| `/dashboard/legacy/` | Django Dashboard | 综合看板：Regime/Policy/资产/信号/Alpha/配额 |
| `/ops/` | Operations Center | 运营与配置快捷入口聚合 |
| `/decision/workspace/` | 决策工作台 | Beta Gate + Alpha Trigger + Decision Rhythm 联动入口 |
| `/docs/` | 文档中心 | 文档分类导航 |
| `/docs/<doc_slug>/` | 文档详情 | Markdown 文档阅读 |
| `/chat-example/` | 聊天组件示例 | AI 聊天组件集成示例 |

### 2.2 账户与权限

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/account/register/` | 注册 | 注册、协议确认、风险提示确认 |
| `/account/login/` | 登录 | 登录与跳转 |
| `/account/profile/` | 我的账户 | 账户概览、组合、持仓、波动率 |
| `/account/settings/` | 账户设置 | 基本信息、偏好、安全、资金流水 |
| `/account/admin/users/` | 用户管理 | 审批、角色、状态管理 |
| `/account/admin/tokens/` | Token 管理 | Token 查看/轮换/吊销 |
| `/account/admin/settings/` | 系统设置 | 审批策略、协议文案等系统参数 |

### 2.3 宏观环境

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/regime/dashboard/` | Regime 判定 | PMI/CPI 驱动判定、分布图、原始数据展示 |
| `/policy/dashboard/` | 政策跟踪看板 | 当前政策状态、建议、最近事件 |
| `/policy/events/` | 政策事件 | 事件列表筛选、分页 |
| `/policy/events/new/` | 新增政策事件 | 事件创建 |
| `/macro/data/` | 宏观数据中心 | 指标查询、图表展示、数据状态 |
| `/macro/datasources/` | 数据源配置 | 数据源清单、状态与说明 |
| `/macro/datasources/new/` | 新增数据源 | 数据源新建 |
| `/macro/datasources/<source_id>/edit/` | 编辑数据源 | 数据源编辑 |
| `/macro/controller/` | 数据管理器 | 批量抓取、记录管理、表格操作 |
| `/filter/dashboard/` | 趋势滤波器 | 指标选择、HP/Kalman 对比与可视化 |

### 2.4 投资管理

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/strategy/` | 策略管理 | 策略列表、启停、编辑、删除 |
| `/strategy/create/` | 创建策略 | 基本信息、风控、规则、脚本、AI 配置 |
| `/strategy/<strategy_id>/` | 策略详情 | 配置详情、执行日志、操作入口 |
| `/strategy/<strategy_id>/edit/` | 编辑策略 | 完整策略配置编辑 |
| `/backtest/` | 回测管理 | 回测列表与统计 |
| `/backtest/create/` | 创建回测 | 参数配置、资金与策略设置 |
| `/backtest/<backtest_id>/` | 回测详情 | 结果、交易记录、Regime 变化、应用结果 |
| `/signal/manage/` | 投资信号 | 创建/审批/拒绝/证伪/批量检查、AI 证伪规则辅助 |

### 2.5 模拟交易

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/simulated-trading/dashboard/` | 模拟盘总览 | 账户入口、系统状态、快捷操作 |
| `/simulated-trading/accounts/<account_id>/` | 账户详情 | 单账户信息与操作 |
| `/simulated-trading/my-accounts/` | 我的投资组合 | 多账户总览、创建、策略绑定 |
| `/simulated-trading/my-accounts/<account_id>/` | 我的账户详情 | 账户概览、持仓概览、最近交易 |
| `/simulated-trading/my-accounts/<account_id>/positions/` | 持仓列表 | 持仓表格与收益表现 |
| `/simulated-trading/my-accounts/<account_id>/trades/` | 交易记录 | 交易流水与统计 |
| `/simulated-trading/my-accounts/<account_id>/inspection-notify/` | 巡检通知配置 | 邮件通知开关与收件配置 |

### 2.6 决策平面

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/beta-gate/config/` | Beta 闸门配置 | 当前生效配置、最近决策 |
| `/beta-gate/config/new/` | 新建 Beta 配置 | 表单创建 |
| `/beta-gate/config/<config_id>/edit/` | 编辑 Beta 配置 | 表单编辑 |
| `/beta-gate/test/` | 资产测试工具 | 单/多资产闸门测试 |
| `/beta-gate/version/` | 版本对比 | 版本查看、对比、回滚入口 |
| `/decision-rhythm/quota/` | 决策配额 | 配额状态与记录 |
| `/decision-rhythm/config/` | 配额配置 | 配置编辑与趋势可视化 |
| `/alpha-triggers/` | Alpha 触发器列表 | 状态分组、列表管理 |
| `/alpha-triggers/create/` | 创建触发器 | 触发条件配置 |
| `/alpha-triggers/edit/<trigger_id>/` | 编辑触发器 | 规则与参数调整 |
| `/alpha-triggers/detail/<trigger_id>/` | 触发器详情 | 条件、状态、关联信息 |
| `/alpha-triggers/invalidation-builder/` | 证伪规则构建器 | 可视化构建与规则调试 |
| `/alpha-triggers/candidates/<candidate_id>/` | 候选详情 | 候选评分、来源与动作 |
| `/alpha-triggers/performance/` | 触发器表现 | 排行、分组、趋势图 |

### 2.7 证券分析

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/asset-analysis/screen/` | 资产筛选 | 跨资产筛选、上下文联动 |
| `/fund/dashboard/` | 基金分析 | 多维筛选、排名、风格、业绩、持仓分析 |
| `/equity/screen/` | 个股筛选 | 条件筛选与结果列表 |
| `/equity/detail/<stock_code>/` | 个股详情 | 基本面、估值、相关性分析 |
| `/equity/pool/` | 股票池管理 | 当前池、历史池、分布统计 |

### 2.8 审计与系统工具

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/audit/page/` | 审计首页 | 最新报告与验证摘要 |
| `/audit/reports/` | 审计报告列表 | 报告入口（与 audit page 共用主页模板） |
| `/audit/reports/<report_id>/` | 归因详情 | 收益分解、损失分析、经验总结 |
| `/audit/indicator-performance/` | 指标表现评估 | 指标分类、统计、推荐动作 |
| `/audit/threshold-validation/` | 阈值验证 | 阈值配置 + 历史验证表现 |
| `/admin/server-logs/` | 服务端日志 | 实时日志查看与导出 |
| `/admin/docs/manage/` | 文档管理 | 文档列表、导入导出、编辑入口 |
| `/admin/docs/edit/` | 新建文档 | 文档编辑 |
| `/admin/docs/edit/<doc_id>/` | 编辑文档 | 文档编辑 |

### 2.9 AI 服务页

| 路由 | 页面 | 主要功能 |
|---|---|---|
| `/ai/` | AI 接口管理 | Provider 列表、新增/编辑入口 |
| `/ai/logs/` | AI 调用日志 | 按 provider/status/limit 过滤 |
| `/ai/detail/<provider_id>/` | Provider 详情 | 基础信息、调用统计、模型统计 |
| `/ai/detail/<provider_id>/edit/` | 编辑 Provider | 配置编辑 |
| `/prompt/manage/` | Prompt 模板管理 | 模板/链路/执行日志/在线测试 |

---

## 3. 当前 UI/UX 观察

### 3.1 正向项

- 全局导航覆盖较全，模块分组清晰（宏观环境、投资管理、决策平面、证券分析、系统、AI 服务）。
- 多数核心页面具备数据可视化（Regime、Dashboard、Filter、Equity、Decision 模块）。
- 管理后台场景（政策 RSS、文档管理、AI Provider、Prompt）已具备可操作页面，不依赖 Django Admin。

### 3.2 主要问题（按优先级）

1. `P0` 导航存在失效链接  
`core/templates/dashboard/index.html` 中存在 `/macro/dashboard/`、`/equity/dashboard/`，当前路由中无对应页面，用户点击会 404。

2. `P1` 视觉与交互风格不一致  
部分页面为现代卡片与统一样式，部分页面大量内联样式与不同按钮体系，用户跨模块切换时认知负担高。

3. `P1` 路由命名与实际行为不一致  
如 `/dashboard/` 可能跳到 Streamlit，`/dashboard/legacy/` 才是 Django 页面，用户心智上不直观。

4. `P2` 页面与 API 混合命名  
部分非页面接口未带 `/api/` 前缀（例如 policy 审核相关），会给前端联调和文档阅读带来歧义。

5. `P2` 模板来源有重复风险  
`core/templates/simulated_trading/*` 与 `templates/simulated_trading/*` 同名并存，后续维护易出现“改了未生效”的问题。

---

## 4. 功能覆盖结论

- 已覆盖并列出当前系统所有主要 HTML 页面入口。
- 已按业务域拆分功能，形成“路由-页面-功能”映射，可作为产品清单与测试清单基线。
- 下一步建议把本文件作为 UI/UX 基线文档，后续每次新增页面或改版时同步更新。

---

## 5. 建议的下一轮优化（可直接排期）

1. 修复 Dashboard 侧栏失效链接（`/macro/dashboard/`、`/equity/dashboard/`）。
2. 统一设计 Token（颜色、按钮、表格、间距、状态标签）并抽离内联样式。
3. 统一页面命名策略（页面路由、API 路由、入口文案），减少学习成本。
4. 补一份“关键用户流程”专项（注册->建仓->信号->回测->决策->复盘）交互走查报告。

