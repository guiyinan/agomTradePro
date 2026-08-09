"""
Data Center — Infrastructure Layer ORM Models

Phase 1: Unified provider configuration and global settings for all data domains.
Phase 2: Master data (AssetMasterModel, IndicatorCatalogModel) and eight fact tables
         (MacroFactModel, PriceBarModel, QuoteSnapshotModel, FundNavFactModel,
          FinancialFactModel, ValuationFactModel, SectorMembershipFactModel,
          NewsFactModel, CapitalFlowFactModel) plus RawAuditModel.
"""

import uuid
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.data_center.domain.control_plane import (
    QuarantineRecord,
    QuarantineResolution,
    SyncBatch,
    SyncCheckpoint,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)
from apps.data_center.domain.entities import (
    MarketThermometerComponentScore,
    MarketThermometerConfig,
    MarketThermometerSnapshot,
    MarketThermometerThresholds,
    MarketThermometerUserOverride,
    ProductionCoverageUniverseConfig,
    ProviderConfig,
    PublisherCatalog,
)
from apps.data_center.domain.raw_landing import RawPayload, SchemaFingerprint
from apps.data_center.domain.retention import (
    ArchiveManifest,
    ArchiveRestoreOutcome,
    ArchiveState,
    RetentionPolicy,
    StorageHold,
)
from shared.numeric import safe_float

from .pit_models import PITDatasetManifestModel, PITFactVersionModel  # noqa: F401
from .publication_models import CanonicalPublicationModel as CanonicalPublicationModel
from .publication_models import CoverageSnapshotModel as CoverageSnapshotModel
from .publication_models import PublicationMemberModel as PublicationMemberModel
from .publication_models import PublicationRollbackModel as PublicationRollbackModel
from .research_data_foundation_models import (  # noqa: F401
    AssetGroupRevisionModel as AssetGroupRevisionModel,
)
from .research_data_foundation_models import (
    InvestorFlowDefinitionModel as InvestorFlowDefinitionModel,
)
from .research_data_foundation_models import (
    OperatingMetricDefinitionModel as OperatingMetricDefinitionModel,
)


def _optional_json_float(value: object, field_name: str) -> float | None:
    """Parse a nullable finite number from persisted JSON."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number")
    parsed = safe_float(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be a finite number")
    return parsed


def _required_json_float(value: object, field_name: str) -> float:
    """Parse a required finite number from persisted JSON."""

    parsed = _optional_json_float(value, field_name)
    if parsed is None:
        raise ValueError(f"{field_name} is required")
    return parsed


def _json_bool(value: object, field_name: str) -> bool:
    """Require real booleans instead of truthy strings from persisted JSON."""

    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _optional_json_nonnegative_int(value: object, field_name: str) -> int | None:
    """Parse a nullable non-negative integer from persisted JSON."""

    if value is None:
        return None
    parsed = _optional_json_float(value, field_name)
    if parsed is None or not parsed.is_integer() or parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return int(parsed)


class ProviderConfigModel(models.Model):
    """Configurable external data-provider entry.

    One row per named provider (e.g. "tushare_main", "akshare_backup").
    Multiple rows may share the same source_type at different priorities.
    """

    SOURCE_TYPE_CHOICES = [
        ("tushare", "Tushare Pro"),
        ("akshare", "AKShare"),
        ("eastmoney", "EastMoney"),
        ("qmt", "QMT (XtQuant)"),
        ("fred", "FRED"),
        ("wind", "Wind"),
        ("choice", "Choice"),
    ]

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Provider name (unique identifier, e.g. 'tushare_main')",
    )
    source_type = models.CharField(
        max_length=20,
        choices=SOURCE_TYPE_CHOICES,
        help_text="Underlying data source type",
    )
    is_active = models.BooleanField(default=True, help_text="Whether this provider is enabled")
    priority = models.IntegerField(
        default=100,
        help_text="Dispatch priority — lower value = higher precedence",
    )

    # Credentials
    api_key = models.CharField(max_length=500, blank=True, help_text="API key / token")
    api_secret = models.CharField(max_length=500, blank=True, help_text="API secret (if required)")

    # Network
    http_url = models.URLField(
        blank=True,
        help_text="Custom HTTP URL (e.g. Tushare third-party proxy)",
    )
    api_endpoint = models.URLField(blank=True, help_text="Override API endpoint URL")

    # Provider-specific extras (QMT client_path/data_dir, etc.)
    extra_config = models.JSONField(
        default=dict, blank=True, help_text="Provider-specific parameters"
    )

    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_provider_config"
        ordering = ["priority", "name"]
        verbose_name = "Provider Config"
        verbose_name_plural = "Provider Configs"
        indexes = [
            models.Index(fields=["source_type", "is_active"]),
            models.Index(fields=["priority"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.get_source_type_display()}, priority={self.priority})"

    def to_domain(
        self,
        *,
        api_key: str = "",
        api_secret: str = "",
        credential_ref: str = "",
    ) -> ProviderConfig:
        """Convert to domain value object with explicitly resolved secrets.

        The model no longer exposes its legacy plaintext columns by default.
        Infrastructure repositories must resolve credentials through the
        encrypted provider-credential store and pass them explicitly.
        """

        return ProviderConfig(
            id=self.pk,
            name=self.name,
            source_type=self.source_type,
            is_active=self.is_active,
            priority=self.priority,
            api_key=api_key,
            api_secret=api_secret,
            http_url=self.http_url,
            api_endpoint=self.api_endpoint,
            extra_config=self.extra_config or {},
            description=self.description,
            credential_ref=credential_ref,
        )


class DataProviderSettingsModel(models.Model):
    """Global provider behaviour settings — singleton row (pk=1).

    Controls the default source preference and failover behaviour
    across all data domains.
    """

    DEFAULT_SOURCE_CHOICES = [
        ("akshare", "AKShare（推荐）"),
        ("tushare", "Tushare Pro"),
        ("failover", "自动容错（AKShare → Tushare）"),
    ]

    default_source = models.CharField(
        max_length=20,
        choices=DEFAULT_SOURCE_CHOICES,
        default="akshare",
        help_text="Default data source preference",
    )
    enable_failover = models.BooleanField(
        default=True,
        help_text="Auto-switch to backup provider when primary fails",
    )
    failover_tolerance = models.FloatField(
        default=0.01,
        help_text="Cross-provider consistency tolerance (0.01 = 1 %)",
    )
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_provider_settings"
        verbose_name = "Provider Settings"
        verbose_name_plural = "Provider Settings"

    def __str__(self) -> str:
        return f"Default source: {self.get_default_source_display()}"


class ProductionCoverageUniverseConfigModel(models.Model):
    """Singleton configuration for production coverage diagnostics universe."""

    _SINGLETON_PK = 1

    universe_id = models.CharField(
        max_length=50,
        default="active_a_share",
        help_text="Logical universe identifier used by readiness diagnostics",
    )
    asset_type = models.CharField(
        max_length=20,
        default="stock",
        help_text="AssetMaster asset_type included in coverage diagnostics",
    )
    exchanges = models.JSONField(
        default=list,
        blank=True,
        help_text="Included MarketExchange codes, e.g. SSE/SZSE/BSE",
    )
    include_inactive = models.BooleanField(
        default=False,
        help_text="Include inactive/delisted assets in the coverage denominator",
    )
    min_active_asset_count = models.PositiveIntegerField(default=4000)
    min_star_market_count = models.PositiveIntegerField(default=200)
    min_chinext_count = models.PositiveIntegerField(default=0)
    min_bse_count = models.PositiveIntegerField(default=50)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_production_coverage_universe_config"
        verbose_name = "Production Coverage Universe Config"
        verbose_name_plural = "Production Coverage Universe Config"

    def __str__(self) -> str:
        return f"{self.universe_id}: {','.join(self.normalized_exchanges())}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist the singleton config at primary key 1."""

        self.pk = self._SINGLETON_PK
        self.exchanges = self.normalized_exchanges()
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "ProductionCoverageUniverseConfigModel":
        """Return singleton, creating the full A-share default if absent."""

        obj, _ = cls.objects.get_or_create(
            pk=cls._SINGLETON_PK,
            defaults={
                "universe_id": "active_a_share",
                "asset_type": "stock",
                "exchanges": ["SSE", "SZSE", "BSE"],
                "include_inactive": False,
                "min_active_asset_count": 4000,
                "min_star_market_count": 200,
                "min_chinext_count": 0,
                "min_bse_count": 50,
                "description": "Full active A-share universe used for production coverage.",
            },
        )
        return obj

    def normalized_exchanges(self) -> list[str]:
        """Return uppercase unique exchange codes with a production-safe default."""

        values = self.exchanges if isinstance(self.exchanges, list) else []
        normalized: list[str] = []
        for raw in values:
            exchange = str(raw or "").strip().upper()
            if exchange and exchange not in normalized:
                normalized.append(exchange)
        return normalized or ["SSE", "SZSE", "BSE"]

    def to_domain(self) -> ProductionCoverageUniverseConfig:
        """Convert to domain ProductionCoverageUniverseConfig value object."""

        return ProductionCoverageUniverseConfig(
            universe_id=self.universe_id,
            asset_type=self.asset_type,
            exchanges=self.normalized_exchanges(),
            include_inactive=self.include_inactive,
            min_active_asset_count=self.min_active_asset_count,
            min_star_market_count=self.min_star_market_count,
            min_chinext_count=self.min_chinext_count,
            min_bse_count=self.min_bse_count,
            description=self.description,
        )


# ---------------------------------------------------------------------------
# Phase 2 — Master data
# ---------------------------------------------------------------------------


class AssetMasterModel(models.Model):
    """Security master table: one row per canonical ticker.

    ``code`` is in canonical Tushare format, e.g. ``600519.SH``.
    """

    ASSET_TYPE_CHOICES = [
        ("stock", "股票"),
        ("etf", "ETF"),
        ("index", "指数"),
        ("fund", "基金"),
        ("bond", "债券"),
        ("futures", "期货"),
        ("crypto", "加密货币"),
        ("other", "其他"),
    ]

    EXCHANGE_CHOICES = [
        ("SSE", "上交所"),
        ("SZSE", "深交所"),
        ("BSE", "北交所"),
        ("HKEX", "港交所"),
        ("NYSE", "纽交所"),
        ("NASDAQ", "纳斯达克"),
        ("OTHER", "其他"),
    ]

    code = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Canonical ticker (Tushare format, e.g. 600519.SH)",
    )
    name = models.CharField(max_length=100, help_text="Full security name")
    short_name = models.CharField(max_length=30, blank=True, help_text="Display short name")
    asset_type = models.CharField(max_length=10, choices=ASSET_TYPE_CHOICES)
    exchange = models.CharField(max_length=10, choices=EXCHANGE_CHOICES)
    is_active = models.BooleanField(default=True)

    list_date = models.DateField(null=True, blank=True, help_text="IPO / listing date")
    delist_date = models.DateField(null=True, blank=True)
    sector = models.CharField(max_length=100, blank=True)
    industry = models.CharField(max_length=100, blank=True)
    currency = models.CharField(max_length=10, default="CNY")
    total_shares = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total shares outstanding",
    )

    extra = models.JSONField(default=dict, blank=True, help_text="Provider-specific extras")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_asset_master"
        ordering = ["code"]
        verbose_name = "Asset"
        verbose_name_plural = "Assets"
        indexes = [
            models.Index(fields=["asset_type", "exchange"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} {self.name}"


class AssetAliasModel(models.Model):
    """Cross-provider ticker alias table.

    Allows the data center to resolve provider-specific codes
    (e.g. ``000001.XSHE`` from AKShare) back to a canonical AssetMaster row.
    """

    asset = models.ForeignKey(
        AssetMasterModel,
        on_delete=models.CASCADE,
        related_name="aliases",
    )
    provider_name = models.CharField(
        max_length=50,
        help_text="Provider identifier (e.g. 'akshare', 'wind')",
    )
    alias_code = models.CharField(
        max_length=40,
        help_text="Provider-local ticker code",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_asset_alias"
        unique_together = [("provider_name", "alias_code")]
        indexes = [
            models.Index(fields=["alias_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.provider_name}:{self.alias_code} → {self.asset.code}"


class PublisherCatalogModel(models.Model):
    """Canonical publisher / institution registry for provenance governance."""

    PUBLISHER_CLASS_CHOICES = [
        ("government", "Government"),
        ("association", "Association"),
        ("market_infrastructure", "Market Infrastructure"),
        ("regulator", "Regulator"),
        ("system", "System"),
        ("other", "Other"),
    ]

    code = models.CharField(
        max_length=40,
        unique=True,
        db_index=True,
        help_text="Stable publisher code such as PBOC, NBS, GACC",
    )
    canonical_name = models.CharField(max_length=120, help_text="Canonical Chinese display name")
    canonical_name_en = models.CharField(max_length=160, blank=True)
    publisher_class = models.CharField(max_length=30, choices=PUBLISHER_CLASS_CHOICES)
    aliases = models.JSONField(default=list, blank=True, help_text="Known alias names")
    country_code = models.CharField(max_length=10, default="CN", blank=True)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_publisher_catalog"
        ordering = ["code"]
        verbose_name = "Publisher Catalog"
        verbose_name_plural = "Publisher Catalog"
        indexes = [
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.canonical_name}"

    def to_domain(self) -> PublisherCatalog:
        """Convert to domain PublisherCatalog value object."""

        return PublisherCatalog(
            code=self.code,
            canonical_name=self.canonical_name,
            canonical_name_en=self.canonical_name_en,
            publisher_class=self.publisher_class,
            aliases=list(self.aliases or []),
            country_code=self.country_code,
            website=self.website,
            is_active=self.is_active,
            description=self.description,
        )


class IndicatorCatalogModel(models.Model):
    """Catalogue of all known macro / economic indicator definitions.

    One row per indicator code (e.g. ``CN_GDP``, ``CN_CPI``).
    Seed data is loaded via a data migration.
    """

    PERIOD_TYPE_CHOICES = [
        ("D", "日"),
        ("W", "周"),
        ("M", "月"),
        ("Q", "季度"),
        ("H", "半年"),
        ("Y", "年"),
    ]

    code = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        help_text="Canonical indicator code (e.g. CN_GDP)",
    )
    name_cn = models.CharField(max_length=100, help_text="中文名称")
    name_en = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    default_unit = models.CharField(max_length=20, blank=True, help_text="e.g. 亿元, %, bps")
    default_period_type = models.CharField(
        max_length=1,
        choices=PERIOD_TYPE_CHOICES,
        default="M",
    )
    category = models.CharField(
        max_length=30,
        blank=True,
        help_text="e.g. growth, inflation, money, trade, financial",
    )
    is_active = models.BooleanField(default=True)
    extra = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_indicator_catalog"
        ordering = ["code"]
        verbose_name = "Indicator Catalog"
        verbose_name_plural = "Indicator Catalog"

    def __str__(self) -> str:
        return f"{self.code} — {self.name_cn}"


class IndicatorUnitRuleModel(models.Model):
    """Canonical unit-governance rules for macro indicators.

    Rules are matched by indicator_code plus optional provider source_type.
    A blank source_type acts as the default fallback rule for the indicator.
    """

    indicator_code = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Matches IndicatorCatalogModel.code",
    )
    source_type = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Logical provider source type (e.g. akshare, tushare); blank = default rule",
    )
    dimension_key = models.CharField(
        max_length=30,
        help_text="Dimension classification such as currency, rate, index, price",
    )
    original_unit = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Provider raw unit before normalization",
    )
    storage_unit = models.CharField(
        max_length=20,
        help_text="Canonical storage unit persisted in MacroFactModel.unit",
    )
    display_unit = models.CharField(
        max_length=20,
        help_text="Frontend display unit returned by macro query APIs",
    )
    multiplier_to_storage = models.DecimalField(
        max_digits=24,
        decimal_places=8,
        default=1,
        help_text="Multiply the raw value by this factor to get canonical storage value",
    )
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=0)
    description = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_indicator_unit_rule"
        ordering = ["indicator_code", "-priority", "source_type", "original_unit"]
        verbose_name = "Indicator Unit Rule"
        verbose_name_plural = "Indicator Unit Rules"
        unique_together = [("indicator_code", "source_type", "original_unit")]
        indexes = [
            models.Index(fields=["indicator_code", "is_active"]),
            models.Index(fields=["indicator_code", "source_type", "is_active"]),
        ]

    def __str__(self) -> str:
        scope = self.source_type or "default"
        original_unit = self.original_unit or "(blank)"
        return f"{self.indicator_code}@{scope} {original_unit} -> {self.storage_unit}"


# ---------------------------------------------------------------------------
# Phase 2 — Fact tables
# ---------------------------------------------------------------------------


class MacroFactModel(models.Model):
    """Stored macro-economic data points (time-series rows).

    Composite natural key: (indicator_code, reporting_period, source).
    ``revision_number`` distinguishes subsequent revisions of the same point.
    """

    QUALITY_CHOICES = [
        ("valid", "Valid"),
        ("stale", "Stale"),
        ("estimated", "Estimated"),
        ("error", "Error"),
        ("missing", "Missing"),
    ]

    indicator_code = models.CharField(
        max_length=50,
        db_index=True,
        help_text="Matches IndicatorCatalogModel.code",
    )
    reporting_period = models.DateField(db_index=True)
    value = models.DecimalField(max_digits=28, decimal_places=6)
    unit = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=50, help_text="Provider name")
    revision_number = models.SmallIntegerField(default=0)
    published_at = models.DateField(null=True, blank=True)
    quality = models.CharField(
        max_length=10,
        choices=QUALITY_CHOICES,
        default="valid",
    )
    fetched_at = models.DateTimeField(auto_now_add=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    available_at = models.DateTimeField(null=True, blank=True, db_index=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "data_center_macro_fact"
        unique_together = [("indicator_code", "reporting_period", "source", "revision_number")]
        indexes = [
            models.Index(fields=["indicator_code", "reporting_period"]),
            models.Index(fields=["source", "reporting_period"]),
        ]
        ordering = ["-reporting_period"]
        verbose_name = "Macro Fact"
        verbose_name_plural = "Macro Facts"

    def __str__(self) -> str:
        return f"{self.indicator_code} {self.reporting_period} = {self.value}"


class PriceBarModel(models.Model):
    """Daily / intraday OHLCV price bar for a single security.

    Natural key: (asset_code, bar_date, freq, adjustment, source).
    """

    FREQ_CHOICES = [
        ("1d", "日线"),
        ("1w", "周线"),
        ("1mo", "月线"),
        ("60m", "60分钟"),
        ("30m", "30分钟"),
        ("15m", "15分钟"),
        ("5m", "5分钟"),
        ("1m", "1分钟"),
    ]

    ADJUSTMENT_CHOICES = [
        ("none", "不复权"),
        ("forward", "前复权"),
        ("backward", "后复权"),
    ]

    asset_code = models.CharField(max_length=20, db_index=True)
    bar_date = models.DateField(db_index=True)
    freq = models.CharField(max_length=5, choices=FREQ_CHOICES, default="1d")
    adjustment = models.CharField(
        max_length=10,
        choices=ADJUSTMENT_CHOICES,
        default="none",
    )
    open = models.DecimalField(max_digits=18, decimal_places=4)
    high = models.DecimalField(max_digits=18, decimal_places=4)
    low = models.DecimalField(max_digits=18, decimal_places=4)
    close = models.DecimalField(max_digits=18, decimal_places=4)
    volume = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Volume in shares",
    )
    amount = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Turnover amount in CNY",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_price_bar"
        unique_together = [("asset_code", "bar_date", "freq", "adjustment", "source")]
        indexes = [
            models.Index(fields=["asset_code", "bar_date"]),
        ]
        ordering = ["-bar_date"]
        verbose_name = "Price Bar"
        verbose_name_plural = "Price Bars"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(close__gt=0) & ~models.Q(asset_code="") & ~models.Q(source="")),
                name="dc_price_bar_executable_price",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_code} {self.bar_date} C={self.close}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate canonical price invariants before persisting a bar."""

        self.validate_constraints()
        super().save(*args, **kwargs)


class QuoteSnapshotModel(models.Model):
    """Intraday real-time quote snapshot.

    Append-only — rows are never updated, only inserted.
    Natural key: (asset_code, snapshot_at, source).
    """

    asset_code = models.CharField(max_length=20, db_index=True)
    snapshot_at = models.DateTimeField(db_index=True)
    fetched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    current_price = models.DecimalField(max_digits=18, decimal_places=4)
    open = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    high = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    low = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    prev_close = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    volume = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    amount = models.DecimalField(max_digits=24, decimal_places=2, null=True, blank=True)
    bid = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    ask = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    source = models.CharField(max_length=50)
    extra = models.JSONField(default=dict, blank=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_quote_snapshot"
        unique_together = [("asset_code", "snapshot_at", "source")]
        indexes = [
            models.Index(fields=["asset_code", "snapshot_at"]),
        ]
        ordering = ["-snapshot_at"]
        verbose_name = "Quote Snapshot"
        verbose_name_plural = "Quote Snapshots"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(current_price__gt=0) & ~models.Q(asset_code="") & ~models.Q(source="")
                ),
                name="dc_quote_executable_price",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.asset_code} @ {self.snapshot_at} = {self.current_price}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate canonical price invariants before persisting a quote."""

        self.validate_constraints()
        super().save(*args, **kwargs)


class FundNavFactModel(models.Model):
    """Fund NAV (net asset value) fact.

    Natural key: (fund_code, nav_date, source).
    """

    fund_code = models.CharField(max_length=20, db_index=True)
    nav_date = models.DateField(db_index=True)
    nav = models.DecimalField(max_digits=18, decimal_places=6, help_text="Unit NAV")
    acc_nav = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Accumulated NAV",
    )
    daily_return = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Daily return rate",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    available_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_fund_nav_fact"
        unique_together = [("fund_code", "nav_date", "source")]
        indexes = [models.Index(fields=["fund_code", "nav_date"])]
        ordering = ["-nav_date"]
        verbose_name = "Fund NAV Fact"
        verbose_name_plural = "Fund NAV Facts"
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(nav__gt=0) & ~models.Q(fund_code="") & ~models.Q(source="")),
                name="dc_fund_nav_executable_price",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.fund_code} {self.nav_date} NAV={self.nav}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate canonical price invariants before persisting a fund NAV."""

        self.validate_constraints()
        super().save(*args, **kwargs)


class FinancialFactModel(models.Model):
    """Financial statement fact (single line-item per row).

    Natural key: (asset_code, period_end, period_type, metric_code, source).
    """

    PERIOD_TYPE_CHOICES = [
        ("annual", "Annual"),
        ("semi_annual", "Semi-Annual"),
        ("quarterly", "Quarterly"),
        ("ttm", "TTM"),
    ]

    asset_code = models.CharField(max_length=20, db_index=True)
    period_end = models.DateField(db_index=True, help_text="Period end date (e.g. 2024-12-31)")
    period_type = models.CharField(max_length=15, choices=PERIOD_TYPE_CHOICES)
    metric_code = models.CharField(
        max_length=60,
        db_index=True,
        help_text="Metric identifier (e.g. revenue, net_profit, total_assets)",
    )
    value = models.DecimalField(max_digits=28, decimal_places=4)
    unit = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=50)
    report_date = models.DateField(null=True, blank=True, help_text="Date report was published")
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    announced_at = models.DateTimeField(null=True, blank=True, db_index=True)
    available_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_financial_fact"
        unique_together = [("asset_code", "period_end", "period_type", "metric_code", "source")]
        indexes = [
            models.Index(fields=["asset_code", "period_end"]),
            models.Index(fields=["metric_code"]),
        ]
        ordering = ["-period_end"]
        verbose_name = "Financial Fact"
        verbose_name_plural = "Financial Facts"

    def __str__(self) -> str:
        return f"{self.asset_code} {self.period_end} {self.metric_code}={self.value}"


class ValuationFactModel(models.Model):
    """Daily valuation multiples snapshot (PE, PB, PS, etc.).

    Natural key: (asset_code, val_date, source).
    """

    asset_code = models.CharField(max_length=20, db_index=True)
    val_date = models.DateField(db_index=True)
    pe_ttm = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    pe_static = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    pb = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    ps_ttm = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    market_cap = models.DecimalField(
        max_digits=28,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Market cap in CNY",
    )
    float_market_cap = models.DecimalField(
        max_digits=28,
        decimal_places=2,
        null=True,
        blank=True,
    )
    dv_ratio = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Dividend yield",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    available_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_valuation_fact"
        unique_together = [("asset_code", "val_date", "source")]
        indexes = [models.Index(fields=["asset_code", "val_date"])]
        ordering = ["-val_date"]
        verbose_name = "Valuation Fact"
        verbose_name_plural = "Valuation Facts"

    def __str__(self) -> str:
        return f"{self.asset_code} {self.val_date} PE={self.pe_ttm}"


class SectorMembershipFactModel(models.Model):
    """Sector / index constituent membership record.

    Natural key: (asset_code, sector_code, effective_date).
    ``expiry_date`` is null for currently active memberships.
    """

    asset_code = models.CharField(max_length=20, db_index=True)
    sector_code = models.CharField(
        max_length=30,
        db_index=True,
        help_text="Industry / index code (e.g. 399300.SZ for CSI 300)",
    )
    sector_name = models.CharField(max_length=100, blank=True)
    effective_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True, help_text="Null = currently active")
    weight = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Weight in index (0–1)",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_sector_membership"
        unique_together = [("asset_code", "sector_code", "effective_date")]
        indexes = [
            models.Index(fields=["sector_code", "effective_date"]),
            models.Index(fields=["asset_code", "effective_date"]),
        ]
        ordering = ["-effective_date"]
        verbose_name = "Sector Membership"
        verbose_name_plural = "Sector Memberships"

    def __str__(self) -> str:
        return f"{self.asset_code} ∈ {self.sector_code} ({self.effective_date})"


class NewsFactModel(models.Model):
    """News article associated with a stock or sector.

    ``external_id`` is the provider-side article identifier; combined with
    ``source`` it forms a dedup key.
    """

    asset_code = models.CharField(
        max_length=20,
        blank=True,
        db_index=True,
        help_text="Primary associated ticker (blank = market-wide news)",
    )
    title = models.CharField(max_length=500)
    summary = models.TextField(blank=True)
    url = models.URLField(max_length=1000, blank=True)
    published_at = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=50)
    external_id = models.CharField(max_length=200, blank=True, help_text="Provider article ID")
    sentiment_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Sentiment score in [-1, +1]",
    )
    extra = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    available_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_news_fact"
        unique_together = [("source", "external_id")]
        indexes = [
            models.Index(fields=["asset_code", "published_at"]),
            models.Index(fields=["published_at"]),
        ]
        ordering = ["-published_at"]
        verbose_name = "News Article"
        verbose_name_plural = "News Articles"

    def __str__(self) -> str:
        return f"[{self.source}] {self.title[:60]}"


class CapitalFlowFactModel(models.Model):
    """Capital-flow data: main-force / retail net inflows per security per day.

    Natural key: (asset_code, flow_date, source).
    """

    asset_code = models.CharField(max_length=20, db_index=True)
    flow_date = models.DateField(db_index=True)
    main_net = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Main-force net inflow (CNY)",
    )
    retail_net = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Retail net inflow (CNY)",
    )
    super_large_net = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
    )
    large_net = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
    )
    medium_net = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
    )
    small_net = models.DecimalField(
        max_digits=24,
        decimal_places=2,
        null=True,
        blank=True,
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)
    contract_version = models.CharField(max_length=40, default="1.0")
    schema_version = models.CharField(max_length=40, default="1.0")
    source_record_id = models.CharField(max_length=200, blank=True)
    raw_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    quality_status = models.CharField(max_length=40, default="accepted", db_index=True)
    revision_number = models.PositiveSmallIntegerField(default=1)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_capital_flow_fact"
        unique_together = [("asset_code", "flow_date", "source")]
        indexes = [models.Index(fields=["asset_code", "flow_date"])]
        ordering = ["-flow_date"]
        verbose_name = "Capital Flow Fact"
        verbose_name_plural = "Capital Flow Facts"

    def __str__(self) -> str:
        return f"{self.asset_code} {self.flow_date} main_net={self.main_net}"


# ---------------------------------------------------------------------------
# Market thermometer persistence
# ---------------------------------------------------------------------------


class MarketThermometerConfigModel(models.Model):
    """Singleton configuration for market thermometer scoring."""

    _SINGLETON_PK = 1

    short_window = models.PositiveIntegerField(default=5)
    medium_window = models.PositiveIntegerField(default=20)
    long_window = models.PositiveIntegerField(default=252)
    monthly_long_window = models.PositiveIntegerField(default=24)
    daily_stale_days = models.PositiveIntegerField(default=3)
    monthly_stale_days = models.PositiveIntegerField(default=45)
    min_valid_components = models.PositiveIntegerField(default=4)
    component_weights = models.JSONField(
        default=dict,
        blank=True,
        help_text="Component weights keyed by component_key",
    )
    warm_threshold = models.FloatField(default=35.0)
    hot_threshold = models.FloatField(default=60.0)
    overheat_threshold = models.FloatField(default=75.0)
    extreme_threshold = models.FloatField(default=85.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_market_thermometer_config"
        verbose_name = "Market Thermometer Config"
        verbose_name_plural = "Market Thermometer Config"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist the singleton config at primary key 1."""

        self.pk = self._SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "MarketThermometerConfigModel":
        """Return the singleton config, creating it with defaults if absent."""

        obj, _ = cls.objects.get_or_create(
            pk=cls._SINGLETON_PK,
            defaults={
                "component_weights": {
                    "turnover": 0.25,
                    "margin_balance": 0.20,
                    "new_investor_accounts": 0.15,
                    "etf_net_flow": 0.15,
                    "market_news_count": 0.15,
                    "market_news_sentiment": 0.10,
                }
            },
        )
        return obj

    def to_domain(self) -> MarketThermometerConfig:
        """Convert to domain MarketThermometerConfig value object."""

        return MarketThermometerConfig(
            short_window=self.short_window,
            medium_window=self.medium_window,
            long_window=self.long_window,
            monthly_long_window=self.monthly_long_window,
            daily_stale_days=self.daily_stale_days,
            monthly_stale_days=self.monthly_stale_days,
            min_valid_components=self.min_valid_components,
            component_weights=dict(self.component_weights or {}),
            thresholds=MarketThermometerThresholds(
                warm_threshold=float(self.warm_threshold),
                hot_threshold=float(self.hot_threshold),
                overheat_threshold=float(self.overheat_threshold),
                extreme_threshold=float(self.extreme_threshold),
            ),
        )


class MarketThermometerUserOverrideModel(models.Model):
    """Per-user threshold override for market thermometer interpretation."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="market_thermometer_override",
    )
    warm_threshold = models.FloatField(default=35.0)
    hot_threshold = models.FloatField(default=60.0)
    overheat_threshold = models.FloatField(default=75.0)
    extreme_threshold = models.FloatField(default=85.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_market_thermometer_user_override"
        verbose_name = "Market Thermometer User Override"
        verbose_name_plural = "Market Thermometer User Overrides"

    def to_domain(self) -> MarketThermometerUserOverride:
        """Convert to domain MarketThermometerUserOverride value object."""

        return MarketThermometerUserOverride(
            user_id=int(self.user_id),
            thresholds=MarketThermometerThresholds(
                warm_threshold=float(self.warm_threshold),
                hot_threshold=float(self.hot_threshold),
                overheat_threshold=float(self.overheat_threshold),
                extreme_threshold=float(self.extreme_threshold),
            ),
        )


class MarketThermometerSnapshotModel(models.Model):
    """One persisted market thermometer snapshot per observed date."""

    observed_at = models.DateField(unique=True, db_index=True)
    score = models.FloatField()
    band = models.CharField(max_length=20, db_index=True)
    change_5d = models.FloatField(null=True, blank=True)
    change_20d = models.FloatField(null=True, blank=True)
    components = models.JSONField(default=list, blank=True)
    trigger_reasons = models.JSONField(default=list, blank=True)
    stale_components = models.JSONField(default=list, blank=True)
    missing_components = models.JSONField(default=list, blank=True)
    valid_component_count = models.PositiveIntegerField(default=0)
    data_source = models.CharField(max_length=20, default="calculated")
    must_not_use_for_decision = models.BooleanField(default=False)
    blocked_reason = models.TextField(blank=True, default="")
    calculated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_market_thermometer_snapshot"
        ordering = ["-observed_at"]
        verbose_name = "Market Thermometer Snapshot"
        verbose_name_plural = "Market Thermometer Snapshots"
        indexes = [
            models.Index(fields=["band", "observed_at"]),
        ]

    def to_domain(self) -> MarketThermometerSnapshot:
        """Convert to domain MarketThermometerSnapshot value object."""

        components: list[MarketThermometerComponentScore] = []
        for item in self.components or []:
            if isinstance(item, dict):
                components.append(
                    MarketThermometerComponentScore(
                        component_key=str(item.get("component_key", "")),
                        label=str(item.get("label", "")),
                        indicator_code=str(item.get("indicator_code", "")),
                        score=_required_json_float(item.get("score", 0.0), "component.score"),
                        weight=_required_json_float(item.get("weight", 0.0), "component.weight"),
                        current_value=_optional_json_float(
                            item.get("current_value"), "component.current_value"
                        ),
                        unit=str(item.get("unit", "")),
                        growth_score=_optional_json_float(
                            item.get("growth_score"), "component.growth_score"
                        ),
                        percentile_score=_optional_json_float(
                            item.get("percentile_score"), "component.percentile_score"
                        ),
                        sentiment_score=_optional_json_float(
                            item.get("sentiment_score"), "component.sentiment_score"
                        ),
                        positive_ratio_score=_optional_json_float(
                            item.get("positive_ratio_score"),
                            "component.positive_ratio_score",
                        ),
                        is_stale=_json_bool(item.get("is_stale", False), "component.is_stale"),
                        is_missing=_json_bool(
                            item.get("is_missing", False), "component.is_missing"
                        ),
                        age_days=_optional_json_nonnegative_int(
                            item.get("age_days"), "component.age_days"
                        ),
                        reason=str(item.get("reason", "")),
                    )
                )

        return MarketThermometerSnapshot(
            observed_at=self.observed_at,
            score=float(self.score),
            band=self.band,
            change_5d=float(self.change_5d) if self.change_5d is not None else None,
            change_20d=float(self.change_20d) if self.change_20d is not None else None,
            components=components,
            trigger_reasons=[str(item) for item in (self.trigger_reasons or [])],
            stale_components=[str(item) for item in (self.stale_components or [])],
            missing_components=[str(item) for item in (self.missing_components or [])],
            valid_component_count=int(self.valid_component_count),
            data_source=self.data_source,
            must_not_use_for_decision=bool(self.must_not_use_for_decision),
            blocked_reason=self.blocked_reason,
            calculated_at=self.calculated_at,
        )


# ---------------------------------------------------------------------------
# Phase 2 — Raw fetch audit log
# ---------------------------------------------------------------------------


class RawAuditModel(models.Model):
    """Append-only log of every raw data fetch attempt.

    Enables data lineage, debugging, and replay support.
    """

    STATUS_CHOICES = [
        ("ok", "OK"),
        ("error", "Error"),
        ("timeout", "Timeout"),
        ("skipped", "Skipped"),
    ]

    provider_name = models.CharField(max_length=50, db_index=True)
    capability = models.CharField(
        max_length=30,
        db_index=True,
        help_text="DataCapability value (e.g. 'macro', 'historical_price')",
    )
    request_params = models.JSONField(default=dict, blank=True)
    request_params_hash = models.CharField(max_length=128, blank=True, db_index=True)
    response_payload_hash = models.CharField(max_length=128, blank=True, db_index=True)
    schema_fingerprint = models.CharField(max_length=128, blank=True, db_index=True)
    redacted = models.BooleanField(default=True)
    parser_version = models.CharField(max_length=40, blank=True)
    payload_size_bytes = models.PositiveBigIntegerField(default=0)
    retention_until = models.DateTimeField(null=True, blank=True, db_index=True)
    ingested_run_id = models.UUIDField(null=True, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    row_count = models.IntegerField(default=0, help_text="Number of rows fetched")
    latency_ms = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    fetched_at = models.DateTimeField(db_index=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "data_center_raw_audit"
        indexes = [
            models.Index(fields=["provider_name", "fetched_at"]),
            models.Index(fields=["capability", "fetched_at"]),
        ]
        ordering = ["-fetched_at"]
        verbose_name = "Raw Audit Log"
        verbose_name_plural = "Raw Audit Logs"

    def __str__(self) -> str:
        return f"{self.provider_name}/{self.capability} {self.fetched_at} [{self.status}]"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Reject audit rows that claim to retain unredacted provider data."""

        if not self.redacted:
            raise ValidationError("Raw audit must be marked redacted before persistence")
        super().save(*args, **kwargs)


class RawPayloadModel(models.Model):
    """Hash-addressed, redacted raw provider payload."""

    payload_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    provider_name = models.CharField(max_length=100, db_index=True)
    payload_hash = models.CharField(max_length=128, unique=True, db_index=True)
    schema_fingerprint = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField(default=dict)
    request_params = models.JSONField(default=dict, blank=True)
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    content_type = models.CharField(max_length=80, default="application/json")
    parser_version = models.CharField(max_length=40, blank=True)
    redacted = models.BooleanField(default=True)
    payload_size_bytes = models.PositiveBigIntegerField(default=0)
    fetched_at = models.DateTimeField(db_index=True)
    retention_until = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_raw_payload"
        ordering = ["-fetched_at"]
        indexes = [
            models.Index(fields=["dataset_key", "fetched_at"]),
            models.Index(fields=["provider_name", "schema_fingerprint"]),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Reject raw payloads that were not marked redacted."""

        if not self.redacted:
            raise ValidationError("Raw payload must be redacted before persistence")
        super().save(*args, **kwargs)

    def to_domain(self) -> RawPayload:
        """Convert the persisted raw payload to a domain object."""

        return RawPayload(
            payload_id=str(self.payload_id),
            dataset_key=self.dataset_key,
            provider_name=self.provider_name,
            payload_hash=self.payload_hash,
            schema_fingerprint=self.schema_fingerprint,
            payload=self.payload or {},
            fetched_at=self.fetched_at,
            request_params=self.request_params or {},
            run_id=str(self.run_id) if self.run_id else "",
            batch_id=str(self.batch_id) if self.batch_id else "",
            content_type=self.content_type,
            parser_version=self.parser_version,
            redacted=self.redacted,
            payload_size_bytes=int(self.payload_size_bytes),
            retention_until=self.retention_until,
        )


class SchemaFingerprintModel(models.Model):
    """Observed provider schema signature and evolution evidence."""

    fingerprint = models.CharField(max_length=128, primary_key=True)
    dataset_key = models.CharField(max_length=160, db_index=True)
    provider_name = models.CharField(max_length=100, db_index=True)
    fields = models.JSONField(default=list)
    parser_version = models.CharField(max_length=40, blank=True)
    first_seen_at = models.DateTimeField(db_index=True)
    last_seen_at = models.DateTimeField(db_index=True)
    sample_count = models.PositiveBigIntegerField(default=1)

    class Meta:
        db_table = "data_center_schema_fingerprint"
        ordering = ["-last_seen_at"]
        indexes = [models.Index(fields=["dataset_key", "provider_name", "last_seen_at"])]

    def to_domain(self) -> SchemaFingerprint:
        """Convert the persisted schema signature to a domain object."""

        return SchemaFingerprint(
            fingerprint=self.fingerprint,
            dataset_key=self.dataset_key,
            provider_name=self.provider_name,
            fields=tuple(str(item) for item in (self.fields or [])),
            parser_version=self.parser_version,
            first_seen_at=self.first_seen_at,
            last_seen_at=self.last_seen_at,
            sample_count=int(self.sample_count),
        )


class RetentionPolicyModel(models.Model):
    """Versioned Data Center dataset retention rule."""

    policy_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    version = models.PositiveIntegerField()
    retention_days = models.PositiveIntegerField()
    archive_after_days = models.PositiveIntegerField(null=True, blank=True)
    archive_retention_days = models.PositiveIntegerField(null=True, blank=True)
    priority = models.CharField(max_length=20, default="normal")
    active = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_retention_policy"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset_key", "version"], name="dc_retention_dataset_version_unique"
            ),
            models.UniqueConstraint(
                fields=["dataset_key"],
                condition=models.Q(active=True),
                name="dc_retention_one_active_per_dataset",
            ),
        ]
        indexes = [models.Index(fields=["dataset_key", "active"])]

    def to_domain(self) -> RetentionPolicy:
        """Convert the retention row to a domain policy."""

        return RetentionPolicy(
            policy_id=str(self.policy_id),
            dataset_key=self.dataset_key,
            version=self.version,
            retention_days=self.retention_days,
            archive_after_days=self.archive_after_days,
            archive_retention_days=self.archive_retention_days,
            priority=self.priority,
            active=self.active,
        )


class StorageHoldModel(models.Model):
    """Non-destructive deletion hold for a dataset, run or archive."""

    hold_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    resource_type = models.CharField(max_length=60, db_index=True)
    resource_key = models.CharField(max_length=240, db_index=True)
    reason = models.TextField()
    created_by = models.CharField(max_length=150)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "data_center_storage_hold"
        indexes = [models.Index(fields=["resource_type", "resource_key", "released_at"])]

    def to_domain(self) -> StorageHold:
        """Convert the hold row to a domain hold."""

        return StorageHold(
            hold_id=str(self.hold_id),
            resource_type=self.resource_type,
            resource_key=self.resource_key,
            reason=self.reason,
            created_by=self.created_by,
            created_at=self.created_at,
            expires_at=self.expires_at,
            released_at=self.released_at,
        )


class ArchiveManifestModel(models.Model):
    """Checksum-verified archive evidence."""

    ARCHIVE_STATE_CHOICES = [(item.value, item.value) for item in ArchiveState]

    archive_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    object_count = models.PositiveBigIntegerField(default=0)
    size_bytes = models.PositiveBigIntegerField(default=0)
    location = models.CharField(max_length=500)
    checksum = models.CharField(max_length=128, db_index=True)
    state = models.CharField(
        max_length=20,
        choices=ARCHIVE_STATE_CHOICES,
        default=ArchiveState.PLANNED.value,
        db_index=True,
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateTimeField(null=True, blank=True, db_index=True)
    contract_version = models.CharField(max_length=40, blank=True)
    schema_version = models.CharField(max_length=40, blank=True)
    format_version = models.CharField(
        max_length=80,
        default="raw-payload-fernet-jsonl-gzip-v1",
    )
    encryption_algorithm = models.CharField(max_length=40, blank=True)
    encryption_key_ref = models.CharField(max_length=160, blank=True)
    encryption_key_version = models.CharField(max_length=80, blank=True)
    coverage_started_at = models.DateTimeField(null=True, blank=True, db_index=True)
    coverage_ended_at = models.DateTimeField(null=True, blank=True, db_index=True)
    restore_outcome = models.CharField(
        max_length=20,
        choices=[(item.value, item.value) for item in ArchiveRestoreOutcome],
        default=ArchiveRestoreOutcome.NOT_TESTED.value,
        db_index=True,
    )
    last_restored_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = "data_center_archive_manifest"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["dataset_key", "state", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(coverage_started_at__isnull=True, coverage_ended_at__isnull=True)
                    | models.Q(
                        coverage_started_at__isnull=False,
                        coverage_ended_at__isnull=False,
                    )
                ),
                name="dc_archive_coverage_pair",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(coverage_started_at__isnull=True)
                    | models.Q(coverage_ended_at__gte=models.F("coverage_started_at"))
                ),
                name="dc_archive_coverage_order",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(state=ArchiveState.VERIFIED.value)
                    | models.Q(verified_at__isnull=False)
                ),
                name="dc_archive_verified_at_required",
            ),
            models.CheckConstraint(
                condition=(
                    ~models.Q(restore_outcome=ArchiveRestoreOutcome.SUCCESS.value)
                    | models.Q(last_restored_at__isnull=False)
                ),
                name="dc_archive_restore_time_required",
            ),
        ]

    def to_domain(self) -> ArchiveManifest:
        """Convert the archive evidence row to a domain manifest."""

        return ArchiveManifest(
            archive_id=str(self.archive_id),
            dataset_key=self.dataset_key,
            object_count=int(self.object_count),
            size_bytes=int(self.size_bytes),
            location=self.location,
            checksum=self.checksum,
            state=ArchiveState(self.state),
            created_at=self.created_at,
            verified_at=self.verified_at,
            retention_until=self.retention_until,
            contract_version=self.contract_version,
            schema_version=self.schema_version,
            format_version=self.format_version,
            encryption_algorithm=self.encryption_algorithm,
            encryption_key_ref=self.encryption_key_ref,
            encryption_key_version=self.encryption_key_version,
            coverage_started_at=self.coverage_started_at,
            coverage_ended_at=self.coverage_ended_at,
            restore_outcome=ArchiveRestoreOutcome(self.restore_outcome),
            last_restored_at=self.last_restored_at,
        )


# ---------------------------------------------------------------------------
# Phase 3 — Ingestion control plane and canonical publication
# ---------------------------------------------------------------------------


class SyncRunModel(models.Model):
    """One resumable dataset ingestion run.

    The run is deliberately independent from Celery's task result.  A task may
    be retried while this record preserves business outcome and item counts.
    """

    STATUS_CHOICES = [(item.value, item.value) for item in SyncRunStatus]
    OUTCOME_CHOICES = [(item, item) for item in ("success", "partial", "noop", "blocked", "failed")]

    run_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    trigger = models.CharField(max_length=40)
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=SyncRunStatus.REQUESTED.value
    )
    outcome = models.CharField(max_length=16, choices=OUTCOME_CHOICES, default="blocked")
    provider_name = models.CharField(max_length=100, blank=True, db_index=True)
    contract_version = models.CharField(max_length=40, blank=True)
    config_snapshot_hash = models.CharField(max_length=128, blank=True)
    requested = models.PositiveIntegerField(default=0)
    fetched = models.PositiveIntegerField(default=0)
    validated = models.PositiveIntegerField(default=0)
    quarantined = models.PositiveIntegerField(default=0)
    succeeded = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    stored = models.PositiveIntegerField(default=0)
    published = models.PositiveIntegerField(default=0)
    unchanged = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_sync_run"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["dataset_key", "started_at"]),
            models.Index(fields=["status", "outcome"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stored__gte=0), name="dc_sync_run_stored_nonnegative"
            ),
            models.CheckConstraint(
                condition=models.Q(published__gte=0), name="dc_sync_run_published_nonnegative"
            ),
        ]

    def to_domain(self) -> SyncRun:
        """Convert the persisted record to its immutable domain value object."""

        return SyncRun(
            run_id=str(self.run_id),
            dataset_key=self.dataset_key,
            trigger=self.trigger,
            status=SyncRunStatus(self.status),
            outcome=self.outcome,
            requested=self.requested,
            fetched=self.fetched,
            validated=self.validated,
            quarantined=self.quarantined,
            succeeded=self.succeeded,
            failed=self.failed,
            stored=self.stored,
            published=self.published,
            unchanged=self.unchanged,
            provider_name=self.provider_name,
            contract_version=self.contract_version,
            config_snapshot_hash=self.config_snapshot_hash,
            started_at=self.started_at,
            finished_at=self.finished_at,
            error_code=self.error_code,
            error_message=self.error_message,
        )


class SyncBatchModel(models.Model):
    """Bounded provider/dataset slice in a :class:`SyncRunModel`."""

    STATE_CHOICES = [(item.value, item.value) for item in SyncItemState]

    batch_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_id = models.UUIDField(db_index=True)
    dataset_key = models.CharField(max_length=160, db_index=True)
    provider_name = models.CharField(max_length=100, db_index=True)
    idempotency_key = models.CharField(max_length=240, unique=True)
    state = models.CharField(
        max_length=20, choices=STATE_CHOICES, default=SyncItemState.PENDING.value
    )
    requested = models.PositiveIntegerField(default=0)
    fetched = models.PositiveIntegerField(default=0)
    validated = models.PositiveIntegerField(default=0)
    quarantined = models.PositiveIntegerField(default=0)
    succeeded = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    stored = models.PositiveIntegerField(default=0)
    published = models.PositiveIntegerField(default=0)
    window_start = models.DateField(null=True, blank=True)
    window_end = models.DateField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "data_center_sync_batch"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["run_id", "dataset_key"]),
            models.Index(fields=["provider_name", "state"]),
        ]

    def to_domain(self) -> SyncBatch:
        """Convert the persisted record to a domain batch."""

        return SyncBatch(
            batch_id=str(self.batch_id),
            run_id=str(self.run_id),
            dataset_key=self.dataset_key,
            provider_name=self.provider_name,
            idempotency_key=self.idempotency_key,
            state=SyncItemState(self.state),
            requested=self.requested,
            fetched=self.fetched,
            validated=self.validated,
            quarantined=self.quarantined,
            succeeded=self.succeeded,
            failed=self.failed,
            stored=self.stored,
            published=self.published,
            window_start=self.window_start,
            window_end=self.window_end,
            started_at=self.started_at,
            finished_at=self.finished_at,
            error_code=self.error_code,
            error_message=self.error_message,
        )


class SyncCheckpointModel(models.Model):
    """Durable cursor for resuming a failed or interrupted batch."""

    STATE_CHOICES = [(item.value, item.value) for item in SyncItemState]

    checkpoint_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_id = models.UUIDField(db_index=True)
    batch_id = models.UUIDField(db_index=True)
    cursor_name = models.CharField(max_length=100)
    cursor_value = models.CharField(max_length=500)
    state = models.CharField(
        max_length=20, choices=STATE_CHOICES, default=SyncItemState.SUCCEEDED.value
    )
    processed = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    recorded_at = models.DateTimeField(db_index=True)
    error_code = models.CharField(max_length=80, blank=True)

    class Meta:
        db_table = "data_center_sync_checkpoint"
        ordering = ["-recorded_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch_id", "cursor_name", "cursor_value"],
                name="dc_checkpoint_batch_cursor_unique",
            ),
        ]
        indexes = [models.Index(fields=["run_id", "batch_id", "recorded_at"])]

    def to_domain(self) -> SyncCheckpoint:
        """Convert the persisted cursor to a domain checkpoint."""

        return SyncCheckpoint(
            checkpoint_id=str(self.checkpoint_id),
            run_id=str(self.run_id),
            batch_id=str(self.batch_id),
            cursor_name=self.cursor_name,
            cursor_value=self.cursor_value,
            state=SyncItemState(self.state),
            processed=self.processed,
            failed=self.failed,
            recorded_at=self.recorded_at,
            error_code=self.error_code,
        )


class QuarantineRecordModel(models.Model):
    """Payload rejected by a Dataset Contract or reconciliation policy."""

    RESOLUTION_CHOICES = [(item.value, item.value) for item in QuarantineResolution]

    quarantine_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    dataset_key = models.CharField(max_length=160, db_index=True)
    provider_name = models.CharField(max_length=100, db_index=True)
    natural_key = models.CharField(max_length=300, db_index=True)
    reason_code = models.CharField(max_length=100, db_index=True)
    reason = models.TextField()
    payload_hash = models.CharField(max_length=128, db_index=True)
    schema_fingerprint = models.CharField(max_length=128, db_index=True)
    payload = models.JSONField(default=dict)
    observed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    run_id = models.UUIDField(null=True, blank=True, db_index=True)
    batch_id = models.UUIDField(null=True, blank=True, db_index=True)
    resolution = models.CharField(
        max_length=20, choices=RESOLUTION_CHOICES, default=QuarantineResolution.OPEN.value
    )
    quarantined_at = models.DateTimeField(db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "data_center_quarantine_record"
        ordering = ["-quarantined_at"]
        indexes = [
            models.Index(fields=["dataset_key", "resolution"]),
            models.Index(fields=["provider_name", "reason_code"]),
        ]

    def to_domain(self) -> QuarantineRecord:
        """Convert the persisted rejected payload to a domain record."""

        return QuarantineRecord(
            quarantine_id=str(self.quarantine_id),
            dataset_key=self.dataset_key,
            provider_name=self.provider_name,
            natural_key=self.natural_key,
            reason_code=self.reason_code,
            reason=self.reason,
            payload_hash=self.payload_hash,
            schema_fingerprint=self.schema_fingerprint,
            payload=self.payload or {},
            observed_at=self.observed_at,
            run_id=str(self.run_id) if self.run_id else "",
            batch_id=str(self.batch_id) if self.batch_id else "",
            resolution=QuarantineResolution(self.resolution),
            quarantined_at=self.quarantined_at,
            resolved_at=self.resolved_at,
            resolved_by=self.resolved_by,
        )
