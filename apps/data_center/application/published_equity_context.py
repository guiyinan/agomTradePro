"""Bounded equity reads that validate each complete publication once per batch."""

from __future__ import annotations

from datetime import UTC, datetime

from apps.data_center.application import query_services as queries
from apps.data_center.application.publication_query_bounds import (
    blocked_publication_members_result,
    blocked_publication_result,
    publication_as_of_datetime,
    publication_freshness_gate,
)
from apps.data_center.composition import get_canonical_publication_repository
from apps.data_center.domain.control_plane import PublicationMember
from apps.data_center.publication_read_composition import (
    publication_snapshot,
    publication_snapshot_for_datasets,
)

_MAX_PUBLISHED_VALUATION_ROWS = 5000
_EQUITY_ANALYSIS_DATASET_KEYS = (
    "equity.financial.fact",
    "equity.price.bar",
    "equity.valuation.fact",
)


@publication_snapshot()
def _dataset_payloads(
    dataset_key: str,
    asset_codes: list[str],
    publication_key: str,
    valuation_limit: int = 1,
) -> dict[str, dict[str, object]]:
    """Keep the full proof and selected facts inside one database snapshot."""

    if dataset_key == "equity.valuation.fact":
        _validate_valuation_limit(valuation_limit)

    reference = datetime.now(UTC)
    gate = queries._publication_gate(dataset_key, publication_key, now=reference)
    is_price = dataset_key == "equity.price.bar"
    if gate is None or (
        gate.get("must_not_use_for_decision")
        and not (is_price and gate.get("blocked_reason") == "canonical_publication_stale")
    ):
        return {code: blocked_publication_result(gate) for code in asset_codes}

    members_by_asset: dict[str, list[PublicationMember]] = {}
    for member in get_canonical_publication_repository().list_members(str(gate["publication_id"])):
        code = member.natural_key.split(":", 1)[0].strip().upper()
        members_by_asset.setdefault(code, []).append(member)

    result: dict[str, dict[str, object]] = {}
    publication = get_canonical_publication_repository().get_current(dataset_key, publication_key)
    scope_blocks_by_code = {
        block.asset_code.strip().upper(): block
        for block in (() if publication is None else publication.scope_blocks)
    }
    for code in asset_codes:
        selected = members_by_asset.get(code, [])
        asset_gate = dict(gate)
        if not selected:
            scope_block = scope_blocks_by_code.get(code)
            blocked = blocked_publication_members_result(
                asset_gate,
                reason=(
                    scope_block.reason_code
                    if scope_block is not None
                    else "canonical_publication_members_missing"
                ),
            )
            if scope_block is not None:
                blocked["scope_block"] = scope_block.to_dict()
            result[code] = blocked
            continue
        if is_price:
            age_limit = gate.get("max_age_seconds")
            if not isinstance(age_limit, int) or isinstance(age_limit, bool):
                raise ValueError("validated publication freshness limit must be an integer")
            asset_gate.update(
                must_not_use_for_decision=False,
                blocked_reason="",
                freshness_scope="asset",
                asset_code=code,
            )
            observed_at = (
                min(member.observed_at for member in selected if member.observed_at is not None)
                if all(member.observed_at is not None for member in selected)
                else None
            )
            asset_gate = publication_freshness_gate(
                asset_gate,
                observed_at=observed_at,
                publication_as_of=publication_as_of_datetime(gate),
                reference=reference,
                max_age_seconds=age_limit,
            )
        if asset_gate.get("must_not_use_for_decision"):
            result[code] = blocked_publication_result(asset_gate)
            continue
        fact_pks = [member.fact_pk for member in selected]
        as_of = queries._publication_as_of_date(asset_gate)
        if is_price:
            rows = queries.fetch_price_bar_payloads(
                asset_code=code, start_date=None, end_date=as_of, limit=1, fact_pks=fact_pks
            )
        elif dataset_key == "equity.financial.fact":
            rows = queries.query_financial_facts(code, limit=100, end=as_of, fact_pks=fact_pks)
        else:
            rows = queries.query_valuation_facts(
                code,
                as_of=as_of,
                limit=valuation_limit,
                fact_pks=fact_pks,
            )
        result[code] = {"rows": rows, **asset_gate}
    return result


def get_published_equity_context_payloads(
    asset_codes: list[str],
    *,
    publication_key: str = "current",
    include_price: bool = True,
    include_financial: bool = True,
    include_valuation: bool = True,
    valuation_limit: int = 1,
) -> dict[str, dict[str, dict[str, object]]]:
    """Read requested equity datasets with one full integrity proof per dataset.

    Proofs are local to each read-only database snapshot, never persisted or
    reused across calls. Freshness remains asset-specific only for prices.
    """

    if include_valuation:
        _validate_valuation_limit(valuation_limit)
    codes = list(dict.fromkeys(code.strip().upper() for code in asset_codes if code.strip()))
    if not codes:
        return {}
    result: dict[str, dict[str, dict[str, object]]] = {code: {} for code in codes}
    for name, dataset, enabled in (
        ("price", "equity.price.bar", include_price),
        ("financial", "equity.financial.fact", include_financial),
        ("valuation", "equity.valuation.fact", include_valuation),
    ):
        if enabled:
            for code, payload in _dataset_payloads(
                dataset,
                codes,
                publication_key,
                valuation_limit,
            ).items():
                result[code][name] = payload
    return result


def get_published_equity_analysis_context_payloads(
    asset_codes: list[str],
    *,
    publication_key: str = "current",
    valuation_limit: int = 1,
) -> dict[str, dict[str, dict[str, object]]]:
    """Read price, financial, and valuation evidence in one shared snapshot.

    The pool-facing context keeps its existing independent read semantics.
    This analysis-specific port acquires all three dataset boundaries before
    any selected-member payload is read; a snapshot or lock timeout propagates
    and fails the whole analysis read closed.
    """

    _validate_valuation_limit(valuation_limit)
    codes = list(dict.fromkeys(code.strip().upper() for code in asset_codes if code.strip()))
    if not codes:
        return {}
    return _read_published_equity_analysis_context_payloads(
        codes,
        publication_key=publication_key,
        valuation_limit=valuation_limit,
    )


@publication_snapshot_for_datasets(_EQUITY_ANALYSIS_DATASET_KEYS)
def _read_published_equity_analysis_context_payloads(
    asset_codes: list[str],
    *,
    publication_key: str,
    valuation_limit: int,
) -> dict[str, dict[str, dict[str, object]]]:
    """Perform the all-dataset read after acquiring each boundary up front."""

    return get_published_equity_context_payloads(
        asset_codes,
        publication_key=publication_key,
        include_price=True,
        include_financial=True,
        include_valuation=True,
        valuation_limit=valuation_limit,
    )


def _validate_valuation_limit(valuation_limit: int) -> None:
    """Reject unbounded or invalid published valuation history requests."""

    if (
        not isinstance(valuation_limit, int)
        or isinstance(valuation_limit, bool)
        or valuation_limit < 1
        or valuation_limit > _MAX_PUBLISHED_VALUATION_ROWS
    ):
        raise ValueError(
            f"valuation_limit must be an integer from 1 to {_MAX_PUBLISHED_VALUATION_ROWS}"
        )
