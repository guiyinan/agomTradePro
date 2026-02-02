# AgomSAAF 系统初始化指南

## 概述

AgomSAAF 系统提供了多个管理命令用于初始化系统数据。这些命令需要按顺序执行，确保系统正常运行。

---

## 快速开始（全新安装）

```bash
# 1. 激活虚拟环境
agomsaaf\Scripts\activate

# 2. 执行数据库迁移
python manage.py migrate

# 3. 初始化资产分类和币种
python manage.py init_classification

# 4. 初始化投资规则
python manage.py init_rules

# 5. 初始化系统文档
python manage.py init_docs

# 6. 初始化 Prompt 模板（AI 功能）
python manage.py init_prompt_templates

# 7. 同步宏观数据（可选）
python manage.py sync_macro_data

# 8. 创建超级用户
python manage.py createsuperuser
```

---

## 初始化命令详解

### 1. init_classification - 资产分类和币种初始化

**位置**: `apps/account/management/commands/init_classification.py`

**功能**:
- 创建支持的币种（CNY, USD, EUR, HKD, JPY, GBP）
- 创建资产分类树形结构（基金、股票、债券、理财、存款等）
- 创建初始汇率数据

**运行**:
```bash
python manage.py init_classification
```

**初始化内容**:
- 6 种币种（CNY 为基准货币）
- 9 个一级分类（FUND, STOCK, BOND, WEALTH, DEPOSIT, COMMODITY, CASH, REAL_ESTATE, OTHER）
- 13 个二级分类（股票基金、债券基金、混合基金、活期存款、定期存款、银行理财等）
- 2 条初始汇率（USD/CNY, CNY/USD）

**注意**: 此命令幂等，重复运行会跳过已存在的数据。

---

### 2. init_rules - 投资规则初始化

**位置**: `apps/account/management/commands/init_rules.py`

**功能**:
- 加载系统默认的投资建议规则
- 包含 Regime 象限建议、仓位建议、风险提示等

**运行**:
```bash
python manage.py init_rules
```

**初始化的规则类型**:
- `regime_advice` - Regime 环境建议（复苏、过热、滞胀、通缩）
- `position_advice` - 仓位建议（高/低仓位提示）
- `match_advice` - Regime 匹配度建议
- `signal_advice` - 投资信号建议
- `risk_alert` - 风险提示（高亏损/高盈利警告）

---

### 3. init_docs - 系统文档初始化

**位置**: `apps/account/management/commands/init_docs.py`

**功能**:
- 加载系统帮助文档到数据库
- 文档可在后台管理和前端查看

**运行**:
```bash
python manage.py init_docs
```

**初始化的文档**:
- 投资信号与持仓关系说明
- Regime 投资象限说明
- 用户操作指南

---

### 4. init_prompt_templates - Prompt 模板初始化

**位置**: `apps/prompt/management/commands/init_prompt_templates.py`

**功能**:
- 加载 AI Prompt 模板和链配置
- 用于 AI 分析和建议生成

**运行**:
```bash
# 默认模式（跳过已存在的模板）
python manage.py init_prompt_templates

# 强制重新加载所有模板
python manage.py init_prompt_templates --force

# 只加载链配置
python manage.py init_prompt_templates --chains-only

# 只加载 Prompt 模板
python manage.py init_prompt_templates --templates-only

# 预览模式（不实际写入）
python manage.py init_prompt_templates --dry-run
```

**参数说明**:
| 参数 | 说明 |
|------|------|
| `--force` | 强制覆盖已存在的模板 |
| `--chains-only` | 只加载链配置 |
| `--templates-only` | 只加载 Prompt 模板 |
| `--dry-run` | 预览模式，不实际写入 |

---

### 5. sync_macro_data - 宏观数据同步

**位置**: `apps/macro/management/commands/sync_macro_data.py`

**功能**:
- 从 AKShare 获取宏观经济数据（PMI, CPI, PPI）
- 保存到数据库供 Regime 分析使用

**运行**:
```bash
# 默认：同步最近 10 年的 PMI, CPI, PPI
python manage.py sync_macro_data

# 同步指定指标
python manage.py sync_macro_data --indicators CN_PMI CN_CPI

# 同步最近 N 年的数据
python manage.py sync_macro_data --years 5

# 使用不同数据源（当前只支持 akshare）
python manage.py sync_macro_data --source akshare
```

**参数说明**:
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--source` | akshare | 数据源（当前仅支持 akshare） |
| `--indicators` | CN_PMI CN_CPI CN_PPI | 要同步的指标列表 |
| `--years` | 10 | 同步最近 N 年的数据 |

**可用指标**:
- `CN_PMI` - 中国制造业 PMI
- `CN_CPI` - 中国消费者物价指数
- `CN_PPI` - 中国生产者物价指数

---

## 数据库迁移

### 首次安装

```bash
# 创建所有数据库表
python manage.py migrate

# 或者查看迁移计划但不执行
python manage.py migrate --plan
```

### 重置数据库（开发环境）

```bash
# 删除数据库文件
del db.sqlite3

# 删除迁移记录（保留 __init__.py）
del apps\*/migrations\00*.py

# 重新生成迁移
python manage.py makemigrations

# 重新执行迁移
python manage.py migrate

# 重新初始化数据
python manage.py init_classification
python manage.py init_rules
python manage.py init_docs
python manage.py init_prompt_templates
```

---

## 超级用户创建

```bash
python manage.py createsuperuser
```

按提示输入：
- 用户名
- 邮箱（可选）
- 密码（两次）

创建后可访问 `/admin/` 登录管理后台。

---

## 验证安装

运行以下命令验证系统状态：

```bash
# Django 系统检查
python manage.py check

# 查看已安装的应用
python manage.py showmigrations

# 检查数据库完整性
python manage.py check --database default
```

---

## 常见问题

### Q1: 运行 init_classification 时报错 "No module named 'apps'"

**A**: 确保在项目根目录（`D:\githv\agomSAAF\`）下运行命令，并且虚拟环境已激活。

### Q2: 数据迁移时提示 "No changes detected"

**A**: 这是正常的，说明模型与数据库同步。如需重置，参考"重置数据库"部分。

### Q3: sync_macro_data 获取数据失败

**A**:
- 检查网络连接
- AKShare 接口可能暂时不可用，稍后重试
- 确认已安装 akshare: `pip list | findstr akshare`

### Q4: 如何查看已初始化的数据？

**A**: 访问管理后台 `http://127.0.0.1:8000/admin/`，登录后可以看到：
- 资产分类 (Account → Asset categories)
- 币种 (Account → Currencies)
- 汇率 (Account → Exchange rates)
- 投资规则 (Account → Investment rules)
- 文档 (Documentation → Documents)

---

## 定期维护任务

系统运行后，需要定期执行：

```bash
# 每月更新宏观数据（PMI、CPI 官方发布后）
python manage.py sync_macro_data

# 更新 Prompt 模板（如需要）
python manage.py init_prompt_templates --force
```

可配置 Celery 定时任务自动执行。

---

## 开发环境快速重置脚本

创建 `reset_dev.bat`:

```bat
@echo off
echo AgomSAAF 开发环境重置...

del db.sqlite3 2>nul
del apps\account\migrations\00*.py 2>nul
del apps\backtest\migrations\00*.py 2>nul
del apps\signal\migrations\00*.py 2>nul
del apps\regime\migrations\00*.py 2>nul
del apps\macro\migrations\00*.py 2>nul
del apps\prompt\migrations\00*.py 2>nul

agomsaaf\Scripts\python manage.py makemigrations
agomsaaf\Scripts\python manage.py migrate
agomsaaf\Scripts\python manage.py init_classification
agomsaaf\Scripts\python manage.py init_rules
agomsaaf\Scripts\python manage.py init_docs
agomsaaf\Scripts\python manage.py init_prompt_templates

echo 重置完成！
pause
```

---

## 附录：命令列表速查

| 命令 | 功能 | 频率 |
|------|------|------|
| `python manage.py migrate` | 数据库迁移 | 安装/更新时 |
| `python manage.py init_classification` | 初始化分类和币种 | 首次安装 |
| `python manage.py init_rules` | 初始化投资规则 | 首次安装 |
| `python manage.py init_docs` | 初始化文档 | 首次安装 |
| `python manage.py init_prompt_templates` | 初始化 AI 模板 | 首次安装 |
| `python manage.py sync_macro_data` | 同步宏观数据 | 每月 |
| `python manage.py createsuperuser` | 创建管理员 | 首次安装 |
| `python manage.py runserver` | 启动开发服务器 | 日常 |
| `python manage.py check` | 系统检查 | 调试时 |

---

## 更多帮助

- Django 管理命令官方文档: https://docs.djangoproject.com/en/5.2/howto/custom-management-commands/
- 项目文档: `docs/` 目录
- API 文档: 访问 `/api/docs/` 查看
