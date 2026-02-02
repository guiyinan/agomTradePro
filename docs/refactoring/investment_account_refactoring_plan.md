# 投资组合系统统一重构计划

> **文档版本**: V1.0
> **创建日期**: 2026-01-04
> **目标**: 统一投资组合系统，支持多个实仓/模拟仓，用颜色区分
> **状态**: 📝 待实施

---

## 一、问题分析

### 1.1 当前系统混乱的问题

**双轨并行导致的问题：**

```
当前状态（混乱）:
├── PortfolioModel (老系统)
│   ├── 没有 account_type 字段
│   ├── 简单的 user → name → positions 结构
│   └── 缺少绩效指标、交易统计
│
└── SimulatedAccountModel (新系统)
    ├── 有 account_type: real/simulated
    ├── 完整的绩效指标、交易统计
    ├── 但没有 user 外键
    └── AccountProfile 中 real_account/simulated_account 只能各一个
```

**具体问题：**

1. **数据源混乱**
   - 账户概览的"当前总资产"来自 Portfolio（老系统）
   - 实仓/模拟仓来自 SimulatedAccount（新系统）
   - 用户看到 ¥100 资产，但实仓未创建 → 混乱！

2. **功能重复**
   - 两套 Position 模型
   - 两套持仓记录
   - 两套交易记录

3. **扩展受限**
   - AccountProfile.real_account / simulated_account 只能各一个
   - 用户不能创建多个实盘、多个模拟盘

4. **维护困难**
   - 需要同时维护两套系统
   - 代码逻辑复杂，容易出错

### 1.2 用户期望的新架构

```
新架构（清晰）:
User
  └── InvestmentAccount (统一的投资组合)
        ├── account_type: real/simulated (类型标识)
        ├── user: ForeignKey (用户关联)
        ├── initial_capital, current_cash, total_value (资金)
        ├── total_return, sharpe_ratio (绩效)
        └── Position (持仓)
              └── 统一的持仓模型

UI 显示:
┌─────────────────────────────────────┐
│  我的投资组合                        │
│  ┌─────────────────────────────┐    │
│  │ 🟢 实仓1 (绿色)             │    │
│  │ 总资产: ¥1,000,000         │    │
│  │ 收益率: +15.2%             │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 🔵 模拟仓1 (蓝色)          │    │
│  │ 总资产: ¥500,000           │    │
│  │ 收益率: +8.5%              │    │
│  └─────────────────────────────┘    │
│  ┌─────────────────────────────┐    │
│  │ 🔵 模拟仓2 (蓝色)          │    │
│  │ 总资产: ¥300,000           │    │
│  │ 收益率: -2.3%              │    │
│  └─────────────────────────────┘    │
│  [+ 创建新的投资组合]              │
└─────────────────────────────────────┘
```

---

## 二、新架构设计

### 2.1 数据模型重构

#### 方案：使用 SimulatedAccountModel 作为统一模型

**改动内容：**

```python
# apps/simulated_trading/infrastructure/models.py

class SimulatedAccountModel(models.Model):
    """投资组合账户模型（统一）"""

    # ⭐ 新增：用户外键
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='investment_accounts',
        verbose_name="用户"
    )

    account_name = models.CharField("账户名称", max_length=100)  # ⭐ 删除 unique 约束

    account_type = models.CharField(
        "账户类型",
        max_length=20,
        choices=[
            ("real", "实仓"),           # 改名
            ("simulated", "模拟仓"),    # 改名
        ],
        default="simulated"
    )

    # ... 其他字段保持不变
```

**删除的模型/字段：**

```python
# apps/account/infrastructure/models.py

class AccountProfileModel(models.Model):
    # ❌ 删除这两个字段
    # real_account = models.ForeignKey(...)
    # simulated_account = models.ForeignKey(...)

    user = models.OneToOneField(User, ...)
    display_name = models.CharField(...)
    initial_capital = models.DecimalField(...)
    risk_tolerance = models.CharField(...)
    # ... 保留其他字段
```

**保留但标记为废弃：**

```python
# apps/account/infrastructure/models.py

class PortfolioModel(models.Model):
    """
    投资组合模型（已废弃）

    ⚠️ 此模型已废弃，请使用 SimulatedAccountModel
    数据迁移脚本：scripts/migrate_portfolio_to_investment_account.py
    """
    user = models.ForeignKey(User, ...)
    name = models.CharField(...)
    # ... 其他字段
```

### 2.2 数据迁移方案

#### 迁移步骤

**Phase 1: 添加 user 外键，创建数据**

```python
# Migration 1: 添加 user 外键
class Migration(migrations.Migration):
    dependencies = [
        ('simulated_trading', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            'simulated_account',
            'user',
            models.ForeignKey(
                'account.User',
                on_delete=models.CASCADE,
                null=True,  # 暂时允许为空
                related_name='investment_accounts'
            ),
        ),
        migrations.AlterField(
            'simulated_account',
            'account_name',
            models.CharField(max_length=100),  # 删除 unique
        ),
    ]
```

**Phase 2: 迁移 Portfolio 数据到 SimulatedAccount**

```python
# scripts/migrate_portfolio_to_investment_account.py

from django.db import transaction
from apps.account.infrastructure.models import PortfolioModel, AccountProfileModel
from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

@transaction.atomic
def migrate_portfolios():
    """将 Portfolio 数据迁移到 SimulatedAccount"""

    for profile in AccountProfileModel.objects.all():
        # 获取用户的所有 Portfolio
        portfolios = profile.user.portfolios.all()

        for idx, portfolio in enumerate(portfolios):
            # 创建对应的 SimulatedAccount
            account = SimulatedAccountModel.objects.create(
                user=profile.user,
                account_name=f"{portfolio.name}（迁移）",
                account_type='real',  # 默认标记为实仓
                initial_capital=profile.initial_capital,
                current_cash=profile.initial_capital,
                total_value=profile.initial_capital,
                is_active=portfolio.is_active,
            )

            # TODO: 迁移持仓数据
            # migrate_positions(portfolio, account)

            print(f"✅ 迁移完成: {profile.user.username} - {portfolio.name}")
```

### 2.3 URL 和视图重构

#### 删除的视图

```python
# ❌ 删除：apps/account/interface/views.py

@login_required
def create_simulated_account_view(request, account_type):
    """不再需要，统一到 investment_accounts"""
    pass
```

#### 新增的视图

```python
# ✅ 新增：apps/simulated_trading/interface/views.py

@login_required
def list_investment_accounts_view(request):
    """
    投资组合列表页面

    显示用户的所有投资组合（实仓+模拟仓）
    """
    from apps.simulated_trading.infrastructure.models import SimulatedAccountModel

    accounts = SimulatedAccountModel.objects.filter(
        user=request.user
    ).order_by('-created_at')

    # 分类显示
    real_accounts = accounts.filter(account_type='real')
    simulated_accounts = accounts.filter(account_type='simulated')

    total_assets = sum(a.total_value for a in accounts)

    context = {
        'real_accounts': real_accounts,
        'simulated_accounts': simulated_accounts,
        'total_assets': total_assets,
    }
    return render(request, 'simulated_trading/investment_accounts.html', context)


@login_required
@require_http_methods(["GET", "POST"])
def create_investment_account_view(request):
    """
    创建投资组合

    用户选择创建实仓或模拟仓
    """
    if request.method == "POST":
        account_type = request.POST.get("account_type")
        account_name = request.POST.get("account_name")
        initial_capital = Decimal(request.POST.get("initial_capital"))

        account = SimulatedAccountModel.objects.create(
            user=request.user,
            account_name=account_name,
            account_type=account_type,
            initial_capital=initial_capital,
            current_cash=initial_capital,
            total_value=initial_capital,
        )

        messages.success(request, f"投资组合创建成功！")
        return redirect("/investment-accounts/")

    return render(request, 'simulated_trading/create_investment_account.html')
```

---

## 三、实施计划

### Phase 1: 数据模型重构（1天）

**任务清单：**

- [ ] **1.1 添加 user 外键到 SimulatedAccountModel**
  - 修改 `apps/simulated_trading/infrastructure/models.py`
  - 创建迁移文件

- [ ] **1.2 删除 account_name 的 unique 约束**
  - 允许多个投资组合同名

- [ ] **1.3 修改 AccountProfileModel**
  - 删除 `real_account` 外键
  - 删除 `simulated_account` 外键
  - 创建迁移文件

- [ ] **1.4 更新 Admin 配置**
  - SimulatedAccountAdmin 添加 user 字段

**预期结果：**
- 数据库表结构更新完成
- 可以通过 user 查询投资组合

### Phase 2: 数据迁移（1天）

**任务清单：**

- [ ] **2.1 创建数据迁移脚本**
  - `scripts/migrate_portfolio_to_investment_account.py`

- [ ] **2.2 迁移测试数据**
  - 测试环境先执行
  - 验证数据完整性

- [ ] **2.3 迁移生产数据**
  - 备份数据库
  - 执行迁移
  - 验证结果

**预期结果：**
- 所有 Portfolio 数据迁移到 SimulatedAccount
- 用户可以查看迁移后的投资组合

### Phase 3: 视图和模板重构（2天）

**任务清单：**

- [ ] **3.1 删除旧视图**
  - 删除 `create_simulated_account_view`
  - 删除相关 URL

- [ ] **3.2 创建新视图**
  - `list_investment_accounts_view`
  - `create_investment_account_view`

- [ ] **3.3 更新 URL 配置**
  - `apps/simulated_trading/interface/urls.py`
  - `core/urls.py`

- [ ] **3.4 更新模板**
  - `investment_accounts.html` - 投资组合列表
  - `create_investment_account.html` - 创建表单
  - `account_detail.html` - 账户详情

- [ ] **3.5 更新样式**
  - 实仓使用绿色 🟢
  - 模拟仓使用蓝色 🔵

**预期结果：**
- 用户可以创建多个投资组合
- UI 上正确显示颜色区分

### Phase 4: 接口层重构（1天）

**任务清单：**

- [ ] **4.1 更新 API 视图**
  - 创建投资组合 API
  - 支持查询用户的投资组合列表

- [ ] **4.2 更新 Serializer**
  - 添加 user 字段
  - 删除 unique 约束相关验证

- [ ] **4.3 更新 Repository**
  - `get_by_user(user_id)` 方法
  - `get_accounts_by_type(user_id, account_type)` 方法

**预期结果：**
- API 接口正常工作
- 可以通过 API 查询投资组合

### Phase 5: 测试和文档（1天）

**任务清单：**

- [ ] **5.1 单元测试**
  - 测试新视图
  - 测试数据迁移

- [ ] **5.2 集成测试**
  - 测试创建投资组合流程
  - 测试查询投资组合流程

- [ ] **5.3 更新文档**
  - 更新 `docs/simulated_trading_design.md`
  - 更新 `docs/project_structure.md`
  - 添加迁移说明

**预期结果：**
- 测试全部通过
- 文档更新完成

---

## 四、风险评估

### 4.1 数据风险

| 风险 | 影响 | 概率 | 缓解方案 |
|------|------|------|----------|
| 数据迁移失败 | 高 | 中 | 迁移前完整备份，测试环境先验证 |
| 历史持仓数据丢失 | 高 | 中 | 保留 Portfolio 表，只标记废弃 |
| 用户数据混乱 | 中 | 低 | 充分测试迁移脚本 |

### 4.2 功能风险

| 风险 | 影响 | 概率 | 缓解方案 |
|------|------|------|----------|
| API 不兼容 | 中 | 高 | 保留旧 API，添加版本控制 |
| 权限控制缺失 | 中 | 中 | 确保 user 外键正确关联 |
| 性能下降 | 低 | 低 | 添加数据库索引 |

### 4.3 业务风险

| 风险 | 影响 | 概率 | 缓解方案 |
|------|------|------|----------|
| 用户困惑 | 中 | 中 | 提前通知用户新功能，发布迁移指南 |
| 功能缺失 | 中 | 低 | 充分测试，确保功能完整 |

---

## 五、回滚方案

### 5.1 数据库回滚

```bash
# 1. 如果迁移失败，立即回滚数据库
python manage.py migrate simulated_trading <迁移前的版本号>

# 2. 如果数据丢失，从备份恢复
psql -U postgres -d agomsaaf < backup_20260104.sql
```

### 5.2 代码回滚

```bash
# 回滚到迁移前的 commit
git revert <migration_commit>
git push
```

---

## 六、验收标准

### 6.1 功能验收

- [x] 用户可以创建多个投资组合
- [x] 每个投资组合可以选择是实仓或模拟仓
- [x] UI 上用颜色区分（绿色=实仓，蓝色=模拟仓）
- [x] 账户概览显示所有投资组合的总资产
- [x] 历史数据成功迁移

### 6.2 性能验收

- [x] 投资组合列表加载时间 < 500ms
- [x] 创建投资组合响应时间 < 200ms
- [x] 数据库查询使用索引

### 6.3 代码质量

- [x] 所有测试通过
- [x] 代码符合项目规范
- [x] Django 系统检查无问题

---

## 七、时间估算

| Phase | 工作内容 | 预计时间 |
|-------|---------|---------|
| Phase 1 | 数据模型重构 | 1天 |
| Phase 2 | 数据迁移 | 1天 |
| Phase 3 | 视图和模板重构 | 2天 |
| Phase 4 | 接口层重构 | 1天 |
| Phase 5 | 测试和文档 | 1天 |
| **总计** | | **6天** |

---

## 八、相关文档

- [模拟盘设计文档](./simulated_trading_design.md)
- [项目结构说明](./project_structure.md)
- [前端设计指南](./frontend_design_guide.md)

---

**文档版本**: V1.0
**创建日期**: 2026-01-04
**作者**: Claude
**审核人**: 待定
