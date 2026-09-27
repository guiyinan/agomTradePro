"""Prepare one immutable, full-scope quote response for bounded fact writes."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import TypedDict

from apps.data_center.application.full_market_task_support import asset_code_scope_sha256
from apps.data_center.domain.entities import QuoteSnapshot
from apps.data_center.domain.market_time import cn_market_date_from_observation
from apps.data_center.domain.protocols import SessionQuoteBatchProviderProtocol
from core.exceptions import DataFetchError

from .batch_identity import require_exact_asset_identities


class _QuoteSessionEvidence(TypedDict):
    provider_id: int
    provider_name: str
    source_type: str
    target_trade_date: str
    universe_sha256: str
    quote_rows_sha256: str
    response_completed_at: str | None
    raw_response_sha256s: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreparedQuoteSession:
    """A task-local exact-session response bound to one provider and universe."""

    provider_id: int
    provider_name: str
    source_type: str
    target_trade_date: date
    universe_codes: tuple[str, ...]
    universe_sha256: str
    _quote_rows: tuple[QuoteSnapshot, ...] = field(repr=False, compare=False)
    quote_rows_sha256: str
    response_completed_at: datetime | None
    raw_response_sha256s: tuple[str, ...]

    @property
    def quote_rows(self) -> tuple[QuoteSnapshot, ...]:
        """Return detached rows so callers cannot mutate the frozen response."""

        return tuple(replace(quote, extra=copy.deepcopy(quote.extra)) for quote in self._quote_rows)

    def quote_rows_for(self, asset_codes: tuple[str, ...]) -> tuple[QuoteSnapshot, ...]:
        """Return copied rows for one exact sub-batch without another provider call."""

        requested = tuple(str(code or "").strip().upper() for code in asset_codes)
        if (
            not requested
            or len(requested) != len(set(requested))
            or not set(requested).issubset(self.universe_codes)
        ):
            raise DataFetchError(
                "Prepared quote batch falls outside its frozen universe",
                code="CURRENT_QUOTE_SESSION_SCOPE_MISMATCH",
            )
        by_code = {quote.asset_code: quote for quote in self._quote_rows}
        evidence: _QuoteSessionEvidence = {
            "provider_id": self.provider_id,
            "provider_name": self.provider_name,
            "source_type": self.source_type,
            "target_trade_date": self.target_trade_date.isoformat(),
            "universe_sha256": self.universe_sha256,
            "quote_rows_sha256": self.quote_rows_sha256,
            "response_completed_at": (
                self.response_completed_at.isoformat()
                if self.response_completed_at is not None
                else None
            ),
            "raw_response_sha256s": self.raw_response_sha256s,
        }
        return tuple(
            replace(
                by_code[code],
                extra={
                    **copy.deepcopy(by_code[code].extra),
                    "market_publication_quote_session": evidence,
                },
            )
            for code in requested
        )


def prepare_quote_session(
    *,
    provider: SessionQuoteBatchProviderProtocol,
    provider_id: int,
    provider_name: str,
    source_type: str,
    asset_codes: tuple[str, ...],
    target_trade_date: date,
) -> PreparedQuoteSession:
    """Fetch one full-market session and freeze its rows, times, and scope identity."""

    if isinstance(provider_id, bool) or not isinstance(provider_id, int) or provider_id <= 0:
        raise DataFetchError(
            "Quote session provider identity is invalid",
            code="CURRENT_QUOTE_SESSION_SCOPE_INVALID",
        )
    if not isinstance(target_trade_date, date) or isinstance(target_trade_date, datetime):
        raise DataFetchError(
            "Quote session target date is invalid",
            code="CURRENT_QUOTE_SESSION_SCOPE_INVALID",
        )
    if (
        not isinstance(provider_name, str)
        or not provider_name.strip()
        or not isinstance(source_type, str)
        or not source_type.strip()
    ):
        raise DataFetchError(
            "Quote session provider identity is incomplete",
            code="CURRENT_QUOTE_SESSION_SCOPE_INVALID",
        )
    requested_codes = tuple(str(code or "").strip().upper() for code in asset_codes)
    if (
        not requested_codes
        or any(not code for code in requested_codes)
        or requested_codes != tuple(sorted(set(requested_codes)))
    ):
        raise DataFetchError(
            "Quote session universe is not a canonical frozen scope",
            code="MARKET_UNIVERSE_SCOPE_INVALID",
        )

    response = provider.fetch_quote_snapshots_for_session(list(requested_codes), target_trade_date)
    require_exact_asset_identities(
        requested_asset_codes=requested_codes,
        returned_asset_codes=[quote.asset_code for quote in response],
        label="quote session",
    )
    quotes = tuple(
        sorted(
            (replace(quote, extra=copy.deepcopy(quote.extra)) for quote in response),
            key=lambda quote: quote.asset_code,
        )
    )
    fetched_times: set[datetime] = set()
    raw_hashes: set[str] = set()
    for quote in quotes:
        if (
            cn_market_date_from_observation(quote.snapshot_at) != target_trade_date
            or quote.fetched_at is None
            or not quote.source.strip()
        ):
            raise DataFetchError(
                "Quote session contains an invalid observation or source time",
                code="CURRENT_QUOTE_SESSION_DATE_MISMATCH",
            )
        fetched_times.add(quote.fetched_at)
        raw_hash = quote.extra.get("raw_payload_hash")
        if raw_hash in (None, ""):
            continue
        if not isinstance(raw_hash, str) or re.fullmatch(r"[0-9a-f]{64}", raw_hash) is None:
            raise DataFetchError(
                "Quote session raw response identity is invalid",
                code="CURRENT_QUOTE_SESSION_EVIDENCE_INVALID",
            )
        raw_scope = quote.extra.get("raw_payload_scope")
        if raw_scope != "batch_response_body":
            raise DataFetchError(
                "Quote session raw response scope is invalid",
                code="CURRENT_QUOTE_SESSION_EVIDENCE_INVALID",
            )
        raw_hashes.add(raw_hash)

    if len(fetched_times) != 1 or len(raw_hashes) > 1:
        raise DataFetchError(
            "Quote session rows do not share one response identity and completion time",
            code="CURRENT_QUOTE_SESSION_EVIDENCE_INVALID",
        )

    scope_sha256 = asset_code_scope_sha256(requested_codes)
    rows_sha256 = _quote_rows_sha256(quotes)
    completed_at = next(iter(fetched_times))
    return PreparedQuoteSession(
        provider_id=provider_id,
        provider_name=provider_name,
        source_type=source_type,
        target_trade_date=target_trade_date,
        universe_codes=requested_codes,
        universe_sha256=scope_sha256,
        _quote_rows=quotes,
        quote_rows_sha256=rows_sha256,
        response_completed_at=completed_at,
        raw_response_sha256s=tuple(sorted(raw_hashes)),
    )


def _quote_rows_sha256(quotes: tuple[QuoteSnapshot, ...]) -> str:
    """Hash the immutable normalized provider rows in canonical asset order."""

    encoded = json.dumps(
        [quote.to_dict() for quote in quotes],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = ["PreparedQuoteSession", "prepare_quote_session"]
