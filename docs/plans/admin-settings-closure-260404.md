# 设置中心 / 管理控制台 后续收口计划

## Summary

本轮已经完成的收口：

- 导航栏完成一级职责拆分：
  - `设置中心` 负责配置类入口
  - `管理控制台` 负责管理员操作与运维入口
  - `Django Admin` 只保留底层模型和未产品化功能
- `/settings/` 已成为统一设置 hub
- `/admin-console/` 已成为管理员统一 hub
- `MCP 工具 / 市场数据 / 文档管理 / 服务端日志 / 用户管理 / Token 管理 / 系统设置 / 文档编辑` 等页面已经统一到同一套 `admin shell`
- 一批旧页面的顶部语义、返回路径、边界文案已经统一

当前还没有完全收口的，不是“入口定义”，而是以下三类残留：

- 仍有部分业务管理页保留旧视觉和旧文案
- 各模块自己的管理页还没有完全对齐到同一套页面骨架
- 页面归属虽然大体清楚，但还缺一个正式的“后台入口矩阵 + ownership 约束”

这份计划用于后续继续收口，不要求一次做完，但要求每一轮都能形成稳定、可验证的边界。

## Target State

目标状态固定为：

- 所有系统级配置页统一从 `设置中心` 进入
- 所有管理员值守/运维/内容治理页统一从 `管理控制台` 进入
- 所有页面顶部都能明确回答：
  - 这页属于哪个入口域
  - 这页负责什么
  - 不负责什么
  - 用户下一步该去哪里
- 同类页面共享一套壳层：
  - hero
  - action bar
  - boundary banner
  - surface/card/list/form 基础样式
- 不再出现“功能明明属于设置域，但页面长得像另一个后台系统”的割裂感

## Scope

### A. 继续收口的重点页面

优先级最高：

- `core/templates/ai_provider/usage_logs.html`
- `core/templates/ai_provider/detail.html`
- `core/templates/share/manage.html` 的细节视觉继续打磨
- `core/templates/policy/rss_logs.html`
- `core/templates/policy/rss_keywords.html`
- `core/templates/policy/rss_reader.html`

第二优先级：

- `core/templates/strategy/edit.html`
- `core/templates/ai_provider/edit` 相关页
- 其他仍直接挂 `base.html`、但语义上属于后台管理/设置入口的页面

本轮暂不纳入统一 admin shell 的页面：

- 已经有独立完整设计系统的模块后台
- 高交互工作台类页面
- 面向终端用户而非管理员的业务页

### B. 必须补齐的治理文档

- 增加正式的“后台入口归属矩阵”
- 明确每个页面属于：
  - 设置域
  - 管理控制台域
  - 模块运营域
  - 终端用户域
- 明确哪些页面允许使用 `admin shell`
- 明确哪些页面必须保留模块自有壳层

## Implementation Plan

### Phase 1. 页面归属盘点

先做一次清单化盘点，不急着改样式：

- 列出所有带 `manage / settings / logs / edit / config / tools` 语义的页面模板
- 为每一页标注所属入口域
- 识别重复入口、重复按钮、重复文案
- 识别已经有独立设计系统的模块页，避免误收口

交付物：

- 一份页面归属矩阵文档
- 一份待改页面清单，按优先级排序

### Phase 2. 扩展共享壳层

当前 `admin-shell.css` 只覆盖了最基础的 hero / banner / card / surface。

下一步应补齐：

- 表格工具栏样式
- 过滤栏样式
- 分页样式
- 表单两栏/侧栏样式
- 状态 badge 统一语义
- 空状态与辅助说明样式

要求：

- 先扩展共享样式，再改页面
- 不要把每页旧样式简单复制一份到新模板里
- 尽量减少页面级 inline style

### Phase 3. 分批迁移旧管理页

建议按下面顺序推进：

1. AI Provider 系列页
2. Policy RSS 系列页
3. Share 管理系列页
4. 其他零散管理员编辑页

每批迁移都必须做：

- 页面顶部语义统一
- 返回路径统一
- banner 边界说明统一
- surface / filter / table / form 结构统一
- 模板渲染测试补齐

### Phase 4. 路由与入口去重

页面壳层统一后，再收入口：

- 检查导航栏、设置中心、管理控制台、模块页内部按钮是否存在重复入口
- 删除语义重复但价值低的快捷按钮
- 避免一个页面同时出现 3 个不同“返回入口”且互相冲突
- 确保同一能力只有一个主入口，其他入口只能作为次级跳转

### Phase 5. 文案与语言统一

统一规则：

- 设置域页面文案强调“配置 / 默认值 / 开关 / 系统语义”
- 管理控制台页面文案强调“值守 / 审批 / 日志 / 内容维护 / 运维”
- 模块运营页文案强调“该模块自己的操作闭环”

需要重点清理：

- “系统设置 / 系统管理 / 后台管理 / 控制台”混用
- “配置页 / 状态页 / 管理页”混用
- 不同页面对同一能力使用不同中文名称

### Phase 6. 测试与回归补齐

后续每批页面迁移后都应补：

- 页面渲染测试
- 关键入口文案断言
- 关键返回按钮断言
- 至少一条跨入口链路测试

建议新增：

- 管理后台入口 smoke tests
- 设置域入口 smoke tests
- 页面归属矩阵校验测试

如果后面做视觉回归：

- 优先用 Playwright 对以下页面截图对比：
  - `/settings/`
  - `/admin-console/`
  - `/settings/mcp-tools/`
  - `/admin/server-logs/`
  - `/admin/docs/manage/`
  - `/admin/docs/edit/`
  - `/ai/`
  - `/prompt/manage/`
  - `/policy/rss/sources/`
  - `/share/manage/disclaimer/`

## Acceptance Criteria

收口完成的验收标准：

- 后台入口边界文档齐全
- 设置类页面和管理类页面在导航、页面文案、返回路径上无冲突
- 同类后台页面共享同一套基础壳层
- 新增后台页时有明确归属规则，不再靠临时判断
- 模板渲染测试能覆盖主要入口页
- 快速参考文档与实际入口保持一致

## Constraints

- 不要为了“统一”去破坏已经成熟的模块级设计系统
- 不要把普通业务工作台误改成管理后台页
- 不要直接修改 frozen MCP / SDK / OpenAPI 契约名称来追求页面命名统一
- 页面重构优先做壳层与入口语义，不优先重写业务 JS

## Suggested Next Commit Split

建议后续按小批次提交，不要一把梭：

1. `docs: add admin/settings ownership matrix`
2. `refactor: extend admin shell for tables and forms`
3. `refactor: unify ai provider admin pages`
4. `refactor: unify rss operations pages`
5. `refactor: unify share management pages`
6. `test: add admin entry smoke coverage`

## Notes

- 如果后面要继续收口 `factor/manage`、`signal/manage`、`strategy/edit`，应先判断它们是“模块自己的工作台”还是“后台管理页”。
- 若一个页面本质是模块工作台，应优先保留模块设计语言，只对入口文案和返回路径做轻量统一。
- 若一个页面本质是系统配置/管理员操作页，则应优先并入 `admin shell`。
