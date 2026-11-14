"""Compose same-database financial tax operations with original Audit/Outbox."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from django.db import connections, transaction
from django.utils import timezone

from apps.audit.corporate_action_tax_assessment_composition import (
    TaxAssessmentAuditCoordinatorPort,
    build_tax_assessment_audit_coordinator,
)
from apps.simulated_trading.application.corporate_action_tax_assessment import (
    TaxAssessmentClockPort,
)
from apps.simulated_trading.application.corporate_action_tax_liability import (
    CorporateActionTaxLiabilityUseCase,
    TaxLiabilityAtomicWriterPort,
    _blocked,
)
from apps.simulated_trading.application.corporate_action_tax_liability_authority import (
    AuditedTaxLiabilityScopeVerifierPort,
)
from apps.simulated_trading.audited_corporate_action_tax_assessment_composition import (
    _build_event,
    _event_id,
    _stream_id,
)
from apps.simulated_trading.corporate_action_tax_assessment_window_composition import (
    read_retained_tax_assessment_window_proof,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    _activate_tax_liability_uow,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_writer import (
    DjangoTaxLiabilityAtomicWriter,
)


class _ServerClock:
    """Use actual aware server time without refreshing source observation clocks."""

    def now(self) -> datetime:
        """Read the current server instant."""
        return timezone.now()


class DjangoRetainedTaxAssessmentAuditVerifier:
    """Verify the exact originally committed nonfinancial assessment Audit pair."""

    def __init__(self, *, audit: TaxAssessmentAuditCoordinatorPort) -> None:
        """Use the existing same-UOW public Audit coordinator."""
        self._audit = audit

    def verify_original(self, header: Header, *, as_of: datetime) -> None:
        """Reject missing or changed original Audit evidence without repairing it."""
        self._audit.lock_streams((_stream_id(header),))
        winner = self._audit.get_winner_targeted(
            event_id=_event_id(header), event_version="1", as_of=as_of, lock=True
        )
        if winner is None:
            raise _blocked("The original assessment Audit event is missing")
        expected = _build_event(
            header,
            sequence_no=winner.sequence_no,
            predecessor_hash=winner.predecessor_hash,
            official_window_proof=read_retained_tax_assessment_window_proof(header, winner),
        )
        outbox = self._audit.get_exact_outbox_winner_targeted(expected)
        if winner != expected or outbox is None or outbox.event != expected:
            raise _blocked("The original assessment Audit/Outbox pair is incomplete or different")


class DjangoTaxLiabilityAtomicUnitOfWork:
    """Own the outer transaction for authority, cash, journal, Audit and Outbox."""

    def __init__(
        self,
        *,
        using: str,
        verifier: AuditedTaxLiabilityScopeVerifierPort,
        audit: TaxAssessmentAuditCoordinatorPort,
        clock: TaxAssessmentClockPort,
    ) -> None:
        """Require same-alias actual authority, financial storage and Audit capabilities."""
        if verifier.database_alias != using or audit.database_alias != using:
            raise _blocked("Financial UOW, current authority and Audit aliases must agree")
        self._using, self._verifier, self._audit, self._clock = using, verifier, audit, clock
        self._active = False

    @property
    def database_alias(self) -> str:
        """Return the common transaction alias."""
        return self._using

    @contextmanager
    def atomic(self, *, using: str) -> Iterator[TaxLiabilityAtomicWriterPort]:
        """Open an unnested PostgreSQL READ COMMITTED transaction and revoke on exit."""
        connection = connections[using]
        if (
            using != self._using
            or self._active
            or connection.in_atomic_block
            or connection.vendor != "postgresql"
        ):
            raise _blocked("Financial tax writes require an unnested PostgreSQL UOW")
        self._active = True
        writer: DjangoTaxLiabilityAtomicWriter | None = None
        try:
            with transaction.atomic(using=using):
                with connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_isolation")
                    if cursor.fetchone() != ("read committed",):
                        raise _blocked("Financial tax writes require READ COMMITTED isolation")
                with self._audit.caller_owned_atomic(), _activate_tax_liability_uow() as token:
                    writer = DjangoTaxLiabilityAtomicWriter(
                        using=using,
                        token=token,
                        verifier=self._verifier,
                        audit=self._audit,
                        clock=self._clock,
                        assessment_audit=DjangoRetainedTaxAssessmentAuditVerifier(
                            audit=self._audit
                        ),
                    )
                    try:
                        yield writer
                    finally:
                        writer.close()
        finally:
            self._active = False


def build_audited_tax_liability_use_case(
    *,
    scope_verifier: AuditedTaxLiabilityScopeVerifierPort,
    using: str,
    clock: TaxAssessmentClockPort | None = None,
    audit: TaxAssessmentAuditCoordinatorPort | None = None,
) -> CorporateActionTaxLiabilityUseCase:
    """Compose financial writes only with an explicit current tax-withholding verifier."""
    selected_clock = _ServerClock() if clock is None else clock
    selected_audit = build_tax_assessment_audit_coordinator(using=using) if audit is None else audit
    unit = DjangoTaxLiabilityAtomicUnitOfWork(
        using=using, verifier=scope_verifier, audit=selected_audit, clock=selected_clock
    )
    return CorporateActionTaxLiabilityUseCase(
        scope_verifier=scope_verifier, unit_of_work=unit, clock=selected_clock, using=using
    )


__all__ = [
    "DjangoRetainedTaxAssessmentAuditVerifier",
    "DjangoTaxLiabilityAtomicUnitOfWork",
    "build_audited_tax_liability_use_case",
]
