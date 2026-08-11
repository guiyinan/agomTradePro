# 治理契约存量覆盖缺口备忘录（2026-08-10）

> 状态：本地软件整改已完成；M9/M10 生产退出证据继续跟踪
> 级别：治理收口 / 存量债务盘点
> 首次盘点：2026-08-10
> 整改回写：2026-08-11
> 上位计划：[数据中台唯一真源重构计划](data-center-canonical-architecture-refactor-2026-08-02.md)

## 结论

本备忘录列出的 G1–G4 本地软件缺口已完成整改：

- Application 层实际存在的 108 个 `@shared_task` 已全部纳入全量扫描；其中 87 个登记规范任务契约，21 个登记为有 owner、理由和 canonical target 的严格兼容豁免。
- Data Center 外 4 处 HTTP 调用已逐项审查，均确认为非数据出站调用；已登记精确 owner、scope 和理由，待审查数归零。
- Data Center provider 凭证明文字段、旁表兼容和运行时回退已删除，凭证统一改由 Config Center secret refs 提供。
- 备份投递的 `SystemSettings` 密文字段及 legacy ref/fallback 已删除，运行时只接收 Config Center canonical secrets 的 typed ephemeral projection。
- 本地契约、迁移、库存和架构门禁已补齐；生产数据库上的零读取/零写入观察、备份恢复、物理退场和重建证据仍归 M9/M10，不在本次无真实数据开发中伪造完成。

因此，本文件不再作为“待开发清单”，而作为本次整改记录以及 M9/M10 的退出证据挂接点。

## 2026-08-11 整改记录

### G1. Celery outcome 契约：已闭合

首次备忘录只列出 19 个显眼缺口；整改时将检查器扩展到全部 `apps/*/application/**/*.py` 后，发现仓库实际共有 108 个 Application `@shared_task`，旧登记仅覆盖 31 个。最终处理结果为：

| 分类 | 数量 | 处理 |
|---|---:|---|
| 规范任务 | 87 | 登记 canonical task path、适用 outcome/计数语义和精确测试证据 |
| 兼容 alias/wrapper | 21 | 登记 owner、理由和 canonical target；测试证明 exact delegation，不复制业务逻辑 |
| 未覆盖 | 0 | 全量扫描 fail closed |

检查器同时补强：

- 扫描全部 Application Python 文件，而非依赖人工维护的文件清单。
- 识别 decorator 的显式 Celery `name=`；没有显式名称时使用 canonical module path。
- 拒绝缺 owner/reason/target、通配、重复、陈旧或 target 未登记的豁免。
- 发现嵌套定义的 `shared_task`，避免通过非模块级符号绕过登记。
- 源文件语法错误以稳定 `source_parse_error` 报告，不用 traceback 中断全量审计。

业务任务已统一发布 `outcome=success/partial/noop/blocked/failed`，并在适用边界发布同单位的 `requested/succeeded/failed/stored`；cleanup 零删除不再伪报成功，批处理部分失败和全部失败不再被 Celery 自身 SUCCESS 掩盖。

主要证据：

- `python scripts/check_celery_task_contracts.py`：`87 registered task(s), 21 exemption(s), 21 governed file(s)`。
- 检查器单元测试：12 passed。
- G1 聚合 focused 回归：129 passed。
- 分组回归还覆盖 policy、account、alpha、simulated trading、regime、task monitor、backtest、broker、readiness、pulse、signal 和 equity compatibility。

### G2. Data Center 外 HTTP 调用：已闭合

4 处调用均是真实在用、但不属于数据 provider 采集的出站能力，迁入 Data Center 会破坏 owner 语义：

| 调用面 | Owner | Scope | 处置 |
|---|---|---|---|
| Dashboard AI client | `ai-provider` | `ai_inference` | 精确批准 |
| Terminal HTTP client | `terminal` | `internal_control_plane` | 精确批准 |
| Shared alert service | `task-monitor` | `alert_delivery` | 精确批准 |
| Shared alerts | `platform-observability` | `alert_delivery` | 精确批准 |

真源为 `governance/data_center_external_http_dispositions.json`。Inventory 只接受 path/import/owner/scope 的 exact match，并拒绝 wildcard、duplicate 和 stale disposition。

刷新结果：

- `external_http_imports_for_review = 0`
- `approved_non_data_http_imports = 4`
- `provider_imports_outside_data_center = 0`
- `direct_data_center_imports_outside_data_center = 0`

### G3. Provider 凭证明文遗留：已闭合

已完成以下切换：

- 删除 `ProviderConfigModel.api_key/api_secret` 明文字段。
- 删除旧 `ProviderCredentialModel` 旁表及公开重导出。
- 删除 admin、summary、repository 和 runtime 的明文 fallback。
- 删除旧 `encrypt_provider_credentials` 管理命令。
- `ProviderCredentialStore` 改为使用 Config Center public secret ports 和稳定 secret refs。
- 新增 `data_center.0067_move_provider_credentials_to_config_center`：拒绝仍有明文的数据库，拒绝 canonical ref/ciphertext 冲突，迁移既有密文而不把明文重新暴露；reverse 重建旧密文旁表供迁移回退。

`governance/data_center_provider_credential_contracts.json` 现为 `legacy_plaintext_paths = []`；凭证 owner 检查器验证 11 个登记项。

### G4. 备份密钥兼容路径：已闭合

已完成以下切换：

- 删除 `SystemSettingsModel` 的备份 archive/SMTP 两个密文字段及 getter/setter。
- 删除 legacy secret ref map、旧投影回填和迁移管理命令。
- 运行时改用带 `archive_password`/`smtp_password` 的 typed ephemeral settings；不再把 secret 写回旧 model。
- `core/encryption_readiness.py` 改为检查 canonical Config Center secret presence 与 typed runtime secret。
- 新增 `config_center.0015_remove_legacy_backup_secret_columns`：删除字段前校验 canonical secret 与 legacy secret 的解密后明文等价；缺失、冲突或不可证明时整笔迁移 fail closed。

`governance/backup_delivery_secret_contracts.json` 现为 `legacy_compatibility_paths = []`，ownership checker 报告 `legacy writes = 0`。

迁移验证使用隔离 SQLite 完成 `0015/0067` 正向、阻断及回退场景：4 passed。相关纯单元 13 passed，component（`--no-migrations`）14 passed。

## 债务牌子与 M9/M10 挂接

下列项目不再混称为 G1–G4 软件缺口。能在本地清理的已经清理；必须依赖生产观察或物理退场的，保留在上位计划的 M9/M10 中：

| 项 | 2026-08-11 状态 | 退出条件 |
|---|---|---|
| 跨 App ORM 引用 | Inventory 仍为 51 | 按 M9 完成生产零读/零写观察后删除旧 adapter/repository/task/import；不能用豁免或改计数伪装清零 |
| 大文件基线 | 7 个有 owner/rationale/plan/review_by 的存量文件 | 按各自计划拆分；新增或过期豁免继续由 governance gate 拒绝 |
| Application 三方库豁免 | 已从 1 清到 0 | 本地闭合；alpha Application 不再直接依赖该三方库 |
| mypy 债务 | 0 errors / 0 files | 本地闭合；继续执行只降不升门禁 |
| development 配置源 | `intentional_bootstrap_only` | 明确仅用于本地 DB 建立前 bootstrap；shared/staging/production-like 必须使用 Config Center，禁止变成生产 fallback |
| SystemSettings compatibility | 34 个兼容字段 | 备份 secrets 已物理删除；其余 account/market/decision/alpha 按 M9 零读写证据逐组退场 |

当前允许的大文件是机器真源中的精确清单，不再沿用首次备忘录中“5 个”的过期数字：

- `apps/data_center/domain/market_structure.py`
- `apps/data_center/infrastructure/models.py`
- `apps/equity/application/use_cases.py`
- `apps/fixed_income/domain/portfolio_risk.py`
- `apps/risk_center/infrastructure/scenario_governance_repository.py`
- `apps/sector/domain/industry_operating_template.py`
- `apps/terminal/infrastructure/tui_metadata_runtime_injection_risk_center.py`

M9 负责生产零读写观察、旧入口/桥接/字段/表的物理退场和独立 destructive migration；M10 负责生产重建、备份恢复、profile、backfill、reconciliation 与 readiness 证据。详见[上位计划](data-center-canonical-architecture-refactor-2026-08-02.md)的 M9/M10。

## 验证证据

已取得的核心结果：

```text
python scripts/check_celery_task_contracts.py
  87 registered, 21 exemptions, 108/108 covered

python scripts/check_data_center_provider_credentials.py
  11 entries validated

python scripts/check_backup_delivery_secret_ownership.py
  legacy writes = 0

python scripts/check_system_settings_field_contract.py
  46 fields / 7 groups; compatibility = 34

python scripts/check_runtime_config_coverage.py
  49 refs; development source = environment_bootstrap

python scripts/data_center_entrypoint_inventory.py --write
  1120 total; candidate-review = 0

python scripts/check_current_data_contracts.py
  46 surfaces validated

python scripts/check_governance_consistency.py
  governance violations = 0

python scripts/verify_architecture.py --include-audit --format text
  2514 files; boundary violations = 0; audit violations = 0

python scripts/check_mypy_debt_ceiling.py
  0 errors in 0 files

python manage.py check
  0 issues

python manage.py makemigrations config_center data_center --check --dry-run
  no changes detected
```

格式、类型与架构验证在整改后统一执行；增量 mypy 为 0 regressions。生成的 Data Center architecture/entrypoint inventories 均由脚本重建，不手工伪造计数。`simulated_trading` 通知 helper 已机械拆出，主任务模块保持在 1200 非空行门禁以内，拆分后相关回归 49 passed。

## 完成定义

### 本地软件整改（已达到）

- `celery_task_contracts.json` 覆盖全部 108 个存量 Application `@shared_task`，无未登记任务。
- `external_http_imports_for_review = 0`，所有批准项均有精确 owner/scope/reason。
- `legacy_plaintext_paths = 0`、`legacy_compatibility_paths = 0`。
- Config Center/Data Center secret cutover migration 能在缺失、冲突和不等价时原子阻断。
- 生成 inventory 无 `candidate-review`，新增治理路径有明确生命周期分类。
- 本地 governance、architecture、format、typing 与 focused tests 通过。

### 生产退出证据（未伪造完成，继续由 M9/M10 管理）

- 生产观察窗证明旧表、旧字段、旧 adapter 和跨 App ORM 路径零读零写。
- 在经验证备份/恢复点之后执行独立物理删除迁移。
- 完成生产 profile、backfill、reconciliation、readiness 和回滚证据。
- 依据真实生产观测核销剩余 SystemSettings compatibility 与跨 App ORM 计数。
