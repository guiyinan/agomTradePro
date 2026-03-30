"""
Repository Implementations for AI Provider Management.

数据仓储实现，参考 DjangoMacroRepository 的模式。
"""

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

from cryptography.fernet import InvalidToken
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from shared.infrastructure.crypto import FieldEncryptionService

from ..domain.entities import AIUsageRecord
from .models import AIProviderConfig, AIUsageLog

logger = logging.getLogger(__name__)


class AIProviderRepository:
    """
    AI提供商仓储

    负责AI提供商配置的CRUD操作。
    支持API Key的加密存储和解密读取。
    """

    def __init__(self):
        """Initialize repository with encryption service."""
        self._crypto: FieldEncryptionService | None = None

    @property
    def _crypto_service(self) -> FieldEncryptionService:
        """Lazy-load encryption service."""
        if self._crypto is None:
            try:
                self._crypto = FieldEncryptionService()
            except ValueError:
                logger.error("AGOMTRADEPRO_ENCRYPTION_KEY not configured")
                raise ValueError("AGOMTRADEPRO_ENCRYPTION_KEY not configured")
        if self._crypto is None:
            raise ValueError("Encryption service not available")
        return self._crypto

    def _encrypt_api_key(self, api_key: str) -> str:
        """Encrypt API key. Plaintext fallback is not allowed."""
        if not api_key:
            return ''
        return self._crypto_service.encrypt(api_key)

    def _decrypt_api_key(self, encrypted_key: str) -> str:
        """Decrypt API key if encryption service is available."""
        if not encrypted_key:
            return ''
        try:
            return self._crypto_service.decrypt(encrypted_key, suppress_warning=True)
        except (InvalidToken, ValueError):
            logger.info("Skipping encrypted API key that cannot be decrypted in current environment")
            return ''
        except Exception:
            if encrypted_key.startswith(FieldEncryptionService.PREFIX):
                return ''
            return encrypted_key

    def get_api_key(self, provider: AIProviderConfig) -> str:
        """
        Get decrypted API key from provider.

        Prioritizes encrypted field, falls back to plaintext field.

        Args:
            provider: AIProviderConfig instance

        Returns:
            Decrypted API key
        """
        # Try encrypted field first
        if provider.api_key_encrypted:
            decrypted = self._decrypt_api_key(provider.api_key_encrypted)
            if decrypted:
                return decrypted
        # Fall back to plaintext field
        return provider.api_key or ''

    def get_all(self) -> list[AIProviderConfig]:
        """获取所有提供商配置"""
        return list(AIProviderConfig._default_manager.all().order_by('priority', 'name'))

    def get_active_providers(self) -> list[AIProviderConfig]:
        """获取所有启用的提供商，按优先级排序"""
        return list(AIProviderConfig._default_manager.filter(
            is_active=True
        ).order_by('priority', 'name'))

    def get_by_id(self, pk: int) -> AIProviderConfig | None:
        """根据ID获取提供商"""
        try:
            return AIProviderConfig._default_manager.get(pk=pk)
        except AIProviderConfig.DoesNotExist:
            return None

    def get_by_name(self, name: str) -> AIProviderConfig | None:
        """根据名称获取提供商"""
        try:
            return AIProviderConfig._default_manager.get(name=name)
        except AIProviderConfig.DoesNotExist:
            return None

    def get_by_type(self, provider_type: str) -> list[AIProviderConfig]:
        """根据类型获取提供商"""
        return list(AIProviderConfig._default_manager.filter(
            provider_type=provider_type,
            is_active=True
        ).order_by('priority'))

    def create(self, **kwargs) -> AIProviderConfig:
        """
        创建新提供商

        API key will be encrypted if provided.
        """
        api_key = kwargs.pop('api_key', '')
        kwargs['api_key_encrypted'] = self._encrypt_api_key(api_key)
        kwargs['api_key'] = ''  # Clear plaintext field
        return AIProviderConfig._default_manager.create(**kwargs)

    def update(self, pk: int, **kwargs) -> bool:
        """
        更新提供商

        API key will be encrypted if provided.
        """
        try:
            provider = AIProviderConfig._default_manager.get(pk=pk)
            # Handle API key encryption
            if 'api_key' in kwargs:
                api_key = kwargs.pop('api_key')
                kwargs['api_key_encrypted'] = self._encrypt_api_key(api_key)
                kwargs['api_key'] = ''  # Clear plaintext field
            for key, value in kwargs.items():
                setattr(provider, key, value)
            provider.save()
            return True
        except AIProviderConfig.DoesNotExist:
            return False

    def delete(self, pk: int) -> bool:
        """删除提供商"""
        try:
            provider = AIProviderConfig._default_manager.get(pk=pk)
            provider.delete()
            return True
        except AIProviderConfig.DoesNotExist:
            return False

    def update_last_used(self, pk: int) -> bool:
        """更新最后使用时间"""
        try:
            provider = AIProviderConfig._default_manager.get(pk=pk)
            provider.last_used_at = timezone.now()
            provider.save(update_fields=['last_used_at'])
            return True
        except AIProviderConfig.DoesNotExist:
            return False


class AIUsageRepository:
    """
    AI使用日志仓储

    负责API调用日志的记录和查询。
    """

    def log_usage(
        self,
        provider: AIProviderConfig,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        estimated_cost: float,
        response_time_ms: int,
        status: str,
        request_type: str = "chat",
        error_message: str = "",
        request_metadata: dict = None
    ) -> AIUsageLog:
        """
        记录API调用日志

        Args:
            provider: 提供商配置
            model: 模型名称
            prompt_tokens: 输入token数
            completion_tokens: 输出token数
            total_tokens: 总token数
            estimated_cost: 预估成本
            response_time_ms: 响应时间（毫秒）
            status: 状态
            request_type: 请求类型
            error_message: 错误信息
            request_metadata: 请求元数据

        Returns:
            AIUsageLog: 日志记录
        """
        log = AIUsageLog._default_manager.create(
            provider=provider,
            model=model,
            request_type=request_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=Decimal(str(estimated_cost)),
            response_time_ms=response_time_ms,
            status=status,
            error_message=error_message,
            request_metadata=request_metadata or {}
        )

        # 更新提供商最后使用时间
        provider.last_used_at = timezone.now()
        provider.save(update_fields=['last_used_at'])

        return log

    def get_daily_usage(
        self,
        provider_id: int,
        target_date: date
    ) -> dict[str, Any]:
        """
        获取指定日期的使用统计

        Args:
            provider_id: 提供商ID
            target_date: 目标日期

        Returns:
            Dict: 统计信息
                {
                    "total_requests": int,
                    "success_requests": int,
                    "total_tokens": int,
                    "total_cost": float,
                    "avg_response_time_ms": float
                }
        """
        result = AIUsageLog._default_manager.filter(
            provider_id=provider_id,
            created_at__date=target_date
        ).aggregate(
            total_requests=Count('id'),
            success_requests=Count('id', filter=Q(status='success')),
            total_tokens=Sum('total_tokens'),
            total_cost=Sum('estimated_cost'),
            avg_response_time_ms=Avg('response_time_ms')
        )

        return {
            'total_requests': result['total_requests'] or 0,
            'success_requests': result['success_requests'] or 0,
            'total_tokens': result['total_tokens'] or 0,
            'total_cost': float(result['total_cost'] or Decimal('0')),
            'avg_response_time_ms': float(result['avg_response_time_ms'] or 0),
        }

    def get_monthly_usage(
        self,
        provider_id: int,
        year: int,
        month: int
    ) -> dict[str, Any]:
        """
        获取指定月份的使用统计

        Args:
            provider_id: 提供商ID
            year: 年份
            month: 月份

        Returns:
            Dict: 统计信息
        """
        result = AIUsageLog._default_manager.filter(
            provider_id=provider_id,
            created_at__year=year,
            created_at__month=month
        ).aggregate(
            total_requests=Count('id'),
            success_requests=Count('id', filter=Q(status='success')),
            total_tokens=Sum('total_tokens'),
            total_cost=Sum('estimated_cost'),
            avg_response_time_ms=Avg('response_time_ms')
        )

        return {
            'total_requests': result['total_requests'] or 0,
            'success_requests': result['success_requests'] or 0,
            'total_tokens': result['total_tokens'] or 0,
            'total_cost': float(result['total_cost'] or Decimal('0')),
            'avg_response_time_ms': float(result['avg_response_time_ms'] or 0),
        }

    def check_budget_limits(
        self,
        provider_id: int,
        daily_limit: float | None,
        monthly_limit: float | None
    ) -> dict[str, Any]:
        """
        检查预算限制

        Args:
            provider_id: 提供商ID
            daily_limit: 每日限制
            monthly_limit: 每月限制

        Returns:
            Dict: 预算检查结果
                {
                    "daily": {"spent": float, "limit": float, "exceeded": bool},
                    "monthly": {"spent": float, "limit": float, "exceeded": bool}
                }
        """
        today = date.today()
        current_month_start = today.replace(day=1)

        # 检查每日预算
        daily_usage = self.get_daily_usage(provider_id, today)
        daily_exceeded = daily_limit and daily_usage['total_cost'] >= daily_limit

        # 检查每月预算
        monthly_usage = self.get_monthly_usage(provider_id, today.year, today.month)
        monthly_exceeded = monthly_limit and monthly_usage['total_cost'] >= monthly_limit

        return {
            'daily': {
                'spent': daily_usage['total_cost'],
                'limit': daily_limit,
                'exceeded': daily_exceeded
            },
            'monthly': {
                'spent': monthly_usage['total_cost'],
                'limit': monthly_limit,
                'exceeded': monthly_exceeded
            }
        }

    def get_recent_logs(
        self,
        provider_id: int | None = None,
        limit: int = 100,
        status: str | None = None
    ) -> list[AIUsageLog]:
        """
        获取最近的日志记录

        Args:
            provider_id: 提供商ID（不指定则查询所有）
            limit: 返回数量限制
            status: 状态过滤

        Returns:
            List[AIUsageLog]: 日志记录列表
        """
        queryset = AIUsageLog._default_manager.all()

        if provider_id:
            queryset = queryset.filter(provider_id=provider_id)

        if status:
            queryset = queryset.filter(status=status)

        return list(queryset.order_by('-created_at')[:limit])

    def get_usage_by_date(
        self,
        provider_id: int,
        days: int = 30
    ) -> list[dict[str, Any]]:
        """
        按日期获取使用统计

        Args:
            provider_id: 提供商ID
            days: 天数

        Returns:
            List[Dict]: 每日统计
                [
                    {"date": "2024-01-01", "requests": 10, "tokens": 1000, "cost": 0.01},
                    ...
                ]
        """
        start_date = date.today() - timedelta(days=days)

        results = AIUsageLog._default_manager.filter(
            provider_id=provider_id,
            created_at__date__gte=start_date,
            status='success'
        ).annotate(
            date=TruncDate('created_at')
        ).values('date').annotate(
            requests=Count('id'),
            tokens=Sum('total_tokens'),
            cost=Sum('estimated_cost')
        ).order_by('date')

        return [
            {
                'date': r['date'].strftime('%Y-%m-%d'),
                'requests': r['requests'],
                'tokens': r['tokens'] or 0,
                'cost': float(r['cost'] or 0)
            }
            for r in results
        ]

    def get_model_stats(
        self,
        provider_id: int,
        days: int = 30
    ) -> list[dict[str, Any]]:
        """
        按模型获取使用统计

        Args:
            provider_id: 提供商ID
            days: 天数

        Returns:
            List[Dict]: 每个模型的统计
        """
        start_date = date.today() - timedelta(days=days)

        results = AIUsageLog._default_manager.filter(
            provider_id=provider_id,
            created_at__date__gte=start_date,
            status='success'
        ).values('model').annotate(
            requests=Count('id'),
            tokens=Sum('total_tokens'),
            cost=Sum('estimated_cost'),
            avg_response_time=Avg('response_time_ms')
        ).order_by('-requests')

        return [
            {
                'model': r['model'],
                'requests': r['requests'],
                'tokens': r['tokens'] or 0,
                'cost': float(r['cost'] or 0),
                'avg_response_time': float(r['avg_response_time'] or 0)
            }
            for r in results
        ]
