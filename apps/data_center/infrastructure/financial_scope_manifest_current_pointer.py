"""PostgreSQL-backed current pointer for reviewed full-scope financial reports."""

from __future__ import annotations

from typing import Literal, cast

from django.db import DatabaseError, transaction

from apps.data_center.application.financial_scope_capacity_input import (
    FinancialScopeCapacityInputError,
    FinancialScopeManifestCurrentPointer,
    FinancialScopeManifestCurrentPointerSource,
)
from apps.data_center.infrastructure.models import FinancialScopeManifestCurrentPointerModel


class DjangoFinancialScopeManifestCurrentPointerSource(FinancialScopeManifestCurrentPointerSource):
    """Read and compare-and-swap the one current reviewed manifest per environment."""

    def get_current(
        self, *, environment: Literal["isolated", "production"]
    ) -> FinancialScopeManifestCurrentPointer | None:
        """Load the persisted report pointer without triggering provider or fact writes."""

        if environment not in {"isolated", "production"}:
            raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_ENVIRONMENT_MISMATCH")
        try:
            row = FinancialScopeManifestCurrentPointerModel._default_manager.filter(
                environment=environment
            ).first()
        except DatabaseError:
            raise FinancialScopeCapacityInputError(
                "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID"
            ) from None
        if row is None:
            return None
        return FinancialScopeManifestCurrentPointer(
            environment=cast(Literal["isolated", "production"], row.environment),
            report_payload=row.report_payload,
            report_sha256=row.report_sha256,
            owner_approval_id=row.owner_approval_id,
            owner_event_id=row.owner_event_id,
            reviewer_approval_id=row.reviewer_approval_id,
            reviewer_event_id=row.reviewer_event_id,
            revision=row.revision,
            updated_by=row.updated_by,
        )

    def set_current(
        self,
        pointer: FinancialScopeManifestCurrentPointer,
        *,
        expected_revision: int,
    ) -> FinancialScopeManifestCurrentPointer:
        """Atomically replace the current pointer when its expected revision is current."""

        if (
            pointer.environment not in {"isolated", "production"}
            or type(expected_revision) is not int
            or expected_revision < 0
        ):
            raise FinancialScopeCapacityInputError("FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID")
        try:
            with transaction.atomic():
                current = (
                    FinancialScopeManifestCurrentPointerModel._default_manager.select_for_update()
                    .filter(environment=pointer.environment)
                    .first()
                )
                actual_revision = current.revision if current is not None else 0
                if actual_revision != expected_revision:
                    raise FinancialScopeCapacityInputError(
                        "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID"
                    )
                if current is None:
                    current = FinancialScopeManifestCurrentPointerModel(
                        environment=pointer.environment,
                        report_payload=pointer.report_payload,
                        report_sha256=pointer.report_sha256,
                        owner_approval_id=pointer.owner_approval_id,
                        owner_event_id=pointer.owner_event_id,
                        reviewer_approval_id=pointer.reviewer_approval_id,
                        reviewer_event_id=pointer.reviewer_event_id,
                        revision=1,
                        updated_by=pointer.updated_by,
                    )
                else:
                    current.report_payload = pointer.report_payload
                    current.report_sha256 = pointer.report_sha256
                    current.owner_approval_id = pointer.owner_approval_id
                    current.owner_event_id = pointer.owner_event_id
                    current.reviewer_approval_id = pointer.reviewer_approval_id
                    current.reviewer_event_id = pointer.reviewer_event_id
                    current.revision = actual_revision + 1
                    current.updated_by = pointer.updated_by
                current.save()
        except FinancialScopeCapacityInputError:
            raise
        except DatabaseError:
            raise FinancialScopeCapacityInputError(
                "FINANCIAL_CAPACITY_SCOPE_POINTER_INVALID"
            ) from None
        return FinancialScopeManifestCurrentPointer(
            environment=cast(Literal["isolated", "production"], current.environment),
            report_payload=current.report_payload,
            report_sha256=current.report_sha256,
            owner_approval_id=current.owner_approval_id,
            owner_event_id=current.owner_event_id,
            reviewer_approval_id=current.reviewer_approval_id,
            reviewer_event_id=current.reviewer_event_id,
            revision=current.revision,
            updated_by=current.updated_by,
        )


__all__ = ["DjangoFinancialScopeManifestCurrentPointerSource"]
