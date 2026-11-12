"""Join current physical ownership with Account policy evidence on one alias."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db import connections
from django.utils import timezone

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    LockedSimulatedCorporateActionWriteScope,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantBinding,
)
from apps.account.simulated_corporate_action_policy_scope_composition import (
    locked_simulated_action_owner_policy,
)
from apps.simulated_trading.application.corporate_action_tax_liability_authority import (
    TaxLiabilityReplayRequest,
    TaxLiabilityReplayTimestampVerifierPort,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStageRequest
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)


@dataclass(frozen=True, slots=True)
class CorporateActionSourceTimestampReplayProof:
    """Server-verified exact replay facts that can waive only the initial source timestamp check."""

    request_payload_sha256: str
    grant_content_hash: str
    audit_event_id: str
    audit_event_content_hash: str
    outbox_event_content_hash: str

    def __post_init__(self) -> None:
        """Require a request, current grant, exact Audit event and matching Outbox event."""

        for name, value in (
            ("request_payload_sha256", self.request_payload_sha256),
            ("grant_content_hash", self.grant_content_hash),
            ("audit_event_content_hash", self.audit_event_content_hash),
            ("outbox_event_content_hash", self.outbox_event_content_hash),
        ):
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        if (
            type(self.audit_event_id) is not str
            or not self.audit_event_id
            or self.audit_event_id != self.audit_event_id.strip()
            or len(self.audit_event_id) > 256
            or self.outbox_event_content_hash != self.audit_event_content_hash
        ):
            raise ValueError("replay proof does not bind one exact Audit/Outbox event")


class CorporateActionSourceTimestampReplayVerifier(ABC):
    """Verify an existing ledger, owner-grant Audit event, and exact Outbox winner."""

    @abstractmethod
    def verify_exact_replay(
        self,
        *,
        request: CorporateActionStageRequest,
        grant: SimulatedCorporateActionWriteGrant,
    ) -> CorporateActionSourceTimestampReplayProof | None:
        """Return exact server evidence only when the request is already fully audited."""


@dataclass(slots=True)
class _ActiveSourceScope:
    """Private physical/source lock facts for one active owner-grant UOW."""

    locker: object
    request: CorporateActionStageRequest
    row_updated_at: datetime
    timestamp_matches: bool
    replay_proof: CorporateActionSourceTimestampReplayProof | None = None


_ACTIVE_SOURCE_SCOPE: ContextVar[_ActiveSourceScope | None] = ContextVar(
    "simulated_corporate_action_locked_source_scope", default=None
)


@dataclass(slots=True)
class _ActiveTaxSourceScope:
    """Separate financial replay context; it cannot waive a cash-stage request."""

    locker: object
    request: TaxLiabilityReplayRequest
    source: SimulatedAccountRowSourceV2
    row_updated_at: datetime
    cash: Decimal
    cash_known: bool
    proven: bool = False


_ACTIVE_TAX_SOURCE: ContextVar[_ActiveTaxSourceScope | None] = ContextVar(
    "simulated_tax_liability_locked_source", default=None
)


@contextmanager
def _tax_source_context(
    *,
    locker: object,
    request: TaxLiabilityReplayRequest | None,
    source: SimulatedAccountRowSourceV2,
    row: SimulatedAccountModel,
) -> Iterator[None]:
    """Keep narrow source mismatch proof inside the exact physical owner lock."""
    if request is None:
        yield
        return
    if _ACTIVE_TAX_SOURCE.get() is not None:
        raise SimulatedCorporateActionWriteGrantUnavailable(
            "tax financial source contexts cannot nest"
        )
    active = _ActiveTaxSourceScope(
        locker, request, source, row.updated_at, row.current_cash, row.cash_known
    )
    token = _ACTIVE_TAX_SOURCE.set(active)
    try:
        yield
        if source.row_updated_at != active.row_updated_at and not active.proven:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "old financial source lacks exact original journal/Audit/Outbox proof"
            )
        if source.row_updated_at != active.row_updated_at and (
            row.updated_at != active.row_updated_at
            or row.current_cash != active.cash
            or row.cash_known is not active.cash_known
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "a historical financial retry must not change the physical ledger"
            )
    finally:
        _ACTIVE_TAX_SOURCE.reset(token)


@dataclass(frozen=True, slots=True)
class DjangoSimulatedCorporateActionWriteScopeLocker:
    """Verify immutable canonical source and real owner while physical locks are held."""

    database_alias: str
    runtime_environment: str

    @contextmanager
    def lock_owned_scope(
        self,
        *,
        physical_account_id: int,
        owner_user_id: int,
        expected_binding: SimulatedCorporateActionWriteGrantBinding,
        request: CorporateActionStageRequest | None = None,
        expected_grant_schema: str = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
        tax_replay_request: TaxLiabilityReplayRequest | None = None,
    ) -> Iterator[LockedSimulatedCorporateActionWriteScope]:
        """Never infer authority from financial balances, physical IDs or evidence-only flags."""
        binding = expected_binding
        binding.__post_init__()
        if tax_replay_request is not None:
            if type(tax_replay_request) is not TaxLiabilityReplayRequest or request is not None:
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "tax financial replay requires its own exact request"
                )
            tax_replay_request.__post_init__()
            if (
                tax_replay_request.assessment.account_id != physical_account_id
                or tax_replay_request.assessment.owner_user_id != owner_user_id
                or tax_replay_request.canonical_account_id != binding.account_id
            ):
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "tax financial replay differs from its exact account source"
                )
        if request is not None and type(request) is not CorporateActionStageRequest:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated action source scope requires one exact posting request"
            )
        if request is not None:
            request.__post_init__()
        if request is not None and _ACTIVE_SOURCE_SCOPE.get() is not None:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated action source scope cannot be nested"
            )
        connection = connections[self.database_alias]
        if (
            connection.vendor != "postgresql"
            or not connection.in_atomic_block
            or binding.owner_user_id != owner_user_id
            or type(physical_account_id) is not int
            or physical_account_id <= 0
            or (
                request is not None
                and (
                    request.account_id != physical_account_id
                    or request.owner_user_id != owner_user_id
                )
            )
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated action scope requires an owner-bound PostgreSQL transaction"
            )
        with connection.cursor() as cursor:
            cursor.execute("SHOW transaction_isolation")
            if cursor.fetchone() != ("read committed",):
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "simulated action scope requires READ COMMITTED"
                )
        row = (
            SimulatedAccountModel._base_manager.using(self.database_alias)
            .select_for_update()
            .filter(
                pk=physical_account_id,
                user_id=owner_user_id,
                account_type="simulated",
                is_active=True,
            )
            .first()
        )
        if row is None:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated action physical account is not currently owned and active"
            )
        repository = DjangoSimulatedAccountRowSourceV2Repository(using=self.database_alias)
        repository.lock_current_sources_for_read()

        def current_source() -> SimulatedAccountRowSourceV2:
            """Reopen the exact source head, with no old-version fallback."""
            now = timezone.now()
            record = repository.get_current_head(
                source_id=binding.account_source_id,
                account_namespace="account",
                account_id=binding.account_id,
                underlying_unified_account_namespace="simulated-account-row",
                underlying_unified_account_id=physical_account_id,
                as_of=now,
            )
            if record is None:
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "simulated action canonical physical source is missing"
                )
            source = record.source
            source.__post_init__()
            if (
                source.source_version != binding.account_source_version
                or source.content_hash != binding.account_source_content_hash
                or source.row_user_id != owner_user_id
                or source.raw_account_type != "simulated"
                or source.row_created_at != row.created_at
                or not source.is_current_at(now)
            ):
                raise SimulatedCorporateActionWriteGrantUnavailable(
                    "simulated action canonical physical source is not exact and current"
                )
            return source

        source = current_source()
        timestamp_matches = source.row_updated_at == row.updated_at
        if request is None and tax_replay_request is None and not timestamp_matches:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated action source predates the physical account state"
            )
        with locked_simulated_action_owner_policy(
            binding=binding,
            canonical_namespace=source.account_namespace,
            using=self.database_alias,
            runtime_environment=self.runtime_environment,
            expected_grant_schema=expected_grant_schema,
        ) as policy:
            if request is None:
                with _tax_source_context(
                    locker=self, request=tax_replay_request, source=source, row=row
                ):
                    yield LockedSimulatedCorporateActionWriteScope(
                        physical_account_id=physical_account_id,
                        binding=binding,
                        valid_until=policy.grant_valid_until(
                            as_of=timezone.now(),
                            source_valid_until=source.valid_until,
                        ),
                        grant_schema=policy.grant_schema,
                        capabilities=policy.capabilities,
                        terms_version=policy.terms_version,
                        terms_sha256=policy.terms_sha256,
                    )
                    row.refresh_from_db(using=self.database_alias)
                    if (
                        row.user_id != owner_user_id
                        or row.account_type != "simulated"
                        or row.is_active is not True
                        or current_source() != source
                    ):
                        raise SimulatedCorporateActionWriteGrantUnavailable(
                            "simulated action physical ownership or source changed before commit"
                        )
            else:
                active_scope = _ActiveSourceScope(
                    locker=self,
                    request=request,
                    row_updated_at=row.updated_at,
                    timestamp_matches=timestamp_matches,
                )
                token: Token[_ActiveSourceScope | None] = _ACTIVE_SOURCE_SCOPE.set(active_scope)
                try:
                    yield LockedSimulatedCorporateActionWriteScope(
                        physical_account_id=physical_account_id,
                        binding=binding,
                        valid_until=policy.grant_valid_until(
                            as_of=timezone.now(),
                            source_valid_until=source.valid_until,
                        ),
                        grant_schema=policy.grant_schema,
                        capabilities=policy.capabilities,
                        terms_version=policy.terms_version,
                        terms_sha256=policy.terms_sha256,
                    )
                    if not active_scope.timestamp_matches and active_scope.replay_proof is None:
                        raise SimulatedCorporateActionWriteGrantUnavailable(
                            "stale physical account timestamp lacks exact audited replay proof"
                        )
                    row.refresh_from_db(using=self.database_alias)
                    if (
                        row.user_id != owner_user_id
                        or row.account_type != "simulated"
                        or row.is_active is not True
                        or current_source() != source
                        or (
                            not active_scope.timestamp_matches
                            and row.updated_at != active_scope.row_updated_at
                        )
                    ):
                        raise SimulatedCorporateActionWriteGrantUnavailable(
                            "simulated action physical ownership or source changed before commit"
                        )
                finally:
                    _ACTIVE_SOURCE_SCOPE.reset(token)

    def get_locked_tax_source(
        self, *, request: TaxLiabilityReplayRequest
    ) -> SimulatedAccountRowSourceV2:
        """Return exact source provenance only inside this locker's financial context."""
        active = _ACTIVE_TAX_SOURCE.get()
        if active is None or active.locker is not self or active.request != request:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "financial source is outside its exact locked context"
            )
        return active.source

    def assert_tax_source_timestamp_current_or_proven(
        self,
        *,
        request: TaxLiabilityReplayRequest,
        verifier: TaxLiabilityReplayTimestampVerifierPort,
    ) -> None:
        """Waive only the same already-recorded financial operation's source timestamp."""
        source = self.get_locked_tax_source(request=request)
        active = _ACTIVE_TAX_SOURCE.get()
        if active is None:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "financial source context is unavailable"
            )
        if source.row_updated_at == active.row_updated_at:
            return
        original = verifier.verify_exact_replay_timestamp(
            request=request,
            source=source,
            physical_updated_at=active.row_updated_at,
            physical_cash=active.cash,
            cash_known=active.cash_known,
            using=self.database_alias,
        )
        if original != source.row_updated_at:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "old financial source lacks exact original operation evidence"
            )
        active.proven = True

    def assert_source_timestamp_current_or_proven(
        self,
        *,
        request: CorporateActionStageRequest,
        grant: SimulatedCorporateActionWriteGrant,
        verifier: CorporateActionSourceTimestampReplayVerifier | None,
    ) -> None:
        """Allow a stale source timestamp only after closed server replay verification."""

        active_scope = _ACTIVE_SOURCE_SCOPE.get()
        if (
            active_scope is None
            or active_scope.locker is not self
            or active_scope.request != request
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "simulated action timestamp check is outside its exact locked source scope"
            )
        if active_scope.timestamp_matches:
            return
        if type(grant) is not SimulatedCorporateActionWriteGrant:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "source timestamp replay requires the exact current Account grant"
            )
        try:
            grant.__post_init__()
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "source timestamp replay grant is invalid"
            ) from error
        if not isinstance(verifier, CorporateActionSourceTimestampReplayVerifier):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "stale physical account timestamp requires a server replay verifier"
            )
        proof = verifier.verify_exact_replay(request=request, grant=grant)
        if type(proof) is not CorporateActionSourceTimestampReplayProof:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "stale physical account timestamp lacks exact ledger/Audit/Outbox evidence"
            )
        try:
            proof.__post_init__()
        except (TypeError, ValueError) as error:
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "corporate-action replay evidence is invalid"
            ) from error
        if (
            proof.request_payload_sha256 != request.payload_sha256
            or proof.grant_content_hash != grant.content_hash
        ):
            raise SimulatedCorporateActionWriteGrantUnavailable(
                "corporate-action replay evidence differs from its request or current grant"
            )
        active_scope.replay_proof = proof
