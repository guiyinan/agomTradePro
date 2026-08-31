"""
Data Center — Infrastructure Layer ORM Models

Phase 1: Unified provider configuration and global settings for all data domains.
Phase 2: Master data (AssetMasterModel, IndicatorCatalogModel) and eight fact tables
         (MacroFactModel, PriceBarModel, QuoteSnapshotModel, FundNavFactModel,
          FinancialFactModel, ValuationFactModel, SectorMembershipFactModel,
          NewsFactModel, CapitalFlowFactModel) plus RawAuditModel.
"""

from typing import Any

from django.db import models

from apps.data_center.domain.entities import (
    ProductionCoverageUniverseConfig,
    ProviderConfig,
    PublisherCatalog,
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


from . import fact_and_operational_models as _split_models  # noqa: E402

ArchiveManifestModel = _split_models.ArchiveManifestModel
CapitalFlowFactModel = _split_models.CapitalFlowFactModel
MarketThermometerConfigModel = _split_models.MarketThermometerConfigModel
MarketThermometerSnapshotModel = _split_models.MarketThermometerSnapshotModel
MarketThermometerUserOverrideModel = _split_models.MarketThermometerUserOverrideModel
NewsFactModel = _split_models.NewsFactModel
QuarantineRecordModel = _split_models.QuarantineRecordModel
RawAuditModel = _split_models.RawAuditModel
RawPayloadModel = _split_models.RawPayloadModel
RetentionPolicyModel = _split_models.RetentionPolicyModel
SchemaFingerprintModel = _split_models.SchemaFingerprintModel
SectorMembershipFactModel = _split_models.SectorMembershipFactModel
StorageHoldModel = _split_models.StorageHoldModel
SyncBatchModel = _split_models.SyncBatchModel
SyncCheckpointModel = _split_models.SyncCheckpointModel
SyncExecutionIdentityModel = _split_models.SyncExecutionIdentityModel
SyncRunModel = _split_models.SyncRunModel
ValuationFactModel = _split_models.ValuationFactModel
