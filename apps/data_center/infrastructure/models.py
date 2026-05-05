"""
Data Center — Infrastructure Layer ORM Models

Phase 1: Unified provider configuration and global settings for all data domains.
Phase 2: Master data (AssetMasterModel, IndicatorCatalogModel) and eight fact tables
         (MacroFactModel, PriceBarModel, QuoteSnapshotModel, FundNavFactModel,
          FinancialFactModel, ValuationFactModel, SectorMembershipFactModel,
          NewsFactModel, CapitalFlowFactModel) plus RawAuditModel.
"""

from django.db import models


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
    extra_config = models.JSONField(default=dict, blank=True, help_text="Provider-specific parameters")

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

    def to_domain(self):
        """Convert to domain ProviderConfig value object."""
        from apps.data_center.domain.entities import ProviderConfig

        return ProviderConfig(
            id=self.pk,
            name=self.name,
            source_type=self.source_type,
            is_active=self.is_active,
            priority=self.priority,
            api_key=self.api_key,
            api_secret=self.api_secret,
            http_url=self.http_url,
            api_endpoint=self.api_endpoint,
            extra_config=self.extra_config or {},
            description=self.description,
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

    _SINGLETON_PK = 1

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

    def save(self, *args, **kwargs) -> None:  # type: ignore[override]
        """Enforce singleton — always use pk=1."""
        self.pk = self._SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "DataProviderSettingsModel":
        """Return singleton, creating with defaults if absent."""
        obj, _ = cls.objects.get_or_create(
            pk=cls._SINGLETON_PK,
            defaults={
                "default_source": "akshare",
                "enable_failover": True,
                "failover_tolerance": 0.01,
            },
        )
        return obj

    def to_domain(self):
        """Convert to domain DataProviderSettings value object."""
        from apps.data_center.domain.entities import DataProviderSettings

        return DataProviderSettings(
            default_source=self.default_source,
            enable_failover=self.enable_failover,
            failover_tolerance=self.failover_tolerance,
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
        max_length=20, unique=True, db_index=True,
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
        max_digits=24, decimal_places=2, null=True, blank=True,
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
        AssetMasterModel, on_delete=models.CASCADE, related_name="aliases",
    )
    provider_name = models.CharField(
        max_length=50, help_text="Provider identifier (e.g. 'akshare', 'wind')",
    )
    alias_code = models.CharField(
        max_length=40, help_text="Provider-local ticker code",
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

    def to_domain(self):
        """Convert to domain PublisherCatalog value object."""
        from apps.data_center.domain.entities import PublisherCatalog

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
        max_length=50, unique=True, db_index=True,
        help_text="Canonical indicator code (e.g. CN_GDP)",
    )
    name_cn = models.CharField(max_length=100, help_text="中文名称")
    name_en = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    default_unit = models.CharField(max_length=20, blank=True, help_text="e.g. 亿元, %, bps")
    default_period_type = models.CharField(
        max_length=1, choices=PERIOD_TYPE_CHOICES, default="M",
    )
    category = models.CharField(
        max_length=30, blank=True,
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
        max_length=50, db_index=True,
        help_text="Matches IndicatorCatalogModel.code",
    )
    reporting_period = models.DateField(db_index=True)
    value = models.DecimalField(max_digits=28, decimal_places=6)
    unit = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=50, help_text="Provider name")
    revision_number = models.SmallIntegerField(default=0)
    published_at = models.DateField(null=True, blank=True)
    quality = models.CharField(
        max_length=10, choices=QUALITY_CHOICES, default="valid",
    )
    fetched_at = models.DateTimeField(auto_now_add=True)
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
        max_length=10, choices=ADJUSTMENT_CHOICES, default="none",
    )
    open = models.DecimalField(max_digits=18, decimal_places=4)
    high = models.DecimalField(max_digits=18, decimal_places=4)
    low = models.DecimalField(max_digits=18, decimal_places=4)
    close = models.DecimalField(max_digits=18, decimal_places=4)
    volume = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True,
        help_text="Volume in shares",
    )
    amount = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True,
        help_text="Turnover amount in CNY",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "data_center_price_bar"
        unique_together = [("asset_code", "bar_date", "freq", "adjustment", "source")]
        indexes = [
            models.Index(fields=["asset_code", "bar_date"]),
        ]
        ordering = ["-bar_date"]
        verbose_name = "Price Bar"
        verbose_name_plural = "Price Bars"

    def __str__(self) -> str:
        return f"{self.asset_code} {self.bar_date} C={self.close}"


class QuoteSnapshotModel(models.Model):
    """Intraday real-time quote snapshot.

    Append-only — rows are never updated, only inserted.
    Natural key: (asset_code, snapshot_at, source).
    """

    asset_code = models.CharField(max_length=20, db_index=True)
    snapshot_at = models.DateTimeField(db_index=True)
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

    class Meta:
        db_table = "data_center_quote_snapshot"
        unique_together = [("asset_code", "snapshot_at", "source")]
        indexes = [
            models.Index(fields=["asset_code", "snapshot_at"]),
        ]
        ordering = ["-snapshot_at"]
        verbose_name = "Quote Snapshot"
        verbose_name_plural = "Quote Snapshots"

    def __str__(self) -> str:
        return f"{self.asset_code} @ {self.snapshot_at} = {self.current_price}"


class FundNavFactModel(models.Model):
    """Fund NAV (net asset value) fact.

    Natural key: (fund_code, nav_date, source).
    """

    fund_code = models.CharField(max_length=20, db_index=True)
    nav_date = models.DateField(db_index=True)
    nav = models.DecimalField(max_digits=18, decimal_places=6, help_text="Unit NAV")
    acc_nav = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True,
        help_text="Accumulated NAV",
    )
    daily_return = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True,
        help_text="Daily return rate",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "data_center_fund_nav_fact"
        unique_together = [("fund_code", "nav_date", "source")]
        indexes = [models.Index(fields=["fund_code", "nav_date"])]
        ordering = ["-nav_date"]
        verbose_name = "Fund NAV Fact"
        verbose_name_plural = "Fund NAV Facts"

    def __str__(self) -> str:
        return f"{self.fund_code} {self.nav_date} NAV={self.nav}"


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
        max_length=60, db_index=True,
        help_text="Metric identifier (e.g. revenue, net_profit, total_assets)",
    )
    value = models.DecimalField(max_digits=28, decimal_places=4)
    unit = models.CharField(max_length=20, blank=True)
    source = models.CharField(max_length=50)
    report_date = models.DateField(null=True, blank=True, help_text="Date report was published")
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)

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
        max_digits=28, decimal_places=2, null=True, blank=True,
        help_text="Market cap in CNY",
    )
    float_market_cap = models.DecimalField(
        max_digits=28, decimal_places=2, null=True, blank=True,
    )
    dv_ratio = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True,
        help_text="Dividend yield",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)

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
        max_length=30, db_index=True,
        help_text="Industry / index code (e.g. 399300.SZ for CSI 300)",
    )
    sector_name = models.CharField(max_length=100, blank=True)
    effective_date = models.DateField()
    expiry_date = models.DateField(null=True, blank=True, help_text="Null = currently active")
    weight = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True,
        help_text="Weight in index (0–1)",
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)

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
        max_length=20, blank=True, db_index=True,
        help_text="Primary associated ticker (blank = market-wide news)",
    )
    title = models.CharField(max_length=500)
    summary = models.TextField(blank=True)
    url = models.URLField(max_length=1000, blank=True)
    published_at = models.DateTimeField(db_index=True)
    source = models.CharField(max_length=50)
    external_id = models.CharField(max_length=200, blank=True, help_text="Provider article ID")
    sentiment_score = models.FloatField(
        null=True, blank=True, help_text="Sentiment score in [-1, +1]",
    )
    extra = models.JSONField(default=dict, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True)

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
        max_digits=24, decimal_places=2, null=True, blank=True,
        help_text="Main-force net inflow (CNY)",
    )
    retail_net = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True,
        help_text="Retail net inflow (CNY)",
    )
    super_large_net = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True,
    )
    large_net = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True,
    )
    medium_net = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True,
    )
    small_net = models.DecimalField(
        max_digits=24, decimal_places=2, null=True, blank=True,
    )
    source = models.CharField(max_length=50)
    fetched_at = models.DateTimeField(auto_now_add=True)
    extra = models.JSONField(default=dict, blank=True)

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
        max_length=30, db_index=True,
        help_text="DataCapability value (e.g. 'macro', 'historical_price')",
    )
    request_params = models.JSONField(default=dict, blank=True)
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
