# AgomSAAF + Qlib 松耦合深度集成实施方案（v1.1）

> **版本**: 1.1（基于 ADR/TDD/Tickets 架构）
> **预计工期**: 10 周
> **核心原则**: Qlib 是研究/离线引擎；AgomSAAF 是生产编排/治理系统

---

## 一、架构决策记录 (ADR) - 硬性约束

### ADR-001: Qlib 仅作为研究/推理引擎，不进入主业务执行路径
- **状态**: Accepted
- **决策**: Qlib 不直接参与主系统同步调用，所有 Qlib 能力通过异步任务 + 结果物化（DB/Artifact）提供
- **后果**: 主系统稳定性极高，Alpha 信号存在"准实时"而非实时

### ADR-002: 训练与推理解耦（Hard Rule）
- **状态**: Accepted
- **决策**:
  - `fit()` 只允许在离线训练任务中出现
  - Provider/Service 层禁止触发训练
  - 所有模型必须通过 `QlibModelRegistry` 激活

### ADR-003: Qlib 强制进程与队列隔离
- **状态**: Accepted
- **决策**:
  - 独立 Celery 队列：`qlib_train`, `qlib_infer`
  - 独立 worker pool（`--max-tasks-per-child`）

### ADR-004: Alpha 层不做宏观门控
- **状态**: Accepted
- **决策**: AlphaProvider 只产出信号，Regime/Policy/Hedge 决策只在策略层

### ADR-005: 时间对齐与 PIT 显式暴露
- **状态**: Accepted
- **决策**: 所有 Alpha 输出必须携带 `asof_date` + `intended_trade_date`，不允许"最近可用日"静默替换

---

## 二、系统架构概览

```
AgomSAAF 主系统（稳定/治理/风控）        Qlib 子系统（离线/可降级）
┌──────────────────────────────┐       ┌──────────────────────────────┐
│ Regime / Rotation / Hedge     │       │ qlib_train_worker (queue)    │
│ Signal / Backtest / SimTrade  │       │  - train jobs                │
│                              │       │  - eval jobs                 │
│   AlphaService (Orchestrator) │  RPC  │                              │
│   - 读缓存/选provider/降级     ├──────▶│ qlib_infer_worker (queue)    │
│   - 不直接import qlib          │       │  - predict jobs              │
│   - 不同步等待训练             │       │  - batch score materialize   │
│                              │       └───────────┬──────────────────┘
│ PostgreSQL: AlphaScoreCache   │◀──────────────────┘
│ PostgreSQL: QlibModelRegistry │
└──────────────────────────────┘
```

---

## 三、目录结构设计

```
apps/
├── alpha/                              # 新建：Alpha 抽象层
│   ├── domain/
│   │   ├── interfaces.py               # AlphaProvider Protocol
│   │   └── entities.py                 # StockScore, AlphaResult（含审计字段）
│   ├── infrastructure/
│   │   ├── models.py                   # AlphaScoreCache, QlibModelRegistry
│   │   └── adapters/
│   │       ├── __init__.py
│   │       ├── base.py                 # BaseAlphaProvider, @qlib_safe 装饰器
│   │       ├── qlib_adapter.py         # QlibAlphaProvider（仅 load+predict）
│   │       ├── simple_adapter.py       # SimpleAlphaProvider（PE/PB/ROE）
│   │       ├── cache_adapter.py        # CacheAlphaProvider（历史缓存）
│   │       └── etf_adapter.py          # ETFFallbackProvider（最后防线）
│   ├── application/
│   │   ├── __init__.py
│   │   ├── services.py                 # AlphaService（单例，Provider 注册中心）
│   │   └── tasks.py                    # Celery 任务
│   ├── interface/
│   │   ├── views.py                    # DRF API 视图
│   │   ├── serializers.py
│   │   └── urls.py
│   └── management/commands/
│       ├── init_qlib_data.py           # 初始化 Qlib 数据
│       └── train_qlib_model.py         # 训练命令

sdk/agomsaaf_mcp/tools/
└── alpha_tools.py                      # MCP 工具

models/qlib/                            # Qlib 模型存储（不可变 artifact）
└── {model_name}/
    └── {artifact_hash}/
        ├── model.pkl
        ├── config.json
        ├── metrics.json
        ├── feature_schema.json
        └── data_version.txt
```

---

## 四、核心数据契约

### 4.1 StockScore（生产化字段集）

```python
# apps/alpha/domain/entities.py

from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional

@dataclass(frozen=True)
class StockScore:
    """股票评分（含审计字段）"""
    code: str
    score: float
    rank: int
    factors: Dict[str, float]
    source: str                # qlib/cache/simple/etf
    confidence: float          # 0-1

    # 生产化字段（审计/复现/排障）
    model_id: Optional[str] = None
    model_artifact_hash: Optional[str] = None
    asof_date: Optional[date] = None           # 信号真实日期
    intended_trade_date: Optional[date] = None # 请求执行日期
    universe_id: Optional[str] = None
    feature_set_id: Optional[str] = None
    label_id: Optional[str] = None
    data_version: Optional[str] = None
```

### 4.2 AlphaResult

```python
@dataclass
class AlphaResult:
    """Alpha 计算结果"""
    success: bool
    scores: list[StockScore]
    source: str
    timestamp: str
    error_message: Optional[str] = None

    # 治理/监控字段
    status: str = "available"        # available/degraded/unavailable
    latency_ms: Optional[int] = None
    staleness_days: Optional[int] = None
```

### 4.3 AlphaProviderStatus

```python
from enum import Enum

class AlphaProviderStatus(Enum):
    """Alpha 提供者状态"""
    AVAILABLE = "available"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
```

---

## 五、关键文件实现规范

### 5.1 Domain 层接口（apps/alpha/domain/interfaces.py）

```python
from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List

class AlphaProvider(ABC):
    """Alpha 提供者抽象接口"""

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def priority(self) -> int:
        pass

    @property
    def max_staleness_days(self) -> int:
        return 2

    @property
    def max_latency_ms(self) -> int:
        return 1500

    @abstractmethod
    def health_check(self) -> AlphaProviderStatus:
        pass

    @abstractmethod
    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
    ) -> AlphaResult:
        pass

    @abstractmethod
    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: date
    ) -> Dict[str, float]:
        pass
```

### 5.2 Infrastructure 层基类（apps/alpha/infrastructure/adapters/base.py）

```python
import logging
from functools import wraps
from typing import Optional, Any, Callable
import traceback

logger = logging.getLogger(__name__)

def qlib_safe(default_return: Any = None):
    """Qlib 安全装饰器 - 捕获所有异常"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ImportError as e:
                logger.error(f"Qlib 未安装: {e}")
                return default_return
            except Exception as e:
                logger.error(f"Qlib 调用失败: {e}\n{traceback.format_exc()}")
                return default_return
        return wrapper
    return decorator


class BaseAlphaProvider(AlphaProvider):
    """Alpha 提供者基类"""

    def __init__(self):
        self._initialized = False

    def supports(self, universe_id: str) -> bool:
        """检查是否支持指定 universe"""
        return True
```

### 5.3 QlibAlphaProvider（关键：仅 load+predict）

```python
# apps/alpha/infrastructure/adapters/qlib_adapter.py

from datetime import date
from pathlib import Path

class QlibAlphaProvider(BaseAlphaProvider):
    """Qlib Alpha 提供者 - 仅做推理，不触发训练"""

    def __init__(self, provider_uri: str = "~/.qlib/qlib_data/cn_data"):
        super().__init__()
        self._data_path = provider_uri
        self._model = None
        self._dataset = None
        self._qlib_initialized = False

    @property
    def name(self) -> str:
        return "qlib"

    @property
    def priority(self) -> int:
        return 1  # 最高优先级

    @qlib_safe(default_return=AlphaProviderStatus.UNAVAILABLE)
    def health_check(self) -> AlphaProviderStatus:
        """健康检查"""
        data_path = Path(self._data_path).expanduser()
        if not data_path.exists():
            return AlphaProviderStatus.UNAVAILABLE

        # 检查是否有激活的模型
        from apps.alpha.infrastructure.models import QlibModelRegistry
        active_model = QlibModelRegistry.objects.filter(
            is_active=True
        ).first()
        if not active_model:
            return AlphaProviderStatus.UNAVAILABLE

        return AlphaProviderStatus.AVAILABLE

    def get_stock_scores(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
    ) -> AlphaResult:
        """
        获取股票评分 - 快路径：优先读缓存
        """
        import time
        start_time = time.time()

        # 1. 快路径：读缓存
        cached = self._get_from_cache(universe_id, intended_trade_date)
        if cached:
            latency_ms = int((time.time() - start_time) * 1000)
            cached.latency_ms = latency_ms
            cached.staleness_days = 0
            return cached

        # 2. 慢路径：触发异步任务
        self._trigger_infer_task(universe_id, intended_trade_date)

        # 3. 立即返回 degraded，让 registry 去走下一个 provider
        return AlphaResult(
            success=False,
            scores=[],
            source="qlib",
            timestamp=intended_trade_date.isoformat(),
            status="degraded",
            error_message="缓存缺失，已触发异步补齐"
        )

    def _get_from_cache(
        self,
        universe_id: str,
        intended_trade_date: date
    ) -> Optional[AlphaResult]:
        """从缓存获取"""
        from apps.alpha.infrastructure.models import AlphaScoreCache

        try:
            cache = AlphaScoreCache.objects.filter(
                universe_id=universe_id,
                intended_trade_date=intended_trade_date,
                provider_source="qlib"
            ).order_by('-created_at').first()

            if not cache:
                return None

            # 检查 staleness
            staleness = (date.today() - cache.asof_date).days
            if staleness > self.max_staleness_days:
                logger.warning(f"Qlib 缓存过期: {staleness} 天")

            # 解析 scores
            scores = [
                StockScore(
                    code=s['code'],
                    score=s['score'],
                    rank=s['rank'],
                    factors=s.get('factors', {}),
                    source="qlib",
                    confidence=s.get('confidence', 0.8),
                    model_id=cache.model_id,
                    model_artifact_hash=cache.model_artifact_hash,
                    asof_date=cache.asof_date,
                    intended_trade_date=cache.intended_trade_date,
                    universe_id=cache.universe_id,
                    feature_set_id=cache.feature_set_id,
                    label_id=cache.label_id,
                    data_version=cache.data_version,
                )
                for s in cache.scores[:30]
            ]

            return AlphaResult(
                success=True,
                scores=scores,
                source="qlib",
                timestamp=cache.created_at.isoformat(),
                status="degraded" if staleness > self.max_staleness_days else "available",
                staleness_days=staleness,
            )
        except Exception as e:
            logger.error(f"读取 Qlib 缓存失败: {e}")
            return None

    def _trigger_infer_task(self, universe_id: str, intended_trade_date: date):
        """触发推理任务"""
        from apps.alpha.application.tasks import qlib_predict_scores

        # 异步投递任务，不等待结果
        qlib_predict_scores.apply_async(
            args=[universe_id, intended_trade_date.isoformat()],
            queue='qlib_infer'
        )

    def get_factor_exposure(self, stock_code: str, trade_date: date) -> Dict[str, float]:
        """获取因子暴露（带异常保护）"""
        try:
            # 实现因子暴露查询
            return {}
        except:
            return {}
```

---

## 六、数据库模型设计

### 6.1 AlphaScoreCache（升级版）

```python
# apps/alpha/infrastructure/models.py

from django.db import models

class AlphaScoreCache(models.Model):
    """Alpha 评分缓存（支持审计、版本、staleness）"""

    PROVIDER_CHOICES = [
        ('qlib', 'Qlib'),
        ('simple', 'Simple'),
        ('etf', 'ETF Fallback'),
    ]

    # 主键信息
    universe_id = models.CharField(max_length=50, db_index=True)
    intended_trade_date = models.DateField(db_index=True)
    provider_source = models.CharField(max_length=20, choices=PROVIDER_CHOICES)

    # 时间对齐字段（审计必需）
    asof_date = models.DateField(db_index=True, help_text="信号真实日期")

    # 模型版本信息（可追溯）
    model_id = models.CharField(max_length=200, null=True, blank=True)
    model_artifact_hash = models.CharField(max_length=64, null=True, blank=True)
    feature_set_id = models.CharField(max_length=50, null=True, blank=True)
    label_id = models.CharField(max_length=50, null=True, blank=True)
    data_version = models.CharField(max_length=50, null=True, blank=True)

    # 评分结果
    scores = models.JSONField(help_text="[{code, score, rank, factors, confidence}, ...]")

    # 质量指标
    status = models.CharField(max_length=20, default='available')
    metrics_snapshot = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # 唯一键：支持多模型同日共存
        unique_together = [
            ['universe_id', 'intended_trade_date', 'provider_source', 'model_artifact_hash']
        ]
        db_table = 'alpha_score_cache'
        ordering = ['-intended_trade_date', '-created_at']

    def __str__(self):
        return f"{self.universe_id}@{self.intended_trade_date} ({self.provider_source})"


class QlibModelRegistry(models.Model):
    """Qlib 模型注册表"""

    MODEL_TYPE_CHOICES = [
        ('LGBModel', 'LightGBM'),
        ('LSTMModel', 'LSTM'),
        ('TransformerModel', 'Transformer'),
    ]

    # 模型标识
    model_name = models.CharField(max_length=100, db_index=True)
    artifact_hash = models.CharField(max_length=64, unique=True, primary_key=True)

    # 训练配置
    model_type = models.CharField(max_length=30, choices=MODEL_TYPE_CHOICES)
    universe = models.CharField(max_length=20)
    train_config = models.JSONField()

    # 特征和标签
    feature_set_id = models.CharField(max_length=50)
    label_id = models.CharField(max_length=50)
    data_version = models.CharField(max_length=50)

    # 评估指标
    ic = models.DecimalField(max_digits=10, decimal_places=6, null=True)
    icir = models.DecimalField(max_digits=10, decimal_places=6, null=True)
    rank_ic = models.DecimalField(max_digits=10, decimal_places=6, null=True)

    # 模型存储
    model_path = models.CharField(max_length=500)

    # 状态
    is_active = models.BooleanField(default=False, db_index=True)

    # 审计
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = 'qlib_model_registry'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.model_name}@{self.artifact_hash[:8]} (active={self.is_active})"
```

---

## 七、Celery 任务设计

### 7.1 队列配置

```python
# core/settings/base.py 新增

# Celery 队列配置
CELERY_TASK_ROUTES = {
    'apps.alpha.application.tasks.qlib_train_model': {'queue': 'qlib_train'},
    'apps.alpha.application.tasks.qlib_predict_scores': {'queue': 'qlib_infer'},
    'apps.alpha.application.tasks.qlib_evaluate_model': {'queue': 'qlib_train'},
}

# Qlib 任务超时配置
CELERY_TASK_TIME_LIMIT = 3600  # 1小时
CELERY_TASK_SOFT_TIME_LIMIT = 3300  # 55分钟
```

### 7.2 推理任务（apps/alpha/application/tasks.py）

```python
from celery import shared_task
from datetime import date
import logging

logger = logging.getLogger(__name__)

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
)
def qlib_predict_scores(
    self,
    universe_id: str,
    intended_trade_date: str,
) -> dict:
    """
    Qlib 推理任务（运行在 qlib_infer 队列）

    1. 加载激活的模型
    2. 执行预测
    3. 结果写入 AlphaScoreCache
    """
    try:
        from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
        from apps.alpha.infrastructure.models import AlphaScoreCache, QlibModelRegistry

        provider = QlibAlphaProvider()
        trade_date = date.fromisoformat(intended_trade_date)

        # 获取激活的模型
        active_model = QlibModelRegistry.objects.filter(is_active=True).first()
        if not active_model:
            raise Exception("没有激活的 Qlib 模型")

        # 执行预测（此处省略具体实现）
        # ...

        # 写入缓存
        AlphaScoreCache.objects.update_or_create(
            universe_id=universe_id,
            intended_trade_date=trade_date,
            provider_source="qlib",
            model_artifact_hash=active_model.artifact_hash,
            defaults={
                'asof_date': trade_date,
                'model_id': active_model.model_name,
                'model_artifact_hash': active_model.artifact_hash,
                'feature_set_id': active_model.feature_set_id,
                'label_id': active_model.label_id,
                'data_version': active_model.data_version,
                'scores': [...],
                'status': 'available',
            }
        )

        return {'status': 'success', 'universe_id': universe_id, 'trade_date': intended_trade_date}

    except Exception as exc:
        logger.error(f"Qlib 推理失败: {exc}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=1)
def qlib_train_model(
    self,
    model_name: str,
    train_config: dict,
) -> dict:
    """
    Qlib 训练任务（运行在 qlib_train 队列）

    1. 准备数据
    2. 训练模型
    3. 评估指标
    4. 保存 artifact
    5. 写入 Registry
    """
    # 实现训练流程
    pass
```

---

## 八、AlphaService（Provider 注册中心）

```python
# apps/alpha/application/services.py

from datetime import date
from typing import List
import logging

logger = logging.getLogger(__name__)

class AlphaProviderRegistry:
    """Provider 注册中心 - 管理降级链路"""

    def __init__(self):
        self._providers: List[AlphaProvider] = []

    def register(self, provider: AlphaProvider):
        self._providers.append(provider)
        # 按 priority 排序
        self._providers.sort(key=lambda p: p.priority)

    def get_scores_with_fallback(
        self,
        universe_id: str,
        intended_trade_date: date,
        top_n: int = 30
    ) -> AlphaResult:
        """
        带降级的评分获取

        降级顺序：Qlib → Cache → Simple → ETF
        """
        for provider in self._providers:
            try:
                status = provider.health_check()
                if status == AlphaProviderStatus.UNAVAILABLE:
                    logger.debug(f"Provider {provider.name} 不可用，跳过")
                    continue

                result = provider.get_stock_scores(universe_id, intended_trade_date, top_n)

                if result.success:
                    # 检查 staleness
                    if result.staleness_days and result.staleness_days > provider.max_staleness_days:
                        logger.warning(f"Provider {provider.name} 数据过期: {result.staleness_days} 天")
                        # 标记 degraded，但继续尝试下一个
                        result.status = "degraded"
                        # 如果这是最后一个 provider，返回 degraded 结果
                        if provider == self._providers[-1]:
                            return result
                        continue

                    return result

            except Exception as e:
                logger.error(f"Provider {provider.name} 调用失败: {e}")
                continue

        # 所有 provider 都失败
        return AlphaResult(
            success=False,
            scores=[],
            source="none",
            timestamp=date.today().isoformat(),
            status="unavailable",
            error_message="所有 Alpha 提供者不可用"
        )


class AlphaService:
    """Alpha 服务（单例）"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._registry = AlphaProviderRegistry()
        self._setup_providers()
        self._initialized = True

    def _setup_providers(self):
        """设置 Provider（按优先级）"""
        # 1. Qlib（最优）
        try:
            from apps.alpha.infrastructure.adapters.qlib_adapter import QlibAlphaProvider
            self._registry.register(QlibAlphaProvider())
        except Exception as e:
            logger.warning(f"Qlib Provider 不可用: {e}")

        # 2. Cache（稳定，滞后可接受）
        try:
            from apps.alpha.infrastructure.adapters.cache_adapter import CacheAlphaProvider
            self._registry.register(CacheAlphaProvider())
        except Exception as e:
            logger.warning(f"Cache Provider 不可用: {e}")

        # 3. Simple（外部依赖，风险更高）
        try:
            from apps.alpha.infrastructure.adapters.simple_adapter import SimpleAlphaProvider
            self._registry.register(SimpleAlphaProvider())
        except Exception as e:
            logger.warning(f"Simple Provider 不可用: {e}")

        # 4. ETF（最后防线）
        try:
            from apps.alpha.infrastructure.adapters.etf_adapter import ETFFallbackProvider
            self._registry.register(ETFFallbackProvider())
        except Exception as e:
            logger.warning(f"ETF Provider 不可用: {e}")

    def get_stock_scores(
        self,
        universe_id: str = "csi300",
        intended_trade_date: date = None,
        top_n: int = 30
    ) -> AlphaResult:
        """获取股票评分（带自动降级）"""
        if intended_trade_date is None:
            intended_trade_date = date.today()

        result = self._registry.get_scores_with_fallback(universe_id, intended_trade_date, top_n)
        return result

    def get_provider_status(self) -> dict:
        """获取所有 Provider 状态"""
        return {
            p.name: {
                "priority": p.priority,
                "status": p.health_check().value
            }
            for p in self._registry._providers
        }
```

---

## 九、MCP 工具

```python
# sdk/agomsaaf_mcp/tools/alpha_tools.py

from datetime import date
from typing import Any

from mcp.server import Server
from agomsaaf import AgomSAAFClient


def register_alpha_tools(server: Server) -> None:
    """注册 Alpha 相关的 MCP 工具"""

    @server.tool()
    def get_alpha_stock_scores(
        universe: str = "csi300",
        trade_date: str | None = None,
        top_n: int = 20
    ) -> dict[str, Any]:
        """
        获取 AI 选股评分

        Args:
            universe: 股票池（默认 csi300）
            trade_date: 交易日期（ISO 格式）
            top_n: 返回前 N 只股票

        Returns:
            包含股票评分的字典
        """
        from apps.alpha.application.services import AlphaService

        service = AlphaService()

        parsed_date = None
        if trade_date:
            parsed_date = date.fromisoformat(trade_date)
        else:
            parsed_date = date.today()

        result = service.get_stock_scores(universe, parsed_date, top_n)

        return {
            "success": result.success,
            "source": result.source,
            "status": result.status,
            "staleness_days": result.staleness_days,
            "stocks": [
                {
                    "code": s.code,
                    "score": s.score,
                    "rank": s.rank,
                    "confidence": s.confidence,
                    "asof_date": s.asof_date.isoformat() if s.asof_date else None,
                    "model_id": s.model_id,
                }
                for s in result.scores
            ],
            "error": result.error_message
        }

    @server.tool()
    def get_alpha_provider_status() -> dict[str, Any]:
        """获取 Alpha Provider 状态（诊断用）"""
        from apps.alpha.application.services import AlphaService
        return AlphaService().get_provider_status()
```

---

## 十、配置更新

### 10.1 requirements.txt

```txt
# Qlib 依赖
pyqlib>=0.9.0
lightgbm>=4.0.0
scikit-learn>=1.3.0
```

### 10.2 .env 新增配置

```bash
# Qlib 配置
QLIB_PROVIDER_URI=~/.qlib/qlib_data/cn_data
QLIB_REGION=CN
QLIB_MODEL_PATH=/models/qlib
```

### 10.3 settings.py 更新

```python
# core/settings/base.py

# 新增 alpha app
INSTALLED_APPS = [
    # ... 现有 apps
    'apps.alpha',
]

# Qlib 配置
QLIB_SETTINGS = {
    'provider_uri': env('QLIB_PROVIDER_URI', default='~/.qlib/qlib_data/cn_data'),
    'region': env('QLIB_REGION', default='CN'),
    'model_path': env('QLIB_MODEL_PATH', default='/models/qlib'),
}
```

---

## 十一、实施路线图（10 周）

### Phase 1（Week 1-2）：Alpha 抽象层 + Cache Provider

**目标**: 不依赖 Qlib，系统可完整运行

**任务**:
- [ ] 创建 `apps/alpha` 目录结构
- [ ] 实现 `apps/alpha/domain/interfaces.py` - AlphaProvider Protocol
- [ ] 实现 `apps/alpha/domain/entities.py` - StockScore, AlphaResult（含审计字段）
- [ ] 实现 `apps/alpha/infrastructure/models.py` - AlphaScoreCache, QlibModelRegistry
- [ ] 实现 `apps/alpha/infrastructure/adapters/base.py` - BaseAlphaProvider, @qlib_safe
- [ ] 实现 `CacheAlphaProvider`（优先级 10）
- [ ] 实现 `SimpleAlphaProvider`（PE/PB/ROE 因子，优先级 100）
- [ ] 实现 `ETFFallbackProvider`（优先级 1000）
- [ ] 实现 `AlphaService` 和 `AlphaProviderRegistry`
- [ ] 单元测试：`tests/unit/test_alpha_providers.py`

**验收**: 不装 Qlib，`AlphaService().get_stock_scores("csi300")` 正常返回

---

### Phase 2（Week 3-4）：Qlib 推理异步产出

**目标**: Qlib 推理任务产出结果并落库，主系统只读缓存

**任务**:
- [ ] 实现 `QlibAlphaProvider`（仅 load+predict，快路径读缓存）
- [ ] 实现 `apps/alpha/application/tasks.py` - `qlib_predict_scores`
- [ ] 配置 Celery 队列：`qlib_train`, `qlib_infer`
- [ ] 实现 management 命令：`init_qlib_data.py`
- [ ] 集成测试：手动触发推理任务，验证缓存写入
- [ ] MCP 工具：`alpha_tools.py`

**验收**:
- `get_alpha_stock_scores` 第一次返回 degraded，第二次命中缓存
- `AlphaScoreCache` 表有正确记录

---

### Phase 3（Week 5-6）：训练流水线

**目标**: 离线训练模型，生成不可变 artifact

**任务**:
- [ ] 实现 `apps/alpha/management/commands/train_qlib_model.py`
- [ ] 实现 `qlib_train_model` Celery 任务
- [ ] 实现 artifact 目录规范（`/models/qlib/{name}/{hash}/`）
- [ ] 实现 `QlibModelRegistry` 激活/回滚机制
- [ ] Management 命令：`activate_model`，`rollback_model`
- [ ] 单元测试：`tests/unit/test_qlib_training.py`

**验收**:
- `python manage.py train_qlib_model` 生成 artifact 并写入 Registry
- `python manage.py activate_model <hash>` 激活模型

---

### Phase 4（Week 7-8）：评估闭环 + 监控

**目标**: IC/覆盖/漂移监控，队列积压告警

**任务**:
- [ ] 实现 `qlib_evaluate_model` 任务（IC/ICIR 计算）
- [ ] 监控指标埋点（Prometheus/日志）
  - `alpha_provider_success_rate{provider}`
  - `alpha_latency_ms{provider}`
  - `alpha_staleness_days{provider}`
  - `qlib_infer_queue_lag`
  - `alpha_coverage_ratio`
  - `ic_drift` / `rank_ic_rolling`
- [ ] 告警规则配置
- [ ] 实现滚动 IC 计算

**验收**: Grafana/日志可看到监控指标

---

### Phase 5（Week 9-10）：宏观集成 + 全链路联调

**目标**: 与 Regime/Rotation/Hedge 全链路联调

**任务**:
- [ ] 移除 `AlphaService` 中的 Regime 调权逻辑（迁移到策略层）
- [ ] 实现 `asof_date` / `data_version` 全链路透传
- [ ] 与 `Signal` 模块对接
- [ ] 与 `Backtest` 模块对接
- [ ] 与 `Rotation` 模块对接
- [ ] 集成测试：`tests/integration/test_alpha_full_flow.py`
- [ ] 压力测试：模拟 Qlib 故障
- [ ] 文档更新

**验收**: 端到端测试通过，Qlib 故障时系统自动降级

---

## 十二、关键文件清单

### 需要创建的文件

```
apps/alpha/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── interfaces.py              # AlphaProvider Protocol
│   └── entities.py                # StockScore, AlphaResult
├── infrastructure/
│   ├── __init__.py
│   ├── models.py                  # AlphaScoreCache, QlibModelRegistry
│   └── adapters/
│       ├── __init__.py
│       ├── base.py                # BaseAlphaProvider, @qlib_safe
│       ├── qlib_adapter.py        # QlibAlphaProvider
│       ├── simple_adapter.py      # SimpleAlphaProvider
│       ├── cache_adapter.py       # CacheAlphaProvider
│       └── etf_adapter.py         # ETFFallbackProvider
├── application/
│   ├── __init__.py
│   ├── services.py                # AlphaService, AlphaProviderRegistry
│   └── tasks.py                   # Celery 任务
├── interface/
│   ├── __init__.py
│   ├── views.py                   # DRF API 视图
│   ├── serializers.py
│   └── urls.py
└── management/commands/
    ├── __init__.py
    ├── init_qlib_data.py
    ├── train_qlib_model.py
    ├── activate_model.py
    └── rollback_model.py

sdk/agomsaaf_mcp/tools/
└── alpha_tools.py                  # MCP 工具

tests/unit/
└── test_alpha_providers.py         # 单元测试

tests/integration/
└── test_alpha_full_flow.py        # 集成测试
```

### 需要修改的文件

```
core/settings/base.py               # 新增 alpha app, QLIB_SETTINGS, CELERY_TASK_ROUTES
requirements.txt                    # 新增 pyqlib, lightgbm
.env                                # 新增 QLIB_* 配置
sdk/agomsaaf_mcp/server.py          # 注册 alpha_tools
sdk/agomsaaf/modules/base.py        # 新增 alpha 模块（可选）
```

---

## 十三、验证方法

### 开发环境验证

```bash
# 1. 安装依赖
pip install pyqlib lightgbm

# 2. 数据库迁移
python manage.py makemigrations alpha
python manage.py migrate

# 3. 初始化 Qlib 数据
python manage.py init_qlib_data

# 4. 测试 Cache Provider（无需 Qlib）
python -c "
from apps.alpha.application.services import AlphaService
result = AlphaService().get_stock_scores('csi300')
print(f'Source: {result.source}, Success: {result.success}')
"

# 5. 启动 Celery worker
celery -A core worker -l info -Q qlib_infer

# 6. 测试推理任务
python -c "
from apps.alpha.application.tasks import qlib_predict_scores
qlib_predict_scores.delay('csi300', '2026-02-05')
"

# 7. 检查缓存
python manage.py shell
>>> from apps.alpha.infrastructure.models import AlphaScoreCache
>>> AlphaScoreCache.objects.all()
```

### MCP 工具验证

```bash
# 启动 MCP 服务器
python -m agomsaaf_mcp

# 测试工具
# get_alpha_stock_scores
# get_alpha_provider_status
```

---

## 十四、故障排查清单

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| Qlib import 失败 | 未安装 pyqlib | `pip install pyqlib` |
| 数据不存在 | `~/.qlib/qlib_data/cn_data` 为空 | 运行 `init_qlib_data` |
| 没有激活的模型 | Registry 中 `is_active=False` | 运行 `activate_model` |
| 推理任务不执行 | Celery queue 未启动 | `celery -A core worker -Q qlib_infer` |
| 缓存过期 | `staleness_days > 2` | 检查定时任务配置 |

---

## 十五、参考现有实现

### 复用的现有模式

1. **Protocol 接口**: 参考 `apps/backtest/infrastructure/adapters/base.py`
2. **Failover 模式**: 参考 `apps/rotation/infrastructure/adapters/price_adapter.py`
3. **Celery 任务**: 参考 `apps/macro/application/tasks.py`
4. **MCP 工具**: 参考 `sdk/agomsaaf_mcp/tools/regime_tools.py`
5. **SDK 模块**: 参考 `sdk/agomsaaf/modules/base.py`
6. **配置管理**: 参考 `shared/config/secrets.py`

---

## 总结

本方案基于 v1.1 架构设计，确保：

1. **训练与推理解耦**: 线上永不触发 `fit()`
2. **进程隔离**: `qlib_train` 和 `qlib_infer` 独立队列
3. **时间对齐**: 所有输出携带 `asof_date` / `intended_trade_date`
4. **可审计**: 完整的模型版本、数据版本追溯
5. **可降级**: Qlib → Cache → Simple → ETF 降级链路
6. **可监控**: 6 个核心指标埋点
