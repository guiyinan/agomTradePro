# Web → TUI M2 Policy RSS Wave 证据（2026-07-26）

## 范围与闭环

- Wave：`M2-policy-rss-w20`；覆盖 RSS 源、源表单、关键词、关键词表单、抓取日志和
  Reader，共 6 个 route templates、8 个 Classic route patterns。
- `policy.workbench` 新增 15 个 runtime action：认证用户使用 Reader；管理员治理
  RSS 源、关键词和抓取日志，并可触发单源或全量抓取。
- 新增 `/api/policy/rss/reader/` 认证只读切片。接口复用 Policy Application
  page service，支持来源、档位、类别和分页筛选，单次最多返回 200 行，不把 ORM
  模型暴露到 Interface/Application 边界。
- RSS 源、关键词和抓取日志 Classic 页面统一为 staff-only；Reader 保持
  login-required，未把普通阅读任务错误提升为管理员任务。
- 源表单保留代理、RSSHub、解析器和分类字段；代理密码与 RSSHub access key
  使用 `password` 输入语义，不发布为输出列。抓取动作返回可追踪任务信息，并复用
  task monitor，不把 Classic 页内轮询脚本迁入 runtime metadata。
- 两个 Rotation 共享模板不对应独立 URL 或独立用户任务，已从 M2 route migration
  调整到 M5 `remove_with_consumer`；Classic Rotation 消费者保留期间不提前删除。

## 验证与风险

- 定向页面权限、Reader API、TUI metadata 与 IA：`9 passed`。
- Policy API 边界：`14 passed`。
- RSS API 边界：`3 passed`。
- Policy 集成契约：`7 passed`。
- ruff 与增量 mypy 通过；migration inventory 为
  `templates=195 route_pages=117 A=130 B=17 C=41 D=7`；TUI static contract
  `407 rule(s), 5 source(s)` 通过。
- 真实 live-server Reader 筛选、源/关键词 CRUD、密码回显保护、抓取任务跟踪 UAT
  尚未执行；6 个 Classic route templates 继续保留兼容入口，删除仍受 M5 的稳定期、
  访问量和回滚门槛约束。
