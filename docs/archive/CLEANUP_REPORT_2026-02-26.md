# 文档整理报告

> **整理日期**: 2026-02-26
> **执行人**: Claude Code
> **状态**: ✅ 完成

---

## 一、整理概览

| 项目 | 整理前 | 整理后 | 变化 |
|------|--------|--------|------|
| docs 下 Markdown 文件总数 | 117 | 118 | +1 |
| docs 子目录总数 | 23 | 28 | +5 |
| 归档文件总数（archive + testing/archive） | 3 | 30 | +27 |

---

## 二、清理操作

### 2.1 删除的文件/目录

| 类型 | 路径 | 原因 |
|------|------|------|
| 空目录 | `docs/regime/` | 目录为空，无内容 |
| 重复文件 | `docs/plans/phase-5-integration-summary.md` | 与 `phase5-integration-summary.md` 内容重复 |

### 2.2 归档的文件（25个）

#### plans/ → archive/plans/ (12个)
- `phase1-alpha-implementation-summary.md`
- `phase2-qlib-inference-summary.md`
- `phase3-training-summary.md`
- `phase4-monitoring-summary.md`
- `phase5-integration-summary.md`
- `phase2-rotation-implementation-summary.md`
- `phase-3-factor-implementation-summary.md`
- `phase-4-hedge-implementation-summary.md`
- `factor-rotation-hedge-implementation-summary.md`
- `decision-platform-enhancement-2026-02-04.md`
- `uat-execution-plan-2026-02-18.md`
- `ui-ux-improvement-prd-2026-02-18.md`

#### fixes/ → archive/fixes/ (3个)
- `2026-02-17-static-api-cleanup.md`
- `api-routing-governance-plan-2026-02-18.md`
- `template-convergence-plan-2026-02-18.md`

**注**: `fixes/` 目录已删除，内容移至 `archive/fixes/`

#### frontend/ → archive/frontend/ (4个)
- `epic-a-refactor-checklist-2026-02-18.md`
- `equity-fund-refactor-guide-2026-02-18.md`
- `routing-governance-report-2026-02-18.md`
- `visual-consistency-report-2026-02-18.md`

#### development/ → archive/development/ (2个)
- `rectification-2026-02-23.md`
- `outsourcing-task-book-2026-02-22.md`

#### testing/ → testing/archive/ (4个)
- `uat-memo-2026-02-07.md`
- `UAT_E2E_Test_Report_2026-02-21.md`
- `uat-route-baseline-2026-02-21.md`
- `outsourcing-test-fix-review-2026-02-20.md`

**注**: 合并到已有的 `testing/archive/` 目录

---

## 三、重组操作

### 3.1 文件移动

| 原路径 | 新路径 | 说明 |
|--------|--------|------|
| `docs/quickStart0205.md` | `docs/QUICK_START.md` | 重命名为标准格式 |
| `docs/simulated-daily-inspection.md` | `docs/modules/simulated_trading/daily-inspection.md` | 移入模块文档 |
| `docs/strategy-position-management.md` | `docs/modules/strategy/position-management.md` | 移入模块文档 |

### 3.2 新增目录

| 目录 | 说明 |
|------|------|
| `docs/modules/simulated_trading/` | 模拟盘模块文档 |
| `docs/modules/strategy/` | 策略模块文档 |
| `docs/archive/plans/` | 归档的实施计划 |
| `docs/archive/fixes/` | 归档的修复记录 |
| `docs/archive/frontend/` | 归档的前端文档 |
| `docs/archive/development/` | 归档的开发文档 |

---

## 四、一致性修复

### 4.1 模块数量更新

| 项目 | 旧值 | 新值 | 说明 |
|------|------|------|------|
| 业务模块数 | 27 | 28 | 新增 `task_monitor` 模块 |

### 4.2 INDEX.md 更新

- ✅ 移除已归档文件的链接
- ✅ 添加新模块文档链接
- ✅ 添加 QUICK_START.md 链接
- ✅ 添加归档索引链接
- ✅ 更新模块分类（工具模块 5→6）
- ✅ 更新最近更新记录

---

## 五、最终目录结构

```
docs/
├── INDEX.md                    # 主索引（已更新）
├── QUICK_START.md              # 快速启动指南（新位置）
├── ai/                         # AI 相关文档 (3个)
├── architecture/               # 架构设计 (8个)
├── archive/                    # 归档文档 (23个)
│   ├── ARCHIVE_INDEX.md        # 归档索引（新增）
│   ├── development/            # 开发归档
│   ├── fixes/                  # 修复归档
│   ├── frontend/               # 前端归档
│   ├── plans/                  # 计划归档
│   └── ...                     # 其他归档文件
├── business/                   # 业务逻辑 (5个)
├── deployment/                 # 部署文档 (8个)
├── development/                # 开发指南 (13个)
├── frontend/                   # 前端体验 (2个)
├── integration/                # 集成文档 (4个)
├── modules/                    # 模块文档 (10个)
│   ├── alpha/
│   ├── audit/
│   ├── factor/
│   ├── hedge/
│   ├── rotation/
│   ├── simulated_trading/      # 新增
│   └── strategy/               # 新增
├── plans/                      # 实施计划 (9个)
├── refactoring/                # 重构文档 (2个)
├── teaching/                   # 教学文档 (3个)
├── testing/                    # 测试文档 (11个 + archive/)
└── user/                       # 用户指南 (2个)
```

---

## 六、建议后续工作

1. **定期归档**: 每个版本发布后，将过程性文档移至 archive/
2. **文档审阅**: 检查 `development/` 目录下是否有过时的指南
3. **API 文档同步**: 确保 `testing/api/openapi.yaml` 与代码保持同步
4. **teaching/ 目录**: 评估是否需要保留或整合到其他目录

---

**整理完成时间**: 2026-02-26
**验证状态**: ✅ `docs/INDEX.md` 主索引链接有效
