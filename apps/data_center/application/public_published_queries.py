"""Stable Data Center Application Public Ports.

Business applications may import this module, but must not import Data Center
ORM models, repositories or provider adapters.  The functions intentionally
return plain DTO-shaped values for the current migration bridge; new callers
can use the typed contracts in :mod:`apps.data_center.domain.contracts`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any

from apps.data_center.application.query_services import (
    fetch_price_bar_payloads,
    get_current_publication_gate,
    get_macro_indicator_metadata,
    get_runtime_macro_metadata_map,
    list_active_asset_codes,
    list_active_provider_summaries,
    list_price_covered_asset_codes,
    list_valuation_covered_asset_codes,
    query_financial_facts,
    query_latest_quote_payloads,
    query_published_a_share_behavior_payload,
    query_published_capital_flow_series,
    query_published_financial_facts,
    query_published_market_news,
    query_published_price_bar_series,
    query_published_quote_payloads,
    query_published_quote_series,
    query_published_sector_memberships,
    query_published_valuation_facts,
    query_valuation_facts,
)
from apps.data_center.composition import (
    get_asset_repository,
    get_canonical_publication_repository,
    get_macro_fact_repository,
    get_provider_config_repository,
)
from apps.data_center.domain.entities import MacroFact


def get_current_publication_freshness_gate(
    dataset_key: str,
    publication_key: str,
) -> dict[str, object] | None:
    """Return the freshness-validated gate for a current publication."""

    return get_current_publication_gate(dataset_key, publication_key)


def get_decision_publication_gate(
    dataset_key: str,
    publication_key: str = "current",
) -> dict[str, object] | None:
    """Return one merged publication and freshness gate for decision APIs.

    This port keeps Interface, SDK and MCP callers on the same fail-closed
    semantics without exposing Data Center repositories outside Application.
    """

    publication = get_current_publication(dataset_key, publication_key)
    if publication is None:
        return None
    freshness = get_current_publication_freshness_gate(dataset_key, publication_key)
    if freshness is None:
        return {
            **publication,
            "must_not_use_for_decision": True,
            "blocked_reason": "publication_freshness_unverified",
            "freshness_status": "unverified",
        }
    return {**publication, **freshness}


def get_published_quote_payloads(
    asset_codes: list[str],
    *,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing quotes only when publication is current."""

    return query_published_quote_payloads(asset_codes, publication_key=publication_key)


def get_published_latest_quote_payload(
    asset_code: str,
    *,
    publication_key: str = "current",
) -> dict[str, object] | None:
    """Return one publication-bound quote payload for a decision consumer.

    A blocked publication is returned as an explicit blocked payload so callers
    can preserve the reason in risk evidence; a usable publication with no
    selected member returns ``None``.
    """

    normalized_code = str(asset_code or "").strip().upper()
    if not normalized_code:
        return None
    published = get_published_quote_payloads(
        [normalized_code],
        publication_key=publication_key,
    )
    if bool(published.get("must_not_use_for_decision")):
        return {
            "asset_code": normalized_code,
            "is_stale": True,
            "must_not_use_for_decision": True,
            "freshness_status": published.get("freshness_status") or "blocked",
            "blocked_reason": published.get("blocked_reason") or "canonical_publication_missing",
            "publication_id": published.get("publication_id"),
            "dataset_key": published.get("dataset_key"),
        }
    rows = published.get("rows")
    if not isinstance(rows, list):
        return None
    row = next((item for item in rows if isinstance(item, dict)), None)
    if row is None:
        return None
    result = dict(row)
    for key in (
        "publication_id",
        "dataset_key",
        "publication_key",
        "published_at",
        "as_of",
        "observed_at",
        "age_seconds",
        "max_age_seconds",
        "freshness_status",
        "blocked_reason",
    ):
        if key not in result and key in published:
            result[key] = published[key]
    result.setdefault("is_stale", False)
    result.setdefault("must_not_use_for_decision", False)
    return result


def get_published_quote_series(
    asset_code: str,
    *,
    publication_key: str = "current",
    snapshot_date: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read current intraday quote snapshots behind the Publication gate."""

    return query_published_quote_series(
        asset_code,
        publication_key=publication_key,
        snapshot_date=snapshot_date,
        limit=limit,
    )


def get_published_price_bar_series(
    asset_code: str,
    *,
    publication_key: str = "current",
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> dict[str, object]:
    """Read decision-facing price bars only when publication is current."""

    return query_published_price_bar_series(
        asset_code,
        publication_key=publication_key,
        start=start,
        end=end,
        limit=limit,
    )


def get_published_sector_memberships(
    sector_code: str,
    *,
    as_of: date | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing sector membership facts behind publication."""

    return query_published_sector_memberships(
        sector_code,
        as_of=as_of,
        publication_key=publication_key,
    )


def get_published_market_news(
    *,
    asset_code: str | None = None,
    target_date: date | None = None,
    limit: int = 50,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing news facts behind publication."""

    return query_published_market_news(
        asset_code=asset_code,
        target_date=target_date,
        limit=limit,
        publication_key=publication_key,
    )


def get_published_capital_flow_series(
    asset_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing capital-flow facts behind publication."""

    return query_published_capital_flow_series(
        asset_code,
        start=start,
        end=end,
        limit=limit,
        publication_key=publication_key,
    )


def get_published_financial_facts(
    asset_code: str,
    *,
    limit: int = 20,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing financial facts behind a publication gate."""

    return query_published_financial_facts(
        asset_code,
        limit=limit,
        publication_key=publication_key,
    )


def get_published_valuation_facts(
    asset_code: str,
    *,
    as_of: date | None = None,
    limit: int | None = None,
    publication_key: str = "current",
) -> dict[str, object]:
    """Read decision-facing valuation facts behind a publication gate."""

    return query_published_valuation_facts(
        asset_code,
        as_of=as_of,
        limit=limit,
        publication_key=publication_key,
    )


def get_macro_indicator_catalog(indicator_code: str) -> dict[str, Any]:
    """Read one indicator catalog entry through the application port."""

    return get_macro_indicator_metadata(indicator_code)


def list_active_data_sources() -> list[dict[str, str]]:
    """Read active provider summaries through the canonical application port."""

    return list_active_provider_summaries()


def save_data_source_configuration(
    *,
    source_type: str,
    name: str,
    api_key: str,
    http_url: str = "",
    api_endpoint: str = "",
) -> dict[str, str | int | bool]:
    """Persist one provider configuration through the Data Center boundary."""

    from apps.data_center.domain.entities import ProviderConfig

    existing = get_provider_config_repository().get_active_by_type(source_type)
    current = existing[0] if existing else None
    saved = get_provider_config_repository().save(
        ProviderConfig(
            id=current.id if current is not None else None,
            name=name,
            source_type=source_type,
            is_active=True,
            priority=current.priority if current is not None else 100,
            api_key=api_key,
            api_secret=current.api_secret if current is not None else "",
            http_url=http_url,
            api_endpoint=api_endpoint,
            extra_config=current.extra_config if current is not None else {},
            description=current.description if current is not None else "",
        )
    )
    return {
        "id": saved.id or 0,
        "name": saved.name,
        "source_type": saved.source_type,
        "is_active": saved.is_active,
    }


def update_asset_display_name(asset_code: str, name: str) -> bool:
    """Update an existing canonical asset name without exposing its ORM."""

    asset_repo = get_asset_repository()
    asset = asset_repo.get_by_code(asset_code)
    normalized_name = name.strip()
    if asset is None or not normalized_name:
        return False
    asset_repo.upsert(replace(asset, name=normalized_name, short_name=normalized_name))
    return True


def save_macro_facts(facts: list[MacroFact]) -> int:
    """Persist validated canonical macro facts through the application port."""

    return get_macro_fact_repository().bulk_upsert(facts)


def list_macro_facts_by_original_unit(
    original_unit: str,
    *,
    limit: int = 100_000,
) -> list[MacroFact]:
    """List canonical macro facts for a bounded unit-normalization repair."""

    return get_macro_fact_repository().list_by_original_unit(original_unit, limit=limit)


def get_macro_runtime_metadata() -> dict[str, dict[str, Any]]:
    """Read the catalog-backed macro runtime metadata map."""

    return get_runtime_macro_metadata_map()


def get_provider_settings_payload() -> dict[str, Any]:
    """Read persisted provider behaviour settings through the public port."""

    from apps.data_center.application.interface_services import load_provider_settings_payload

    return dict(load_provider_settings_payload())


def list_macro_indicator_codes() -> list[str]:
    """Return active macro indicator codes from the canonical catalog."""

    return sorted(get_macro_runtime_metadata())


def get_market_breadth_snapshot() -> dict[str, Any]:
    """Read the canonical market-breadth snapshot and reliability contract."""

    return query_published_a_share_behavior_payload()


def get_active_stock_fact_coverage_payload() -> dict[str, Any]:
    """Return the diagnostic coverage payload through the public port."""

    from apps.data_center.application.query_services import (
        get_active_stock_fact_coverage_payload as _get_coverage,
    )

    return _get_coverage()


def get_decision_data_readiness_payload(
    *,
    asset_codes: list[str] | None = None,
    quote_max_age_hours: float | None = None,
) -> dict[str, Any]:
    """Return the fail-closed decision-data readiness payload."""

    from apps.data_center.application.interface_services import (
        get_decision_data_readiness_payload as _get_readiness,
    )

    return _get_readiness(
        asset_codes=asset_codes,
        quote_max_age_hours=quote_max_age_hours,
    )


def get_decision_provider_capability_health_payload() -> dict[str, Any]:
    """Return provider capability health through the public application port."""

    from apps.data_center.application.interface_services import (
        get_decision_provider_capability_health_payload as _get_capability_health,
    )

    return _get_capability_health()


def resolve_asset_payload(asset_code: str) -> dict[str, Any] | None:
    """Resolve one canonical AssetMaster record into a plain public payload."""

    normalized_code = str(asset_code or "").strip().upper()
    if not normalized_code:
        return None

    from apps.data_center.application.dtos import ResolveAssetRequest
    from apps.data_center.application.interface_services import make_resolve_asset_use_case

    response = make_resolve_asset_use_case().execute(
        ResolveAssetRequest(code=normalized_code),
    )
    if response is None:
        return None
    return response.to_dict()


def list_active_stock_codes() -> list[str]:
    """Read the canonical active A-share universe."""

    return list_active_asset_codes()


def list_price_covered_codes(as_of: date | None = None) -> list[str]:
    """Read canonical price coverage through a bounded application port."""

    return list_price_covered_asset_codes(as_of)


def list_valuation_covered_codes(as_of: date | None = None) -> list[str]:
    """Read canonical valuation coverage through a bounded application port."""

    return list_valuation_covered_asset_codes(as_of)


def get_financial_facts(
    asset_code: str,
    *,
    limit: int = 20,
    as_of: date | None = None,
) -> list[dict[str, object]]:
    """Read canonical financial facts for one asset through an optional as-of date."""

    return query_financial_facts(asset_code, limit=limit, end=as_of)


def get_valuation_facts(
    asset_code: str,
    *,
    as_of: date | None = None,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Read canonical valuation facts for one asset."""

    return query_valuation_facts(asset_code, as_of=as_of, limit=limit)


def get_latest_quote_payloads(
    asset_codes: list[str],
    *,
    observed_after: datetime | None = None,
) -> list[dict[str, object]]:
    """Read latest canonical quotes for a bounded list of assets."""

    return query_latest_quote_payloads(asset_codes, observed_after=observed_after)


def get_price_bar_series(
    asset_code: str,
    *,
    start: date | None = None,
    end: date | None = None,
    limit: int = 500,
) -> list[dict[str, object]]:
    """Read canonical OHLCV bars through the public query port."""

    return fetch_price_bar_payloads(
        asset_code=asset_code,
        start_date=start,
        end_date=end,
        limit=limit,
    )


def get_current_publication(
    dataset_key: str,
    publication_key: str,
) -> dict[str, object] | None:
    """Return the active published selection for a canonical dataset scope."""

    publication = get_canonical_publication_repository().get_current(dataset_key, publication_key)
    if publication is None:
        return None
    return {
        "publication_id": publication.publication_id,
        "dataset_key": publication.dataset_key,
        "publication_key": publication.publication_key,
        "policy_version": publication.policy_version,
        "state": publication.state.value,
        "selected_source": publication.selected_source,
        "publication_hash": publication.publication_hash,
        "coverage_ratio": publication.coverage.coverage_ratio,
        "coverage": {
            "requested_count": publication.coverage.requested_count,
            "eligible_count": publication.coverage.eligible_count,
            "selected_count": publication.coverage.selected_count,
            "missing_count": publication.coverage.missing_count,
            "conflict_count": publication.coverage.conflict_count,
        },
        "published_at": publication.published_at.isoformat() if publication.published_at else None,
        "as_of": publication.as_of.isoformat() if publication.as_of else None,
        "must_not_use_for_decision": publication.must_not_use_for_decision,
        "blocked_reason": publication.blocked_reason,
    }


def get_publication_as_of(
    dataset_key: str,
    publication_key: str,
    as_of: datetime,
) -> dict[str, object] | None:
    """Return the publication visible at an explicit historical boundary."""

    publication = get_canonical_publication_repository().get_as_of(
        dataset_key,
        publication_key,
        as_of,
    )
    if publication is None:
        return None
    return {
        "publication_id": publication.publication_id,
        "dataset_key": publication.dataset_key,
        "publication_key": publication.publication_key,
        "policy_version": publication.policy_version,
        "state": publication.state.value,
        "selected_source": publication.selected_source,
        "publication_hash": publication.publication_hash,
        "coverage_ratio": publication.coverage.coverage_ratio,
        "published_at": publication.published_at.isoformat() if publication.published_at else None,
        "as_of": publication.as_of.isoformat() if publication.as_of else None,
        "must_not_use_for_decision": publication.must_not_use_for_decision,
        "blocked_reason": publication.blocked_reason,
    }
