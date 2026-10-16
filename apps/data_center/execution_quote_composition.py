"""Composition root for publication-bound exact execution quote reads."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from django.utils import timezone

from apps.data_center.application.execution_quotes import (
    ExecutionQuoteBlockReason,
    ExecutionQuotePublicationGate,
    ExecutionQuoteUnavailable,
    GetExecutionQuoteUseCase,
)
from apps.data_center.application.public_published_queries import (
    get_current_publication_freshness_gate,
)
from apps.data_center.domain.execution_quotes import ExecutionQuoteSnapshot
from apps.data_center.infrastructure.execution_quote_repository import (
    DjangoExecutionQuoteRepository,
)
from apps.data_center.publication_read_composition import publication_snapshot


class _ExecutionQuoteGateReader:
    """Adapt the exact execution-pointer payload to its typed use-case port."""

    def get_current_gate(
        self, asset_code: str, *, as_of: datetime
    ) -> ExecutionQuotePublicationGate | None:
        """Read the execution pointer and current active catalog TTL gate."""

        payload = get_current_publication_freshness_gate(
            "equity.quote.snapshot",
            "execution",
            as_of=as_of,
            asset_code=asset_code,
        )
        if payload is None:
            return None
        return _gate_from_payload(payload)


@publication_snapshot("equity.quote.snapshot")
def get_execution_quote(
    asset_code: str,
    *,
    as_of: datetime | None = None,
) -> ExecutionQuoteSnapshot:
    """Return an exact quote under the execution pointer and catalog TTL.

    The active contract selection is current configuration, not point-in-time
    history; ``as_of`` bounds quote freshness only. The DTO contains no trading
    session, halt, price-band, security-status, or account-policy decision.
    """

    reference = as_of if as_of is not None else timezone.now()
    return GetExecutionQuoteUseCase(
        gate_reader=_ExecutionQuoteGateReader(),
        quote_reader=DjangoExecutionQuoteRepository(),
    ).execute(asset_code, as_of=reference)


def _gate_from_payload(payload: Mapping[str, object]) -> ExecutionQuotePublicationGate:
    """Narrow the legacy gate mapping before it reaches the typed use case."""

    published_at = _datetime_value(payload.get("published_at"))
    publication_as_of = _datetime_value(payload.get("as_of"))
    execution_freshness_seconds_value = payload.get("execution_freshness_seconds")
    if execution_freshness_seconds_value is not None and (
        type(execution_freshness_seconds_value) is not int or execution_freshness_seconds_value <= 0
    ):
        raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
    must_not_use = payload.get("must_not_use_for_decision")
    if type(must_not_use) is not bool:
        raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
    try:
        gate = ExecutionQuotePublicationGate(
            dataset_key=_text_value(payload.get("dataset_key")),
            publication_key=_text_value(payload.get("publication_key")),
            publication_id=_text_value(payload.get("publication_id")),
            publication_hash=_text_value(payload.get("publication_hash")),
            publication_as_of=publication_as_of,
            published_at=published_at,
            policy_identity=_text_value(payload.get("policy_identity")),
            contract_version=_text_value(payload.get("contract_version", "")),
            schema_version=_text_value(payload.get("schema_version", "")),
            contract_resolution=_text_value(payload.get("contract_resolution")),
            execution_freshness_seconds=execution_freshness_seconds_value,
            must_not_use_for_decision=must_not_use,
            blocked_reason=_text_value(payload.get("blocked_reason")),
            freshness_status=_text_value(payload.get("freshness_status")),
        )
        gate.validate()
    except (TypeError, ValueError):
        raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT) from None
    return gate


def _text_value(value: object) -> str:
    """Require a string-valued legacy gate field."""

    if type(value) is not str:
        raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
    return value


def _datetime_value(value: object) -> datetime:
    """Parse one aware datetime from the existing gate's ISO projection."""

    if isinstance(value, datetime):
        parsed = value
    elif type(value) is str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            raise ExecutionQuoteUnavailable(
                ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT
            ) from None
    else:
        raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ExecutionQuoteUnavailable(ExecutionQuoteBlockReason.INVALID_PROVIDER_RESULT)
    return parsed.astimezone(UTC)


__all__ = ["get_execution_quote"]
