"""
Data Center — Domain Business Rules

Pure-Python utility functions encoding platform-wide data rules.
No Django, no ORM, no external libraries — only stdlib.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

# ---------------------------------------------------------------------------
# Unit-normalisation (migrated from macro.domain.entities)
# ---------------------------------------------------------------------------

# Conversion factors relative to "元" (CNY base unit)
UNIT_CONVERSION_FACTORS: dict[str, float] = {
    "元": 1,
    "千元": 1e3,
    "万元": 1e4,
    "亿元": 1e8,
    "万亿元": 1e12,
    "万美元": 1e4,
    "百万美元": 1e6,
    "亿美元": 1e8,
    "十亿美元": 1e9,
    "万亿美元": 1e13,
}
USD_UNIT_LABELS = frozenset({"万美元", "百万美元", "亿美元", "十亿美元", "万亿美元"})


def convert_currency_value(
    value: float,
    from_unit: str,
    to_unit: str,
    exchange_rate: float = 1.0,
) -> tuple[float, str]:
    """Convert between supported currency units.

    Returns the converted numeric value and the target unit when both units are
    recognised. If either unit is unknown, the original pair is returned
    unchanged so callers can fall back safely.
    """
    if from_unit == to_unit:
        return (value, to_unit)
    if from_unit not in UNIT_CONVERSION_FACTORS or to_unit not in UNIT_CONVERSION_FACTORS:
        return (value, from_unit)

    from_factor = UNIT_CONVERSION_FACTORS[from_unit]
    to_factor = UNIT_CONVERSION_FACTORS[to_unit]

    value_in_yuan = value * from_factor
    if from_unit in USD_UNIT_LABELS:
        value_in_yuan *= exchange_rate

    if to_unit in USD_UNIT_LABELS:
        return (value_in_yuan / (to_factor * exchange_rate), to_unit)
    return (value_in_yuan / to_factor, to_unit)


def normalize_currency_unit(
    value: float,
    unit: str,
    exchange_rate: float = 1.0,
) -> tuple[float, str]:
    """Convert a currency value to the base CNY unit ("元").

    Args:
        value: Raw numeric value.
        unit:  Original unit label (e.g. "亿元", "百万美元").
        exchange_rate: USD/CNY rate (how many CNY per 1 USD).
            ⚠️ Default 1.0 is a safe fallback only — back-testing must supply
            the historical rate.

    Returns:
        ``(converted_value, "元")`` — always returns the canonical unit string.
        If *unit* is unrecognised the original (value, unit) pair is returned
        unchanged so callers can handle it gracefully.

    Examples:
        >>> normalize_currency_unit(1.5, "亿元")
        (150000000.0, '元')
        >>> normalize_currency_unit(1.0, "亿美元", exchange_rate=7.2)
        (720000000.0, '元')
    """
    return convert_currency_value(value, unit, "元", exchange_rate)


# ---------------------------------------------------------------------------
# Asset-code normalisation
# ---------------------------------------------------------------------------

# Suffix mapping: provider-local suffix → canonical (Tushare-style) suffix
_EXCHANGE_SUFFIX_MAP: dict[str, str] = {
    # AKShare / baostock use XSHG / XSHE
    "XSHG": "SH",
    "XSHE": "SZ",
    # Wind uses .SS for Shanghai
    "SS": "SH",
    # Beijing exchange
    "BJ": "BJ",
    # Hong Kong
    "HK": "HK",
    # Already canonical — keep as-is
    "SH": "SH",
    "SZ": "SZ",
}


def normalize_asset_code(code: str, source_type: str = "") -> str:
    """Normalise a provider-specific ticker to canonical Tushare format.

    Canonical format: ``<numeric_code>.<EXCHANGE>``  (e.g. ``000001.SZ``).

    Rules applied (in order):
    1. Strip whitespace.
    2. If the code already matches ``\\d+\\.[A-Z]{2}`` (e.g. ``600519.SH``)
       it is returned unchanged — already canonical.
    3. Map known provider suffixes to the canonical two-letter exchange suffix
       via ``_EXCHANGE_SUFFIX_MAP``.
    4. For AKShare / baostock codes that prepend the exchange letter
       (e.g. ``sh600519``, ``sz000001``) rewrite to canonical form.
    5. Codes that cannot be mapped are returned unchanged.

    Args:
        code:        Raw ticker string from provider.
        source_type: Optional hint (``"akshare"``, ``"tushare"``, …) — used
                     only when the suffix is absent and disambiguation is needed.

    Returns:
        Canonical ticker string or the original string if mapping is undefined.

    Examples:
        >>> normalize_asset_code("000001.XSHE")
        '000001.SZ'
        >>> normalize_asset_code("sh600519")
        '600519.SH'
        >>> normalize_asset_code("600519.SH")
        '600519.SH'
    """
    code = code.strip()

    # dot-separated suffix (e.g. "000001.XSHE", "600519.SS", "600519.SH")
    if "." in code:
        parts = code.rsplit(".", 1)
        if len(parts) == 2:
            numeric, suffix = parts[0], parts[1].upper()
            if suffix in {"SH", "SZ", "BJ", "HK"}:
                return f"{numeric}.{suffix}"
            canonical_suffix = _EXCHANGE_SUFFIX_MAP.get(suffix)
            if canonical_suffix:
                return f"{numeric}.{canonical_suffix}"
        # Unknown suffix — return as-is
        return code

    # AKShare-style prefix codes: sh600519 / sz000001 / bj430047
    m = re.fullmatch(r"(sh|sz|bj|hk)(\d+)", code, re.IGNORECASE)
    if m:
        prefix, numeric = m.group(1).upper(), m.group(2)
        canonical_suffix = _EXCHANGE_SUFFIX_MAP.get(prefix, prefix)
        return f"{numeric}.{canonical_suffix}"

    # Bare numeric code — use source_type hint if available
    if re.fullmatch(r"\d+", code):
        if source_type.lower() in ("akshare", "tushare", "baostock"):
            # Heuristic: 6xxxxx → SH, others → SZ (rough Chinese market rule)
            if code.startswith("6"):
                return f"{code}.SH"
            if code.startswith("4") or code.startswith("8"):
                return f"{code}.BJ"
            return f"{code}.SZ"

    return code


# ---------------------------------------------------------------------------
# Staleness check
# ---------------------------------------------------------------------------

DEFAULT_MACRO_MAX_LAG_DAYS_BY_PERIOD_TYPE: dict[str, int] = {
    "D": 7,
    "W": 21,
    "M": 45,
    "Q": 120,
    "H": 220,
    "Y": 400,
}


def is_stale(fetched_at: datetime, max_age_hours: float) -> bool:
    """Return True if *fetched_at* is older than *max_age_hours*.

    Both naive and timezone-aware datetimes are handled: naive datetimes are
    assumed to be UTC.

    Args:
        fetched_at:    The timestamp when the data was last fetched.
        max_age_hours: Maximum acceptable age in hours (may be fractional).

    Returns:
        ``True`` if the data is stale, ``False`` otherwise.

    Examples:
        >>> from datetime import timedelta
        >>> is_stale(datetime.now(timezone.utc) - timedelta(hours=2), max_age_hours=1)
        True
        >>> is_stale(datetime.now(timezone.utc) - timedelta(minutes=30), max_age_hours=1)
        False
    """
    now = datetime.now(UTC)
    # Normalise naive datetime to UTC
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    age_hours = (now - fetched_at).total_seconds() / 3600
    return age_hours > max_age_hours


def get_macro_max_lag_days(period_type: str | None) -> int:
    """Return the default freshness threshold for a macro period type."""
    normalized = (period_type or "M").strip().upper()
    return DEFAULT_MACRO_MAX_LAG_DAYS_BY_PERIOD_TYPE.get(normalized, 45)


def get_macro_age_days(
    reporting_period: date,
    published_at: date | None = None,
    *,
    as_of_date: date | None = None,
) -> int:
    """Return the age in whole days using published_at when available."""
    target_date = as_of_date or date.today()
    reference_date = published_at or reporting_period
    if reference_date > target_date:
        return 0
    return (target_date - reference_date).days


def is_macro_observation_stale(
    reporting_period: date,
    published_at: date | None = None,
    *,
    period_type: str | None = None,
    as_of_date: date | None = None,
) -> bool:
    """Return True when a macro observation exceeds its expected reporting lag."""
    return get_macro_age_days(
        reporting_period,
        published_at,
        as_of_date=as_of_date,
    ) > get_macro_max_lag_days(period_type)


# ---------------------------------------------------------------------------
# Market thermometer scoring helpers
# ---------------------------------------------------------------------------


def clamp_score_0_100(value: float) -> float:
    """Clamp a numeric score into the inclusive [0, 100] range."""

    return max(0.0, min(100.0, float(value)))


def normalize_signed_value(
    value: float | None,
    *,
    negative_bound: float,
    positive_bound: float,
) -> float:
    """Normalize a signed metric into a 0-100 score.

    Values at ``negative_bound`` map to 0, at 0 map to 50, and at
    ``positive_bound`` map to 100.
    """

    if value is None:
        return 50.0
    numeric = float(value)
    if numeric >= 0:
        if positive_bound <= 0:
            return 50.0
        return clamp_score_0_100(50.0 + (numeric / positive_bound) * 50.0)
    if negative_bound >= 0:
        return 50.0
    return clamp_score_0_100(50.0 - (numeric / negative_bound) * 50.0)


def compute_percentile_score(values: list[float], current_value: float | None) -> float:
    """Compute a simple percentile rank score in [0, 100]."""

    if current_value is None or not values:
        return 50.0
    ordered = sorted(float(value) for value in values)
    rank = sum(1 for value in ordered if value <= float(current_value))
    if len(ordered) == 1:
        return 50.0
    return clamp_score_0_100(((rank - 1) / (len(ordered) - 1)) * 100.0)


def compute_rate_of_change(current_value: float | None, previous_value: float | None) -> float | None:
    """Return fractional rate of change ``(current / previous) - 1``."""

    if current_value is None or previous_value in (None, 0):
        return None
    return (float(current_value) / float(previous_value)) - 1.0


def market_indicator_is_stale(
    observed_at: date | None,
    *,
    frequency: str,
    as_of_date: date | None = None,
    daily_stale_days: int = 3,
    monthly_stale_days: int = 45,
) -> tuple[bool, int | None]:
    """Return stale flag and age for market thermometer inputs."""

    if observed_at is None:
        return (True, None)
    target_date = as_of_date or date.today()
    age_days = max(0, (target_date - observed_at).days)
    if str(frequency).upper() == "M":
        return (age_days > monthly_stale_days, age_days)
    return (age_days > daily_stale_days, age_days)


def determine_market_thermometer_band(
    score: float,
    *,
    warm_threshold: float,
    hot_threshold: float,
    overheat_threshold: float,
    extreme_threshold: float,
) -> str:
    """Map a thermometer score into a stable interpretation band."""

    bounded = clamp_score_0_100(score)
    if bounded < warm_threshold:
        return "cold"
    if bounded < hot_threshold:
        return "warm"
    if bounded < overheat_threshold:
        return "hot"
    if bounded < extreme_threshold:
        return "overheat"
    return "extreme"
