"""Provider configuration, settings, coverage-universe, and fetch-audit persistence."""

from __future__ import annotations

from apps.data_center.domain.entities import (
    DataProviderSettings,
    ProductionCoverageUniverseConfig,
    ProviderConfig,
    RawAudit,
)
from apps.data_center.infrastructure.models import (
    DataProviderSettingsModel,
    ProductionCoverageUniverseConfigModel,
    ProviderConfigModel,
    RawAuditModel,
)


class ProviderConfigRepository:
    """Persists and retrieves ProviderConfig domain objects via Django ORM."""

    def list_all(self) -> list[ProviderConfig]:
        return [m.to_domain() for m in ProviderConfigModel.objects.all()]

    def list_active(self) -> list[ProviderConfig]:
        """Return active provider configs ordered by priority."""
        return [
            m.to_domain()
            for m in ProviderConfigModel.objects.filter(is_active=True).order_by("priority")
        ]

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        try:
            return ProviderConfigModel.objects.get(pk=provider_id).to_domain()
        except ProviderConfigModel.DoesNotExist:
            return None

    def get_by_name(self, name: str) -> ProviderConfig | None:
        try:
            return ProviderConfigModel.objects.get(name=name).to_domain()
        except ProviderConfigModel.DoesNotExist:
            return None

    def get_active_by_type(self, source_type: str) -> list[ProviderConfig]:
        return [
            m.to_domain()
            for m in ProviderConfigModel.objects.filter(
                source_type=source_type, is_active=True
            ).order_by("priority")
        ]

    def save(self, config: ProviderConfig) -> ProviderConfig:
        """Create or update a ProviderConfigModel row."""
        if config.id is not None:
            model = ProviderConfigModel.objects.get(pk=config.id)
        else:
            model = ProviderConfigModel()

        model.name = config.name
        model.source_type = config.source_type
        model.is_active = config.is_active
        model.priority = config.priority
        model.api_key = config.api_key
        model.api_secret = config.api_secret
        model.http_url = config.http_url
        model.api_endpoint = config.api_endpoint
        model.extra_config = config.extra_config
        model.description = config.description
        model.save()
        return model.to_domain()

    def delete(self, provider_id: int) -> None:
        ProviderConfigModel.objects.filter(pk=provider_id).delete()


class DataProviderSettingsRepository:
    """Persists and retrieves global provider settings (singleton)."""

    def has_settings(self) -> bool:
        """Return whether the singleton settings row already exists."""

        return DataProviderSettingsModel.objects.exists()

    def load(self) -> DataProviderSettings:
        return DataProviderSettingsModel.load().to_domain()

    def save(self, settings: DataProviderSettings) -> DataProviderSettings:
        model = DataProviderSettingsModel.load()
        model.default_source = settings.default_source
        model.enable_failover = settings.enable_failover
        model.failover_tolerance = settings.failover_tolerance
        model.save()
        return model.to_domain()


class ProductionCoverageUniverseConfigRepository:
    """Persists and retrieves production coverage universe config."""

    def load(self) -> ProductionCoverageUniverseConfig:
        return ProductionCoverageUniverseConfigModel.load().to_domain()

    def save(
        self,
        config: ProductionCoverageUniverseConfig,
    ) -> ProductionCoverageUniverseConfig:
        model = ProductionCoverageUniverseConfigModel.load()
        model.universe_id = config.universe_id
        model.asset_type = config.asset_type
        model.exchanges = list(config.exchanges)
        model.include_inactive = config.include_inactive
        model.min_active_asset_count = config.min_active_asset_count
        model.min_star_market_count = config.min_star_market_count
        model.min_chinext_count = config.min_chinext_count
        model.min_bse_count = config.min_bse_count
        model.description = config.description
        model.save()
        return model.to_domain()


class RawAuditRepository:
    """ORM-backed repository for the raw fetch audit log."""

    @staticmethod
    def _from_model(m: RawAuditModel) -> RawAudit:
        return RawAudit(
            provider_name=m.provider_name,
            capability=m.capability,
            request_params=m.request_params or {},
            status=m.status,
            row_count=m.row_count,
            latency_ms=m.latency_ms,
            error_message=m.error_message,
            fetched_at=m.fetched_at,
            extra=m.extra or {},
            request_params_hash=m.request_params_hash,
            response_payload_hash=m.response_payload_hash,
            schema_fingerprint=m.schema_fingerprint,
            redacted=m.redacted,
            parser_version=m.parser_version,
            payload_size_bytes=int(m.payload_size_bytes),
            retention_until=m.retention_until,
            ingested_run_id=str(m.ingested_run_id) if m.ingested_run_id else "",
        )

    def log(self, audit: RawAudit) -> RawAudit:
        m = RawAuditModel.objects.create(
            provider_name=audit.provider_name,
            capability=audit.capability,
            request_params=audit.request_params,
            status=audit.status,
            row_count=audit.row_count,
            latency_ms=audit.latency_ms,
            error_message=audit.error_message,
            fetched_at=audit.fetched_at,
            extra=audit.extra,
            request_params_hash=audit.request_params_hash,
            response_payload_hash=audit.response_payload_hash,
            schema_fingerprint=audit.schema_fingerprint,
            redacted=audit.redacted,
            parser_version=audit.parser_version,
            payload_size_bytes=audit.payload_size_bytes,
            retention_until=audit.retention_until,
            ingested_run_id=audit.ingested_run_id or None,
        )
        return self._from_model(m)

    def get_recent(
        self,
        provider_name: str | None = None,
        capability: str | None = None,
        limit: int = 100,
    ) -> list[RawAudit]:
        qs = RawAuditModel.objects.all()
        if provider_name:
            qs = qs.filter(provider_name=provider_name)
        if capability:
            qs = qs.filter(capability=capability)
        return [self._from_model(m) for m in qs.order_by("-fetched_at")[:limit]]
