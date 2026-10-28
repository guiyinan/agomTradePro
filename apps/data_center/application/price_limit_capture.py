"""Explicit capture and exact raw replay of provider-native daily price bounds.

These inputs have no publication, currency qualification, trading state, or
execution authority. A caller must retain the returned request and reference;
this raw-only workflow does not create a discoverable daily market fact.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from apps.data_center.application.price_limit_response_capture import (
    ExactPriceLimitRequestScope,
    ExactPriceLimitResponseProviderProtocol,
    ExactPriceLimitValues,
    replay_exact_tushare_price_limit_values,
    validate_exact_price_limit_capture,
    validate_exact_price_limit_payload_reference,
)
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
    ProviderResponsePayloadRepositoryPort,
    RetainProviderResponsePayloadUseCase,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.raw_landing import RawPayload
from core.exceptions import DataFetchError


class PriceLimitProviderConfigReader(Protocol):
    """Read the explicitly selected provider, without implicit failover."""

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        """Return current configuration through its existing credential owner."""
        ...


class PriceLimitRawPayloadRepository(ProviderResponsePayloadRepositoryPort, Protocol):
    """Use the existing immutable raw store for saving and exact readback."""

    def get_by_hash(self, payload_hash: str) -> RawPayload | None:
        """Read one original record without capture, repair, or substitution."""
        ...


@dataclass(frozen=True, slots=True)
class RetainedPriceLimitCapture:
    """Validated source numbers and provenance, without decision qualification."""

    request_scope: ExactPriceLimitRequestScope
    values: ExactPriceLimitValues
    reference: ProviderResponsePayloadReference

    @property
    def known_at(self) -> datetime:
        """Return local response completion, not upstream first availability."""
        return self.reference.response_completed_at

    @property
    def price_unit(self) -> Literal["provider_native_price"]:
        """Keep the provider's native price scale without currency conversion."""
        return "provider_native_price"

    @property
    def currency(self) -> None:
        """The raw endpoint does not establish the instrument's quote currency."""
        return None

    @property
    def observed_at(self) -> None:
        """A trade date alone cannot establish a market observation timestamp."""
        return None

    @property
    def source_published_at(self) -> None:
        """The provider does not supply a row-level publication timestamp."""
        return None

    @property
    def must_not_use_for_decision(self) -> Literal[True]:
        """Raw source verification alone grants no decision-data qualification."""
        return True

    @property
    def must_not_execute(self) -> Literal[True]:
        """A price bound cannot establish tradability or execution permission."""
        return True


class ReadRetainedPriceLimitUseCase:
    """Reconstruct exactly the requested retained capture without network I/O."""

    def __init__(self, repository: PriceLimitRawPayloadRepository) -> None:
        """Bind the existing raw repository; construction performs no reads."""
        self._repository = repository

    def execute(
        self,
        reference: ProviderResponsePayloadReference,
        *,
        scope: ExactPriceLimitRequestScope,
    ) -> RetainedPriceLimitCapture:
        """Verify the reference and original body before returning exact values."""
        validate_exact_price_limit_payload_reference(reference, scope=scope)
        raw = self._repository.get_by_hash(reference.payload_hash)
        if raw is None:
            raise _blocked("PRICE_LIMIT_CAPTURE_PAYLOAD_MISSING")
        values = replay_exact_tushare_price_limit_values(raw, reference, scope=scope)
        return RetainedPriceLimitCapture(scope, values, reference)


class CaptureExactPriceLimitUseCase:
    """Capture one explicitly selected provider and retain its replayable body."""

    def __init__(
        self,
        configurations: PriceLimitProviderConfigReader,
        provider_factory: Callable[[ProviderConfig], ExactPriceLimitResponseProviderProtocol],
        repository: PriceLimitRawPayloadRepository,
    ) -> None:
        """Inject source construction and the existing immutable raw store."""
        self._configurations = configurations
        self._provider_factory = provider_factory
        self._retainer = RetainProviderResponsePayloadUseCase(repository)
        self._reader = ReadRetainedPriceLimitUseCase(repository)

    def execute(
        self, *, provider_id: int, asset_code: str, target_trade_date: date
    ) -> RetainedPriceLimitCapture:
        """Capture, retain, then re-read the exact original values under one scope."""
        if (
            type(provider_id) is not int
            or provider_id < 1
            or type(asset_code) is not str
            or type(target_trade_date) is not date
        ):
            raise _blocked("PRICE_LIMIT_CAPTURE_REQUEST_INVALID")
        config = self._configurations.get_by_id(provider_id)
        if (
            config is None
            or type(config.id) is not int
            or config.id != provider_id
            or config.is_active is not True
            or config.source_type != "tushare"
        ):
            raise _blocked("PRICE_LIMIT_CAPTURE_PROVIDER_UNAVAILABLE")
        try:
            scope = ExactPriceLimitRequestScope(
                provider_id=provider_id,
                provider_name=config.name,
                dataset_key="equity.price.limit",
                api_name="stk_limit",
                asset_code=asset_code,
                trade_date=target_trade_date,
            )
        except (TypeError, ValueError) as error:
            raise _blocked("PRICE_LIMIT_CAPTURE_REQUEST_INVALID") from error
        provider = self._provider_factory(config)
        captured = validate_exact_price_limit_capture(
            provider.fetch_price_limit_with_capture(asset_code, target_trade_date), scope=scope
        )
        if self._configurations.get_by_id(provider_id) != config:
            raise _blocked("PRICE_LIMIT_CAPTURE_PROVIDER_CHANGED")
        reference = self._retainer.execute(
            captured.capture,
            provider_name=scope.provider_name,
            dataset_key=scope.dataset_key,
            api_name=scope.api_name,
            request_params=scope.request_params(),
            sensitive_values=captured.sensitive_values,
        )
        retained = self._reader.execute(reference, scope=scope)
        if retained.values != captured.values:
            raise _blocked("PRICE_LIMIT_CAPTURE_READBACK_MISMATCH")
        return retained


def _blocked(code: str) -> DataFetchError:
    """Preserve a stable failure without fabricating market or zero-price data."""
    return DataFetchError(code, code=code)
