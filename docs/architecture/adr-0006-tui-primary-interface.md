# ADR-0006：TUI 作为日常任务主界面

状态：Accepted（2026-07-26）

## 背景

AgomTradePro 当前有 195 个 Django HTML 模板，其中 114 个包含无 `src` 的内联脚本。Classic Web 页面按模块和技术实现逐步增长，形成重复模板、内联交互测试盲区和跨页面任务割裂。与此同时，`/tui/` 已具备 schema v3、IA registry、reviewed published graph、运行时权限过滤、静态契约与浏览器几何门禁。

迁移不能按模板逐页翻译。TUI screen 的边界必须是用户主任务，后端数据和业务规则继续由所属业务 app 负责。

## 决策

1. `/tui/` 是普通用户日常决策、研究、执行与日常运维主任务的默认界面。
2. Classic Web 收敛为明确的保留清单：外部分享、观察者门户、Setup Wizard、Django Admin、错误页/基座、TUI shell 与低频 docs。
3. 迁移按 `docs/plans/web-to-tui-migration-plan-2026-07-25.md` 的 M0-M5 和小 wave 执行，不按 HTML 文件一一翻译。
4. `config/tui/ia/tui_information_architecture.v1.json` 继续是 screen、workflow、audience 和 alias 的唯一 IA 真源。
5. TUI 优先复用既有 JSON API。发现缺口时，在数据所属 app 内按四层架构补齐纵向切片；`terminal` 不承载金融业务逻辑。
6. 迁移期间冻结新的 Classic 业务主任务。模板集合由 `docs/plans/web-to-tui-migration-matrix-2026-07-25.csv` 和 `scripts/web_template_migration_inventory.py --check` 约束。
7. 旧 URL 必须逐项指定 retain、TUI deep-link redirect、410 或 404，不允许静默落到 TUI 首页。
8. graph、schema、runtime、registry 和模板/路由按 wave 记录兼容性与回滚证据；通用 runtime/schema 变化必须通过 AgomTradePro 与 AgomTUI 双端门禁。

## 后果

### 正面

- 用户任务从分散页面收敛到受机器契约约束的工作台。
- 新 UI 不再依赖大量无法复用和难以测试的内联脚本。
- 权限、确认、重新认证、审计、错误恢复和信息优先级采用统一契约。
- 模板删除、旧 URL 切换和 metadata 发布都有可审计、可回滚的 wave 边界。

### 代价

- 兼容期需要同时维护 Classic 与 TUI，并采集旧入口使用证据。
- 部分页面缺少可供 TUI 使用的 JSON API，需要 owner app 补齐纵向切片。
- 图表、复杂表单和异步任务状态需要先建立通用 renderer 与 view-model 约定。

## 不在本决策中的内容

- 不迁移外部分享、初始化向导和 Django Admin。
- 不改变金融业务规则、数据 owner 或四层依赖方向。
- 不以隐藏前端控件替代后端权限控制。
- 不允许把 AgomTradePro 业务 key 或业务文案写入通用 AgomTUI runtime。

## 执行证据

- 计划：`docs/plans/web-to-tui-migration-plan-2026-07-25.md`
- 迁移矩阵：`docs/plans/web-to-tui-migration-matrix-2026-07-25.csv`
- 规则真源：`config/tui/migration/web_template_migration.v1.json`
- 冻结检查：`python scripts/web_template_migration_inventory.py --check`
- 可移植性计划：`docs/plans/agomtui-portability-remediation-2026-07-21.md`
