"""Quote payload selection and publication-identity compatibility helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from apps.data_center.domain.protocols import QuoteSnapshotRepositoryProtocol


def _latest_quote_payload_rows(
    *,
    repository: QuoteSnapshotRepositoryProtocol,
    asset_codes: list[str],
    observed_after: datetime | None = None,
    observed_before: datetime | None = None,
    fact_pks: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    """Select bounded quote rows and preserve their canonical DTO serialization."""
    rows: list[dict[str, object]] = []
    for asset_code in asset_codes:
        quote = (
            repository.get_latest(asset_code)
            if fact_pks is None
            else repository.get_latest(asset_code, fact_pks=fact_pks)
        )
        if quote is None:
            continue
        if observed_after is not None and quote.snapshot_at < observed_after:
            continue
        if observed_before is not None and quote.snapshot_at > observed_before:
            continue
        rows.append(quote.to_dict())
    return rows


def _clear_unbound_quote_metric_evidence(
    rows: list[dict[str, object]],
    *,
    policy_identity: object,
) -> list[dict[str, object]]:
    """Keep p1 quote prices while removing metrics not bound by the member hash."""
    if not isinstance(policy_identity, str) or not policy_identity.startswith("p2:"):
        # The v1 publication hash deliberately excludes fact_content_hash. Keep
        # its price payload compatible, but do not expose a later-added metric
        # as publication-bound decision evidence.
        for row in rows:
            row["change_pct"] = None
            row["change_pct_source_contract"] = None
            extra = row.get("extra")
            if isinstance(extra, Mapping):
                sanitized_extra = dict(extra)
                sanitized_extra.pop("change_pct_source_contract", None)
                row["extra"] = sanitized_extra
    return rows
