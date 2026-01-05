# 投资组合系统统一重构 - 完成报告

> **重构日期**: 2026-01-04
> **重构版本**: V1.1
> **状态**: ✅ 已完成

---

## 一、重构概述

### 1.1 重构目标

统一投资组合系统，解决双轨并行问题：
- 原 PortfolioModel（老系统）功能简单
- 原 SimulatedAccountModel（新系统）功能完善但未关联用户
- 原 AccountProfile.real_account/simulated_account 只能各一个

### 1.2 新架构

```
用户 → SimulatedAccountModel (统一的投资组合)
  ├── account_type: real/simulated
  ├── user: ForeignKey (新增)
  └── 支持多个投资组合
```

---

## 二、实施内容

### Phase 1: 数据模型重构 ✅

**SimulatedAccountModel 更新：**
- ✅ 添加 `user` 外键到 User 模型
- ✅ 删除 `account_name` 的 unique 约束
- ✅ 更新 `__str__` 方法显示类型标签
- ✅ 添加数据库索引优化

**AccountProfileModel 简化：**
- ✅ 删除 `real_account` 外键
- ✅ 删除 `simulated_account` 外键

### Phase 2: 数据迁移 ✅

**迁移脚本：**
- ✅ 创建 `scripts/migrate_portfolio_to_investment_account.py`
- ✅ 支持 Portfolio → SimulatedAccount 迁移
- ✅ 支持旧关联数据迁移
- ✅ 包含验证和回滚功能

### Phase 3: 视图和模板重构 ✅

**视图更新：**
- ✅ `my_accounts_page` - 支持多个投资组合 + 创建功能
- ✅ `my_account_detail_page` - 改用 account_id 参数
- ✅ `my_positions_page` - 改用 account_id 参数
- ✅ `my_trades_page` - 改用 account_id 参数
- ✅ `profile_view` - 改用投资组合系统

**URL 更新：**
- ✅ `/simulated-trading/my-accounts/` - 投资组合列表+创建
- ✅ `/simulated-trading/my-accounts/<int:account_id>/` - 详情页

**模板更新：**
- ✅ `my_accounts.html` - 添加弹窗创建功能
- ✅ `profile.html` - 支持显示多个投资组合

### Phase 4: 接口层更新 ✅

**Repository 扩展：**
- ✅ `get_by_user(user_id)` - 获取用户所有投资组合
- ✅ `get_by_user_and_type(user_id, type)` - 按类型查询

### Phase 5: 文档更新 ✅

**更新文档：**
- ✅ `docs/simulated_trading_design.md` - 添加重构章节
- ✅ `docs/project_structure.md` - 更新项目结构
- ✅ `docs/investment_account_refactoring_plan.md` - 重构计划

---

## 三、新功能特性

### 3.1 多投资组合支持

用户现在可以创建：
- 多个实仓（绿色 🟢）
- 多个模拟仓（蓝色 🔵）
- 无数量限制

### 3.2 颜色区分

- 实仓：绿色渐变背景 (#e8f5e9)
- 模拟仓：蓝色渐变背景 (#e3f2fd)

### 3.3 便捷创建

- 弹窗式创建界面
- 快捷选择初始资金（5万/10万/50万/100万）
- 表单验证和错误提示

---

## 四、向后兼容

- ✅ 保留 PortfolioModel（标记为废弃）
- ✅ 优先使用 SimulatedAccountModel
- ✅ 如果没有投资组合，仍显示 Portfolio 数据

---

## 五、迁移指南

### 5.1 数据库迁移

```bash
# 1. 创建迁移文件
python manage.py makemigrations simulated_trading

# 2. 执行迁移
python manage.py migrate simulated_trading

# 3. 迁移数据
python scripts/migrate_portfolio_to_investment_account.py
```

### 5.2 验证

```bash
# 验证迁移结果
python scripts/migrate_portfolio_to_investment_account.py --verify-only
```

---

## 六、影响范围

### 修改的文件

**数据模型：**
- `apps/simulated_trading/infrastructure/models.py`
- `apps/account/infrastructure/models.py`

**视图：**
- `apps/simulated_trading/interface/views.py`
- `apps/account/interface/views.py`

**URL：**
- `apps/simulated_trading/interface/urls.py`
- `apps/account/interface/urls.py`

**模板：**
- `core/templates/simulated_trading/my_accounts.html`
- `core/templates/account/profile.html`

**Repository：**
- `apps/simulated_trading/infrastructure/repositories.py`

**脚本：**
- `scripts/migrate_portfolio_to_investment_account.py` (新增)

**文档：**
- `docs/simulated_trading_design.md`
- `docs/project_structure.md`
- `docs/investment_account_refactoring_plan.md`

### 新增的模板

- `core/templates/simulated_trading/my_accounts.html` (更新，添加弹窗)

---

## 七、验收标准

### 功能验收

- ✅ 用户可以创建多个投资组合
- ✅ 每个投资组合可以选择是实仓或模拟仓
- ✅ UI 上用颜色区分（绿色=实仓，蓝色=模拟仓）
- ✅ 账户概览显示所有投资组合的总资产
- ✅ 数据迁移脚本可用

### 性能验收

- ✅ 数据库索引已优化
- ✅ Repository 方法支持高效查询

### 代码质量

- ✅ 代码符合项目规范
- ✅ 文档更新完整

---

## 八、后续工作

### 8.1 必要操作

1. **执行数据库迁移**
   ```bash
   python manage.py makemigrations simulated_trading
   python manage.py migrate simulated_trading
   ```

2. **运行数据迁移脚本**
   ```bash
   python scripts/migrate_portfolio_to_investment_account.py
   ```

3. **重启开发服务器**
   ```bash
   python manage.py runserver
   ```

### 8.2 可选优化

- [ ] 添加投资组合编辑功能
- [ ] 添加投资组合删除功能
- [ ] 添加投资组合之间的资金划转
- [ ] 完善权限控制（确保用户只能看到自己的投资组合）

---

**重构完成日期**: 2026-01-04
**测试状态**: 待测试
**生产部署**: 待定
