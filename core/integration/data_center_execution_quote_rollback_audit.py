"""Bridge execution quote rollback facts to the canonical Audit application."""

from __future__ import annotations

from apps.audit.application.data_publication_rollback_audit import (
    AppendDataPublicationRollbackAuditObservationUseCase,
    DataPublicationRollbackAuditObservation,
    build_data_publication_rollback_audit_event,
)
from apps.audit.application.repository_provider import get_data_publication_rollback_audit_writer
from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxCommit
from apps.audit.domain.system_audit_event import AuditOutcome, AuditScopeRef
from apps.data_center.application.execution_quote_pointer_rollback import (
    ExecutionQuotePointerRollbackAuditObservation,
    ExecutionQuotePointerRollbackAuditReceipt,
    ExecutionQuotePointerRollbackError,
)


class CoreDataCenterExecutionQuoteRollbackAuditBridge:
    """Translate Data Center rollback evidence and verify the canonical event pair."""

    def __init__(
        self,
        audit_writer: AppendDataPublicationRollbackAuditObservationUseCase,
    ) -> None:
        """Bind the bridge to one Audit Application use case."""

        if type(audit_writer) is not AppendDataPublicationRollbackAuditObservationUseCase:
            raise TypeError("execution pointer rollback requires the canonical Audit use case")
        self._audit_writer = audit_writer

    @property
    def database_alias(self) -> str:
        """Return the alias used by the canonical Audit and outbox repositories."""

        return self._audit_writer.database_alias

    def execute_in_caller_transaction(
        self,
        observation: ExecutionQuotePointerRollbackAuditObservation,
        *,
        exact_replay: bool,
    ) -> ExecutionQuotePointerRollbackAuditReceipt:
        """Write or prove the exact event/outbox pair without creating a new transaction."""

        if type(observation) is not ExecutionQuotePointerRollbackAuditObservation:
            raise ExecutionQuotePointerRollbackError("rollback Audit observation is invalid")
        observation.__post_init__()
        audit_observation = DataPublicationRollbackAuditObservation(
            dataset_key="equity.quote.snapshot",
            publication_key="execution",
            publication_id=observation.target_publication_id,
            publication_version=observation.target_publication_version,
            publication_hash=observation.target_publication_hash,
            rollback_id=observation.rollback_id,
            rollback_version=observation.rollback_version,
            rollback_content_hash=observation.rollback_content_hash,
            previous_publication_id=observation.previous_publication_id,
            previous_publication_version=observation.previous_publication_version,
            previous_publication_hash=observation.previous_publication_hash,
            run_id=observation.run_id,
            occurred_at=observation.occurred_at,
            recorded_at=observation.recorded_at,
            outcome=AuditOutcome.ROLLED_BACK,
            scope=AuditScopeRef(
                tenant_id=observation.tenant_id,
                owner_id=observation.owner_id,
            ),
            previous_pointer_activation_id=observation.previous_pointer_activation_id,
        )
        commit = self._audit_writer.execute_in_caller_transaction(
            audit_observation,
            exact_replay=exact_replay,
        )
        if type(commit) is not SystemAuditEventOutboxCommit:
            raise ExecutionQuotePointerRollbackError(
                "Audit returned an invalid event/outbox commit"
            )
        try:
            expected_event = build_data_publication_rollback_audit_event(
                audit_observation,
                sequence_no=commit.event.sequence_no,
                predecessor_hash=commit.event.predecessor_hash,
            )
            expected_event.validate_hashes()
            commit.event.validate_hashes()
        except (AttributeError, TypeError, ValueError) as error:
            raise ExecutionQuotePointerRollbackError(
                "Audit event failed exact validation"
            ) from error
        if (
            commit.event != expected_event
            or commit.event_id != expected_event.event_id
            or commit.idempotency_key != expected_event.idempotency_key
            or commit.outbox_id.int == 0
        ):
            raise ExecutionQuotePointerRollbackError(
                "Audit commit does not bind the exact rollback event and outbox"
            )
        return ExecutionQuotePointerRollbackAuditReceipt(
            target_publication_id=observation.target_publication_id,
            target_publication_version=observation.target_publication_version,
            target_publication_hash=observation.target_publication_hash,
            rollback_id=observation.rollback_id,
            rollback_version=observation.rollback_version,
            rollback_content_hash=observation.rollback_content_hash,
            previous_publication_id=observation.previous_publication_id,
            previous_publication_version=observation.previous_publication_version,
            previous_publication_hash=observation.previous_publication_hash,
            previous_pointer_activation_id=observation.previous_pointer_activation_id,
            run_id=observation.run_id,
            occurred_at=observation.occurred_at,
            recorded_at=observation.recorded_at,
            tenant_id=observation.tenant_id,
            owner_id=observation.owner_id,
            event_id=commit.event_id,
            event_content_hash=expected_event.content_hash,
            outbox_id=commit.outbox_id,
            idempotency_key=commit.idempotency_key,
        )


def build_execution_quote_rollback_audit_bridge(
    *,
    environment: str,
    using: str,
) -> CoreDataCenterExecutionQuoteRollbackAuditBridge:
    """Compose and validate the Audit capability outside the Data Center App."""

    writer = get_data_publication_rollback_audit_writer(environment=environment, using=using)
    if (
        type(writer) is not AppendDataPublicationRollbackAuditObservationUseCase
        or writer.database_alias != using
    ):
        raise ExecutionQuotePointerRollbackError(
            "canonical rollback Audit runtime is unavailable on the selected alias"
        )
    return CoreDataCenterExecutionQuoteRollbackAuditBridge(writer)


__all__ = [
    "CoreDataCenterExecutionQuoteRollbackAuditBridge",
    "build_execution_quote_rollback_audit_bridge",
]
