"""Pure rules for selecting and normalizing valuation payloads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .entities import ValuationSnapshot


class ValuationPayloadPolicy:
    """Validate formal valuations and build canonical price contracts."""

    MAX_FORMAL_VALUATION_AGE_DAYS = 30
    UNUSABLE_QUALITY_FLAGS = frozenset(
        {
            "error",
            "expired",
            "failed",
            "invalid",
            "invalid_pb",
            "jump_alert",
            "missing_pb",
            "source_deviation",
            "stale",
            "unusable",
        }
    )

    @classmethod
    def is_usable(cls, payload: Mapping[str, Any], *, today: date) -> bool:
        """Return whether a formal valuation is positive, fresh, and reliable."""
        if not cls.has_positive_price_contract(payload):
            return False
        if payload.get("is_legacy") is True:
            return False
        if str(payload.get("valuation_method") or "").lower() in {
            "fallback",
            "legacy",
        }:
            return False
        if not cls._has_acceptable_quality(payload):
            return False
        valuation_date = cls._extract_payload_date(payload)
        if valuation_date is None:
            return False
        earliest = today - timedelta(days=cls.MAX_FORMAL_VALUATION_AGE_DAYS)
        return earliest <= valuation_date <= today

    @classmethod
    def has_positive_price_contract(cls, payload: Mapping[str, Any]) -> bool:
        """Return whether all required price fields are positive."""
        return all(
            cls.to_decimal(payload.get(field)) > 0
            for field in (
                "fair_value",
                "entry_price_low",
                "entry_price_high",
                "target_price_low",
                "target_price_high",
            )
        )

    @classmethod
    def build_fact_payload(
        cls,
        fact: Mapping[str, Any],
        *,
        today: date,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Build a canonical price contract from one data-center valuation fact.

        ``now`` is injectable for deterministic boundary tests; production callers
        may omit it and use the current UTC clock.
        """
        extra = fact.get("extra") or {}
        if not isinstance(extra, Mapping):
            return None
        fair_value = cls._pick_decimal(
            extra,
            (
                "fair_value",
                "intrinsic_value_per_share",
                "estimated_fair_value",
                "target_fair_value",
            ),
        )
        if fair_value <= 0:
            return None
        source_updated_at = fact.get("source_updated_at")
        if source_updated_at is None:
            source_updated_at = fact.get("observed_at")
        if not cls._is_current_data_center_observation(
            source_updated_at,
            today=today,
            now=now,
        ):
            return None
        payload: dict[str, Any] = {
            "fair_value": fair_value,
            "entry_price_low": cls._pick_decimal(extra, ("entry_price_low", "entry_low")),
            "entry_price_high": cls._pick_decimal(extra, ("entry_price_high", "entry_high")),
            "target_price_low": cls._pick_decimal(extra, ("target_price_low", "target_low")),
            "target_price_high": cls._pick_decimal(extra, ("target_price_high", "target_high")),
            "stop_loss_price": cls._pick_decimal(extra, ("stop_loss_price", "stop_loss")),
            "valuation_method": str(extra.get("valuation_method") or "DATA_CENTER_FACT"),
            "valuation_source": "data_center_valuation_fact",
            "valuation_fact_date": fact.get("valuation_fact_date"),
            "source_updated_at": source_updated_at,
            "fetched_at": fact.get("fetched_at"),
            "is_valid": extra.get("is_valid", True),
            "quality_flag": extra.get("quality_flag") or extra.get("data_quality_flag") or "ok",
        }
        defaults = {
            "entry_price_low": fair_value * Decimal("0.95"),
            "entry_price_high": fair_value * Decimal("1.05"),
            "target_price_low": fair_value * Decimal("1.15"),
            "target_price_high": fair_value * Decimal("1.25"),
            "stop_loss_price": fair_value * Decimal("0.855"),
        }
        for key, default in defaults.items():
            if cls.to_decimal(payload[key]) <= 0:
                payload[key] = default
        if not cls.is_usable(payload, today=today):
            return None
        return {
            key: float(value) if isinstance(value, Decimal) else value
            for key, value in payload.items()
        }

    @classmethod
    def snapshot_to_payload(
        cls,
        snapshot: ValuationSnapshot,
        *,
        valuation_source: str,
    ) -> dict[str, Any]:
        """Serialize a snapshot into the recommendation valuation contract."""
        return {
            "fair_value": float(snapshot.fair_value),
            "entry_price_low": float(snapshot.entry_price_low),
            "entry_price_high": float(snapshot.entry_price_high),
            "target_price_low": float(snapshot.target_price_low),
            "target_price_high": float(snapshot.target_price_high),
            "stop_loss_price": float(snapshot.stop_loss_price),
            "valuation_method": snapshot.valuation_method,
            "valuation_source": valuation_source,
            "valuation_snapshot_id": snapshot.snapshot_id,
        }

    @staticmethod
    def to_decimal(value: Any) -> Decimal:
        """Coerce external numeric input to Decimal or zero."""
        try:
            return Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return Decimal("0")

    @classmethod
    def _has_acceptable_quality(cls, payload: Mapping[str, Any]) -> bool:
        input_parameters = payload.get("input_parameters")
        if isinstance(input_parameters, Mapping):
            if input_parameters.get("is_valid") is False:
                return False
            nested_flag = input_parameters.get("quality_flag") or input_parameters.get(
                "data_quality_flag"
            )
            if cls._is_unusable_quality_flag(nested_flag):
                return False
        if payload.get("is_valid") is False:
            return False
        return not cls._is_unusable_quality_flag(
            payload.get("quality_flag") or payload.get("data_quality_flag")
        )

    @classmethod
    def _is_unusable_quality_flag(cls, quality_flag: Any) -> bool:
        if quality_flag is None:
            return False
        if isinstance(quality_flag, list | tuple | set):
            return any(cls._is_unusable_quality_flag(item) for item in quality_flag)
        return str(quality_flag).strip().lower() in cls.UNUSABLE_QUALITY_FLAGS

    @classmethod
    def _extract_payload_date(cls, payload: Mapping[str, Any]) -> date | None:
        candidates = (
            payload.get("valuation_date"),
            payload.get("valuation_fact_date"),
            payload.get("trade_date"),
            payload.get("as_of_date"),
            payload.get("calculated_at"),
            payload.get("fetched_at"),
            payload.get("source_updated_at"),
        )
        for candidate in candidates:
            parsed = cls._coerce_date(candidate)
            if parsed is not None:
                return parsed
        input_parameters = payload.get("input_parameters")
        if isinstance(input_parameters, Mapping):
            for key in (
                "valuation_date",
                "trade_date",
                "as_of_date",
                "calculated_at",
                "fetched_at",
                "source_updated_at",
            ):
                parsed = cls._coerce_date(input_parameters.get(key))
                if parsed is not None:
                    return parsed
        return None

    @staticmethod
    def _coerce_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            if normalized:
                try:
                    return datetime.fromisoformat(normalized).date()
                except ValueError:
                    try:
                        return date.fromisoformat(normalized[:10])
                    except ValueError:
                        return None
        return None

    @staticmethod
    def _coerce_aware_datetime(value: object) -> datetime | None:
        """Parse one source observation timestamp without accepting naive input."""

        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            normalized = value.strip()
            if normalized.endswith("Z"):
                normalized = f"{normalized[:-1]}+00:00"
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(UTC)

    @classmethod
    def _is_current_data_center_observation(
        cls,
        value: object,
        *,
        today: date,
        now: datetime | None,
    ) -> bool:
        """Require a bounded, aware, current source observation for fact decisions."""

        observed_at = cls._coerce_aware_datetime(value)
        if observed_at is None:
            return False
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None or reference.utcoffset() is None:
            return False
        reference = reference.astimezone(UTC)
        earliest = today - timedelta(days=cls.MAX_FORMAL_VALUATION_AGE_DAYS)
        return earliest <= observed_at.date() <= today and observed_at <= reference

    @classmethod
    def _pick_decimal(cls, payload: Mapping[str, Any], keys: tuple[str, ...]) -> Decimal:
        for key in keys:
            amount = cls.to_decimal(payload.get(key))
            if amount > 0:
                return amount
        return Decimal("0")
