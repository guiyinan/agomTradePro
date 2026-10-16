"""Production composition for exact execution quote pointer rollback."""

from __future__ import annotations

from datetime import datetime

from apps.data_center.application.execution_quote_pointer_rollback import (
    ExecutionQuotePointerRollbackAuditWriter,
    ExecutionQuotePointerRollbackBundle,
    ExecutionQuotePointerRollbackError,
)
from apps.data_center.infrastructure.execution_quote_pointer_rollback_repository import (
    DjangoExecutionQuotePointerRollbackRepository,
)
from core.integration.data_center_audit import SystemAuditReaderContext
from core.integration.data_center_execution_quote_rollback_audit import (
    build_execution_quote_rollback_audit_bridge,
)
from core.integration.production_account_authority_capture import (
    ProductionAccountAuthorityCapture,
    capture_production_account_authority,
)

_DEFAULT_DATABASE_ALIAS = "default"
_PRODUCTION_ENVIRONMENT = "production"


def build_production_execution_quote_pointer_rollback_bundle(
    *,
    using: str = _DEFAULT_DATABASE_ALIAS,
) -> ExecutionQuotePointerRollbackBundle:
    """Compose Account-fenced pointer rollback with the canonical Audit outbox."""

    alias = _require_default_database_alias(using)

    def build_audit_writer() -> ExecutionQuotePointerRollbackAuditWriter:
        """Build the canonical Audit application and translate its exact receipt."""

        return build_execution_quote_rollback_audit_bridge(
            environment=_PRODUCTION_ENVIRONMENT,
            using=alias,
        )

    def capture_authority(
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> ProductionAccountAuthorityCapture:
        """Capture the current complete production Account graph on the same alias."""

        capture = capture_production_account_authority(
            using=alias,
            as_of=as_of,
            preflight_context=preflight_context,
        )
        if type(capture) is not ProductionAccountAuthorityCapture:
            raise ExecutionQuotePointerRollbackError(
                "production Account authority capture returned an invalid result"
            )
        if capture.database_alias != alias:
            raise ExecutionQuotePointerRollbackError(
                "production Account authority capture uses a different database alias"
            )
        return capture

    return ExecutionQuotePointerRollbackBundle(
        database_alias=alias,
        repository=DjangoExecutionQuotePointerRollbackRepository(using=alias),
        audit_writer_factory=build_audit_writer,
        authority_capture=capture_authority,
    )


def _require_default_database_alias(value: object) -> str:
    """Reject unsupported aliases before resolving cross-app capabilities."""

    if type(value) is not str or value != _DEFAULT_DATABASE_ALIAS:
        raise ExecutionQuotePointerRollbackError(
            "execution pointer rollback requires the default database"
        )
    return value


__all__ = ["build_production_execution_quote_pointer_rollback_bundle"]
