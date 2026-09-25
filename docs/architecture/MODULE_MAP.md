# AgomTradePro 模块架构地图（Module Map）

> **版本**: V1.0
> **生成日期**: 2026-09-25
> **文档角色**: `governance/module_map.json` 的字段说明书与使用指南
> **投影真源**: 代码树（`apps/`）；生成脚本 `scripts/build_module_map.py`

---

## 1. 定位：生成投影，不是第二真源

`governance/module_map.json` 是代码树的**生成投影（generated projection）**，定位与
`requirements-prod.txt` 之于 `pyproject.toml` 完全相同：

- **唯一真源是代码**。JSON 里没有任何信息是代码之外的增量知识。
- **禁止手工编辑**。文件头自带 `projection_notice`，改动模块结构后必须重新生成。
- 生成的唯一方式是：

```bash
python scripts/build_module_map.py        # 写入 governance/module_map.json
python scripts/build_module_map.py --stdout   # 调试：打印到标准输出
python scripts/check_module_map.py        # 校验：内存重生成并与文件做深度比较
```

`check_module_map.py` 在 CI 的架构守卫工作流（`architecture-layer-guard.yml` 的
`layer-guard` job）中执行。漂移检测的方式是**字节级再生成**：检查脚本在内存中重新扫描
`apps/`，与提交的文件做深度相等比较，因此输出必须无时间戳、无 git hash、键序确定，
否则每次提交都会误报漂移。

## 2. 字段说明书

所有路径键均为**模块相对路径**（POSIX 风格），如 `application/services.py`。
空集合字段整体省略，但 `layers` 始终输出。

| 字段 | 含义与统计口径 |
| --- | --- |
| `layers` | 每个一层目录下的 `.py` 文件数。标准四层 `domain/application/infrastructure/interface` 加上 `management` 按目录名计数；顶层散落文件（`apps.py`、`composition.py`、`models.py` 等）计入 `"root"`；额外的含 Python 目录（如 `tests`、`templatetags`）按实际目录名计入。`migrations` 与 `__pycache__` 全局排除。 |
| `entrypoints` | 仅扫描 `application/` **直下**（不进子目录、跳过 `__init__.py`）的文件，列出顶层公开类名与（异步）函数名（名字不以 `_` 开头）。用途：快速回答"这个模块对外提供哪些用例/服务"。 |
| `orm_models` | 仅扫描 `infrastructure/` 内名为 `models.py` 或位于 `models/` 包内的文件。**启发式**：模块级 `ClassDef` 的任一基类的最终标识符等于 `Model` 或以 `Model` 结尾（覆盖 `models.Model`、`TypedModel`、`TimeStampedModel`），且不在排除名单（`ABC`、`ABCMeta`、`Protocol`、`Generic`、`TypedDict`）内。只看模块级类，因此内部 `Meta` 类不会被误报。这是启发式而非语义判定：手写的非 Django `*Model` 基类会被计入，继承自定义抽象模型基类的实体可能被漏计。 |
| `celery_tasks` | 模块内任意位置被 `@shared_task` 或任意 `@<x>.task`（含调用形式 `@shared_task(...)`、`@app.task(...)`）装饰的函数名，按模块相对路径归组。 |
| `http_routes` | 模块内任意位置名为 `urls.py` / `api_urls.py` 的文件中，`path(...)` / `re_path(...)` 调用的第一个位置参数字符串字面量。无字面量首参的 `include(...)` 式注册被跳过。 |
| `depends_on` | 本模块对 `apps.<other>` 的 **import 语句**计数（按语句计，不按文件计；同一语句多个别名仍算一条）。相对导入用与 `scripts/data_center_architecture_inventory.py` 相同的算法解析为绝对路径；`from apps import macro` 形式按别名计入目标模块（`target_layers` 记 `root`）。`target_layers` 是被导入路径第三段的排序去重集合（`apps.macro.infrastructure.models` → `infrastructure`；裸 `apps.macro` → `root`；`apps.x.composition.y` → `composition`）。模块不会列出自己。 |
| `depended_by` | `depends_on` 的反向索引（全部模块扫描完成后计算），只含 import 计数。 |

## 3. 使用命令

```bash
# 重新生成（改动模块结构/依赖/入口/路由后必做）
python scripts/build_module_map.py

# 校验投影是否新鲜（CI 在 layer-guard job 中执行）
python scripts/check_module_map.py
```

校验失败时会打印模块级/字段级差异摘要，并提示 `run: python scripts/build_module_map.py`。

## 4. Debug 用法示例

以下示例均基于当前生成结果（44 个模块、210 条模块间依赖边）。

### 4.1 某模块被谁依赖（改接口前评估爆炸半径）

```bash
python -c "import json; d=json.load(open('governance/module_map.json',encoding='utf-8'))['modules']; print(sorted(d['regime']['depended_by']))"
# ['account', 'agent_runtime', 'ai_capability', 'alpha_trigger', 'asset_analysis',
#  'audit', 'backtest', 'beta_gate', 'dashboard', 'decision_rhythm', 'equity',
#  'fund', 'macro', 'policy', 'prompt', 'rotation', 'sector', 'sentiment',
#  'signal', 'simulated_trading', 'strategy', 'terminal']
```

### 4.2 谁绕过 application 层直接 import 了别人的 infrastructure

```bash
python -c "
import json
d = json.load(open('governance/module_map.json', encoding='utf-8'))['modules']
for m, rec in sorted(d.items()):
    for tgt, info in rec.get('depends_on', {}).items():
        if 'infrastructure' in info['target_layers']:
            print(f'{m} -> {tgt}.infrastructure ({info[\"imports\"]} imports)')
"
# 示例输出：account -> regime.infrastructure (2 imports) 等
```

这些是当前存量事实（投影不评判），整改红线由 `architecture_rules.json` 与
`check_architecture_delta.py` 负责；本字段用于定位存量违规的具体模块对。

### 4.3 某 Celery 任务属于哪个模块、哪个文件

```bash
python -c "
import json
d = json.load(open('governance/module_map.json', encoding='utf-8'))['modules']
for m, rec in d.items():
    for f, tasks in rec.get('celery_tasks', {}).items():
        if 'sync_macro_data' in tasks:
            print(m, f)
"
# macro application/tasks.py
```

## 5. 与现有治理文件的关系

| 治理文件 | 管什么 |
| --- | --- |
| `governance/architecture_rules.json` | **红线**：层间/模块间哪些依赖方向被禁止（由 `verify_architecture.py`、`check_architecture_delta.py` 执行）。 |
| `governance/module_cycle_allowlist.json` | **环**：模块级循环依赖的存量白名单与预算（由 `check_module_cycles.py` 执行）。 |
| `governance/module_map.json` | **结构事实**：每个模块的层、入口、模型、任务、路由与依赖投影（由 `check_module_map.py` 做漂移检测）。 |

三者职责正交：module_map 不做判定，只回答"现状是什么"，让红线和白名单规则的变化
可以先在投影上观察影响面。

**字段选型理由**：`layers/entrypoints/orm_models/celery_tasks/http_routes/depends_on/depended_by`
对应调试一个陌生模块时最常问的六个问题（有多大、入口在哪、表在哪、任务在哪、URL 在哪、
和谁耦合）。**字段级数据血缘（field-level lineage，如某 entrypoint 引用了哪些
repository）刻意留作后续扩展**：当前版本优先保证字节级确定性与零运行时依赖，血缘分析
需要跨文件符号解析，复杂度和误报率都上一个量级，等投影消费场景稳定后再评估。

## 6. 落地过程记录（2026-09-25）

- **为什么是生成式**：项目已有 `data_center_architecture_inventory.py` 的成熟模式
  （纯 AST 静态扫描、不导入 Django、不触库、输出进 `governance/`），本投影完全复用该
  模式，包括 `_resolved_import_from_module` 的相对导入解析算法，保证两个扫描器对同一
  import 的解析结果一致。
- **为什么无时间戳/无 git hash**：检查脚本用"内存重生成 + 深度相等"做漂移检测，任何
  非代码因素的字节变化都会造成误报，因此输出只含代码树可推导的内容。
- **漂移检测的实现**：`check_module_map.py` 将 `scripts/` 加入 `sys.path` 后直接复用
  `build_module_map.build_module_map()`，先校验 `schema_version`/`generated_by` 身份
  字段，再比较 `modules` 树，失败时打印到"模块 + 字段名"粒度的差异摘要。
- **意外发现**：44 个模块全部存在四层目录，但全部模块都有顶层散落 `.py` 文件
  （`apps.py`/`composition.py`/遗留 `models.py` 等，计入 `"root"`）；`alpha` 等模块存在
  层外目录（`tests/`、`templatetags/`），按实际目录名计入 `layers`；`sync_macro_data`
  这类任务同时出现在 `entrypoints` 与 `celery_tasks` 中属预期（同一函数两种视角）。

---

**文档维护**: AgomTradePro Team
**最后更新**: 2026-09-25
