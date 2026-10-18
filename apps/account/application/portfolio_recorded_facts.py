"""Read stored portfolio facts through the existing Account authorization policy.

Read boundaries identify application reads, not source observations or an atomic
portfolio snapshot. This facade does not synchronize ledgers or refresh prices.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol, cast

from apps.account.application.portfolio_api_contracts import (
    AccountReadRepository,
    PortfolioApiRepository,
)
from apps.account.application.portfolio_api_services import (
    PortfolioAccessContext,
    PortfolioAccessDeniedError,
    PortfolioNotFoundError,
    resolve_portfolio_for_user,
)
from apps.account.application.repository_provider import (
    get_account_read_repository,
    get_portfolio_api_repository,
)
from core.exceptions import ExternalServiceError, InvalidInputError
from shared.numeric import safe_float

from .portfolio_recorded_facts_contracts import (
    PortfolioRecordedFactsPayload,
    RecordedPosition,
    RecordedPositionPage,
    RecordedReadClock,
    RecordedStatistics,
)

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PortfolioRecordedFactsInputError(InvalidInputError):
    """Raised when a recorded-facts request has invalid bounded input."""

    default_message = "组合事实请求输入无效"
    default_code = "PORTFOLIO_RECORDED_FACTS_INVALID_INPUT"
    default_status_code = 400


class PortfolioRecordedFactsReadError(ExternalServiceError):
    """Raised when a stored-facts read cannot produce a complete result."""

    default_message = "组合事实读取暂不可用"
    default_code = "PORTFOLIO_RECORDED_FACTS_UNAVAILABLE"
    default_status_code = 503


class PortfolioAccessResolver(Protocol):
    """Authorization resolver used by the façade and replaceable in unit tests."""

    def __call__(self, *, user_id: int, portfolio_id: int | str) -> PortfolioAccessContext:
        """Resolve one portfolio through the Account owner policy."""


class ReadNow(Protocol):
    """Clock port used only to label application read boundaries."""

    def __call__(self) -> datetime:
        """Return an aware UTC timestamp for a read boundary."""


@dataclass(frozen=True, slots=True)
class PortfolioRecordedFactsReadResult:
    """Authorized context plus the typed JSON payload returned by the façade."""

    context: PortfolioAccessContext
    payload: PortfolioRecordedFactsPayload


class PortfolioRecordedFactsReader:
    """Read one authorized portfolio without synchronization or business writes."""

    def __init__(
        self,
        *,
        read_repository: AccountReadRepository | None = None,
        portfolio_repository: PortfolioApiRepository | None = None,
        resolve_access: PortfolioAccessResolver | None = None,
        now: ReadNow | None = None,
    ) -> None:
        """Build the façade from existing application ports.

        ``resolve_access`` defaults to ``resolve_portfolio_for_user`` and is
        exposed only as a typed seam for isolated unit tests.  Production
        callers must retain the default resolver and must pass the authenticated
        actor's persisted user ID.
        """

        try:
            self._read_repository = (
                read_repository
                if read_repository is not None
                else cast(AccountReadRepository, get_account_read_repository())
            )
            self._portfolio_repository = (
                portfolio_repository
                if portfolio_repository is not None
                else cast(PortfolioApiRepository, get_portfolio_api_repository())
            )
        except Exception as exc:  # pragma: no cover - composition failure boundary
            raise PortfolioRecordedFactsReadError(
                "portfolio read services are unavailable"
            ) from exc
        self._resolve_access = (
            resolve_access if resolve_access is not None else resolve_portfolio_for_user
        )
        self._now = now if now is not None else _utc_now

    def read(
        self,
        *,
        user_id: int,
        portfolio_id: int | str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PortfolioRecordedFactsReadResult:
        """Return one complete authorized record of stored portfolio facts.

        Authorization is resolved before both reads and rechecked immediately
        before publication.  The two read clocks describe application
        boundaries only; they are not source timestamps or a shared atomic
        ``as_of``.  Any read, scope, or payload-shape failure aborts the whole
        response so a positions-only result is never presented as a complete
        portfolio check.  The recheck is a safety boundary, not a database lock.
        """

        normalized_user_id = _positive_int(user_id, "user_id")
        normalized_portfolio_id = _positive_int(portfolio_id, "portfolio_id")
        normalized_page = _positive_int(page, "page")
        normalized_page_size = _page_size(page_size)

        try:
            context = self._resolve_access(
                user_id=normalized_user_id,
                portfolio_id=normalized_portfolio_id,
            )
        except (PortfolioNotFoundError, PortfolioAccessDeniedError):
            raise
        except Exception as exc:  # pragma: no cover - composition failure boundary
            raise PortfolioRecordedFactsReadError(
                "portfolio authorization service unavailable"
            ) from exc
        initial_identity = _portfolio_identity(context)

        try:
            positions_started_at = _aware_read_time(self._now())
            raw_positions = self._read_repository.list_open_legacy_position_payloads(
                context.portfolio
            )
            source_position_ids = _legacy_position_source_ids(raw_positions)
            valuation_by_source_id = self._portfolio_repository.get_legacy_position_valuation_known(
                portfolio=context.portfolio,
                source_position_ids=source_position_ids,
            )
            position_rows = _apply_authoritative_valuation_knowledge(
                raw_positions,
                valuation_by_source_id,
            )
            positions_finished_at = _aware_read_time(self._now())
        except Exception as exc:  # pragma: no cover - repository boundary
            raise PortfolioRecordedFactsReadError(
                "portfolio positions are temporarily unavailable"
            ) from exc

        try:
            statistics_started_at = _aware_read_time(self._now())
            raw_statistics = self._portfolio_repository.build_portfolio_statistics(
                context.portfolio
            )
            statistics_finished_at = _aware_read_time(self._now())
        except Exception as exc:  # pragma: no cover - repository boundary
            raise PortfolioRecordedFactsReadError(
                "portfolio statistics are temporarily unavailable"
            ) from exc

        try:
            position_records = tuple(
                _coerce_position(
                    raw_position,
                    resolved_portfolio_id=initial_identity[0],
                )
                for raw_position in position_rows
            )
            if not isinstance(raw_statistics, Mapping):
                raise PortfolioRecordedFactsReadError(
                    "stored statistics payload has an invalid shape"
                )
            statistics = _coerce_statistics(cast(Mapping[str, object], raw_statistics))
        except PortfolioRecordedFactsReadError:
            raise
        except Exception as exc:  # pragma: no cover - malformed repository boundary
            raise PortfolioRecordedFactsReadError(
                "stored portfolio facts have an invalid shape"
            ) from exc
        try:
            final_context = self._resolve_access(
                user_id=normalized_user_id,
                portfolio_id=normalized_portfolio_id,
            )
        except (PortfolioNotFoundError, PortfolioAccessDeniedError):
            raise
        except Exception as exc:  # pragma: no cover - composition failure boundary
            raise PortfolioRecordedFactsReadError(
                "portfolio authorization recheck unavailable"
            ) from exc

        final_identity = _portfolio_identity(final_context)
        if final_identity != initial_identity or final_context.is_owner != context.is_owner:
            raise PortfolioRecordedFactsReadError(
                "portfolio scope changed while reading recorded facts"
            )

        position_page = _page(
            position_records,
            page=normalized_page,
            page_size=normalized_page_size,
        )
        position_clock = _read_clock(positions_started_at, positions_finished_at)
        statistics_clock = _read_clock(statistics_started_at, statistics_finished_at)

        (
            portfolio_id_value,
            portfolio_name,
            owner_user_id,
            owner_username,
            portfolio_is_active,
            _is_owner,
        ) = final_identity

        payload: PortfolioRecordedFactsPayload = {
            "portfolio_id": portfolio_id_value,
            "portfolio_name": portfolio_name,
            "portfolio_is_active": portfolio_is_active,
            "owner_user_id": owner_user_id,
            "owner_username": owner_username,
            "access_role": "owner" if final_context.is_owner else "observer",
            "positions": position_page.to_payload(),
            "statistics": statistics.to_payload(),
            "position_read_clock": position_clock.to_payload(),
            "statistics_read_clock": statistics_clock.to_payload(),
        }
        return PortfolioRecordedFactsReadResult(context=final_context, payload=payload)


def _utc_now() -> datetime:
    """Return the aware UTC clock used for application read boundaries."""

    return datetime.now(UTC)


def _positive_int(value: int | str, field_name: str) -> int:
    """Normalize a positive integer input without accepting booleans."""

    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise PortfolioRecordedFactsInputError(f"{field_name} must be a positive integer")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioRecordedFactsInputError(f"{field_name} must be a positive integer") from exc
    if normalized <= 0:
        raise PortfolioRecordedFactsInputError(f"{field_name} must be a positive integer")
    return normalized


def _page_size(value: int | str) -> int:
    """Normalize page size with the bounded UI limit."""

    normalized = _positive_int(value, "page_size")
    if normalized > MAX_PAGE_SIZE:
        raise PortfolioRecordedFactsInputError(f"page_size must be at most {MAX_PAGE_SIZE}")
    return normalized


def _aware_read_time(value: datetime) -> datetime:
    """Validate one aware read-boundary timestamp."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioRecordedFactsReadError("application read clock must be timezone-aware")
    return value


def _read_clock(started_at: datetime, finished_at: datetime) -> RecordedReadClock:
    """Build a non-source read clock and reject a backwards local clock."""

    if finished_at < started_at:
        raise PortfolioRecordedFactsReadError("application read clock moved backwards")
    return RecordedReadClock(started_at, finished_at)


def _page(
    records: tuple[RecordedPosition, ...], *, page: int, page_size: int
) -> RecordedPositionPage:
    """Slice a fully read list while retaining the total and continuation flag."""

    start = (page - 1) * page_size
    finish = start + page_size
    return RecordedPositionPage(
        count=len(records),
        page=page,
        page_size=page_size,
        has_next=finish < len(records),
        items=records[start:finish],
    )


def _legacy_position_source_ids(raw_positions: object) -> tuple[int, ...]:
    """Read unique Account position IDs before asking the ledger for knowledge flags."""

    if not isinstance(raw_positions, Sequence) or isinstance(raw_positions, (str, bytes)):
        raise PortfolioRecordedFactsReadError("stored position rows have an invalid shape")
    source_ids: list[int] = []
    for raw_position in raw_positions:
        if not isinstance(raw_position, Mapping):
            raise PortfolioRecordedFactsReadError("stored position payload has an invalid shape")
        source_ids.append(_required_int(cast(Mapping[str, object], raw_position), "id"))
    if len(source_ids) != len(set(source_ids)):
        raise PortfolioRecordedFactsReadError("stored position IDs are duplicated")
    return tuple(source_ids)


def _apply_authoritative_valuation_knowledge(
    raw_positions: Sequence[object],
    valuation_by_source_id: Mapping[int, bool],
) -> tuple[dict[str, object], ...]:
    """Null valuation fields unless the exact unified position says its mark is known."""

    prepared: list[dict[str, object]] = []
    for raw_position in raw_positions:
        if not isinstance(raw_position, Mapping):
            raise PortfolioRecordedFactsReadError("stored position payload has an invalid shape")
        payload = cast(Mapping[str, object], raw_position)
        source_id = _required_int(payload, "id")
        valuation_known = valuation_by_source_id.get(source_id, False)
        if not isinstance(valuation_known, bool):
            raise PortfolioRecordedFactsReadError("valuation knowledge flag is invalid")
        prepared_row = dict(payload)
        prepared_row["valuation_known"] = valuation_known
        if not valuation_known:
            prepared_row["current_price"] = None
            prepared_row["market_value"] = None
            prepared_row["unrealized_pnl"] = None
            prepared_row["unrealized_pnl_pct"] = None
        prepared.append(prepared_row)
    return tuple(prepared)


def _coerce_position(raw: object, *, resolved_portfolio_id: int) -> RecordedPosition:
    """Narrow one repository JSON row without changing native values."""

    if not isinstance(raw, Mapping):
        raise PortfolioRecordedFactsReadError("stored position payload has an invalid shape")
    payload = cast(Mapping[str, object], raw)
    portfolio_id = _required_int(payload, "portfolio")
    if portfolio_id != resolved_portfolio_id:
        raise PortfolioRecordedFactsReadError("stored position belongs to another portfolio")
    return RecordedPosition(
        id=_required_int(payload, "id"),
        portfolio=portfolio_id,
        portfolio_name=_required_text(payload, "portfolio_name"),
        asset_code=_required_text(payload, "asset_code"),
        asset_name=_required_text(payload, "asset_name"),
        asset_class=_required_text(payload, "asset_class"),
        shares=_required_float(payload, "shares"),
        avg_cost=_required_decimal(payload, "avg_cost"),
        current_price=_optional_decimal(payload, "current_price"),
        market_value=_optional_decimal(payload, "market_value"),
        unrealized_pnl=_optional_decimal(payload, "unrealized_pnl"),
        unrealized_pnl_pct=_optional_float(payload, "unrealized_pnl_pct"),
        valuation_known=_required_bool(payload, "valuation_known"),
        source=_required_text(payload, "source"),
        source_id=_optional_int(payload, "source_id"),
        currency_code=_optional_text(payload, "currency_code"),
        currency_name=_optional_text(payload, "currency_name"),
        currency_symbol=_optional_text(payload, "currency_symbol"),
        opened_at=_optional_datetime(payload, "opened_at"),
        updated_at=_optional_datetime(payload, "updated_at"),
    )


def _coerce_statistics(raw: Mapping[str, object]) -> RecordedStatistics:
    """Narrow the existing statistics dictionary without FX or freshness claims."""

    return RecordedStatistics(
        total_value=_optional_decimal(raw, "total_value"),
        total_cost=_required_decimal(raw, "total_cost"),
        total_pnl=_optional_decimal(raw, "total_pnl"),
        total_pnl_pct=_optional_float(raw, "total_pnl_pct"),
        position_count=_required_int(raw, "position_count"),
        asset_class_breakdown=_optional_float_mapping(raw, "asset_class_breakdown"),
        region_breakdown=_optional_float_mapping(raw, "region_breakdown"),
        valuation_known=_required_bool(raw, "valuation_known"),
        total_capital_inflow=_required_decimal(raw, "total_capital_inflow"),
        total_capital_outflow=_required_decimal(raw, "total_capital_outflow"),
        net_capital_flow=_required_decimal(raw, "net_capital_flow"),
    )


def _required_int(payload: Mapping[str, object], key: str) -> int:
    """Return a required integer payload field."""

    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return value


def _optional_int(payload: Mapping[str, object], key: str) -> int | None:
    """Return an optional integer payload field, preserving null."""

    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return value


def _required_text(payload: Mapping[str, object], key: str) -> str:
    """Return a required text payload field."""

    value = payload.get(key)
    if not isinstance(value, str):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return value


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    """Return an explicit Boolean knowledge flag without coercion."""

    value = payload.get(key)
    if not isinstance(value, bool):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return value


def _optional_text(payload: Mapping[str, object], key: str) -> str | None:
    """Return an optional text payload field without inferring a default."""

    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return value


def _required_float(payload: Mapping[str, object], key: str) -> float:
    """Return a finite numeric payload field as a float."""

    value = payload.get(key)
    if isinstance(value, bool):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    result = safe_float(value)
    if result is None:
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return result


def _optional_float(payload: Mapping[str, object], key: str) -> float | None:
    """Return an optional finite numeric payload field without replacing null."""

    if payload.get(key) is None:
        return None
    return _required_float(payload, key)


def _required_decimal(payload: Mapping[str, object], key: str) -> Decimal:
    """Return a finite Decimal payload field while preserving zero exactly."""

    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float)):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return result


def _optional_decimal(payload: Mapping[str, object], key: str) -> Decimal | None:
    """Return an optional Decimal payload field without replacing null."""

    value = payload.get(key)
    if value is None:
        return None
    return _required_decimal(payload, key)


def _optional_datetime(payload: Mapping[str, object], key: str) -> datetime | None:
    """Return an optional aware record clock, preserving its record semantics."""

    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    return value


def _float_mapping(payload: Mapping[str, object], key: str) -> dict[str, float]:
    """Narrow one aggregate mapping without converting its currency basis."""

    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
    result: dict[str, float] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str):
            raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
        if isinstance(raw_value, bool):
            raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
        converted = safe_float(raw_value)
        if converted is None:
            raise PortfolioRecordedFactsReadError(f"stored payload field {key} is invalid")
        result[raw_key] = converted
    return result


def _optional_float_mapping(payload: Mapping[str, object], key: str) -> dict[str, float] | None:
    """Narrow an optional breakdown while preserving unknown as null."""

    if payload.get(key) is None:
        return None
    return _float_mapping(payload, key)


def _portfolio_identity(
    context: PortfolioAccessContext,
) -> tuple[int, str, int, str, bool, bool]:
    """Validate the selected portfolio and return its stable read identity."""

    portfolio = context.portfolio
    portfolio_id = getattr(portfolio, "id", None)
    if not isinstance(portfolio_id, int) or isinstance(portfolio_id, bool):
        raise PortfolioRecordedFactsReadError("portfolio identity is unavailable")
    portfolio_name = getattr(portfolio, "name", None)
    if not isinstance(portfolio_name, str):
        raise PortfolioRecordedFactsReadError("portfolio name is unavailable")
    owner_user_id = getattr(portfolio, "user_id", None)
    if not isinstance(owner_user_id, int) or isinstance(owner_user_id, bool):
        raise PortfolioRecordedFactsReadError("portfolio owner identity is unavailable")
    owner_username = getattr(getattr(portfolio, "user", None), "username", None)
    if not isinstance(owner_username, str):
        raise PortfolioRecordedFactsReadError("portfolio owner identity is unavailable")
    portfolio_is_active = getattr(portfolio, "is_active", None)
    if not isinstance(portfolio_is_active, bool):
        raise PortfolioRecordedFactsReadError("portfolio status is unavailable")
    if not isinstance(context.is_owner, bool):
        raise PortfolioRecordedFactsReadError("portfolio access role is unavailable")
    return (
        portfolio_id,
        portfolio_name,
        owner_user_id,
        owner_username,
        portfolio_is_active,
        context.is_owner,
    )


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "PortfolioRecordedFactsInputError",
    "PortfolioRecordedFactsReadError",
    "PortfolioRecordedFactsReadResult",
    "PortfolioRecordedFactsReader",
]
