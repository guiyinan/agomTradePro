# 外包实施说明书：政策抓取 / 市场情绪 / 热点统一工作台（一次性重构）

## 一、交付目标（必须达成）
把当前分散在多个页面的流程，重构为一个唯一入口页面：`/policy/workbench/`，并满足以下结果：

1. 抓取、判定、审核、生效、回滚、情绪趋势、闸门配置都在同一页完成。  
2. 旧页面全部 301 跳转到新页面。  
3. 政策档位 `P0-P3` 按“全部已生效事件”计算（不是仅 policy 类型）。  
4. 外包团队不得自行改变业务规则与接口语义。

---

## 二、现状问题（开发前先统一认知）
以下是当前代码中已确认的问题（用于解释为什么要改）：

1. 页面入口分散：
- `policy/dashboard`
- `policy/events`
- `policy/rss/*`
- `sentiment/dashboard`
- `policy/workbench`
2. `sentiment` 路由冲突：`analyze/` 同时注册了页面视图和 API 视图（先匹配页面，API 路径语义混乱）。  
3. 工作台前端调用了不存在/不稳定的抓取路径：`/api/policy/rss/fetch/`。  
4. 工作台“详情”功能是占位（弹窗提示“开发中”）。  
5. 旧逻辑中 `P0-P3` 只看 `event_type=policy`，与你的新规则不一致。

---

## 三、实施边界（In Scope / Out of Scope）

### In Scope
1. 后端 API 收敛与新增（bootstrap/detail/fetch）。  
2. 工作台前端重构（详情抽屉、批量操作、统一数据流）。  
3. 导航与路由统一。  
4. 全量 301 跳转。  
5. 自动化测试补齐（后端+E2E 关键路径）。

### Out of Scope
1. 新增复杂算法模型（只复用现有分类和评分逻辑）。  
2. 新增外部数据源类型。  
3. 大规模视觉品牌重设计（以可用性优先）。

---

## 四、必须遵守的业务规则（禁止擅改）

1. `P0-P3` 计算口径：
- 使用“全部 `gate_effective=True` 事件”计算当前政策档位。
- 不再限制 `event_type='policy'`。
2. `L0-L3` 仍由热点/情绪闸门逻辑计算。  
3. 审核动作语义：
- `approve`：生效并写审计日志
- `reject`：拒绝并写审计日志
- `rollback`：取消生效并写审计日志
- `override`：临时豁免/改档位并写审计日志
4. 所有写操作必须校验登录态与 CSRF。  
5. 旧页面不再长期维护，全部 301。

---

## 五、详细任务拆解（按顺序执行）

## 阶段 A：后端先行（先稳定真相和接口）

### A1. 修改政策档位口径
文件：`apps/policy/infrastructure/repositories.py`  
函数：`DjangoPolicyRepository.get_current_policy_level`

实施要求：
1. 删除 `event_type='policy'` 过滤条件。  
2. 保留 `gate_effective=True` 和日期条件过滤。  
3. 仍按 `-event_date, -effective_at` 取最新。  
4. 无数据默认 `P0`。

验收：
- 单元测试覆盖 “mixed/sentiment/hotspot 生效后能影响 P 档位”。

---

### A2. 新增统一首屏 API（bootstrap）
文件：`apps/policy/interface/views.py`、`apps/policy/interface/api_urls.py`、`apps/policy/interface/serializers.py`

新增接口：
- `GET /api/policy/workbench/bootstrap/`

返回字段（固定）：
1. `summary`（现有 WorkbenchSummary）  
2. `default_list`（默认 `tab=all` 的前 50 条）  
3. `filter_options`
- `event_types`
- `levels`
- `gate_levels`
- `asset_classes`
- `sources`  
4. `trend`
- `sentiment_recent_30d`
- `effective_events_recent_30d`  
5. `fetch_status`
- `last_fetch_at`
- `last_fetch_status`
- `recent_fetch_errors`

禁止事项：
- 不要让前端首屏发 4~6 个独立请求；bootstrap 必须聚合一次返回。

---

### A3. 新增详情 API（给抽屉用）
新增接口：
- `GET /api/policy/workbench/items/{id}/`

返回字段（必须包含）：
1. 基础字段：`id,event_date,event_type,level,gate_level,title,description,evidence_url`  
2. 分析字段：`ai_confidence,heat_score,sentiment_score,risk_impact,structured_data,processing_metadata`  
3. 流程字段：`audit_status,gate_effective,effective_at,effective_by,review_notes,rollback_reason`  
4. 来源字段：`rss_source_id,rss_source_name,rss_item_guid`

---

### A4. 新增统一抓取 API（修复前端断链）
新增接口：
- `POST /api/policy/workbench/fetch/`

请求体：
- `{"source_id": null, "force_refetch": false}`

行为：
1. `source_id=null` 时抓全部启用源。  
2. 非空时抓指定源。  
3. 返回同步结果结构（本地 eager 模式）或任务 ID（异步模式）统一包装为：
- `success`
- `mode` (`sync|async`)
- `task_id` (nullable)
- `sources_processed,total_items,new_policy_events,errors,details`

注意：
- 不要再让前端直接调用 `/api/policy/rss/sources/fetch_all/` 或不存在路径。

---

### A5. 修复 sentiment 路由冲突
文件：`apps/sentiment/interface/urls.py`

实施要求：
1. 页面路由与 API 路由分离，不得同路径。
2. 建议：
- 页面：`/sentiment/dashboard/`、`/sentiment/console/`
- API：仅 `/api/sentiment/*` 下提供  
3. 保留兼容跳转，但不保留冲突定义。

---

## 阶段 B：前端工作台重构（单页闭环）

### B1. 模板与静态资源拆分
文件：
- `core/templates/policy/workbench.html`
- 新建 `static/css/policy-workbench.css`
- 新建 `static/js/policy-workbench.js`

要求：
1. 页面保留骨架，不写超长内联 JS。  
2. JS 分模块：
- `apiClient`
- `stateStore`
- `listRenderer`
- `drawerRenderer`
- `actions`
- `filters`
- `charts`
3. 所有 POST 请求统一带 CSRF 头。

---

### B2. 主列表默认“全量时间流”
默认行为：
1. 首屏 tab=`all`。  
2. 可切换 `pending/effective/all`。  
3. 筛选实时生效（按钮触发，不做输入即查）。  
4. 分页固定 `limit=50`。

列表列（固定顺序）：
1. 日期  
2. 事件类型  
3. 档位  
4. 闸门  
5. 标题  
6. AI 置信度  
7. 审核状态  
8. 操作

---

### B3. 右侧详情抽屉（必须实现）
交互要求：
1. 点击“详情”打开抽屉，不跳页。  
2. 抽屉内显示：
- 原文与证据链接
- 结构化字段 JSON（格式化）
- 处理轨迹与错误信息
- 可执行动作（approve/reject/rollback/override）  
3. 动作后只刷新：
- 当前行
- summary 卡片
- 抽屉内容  
避免全页刷新闪烁。

---

### B4. 抓取区与配置区
同页提供：
1. “抓取全部”按钮  
2. “按源抓取”下拉 + 按钮  
3. 最近抓取状态卡（成功率/错误数/最后一次）  
4. 可折叠配置面板：
- ingestion config
- sentiment gate config  
配置修改后显示版本号变化。

---

### B5. 图表区
展示：
1. 最近 30 天情绪趋势线（综合/新闻/政策）  
2. 近 30 天生效事件数量柱状图  
无数据时必须有空态，不允许 JS 报错。

---

## 阶段 C：路由与导航统一（强制收口）

### C1. 旧页面 301 清单（全部跳新页）
以下 URL 全部 301 到 `/policy/workbench/`：

1. `/policy/dashboard/`
2. `/policy/events/`
3. `/policy/rss/reader/`
4. `/policy/rss/manage/`
5. `/policy/rss/keywords/`
6. `/policy/rss/logs/`
7. `/policy/audit/queue/`
8. `/sentiment/dashboard/`
9. `/sentiment/analyze/`

---

### C2. 导航改造
文件：
- `core/templates/base.html`
- `core/templates/dashboard/index.html`

要求：
1. 宏观环境菜单只保留一个主入口文案：`政策/情绪/热点工作台`。  
2. 删除或隐藏旧入口项，避免用户继续分散跳转。
3. “投资管理”菜单中账户入口文案统一为：`我的投资账户`（替代“我的模拟仓”）。
4. API 文档入口只保留在“系统”菜单内；右上角重复入口必须移除。
5. 仪表盘左侧导航（`dashboard/index.html`）中与业务页面相关的链接必须使用 Django `{% url %}` 反解，禁止硬编码路径。
6. 页面导航禁止直接跳转业务 API（`/api/*`）；唯一例外是文档入口 `/api/docs/`。

验收（2026-02-28 导航口径）：
1. 顶部导航仅在“系统”菜单出现一次“API 文档”。  
2. 顶部导航文案显示“我的投资账户”。  
3. 左侧“宏观环境”中的政策入口为“政策/情绪/热点工作台”，目标路由为 `{% url 'policy:workbench' %}`。  
4. `dashboard/index.html` 不再出现以下硬编码业务路径：`/regime/dashboard/`、`/policy/events/`、`/macro/data/`、`/signal/manage/`、`/backtest/create/`、`/filter/dashboard/`、`/equity/screen/`、`/fund/dashboard/`、`/audit/review/`、`/account/profile/#...`。

---

## 六、接口契约（外包必须按此开发）

## 1) Bootstrap
`GET /api/policy/workbench/bootstrap/`

响应（示例结构）：
```json
{
  "success": true,
  "summary": {...},
  "default_list": {"items":[...], "total": 1234},
  "filter_options": {
    "event_types":["policy","hotspot","sentiment","mixed"],
    "levels":["PX","P0","P1","P2","P3"],
    "gate_levels":["L0","L1","L2","L3"],
    "asset_classes":["all","equity","bond","commodity","fx","crypto"],
    "sources":[{"id":1,"name":"..."}]
  },
  "trend": {
    "sentiment_recent_30d":[...],
    "effective_events_recent_30d":[...]
  },
  "fetch_status": {
    "last_fetch_at":"2026-02-27T10:00:00Z",
    "last_fetch_status":"success",
    "recent_fetch_errors":[]
  }
}
```

## 2) Item Detail
`GET /api/policy/workbench/items/{id}/`

## 3) Fetch
`POST /api/policy/workbench/fetch/`
```json
{"source_id": null, "force_refetch": false}
```

## 4) Existing Actions（继续使用）
- `POST /api/policy/workbench/items/{id}/approve/`
- `POST /api/policy/workbench/items/{id}/reject/`
- `POST /api/policy/workbench/items/{id}/rollback/`
- `POST /api/policy/workbench/items/{id}/override/`

---

## 七、测试计划（外包必须交付）

## 后端测试
1. `get_current_policy_level` 新口径单测（含 all event types）。  
2. bootstrap 接口序列化与字段完整性测试。  
3. detail/fetch/action 接口鉴权与错误码测试。  
4. sentiment 路由冲突回归测试。  
5. 301 跳转测试（每个旧 URL 都测）。

## 前端测试
1. 首屏加载一次 bootstrap。  
2. 列表筛选/分页/切 tab 正常。  
3. 抽屉详情展示完整。  
4. 审核动作成功后局部刷新。  
5. 抓取按钮成功/失败提示正确。  
6. 无数据空态正常。  

## E2E 流程验收
1. 触发抓取 -> 新事件入队 -> 抽屉查看 -> approve -> summary 更新。  
2. reject/rollback/override 各跑一遍并检查审计字段。  
3. 从旧入口访问，确认 301 到新工作台。

---

## 八、交付清单（必须全部提交）

1. 代码变更（后端 + 前端 + 路由 + 模板）  
2. 自动化测试代码  
3. 接口文档（OpenAPI 或 markdown）  
4. 回归测试记录（截图+步骤）  
5. 已知问题清单（如有）

---

## 九、Definition of Done（验收标准）
满足以下全部条件才算完成：

1. 用户从任意旧入口都进入 `/policy/workbench/`。  
2. 单页能完成抓取、审核、生效、回滚、配置、查看趋势。  
3. 详情抽屉可用，不再出现“开发中”占位。  
4. `P0-P3` 口径按“全部已生效事件”计算并通过测试。  
5. 所有关键接口具备鉴权、CSRF、防错响应。  
6. 自动化测试通过，E2E 主流程通过。

---

## 十、默认假设
1. 不新增强制数据库迁移字段（优先复用现有模型）。  
2. 使用现有 AI 分类器与情绪计算服务，不新增模型供应商接入。  
3. 仅内部运营/投研使用，权限按 staff 严格控制。
