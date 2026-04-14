"""
Repository implementations for AI provider management.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from cryptography.fernet import InvalidToken
from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from shared.infrastructure.crypto import FieldEncryptionService

from .models import AIProviderConfig, AIUsageLog, AIUserFallbackQuota

logger = logging.getLogger(__name__)


class AIProviderRepository:
    """
    AI提供商仓储。

    负责 provider 配置的 CRUD、scope 过滤与 API Key 加解密。
    """

    def __init__(self) -> None:
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
        if not api_key:
            return ""
        return self._crypto_service.encrypt(api_key)

    def _decrypt_api_key(self, encrypted_key: str) -> str:
        if not encrypted_key:
            return ""
        try:
            return self._crypto_service.decrypt(encrypted_key, suppress_warning=True)
        except (InvalidToken, ValueError):
            logger.info("Skipping encrypted API key that cannot be decrypted in current environment")
            return ""
        except Exception:
            if encrypted_key.startswith(FieldEncryptionService.PREFIX):
                return ""
            return encrypted_key

    def get_api_key(self, provider: AIProviderConfig) -> str:
        """Get decrypted API key from provider."""
        if provider.api_key_encrypted:
            decrypted = self._decrypt_api_key(provider.api_key_encrypted)
            if decrypted:
                return decrypted
        return provider.api_key or ""

    def _base_queryset(self):
        return AIProviderConfig._default_manager.select_related("owner_user")

    def _build_queryset(
        self,
        *,
        scope: str | None = None,
        owner_user=None,
        include_inactive: bool = True,
    ):
        queryset = self._base_queryset()
        if scope is not None:
            queryset = queryset.filter(scope=scope)
        if owner_user is not None:
            queryset = queryset.filter(owner_user=owner_user)
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        return queryset.order_by("priority", "name")

    def get_all(self) -> list[AIProviderConfig]:
        """Backward-compatible admin listing for system providers."""
        return self.get_system_providers(include_inactive=True)

    def get_all_for_admin(self, include_inactive: bool = True) -> list[AIProviderConfig]:
        """Return all providers across scopes for admins."""
        return list(self._build_queryset(include_inactive=include_inactive))

    def get_system_providers(self, include_inactive: bool = True) -> list[AIProviderConfig]:
        """Return system-scope providers."""
        return list(
            self._build_queryset(
                scope="system",
                include_inactive=include_inactive,
            )
        )

    def get_active_providers(self) -> list[AIProviderConfig]:
        """Backward-compatible active provider listing for system scope."""
        return self.get_active_system_providers()

    def get_active_system_providers(self) -> list[AIProviderConfig]:
        """Return active system providers ordered by priority."""
        return self.get_system_providers(include_inactive=False)

    def get_user_providers(self, user, include_inactive: bool = True) -> list[AIProviderConfig]:
        """Return user-owned providers."""
        if user is None:
            return []
        return list(
            self._build_queryset(
                scope="user",
                owner_user=user,
                include_inactive=include_inactive,
            )
        )

    def get_active_user_providers(self, user) -> list[AIProviderConfig]:
        """Return active providers owned by a user."""
        return self.get_user_providers(user, include_inactive=False)

    def get_by_id(self, pk: int, user=None) -> AIProviderConfig | None:
        """Get provider by id, optionally enforcing user visibility."""
        try:
            provider = self._base_queryset().get(pk=pk)
        except AIProviderConfig.DoesNotExist:
            return None
        if provider.scope == "user" and user is not None and provider.owner_user_id != user.id:
            return None
        return provider

    def get_by_name(
        self,
        name: str,
        *,
        scope: str | None = None,
        owner_user=None,
    ) -> AIProviderConfig | None:
        """Get provider by name with optional scope filter."""
        queryset = self._base_queryset()
        if scope is not None:
            queryset = queryset.filter(scope=scope)
        if owner_user is not None:
            queryset = queryset.filter(owner_user=owner_user)
        try:
            return queryset.get(name=name)
        except AIProviderConfig.DoesNotExist:
            return None

    def get_by_type(self, provider_type: str, *, scope: str = "system") -> list[AIProviderConfig]:
        """Get active providers by type and scope."""
        return list(
            self._base_queryset()
            .filter(provider_type=provider_type, is_active=True, scope=scope)
            .order_by("priority", "name")
        )

    def name_exists(
        self,
        *,
        name: str,
        scope: str,
        owner_user=None,
        exclude_pk: int | None = None,
    ) -> bool:
        """Check name uniqueness within the relevant scope."""
        queryset = self._base_queryset().filter(name=name, scope=scope)
        if scope == "user":
            queryset = queryset.filter(owner_user=owner_user)
        else:
            queryset = queryset.filter(owner_user__isnull=True)
        if exclude_pk is not None:
            queryset = queryset.exclude(pk=exclude_pk)
        return queryset.exists()

    def get_provider_for_reference(self, provider_ref, user=None) -> AIProviderConfig | None:
        """Resolve provider reference for a user-aware request."""
        if provider_ref in (None, ""):
            return None
        provider: AIProviderConfig | None
        if isinstance(provider_ref, int) or (
            isinstance(provider_ref, str) and provider_ref.isdigit()
        ):
            provider = self.get_by_id(int(provider_ref), user=user)
        else:
            provider = None
            if user is not None:
                provider = self.get_by_name(str(provider_ref), scope="user", owner_user=user)
            if provider is None:
                provider = self.get_by_name(str(provider_ref), scope="system")
        if provider is None:
            return None
        if provider.scope == "user" and user is None:
            return None
        if provider.scope == "user" and user is not None and provider.owner_user_id != user.id:
            return None
        return provider

    def create(self, **kwargs) -> AIProviderConfig:
        """Create provider and encrypt API key."""
        scope = kwargs.get("scope", "system")
        owner_user = kwargs.get("owner_user")
        if scope == "system":
            kwargs["owner_user"] = None
        elif owner_user is None:
            raise ValueError("owner_user is required for user-scope providers")

        api_key = kwargs.pop("api_key", "")
        kwargs["api_key_encrypted"] = self._encrypt_api_key(api_key)
        kwargs["api_key"] = ""
        return AIProviderConfig._default_manager.create(**kwargs)

    def update(self, pk: int, **kwargs) -> bool:
        """Update provider with optional encrypted API key handling."""
        try:
            provider = AIProviderConfig._default_manager.get(pk=pk)
        except AIProviderConfig.DoesNotExist:
            return False

        if "scope" in kwargs and kwargs["scope"] == "system":
            kwargs["owner_user"] = None

        if "api_key" in kwargs:
            api_key = kwargs.pop("api_key")
            if api_key:
                kwargs["api_key_encrypted"] = self._encrypt_api_key(api_key)
                kwargs["api_key"] = ""
            else:
                kwargs.pop("api_key_encrypted", None)
                if provider.api_key and not provider.api_key_encrypted:
                    kwargs["api_key_encrypted"] = self._encrypt_api_key(provider.api_key)
                    kwargs["api_key"] = ""
        elif provider.api_key and not provider.api_key_encrypted:
            kwargs["api_key_encrypted"] = self._encrypt_api_key(provider.api_key)
            kwargs["api_key"] = ""

        for key, value in kwargs.items():
            setattr(provider, key, value)
        provider.save()
        return True

    def delete(self, pk: int) -> bool:
        """Delete provider by id."""
        try:
            provider = AIProviderConfig._default_manager.get(pk=pk)
        except AIProviderConfig.DoesNotExist:
            return False
        provider.delete()
        return True

    def update_last_used(self, pk: int) -> bool:
        """Update provider last-used timestamp."""
        try:
            provider = AIProviderConfig._default_manager.get(pk=pk)
        except AIProviderConfig.DoesNotExist:
            return False
        provider.last_used_at = timezone.now()
        provider.save(update_fields=["last_used_at"])
        return True


class AIUsageRepository:
    """AI使用日志仓储。"""

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
        request_metadata: dict[str, Any] | None = None,
        user=None,
        provider_scope: str = "system_global",
        quota_charged: bool = False,
    ) -> AIUsageLog:
        """Persist one AI usage log entry."""
        log = AIUsageLog._default_manager.create(
            provider=provider,
            user=user,
            provider_scope=provider_scope,
            quota_charged=quota_charged,
            model=model,
            request_type=request_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost=Decimal(str(estimated_cost)),
            response_time_ms=response_time_ms,
            status=status,
            error_message=error_message,
            request_metadata=request_metadata or {},
        )
        provider.last_used_at = timezone.now()
        provider.save(update_fields=["last_used_at"])
        return log

    def get_daily_usage(self, provider_id: int, target_date: date) -> dict[str, Any]:
        """Aggregate provider usage for a date."""
        result = (
            AIUsageLog._default_manager.filter(
                provider_id=provider_id,
                created_at__date=target_date,
            ).aggregate(
                total_requests=Count("id"),
                success_requests=Count("id", filter=Q(status="success")),
                total_tokens=Sum("total_tokens"),
                total_cost=Sum("estimated_cost"),
                avg_response_time_ms=Avg("response_time_ms"),
            )
        )
        return {
            "total_requests": result["total_requests"] or 0,
            "success_requests": result["success_requests"] or 0,
            "total_tokens": result["total_tokens"] or 0,
            "total_cost": float(result["total_cost"] or Decimal("0")),
            "avg_response_time_ms": float(result["avg_response_time_ms"] or 0),
        }

    def get_monthly_usage(self, provider_id: int, year: int, month: int) -> dict[str, Any]:
        """Aggregate provider usage for a month."""
        result = (
            AIUsageLog._default_manager.filter(
                provider_id=provider_id,
                created_at__year=year,
                created_at__month=month,
            ).aggregate(
                total_requests=Count("id"),
                success_requests=Count("id", filter=Q(status="success")),
                total_tokens=Sum("total_tokens"),
                total_cost=Sum("estimated_cost"),
                avg_response_time_ms=Avg("response_time_ms"),
            )
        )
        return {
            "total_requests": result["total_requests"] or 0,
            "success_requests": result["success_requests"] or 0,
            "total_tokens": result["total_tokens"] or 0,
            "total_cost": float(result["total_cost"] or Decimal("0")),
            "avg_response_time_ms": float(result["avg_response_time_ms"] or 0),
        }

    def check_budget_limits(
        self,
        provider_id: int,
        daily_limit: float | None,
        monthly_limit: float | None,
    ) -> dict[str, Any]:
        """Check provider-level budget usage against current limits."""
        today = date.today()
        daily_usage = self.get_daily_usage(provider_id, today)
        monthly_usage = self.get_monthly_usage(provider_id, today.year, today.month)
        daily_exceeded = daily_limit is not None and daily_usage["total_cost"] >= daily_limit
        monthly_exceeded = monthly_limit is not None and monthly_usage["total_cost"] >= monthly_limit
        return {
            "daily": {
                "spent": daily_usage["total_cost"],
                "limit": daily_limit,
                "exceeded": daily_exceeded,
            },
            "monthly": {
                "spent": monthly_usage["total_cost"],
                "limit": monthly_limit,
                "exceeded": monthly_exceeded,
            },
        }

    def get_user_fallback_daily_spend(self, user, target_date: date) -> float:
        """Get user's system-fallback spend for a given day."""
        result = AIUsageLog._default_manager.filter(
            user=user,
            quota_charged=True,
            provider_scope="system_fallback",
            created_at__date=target_date,
            status="success",
        ).aggregate(total_cost=Sum("estimated_cost"))
        return float(result["total_cost"] or Decimal("0"))

    def get_user_fallback_monthly_spend(self, user, year: int, month: int) -> float:
        """Get user's system-fallback spend for a given month."""
        result = AIUsageLog._default_manager.filter(
            user=user,
            quota_charged=True,
            provider_scope="system_fallback",
            created_at__year=year,
            created_at__month=month,
            status="success",
        ).aggregate(total_cost=Sum("estimated_cost"))
        return float(result["total_cost"] or Decimal("0"))

    def check_user_fallback_limits(
        self,
        user,
        daily_limit: float | None,
        monthly_limit: float | None,
    ) -> dict[str, Any]:
        """Check user fallback quota usage."""
        today = date.today()
        daily_spent = self.get_user_fallback_daily_spend(user, today)
        monthly_spent = self.get_user_fallback_monthly_spend(user, today.year, today.month)
        return {
            "daily": {
                "spent": daily_spent,
                "limit": daily_limit,
                "exceeded": daily_limit is not None and daily_spent >= daily_limit,
            },
            "monthly": {
                "spent": monthly_spent,
                "limit": monthly_limit,
                "exceeded": monthly_limit is not None and monthly_spent >= monthly_limit,
            },
        }

    def get_recent_logs(
        self,
        provider_id: int | None = None,
        limit: int = 100,
        status: str | None = None,
        user=None,
        provider_scope: str | None = None,
    ) -> list[AIUsageLog]:
        """Fetch recent logs with optional provider/user filters."""
        queryset = AIUsageLog._default_manager.select_related("provider", "user")
        if provider_id:
            queryset = queryset.filter(provider_id=provider_id)
        if status:
            queryset = queryset.filter(status=status)
        if user is not None:
            queryset = queryset.filter(user=user)
        if provider_scope:
            queryset = queryset.filter(provider_scope=provider_scope)
        return list(queryset.order_by("-created_at")[:limit])

    def get_usage_by_date(self, provider_id: int, days: int = 30) -> list[dict[str, Any]]:
        """Aggregate success usage by date."""
        start_date = date.today() - timedelta(days=days)
        results = (
            AIUsageLog._default_manager.filter(
                provider_id=provider_id,
                created_at__date__gte=start_date,
                status="success",
            )
            .annotate(date=TruncDate("created_at"))
            .values("date")
            .annotate(
                requests=Count("id"),
                tokens=Sum("total_tokens"),
                cost=Sum("estimated_cost"),
            )
            .order_by("date")
        )
        return [
            {
                "date": item["date"].strftime("%Y-%m-%d"),
                "requests": item["requests"],
                "tokens": item["tokens"] or 0,
                "cost": float(item["cost"] or 0),
            }
            for item in results
        ]

    def get_model_stats(self, provider_id: int, days: int = 30) -> list[dict[str, Any]]:
        """Aggregate success usage by model."""
        start_date = date.today() - timedelta(days=days)
        results = (
            AIUsageLog._default_manager.filter(
                provider_id=provider_id,
                created_at__date__gte=start_date,
                status="success",
            )
            .values("model")
            .annotate(
                requests=Count("id"),
                tokens=Sum("total_tokens"),
                cost=Sum("estimated_cost"),
                avg_response_time=Avg("response_time_ms"),
            )
            .order_by("-requests")
        )
        return [
            {
                "model": item["model"],
                "requests": item["requests"],
                "tokens": item["tokens"] or 0,
                "cost": float(item["cost"] or 0),
                "avg_response_time": float(item["avg_response_time"] or 0),
            }
            for item in results
        ]


class AIUserFallbackQuotaRepository:
    """Repository for user-scoped fallback quota configuration."""

    def __init__(self, usage_repo: AIUsageRepository | None = None) -> None:
        self._usage_repo = usage_repo or AIUsageRepository()

    def get_for_user(self, user) -> AIUserFallbackQuota | None:
        """Get one user's fallback quota."""
        if user is None:
            return None
        try:
            return AIUserFallbackQuota._default_manager.get(user=user)
        except AIUserFallbackQuota.DoesNotExist:
            return None

    def get_with_usage(self, user) -> tuple[AIUserFallbackQuota | None, float, float]:
        """Return quota with today's and this month's usage."""
        quota = self.get_for_user(user)
        if quota is None:
            return None, 0.0, 0.0
        today = date.today()
        daily_spent = self._usage_repo.get_user_fallback_daily_spend(user, today)
        monthly_spent = self._usage_repo.get_user_fallback_monthly_spend(user, today.year, today.month)
        return quota, daily_spent, monthly_spent

    def upsert_for_user(
        self,
        *,
        user,
        daily_limit: float | Decimal | None,
        monthly_limit: float | Decimal | None,
        is_active: bool = True,
        admin_note: str = "",
    ) -> tuple[AIUserFallbackQuota, bool]:
        """Create or update one user's quota."""
        quota, created = AIUserFallbackQuota._default_manager.update_or_create(
            user=user,
            defaults={
                "daily_limit": daily_limit,
                "monthly_limit": monthly_limit,
                "is_active": is_active,
                "admin_note": admin_note,
            },
        )
        return quota, created

    def batch_apply_to_users(
        self,
        *,
        daily_limit: float | Decimal | None,
        monthly_limit: float | Decimal | None,
        overwrite_existing: bool = False,
        is_active: bool = True,
        admin_note: str = "",
    ) -> dict[str, int]:
        """Apply the same quota to all active users."""
        user_model = get_user_model()
        users = user_model._default_manager.all()
        if hasattr(user_model, "is_active"):
            users = users.filter(is_active=True)

        created_count = 0
        updated_count = 0
        skipped_count = 0
        processed_users = 0

        for user in users:
            processed_users += 1
            existing = self.get_for_user(user)
            if existing is not None and not overwrite_existing:
                skipped_count += 1
                continue
            _, created = self.upsert_for_user(
                user=user,
                daily_limit=daily_limit,
                monthly_limit=monthly_limit,
                is_active=is_active,
                admin_note=admin_note,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        return {
            "processed_users": processed_users,
            "created_count": created_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
        }
