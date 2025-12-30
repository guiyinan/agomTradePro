# AgomSAAF 项目实施任务分解计划

> **版本**: V1.0
> **基于**: AgomSAAF_V3.4.md
> **开发模式**: 本地开发（无 Docker）→ Docker 打包部署

---

## 任务状态图例

| 状态 | 图标 | 说明 |
|------|------|------|
| 待开始 | ⬜ | 尚未开始 |
| 进行中 | 🔄 | 正在实施 |
| 已完成 | ✅ | 已完成 |
| 已阻塞 | ⛔ | 有依赖阻塞 |
| 已跳过 | ⏭️ | 非必需任务 |

---

## Phase 1: 基础搭建 (Week 1-2)

> **开发模式**: 本地开发（venv + SQLite）
> **目标**: 搭建项目骨架，实现基础数据采集能力

### 1.1 项目初始化

#### 1.1.1 Django 项目骨架创建
- [x] ✅ 创建项目目录结构
- [x] ✅ 初始化 Django 项目 (`django-admin startproject core .`)
- [x] ✅ 创建 `core/settings/` 目录
  - [x] ✅ `base.py` - 基础配置
  - [x] ✅ `development.py` - 开发环境配置
  - [x] ✅ `production.py` - 生产环境配置
- [x] ✅ 配置 `core/urls.py` 根路由
- [x] ✅ 配置 `core/celery.py` Celery 初始化

**验收**: `python manage.py runserver` 成功启动 ✅

#### 1.1.2 本地开发环境配置
- [x] ✅ 创建 Python 虚拟环境 (`python -m venv venv`)
- [x] ✅ 创建 `requirements.txt` 依赖文件
- [x] ✅ 创建 `.env.example` 环境变量模板
- [x] ✅ 创建 `.gitignore` 文件
- [x] ✅ 配置 `django-environ` 库读取环境变量

**验收**: `pip install -r requirements.txt` 成功，环境变量正确加载 ✅

#### 1.1.3 代码规范工具配置
- [x] ✅ 配置 `black` (代码格式化)
- [x] ✅ 配置 `isort` (导入排序)
- [x] ✅ 配置 `ruff` (代码检查)
- [x] ✅ 配置 `mypy` (类型检查)
- [x] ✅ 创建 `pyproject.toml` 统一配置

**验收**: `black .`, `mypy apps/ --strict` 正常运行 ✅

### 1.2 Apps 骨架创建

#### 1.2.1 创建 macro App (宏观数据)
- [x] ✅ `python manage.py startapp macro apps/macro`
- [x] ✅ 创建四层目录结构
  - [x] ✅ `domain/` - entities.py, services.py
  - [x] ✅ `application/` - use_cases.py, tasks.py
  - [x] ✅ `infrastructure/` - models.py, repositories.py, adapters/
  - [x] ✅ `interface/` - views.py, serializers.py, admin.py
- [x] ✅ 注册到 `INSTALLED_APPS`

#### 1.2.2 创建 regime App (Regime 判定)
- [x] ✅ `python manage.py startapp regime apps/regime`
- [x] ✅ 创建四层目录结构 (同上)
- [x] ✅ 注册到 `INSTALLED_APPS`

#### 1.2.3 创建 policy App (政策事件)
- [x] ✅ `python manage.py startapp policy apps/policy`
- [x] ✅ 创建四层目录结构 (同上)
- [x] ✅ 注册到 `INSTALLED_APPS`

#### 1.2.4 创建 signal App (投资信号)
- [x] ✅ `python manage.py startapp signal apps/signal`
- [x] ✅ 创建四层目录结构 (同上)
- [x] ✅ 注册到 `INSTALLED_APPS`

#### 1.2.5 创建 backtest App (回测引擎)
- [x] ✅ `python manage.py startapp backtest apps/backtest`
- [x] ✅ 创建四层目录结构 (同上)
- [x] ✅ 注册到 `INSTALLED_APPS`

#### 1.2.6 创建 audit App (事后审计)
- [x] ✅ `python manage.py startapp audit apps/audit`
- [x] ✅ 创建四层目录结构 (同上)
- [x] ✅ 注册到 `INSTALLED_APPS`

### 1.3 Shared 模块创建

#### 1.3.1 共享 Domain 层
- [x] ✅ 创建 `shared/domain/interfaces.py`
  - [x] ✅ 定义 `TrendCalculatorProtocol` (趋势计算协议)
  - [x] ✅ 定义 `RepositoryProtocol` 基类
- [x] ✅ 创建 `shared/domain/value_objects.py`
  - [x] ✅ 定义 `DateRange`, `Percentage`, `ZScore` 值对象

#### 1.3.2 共享 Infrastructure 层
- [x] ✅ 创建 `shared/infrastructure/calculators.py`
  - [x] ✅ 实现 `PandasTrendCalculator` (HP 滤波)
  - [x] ✅ 实现 Z-score 计算
- [x] ✅ 创建 `shared/infrastructure/kalman_filter.py`
  - [x] ✅ 实现 `LocalLinearTrendFilter`
  - [x] ✅ 实现 `KalmanFilterResult`, `KalmanState`

#### 1.3.3 密钥管理模块
- [x] ✅ 创建 `shared/config/secrets.py`
  - [x] ✅ 定义 `DataSourceSecrets` dataclass
  - [x] ✅ 定义 `AppSecrets` dataclass
  - [x] ✅ 实现 `get_secrets()` 函数 (带启动验证)

**验收**: 启动时缺失 TUSHARE_TOKEN 会抛出 EnvironmentError ✅

### 1.4 Domain 层 Entities 定义

#### 1.4.1 macro/domain/entities.py
- [x] ✅ 定义 `MacroIndicator` 值对象
  ```python
  @dataclass(frozen=True)
  class MacroIndicator:
      code: str
      value: float
      observed_at: date
      published_at: Optional[date] = None
      source: str = "unknown"
  ```

#### 1.4.2 regime/domain/entities.py
- [x] ✅ 定义 `RegimeSnapshot` 值对象
- [x] ✅ 定义 `KalmanFilterParams` 值对象
  ```python
  @dataclass(frozen=True)
  class KalmanFilterParams:
      level_variance: float = 0.01
      slope_variance: float = 0.001
      observation_variance: float = 1.0
      ...
  ```
- [x] ✅ 定义 `KalmanState` 值对象

#### 1.4.3 policy/domain/entities.py
- [x] ✅ 定义 `PolicyLevel` 枚举 (P0-P3)
- [x] ✅ 定义 `PolicyEvent` 实体

#### 1.4.4 signal/domain/entities.py
- [x] ✅ 定义 `SignalStatus` 枚举
- [x] ✅ 定义 `Eligibility` 枚举
- [x] ✅ 定义 `InvestmentSignal` 实体
  ```python
  @dataclass
  class InvestmentSignal:
      asset_code: str
      logic_desc: str
      invalidation_logic: str  # 必填
      invalidation_threshold: Optional[float]
      ...
  ```

**验收**: `mypy apps/ --strict` 通过，无任何外部依赖 ✅

### 1.5 Infrastructure 层 ORM Models

#### 1.5.1 macro/infrastructure/models.py
- [x] ✅ 定义 `MacroIndicator` Model
  ```python
  class MacroIndicator(models.Model):
      code = models.CharField(max_length=50)
      value = models.DecimalField(max_digits=20, decimal_places=6)
      observed_at = models.DateField()
      published_at = models.DateField(null=True)
      publication_lag_days = models.IntegerField(default=0)
      source = models.CharField(max_length=20)
      revision_number = models.IntegerField(default=1)
      ...
  ```

#### 1.5.2 其他 App 的 Models
- [x] ✅ regime: `RegimeLog`
- [x] ✅ policy: `PolicyLog`
- [x] ✅ signal: `InvestmentSignal`
- [x] ✅ backtest: `BacktestResult`, `TradeLog`
- [x] ✅ audit: `AuditReport`

**验收**: `python manage.py makemigrations` && `python manage.py migrate` 成功 ✅

### 1.6 数据源适配器开发

#### 1.6.1 Tushare Adapter
- [x] ✅ 创建 `apps/macro/infrastructure/adapters/tushare_adapter.py`
- [x] ✅ 实现 `TushareAdapter` 类
  - [x] ✅ `fetch_shibor()` - 获取 SHIBOR 利率
  - [x] ✅ `fetch_index_daily()` - 获取指数日线
- [x] ✅ 使用 `get_secrets()` 获取 token

#### 1.6.2 AKShare Adapter
- [x] ✅ 创建 `apps/macro/infrastructure/adapters/akshare_adapter.py`
- [x] ✅ 实现 `AKShareAdapter` 类
  - [x] ✅ `fetch_china_pmi()` - 获取 PMI
  - [x] ✅ `fetch_china_cpi()` - 获取 CPI
  - [x] ✅ `fetch_china_money_supply()` - 获取 M2
  - [x] ✅ 配置 `PUBLICATION_LAGS` 字典

#### 1.6.3 Failover Adapter
- [x] ✅ 创建 `apps/macro/infrastructure/adapters/base.py`
  - [x] ✅ 定义 `MacroAdapterProtocol`
  - [x] ✅ 定义 `DataSourceUnavailableError`
- [x] ✅ 实现 `FailoverAdapter` 类
  - [x] ✅ 按优先级尝试多个数据源
  - [x] ✅ 记录失败日志

**验收**: 单元测试通过，可获取真实数据 ✅

### 1.7 测试框架搭建

#### 1.7.1 测试目录结构
- [x] ✅ 创建 `tests/unit/domain/` - Domain 层单元测试
- [ ] ⬜ 创建 `tests/unit/application/` - Application 层单元测试
- [ ] ⬜ 创建 `tests/integration/` - 集成测试
- [ ] ⬜ 创建 `tests/fixtures/` - 测试数据

#### 1.7.2 pytest 配置
- [x] ✅ 创建 `pytest.ini` 配置文件
- [x] ✅ 配置 `pytest-cov` 覆盖率检查
- [x] ✅ 创建测试 fixtures (示例数据)

#### 1.7.3 Domain 层单元测试
- [x] ✅ `tests/unit/domain/test_regime_services.py` - 40 个测试，覆盖率 97%
- [x] ✅ `tests/unit/domain/test_signal_rules.py` - 36 个测试，覆盖率 100%
- [x] ✅ `tests/unit/domain/test_macro_entities.py` - 18 个测试，覆盖率 100%

**验收**: `pytest tests/unit/domain/ -v` 通过，88 个测试全部通过，Domain 层覆盖率 ≥ 90% ✅

---

## Phase 2: 核心引擎 (Week 3-4)

> **开发模式**: 本地开发
> **目标**: 实现 Regime 判定、准入规则、Kalman 滤波核心逻辑

### 2.1 趋势滤波器实现

#### 2.1.1 HP 滤波 (回测用)
- [x] ✅ 实现 `PandasTrendCalculator.calculate_hp_trend()`
- [x] ✅ **关键**: 扩张窗口模式
  ```python
  def calculate_trend_at(series, t):
      # 只用 [0, t] 的数据，避免后视偏差
      truncated = series[:t+1]
      trend, _ = hpfilter(truncated, lamb=129600)
      return trend[-1]
  ```

#### 2.1.2 Kalman 滤波 (实时用)
- [x] ✅ 实现 `LocalLinearTrendFilter.filter()`
  - [x] ✅ 预测步骤: `x_pred = F @ x`
  - [x] ✅ 更新步骤: 计算卡尔曼增益 K
  - [x] ✅ 返回 `KalmanFilterResult`
- [x] ✅ 实现 `LocalLinearTrendFilter.update_single()`
  - [x] ✅ 增量更新单个新观测值
  - [x] ✅ 返回新状态 (可持久化)

**验收**: 输入测试序列，输出趋势值合理 ✅

### 2.2 Regime 计算服务

#### 2.2.1 regime/domain/services.py
- [x] ✅ 实现 `RegimeCalculator` 类
  - [x] ✅ `calculate()` - 主计算方法
  - [x] ✅ `_calculate_momentum()` - 动量计算 (3个月变化)
  - [x] ✅ `_to_zscore()` - Z-score 标准化 (60个月窗口)
  - [x] ✅ `_calculate_distribution()` - 模糊权重

#### 2.2.2 模糊权重计算
- [x] ✅ 实现 `calculate_regime_distribution()`
  ```python
  def sigmoid(x, k=2):
      return 1 / (1 + exp(-k * x))

  p_growth_up = sigmoid(growth_z)
  p_inflation_up = sigmoid(inflation_z)

  return {
      "Recovery": p_growth_up * (1 - p_inflation_up),
      "Overheat": p_growth_up * p_inflation_up,
      "Stagflation": (1 - p_growth_up) * p_inflation_up,
      "Deflation": (1 - p_growth_up) * (1 - p_inflation_up),
  }
  ```

**验收**: 输入增长/通胀动量，输出四象限概率和为 1 ✅

### 2.3 准入规则引擎

#### 2.3.1 signal/domain/rules.py
- [x] ✅ 定义 `ELIGIBILITY_MATRIX` 配置
  ```python
  ELIGIBILITY_MATRIX: Dict[str, Dict[str, Eligibility]] = {
      "a_share_growth": {
          "Recovery": Eligibility.PREFERRED,
          "Overheat": Eligibility.NEUTRAL,
          "Stagflation": Eligibility.HOSTILE,
          "Deflation": Eligibility.NEUTRAL,
      },
      ...
  }
  ```

- [x] ✅ 实现 `check_eligibility()` 函数
- [x] ✅ 实现 `should_reject_signal()` 函数
- [x] ✅ 实现 `validate_invalidation_logic()` 函数
  - [x] ✅ 检查证伪逻辑长度 ≥ 10 字符
  - [x] ✅ 检查包含可量化关键词 ("跌破", "突破", "<", ">" 等)

**验收**: Domain 层单元测试覆盖率 ≥ 90% ✅

### 2.4 Repositories 实现

#### 2.4.1 MacroRepository
- [x] ✅ 创建 `apps/macro/infrastructure/repositories.py`
- [x] ✅ 实现 `DjangoMacroRepository`
  - [x] ✅ `get_growth_series()` - 获取增长指标序列
  - [x] ✅ `get_inflation_series()` - 获取通胀指标序列
  - [x] ✅ `save_indicator()` - 保存单个指标
  - [x] ✅ `get_by_code_and_date()` - 按代码和日期查询

#### 2.4.2 其他 Repositories
- [x] ✅ regime: `RegimeRepository`
- [x] ✅ policy: `PolicyRepository`
- [x] ✅ signal: `SignalRepository`

**验收**: 可从数据库存取数据 ✅

### 2.5 Application 层 Use Cases

#### 2.5.1 SyncMacroDataUseCase
- [x] ✅ 创建 `apps/macro/application/use_cases.py`
- [x] ✅ 实现 `SyncMacroDataUseCase`
  - [x] ✅ 调用适配器获取数据
  - [x] ✅ 去重处理 (检查 observed_at + source)
  - [x] ✅ 批量保存到数据库

#### 2.5.2 CalculateRegimeUseCase
- [x] ✅ 实现 `CalculateRegimeUseCase`
  - [x] ✅ 输入: `as_of_date`, `use_pit`
  - [x] ✅ 调用 `MacroRepository` 获取数据
  - [x] ✅ 调用 `RegimeCalculator` 计算
  - [x] ✅ 输出: `RegimeSnapshot` + warnings

#### 2.5.3 ValidateSignalUseCase
- [x] ✅ 实现 `ValidateSignalUseCase`
  - [x] ✅ 检查证伪逻辑完整性
  - [x] ✅ 调用准入规则检查
  - [x] ✅ 生成 `RejectionRecord` (如被拦截)

**验收**: Use Case 测试通过，可手动调用完成工作流 ✅

### 2.6 Celery 任务 (可选)

#### 2.6.1 定时数据同步
- [ ] ⬜ 创建 `apps/macro/application/tasks.py`
- [ ] ⬜ 实现 `@shared_task sync_macro_data()`
  - [ ] ⬜ 配置重试策略 (max_retries=3, delay=300s)
  - [ ] ⬜ 捕获异常并发送告警

**验收**: 手动触发 `sync_macro_data.delay()` 成功执行

---

## Phase 3: 回测验证 (Week 5-6)

> **开发模式**: 本地开发
> **目标**: 实现回测框架，验证 Regime 判定有效性

### 3.1 历史数据导入

#### 3.1.1 数据导入脚本
- [x] ✅ 创建 `scripts/seed_historical.py`
- [x] ✅ 实现 PMI 历史数据导入 (2015-2024)
- [x] ✅ 实现 CPI 历史数据导入
- [x] ✅ 实现 M2 历史数据导入
- [x] ✅ 实现 PPI 历史数据导入
- [ ] ⬜ 实现指数行情数据导入

**验收**: 数据库有历史数据 ✅
- 支持 `--all` 导入所有指标
- 支持 `--indicator` 单独导入
- 支持 `--check` 检查数据库状态
- 支持 `--list` 列出可用指标

### 3.2 回测引擎核心

#### 3.2.1 backtest/domain/services.py
- [x] ✅ 定义 `BacktestConfig` 配置类
- [x] ✅ 定义 `BacktestResult` 结果类
- [x] ✅ 定义 `PortfolioState` 组合状态
- [x] ✅ 定义 `Trade` 交易记录
- [x] ✅ 定义 `RebalanceFrequency` 枚举
- [x] ✅ 实现 `BacktestEngine` 类
  - [x] ✅ `run()` - 主回测方法
  - [x] ✅ `_rebalance()` - 再平衡逻辑
  - [x] ✅ `_calculate_target_weights()` - 应用准入规则
  - [x] ✅ `_calculate_transaction_cost()` - 计算交易成本
  - [x] ✅ `_calculate_sharpe_ratio()` - 计算夏普比率
  - [x] ✅ `_calculate_max_drawdown()` - 计算最大回撤

#### 3.2.2 Point-in-Time 处理
- [x] ✅ 实现 `PITDataProcessor`
  - [x] ✅ 根据 `publication_lags` 调整可用日期
  - [x] ✅ `is_data_available()` - 检查数据是否可用

**验收**: Domain 层纯实现，已完成核心逻辑 ✅

### 3.3 归因分析

#### 3.3.1 audit/domain/services.py
- [x] ✅ 定义 `AttributionResult` 类
  ```python
  @dataclass
  class AttributionResult:
      total_return: float
      regime_timing_pnl: float  # 择时收益
      asset_selection_pnl: float  # 选资产收益
      interaction_pnl: float
      transaction_cost_pnl: float
      loss_source: LossSource
      lesson_learned: str
  ```

- [x] ✅ 定义 `LossSource` 枚举
- [x] ✅ 定义 `RegimePeriod` 和 `PeriodPerformance`
- [x] ✅ 定义 `AttributionAnalyzer` 类
- [x] ✅ 实现 `analyze_attribution()` 函数
  - [x] ✅ 判断: Regime 预测正确/错误
  - [x] ✅ 拆解: 择时 vs 选资产贡献
  - [x] ✅ 计算: 假设收益 (如果判断正确)
  - [x] ✅ 生成: 经验总结和改进建议

#### 3.3.2 回测脚本
- [x] ✅ 创建 `scripts/run_backtest.py`
  - [x] ✅ 支持配置日期、频率、初始资金
  - [x] ✅ 支持启用/禁用 Point-in-Time 数据
  - [x] ✅ 自动运行归因分析

**验收**: 可生成归因分析报告 ✅

### 3.4 回测验证任务

#### 3.4.1 Regime 准确率验证
- [x] ✅ 创建 `RegimeAccuracyValidator` 类
- [x] ✅ 计算 Regime 判定历史准确率
- [x] ✅ 生成 Regime 转换时点图
- [x] ✅ 计算 Regime 分布统计

#### 3.4.2 策略有效性验证
- [x] ✅ 创建 `StrategyValidator` 类
- [x] ✅ 对比: 有准入过滤 vs 无过滤
- [x] ✅ 计算夏普比率、最大回撤
- [x] ✅ 生成 HTML 回测报告

**验收**: 生成准确率报告 + 回测报告 ✅
- `scripts/validate_backtest.py --compare` 运行策略对比
- `scripts/validate_backtest.py --report backtest_report.html` 生成 HTML 报告

---

## Phase 4: 产品化与部署 (Week 7-8)

> **开发模式**: Docker 打包部署
> **目标**: 实现产品化功能，部署到生产环境

### 4.1 Admin 后台

#### 4.1.1 macro/interface/admin.py
- [x] ✅ 注册 `MacroIndicatorAdmin`
  - [x] ✅ 列表显示: code, value, observed_at, source
  - [x] ✅ 搜索字段: code, observed_at
  - [x] ✅ 日期过滤: observed_at 范围

#### 4.1.2 policy/interface/admin.py
- [x] ✅ 注册 `PolicyLogAdmin`
  - [x] ✅ 手动标注 P0-P3 档位
  - [x] ✅ 关联证据 URL 输入
  - [x] ✅ P2/P3 自动告警标记

#### 4.1.3 signal/interface/admin.py
- [x] ✅ 注册 `InvestmentSignalAdmin`
  - [x] ✅ 信号录入表单
  - [x] ✅ 证伪逻辑必填验证
  - [x] ✅ 自动准入检查按钮
  - [x] ✅ 拒绝原因显示

**验收**: 可通过 Admin 完成完整工作流 ✅

### 4.2 DRF API 接口

#### 4.2.1 regime/interface/api_views.py
- [x] ✅ 实现 `RegimeViewSet` (历史查询)
- [x] ✅ 实现 `RegimeViewSet.current` (当前状态)
- [x] ✅ 实现 `RegimeViewSet.calculate` (手动触发计算)
- [x] ✅ 实现 `RegimeHealthView` (健康检查)

#### 4.2.2 signal/interface/api_views.py
- [x] ✅ 实现 `SignalViewSet` (创建信号)
- [x] ✅ 实现 `SignalViewSet.list` (信号列表)
- [x] ✅ 实现 `SignalViewSet.validate` (验证准入)
- [x] ✅ 实现 `SignalHealthView` (健康检查)

#### 4.2.3 OpenAPI 文档
- [x] ✅ 配置 drf-spectacular
- [x] ✅ 生成 API 文档
- [x] ✅ 配置 Swagger UI

**验收**: API 可通过 Swagger 测试 ✅

### 4.3 Docker 部署

#### 4.3.1 Dockerfile
- [x] ✅ 创建 `Dockerfile`
  ```dockerfile
  FROM python:3.11-slim
  WORKDIR /app
  RUN apt-get update && apt-get install -y gcc
  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt
  COPY . .
  RUN python manage.py collectstatic --noinput
  EXPOSE 8000
  CMD ["gunicorn", "core.wsgi:application", "--bind", "0.0.0.0:8000"]
  ```

#### 4.3.2 docker-compose.yml
- [x] ✅ 创建 `docker-compose.yml`
  - [x] ✅ web 服务 (Django)
  - [x] ✅ redis 服务
  - [x] ✅ celery 服务
  - [x] ✅ celery-beat 服务
  - [x] ✅ 数据卷配置

#### 4.3.3 生产环境配置
- [x] ✅ 创建 `core/settings/production.py`
  - [x] ✅ `DEBUG=False`
  - [x] ✅ `ALLOWED_HOSTS` 配置
  - [x] ✅ HTTPS/SSL 配置 (可选)

**验收**: `docker-compose up` 一键启动 ✅

### 4.4 Celery 定时任务

#### 4.4.1 Celery Beat 配置
- [x] ✅ 配置 `celery beat` 调度器
- [x] ✅ 创建 `apps/macro/application/tasks.py`
- [x] ✅ 定义定时任务
  - [x] ✅ 每日 00:00 同步宏观数据
  - [x] ✅ 每日 00:30 计算 Regime
  - [x] ✅ 每 6 小时检查数据新鲜度
- [x] ✅ 创建 `scripts/setup_celery_beat.py` 自动配置脚本

**验收**: 定时任务稳定运行 ✅

### 4.5 告警系统

#### 4.5.1 告警服务
- [x] ✅ 创建 `shared/infrastructure/alerts.py`
- [x] ✅ 实现 `AlertService`
  - [x] ✅ `EmailAlertChannel` - 邮件告警
  - [x] ✅ `SlackAlertChannel` - Slack 告警
  - [x] ✅ `DingTalkAlertChannel` - 钉钉告警
  - [x] ✅ `WeChatWorkAlertChannel` - 企业微信告警

#### 4.5.2 告警触发
- [x] ✅ P2 状态触发告警
- [x] ✅ P3 状态触发紧急告警
- [x] ✅ 数据源失败触发告警

**验收**: 告警正常发送 ✅

---

## Phase 5: 持续迭代 (Week 9+)

### 5.1 数据库升级 暂时略过)

- [ ] ⬜ 评估 SQLite → PostgreSQL 迁移时机
- [ ] ⬜ 创建迁移脚本
  - [ ] ⬜ 导出 SQLite 数据
  - [ ] ⬜ 导入 PostgreSQL
- [ ] ⬜ 更新 docker-compose.prod.yml

**触发条件**: 并发请求 > 10 或 数据量 > 100万条

### 5.2 功能扩展

#### 5.2.1 全球市场数据
- [ ] ⬜ 接入 FRED 美国数据
- [ ] ⬜ 接入其他市场 (欧洲、日本)
- [ ] ⬜ 多市场 Regime 判定

#### 5.2.2 前端可视化
- [ ] ⬜ Regime 象限图可视化
- [ ] ⬜ 历史回测曲线图
- [ ] ⬜ 实时信号监控面板

#### 5.2.3 LLM 辅助分析
- [ ] ⬜ 投资逻辑自动审查
- [ ] ⬜ 证伪条件建议
- [ ] ⬜ 归因分析报告生成

---

## 任务依赖关系图

```
Phase 1: 基础搭建
├── 1.1 项目初始化 → 1.2 Apps 骨架
├── 1.3 Shared 模块 → 1.4 Domain Entities
├── 1.4 Domain Entities → 1.5 ORM Models
├── 1.5 ORM Models → 1.6 数据源适配器
└── 1.7 测试框架 (并行)

Phase 2: 核心引擎
├── 2.1 趋势滤波器 → 2.2 Regime 计算
├── 2.2 Regime 计算 → 2.3 准入规则
├── 2.3 准入规则 → 2.4 Repositories
└── 2.4 Repositories → 2.5 Use Cases

Phase 3: 回测验证
├── 3.1 历史数据导入 → 3.2 回测引擎
└── 3.2 回测引擎 → 3.3 归因分析

Phase 4: 产品化与部署
├── 4.1 Admin 后台 (并行)
├── 4.2 DRF API (并行)
├── 4.3 Docker 部署 → 4.4 Celery 任务
└── 4.5 告警系统 (并行)

Phase 5: 持续迭代
└── 基于 Phase 1-4 完成
```

---

## 验收标准总览

| Phase | 关键验收指标 |
|-------|-------------|
| Phase 1 | `python manage.py runserver` 成功，可获取 Tushare/AKShare 数据 |
| Phase 2 | Regime 计算测试通过，准入规则测试覆盖率 ≥ 90% |
| Phase 3 | 回测可跑通 2015-2024，生成准确率报告 |
| Phase 4 | `docker-compose up` 一键启动，API + Admin 可用 |
| Phase 5 | PostgreSQL 迁移成功，新功能上线 |

---

## 风险检查点

| 风险 | 检查点 | 缓解措施 |
|------|--------|----------|
| HP 滤波后视偏差 | Phase 2 代码审查 | 强制扩张窗口，单元测试验证 |
| Token 泄露 | Phase 1 提交前检查 | `.gitignore` 审查，secrets.py 验证 |
| Domain 层污染 | 每个 Phase 结束 | `mypy --strict` 检查，禁用外部导入 |
| 数据源不稳定 | Phase 3 回测前 | Failover 测试，备用数据源验证 |
| 前视偏差 | Phase 3 回测设计 | PIT 处理审查，保守解读结果 |

---

**维护**: 本文档随项目进展动态更新
**更新**: 每完成一个 Phase 的所有任务，更新状态为 ✅
