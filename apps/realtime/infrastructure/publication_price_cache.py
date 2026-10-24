"""Qualification and provenance helpers for cached realtime prices."""

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Literal
from zoneinfo import ZoneInfo

from apps.data_center.application.public import (
    get_published_price_bar_series,
    get_published_quote_payloads,
)
from apps.data_center.domain.entities import QuoteChangePctEvidence
from apps.realtime.domain.entities import AssetType, RealtimePrice, normalize_asset_code
from shared.numeric import safe_float

logger = logging.getLogger(__name__)
_CHINA_MARKET_TIMEZONE = ZoneInfo("Asia/Shanghai")
_QUOTE_PUBLICATION_DATASET = "equity.quote.snapshot"
_BAR_PUBLICATION_DATASET = "equity.price.bar"


def _daily_bar_observed_at(bar_date: date) -> datetime:
    """Return the actual China-market close time represented by a daily bar."""

    return datetime.combine(
        bar_date,
        time(hour=15),
        tzinfo=_CHINA_MARKET_TIMEZONE,
    ).astimezone(UTC)


def _finite_float(value: object) -> float | None:
    """Return one finite numeric payload value, rejecting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return safe_float(value, default=None)


def _finite_decimal(value: object) -> Decimal | None:
    """Preserve exact decimal text after the shared finite-number boundary check."""

    if isinstance(value, bool) or safe_float(value, default=None) is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _published_quote_metric_evidence(
    row: Mapping[str, object],
    *,
    source: str,
    observed_at: datetime,
) -> tuple[Decimal | None, str | None]:
    """Return one exact metric and evidence hash only when the row proves both."""

    metric = _finite_decimal(row.get("change_pct"))
    evidence_payload = row.get("change_pct_source_contract")
    if metric is None or not isinstance(evidence_payload, Mapping):
        return None, None
    try:
        evidence = QuoteChangePctEvidence.from_payload(evidence_payload)
    except ValueError:
        return None, None
    extra = row.get("extra")
    actual_source = extra.get("actual_source") if isinstance(extra, Mapping) else None
    if (
        isinstance(extra, Mapping)
        and "actual_source" in extra
        and not isinstance(actual_source, str)
    ):
        return None, None
    provider_source = actual_source if isinstance(actual_source, str) else source
    if (
        evidence.metric_value != metric
        or evidence.dataset_contract_key != _QUOTE_PUBLICATION_DATASET
        or evidence.dataset_contract_version != row.get("contract_version")
        or evidence.dataset_schema_version != row.get("schema_version")
        or evidence.quote_source != source
        or evidence.observed_at != observed_at
        or evidence.source_contract.provider_source != provider_source
        or evidence.source_contract.origin != "vendor_reported"
        or evidence.source_contract.canonical_unit != "percent"
    ):
        return None, None
    encoded = json.dumps(
        evidence.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return metric, hashlib.sha256(encoded).hexdigest()


def _aware_datetime(value: object) -> datetime | None:
    """Parse one source observation timestamp without inventing a clock time."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def cache_identity_text(data: Mapping[str, object], key: str) -> str | None:
    """Return one nonempty string cache identity without coercing other values."""

    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def cache_source_kind(
    data: Mapping[str, object],
) -> Literal["external_provider", "data_center_publication"] | None:
    """Keep only recognized cache provenance; absent or malformed values stay unknown."""

    value = data.get("_cache_source_kind")
    if value == "external_provider":
        return "external_provider"
    if value == "data_center_publication":
        return "data_center_publication"
    return None


def _publication_identity(
    payload: Mapping[str, object],
    *,
    expected_dataset_key: str,
) -> tuple[str, str, str] | None:
    """Return a safe, complete current-publication identity or fail closed."""

    if payload.get("must_not_use_for_decision") is not False:
        return None
    publication_id = cache_identity_text(payload, "publication_id")
    dataset_key = cache_identity_text(payload, "dataset_key")
    publication_key = cache_identity_text(payload, "publication_key")
    if (
        publication_id is None
        or dataset_key != expected_dataset_key
        or publication_key != "current"
    ):
        return None
    return publication_id, dataset_key, publication_key


def _row_matches_requested_asset_code(
    row: Mapping[str, object],
    requested_asset_code: str,
) -> bool:
    """Require a publication member to identify the requested asset explicitly."""

    row_asset_code = cache_identity_text(row, "asset_code")
    if row_asset_code is None:
        return False
    try:
        return normalize_asset_code(row_asset_code) == normalize_asset_code(requested_asset_code)
    except ValueError:
        return False


def _payload_row_matches_cached_price(
    price: RealtimePrice,
    row: Mapping[str, object],
) -> bool:
    """Require the cache value and source observation to match a current member."""

    if str(row.get("asset_code") or "").strip().upper() != price.asset_code:
        return False
    if "must_not_use_for_decision" in row and row.get("must_not_use_for_decision") is not False:
        return False

    if price.publication_dataset_key == _QUOTE_PUBLICATION_DATASET:
        if price.change is not None:
            return False
        raw_price = row.get("current_price")
        observed_at = _aware_datetime(row.get("snapshot_at"))
        fetched_at = _aware_datetime(row.get("fetched_at"))
        if fetched_at != price.fetched_at:
            return False
    elif price.publication_dataset_key == _BAR_PUBLICATION_DATASET:
        if (
            price.change is not None
            or price.change_pct is not None
            or price.change_pct_evidence_hash is not None
        ):
            return False
        raw_price = row.get("close")
        raw_date = row.get("timestamp") or row.get("bar_date")
        if not isinstance(raw_date, str) or not raw_date.strip():
            return False
        observed_at = _aware_datetime(raw_date)
        if observed_at is None:
            try:
                bar_date = date.fromisoformat(raw_date[:10])
            except ValueError:
                return False
            if _daily_bar_observed_at(bar_date) != price.timestamp:
                return False
            observed_at = price.timestamp
    else:
        return False

    current_price = _finite_float(raw_price)
    if (
        current_price is None
        or observed_at is None
        or Decimal(str(current_price)) != price.price
        or observed_at != price.timestamp
        or str(row.get("source") or "data_center") != price.source
    ):
        return False
    volume_value = _finite_float(row.get("volume"))
    current_volume = int(volume_value) if volume_value is not None else None
    if current_volume != price.volume:
        return False
    if price.publication_dataset_key == _QUOTE_PUBLICATION_DATASET:
        current_change_pct, current_evidence_hash = _published_quote_metric_evidence(
            row,
            source=str(row.get("source") or "data_center"),
            observed_at=observed_at,
        )
        return (
            current_change_pct == price.change_pct
            and current_evidence_hash == price.change_pct_evidence_hash
        )
    return True


def published_data_center_price(
    asset_code: str,
    asset_type: AssetType,
) -> RealtimePrice | None:
    """Read a current Data Center quote/bar only behind publication gates.

    Quote snapshots are preferred, while a daily bar is an explicitly gated
    fallback.  A raw repository read is intentionally not used here: an
    unpublished or stale fact must not be presented as realtime data.
    """

    try:
        quote_payload = get_published_quote_payloads([asset_code], publication_key="current")
    except Exception:
        logger.warning(
            "Current quote publication unavailable for %s",
            asset_code,
            exc_info=True,
        )
        return None
    quote_rows = quote_payload.get("rows")
    quote_identity = _publication_identity(
        quote_payload,
        expected_dataset_key=_QUOTE_PUBLICATION_DATASET,
    )
    if quote_identity is not None and isinstance(quote_rows, list):
        for row in quote_rows:
            if not isinstance(row, Mapping):
                continue
            if not _row_matches_requested_asset_code(row, asset_code):
                continue
            if (
                "must_not_use_for_decision" in row
                and row.get("must_not_use_for_decision") is not False
            ):
                continue
            price = _finite_float(row.get("current_price"))
            observed_at = _aware_datetime(row.get("snapshot_at"))
            if price is None or observed_at is None:
                continue
            fetched_at = _aware_datetime(row.get("fetched_at"))
            change_pct, change_pct_evidence_hash = _published_quote_metric_evidence(
                row,
                source=str(row.get("source") or "data_center"),
                observed_at=observed_at,
            )
            return RealtimePrice(
                asset_code=asset_code,
                asset_type=asset_type,
                price=Decimal(str(price)),
                change=None,
                change_pct=change_pct,
                volume=(
                    int(volume_value)
                    if (volume_value := _finite_float(row.get("volume"))) is not None
                    else None
                ),
                timestamp=observed_at,
                source=str(row.get("source") or "data_center"),
                fetched_at=fetched_at,
                cache_source_kind="data_center_publication",
                publication_id=quote_identity[0],
                publication_dataset_key=quote_identity[1],
                publication_key=quote_identity[2],
                change_pct_evidence_hash=change_pct_evidence_hash,
            )

    try:
        bar_payload = get_published_price_bar_series(
            asset_code,
            publication_key="current",
            limit=1,
        )
    except Exception:
        logger.warning(
            "Current price-bar publication unavailable for %s",
            asset_code,
            exc_info=True,
        )
        return None
    bar_rows = bar_payload.get("rows")
    bar_identity = _publication_identity(
        bar_payload,
        expected_dataset_key=_BAR_PUBLICATION_DATASET,
    )
    if bar_identity is None or not isinstance(bar_rows, list):
        return None
    for row in reversed(bar_rows):
        if not isinstance(row, Mapping):
            continue
        if not _row_matches_requested_asset_code(row, asset_code):
            continue
        if "must_not_use_for_decision" in row and row.get("must_not_use_for_decision") is not False:
            continue
        close = _finite_float(row.get("close"))
        raw_date = row.get("timestamp") or row.get("bar_date")
        if close is None or not isinstance(raw_date, str):
            continue
        try:
            bar_date = date.fromisoformat(raw_date[:10])
        except ValueError:
            continue
        volume_value = _finite_float(row.get("volume"))
        return RealtimePrice(
            asset_code=asset_code,
            asset_type=asset_type,
            price=Decimal(str(close)),
            change=None,
            change_pct=None,
            volume=int(volume_value) if volume_value is not None else None,
            timestamp=_daily_bar_observed_at(bar_date),
            source=str(row.get("source") or "data_center"),
            cache_source_kind="data_center_publication",
            publication_id=bar_identity[0],
            publication_dataset_key=bar_identity[1],
            publication_key=bar_identity[2],
            change_pct_evidence_hash=None,
        )
    return None


def cache_payload(price: RealtimePrice) -> dict[str, object]:
    """Serialize public values plus private cache provenance for revalidation."""

    payload = price.to_dict()
    if price.change_pct is not None:
        payload["change_pct"] = format(price.change_pct, "f")
    payload.update(
        {
            "_cache_source_kind": price.cache_source_kind,
            "_publication_id": price.publication_id,
            "_publication_dataset_key": price.publication_dataset_key,
            "_publication_key": price.publication_key,
            "_change_pct_evidence_hash": price.change_pct_evidence_hash,
        }
    )
    return payload


def currently_qualified_cache_prices(prices: list[RealtimePrice]) -> list[RealtimePrice]:
    """Revalidate publication-bound cache rows in bounded current reads."""

    accepted: list[RealtimePrice] = [
        price for price in prices if price.cache_source_kind == "external_provider"
    ]
    quote_prices = [
        price
        for price in prices
        if price.cache_source_kind == "data_center_publication"
        and price.publication_dataset_key == _QUOTE_PUBLICATION_DATASET
    ]
    bar_prices = [
        price
        for price in prices
        if price.cache_source_kind == "data_center_publication"
        and price.publication_dataset_key == _BAR_PUBLICATION_DATASET
    ]

    if quote_prices:
        quote_codes = sorted({price.asset_code for price in quote_prices})
        try:
            quote_payload = get_published_quote_payloads(
                quote_codes,
                publication_key="current",
            )
        except Exception:
            logger.warning(
                "Current quote publication revalidation unavailable for cached prices",
                exc_info=True,
            )
        else:
            if isinstance(quote_payload, Mapping):
                identity = _publication_identity(
                    quote_payload,
                    expected_dataset_key=_QUOTE_PUBLICATION_DATASET,
                )
                rows = quote_payload.get("rows")
                if identity is not None and isinstance(rows, list):
                    accepted.extend(
                        price
                        for price in quote_prices
                        if price.publication_id == identity[0]
                        and price.publication_dataset_key == identity[1]
                        and price.publication_key == identity[2]
                        and any(
                            isinstance(row, Mapping)
                            and _payload_row_matches_cached_price(price, row)
                            for row in rows
                        )
                    )

    for price in bar_prices:
        if (
            not isinstance(price.publication_id, str)
            or not price.publication_id.strip()
            or price.publication_key != "current"
        ):
            continue
        try:
            bar_payload = get_published_price_bar_series(
                price.asset_code,
                publication_key="current",
                limit=1,
            )
        except Exception:
            logger.warning(
                "Current price-bar publication revalidation unavailable for cached asset_code=%s",
                price.asset_code,
                exc_info=True,
            )
            continue
        if not isinstance(bar_payload, Mapping):
            continue
        identity = _publication_identity(
            bar_payload,
            expected_dataset_key=_BAR_PUBLICATION_DATASET,
        )
        if identity != (price.publication_id, _BAR_PUBLICATION_DATASET, "current"):
            continue
        rows = bar_payload.get("rows")
        if isinstance(rows, list) and any(
            isinstance(row, Mapping) and _payload_row_matches_cached_price(price, row)
            for row in rows
        ):
            accepted.append(price)

    qualified_object_ids = {id(price) for price in accepted}
    return [price for price in prices if id(price) in qualified_object_ids]
