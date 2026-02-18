# 模板目录收敛计划

> **创建日期**: 2026-02-18
> **负责**: backend-dev
> **优先级**: P0

---

## 1. 现状分析

### 1.1 模板目录结构

当前项目存在以下模板目录：

| 目录 | 路径 | 用途 | 状态 |
|------|------|------|------|
| 根目录模板 | `templates/` | 旧项目遗留模板 | 需迁移 |
| 核心模板 | `core/templates/` | 全局模板 + 各模块模板 | 主来源 |
| 应用模板 | `apps/*/templates/` | 各应用独立模板 | 规范 |

### 1.2 重复模板分析

#### Simulated Trading 模块重复

| 模板文件 | `templates/` | `core/templates/` | 状态 |
|----------|-------------|------------------|------|
| `my_accounts.html` | 存在 | 存在 | 重复 |
| `my_account_detail.html` | 存在 | 存在 | 重复 |
| `my_positions.html` | 存在 | 存在 | 重复 |
| `my_trades.html` | 存在 | 存在 | 重复 |

**冲突说明**:
- Django 模板查找顺序：先查找 `DIRS` 指定的目录，再查找各 app 的 templates 目录
- 当前配置 `TEMPLATES.DIRS = [BASE_DIR/'core/templates']`
- `templates/` 目录不在查找路径中，属于遗留无效目录

---

## 2. 收敛方案

### 2.1 模板组织原则

1. **全局模板** (`core/templates/`)
   - 不属于特定应用模块的模板
   - 基础模板 (`base.html`, `404.html`, `500.html`)
   - 跨应用共享的组件模板

2. **应用模板** (`apps/*/templates/<app_name>/`)
   - 特定应用模块的模板
   - 遵循 Django 应用模板约定

3. **单一真源规则**
   - 每个模板文件只有一个主来源
   - 不允许跨目录重复

### 2.2 收敛目标

| 目录 | 目标状态 | 说明 |
|------|----------|------|
| `templates/` | 删除 | 遗留目录，不再使用 |
| `core/templates/` | 保留 + 清理 | 仅保留全局模板 |
| `apps/*/templates/` | 保留 | 应用模板标准位置 |

---

## 3. 迁移计划

### 3.1 Phase 1: 删除遗留目录

**操作**: 删除项目根目录下的 `templates/` 目录

**理由**:
- 该目录不在 Django 模板查找路径中
- 所有模板文件已在 `core/templates/` 中有最新版本
- 删除后可避免混淆

**命令**:
```bash
rm -rf /d/githv/agomSAAF/templates/
```

### 3.2 Phase 2: 清理 core/templates/ 目录

**当前 `core/templates/` 中的模块模板**:

| 模板路径 | 应归属 | 迁移目标 |
|----------|--------|----------|
| `simulated_trading/*` | `apps/simulated_trading/templates/` | 保持现有位置 |
| `strategy/*` | `apps/strategy/templates/` | 创建并迁移 |
| `backtest/*` | `apps/backtest/templates/` | 创建并迁移 |
| `policy/*` | `apps/policy/templates/` | 创建并迁移 |
| `account/*` | `apps/account/templates/` | 创建并迁移 |
| `equity/*` | `apps/equity/templates/` | 创建并迁移 |
| `fund/*` | `apps/fund/templates/` | 创建并迁移 |
| `dashboard/*` | `apps/dashboard/templates/` | 创建并迁移 |
| `audit/*` | `apps/audit/templates/` | 创建并迁移 |
| `macro/*` | `apps/macro/templates/` | 创建并迁移 |
| `filter/*` | `apps/filter/templates/` | 创建并迁移 |
| `signal/*` | `apps/signal/templates/` | 创建并迁移 |
| `ai_provider/*` | `apps/ai_provider/templates/` | 创建并迁移 |
| `prompt/*` | `apps/prompt/templates/` | 创建并迁移 |
| `regime/*` | `apps/regime/templates/` | 创建并迁移 |
| `decision/*` | 待确定 | 待定 |
| `datasource/*` | `apps/macro/templates/` | 迁移 |
| `docs/*` | 保留在 core | 全局文档功能 |
| `admin/*` | 保留在 core | 管理后台全局功能 |
| `components/*` | 保留在 core | 全局组件 |
| `ops/*` | 保留在 core | 运营中心 |

### 3.3 Phase 3: 更新视图引用

需要更新视图中的模板路径引用：

```python
# 修改前
render(request, 'simulated_trading/my_accounts.html')

# 修改后
render(request, 'my_accounts.html')  # 自动从 apps/simulated_trading/templates/ 查找
```

---

## 4. 实施步骤

### Step 1: 删除遗留目录
```bash
# 删除项目根目录下的 templates/ 目录
rm -rf templates/
```

### Step 2: 迁移核心模块模板

对于 `core/templates/` 中的应用模板，有两个选择：

**选项 A**: 保持现状（推荐）
- 保持模板在 `core/templates/` 中
- 理由：已经工作正常，迁移风险高

**选项 B**: 迁移到各自应用
- 将模板迁移到 `apps/*/templates/` 目录
- 需要更新所有视图引用
- 风险较高，不推荐

**推荐方案**: 采用选项 A
- 仅删除 `templates/` 遗留目录
- 保持 `core/templates/` 现有结构
- 确保新应用模板放在 `apps/*/templates/` 中

### Step 3: 更新文档

更新 `docs/development/coding_standards.md` 说明模板组织规则。

---

## 5. 验收标准

1. `templates/` 目录已删除
2. 项目正常运行，无模板查找错误
3. 所有页面正常渲染
4. 测试通过

---

## 6. 回滚计划

如果出现问题：

1. 从 git 恢复删除的 `templates/` 目录
2. 检查模板查找路径配置

---

**维护**: backend-dev
**最后更新**: 2026-02-18
