"""Read-only Simulated Trading repository for the G5 quantity diagnostic."""

from __future__ import annotations

from decimal import Decimal

from django.db import models, router
from django.db.models import Q

from apps.simulated_trading.application.historical_sellable_difference import (
    LedgerMappingProjection,
    SelectedAccountScopeRead,
    TargetPositionProjection,
    TargetPositionScopeRead,
)
from apps.simulated_trading.infrastructure.models import (
    LedgerMigrationMapModel,
    PositionModel,
    SimulatedAccountModel,
)


class DjangoHistoricalSellableDifferenceRepository:
    """Read only the requested simulated account, its positions, and map edges."""

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
        source_position_ids: tuple[int, ...],
        database_alias: str,
    ) -> TargetPositionScopeRead:
        """Read selected-account positions plus exact source and reverse map edges."""

        if self._route_mismatch(
            database_alias,
            (SimulatedAccountModel, PositionModel, LedgerMigrationMapModel),
        ):
            return TargetPositionScopeRead("database_route_mismatch", None, (), (), frozenset())

        account_exists = (
            SimulatedAccountModel._default_manager.using(database_alias)
            .filter(
                pk=account_id,
                user_id=user_id,
            )
            .exists()
        )
        if not account_exists:
            return TargetPositionScopeRead(
                "account_unavailable", database_alias, (), (), frozenset()
            )

        records = (
            PositionModel._default_manager.using(database_alias)
            .filter(account_id=account_id)
            .only(
                "id",
                "account_id",
                "asset_code",
                "quantity",
                "available_quantity",
                "available_quantity_known",
            )
            .order_by("pk")
        )
        positions = tuple(
            TargetPositionProjection(
                position_id=int(record.pk),
                account_id=int(record.account_id),
                asset_code=str(record.asset_code),
                quantity=_decimal_field(record.quantity),
                available_quantity=_decimal_field(record.available_quantity),
                available_quantity_known=_bool_field(record.available_quantity_known),
            )
            for record in records
        )
        target_ids = tuple(position.position_id for position in positions)
        mapping_filter = Q(
            source_app="account",
            source_table="position",
            source_id__in=source_position_ids,
        ) | Q(target_table="simulated_position", target_id__in=target_ids)
        mapping_records = (
            LedgerMigrationMapModel._default_manager.using(database_alias)
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

        return TargetPositionScopeRead(
            status="ready",
            database_alias=database_alias,
            positions=positions,
            mappings=mappings,
            existing_target_position_ids=frozenset(existing_target_ids),
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


def _bool_field(value: object) -> bool | None:
    """Preserve the knownness flag only when the ORM returned a real Boolean."""

    return value if isinstance(value, bool) else None
