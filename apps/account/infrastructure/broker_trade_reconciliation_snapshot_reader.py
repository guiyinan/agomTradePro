"""Read Account and unified local balances for reconciliation previews."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from django.utils import timezone

from apps.account.application.broker_trade_projection_contracts import (
    BrokerTradeProjectionGateway,
)
from apps.account.application.broker_trade_reconciliation_contracts import (
    BalanceSnapshot,
    BalanceSnapshotKind,
    BrokerBalancePreview,
    ValuationStatus,
)
from apps.account.domain.asset_type_mapping import map_account_asset_type_strict
from apps.account.domain.broker_trade_reconciliation_fingerprints import canonical_float
from apps.account.infrastructure.models import AssetMetadataModel, PortfolioModel, PositionModel
from core.exceptions import InvalidInputError

from .broker_trade_reconciliation_codec import _balance_hash


class BrokerBalanceSnapshotMixin:
    """Capture account and unified position snapshots without writing ledger rows."""

    _projection_service: BrokerTradeProjectionGateway

    def capture_balance_preview(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        asset_codes: tuple[str, ...],
    ) -> BrokerBalancePreview:
        """Capture Account and unified balances without creating ledger rows."""

        portfolio = PortfolioModel._default_manager.filter(
            pk=portfolio_id, user_id=owner_user_id
        ).first()
        if portfolio is None:
            raise InvalidInputError("portfolio is not owned by the preview owner")
        codes = tuple(sorted(set(asset_codes)))
        legacy_rows = list(
            PositionModel._default_manager.filter(
                portfolio_id=portfolio_id,
                asset_code__in=codes,
                is_closed=False,
            )
            .select_related("portfolio")
            .order_by("asset_code", "pk")
        )
        by_code: dict[str, list[PositionModel]] = {code: [] for code in codes}
        for row in legacy_rows:
            by_code.setdefault(row.asset_code, []).append(row)
        legacy_ids = {
            code: rows[0].pk if len(rows) == 1 else None for code, rows in by_code.items()
        }
        service = self._projection_service
        unified_rows = service.capture_position_snapshots(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            portfolio_name=portfolio.name,
            asset_codes=codes,
            legacy_position_ids=legacy_ids,
        )
        unified_by_code = {snapshot.asset_code: snapshot for snapshot in unified_rows}
        metadata = {
            item.asset_code: item
            for item in AssetMetadataModel._default_manager.filter(asset_code__in=codes)
        }
        snapshots: list[BalanceSnapshot] = []
        for code in codes:
            legacy_list = by_code.get(code, [])
            legacy = legacy_list[0] if len(legacy_list) == 1 else None
            unified = unified_by_code.get(code)
            reason: str | None = None
            if len(legacy_list) > 1:
                reason = "LEGACY_POSITION_AMBIGUOUS"
            elif unified is not None and unified.blocked_reason_code is not None:
                reason = unified.blocked_reason_code
            if (
                legacy is None
                and unified is not None
                and unified.position_map_source_id is not None
            ):
                mapped_legacy = PositionModel._default_manager.filter(
                    pk=unified.position_map_source_id,
                    portfolio_id=portfolio_id,
                ).first()
                reason = reason or (
                    "POSITION_MAP_TO_CLOSED_LEGACY_POSITION"
                    if mapped_legacy is not None and mapped_legacy.is_closed
                    else "LEGACY_POSITION_INDEX_MISMATCH"
                )
            if legacy is not None and map_account_asset_type_strict(legacy.asset_class) is None:
                reason = reason or "ASSET_TYPE_UNSUPPORTED"
            elif legacy is None and unified is None and code not in metadata:
                reason = reason or "ASSET_METADATA_MISSING"
            has_unified = unified is not None and unified.unified_position_id is not None
            kind: BalanceSnapshotKind
            valuation_status: ValuationStatus
            if reason is not None:
                kind = "blocked"
            elif has_unified:
                kind = "unified"
            elif legacy is not None:
                kind = "legacy"
            else:
                kind = "empty"
            if has_unified and unified is not None:
                total_shares = (
                    float(unified.total_shares) if unified.total_shares is not None else None
                )
                available = (
                    float(unified.available_quantity)
                    if unified.available_quantity is not None
                    else None
                )
                available_known = unified.available_quantity_known
                average_cost = unified.average_cost
                reference_mark = unified.reference_mark
                valuation_status = "unconfirmed" if unified.valuation_known else "unknown"
                position_id = unified.unified_position_id
                legacy_position_id = (
                    legacy.pk if legacy is not None else unified.position_map_source_id
                )
                account_id = unified.account_id
                mapping_id = unified.account_mapping_id
                mark_as_of = (
                    unified.source_updated_at
                    if unified.valuation_known is True and reference_mark is not None
                    else None
                )
                source_updated = unified.source_updated_at
                local_identity = {
                    "sim_position_id": position_id,
                    "sim_position_map_source_id": unified.position_map_source_id,
                    "sim_position_map_target_id": unified.position_map_target_id,
                    "sim_position_map_state": unified.position_map_state,
                    "sim_quantity": (
                        str(unified.total_shares) if unified.total_shares is not None else None
                    ),
                    "sim_cost": (
                        str(unified.average_cost) if unified.average_cost is not None else None
                    ),
                    "sim_mark": (
                        str(unified.reference_mark) if unified.reference_mark is not None else None
                    ),
                    "sim_valuation_known": unified.valuation_known,
                }
                if legacy is not None:
                    local_identity["legacy_position_id"] = legacy.pk
                    local_identity["legacy_quantity"] = str(legacy.shares)
                    local_identity["legacy_cost"] = str(legacy.avg_cost)
                    local_identity["legacy_mark"] = (
                        str(legacy.current_price) if legacy.current_price is not None else None
                    )
                    local_identity["legacy_updated_at"] = legacy.updated_at.isoformat()
            elif legacy is not None:
                metadata_row = metadata.get(code)
                total_shares = float(legacy.shares)
                available = None
                available_known = False
                average_cost = Decimal(legacy.avg_cost)
                reference_mark = (
                    Decimal(legacy.current_price) if legacy.current_price is not None else None
                )
                valuation_status = "unconfirmed" if reference_mark is not None else "unknown"
                position_id = None
                legacy_position_id = int(legacy.pk)
                account_id = unified.account_id if unified is not None else None
                mapping_id = unified.account_mapping_id if unified is not None else None
                mark_as_of = legacy.updated_at if reference_mark is not None else None
                source_updated = legacy.updated_at
                local_identity = {
                    "legacy_position_id": legacy.pk,
                    "legacy_quantity": str(legacy.shares),
                    "legacy_cost": str(legacy.avg_cost),
                    "legacy_mark": (
                        str(legacy.current_price) if legacy.current_price is not None else None
                    ),
                    "legacy_asset_class": legacy.asset_class,
                    "legacy_updated_at": legacy.updated_at.isoformat(),
                    "metadata_id": metadata_row.pk if metadata_row is not None else None,
                }
            else:
                total_shares = None
                available = None
                available_known = None
                average_cost = None
                reference_mark = None
                valuation_status = "unknown"
                position_id = None
                legacy_position_id = None
                account_id = unified.account_id if unified is not None else None
                mapping_id = unified.account_mapping_id if unified is not None else None
                mark_as_of = None
                source_updated = None
                local_identity = {
                    "metadata_id": metadata[code].pk if code in metadata else None,
                    "metadata_class": metadata[code].asset_class if code in metadata else None,
                    "account_mapping_count": (
                        unified.account_mapping_count if unified is not None else 0
                    ),
                }
            fingerprint_payload = {
                "owner_user_id": owner_user_id,
                "portfolio_id": portfolio_id,
                "asset_code": code,
                "account_id": account_id,
                "account_mapping_id": mapping_id,
                "kind": kind,
                "total_shares": canonical_float(total_shares, field_name="total_shares"),
                "available_quantity": canonical_float(available, field_name="available_quantity"),
                "available_quantity_known": available_known,
                "average_cost": str(average_cost.normalize()) if average_cost is not None else None,
                "reference_mark": (
                    str(reference_mark.normalize()) if reference_mark is not None else None
                ),
                "valuation_status": valuation_status,
                "unified_position_id": position_id,
                "legacy_position_id": legacy_position_id,
                "local_identity": local_identity,
                "blocked_reason_code": reason,
            }
            fingerprint = hashlib.sha256(
                json.dumps(
                    fingerprint_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            snapshots.append(
                BalanceSnapshot(
                    owner_user_id=owner_user_id,
                    portfolio_id=portfolio_id,
                    account_id=account_id,
                    account_mapping_id=mapping_id,
                    asset_code=code,
                    kind=kind,
                    unified_position_id=position_id,
                    legacy_position_id=legacy_position_id,
                    total_shares=total_shares,
                    available_quantity=available,
                    available_quantity_known=available_known,
                    average_cost=average_cost,
                    reference_mark=reference_mark,
                    reference_mark_as_of=mark_as_of,
                    valuation_status=valuation_status,
                    source_updated_at=source_updated,
                    observed_at=timezone.now(),
                    fingerprint=fingerprint,
                    blocked_reason_code=reason,
                )
            )
        tuple_snapshots = tuple(snapshots)
        return BrokerBalancePreview(
            owner_user_id=owner_user_id,
            portfolio_id=portfolio_id,
            snapshots=tuple_snapshots,
            expected_balance_fingerprint=_balance_hash(tuple_snapshots),
        )
