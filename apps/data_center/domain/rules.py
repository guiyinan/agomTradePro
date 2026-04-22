"""
Data Center — Domain Business Rules

Pure-Python utility functions encoding platform-wide data rules.
No Django, no ORM, no external libraries — only stdlib.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

# ---------------------------------------------------------------------------
# Unit-normalisation (migrated from macro.domain.entities)
# ---------------------------------------------------------------------------

# Conversion factors relative to "元" (CNY base unit)
UNIT_CONVERSION_FACTORS: dict[str, float] = {
    "元": 1,
    "万元": 1e4,
    "亿元": 1e8,
    "万亿元": 1e12,
    "万美元": 1e4,
    "百万美元": 1e6,
    "亿美元": 1e8,
    "十亿美元": 1e9,
}


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
    if unit not in UNIT_CONVERSION_FACTORS:
        return (value, unit)

    factor = UNIT_CONVERSION_FACTORS[unit]
    if "美元" in unit or "USD" in unit.upper():
        return (value * factor * exchange_rate, "元")
    return (value * factor, "元")


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
    now = datetime.now(timezone.utc)
    # Normalise naive datetime to UTC
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
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
