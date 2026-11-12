"""Compose explicit current Config Center, calendar, V4 ledger, and local-fill readers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.data_center.calendar_publication_operations_composition import (
    read_current_exchange_calendar_reference,
)
from apps.simulated_trading.application.corporate_action_tax_settlement_history import (
    CurrentSimulatedTaxDateRuleReader,
    ReadSimulatedTaxSettlementHistoryUseCase,
    SimulatedTaxDateConventionRead,
    TaxSettlementHistoryClock,
)
from apps.simulated_trading.corporate_action_ownership_history_composition import (
    build_corporate_action_ownership_history_repository,
)
from apps.simulated_trading.corporate_action_tax_date_convention_composition import (
    read_current_simulated_dividend_tax_date_convention,
)
from apps.simulated_trading.domain.simulated_tax_settlement_history import (
    SimulatedTaxDateRuleRuntimeProvenance,
)
from apps.simulated_trading.execution_settlement_composition import (
    build_current_published_execution_calendar_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_settlement_history_repository import (
    DjangoSimulatedTaxSettlementHistoryRepository,
)
from apps.simulated_trading.infrastructure.local_daily_match_event_reader import (
    DjangoLocalDailyMatchEventReader,
)
from core.exceptions import BusinessLogicError


@dataclass(frozen=True, slots=True)
class _CurrentSimulatedTaxDateRuleReader(CurrentSimulatedTaxDateRuleReader):
    """Bind the public Config Center current-read function to one runtime environment."""

    runtime_environment: str

    def read_current(
        self,
        *,
        environment: str,
        as_of: datetime,
        physical_account_id: int,
        canonical_account_id: str,
        owner_user_id: int,
    ) -> SimulatedTaxDateConventionRead:
        """Return the selected rule with every current profile/snapshot observation clock."""

        if environment != self.runtime_environment:
            raise BusinessLogicError(
                "tax date environment differs from the composed current reader",
                code="TAX_SETTLEMENT_DATE_RULE_UNAVAILABLE",
            )
        configured = read_current_simulated_dividend_tax_date_convention(
            environment=environment,
            as_of=as_of,
            account_kind="simulated",
            physical_account_id=physical_account_id,
            canonical_account_id=canonical_account_id,
            owner_user_id=owner_user_id,
        )
        provenance = SimulatedTaxDateRuleRuntimeProvenance(
            convention_sha256=configured.convention.semantic_sha256,
            environment=configured.environment,
            definition_key=configured.definition_key,
            profile_id=configured.profile_id,
            profile_key=configured.profile_key,
            profile_version=configured.profile_version,
            profile_content_hash=configured.profile_content_hash,
            snapshot_id=configured.snapshot_id,
            snapshot_hash=configured.snapshot_hash,
            created_at=configured.created_at,
            known_at=configured.known_at,
            activated_at=configured.activated_at,
            snapshot_generated_at=configured.snapshot_generated_at,
            effective_at=configured.effective_at,
            as_of=configured.as_of,
        )
        return SimulatedTaxDateConventionRead(configured.convention, provenance)


@dataclass(frozen=True, slots=True)
class _DjangoTaxSettlementHistoryClock(TaxSettlementHistoryClock):
    """Use Django's timezone-aware server clock for current source reads."""

    def now(self) -> datetime:
        """Return the current aware server instant."""

        return timezone.now()


def build_read_simulated_tax_settlement_history_use_case(
    *,
    runtime_environment: str,
    calendar_dataset_key: str,
    using: str = DEFAULT_DB_ALIAS,
) -> ReadSimulatedTaxSettlementHistoryUseCase:
    """Compose the read-only adapter; construction does not enable tax assessment or posting."""

    if (
        type(runtime_environment) is not str
        or not runtime_environment
        or runtime_environment.strip() != runtime_environment
        or type(calendar_dataset_key) is not str
        or not calendar_dataset_key
        or calendar_dataset_key.strip() != calendar_dataset_key
        or using != DEFAULT_DB_ALIAS
    ):
        raise BusinessLogicError(
            "tax history requires explicit runtime/calendar scope on the default alias",
            code="TAX_SETTLEMENT_HISTORY_SCOPE_INVALID",
        )
    ownership_reader = build_corporate_action_ownership_history_repository(
        runtime_environment=runtime_environment,
        using=using,
    )
    source_event_reader = DjangoLocalDailyMatchEventReader(using=using)
    input_reader = DjangoSimulatedTaxSettlementHistoryRepository(
        using=using,
        ownership_history_reader=ownership_reader,
        source_event_reader=source_event_reader,
    )
    calendar_reader = build_current_published_execution_calendar_reader(
        dataset_key=calendar_dataset_key,
        runtime_environment=runtime_environment,
        read_publication=read_current_exchange_calendar_reference,
    )
    return ReadSimulatedTaxSettlementHistoryUseCase(
        input_reader=input_reader,
        date_rule_reader=_CurrentSimulatedTaxDateRuleReader(runtime_environment),
        calendar_reader=calendar_reader,
        clock=_DjangoTaxSettlementHistoryClock(),
        using=using,
    )


__all__ = ["build_read_simulated_tax_settlement_history_use_case"]
