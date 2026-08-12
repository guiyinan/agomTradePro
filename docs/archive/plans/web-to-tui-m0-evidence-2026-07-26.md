# Web → TUI M0 / M0-D 实施证据

> 日期：2026-07-26
> 分支：`dev/feat-tui-design-review-implementation`
> 状态：M0 与 M0-D 已完成；M1 待启动

## 1. 基线身份

| 证据 | 值 |
|---|---|
| M0 起始 commit | `7e706d07caacca8b3e56a486d8c0b6b6ed2cdf37` |
| 初始模板数 | 195 |
| 初始模板 manifest SHA-256 | `e0057a7a0b8b69acd8827d5c476eeb4fd721fd2ce4a0951a7c2ce1dbd8ec846b` |
| reviewed graph 文件 SHA-256 | `92acf9e42ffcf6b76af5abf368297407870159a66e53876855873e2efabb436c` |
| schema | `tui-metadata.v3` |
| IA | `2026-07-21` |
| runtime build | `agomtui-runtime-0.2.0+40a52d5a5e8f` |
| runtime upstream commit | `dff880dff8fe78169c90efd9c7fa6a9546d841a9` |

基线由以下机器产物持续约束：

- `config/tui/migration/web_template_migration.v1.json`
- `docs/plans/web-to-tui-migration-matrix-2026-07-25.csv`
- `scripts/web_template_migration_inventory.py`
- `.github/workflows/consistency-check.yml`

## 2. M0 盘点结果

| 项目 | 数量 |
|---|---:|
| 初始模板 | 195 |
| A：迁入 TUI | 130 |
| B：图表能力后迁入 | 17 |
| C：保留 Web | 41 |
| D：已删除 | 7 |
| 当前物理模板 | 188 |
| 历史 route page | 117 |
| active route page | 110 |
| active route page 已关联 URL/view | 110 |
| active 内联脚本模板 | 108 |
| API 契约待复核标记 | 101 |

盘点没有把静态全文搜索当成路由真源：

- URL/view 使用 Django URL resolver 展平。
- template origin 使用 Django template loader source resolution，不编译模板即可识别 shadow。
- `extends`、`include`、静态资源、内联脚本、API 字面量和 Python template 引用作为补充证据。
- 同模块 helper/view 调用会传播到实际 route callable，覆盖 redirect wrapper、CBV `as_view()` 与共用 render helper。

## 3. M0-D 删除清单

### 3.1 Loader shadow

| 已删模板 | Django 实际命中 |
|---|---|
| `apps/audit/templates/audit/audit_page.html` | `core/templates/audit/audit_page.html`；同时 audit 当前 route 已改用 `audit/review_page.html` |
| `apps/data_center/templates/data_center/monitor.html` | `core/templates/data_center/monitor.html` |
| `apps/data_center/templates/data_center/providers.html` | `core/templates/data_center/providers.html` |

### 3.2 无运行消费者

| 已删模板 | 证据 |
|---|---|
| `apps/audit/templates/audit/attribution_report.html` | 无 view/route/include/task 消费；归因使用 report list/detail 页面和 JSON API |
| `core/templates/account/create_simulated_account.html` | 原 view 已明确退休，创建流程归 `simulated_trading` 的 my-accounts |
| `core/templates/audit/audit_page.html` | `/audit/page/` 与 `/audit/review/` 均渲染 `audit/review_page.html` |
| `core/templates/macro/data_controller.html` | `/macro/controller/` 是到 `/data-center/providers/` 的 redirect-only 兼容路由 |

对应矩阵行保留原始 `content_hash`、解析 origin、reviewer、日期与 `status=deleted`；在形成提交前，`rollback_commit` 保持 `pending_commit`。

## 4. 冻结与架构决策

- `AGENTS.md` 已增加迁移期页面冻结约束。
- CI 已增加 `python scripts/web_template_migration_inventory.py --check`。
- `docs/architecture/adr-0006-tui-primary-interface.md` 已接受 TUI 主界面、Web allowlist、owner app API 与 wave 回滚边界。
- 检查允许矩阵中有证据且 `status=deleted` 的历史行不存在于磁盘，但拒绝未登记新增、未标记删除和“已删除但仍在磁盘”的路径。

## 5. 验证结果

### 5.1 Python / Django

```text
pytest tests/unit/test_web_template_migration_inventory.py \
  tests/component/test_route_name_compatibility.py \
  tests/component/test_template_rendering.py \
  tests/integration/macro/test_datasource_config_api.py::test_data_center_provider_page_renders_canonical_entry \
  tests/integration/macro/test_datasource_config_api.py::test_data_center_monitor_page_renders_runtime_status_entry \
  tests/e2e/test_audit_admin_console.py \
  tests/component/test_core_user_page_contracts.py -q
```

结果：`93 passed`。

M2 认证边界复核将登录/注册从 A 更正为 C；最新
`python scripts/web_template_migration_inventory.py --check`：矩阵 195 行，
A=130、B=17、C=41、D=7。

### 5.2 AgomTradePro TUI

- `validate_tui_metadata.py`：通过，12 screens、402 actions。
- `npm run check:tui`：通过。
- `npm run test:tui-js`：20 passed。

### 5.3 AgomTUI 下游

- `sync_from_agomtradepro.py --check`：全部 `UNCHANGED`。
- `npm run check:runtime`：通过。
- `npm run test:runtime-js`：6 passed。
- 下游 `validate-metadata` / `check-usability`：未通过。首个确定错误为 AgomTUI core 尚不接受 AgomTradePro 已采用的 dashboard panel `empty_message`、`error_message`、`row_actions`、`stale_message` 字段。

该失败属于既有可移植性计划 R3 schema gap，不由模板删除引入。M1 可以先做 host-owned 样板，但其退出门槛和任何通用 schema/runtime 交付必须先关闭此差异。

## 6. 尚未验证

- 全仓 pytest。
- Playwright smoke/UAT。
- PostgreSQL/VPS 行为。
- 生产访问量、14 日兼容窗口和真实回滚演练。

这些项目不属于 M0-D 删除的局部完成声明，仍是 M1-M5 和最终完成审计的必需证据。
