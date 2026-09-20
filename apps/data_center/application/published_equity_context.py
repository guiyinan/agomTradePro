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
from apps.data_center.publication_read_composition import publication_snapshot


@publication_snapshot()
def _dataset_payloads(
    dataset_key: str, asset_codes: list[str], publication_key: str
) -> dict[str, dict[str, object]]:
    """Keep the full proof and selected facts inside one database snapshot."""

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
    for code in asset_codes:
        selected = members_by_asset.get(code, [])
        asset_gate = dict(gate)
        if not selected:
            result[code] = blocked_publication_members_result(asset_gate)
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
            rows = queries.query_valuation_facts(code, as_of=as_of, limit=1, fact_pks=fact_pks)
        result[code] = {"rows": rows, **asset_gate}
    return result


def get_published_equity_context_payloads(
    asset_codes: list[str],
    *,
    publication_key: str = "current",
    include_price: bool = True,
    include_financial: bool = True,
    include_valuation: bool = True,
) -> dict[str, dict[str, dict[str, object]]]:
    """Read requested equity datasets with one full integrity proof per dataset.

    Proofs are local to each read-only database snapshot, never persisted or
    reused across calls. Freshness remains asset-specific only for prices.
    """

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
            for code, payload in _dataset_payloads(dataset, codes, publication_key).items():
                result[code][name] = payload
    return result
