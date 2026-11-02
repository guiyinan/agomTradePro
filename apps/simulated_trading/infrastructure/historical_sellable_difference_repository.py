"""Owner-scoped G5 ledger diagnostics and bounded simulated Position repairs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, cast

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, router, transaction
from django.db.models import Q
from django.utils import timezone

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeAccountScopeUnavailable,
    SimulatedTradeExecutionBlocked,
)
from apps.simulated_trading.application.historical_sellable_difference import (
    LedgerMappingProjection,
    SelectedAccountScopeRead,
    TargetPositionProjection,
    TargetPositionScopeRead,
)
from apps.simulated_trading.application.historical_sellable_repair import (
    HistoricalSellableRepairCommand,
    HistoricalSellableRepairResult,
)
from apps.simulated_trading.domain.execution_settlement_primitives import (
    SimulatedSettlementContractError,
)
from apps.simulated_trading.domain.historical_sellable_difference import (
    HistoricalLedgerEvidence,
    HistoricalLedgerFillFact,
    HistoricalLedgerHoldFact,
    HistoricalLedgerSellabilityProof,
    HistoricalPositionMappingFact,
    HistoricalSourcePositionFact,
    HistoricalTargetPositionFact,
    format_ledger_quantity,
    normalize_ledger_quantity,
    prove_historical_ledger_sellability,
)
from apps.simulated_trading.infrastructure.models import (
    HistoricalSellableRepairJournalModel,
    LedgerMigrationMapModel,
    PositionModel,
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_account_history import (
    validate_account_v4_fill_history,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_chain_storage import (
    _locked_fill_chain,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_initial_position_mark_codec import (
    decode_initial_position_mark_evidence,
)
from apps.simulated_trading.infrastructure.order_reservation_fill_ledger_storage import (
    _lock_simulated_fill_account,
)
from apps.simulated_trading.infrastructure.order_reservation_guard import (
    lock_active_order_reservations,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)


class DjangoHistoricalSellableDifferenceRepository:
    """Read exact owner scopes and atomically repair one proved Position row."""

    def read_selected_account_scope(
        self,
        *,
        user_id: int,
        account_id: int,
        database_alias: str,
    ) -> SelectedAccountScopeRead:
        """Resolve the selected account and its explicit source portfolio map."""

        if self._route_mismatch(
            database_alias,
            (SimulatedAccountModel, LedgerMigrationMapModel),
        ):
            return SelectedAccountScopeRead("database_route_mismatch", None, ())

        account_exists = (
            SimulatedAccountModel._default_manager.using(database_alias)
            .filter(
                pk=account_id,
                user_id=user_id,
            )
            .exists()
        )
        if not account_exists:
            return SelectedAccountScopeRead("account_unavailable", database_alias, ())

        records = (
            LedgerMigrationMapModel._default_manager.using(database_alias)
            .filter(
                source_app="account",
                source_table="portfolio",
                target_id=account_id,
            )
            .order_by("pk")
        )
        mappings = tuple(self._mapping(record) for record in records)
        return SelectedAccountScopeRead("ready", database_alias, mappings)

    def read_position_scope(
        self,
        *,
        user_id: int,
        account_id: int,
        source_positions: tuple[HistoricalSourcePositionFact, ...],
        self_simulated_scope: bool,
        database_alias: str,
    ) -> TargetPositionScopeRead:
        """Read one locked account snapshot and reconstruct eligible V4 sellable chains."""

        if self._route_mismatch(
            database_alias,
            (
                SimulatedAccountModel,
                PositionModel,
                LedgerMigrationMapModel,
                SimulatedTradeModel,
                SimulatedOrderReservationModel,
                SimulatedOrderFillReceiptModel,
            ),
        ):
            return TargetPositionScopeRead("database_route_mismatch", None, (), (), frozenset())
        if self_simulated_scope and source_positions:
            return TargetPositionScopeRead(
                "account_unavailable", database_alias, (), (), frozenset()
            )

        source_position_ids = tuple(position.position_id for position in source_positions)
        try:
            with transaction.atomic(using=database_alias):
                account_query = SimulatedAccountModel._base_manager.using(database_alias).filter(
                    pk=account_id,
                    user_id=user_id,
                )
                if self_simulated_scope:
                    account_query = account_query.filter(account_type="simulated")
                account = account_query.select_for_update().first()
                if account is None:
                    return TargetPositionScopeRead(
                        "account_unavailable", database_alias, (), (), frozenset()
                    )
                active_reservations = lock_active_order_reservations(
                    account_id=account_id,
                    using=database_alias,
                )
                account_history_valid = True
                try:
                    validate_account_v4_fill_history(
                        account=account,
                        intent=None,
                        using=database_alias,
                    )
                except SimulatedTradeExecutionBlocked:
                    account_history_valid = False

                records = tuple(
                    PositionModel._default_manager.using(database_alias)
                    .select_for_update(of=("self",))
                    .filter(account_id=account_id)
                    .only(
                        "id",
                        "account_id",
                        "asset_code",
                        "quantity",
                        "available_quantity",
                        "available_quantity_known",
                        "first_buy_date_known",
                    )
                    .order_by("pk")
                )
                positions_by_id = {int(record.pk): record for record in records}
                target_ids = tuple(positions_by_id)
                mapping_filter = Q(
                    source_app="account",
                    source_table="position",
                    source_id__in=source_position_ids,
                ) | Q(target_table="simulated_position", target_id__in=target_ids)
                mapping_records = tuple(
                    LedgerMigrationMapModel._default_manager.using(database_alias)
                    .select_for_update(of=("self",))
                    .filter(mapping_filter)
                    .order_by("pk")
                )
                mappings = tuple(self._mapping(record) for record in mapping_records)
                referenced_target_ids = tuple(
                    mapping.target_id
                    for mapping in mappings
                    if mapping.source_app == "account"
                    and mapping.source_table == "position"
                    and mapping.source_id in source_position_ids
                    and mapping.target_table == "simulated_position"
                )
                existing_target_ids = set(target_ids)
                if referenced_target_ids:
                    existing_target_ids.update(
                        int(position_id)
                        for position_id in PositionModel._default_manager.using(database_alias)
                        .filter(pk__in=referenced_target_ids)
                        .values_list("pk", flat=True)
                    )

                proofs_by_target: dict[int, HistoricalLedgerSellabilityProof] = {}
                for source in source_positions:
                    source_maps = tuple(
                        item
                        for item in mappings
                        if item.source_app == "account"
                        and item.source_table == "position"
                        and item.source_id == source.position_id
                    )
                    if len(source_maps) != 1:
                        continue
                    mapping = source_maps[0]
                    target = positions_by_id.get(mapping.target_id)
                    if target is None or mapping.target_table != "simulated_position":
                        continue
                    target_projection = HistoricalTargetPositionFact(
                        position_id=int(target.pk),
                        account_id=int(target.account_id),
                        asset_code=str(target.asset_code),
                        quantity=_decimal_field(target.quantity),
                        available_quantity=_decimal_field(target.available_quantity),
                        available_quantity_known=_bool_field(target.available_quantity_known),
                        first_buy_date_known=_bool_field(target.first_buy_date_known),
                    )
                    if not account_history_valid:
                        proof = _unavailable_proof("LEDGER_ACCOUNT_HISTORY_INVALID")
                    else:
                        proof = self._reconstruct_position_ledger(
                            account_id=account_id,
                            user_id=user_id,
                            source=source,
                            target=target_projection,
                            mapping=HistoricalPositionMappingFact(
                                mapping_id=mapping.mapping_id,
                                source_app=mapping.source_app,
                                source_table=mapping.source_table,
                                source_id=mapping.source_id,
                                target_table=mapping.target_table,
                                target_id=mapping.target_id,
                            ),
                            active_reservations=active_reservations,
                            using=database_alias,
                        )
                    proofs_by_target[target_projection.position_id] = proof

                if self_simulated_scope:
                    for target in records:
                        target_id = int(target.pk)
                        target_projection = HistoricalTargetPositionFact(
                            position_id=target_id,
                            account_id=int(target.account_id),
                            asset_code=str(target.asset_code),
                            quantity=_decimal_field(target.quantity),
                            available_quantity=_decimal_field(target.available_quantity),
                            available_quantity_known=_bool_field(target.available_quantity_known),
                            first_buy_date_known=_bool_field(target.first_buy_date_known),
                        )
                        proofs_by_target[target_id] = (
                            _unavailable_proof("LEDGER_ACCOUNT_HISTORY_INVALID")
                            if not account_history_valid
                            else self._reconstruct_position_ledger(
                                account_id=account_id,
                                user_id=user_id,
                                source=None,
                                target=target_projection,
                                mapping=None,
                                active_reservations=active_reservations,
                                using=database_alias,
                            )
                        )

                positions = tuple(
                    TargetPositionProjection(
                        position_id=int(record.pk),
                        account_id=int(record.account_id),
                        asset_code=str(record.asset_code),
                        quantity=_decimal_field(record.quantity),
                        available_quantity=_decimal_field(record.available_quantity),
                        available_quantity_known=_bool_field(record.available_quantity_known),
                        first_buy_date_known=_bool_field(record.first_buy_date_known),
                        ledger_proof=proofs_by_target.get(int(record.pk)),
                    )
                    for record in records
                )
                return TargetPositionScopeRead(
                    status="ready",
                    database_alias=database_alias,
                    positions=positions,
                    mappings=mappings,
                    existing_target_position_ids=frozenset(existing_target_ids),
                )
        except SimulatedTradeAccountScopeUnavailable:
            return TargetPositionScopeRead(
                "account_unavailable", database_alias, (), (), frozenset()
            )

    def apply_sellable_repair(
        self,
        *,
        command: HistoricalSellableRepairCommand,
        database_alias: str,
    ) -> HistoricalSellableRepairResult:
        """Atomically repair one settled-share cache under account/Position locks."""

        if command.action != "apply":
            raise _repair_blocked(
                "apply repository received a non-apply request",
                "HISTORICAL_SELLABLE_REPAIR_REQUEST_INVALID",
            )
        preview_cutoff = command.preview_evidence_cutoff_at
        if type(preview_cutoff) is not datetime or preview_cutoff.tzinfo is None:
            raise _repair_blocked(
                "apply requires the exact read-only preview cutoff",
                "HISTORICAL_SELLABLE_REPAIR_PREVIEW_INVALID",
            )
        if self._write_route_mismatch(
            database_alias,
            (
                SimulatedAccountModel,
                PositionModel,
                SimulatedTradeModel,
                SimulatedOrderReservationModel,
                SimulatedOrderFillReceiptModel,
                HistoricalSellableRepairJournalModel,
            ),
        ):
            raise _repair_blocked(
                "selected database alias does not match the configured write routes",
                "DATABASE_ROUTER_ALIAS_MISMATCH",
            )
        request_hash = _repair_request_hash(command, database_alias)
        with transaction.atomic(using=database_alias):
            account = _lock_simulated_fill_account(
                account_id=command.account_id,
                user_id=command.user_id,
                using=database_alias,
            )
            existing = (
                HistoricalSellableRepairJournalModel._base_manager.using(database_alias)
                .filter(
                    account_id=command.account_id,
                    idempotency_key=command.idempotency_key,
                )
                .first()
            )
            if existing is not None:
                if existing.action != "apply" or existing.request_hash != request_hash:
                    raise _repair_blocked(
                        "G5 repair key was already used for a different request",
                        "HISTORICAL_SELLABLE_REPAIR_IDEMPOTENCY_CONFLICT",
                    )
                return _repair_result(existing, outcome="replayed")

            active_reservations = lock_active_order_reservations(
                account_id=command.account_id,
                using=database_alias,
            )
            if preview_cutoff > timezone.now():
                raise _repair_blocked(
                    "read-only preview cutoff is later than the locked repair clock",
                    "HISTORICAL_SELLABLE_REPAIR_PREVIEW_INVALID",
                )
            try:
                validate_account_v4_fill_history(
                    account=account,
                    intent=None,
                    using=database_alias,
                )
            except SimulatedTradeExecutionBlocked as error:
                raise _repair_blocked(
                    "account V4 history is not complete enough for a repair",
                    "HISTORICAL_SELLABLE_LEDGER_INVALID",
                ) from error
            position = (
                PositionModel._base_manager.using(database_alias)
                .select_for_update(of=("self",))
                .filter(pk=command.target_position_id, account_id=command.account_id)
                .first()
            )
            if position is None:
                raise _repair_blocked(
                    "selected simulated Position is missing",
                    "HISTORICAL_SELLABLE_POSITION_MISSING",
                )
            target = HistoricalTargetPositionFact(
                position_id=int(position.pk),
                account_id=int(position.account_id),
                asset_code=str(position.asset_code),
                quantity=_decimal_field(position.quantity),
                available_quantity=_decimal_field(position.available_quantity),
                available_quantity_known=_bool_field(position.available_quantity_known),
                first_buy_date_known=_bool_field(position.first_buy_date_known),
            )
            proof = self._reconstruct_position_ledger(
                account_id=command.account_id,
                user_id=command.user_id,
                source=None,
                target=target,
                mapping=None,
                active_reservations=active_reservations,
                using=database_alias,
                cutoff_at=preview_cutoff,
            )
            _require_g5_repair_proof(
                proof=proof,
                account_id=command.account_id,
                user_id=command.user_id,
                target=target,
            )
            proof_total = proof.total_quantity
            proof_available = proof.available_quantity
            proof_security_id = proof.security_id
            proof_cutoff = proof.cutoff_at
            proof_hash = proof.proof_hash
            if (
                type(position.available_quantity) is not Decimal
                or type(position.available_quantity_known) is not bool
                or type(proof_total) is not Decimal
                or type(proof_available) is not Decimal
                or type(proof_security_id) is not str
                or type(proof_cutoff) is not datetime
                or type(proof_hash) is not str
            ):
                raise _repair_blocked(
                    "available-share state is not exactly representable",
                    "HISTORICAL_SELLABLE_POSITION_INVALID",
                )
            before_quantity = position.available_quantity
            before_known = position.available_quantity_known
            if (
                proof_hash != command.preview_evidence_proof_hash
                or proof_cutoff != preview_cutoff
                or before_quantity != command.preview_available_quantity
                or before_known is not command.preview_available_quantity_known
            ):
                raise _repair_blocked(
                    "ledger evidence or stored available state changed since preview; rerun the report",
                    "HISTORICAL_SELLABLE_REPAIR_PREVIEW_STALE",
                )
            if before_quantity == proof_available and before_known is True:
                raise _repair_blocked(
                    "simulated Position already matches its proved available-share quantity",
                    "HISTORICAL_SELLABLE_REPAIR_NOT_NEEDED",
                )
            changed_at = timezone.now()
            updated = (
                PositionModel._base_manager.using(database_alias)
                .filter(
                    pk=position.pk,
                    account_id=command.account_id,
                    quantity=position.quantity,
                    available_quantity=before_quantity,
                    available_quantity_known=before_known,
                    updated_at=position.updated_at,
                )
                .update(
                    available_quantity=proof_available,
                    available_quantity_known=True,
                    updated_at=changed_at,
                )
            )
            if updated != 1:
                raise _repair_blocked(
                    "simulated Position changed before the repair compare-and-set",
                    "HISTORICAL_SELLABLE_REPAIR_CONFLICT",
                )
            event = HistoricalSellableRepairJournalModel._default_manager.using(
                database_alias
            ).create(
                action="apply",
                account_id=command.account_id,
                owner_user_id=command.user_id,
                actor_user_id=command.actor_user_id,
                source_scope="simulated_position",
                source_position_id=None,
                target_position_id=command.target_position_id,
                position_mapping_id=None,
                security_id=proof_security_id,
                asset_code=target.asset_code,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                apply_event_id=None,
                source_total_quantity=None,
                target_total_quantity=proof_total,
                source_record_updated_at=None,
                evidence_cutoff_at=proof_cutoff,
                evidence_proof_hash=proof_hash,
                before_available_quantity=before_quantity,
                before_available_quantity_known=before_known,
                after_available_quantity=proof_available,
                after_available_quantity_known=True,
            )
            return _repair_result(event, outcome="applied")

    def rollback_sellable_repair(
        self,
        *,
        command: HistoricalSellableRepairCommand,
        database_alias: str,
    ) -> HistoricalSellableRepairResult:
        """Restore one apply only if its original V4 proof and exact cache value remain."""

        if command.action != "rollback":
            raise _repair_blocked(
                "rollback repository received a non-rollback request",
                "HISTORICAL_SELLABLE_REPAIR_REQUEST_INVALID",
            )
        apply_event_id = command.apply_event_id
        if type(apply_event_id) is not int or apply_event_id <= 0:
            raise _repair_blocked(
                "rollback requires the original G5 apply event id",
                "HISTORICAL_SELLABLE_REPAIR_REQUEST_INVALID",
            )
        if self._write_route_mismatch(
            database_alias,
            (
                SimulatedAccountModel,
                PositionModel,
                SimulatedTradeModel,
                SimulatedOrderReservationModel,
                SimulatedOrderFillReceiptModel,
                HistoricalSellableRepairJournalModel,
            ),
        ):
            raise _repair_blocked(
                "selected database alias does not match the configured write routes",
                "DATABASE_ROUTER_ALIAS_MISMATCH",
            )
        request_hash = _repair_request_hash(command, database_alias)
        with transaction.atomic(using=database_alias):
            account = _lock_simulated_fill_account(
                account_id=command.account_id,
                user_id=command.user_id,
                using=database_alias,
            )
            existing = (
                HistoricalSellableRepairJournalModel._base_manager.using(database_alias)
                .filter(
                    account_id=command.account_id,
                    idempotency_key=command.idempotency_key,
                )
                .first()
            )
            if existing is not None:
                if existing.action != "rollback" or existing.request_hash != request_hash:
                    raise _repair_blocked(
                        "G5 rollback key was already used for a different request",
                        "HISTORICAL_SELLABLE_REPAIR_IDEMPOTENCY_CONFLICT",
                    )
                return _repair_result(existing, outcome="replayed")
            apply_event = (
                HistoricalSellableRepairJournalModel._base_manager.using(database_alias)
                .select_for_update(of=("self",))
                .filter(
                    pk=apply_event_id,
                    account_id=command.account_id,
                    owner_user_id=command.user_id,
                    target_position_id=command.target_position_id,
                    action="apply",
                    source_scope="simulated_position",
                )
                .first()
            )
            if apply_event is None:
                raise _repair_blocked(
                    "original G5 apply event is unavailable in this owner scope",
                    "HISTORICAL_SELLABLE_REPAIR_APPLY_EVENT_MISSING",
                )
            if (
                HistoricalSellableRepairJournalModel._base_manager.using(database_alias)
                .filter(action="rollback", apply_event_id=apply_event.pk)
                .exists()
            ):
                raise _repair_blocked(
                    "original G5 apply event already has a rollback",
                    "HISTORICAL_SELLABLE_REPAIR_ALREADY_ROLLED_BACK",
                )

            active_reservations = lock_active_order_reservations(
                account_id=command.account_id,
                using=database_alias,
            )
            try:
                validate_account_v4_fill_history(
                    account=account,
                    intent=None,
                    using=database_alias,
                )
            except SimulatedTradeExecutionBlocked as error:
                raise _repair_blocked(
                    "account V4 history changed or is no longer complete",
                    "HISTORICAL_SELLABLE_LEDGER_INVALID",
                ) from error
            position = (
                PositionModel._base_manager.using(database_alias)
                .select_for_update(of=("self",))
                .filter(pk=command.target_position_id, account_id=command.account_id)
                .first()
            )
            if position is None:
                raise _repair_blocked(
                    "selected simulated Position no longer exists",
                    "HISTORICAL_SELLABLE_POSITION_MISSING",
                )
            target = HistoricalTargetPositionFact(
                position_id=int(position.pk),
                account_id=int(position.account_id),
                asset_code=str(position.asset_code),
                quantity=_decimal_field(position.quantity),
                available_quantity=_decimal_field(position.available_quantity),
                available_quantity_known=_bool_field(position.available_quantity_known),
                first_buy_date_known=_bool_field(position.first_buy_date_known),
            )
            proof = self._reconstruct_position_ledger(
                account_id=command.account_id,
                user_id=command.user_id,
                source=None,
                target=target,
                mapping=None,
                active_reservations=active_reservations,
                using=database_alias,
                cutoff_at=apply_event.evidence_cutoff_at,
            )
            _require_g5_repair_proof(
                proof=proof,
                account_id=command.account_id,
                user_id=command.user_id,
                target=target,
            )
            if proof.proof_hash != apply_event.evidence_proof_hash:
                raise _repair_blocked(
                    "ledger fills, releases, active holds, or evidence changed after apply",
                    "HISTORICAL_SELLABLE_REPAIR_EVIDENCE_CHANGED",
                )
            if (
                position.available_quantity != apply_event.after_available_quantity
                or position.available_quantity_known
                is not apply_event.after_available_quantity_known
            ):
                raise _repair_blocked(
                    "available-share state changed after apply; rollback was refused",
                    "HISTORICAL_SELLABLE_REPAIR_COMPARE_FAILED",
                )
            changed_at = timezone.now()
            updated = (
                PositionModel._base_manager.using(database_alias)
                .filter(
                    pk=position.pk,
                    account_id=command.account_id,
                    quantity=position.quantity,
                    available_quantity=apply_event.after_available_quantity,
                    available_quantity_known=apply_event.after_available_quantity_known,
                    updated_at=position.updated_at,
                )
                .update(
                    available_quantity=apply_event.before_available_quantity,
                    available_quantity_known=apply_event.before_available_quantity_known,
                    updated_at=changed_at,
                )
            )
            if updated != 1:
                raise _repair_blocked(
                    "simulated Position changed before rollback compare-and-set",
                    "HISTORICAL_SELLABLE_REPAIR_CONFLICT",
                )
            event = HistoricalSellableRepairJournalModel._default_manager.using(
                database_alias
            ).create(
                action="rollback",
                account_id=command.account_id,
                owner_user_id=command.user_id,
                actor_user_id=command.actor_user_id,
                source_scope=apply_event.source_scope,
                source_position_id=apply_event.source_position_id,
                target_position_id=apply_event.target_position_id,
                position_mapping_id=apply_event.position_mapping_id,
                security_id=apply_event.security_id,
                asset_code=apply_event.asset_code,
                idempotency_key=command.idempotency_key,
                request_hash=request_hash,
                apply_event_id=apply_event.pk,
                source_total_quantity=apply_event.source_total_quantity,
                target_total_quantity=apply_event.target_total_quantity,
                source_record_updated_at=apply_event.source_record_updated_at,
                evidence_cutoff_at=apply_event.evidence_cutoff_at,
                evidence_proof_hash=apply_event.evidence_proof_hash,
                before_available_quantity=apply_event.after_available_quantity,
                before_available_quantity_known=apply_event.after_available_quantity_known,
                after_available_quantity=apply_event.before_available_quantity,
                after_available_quantity_known=apply_event.before_available_quantity_known,
            )
            return _repair_result(event, outcome="rolled_back")

    def _reconstruct_position_ledger(
        self,
        *,
        account_id: int,
        user_id: int,
        source: HistoricalSourcePositionFact | None,
        target: HistoricalTargetPositionFact,
        mapping: HistoricalPositionMappingFact | None,
        active_reservations: list[SimulatedOrderReservationModel],
        using: str,
        cutoff_at: datetime | None = None,
    ) -> HistoricalLedgerSellabilityProof:
        """Validate one exact asset against its complete account reservation chain."""

        checked_cutoff = cutoff_at if cutoff_at is not None else timezone.now()
        if (
            target.quantity is None
            or (
                source is not None
                and (
                    source.position_id <= 0
                    or source.quantity is None
                    or source.asset_code != target.asset_code
                )
            )
            or (source is None and mapping is not None)
            or (source is not None and mapping is None)
        ):
            return _unavailable_proof(
                "LEDGER_SOURCE_TARGET_SCOPE_INVALID",
                cutoff_at=checked_cutoff,
            )

        trade_rows = tuple(
            SimulatedTradeModel._base_manager.using(using)
            .filter(account_id=account_id, asset_code=target.asset_code)
            .order_by("pk")
        )
        unsupported_trade_ids = tuple(
            int(trade.pk) for trade in trade_rows if trade.settlement_plan_binding_version != 4
        )

        asset_reservations = tuple(
            SimulatedOrderReservationModel._base_manager.using(using)
            .select_for_update(of=("self",))
            .filter(account_id=account_id, asset_code=target.asset_code)
            .order_by("pk")
        )
        security_ids = {row.security_id for row in asset_reservations}
        relevant_rows = (
            tuple(
                SimulatedOrderReservationModel._base_manager.using(using)
                .select_for_update(of=("self",))
                .filter(account_id=account_id)
                .filter(Q(asset_code=target.asset_code) | Q(security_id__in=tuple(security_ids)))
                .order_by("pk")
            )
            if security_ids
            else asset_reservations
        )
        if not security_ids:
            return _unavailable_proof(
                "LEDGER_OPENING_ANCHOR_MISSING",
                cutoff_at=checked_cutoff,
            )
        if len(security_ids) != 1 or any(
            row.asset_code != target.asset_code
            for row in relevant_rows
            if row.security_id in security_ids
        ):
            return _unavailable_proof(
                "LEDGER_SECURITY_ASSET_ALIAS",
                cutoff_at=checked_cutoff,
            )
        security_id = next(iter(security_ids))

        fill_facts: list[HistoricalLedgerFillFact] = []
        active_hold_facts: list[HistoricalLedgerHoldFact] = []
        active_by_id = {int(row.pk): row for row in active_reservations}
        try:
            for reservation_row in relevant_rows:
                chain = _locked_fill_chain(
                    reservation_row=reservation_row,
                    using=using,
                )
                if (
                    chain.intent.account_id != account_id
                    or chain.intent.user_id != user_id
                    or chain.intent.security_id != security_id
                    or chain.intent.asset_code != target.asset_code
                ):
                    return _unavailable_proof(
                        "LEDGER_RESERVATION_SCOPE_INVALID",
                        cutoff_at=checked_cutoff,
                    )
                for receipt_row, decoded in chain.rows:
                    raw_settlement_status = receipt_row.trade.settlement_status
                    if raw_settlement_status is None:
                        settlement_status: Literal["pending", "released"] | None = None
                    elif type(raw_settlement_status) is str and raw_settlement_status == "pending":
                        settlement_status = "pending"
                    elif type(raw_settlement_status) is str and raw_settlement_status == "released":
                        settlement_status = "released"
                    else:
                        return _unavailable_proof(
                            "LEDGER_SETTLEMENT_STATUS_INVALID",
                            cutoff_at=checked_cutoff,
                        )
                    mark_hash: str | None = None
                    if receipt_row.initial_position_mark_evidence is not None:
                        if type(receipt_row.initial_position_mark_evidence) is not dict:
                            return _unavailable_proof(
                                "LEDGER_INITIAL_MARK_INVALID",
                                cutoff_at=checked_cutoff,
                            )
                        mark_payload = cast(
                            dict[str, object],
                            receipt_row.initial_position_mark_evidence,
                        )
                        mark_json = json.dumps(
                            mark_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        mark_hash = decode_initial_position_mark_evidence(mark_json).proof_hash
                    fill_facts.append(
                        HistoricalLedgerFillFact(
                            trade_id=decoded.trade_id,
                            reservation_id=decoded.reservation_id,
                            fill_sequence=decoded.fill_sequence,
                            binding_version=4,
                            receipt_version=int(receipt_row.receipt_version),
                            receipt_hash=decoded.receipt_hash,
                            security_id=chain.intent.security_id,
                            asset_code=chain.intent.asset_code,
                            side=decoded.economics.side.value,
                            quantity=decoded.economics.quantity,
                            recorded_at=decoded.event.recorded_at,
                            prior_fill_count=decoded.economics.prior.fill_count,
                            settlement_status=settlement_status,
                            settlement_lag_sessions=decoded.proof.settlement_lag_sessions,
                            release_proof_hash=receipt_row.trade.settlement_release_proof_hash,
                            initial_position_mark_hash=mark_hash,
                        )
                    )
                active_row = active_by_id.get(int(reservation_row.pk))
                if active_row is not None and chain.reservation.side.value == "sell":
                    state_payload = {
                        "reservation_id": int(reservation_row.pk),
                        "request_hash": chain.reservation.identity.request_payload_hash,
                        "plan_snapshot_hash": str(reservation_row.plan_snapshot_hash),
                        "status": str(reservation_row.status),
                        "reserved_at": chain.reservation.reserved_at.isoformat(),
                        "quantity": format_ledger_quantity(chain.reservation.quantity),
                        "filled_quantity": format_ledger_quantity(
                            chain.reservation.filled_quantity
                        ),
                        "shares_reserved": format_ledger_quantity(
                            chain.reservation.shares_reserved
                        ),
                        "shares_consumed": format_ledger_quantity(
                            chain.reservation.shares_consumed
                        ),
                        "shares_released": format_ledger_quantity(
                            chain.reservation.shares_released
                        ),
                    }
                    state_hash = hashlib.sha256(
                        json.dumps(
                            state_payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    ).hexdigest()
                    if chain.reservation.remaining_shares > 0:
                        active_hold_facts.append(
                            HistoricalLedgerHoldFact(
                                reservation_id=int(reservation_row.pk),
                                security_id=chain.intent.security_id,
                                asset_code=chain.intent.asset_code,
                                side="sell",
                                remaining_shares=chain.reservation.remaining_shares,
                                reservation_state_hash=state_hash,
                            )
                        )
        except (
            ArithmeticError,
            AttributeError,
            ObjectDoesNotExist,
            SimulatedTradeExecutionBlocked,
            SimulatedSettlementContractError,
            TypeError,
            ValueError,
        ):
            return _unavailable_proof(
                "LEDGER_RESERVATION_CHAIN_INVALID",
                cutoff_at=checked_cutoff,
            )

        if unsupported_trade_ids:
            return _unavailable_proof(
                "LEDGER_TRADE_VERSION_UNSUPPORTED",
                cutoff_at=checked_cutoff,
            )
        if {fact.trade_id for fact in fill_facts} != {int(row.pk) for row in trade_rows}:
            return _unavailable_proof(
                "LEDGER_TRADE_RECEIPT_COVERAGE_GAP",
                cutoff_at=checked_cutoff,
            )
        fill_facts.sort(key=lambda fact: fact.trade_id)
        return prove_historical_ledger_sellability(
            HistoricalLedgerEvidence(
                owner_user_id=user_id,
                account_id=account_id,
                source_scope=(
                    "simulated_position" if source is None else "account_position_mapping"
                ),
                source_position_id=(source.position_id if source is not None else None),
                target_position_id=target.position_id,
                position_mapping_id=(mapping.mapping_id if mapping is not None else None),
                mapping_fact=mapping,
                security_id=security_id,
                asset_code=target.asset_code,
                cutoff_at=checked_cutoff,
                source_total_quantity=(source.quantity if source is not None else None),
                source_record_updated_at=(source.record_updated_at if source is not None else None),
                target_total_quantity=target.quantity,
                fills=tuple(fill_facts),
                active_holds=tuple(active_hold_facts),
            )
        )

    @staticmethod
    def _route_mismatch(
        database_alias: str,
        models_to_check: tuple[type[models.Model], ...],
    ) -> bool:
        """Refuse reads when configured routers disagree with the requested alias."""

        routed_aliases = {
            alias
            for alias in (router.db_for_read(model) for model in models_to_check)
            if alias is not None
        }
        return len(routed_aliases) > 1 or bool(
            routed_aliases and routed_aliases != {database_alias}
        )

    @staticmethod
    def _write_route_mismatch(
        database_alias: str,
        models_to_check: tuple[type[models.Model], ...],
    ) -> bool:
        """Refuse mutations when any G5 table routes writes to another alias."""

        routed_aliases = {
            alias
            for alias in (router.db_for_write(model) for model in models_to_check)
            if alias is not None
        }
        return len(routed_aliases) > 1 or bool(
            routed_aliases and routed_aliases != {database_alias}
        )

    @staticmethod
    def _mapping(record: LedgerMigrationMapModel) -> LedgerMappingProjection:
        """Narrow one ORM map row to the Application's immutable projection."""

        return LedgerMappingProjection(
            mapping_id=int(record.pk),
            source_app=str(record.source_app),
            source_table=str(record.source_table),
            source_id=int(record.source_id),
            target_table=str(record.target_table),
            target_id=int(record.target_id),
        )


def _decimal_field(value: object) -> Decimal | None:
    """Accept only a Decimal returned by the known DecimalField boundary."""

    return value if isinstance(value, Decimal) else None


def _repair_request_hash(
    command: HistoricalSellableRepairCommand,
    database_alias: str,
) -> str:
    """Seal one explicit self-simulated apply or rollback identity for replay."""

    if type(command) is not HistoricalSellableRepairCommand:
        raise _repair_blocked(
            "G5 repair request type is invalid",
            "HISTORICAL_SELLABLE_REPAIR_REQUEST_INVALID",
        )
    preview_cutoff = command.preview_evidence_cutoff_at
    preview_hash = command.preview_evidence_proof_hash
    preview_quantity = command.preview_available_quantity
    preview_known = command.preview_available_quantity_known
    normalized_preview_quantity: Decimal | None = None
    if command.action == "apply":
        if (
            type(preview_cutoff) is not datetime
            or preview_cutoff.tzinfo is None
            or preview_cutoff.utcoffset() is None
            or not _is_lower_sha256(preview_hash)
            or type(preview_quantity) is not Decimal
            or type(preview_known) is not bool
        ):
            raise _repair_blocked(
                "G5 apply request is missing its exact read-only preview",
                "HISTORICAL_SELLABLE_REPAIR_PREVIEW_INVALID",
            )
        normalized_preview_quantity = normalize_ledger_quantity(preview_quantity).value
        preview_valid = normalized_preview_quantity is not None
    else:
        preview_valid = all(
            value is None
            for value in (preview_cutoff, preview_hash, preview_quantity, preview_known)
        )
    if (
        command.action not in ("apply", "rollback")
        or not preview_valid
        or any(
            type(value) is not int or value <= 0
            for value in (
                command.user_id,
                command.account_id,
                command.target_position_id,
                command.actor_user_id,
            )
        )
        or command.actor_user_id != command.user_id
        or type(command.idempotency_key) is not str
        or not command.idempotency_key.strip()
        or len(command.idempotency_key) > 128
        or type(database_alias) is not str
        or not database_alias.strip()
        or database_alias != database_alias.strip()
        or (command.action == "apply" and command.apply_event_id is not None)
        or (
            command.action == "rollback"
            and (type(command.apply_event_id) is not int or command.apply_event_id <= 0)
        )
    ):
        raise _repair_blocked(
            "G5 repair request identity is invalid",
            "HISTORICAL_SELLABLE_REPAIR_REQUEST_INVALID",
        )
    payload = {
        "schema": "ash03.g5-sellable-repair-request.v1",
        "source_scope": "simulated_position",
        "action": command.action,
        "database_alias": database_alias,
        "owner_user_id": command.user_id,
        "account_id": command.account_id,
        "target_position_id": command.target_position_id,
        "actor_user_id": command.actor_user_id,
        "idempotency_key": command.idempotency_key,
        "apply_event_id": command.apply_event_id,
        "preview_evidence_cutoff_at": (
            preview_cutoff.astimezone(UTC).isoformat() if preview_cutoff is not None else None
        ),
        "preview_evidence_proof_hash": preview_hash,
        "preview_available_quantity": (
            format_ledger_quantity(normalized_preview_quantity)
            if command.action == "apply"
            else None
        ),
        "preview_available_quantity_known": preview_known,
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _require_g5_repair_proof(
    *,
    proof: HistoricalLedgerSellabilityProof,
    account_id: int,
    user_id: int,
    target: HistoricalTargetPositionFact,
) -> None:
    """Require one complete self-simulated V4 proof before changing Position state."""

    if (
        proof.reason_codes
        or proof.source_scope != "simulated_position"
        or proof.owner_user_id != user_id
        or proof.account_id != account_id
        or proof.source_position_id is not None
        or proof.target_position_id != target.position_id
        or proof.position_mapping_id is not None
        or type(proof.security_id) is not str
        or not proof.security_id.strip()
        or proof.asset_code != target.asset_code
        or proof.total_quantity is None
        or proof.total_quantity != target.quantity
        or proof.available_quantity is None
        or proof.active_sell_hold_quantity is None
        or proof.supported_sellable_quantity is None
        or proof.cutoff_at is None
        or proof.cutoff_at.tzinfo is None
        or proof.cutoff_at.utcoffset() is None
        or not _is_lower_sha256(proof.proof_hash)
        or target.first_buy_date_known is not True
    ):
        reason = proof.reason_codes[0] if proof.reason_codes else "LEDGER_PROOF_SCOPE_INVALID"
        raise _repair_blocked(
            f"simulated ledger proof is incomplete: {reason}",
            "HISTORICAL_SELLABLE_LEDGER_INVALID",
        )


def _repair_result(
    event: HistoricalSellableRepairJournalModel,
    *,
    outcome: Literal["applied", "rolled_back", "replayed"],
) -> HistoricalSellableRepairResult:
    """Narrow one append-only journal row into its public application receipt."""

    if (
        type(event.pk) is not int
        or type(event.before_available_quantity) is not Decimal
        or type(event.after_available_quantity) is not Decimal
        or type(event.before_available_quantity_known) is not bool
        or type(event.after_available_quantity_known) is not bool
        or type(event.evidence_cutoff_at) is not datetime
        or type(event.evidence_proof_hash) is not str
    ):
        raise _repair_blocked(
            "stored G5 repair event cannot be read exactly",
            "HISTORICAL_SELLABLE_REPAIR_EVENT_INVALID",
        )
    if event.action not in ("apply", "rollback"):
        raise _repair_blocked(
            "stored G5 repair event action is unknown",
            "HISTORICAL_SELLABLE_REPAIR_EVENT_INVALID",
        )
    return HistoricalSellableRepairResult(
        journal_event_id=event.pk,
        apply_event_id=(event.pk if event.action == "apply" else event.apply_event_id),
        action=cast(Literal["apply", "rollback"], event.action),
        outcome=outcome,
        user_id=int(event.owner_user_id),
        account_id=int(event.account_id),
        target_position_id=int(event.target_position_id),
        before_available_quantity=event.before_available_quantity,
        before_available_quantity_known=event.before_available_quantity_known,
        after_available_quantity=event.after_available_quantity,
        after_available_quantity_known=event.after_available_quantity_known,
        evidence_cutoff_at=event.evidence_cutoff_at,
        evidence_proof_hash=event.evidence_proof_hash,
    )


def _is_lower_sha256(value: str | None) -> bool:
    """Require one canonical lowercase SHA-256 value at the ORM boundary."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _repair_blocked(message: str, code: str) -> SimulatedTradeExecutionBlocked:
    """Use the established typed simulation failure for G5 write refusals."""

    return SimulatedTradeExecutionBlocked(message, code=code)


def _bool_field(value: object) -> bool | None:
    """Preserve the knownness flag only when the ORM returned a real Boolean."""

    return value if isinstance(value, bool) else None


def _unavailable_proof(
    reason_code: str,
    *,
    cutoff_at: datetime | None = None,
) -> HistoricalLedgerSellabilityProof:
    """Return no quantity or digest when any persisted-history gate is unknown."""

    checked_cutoff = (
        cutoff_at
        if type(cutoff_at) is datetime
        and cutoff_at.tzinfo is not None
        and cutoff_at.utcoffset() is not None
        else None
    )
    return HistoricalLedgerSellabilityProof(
        total_quantity=None,
        available_quantity=None,
        active_sell_hold_quantity=None,
        supported_sellable_quantity=None,
        owner_user_id=None,
        account_id=None,
        source_scope=None,
        source_position_id=None,
        target_position_id=None,
        position_mapping_id=None,
        security_id=None,
        asset_code=None,
        source_record_updated_at=None,
        cutoff_at=checked_cutoff,
        proof_hash=None,
        reason_codes=(reason_code, "SETTLEMENT_EVIDENCE_UNAVAILABLE"),
    )
