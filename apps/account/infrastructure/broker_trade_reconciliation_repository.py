"""Django persistence for immutable broker facts and owner-scoped reconciliation."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import cast

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.account.application.broker_trade_projection_contracts import (
    BrokerActualFact,
    BrokerLegacyPositionSeed,
    BrokerPositionExpectation,
    BrokerTradeProjectionCommand,
    BrokerTradeProjectionGateway,
)
from apps.account.application.broker_trade_projection_errors import BrokerTradeProjectionConflict
from apps.account.application.broker_trade_reconciliation_contracts import (
    BaselineRequest,
    BrokerBalancePreview,
    BrokerFactCandidate,
    BrokerFactPreviewConflictCode,
    BrokerFactProjectionResult,
    BrokerFactSetReconciliationResult,
    BrokerFactWriteResult,
    BrokerTradeAction,
    BrokerTradeReconciliationRepository,
    JsonValue,
)
from apps.account.domain.asset_type_mapping import map_account_asset_type_strict
from apps.account.domain.broker_trade_reconciliation import BrokerReconciliationState
from apps.account.domain.broker_trade_reconciliation_fingerprints import broker_fact_set_fingerprint
from apps.account.infrastructure.broker_trade_reconciliation_codec import (
    _FEE_QUANTUM,
    _NOTIONAL_QUANTUM,
    _PRICE_QUANTUM,
    _SHA256_PATTERN,
    _SHARE_QUANTUM,
    _as_decimal,
    _aware_datetime,
    _details,
    _economic_identity_matches,
    _fact_identity,
    _fits_decimal_field,
    _json_object,
    _quantized,
)
from apps.account.infrastructure.broker_trade_reconciliation_fact_access import (
    BrokerFactAccessMixin,
)
from apps.account.infrastructure.broker_trade_reconciliation_snapshot_reader import (
    BrokerBalanceSnapshotMixin,
)
from apps.account.infrastructure.models import (
    AssetMetadataModel,
    BrokerTradeImportBatchModel,
    PortfolioModel,
    PositionModel,
    TransactionModel,
)
from core.exceptions import BusinessLogicError, InvalidInputError


class _ProjectionAbort(BusinessLogicError):
    """Roll back an entire excluded-file projection and persist a stable blocker."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(
            message=reason_code, code=reason_code, details={"reason_code": reason_code}
        )


class DjangoBrokerTradeReconciliationRepository(
    BrokerFactAccessMixin, BrokerBalanceSnapshotMixin, BrokerTradeReconciliationRepository
):
    """Persist actual broker facts and reconcile their economic projections."""

    def __init__(self, projection_service: BrokerTradeProjectionGateway) -> None:
        """Inject the Account consumer port implemented by Simulated Trading."""

        self._projection_service = projection_service

    def persist_fact_first(self, candidate: BrokerFactCandidate) -> BrokerFactWriteResult:
        """Commit one owner-scoped actual execution before optional matching work."""

        source = candidate.source_row
        if not _SHA256_PATTERN.fullmatch(candidate.source_file_sha256):
            raise InvalidInputError("source_file_sha256 must be a lowercase SHA-256 digest")
        if not candidate.source_filename or len(candidate.source_filename) > 255:
            raise InvalidInputError("source_filename is invalid")
        if not candidate.broker_name or len(candidate.broker_name) > 64:
            raise InvalidInputError("broker_name is invalid")
        if not source.asset_code or not source.broker_trade_key:
            raise InvalidInputError("broker fact asset code and stable key are required")
        if (
            len(source.asset_code) > 20
            or len(source.broker_trade_key) > 64
            or len(source.external_trade_id) > 128
        ):
            raise InvalidInputError("broker fact identifier exceeds persistence limits")
        traded_at = _aware_datetime(source.traded_at, "traded_at")
        shares = _quantized(_as_decimal(source.shares, "shares"), _SHARE_QUANTUM, "shares")
        price = _quantized(_as_decimal(source.price, "price"), _PRICE_QUANTUM, "price")
        if shares <= 0 or price <= 0:
            raise InvalidInputError("shares and price must be positive")
        commission = (
            _quantized(_as_decimal(source.commission, "commission"), _FEE_QUANTUM, "commission")
            if source.commission is not None
            else None
        )
        stamp_duty = (
            _quantized(_as_decimal(source.stamp_duty, "stamp_duty"), _FEE_QUANTUM, "stamp_duty")
            if source.stamp_duty is not None
            else None
        )
        transfer_fee = (
            _quantized(
                _as_decimal(source.transfer_fee, "transfer_fee"), _FEE_QUANTUM, "transfer_fee"
            )
            if source.transfer_fee is not None
            else None
        )
        if any(value is not None and value < 0 for value in (commission, stamp_duty, transfer_fee)):
            raise InvalidInputError("broker fees must not be negative")
        fact_notional = (shares * price).quantize(_NOTIONAL_QUANTUM, rounding=ROUND_HALF_UP)
        if not _fits_decimal_field(fact_notional, max_digits=20, decimal_places=2):
            raise InvalidInputError("broker fact notional exceeds supported persistence range")
        if any(
            value is not None and not _fits_decimal_field(value, max_digits=10, decimal_places=2)
            for value in (commission, stamp_duty, transfer_fee)
        ):
            raise InvalidInputError("broker fees exceed supported persistence range")
        if source.action not in {"buy", "sell"}:
            raise InvalidInputError("broker fact action is not recognized")
        raw_payload = _json_object(source.raw_payload, field_name="raw_payload")
        details: dict[str, JsonValue] = {
            "source": {
                "source_file_sha256": candidate.source_file_sha256,
                "source_filename": candidate.source_filename,
                "broker_name": candidate.broker_name,
                "first_seen_by_user_id": candidate.owner_user_id,
                "first_seen_at": timezone.now().isoformat(),
            },
            "legacy_origin": False,
            "baseline_declarations": [],
            "projection_attempts": [],
            "matching_attempts": [],
        }
        with transaction.atomic():
            portfolio = (
                PortfolioModel._default_manager.select_for_update()
                .filter(pk=candidate.portfolio_id, user_id=candidate.owner_user_id)
                .first()
            )
            if portfolio is None:
                raise InvalidInputError("portfolio is not owned by the fact owner")
            batch = None
            if candidate.first_import_batch_id is not None:
                batch = (
                    BrokerTradeImportBatchModel._default_manager.select_for_update()
                    .filter(
                        pk=candidate.first_import_batch_id,
                        user_id=candidate.owner_user_id,
                        portfolio_id=candidate.portfolio_id,
                    )
                    .first()
                )
                if batch is None:
                    raise InvalidInputError("first import batch is outside the fact owner scope")
                if batch.file_hash != candidate.source_file_sha256:
                    raise InvalidInputError("first import batch source hash does not match")
            existing = (
                TransactionModel._default_manager.select_for_update()
                .filter(broker_trade_key=source.broker_trade_key)
                .first()
            )
            if existing is not None:
                return self._compare_existing(
                    existing,
                    candidate,
                    shares=shares,
                    price=price,
                    commission=commission,
                    stamp_duty=stamp_duty,
                    transfer_fee=transfer_fee,
                )
            try:
                with transaction.atomic():
                    matching_positions = list(
                        PositionModel._default_manager.select_for_update()
                        .filter(
                            portfolio_id=candidate.portfolio_id,
                            asset_code=source.asset_code,
                            is_closed=False,
                        )
                        .order_by("pk")[:2]
                    )
                    model = TransactionModel._default_manager.create(
                        portfolio=portfolio,
                        position=matching_positions[0] if len(matching_positions) == 1 else None,
                        action=source.action,
                        asset_code=source.asset_code,
                        shares=float(shares),
                        price=price,
                        notional=(shares * price).quantize(
                            _NOTIONAL_QUANTUM, rounding=ROUND_HALF_UP
                        ),
                        commission=commission if commission is not None else Decimal("0"),
                        commission_known=commission is not None,
                        slippage=Decimal("0"),
                        slippage_known=False,
                        stamp_duty=stamp_duty if stamp_duty is not None else Decimal("0"),
                        stamp_duty_known=stamp_duty is not None,
                        transfer_fee=transfer_fee if transfer_fee is not None else Decimal("0"),
                        transfer_fee_known=transfer_fee is not None,
                        traded_at=traded_at,
                        notes=source.notes,
                        broker_name=candidate.broker_name,
                        external_trade_id=source.external_trade_id[:128],
                        broker_trade_key=source.broker_trade_key,
                        raw_payload=raw_payload,
                        import_batch=batch,
                        broker_reconciliation_state=BrokerReconciliationState.AWAITING_BASELINE.value,
                        broker_reconciliation_details=details,
                    )
            except IntegrityError:
                raced = (
                    TransactionModel._default_manager.select_for_update()
                    .filter(broker_trade_key=source.broker_trade_key)
                    .first()
                )
                if raced is None:
                    raise
                return self._compare_existing(
                    raced,
                    candidate,
                    shares=shares,
                    price=price,
                    commission=commission,
                    stamp_duty=stamp_duty,
                    transfer_fee=transfer_fee,
                )
            return BrokerFactWriteResult(
                disposition="created",
                record=self._record(model),
                conflict_reason_code=None,
            )

    def _compare_existing(
        self,
        model: TransactionModel,
        candidate: BrokerFactCandidate,
        *,
        shares: Decimal,
        price: Decimal,
        commission: Decimal | None,
        stamp_duty: Decimal | None,
        transfer_fee: Decimal | None,
    ) -> BrokerFactWriteResult:
        """Return an identical duplicate or conflict without exposing foreign rows."""

        if (
            model.portfolio_id != candidate.portfolio_id
            or model.portfolio.user_id != candidate.owner_user_id
        ):
            return BrokerFactWriteResult(
                disposition="stable_key_conflict",
                record=None,
                conflict_reason_code="BROKER_TRADE_KEY_ALREADY_CLAIMED",
            )
        identical = _economic_identity_matches(
            model,
            candidate,
            shares=shares,
            price=price,
            commission=commission,
            stamp_duty=stamp_duty,
            transfer_fee=transfer_fee,
        )
        return BrokerFactWriteResult(
            disposition="identical_duplicate" if identical else "stable_key_conflict",
            record=self._record(model),
            conflict_reason_code=None if identical else "BROKER_TRADE_KEY_ECONOMICS_CONFLICT",
        )

    def reconcile_fact_set(
        self,
        *,
        owner_user_id: int,
        portfolio_id: int,
        decision_batch_id: int | None,
        transaction_ids: tuple[int, ...],
        source_file_sha256: str,
        request: BaselineRequest,
    ) -> BrokerFactSetReconciliationResult:
        """Recheck file/fact/balance previews and project excluded facts atomically."""

        if not transaction_ids:
            return BrokerFactSetReconciliationResult(
                decision=request.decision,
                expected_fact_set_fingerprint=request.expected_fact_set_fingerprint,
                expected_balance_fingerprint=request.expected_balance_fingerprint,
                facts=(),
            )
        ids = tuple(dict.fromkeys(transaction_ids))
        if request.decision == "pending":
            pending_results: list[BrokerFactProjectionResult] = []
            with transaction.atomic():
                pending_portfolio = (
                    PortfolioModel._default_manager.select_for_update()
                    .filter(pk=portfolio_id, user_id=owner_user_id)
                    .first()
                )
                if pending_portfolio is None:
                    raise InvalidInputError("portfolio is not owned by the pending fact owner")
                locked = list(
                    TransactionModel._default_manager.select_for_update()
                    .filter(pk__in=ids, portfolio_id=portfolio_id, portfolio__user_id=owner_user_id)
                    .order_by("pk")
                )
                if len(locked) != len(ids):
                    raise InvalidInputError("pending fact set is outside the owner scope")
                for row in locked:
                    current = BrokerReconciliationState(row.broker_reconciliation_state)
                    if current is BrokerReconciliationState.NOT_APPLICABLE:
                        raise InvalidInputError("transaction is not a broker fact")
                    if current in {
                        BrokerReconciliationState.PROJECTED,
                        BrokerReconciliationState.ALREADY_IN_BASELINE,
                    }:
                        pending_results.append(
                            self._projection_result(
                                row,
                                outcome=(
                                    "projected"
                                    if current is BrokerReconciliationState.PROJECTED
                                    else "already_in_baseline"
                                ),
                            )
                        )
                        continue
                    if current is not BrokerReconciliationState.LEGACY_UNVERIFIED:
                        row.broker_reconciliation_state = (
                            BrokerReconciliationState.AWAITING_BASELINE.value
                        )
                    details = _details(row)
                    details["last_reason_code"] = "BASELINE_DECISION_PENDING"
                    row.broker_reconciliation_details = details
                    row.save(
                        update_fields=[
                            "broker_reconciliation_state",
                            "broker_reconciliation_details",
                        ]
                    )
                    pending_results.append(
                        self._projection_result(row, outcome="awaiting_baseline")
                    )
            return BrokerFactSetReconciliationResult(
                decision="pending",
                expected_fact_set_fingerprint=request.expected_fact_set_fingerprint,
                expected_balance_fingerprint=request.expected_balance_fingerprint,
                facts=tuple(pending_results),
            )

        if (
            request.expected_fact_set_fingerprint is None
            or request.expected_balance_fingerprint is None
        ):
            raise InvalidInputError("included/excluded baseline requires both preview fingerprints")
        if request.baseline_as_of is not None:
            _aware_datetime(request.baseline_as_of, "baseline_as_of")
        if not _SHA256_PATTERN.fullmatch(source_file_sha256):
            raise InvalidInputError("source_file_sha256 must be a lowercase SHA-256 digest")
        if decision_batch_id is not None:
            batch = BrokerTradeImportBatchModel._default_manager.filter(
                pk=decision_batch_id,
                user_id=owner_user_id,
                portfolio_id=portfolio_id,
            ).first()
            if batch is None:
                raise InvalidInputError("decision batch is outside the owner scope")
            if batch.file_hash != source_file_sha256:
                raise InvalidInputError("decision batch source hash does not match")
        conflict_code: BrokerFactPreviewConflictCode | None = None
        rows: list[TransactionModel] = []
        baseline_declared_at = timezone.now()
        try:
            with transaction.atomic():
                portfolio = (
                    PortfolioModel._default_manager.select_for_update()
                    .filter(pk=portfolio_id, user_id=owner_user_id)
                    .first()
                )
                if portfolio is None:
                    raise InvalidInputError("portfolio is not owned by the reconciliation owner")
                rows = list(
                    TransactionModel._default_manager.select_for_update()
                    .filter(pk__in=ids, portfolio_id=portfolio_id, portfolio__user_id=owner_user_id)
                    .select_related("portfolio")
                    .order_by("traded_at", "asset_code", "broker_trade_key", "pk")
                )
                if len(rows) != len(ids):
                    conflict_code = "BROKER_FACT_PREVIEW_CHANGED"
                    raise _ProjectionAbort("BROKER_FACT_PREVIEW_CHANGED")
                if any(row.broker_trade_key is None for row in rows):
                    raise InvalidInputError(
                        "baseline set contains a transaction without a broker key"
                    )
                identities = tuple(_fact_identity(row) for row in rows)
                current_fact_fingerprint = broker_fact_set_fingerprint(
                    owner_user_id=owner_user_id,
                    portfolio_id=portfolio_id,
                    source_file_sha256=source_file_sha256,
                    facts=identities,
                )
                if current_fact_fingerprint != request.expected_fact_set_fingerprint:
                    conflict_code = "BROKER_FACT_PREVIEW_CHANGED"
                    raise _ProjectionAbort("BROKER_FACT_PREVIEW_CHANGED")
                asset_codes = tuple(sorted({row.asset_code for row in rows}))
                preview = self.capture_balance_preview(
                    owner_user_id=owner_user_id,
                    portfolio_id=portfolio_id,
                    asset_codes=asset_codes,
                )
                if preview.expected_balance_fingerprint != request.expected_balance_fingerprint:
                    conflict_code = "BROKER_BALANCE_PREVIEW_CHANGED"
                    raise _ProjectionAbort("BROKER_BALANCE_PREVIEW_CHANGED")
                if any(snapshot.blocked_reason_code is not None for snapshot in preview.snapshots):
                    reason = next(
                        snapshot.blocked_reason_code
                        for snapshot in preview.snapshots
                        if snapshot.blocked_reason_code is not None
                    )
                    raise _ProjectionAbort(reason or "BALANCE_PREVIEW_BLOCKED")
                for row in rows:
                    details = _details(row)
                    if (
                        row.broker_reconciliation_state
                        == BrokerReconciliationState.LEGACY_UNVERIFIED.value
                        or bool(details.get("legacy_origin"))
                        or details.get("initial_state")
                        == BrokerReconciliationState.LEGACY_UNVERIFIED.value
                    ):
                        if request.decision == "excluded":
                            raise _ProjectionAbort("LEGACY_UNVERIFIED_CANNOT_BE_EXCLUDED")
                    if (
                        row.broker_reconciliation_state
                        == BrokerReconciliationState.ALREADY_IN_BASELINE.value
                        and request.decision == "excluded"
                    ):
                        raise _ProjectionAbort("BASELINE_INCLUSION_CANNOT_BE_REVERSED")
                    if (
                        row.broker_reconciliation_state == BrokerReconciliationState.PROJECTED.value
                        and request.decision == "included"
                    ):
                        raise _ProjectionAbort("BASELINE_PROJECTION_CANNOT_BE_REVERSED")
                self._append_baseline_declaration(
                    rows=rows,
                    request=request,
                    actor_user_id=owner_user_id,
                    declared_at=baseline_declared_at,
                    decision_batch_id=decision_batch_id,
                    source_file_sha256=source_file_sha256,
                )
                if request.decision == "included":
                    for row in rows:
                        details = _details(row)
                        row.broker_reconciliation_state = (
                            BrokerReconciliationState.ALREADY_IN_BASELINE.value
                        )
                        details["last_reason_code"] = None
                        row.broker_reconciliation_details = details
                        row.save(
                            update_fields=[
                                "broker_reconciliation_state",
                                "broker_reconciliation_details",
                            ]
                        )
                    results = tuple(
                        self._projection_result(row, outcome="already_in_baseline") for row in rows
                    )
                    return BrokerFactSetReconciliationResult(
                        decision="included",
                        expected_fact_set_fingerprint=current_fact_fingerprint,
                        expected_balance_fingerprint=preview.expected_balance_fingerprint,
                        facts=results,
                    )
                if request.decision != "excluded":
                    raise InvalidInputError("baseline decision is not recognized")
                results = self._project_excluded_rows(
                    portfolio=portfolio,
                    rows=rows,
                    preview=preview,
                    request=request,
                    decision_batch_id=decision_batch_id,
                    source_file_sha256=source_file_sha256,
                    declared_at=baseline_declared_at,
                )
                return BrokerFactSetReconciliationResult(
                    decision="excluded",
                    expected_fact_set_fingerprint=current_fact_fingerprint,
                    expected_balance_fingerprint=preview.expected_balance_fingerprint,
                    facts=results,
                )
        except _ProjectionAbort as error:
            if conflict_code is None and error.reason_code in {
                "BROKER_FACT_PREVIEW_CHANGED",
                "BROKER_BALANCE_PREVIEW_CHANGED",
            }:
                conflict_code = cast(
                    BrokerFactPreviewConflictCode,
                    error.reason_code,
                )
            blocked_rows = self._mark_blocked(
                transaction_ids=ids,
                reason_code=error.reason_code,
                owner_user_id=owner_user_id,
                portfolio_id=portfolio_id,
                request=request,
                actor_user_id=owner_user_id,
                decision_batch_id=decision_batch_id,
                source_file_sha256=source_file_sha256,
                declared_at=baseline_declared_at,
            )
            return BrokerFactSetReconciliationResult(
                decision=request.decision,
                expected_fact_set_fingerprint=request.expected_fact_set_fingerprint,
                expected_balance_fingerprint=request.expected_balance_fingerprint,
                facts=tuple(
                    self._projection_result(
                        row,
                        outcome=(
                            "blocked"
                            if row.broker_reconciliation_state
                            == BrokerReconciliationState.PROJECTION_BLOCKED.value
                            else (
                                "already_in_baseline"
                                if row.broker_reconciliation_state
                                == BrokerReconciliationState.ALREADY_IN_BASELINE.value
                                else "projected"
                            )
                        ),
                    )
                    for row in blocked_rows
                ),
                conflict_code=conflict_code,
            )

    def _project_excluded_rows(
        self,
        *,
        portfolio: PortfolioModel,
        rows: list[TransactionModel],
        preview: BrokerBalancePreview,
        request: BaselineRequest,
        decision_batch_id: int | None,
        source_file_sha256: str,
        declared_at: datetime,
    ) -> tuple[BrokerFactProjectionResult, ...]:
        """Apply excluded economic facts in actual execution order, all or none."""

        service = self._projection_service
        initial_states = {int(row.pk): row.broker_reconciliation_state for row in rows}
        results_by_id: dict[int, BrokerFactProjectionResult] = {}
        snapshots_by_code = {snapshot.asset_code: snapshot for snapshot in preview.snapshots}
        for row in sorted(
            rows,
            key=lambda item: (
                item.traded_at,
                item.asset_code,
                item.broker_trade_key or "",
                item.pk,
            ),
        ):
            details = _details(row)
            legacy_origin = bool(details.get("legacy_origin")) or details.get("initial_state") == (
                BrokerReconciliationState.LEGACY_UNVERIFIED.value
            )
            if (
                legacy_origin
                or row.broker_reconciliation_state
                == BrokerReconciliationState.LEGACY_UNVERIFIED.value
            ):
                raise _ProjectionAbort("LEGACY_UNVERIFIED_CANNOT_BE_EXCLUDED")
            if initial_states[int(row.pk)] in {
                BrokerReconciliationState.PROJECTED.value,
                BrokerReconciliationState.ALREADY_IN_BASELINE.value,
            }:
                if initial_states[int(row.pk)] == BrokerReconciliationState.PROJECTED.value:
                    results_by_id[int(row.pk)] = self._projection_result(row, outcome="projected")
                    continue
                raise _ProjectionAbort("BASELINE_INCLUSION_CANNOT_BE_REVERSED")
            legacy = (
                PositionModel._default_manager.select_for_update()
                .filter(
                    portfolio_id=portfolio.pk,
                    asset_code=row.asset_code,
                    is_closed=False,
                )
                .order_by("pk")
                .first()
            )
            duplicates = PositionModel._default_manager.filter(
                portfolio_id=portfolio.pk,
                asset_code=row.asset_code,
                is_closed=False,
            ).count()
            if duplicates > 1:
                raise _ProjectionAbort("LEGACY_POSITION_AMBIGUOUS")
            legacy_id = int(legacy.pk) if legacy is not None else None
            unified_snapshots = service.capture_position_snapshots(
                owner_user_id=int(portfolio.user_id),
                portfolio_id=int(portfolio.pk),
                portfolio_name=portfolio.name,
                asset_codes=(row.asset_code,),
                legacy_position_ids={row.asset_code: legacy_id},
            )
            if len(unified_snapshots) != 1:
                raise _ProjectionAbort("UNIFIED_POSITION_SNAPSHOT_MISSING")
            unified = unified_snapshots[0]
            if unified.blocked_reason_code is not None:
                raise _ProjectionAbort(unified.blocked_reason_code)
            snapshot_before = snapshots_by_code.get(row.asset_code)
            if snapshot_before is None:
                raise _ProjectionAbort("BROKER_BALANCE_PREVIEW_CHANGED")
            asset_type: str | None = None
            asset_name = row.asset_code
            metadata = AssetMetadataModel._default_manager.filter(asset_code=row.asset_code).first()
            if legacy is not None:
                asset_type = map_account_asset_type_strict(legacy.asset_class)
            elif unified.asset_type is not None:
                asset_type = unified.asset_type
            elif metadata is not None:
                asset_type = map_account_asset_type_strict(metadata.asset_class)
            if metadata is not None:
                asset_name = metadata.name
            elif legacy is not None:
                asset_name = row.asset_code
            if asset_type is None:
                raise _ProjectionAbort("ASSET_TYPE_UNSUPPORTED_OR_METADATA_MISSING")
            legacy_seed = self._legacy_seed(legacy, metadata, asset_type)
            expectation = BrokerPositionExpectation(
                account_id=unified.account_id,
                account_mapping_id=unified.account_mapping_id,
                account_mapping_count=unified.account_mapping_count,
                unified_position_id=unified.unified_position_id,
                position_map_source_id=unified.position_map_source_id,
                position_map_target_id=unified.position_map_target_id,
                total_shares=unified.total_shares,
                average_cost=unified.average_cost,
                reference_mark=unified.reference_mark,
                valuation_known=unified.valuation_known,
                available_quantity=unified.available_quantity,
                available_quantity_known=unified.available_quantity_known,
                asset_type=unified.asset_type,
                position_map_state=unified.position_map_state,
            )
            actual = BrokerActualFact(
                transaction_id=int(row.pk),
                asset_code=row.asset_code,
                asset_name=asset_name,
                asset_type=asset_type,
                action=cast(BrokerTradeAction, row.action),
                shares=_as_decimal(row.shares, "shares"),
                price=_as_decimal(row.price, "price"),
                notional=_as_decimal(row.notional, "notional"),
                commission=_as_decimal(row.commission, "commission"),
                commission_known=row.commission_known is True,
                stamp_duty=_as_decimal(row.stamp_duty, "stamp_duty"),
                stamp_duty_known=row.stamp_duty_known is True,
                transfer_fee=_as_decimal(row.transfer_fee, "transfer_fee"),
                transfer_fee_known=row.transfer_fee_known is True,
                slippage=_as_decimal(row.slippage, "slippage"),
                slippage_known=row.slippage_known is True,
                traded_at=_aware_datetime(row.traded_at, "traded_at"),
            )
            try:
                result = service.apply_actual_broker_fact(
                    BrokerTradeProjectionCommand(
                        owner_user_id=int(portfolio.user_id),
                        portfolio_id=int(portfolio.pk),
                        portfolio_name=portfolio.name,
                        portfolio_is_active=bool(portfolio.is_active),
                        legacy_position=legacy_seed,
                        expectation=expectation,
                        fact=actual,
                    )
                )
            except BrokerTradeProjectionConflict as error:
                raise _ProjectionAbort(error.reason_code) from error
            if not result.applied:
                raise _ProjectionAbort(result.reason_code or "BROKER_FACT_PROJECTION_BLOCKED")
            legacy_after = legacy
            if legacy_after is None:
                if metadata is None:
                    raise _ProjectionAbort("ASSET_METADATA_MISSING")
                legacy_after = PositionModel._default_manager.create(
                    portfolio=portfolio,
                    asset_code=row.asset_code,
                    asset_class=metadata.asset_class,
                    region=metadata.region,
                    cross_border=metadata.cross_border,
                    shares=float(result.total_shares or Decimal("0")),
                    avg_cost=result.average_cost or Decimal("0"),
                    current_price=result.reference_mark,
                    market_value=(
                        Decimal(result.total_shares or Decimal("0")) * result.reference_mark
                        if result.reference_mark is not None
                        else Decimal("0")
                    ),
                    unrealized_pnl=Decimal("0"),
                    unrealized_pnl_pct=0.0,
                    source="manual",
                    is_closed=result.fully_closed,
                    closed_at=timezone.now() if result.fully_closed else None,
                )
                if (
                    result.unified_position_id is not None
                    and not service.bind_legacy_position_source(
                        owner_user_id=int(portfolio.user_id),
                        portfolio_id=int(portfolio.pk),
                        source_position_id=int(legacy_after.pk),
                        unified_position_id=result.unified_position_id,
                    )
                ):
                    raise _ProjectionAbort("POSITION_MAPPING_CONFLICT")
            else:
                legacy_after.shares = float(result.total_shares or Decimal("0"))
                if result.average_cost is not None:
                    legacy_after.avg_cost = result.average_cost
                if result.reference_mark is not None:
                    legacy_after.current_price = result.reference_mark
                    legacy_after.market_value = (
                        Decimal(result.total_shares or Decimal("0")) * result.reference_mark
                    )
                    legacy_after.unrealized_pnl = (
                        result.reference_mark - legacy_after.avg_cost
                    ) * Decimal(str(legacy_after.shares))
                elif legacy_after.current_price is None:
                    legacy_after.market_value = Decimal("0")
                    legacy_after.unrealized_pnl = Decimal("0")
                legacy_after.is_closed = result.fully_closed
                legacy_after.closed_at = timezone.now() if result.fully_closed else None
                legacy_after.save(
                    update_fields=[
                        "shares",
                        "avg_cost",
                        "current_price",
                        "market_value",
                        "unrealized_pnl",
                        "is_closed",
                        "closed_at",
                        "updated_at",
                    ]
                )
            row.position = legacy_after
            row.broker_reconciliation_state = BrokerReconciliationState.PROJECTED.value
            details = _details(row)
            now = timezone.now()
            attempt: dict[str, JsonValue] = {
                "attempted_at": now.isoformat(),
                "outcome": "projected",
                "reason_code": None,
                "account_id": result.account_id,
                "unified_position_id": result.unified_position_id,
                "legacy_position_id": int(legacy_after.pk),
                "resulting_balance_fingerprint": None,
                "decision_batch_id": decision_batch_id,
                "source_file_sha256": source_file_sha256,
                "retired_unified_position_id": (
                    unified.unified_position_id if result.fully_closed else None
                ),
                "retired_legacy_position_id": legacy_id if result.fully_closed else None,
            }
            attempts_value = details.get("projection_attempts")
            attempts = attempts_value if isinstance(attempts_value, list) else []
            attempts.append(attempt)
            details["projection_attempts"] = attempts
            details["last_projection"] = attempt
            details["last_reason_code"] = None
            row.broker_reconciliation_details = details
            row.save(
                update_fields=[
                    "position",
                    "broker_reconciliation_state",
                    "broker_reconciliation_details",
                ]
            )
            # Refresh the per-asset map for the next actual execution in this file.
            refreshed = service.capture_position_snapshots(
                owner_user_id=int(portfolio.user_id),
                portfolio_id=int(portfolio.pk),
                portfolio_name=portfolio.name,
                asset_codes=(row.asset_code,),
                legacy_position_ids={row.asset_code: int(legacy_after.pk)},
            )
            if len(refreshed) != 1:
                raise _ProjectionAbort("UNIFIED_POSITION_SNAPSHOT_MISSING")
            resulting_preview = self.capture_balance_preview(
                owner_user_id=int(portfolio.user_id),
                portfolio_id=int(portfolio.pk),
                asset_codes=(row.asset_code,),
            )
            resulting_fingerprint = resulting_preview.expected_balance_fingerprint
            details = _details(row)
            last_projection = details.get("last_projection")
            if isinstance(last_projection, dict):
                last_projection["resulting_balance_fingerprint"] = resulting_fingerprint
                details["last_projection"] = last_projection
                attempts_value = details.get("projection_attempts")
                if isinstance(attempts_value, list) and attempts_value:
                    latest_attempt = attempts_value[-1]
                    if isinstance(latest_attempt, dict):
                        latest_attempt["resulting_balance_fingerprint"] = resulting_fingerprint
                        attempts_value[-1] = latest_attempt
                        details["projection_attempts"] = attempts_value
                row.broker_reconciliation_details = details
                row.save(update_fields=["broker_reconciliation_details"])
            results_by_id[int(row.pk)] = BrokerFactProjectionResult(
                transaction_id=int(row.pk),
                state=BrokerReconciliationState.PROJECTED,
                outcome="projected",
                reason_code=None,
                resulting_balance_fingerprint=resulting_fingerprint,
            )
        return tuple(
            results_by_id.get(int(row.pk), self._projection_result(row, outcome="projected"))
            for row in rows
        )

    @staticmethod
    def _legacy_seed(
        position: PositionModel | None,
        metadata: AssetMetadataModel | None,
        asset_type: str,
    ) -> BrokerLegacyPositionSeed | None:
        """Narrow one exact, active Account position into the Sim public projection port."""

        if position is None:
            return None
        asset_name = metadata.name if metadata is not None else position.asset_code
        return BrokerLegacyPositionSeed(
            source_position_id=int(position.pk),
            asset_code=position.asset_code,
            asset_name=asset_name,
            asset_type=asset_type,
            total_shares=_as_decimal(position.shares, "legacy shares"),
            average_cost=_as_decimal(position.avg_cost, "legacy average cost"),
            reference_mark=(
                _as_decimal(position.current_price, "legacy reference mark")
                if position.current_price is not None
                else None
            ),
            valuation_known=position.current_price is not None,
            first_buy_date=position.opened_at.date(),
        )

    def _append_baseline_declaration(
        self,
        *,
        rows: list[TransactionModel],
        request: BaselineRequest,
        actor_user_id: int,
        declared_at: datetime,
        decision_batch_id: int | None,
        source_file_sha256: str,
    ) -> None:
        """Append an immutable decision record while preserving earlier declarations."""

        declaration: dict[str, JsonValue] = {
            "decision": request.decision,
            "actor_user_id": actor_user_id,
            "declared_at": declared_at.isoformat(),
            "expected_fact_set_fingerprint": request.expected_fact_set_fingerprint,
            "expected_balance_fingerprint": request.expected_balance_fingerprint,
            "baseline_as_of": (
                request.baseline_as_of.isoformat() if request.baseline_as_of is not None else None
            ),
            "decision_batch_id": decision_batch_id,
            "source_file_sha256": source_file_sha256,
        }
        for row in rows:
            details = _details(row)
            if row.broker_reconciliation_state == BrokerReconciliationState.LEGACY_UNVERIFIED.value:
                details["legacy_origin"] = True
                details["initial_state"] = BrokerReconciliationState.LEGACY_UNVERIFIED.value
            existing_value = details.get("baseline_declarations")
            declarations = existing_value if isinstance(existing_value, list) else []
            declarations.append(dict(declaration))
            details["baseline_declarations"] = declarations
            details["baseline_declaration"] = dict(declaration)
            row.broker_reconciliation_details = details
            row.save(update_fields=["broker_reconciliation_details"])

    def _mark_blocked(
        self,
        transaction_ids: tuple[int, ...],
        reason_code: str,
        *,
        owner_user_id: int,
        portfolio_id: int,
        request: BaselineRequest | None = None,
        actor_user_id: int | None = None,
        decision_batch_id: int | None = None,
        source_file_sha256: str | None = None,
        declared_at: datetime | None = None,
    ) -> tuple[TransactionModel, ...]:
        """Persist blockers under portfolio/fact locks and return those locked rows."""

        if not transaction_ids:
            return ()
        with transaction.atomic():
            portfolio = (
                PortfolioModel._default_manager.select_for_update()
                .filter(pk=portfolio_id, user_id=owner_user_id)
                .first()
            )
            if portfolio is None:
                raise InvalidInputError(
                    "portfolio ownership changed before blocked outcomes could be persisted"
                )
            locked = list(
                TransactionModel._default_manager.select_for_update()
                .filter(
                    pk__in=transaction_ids,
                    portfolio_id=portfolio_id,
                    portfolio__user_id=owner_user_id,
                )
                .select_related("portfolio")
                .order_by("traded_at", "asset_code", "broker_trade_key", "pk")
            )
            attempted_at = timezone.now().isoformat()
            for row in locked:
                state = BrokerReconciliationState(row.broker_reconciliation_state)
                if state in {
                    BrokerReconciliationState.PROJECTED,
                    BrokerReconciliationState.ALREADY_IN_BASELINE,
                }:
                    continue
                details = _details(row)
                if state is BrokerReconciliationState.LEGACY_UNVERIFIED:
                    details["legacy_origin"] = True
                    details["initial_state"] = BrokerReconciliationState.LEGACY_UNVERIFIED.value
                if (
                    request is not None
                    and actor_user_id is not None
                    and source_file_sha256 is not None
                    and declared_at is not None
                ):
                    declaration: dict[str, JsonValue] = {
                        "decision": request.decision,
                        "actor_user_id": actor_user_id,
                        "declared_at": declared_at.isoformat(),
                        "expected_fact_set_fingerprint": request.expected_fact_set_fingerprint,
                        "expected_balance_fingerprint": request.expected_balance_fingerprint,
                        "baseline_as_of": (
                            request.baseline_as_of.isoformat()
                            if request.baseline_as_of is not None
                            else None
                        ),
                        "decision_batch_id": decision_batch_id,
                        "source_file_sha256": source_file_sha256,
                        "attempt_outcome": "blocked",
                        "reason_code": reason_code,
                    }
                    declaration_value = details.get("baseline_declarations")
                    declarations = declaration_value if isinstance(declaration_value, list) else []
                    declarations.append(dict(declaration))
                    details["baseline_declarations"] = declarations
                    details["baseline_declaration"] = dict(declaration)
                attempt: dict[str, JsonValue] = {
                    "attempted_at": attempted_at,
                    "outcome": "blocked",
                    "reason_code": reason_code,
                    "account_id": None,
                    "unified_position_id": None,
                    "legacy_position_id": row.position_id,
                    "resulting_balance_fingerprint": None,
                }
                attempts_value = details.get("projection_attempts")
                attempts = attempts_value if isinstance(attempts_value, list) else []
                attempts.append(attempt)
                details["projection_attempts"] = attempts
                details["last_projection"] = attempt
                details["last_reason_code"] = reason_code
                row.broker_reconciliation_state = BrokerReconciliationState.PROJECTION_BLOCKED.value
                row.broker_reconciliation_details = details
                row.save(
                    update_fields=["broker_reconciliation_state", "broker_reconciliation_details"]
                )
            return tuple(locked)
