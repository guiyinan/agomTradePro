"""Concrete R5 audit-ledger composition using only Application owner ports."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.fixed_income.application.relative_value import (
    BondMasterEvidenceProvider,
    CalendarEvidenceProvider,
    CashFlowEvidenceProvider,
    ExactOwnerEvidenceProvider,
    ExactPITInputEvidenceProvider,
    PublicationEvidenceProvider,
    R5RelativeValuePolicySetProvider,
    RunR5RelativeValueResearch,
)
from apps.fixed_income.application.relative_value_persistence import (
    GetExactPersistedR5RelativeValue,
    PersistR5RelativeValue,
    PersistR5RelativeValueCommand,
    R5CrossOwnerUnitOfWork,
    R5OwnerAtomicApplicationPort,
    R5PersistedRelativeValueBundle,
    R5RelativeValuePersistenceConflict,
    R5RelativeValuePersistenceDraft,
)
from apps.fixed_income.infrastructure.relative_value_models import (
    FixedIncomeR5InputReceiptModel,
    FixedIncomeR5ResultModel,
    _activate_r5_relative_value_unit_of_work,
    _authorize_r5_owner_graph_append,
    _claim_r5_relative_value_insert,
    _r5_owner_graph_append_is_authorized,
    _r5_relative_value_unit_of_work_is_active,
)
from apps.fixed_income.infrastructure.relative_value_repository import (
    DjangoR5RelativeValueRepository,
    DjangoR5RelativeValueServerClock,
    R5RelativeValueServerClock,
    _bundle_from_model,
    _get_r5_result_by_assessment_id,
    _receipt_model_values,
    _result_model_values,
)


class _CrossOwnerUnitOfWork(R5CrossOwnerUnitOfWork):
    """Activate Data Center, Portfolio and Research Application UoWs together."""

    def __init__(
        self,
        *,
        data_center: R5OwnerAtomicApplicationPort,
        portfolio: R5OwnerAtomicApplicationPort,
        research: R5OwnerAtomicApplicationPort,
    ) -> None:
        ports = (data_center, portfolio, research)
        if tuple(port.owner for port in ports) != (
            "data_center",
            "portfolio",
            "research",
        ):
            raise R5RelativeValuePersistenceConflict(
                "R5 cross-owner ports have invalid owner identities"
            )
        keys = {port.unit_of_work_key for port in ports}
        if len(keys) != 1:
            raise R5RelativeValuePersistenceConflict(
                "R5 cross-owner ports must share one transaction boundary"
            )
        self._ports = ports
        self._unit_of_work_key = next(iter(keys))

    @property
    def unit_of_work_key(self) -> str:
        """Return the shared owner transaction key."""

        return self._unit_of_work_key

    def atomic(self) -> AbstractContextManager[None]:
        """Return a context activating and checking every owner UoW."""

        return self._atomic()

    @contextmanager
    def _atomic(self) -> Iterator[None]:
        with ExitStack() as stack:
            for port in self._ports:
                stack.enter_context(port.atomic())
            for port in self._ports:
                port.require_active_unit_of_work()
            yield


@dataclass(frozen=True)
class DjangoR5RelativeValueRuntime:
    """Fully wired Phase-A evaluator and Phase-B1 audit persistence runtime."""

    phase_a: RunR5RelativeValueResearch
    persist: PersistR5RelativeValue
    query: GetExactPersistedR5RelativeValue


def build_django_r5_relative_value_runtime(
    *,
    input_provider: ExactPITInputEvidenceProvider,
    policy_provider: R5RelativeValuePolicySetProvider,
    publication_provider: PublicationEvidenceProvider,
    bond_master_provider: BondMasterEvidenceProvider,
    cash_flow_provider: CashFlowEvidenceProvider,
    calendar_provider: CalendarEvidenceProvider,
    exact_owner_provider: ExactOwnerEvidenceProvider,
    data_center_unit_of_work: R5OwnerAtomicApplicationPort,
    portfolio_unit_of_work: R5OwnerAtomicApplicationPort,
    research_unit_of_work: R5OwnerAtomicApplicationPort,
    clock: R5RelativeValueServerClock | None = None,
    using: str = "default",
) -> DjangoR5RelativeValueRuntime:
    """Wire local persistence to injected owner Application ports only."""

    phase_a = RunR5RelativeValueResearch(
        input_provider=input_provider,
        policy_provider=policy_provider,
        publication_provider=publication_provider,
        bond_master_provider=bond_master_provider,
        cash_flow_provider=cash_flow_provider,
        calendar_provider=calendar_provider,
        exact_owner_provider=exact_owner_provider,
    )
    repository = DjangoR5RelativeValueRepository(using=using)
    owner_unit_of_work = _CrossOwnerUnitOfWork(
        data_center=data_center_unit_of_work,
        portfolio=portfolio_unit_of_work,
        research=research_unit_of_work,
    )
    if repository.unit_of_work_key != owner_unit_of_work.unit_of_work_key:
        raise R5RelativeValuePersistenceConflict(
            "R5 repository and owner ports must share one transaction boundary"
        )

    # The only persistence authority is captured by these local closures.  No
    # repository/runtime attribute exposes the token, an authorization context,
    # or a Draft-accepting append method.  Reflection into function closures is
    # intentionally outside the internal API threat model.
    unit_of_work_token = object()
    server_clock = clock or DjangoR5RelativeValueServerClock()
    execute_authoritative = phase_a.execute_authoritative

    def require_repository_unit_of_work() -> None:
        connection = transaction.get_connection(using)
        if (
            not _r5_relative_value_unit_of_work_is_active(unit_of_work_token)
            or not connection.in_atomic_block
        ):
            raise R5RelativeValuePersistenceConflict(
                "R5 persistence requires its closure-bound repository unit of work"
            )

    def match_draft(
        model: FixedIncomeR5ResultModel,
        draft: R5RelativeValuePersistenceDraft,
    ) -> R5PersistedRelativeValueBundle:
        persisted = _bundle_from_model(model)
        persisted_draft = R5RelativeValuePersistenceDraft(
            assessment_id=persisted.result.assessment.assessment_id,
            input_set=persisted.receipt.input_set,
            policy_set=persisted.receipt.policy_set,
            assessment=persisted.result.assessment,
        )
        if persisted_draft.draft_hash != draft.draft_hash:
            raise R5RelativeValuePersistenceConflict(
                "R5 assessment identity conflicts with different evidence"
            )
        return persisted

    def append_verified(
        draft: R5RelativeValuePersistenceDraft,
        *,
        command_hash: str,
    ) -> R5PersistedRelativeValueBundle:
        require_repository_unit_of_work()
        if command_hash != draft.expected_command_hash:
            raise R5RelativeValuePersistenceConflict(
                "R5 append command differs from the verified owner graph"
            )
        if not _r5_owner_graph_append_is_authorized(
            token=unit_of_work_token,
            command_hash=command_hash,
            draft_hash=draft.draft_hash,
        ):
            raise R5RelativeValuePersistenceConflict(
                "R5 append requires exact cross-owner authorization"
            )
        existing = _get_r5_result_by_assessment_id(
            draft.assessment_id,
            using=using,
        )
        if existing is not None:
            return match_draft(existing, draft)
        try:
            bundle = R5PersistedRelativeValueBundle.from_draft(
                draft,
                recorded_at=server_clock.now(),
            )
        except ValueError as error:
            raise R5RelativeValuePersistenceConflict(
                "R5 repository server clock is invalid for this evaluation"
            ) from error
        receipt_values = _receipt_model_values(bundle.receipt)
        result_values = _result_model_values(bundle.result)
        try:
            with transaction.atomic(using=using):
                with _claim_r5_relative_value_insert(
                    token=unit_of_work_token,
                    command_hash=command_hash,
                    draft_hash=draft.draft_hash,
                    model_type=FixedIncomeR5InputReceiptModel,
                    expected_values=receipt_values,
                ):
                    receipt_model = FixedIncomeR5InputReceiptModel(**receipt_values)
                    receipt_model.full_clean()
                    receipt_model.save(force_insert=True, using=using)
                result_claim_values = {
                    **result_values,
                    "receipt_id": receipt_model.pk,
                }
                with _claim_r5_relative_value_insert(
                    token=unit_of_work_token,
                    command_hash=command_hash,
                    draft_hash=draft.draft_hash,
                    model_type=FixedIncomeR5ResultModel,
                    expected_values=result_claim_values,
                ):
                    result_model = FixedIncomeR5ResultModel(
                        receipt=receipt_model,
                        **result_values,
                    )
                    result_model.full_clean()
                    result_model.save(force_insert=True, using=using)
        except (IntegrityError, ValidationError, ValueError) as error:
            winner = _get_r5_result_by_assessment_id(
                draft.assessment_id,
                using=using,
            )
            if winner is None:
                raise R5RelativeValuePersistenceConflict(
                    "R5 relative-value append conflict"
                ) from error
            return match_draft(winner, draft)
        restored = _bundle_from_model(result_model)
        if restored != bundle:
            raise R5RelativeValuePersistenceConflict(
                "R5 relative-value append did not round-trip exactly"
            )
        return restored

    class ClosureBoundPersistenceWriter:
        """ID-only writer whose authority exists solely in enclosing locals."""

        __slots__ = ()

        def persist(
            self,
            command: PersistR5RelativeValueCommand,
        ) -> R5PersistedRelativeValueBundle:
            """Reread all owners and append under one shared transaction."""

            with owner_unit_of_work.atomic():
                with transaction.atomic(using=using):
                    with _activate_r5_relative_value_unit_of_work(unit_of_work_token):
                        run = execute_authoritative(command.phase_a_command)
                        draft = R5RelativeValuePersistenceDraft.from_authoritative_run(run)
                        if command.command_hash != draft.expected_command_hash:
                            raise R5RelativeValuePersistenceConflict(
                                "R5 command does not authorize this owner graph"
                            )
                        with _authorize_r5_owner_graph_append(
                            token=unit_of_work_token,
                            command_hash=command.command_hash,
                            draft_hash=draft.draft_hash,
                        ):
                            return append_verified(
                                draft,
                                command_hash=command.command_hash,
                            )

    writer = ClosureBoundPersistenceWriter()
    return DjangoR5RelativeValueRuntime(
        phase_a=phase_a,
        persist=PersistR5RelativeValue(writer=writer),
        query=GetExactPersistedR5RelativeValue(repository),
    )


__all__ = [
    "DjangoR5RelativeValueRuntime",
    "build_django_r5_relative_value_runtime",
]
