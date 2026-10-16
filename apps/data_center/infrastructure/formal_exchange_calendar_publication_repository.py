"""Persist formal exchange-calendar publications over existing DC tables."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Final
from uuid import UUID, uuid4

from django.db import DatabaseError, IntegrityError, connections, router
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.utils import CursorWrapper
from django.db.models import Model
from django.utils import timezone
from django.utils.connection import ConnectionDoesNotExist

from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from apps.data_center.application.calendar_publication_authority import (
    CALENDAR_PUBLISH_PERMISSION_CODENAME,
    LockedCalendarPublisherPrincipal,
)
from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreparationContext,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CalendarFormalPublicationCommit,
    CalendarFormalPublicationRequest,
    CalendarPublicationAuditPair,
    CurrentPublishedExchangeCalendar,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.domain.calendar_publication_window import (
    CalendarPublicationLifecycle,
)
from apps.data_center.domain.contracts import DatasetKey
from apps.data_center.domain.control_plane import (
    CalendarNullableMemberCodecVersion,
    CalendarPublicationMemberReference,
    PublicationMember,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    ExchangeCalendarSnapshot,
    ExchangeCalendarSnapshotReference,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarFormalPublicationRecord,
    CalendarFormalPublicationSeal,
    CalendarPublicationPointerExpectation,
    CalendarPublicationTransition,
    calendar_formal_seals_have_same_evidence,
    calendar_snapshot_natural_key,
    create_calendar_formal_publication_seal,
    decide_calendar_publication_transition,
    exchange_calendar_publication_key,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.exchange_calendar_repository import (
    DjangoExchangeCalendarSnapshotRepository,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from apps.data_center.infrastructure.publication_fact_evidence import (
    canonical_fact_content_hash,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
)
from core.exceptions import DataFetchError
from shared.infrastructure.postgres_advisory_lock import (
    ScopedAdvisoryLockKey,
    derive_scoped_advisory_lock_id,
)

_DEFAULT_ALIAS: Final[str] = "default"
_LOCK_TIMEOUT_MS: Final[int] = 5_000
_LOCK_TIMEOUT_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<amount>[0-9]+(?:\.[0-9]+)?)(?P<unit>ms|s|min|h)?$"
)
_LOCK_TIMEOUT_SECONDS: Final[dict[str, Decimal]] = {
    "ms": Decimal("0.001"),
    "s": Decimal("1"),
    "min": Decimal("60"),
    "h": Decimal("3600"),
}
_PUBLICATION_MODELS: Final[tuple[type[Model], ...]] = (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    RawPayloadModel,
    ExchangeCalendarSnapshotFactModel,
    CanonicalPublicationModel,
    PublicationMemberModel,
    CoverageSnapshotModel,
    CanonicalPublicationPointerModel,
)
_CATALOG_MODELS: Final[tuple[type[Model], ...]] = (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
_SQLITE_FENCE_MODEL: Final[type[Model]] = DatasetContractModel


class DjangoFormalExchangeCalendarPublicationRepository:
    """Write and read exact calendar publications using existing DC storage."""

    def __init__(
        self,
        *,
        audit_port: CalendarFormalPublicationAuditPort,
        using: str = _DEFAULT_ALIAS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Bind one explicit database alias, Audit port, and UTC clock source."""

        if type(using) is not str or not using or using.strip() != using:
            raise DataFetchError(
                "Formal calendar repository requires an explicit database alias",
                code="CALENDAR_FORMAL_DATABASE_ALIAS_INVALID",
            )
        self._using = using
        self._audit_port = audit_port
        self._clock = clock or timezone.now

    def publish(
        self,
        request: CalendarFormalPublicationRequest,
        *,
        principal: LockedCalendarPublisherPrincipal,
    ) -> CalendarFormalPublicationCommit:
        """Publish or verify an exact current replay inside the caller's UoW."""

        if type(request) is not CalendarFormalPublicationRequest:
            raise DataFetchError(
                "Formal calendar request is not typed",
                code="CALENDAR_PUBLICATION_REQUEST_INVALID",
            )
        try:
            request.validate()
        except CalendarFormalPublicationApplicationError as error:
            raise DataFetchError(str(error), code=error.code) from error
        connection = self._connection()
        self._require_single_caller_transaction(connection)
        self._require_router_alias()
        self._require_postgresql_read_committed(connection)
        self._validate_principal(principal, expected_database_alias=self._using)
        self._assert_principal_live(principal)
        if self._audit_port.database_alias != self._using:
            raise DataFetchError(
                "Formal calendar Audit port uses another database alias",
                code="CALENDAR_PUBLICATION_AUDIT_ALIAS_MISMATCH",
            )

        self._acquire_catalog_fence(connection)
        dataset_key = request.proposed_seal.dataset.value
        publication_key = request.proposed_seal.publication_key
        self._acquire_scope_fence(connection, dataset_key, publication_key)
        now = self._clock_now()
        active_contract, active_policy = self._load_active_catalog(
            dataset_key=dataset_key,
            contract_version=request.proposed_seal.dataset.contract_version,
            schema_version=request.proposed_seal.dataset.schema_version,
            knowledge_cutoff=now,
        )

        old_snapshot_ids: tuple[str, ...] = ()
        expected = request.expected_pointer
        if not expected.is_absent:
            old_snapshot_ids = self._snapshot_ids_for_publication(expected.publication_id)
        source_ids = tuple(
            sorted(
                {
                    request.proposed_seal.snapshot_reference.snapshot_id,
                    *old_snapshot_ids,
                }
            )
        )
        snapshots, facts = self._lock_and_rebuild_snapshots(source_ids)
        proposal_snapshot = snapshots.get(request.proposed_seal.snapshot_reference.snapshot_id)
        if proposal_snapshot is None:
            raise DataFetchError(
                "Proposed calendar source snapshot is unavailable",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        proposal_fact = facts.get(proposal_snapshot.snapshot_id)
        if proposal_fact is None:
            raise DataFetchError(
                "Proposed calendar source fact was not locked",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        publication_id = str(uuid4())
        member_id = str(uuid4())
        proposed_recorded_seal = self._build_seal(
            snapshot=proposal_snapshot,
            fact_model=proposal_fact,
            contract=active_contract,
            policy_model=active_policy,
            member_id=member_id,
            publication_id=publication_id,
        )
        if not calendar_formal_seals_have_same_evidence(
            request.proposed_seal, proposed_recorded_seal
        ):
            raise DataFetchError(
                "Formal calendar proposal differs from the exact persisted source or catalog",
                code="CALENDAR_FORMAL_PROPOSAL_MISMATCH",
            )

        pointer_model = self._lock_pointer(dataset_key, publication_key)
        actual_pointer = self._pointer_expectation(pointer_model, dataset_key, publication_key)
        if actual_pointer != request.expected_pointer:
            raise DataFetchError(
                "Formal calendar pointer differs from the supplied compare-and-swap token",
                code="CALENDAR_POINTER_CAS_MISMATCH",
            )
        current_record: CalendarFormalPublicationRecord | None = None
        if pointer_model is not None:
            if actual_pointer.is_absent:
                raise DataFetchError(
                    "Formal calendar pointer contains an empty placeholder",
                    code="CALENDAR_FORMAL_POINTER_PLACEHOLDER",
                )
            current_record = self._load_record(
                publication_id=actual_pointer.publication_id,
                activation_id=actual_pointer.activation_id,
                snapshots=snapshots,
                facts=facts,
                knowledge_cutoff=now,
                lock_rows=True,
            )
        elif self._has_scope_publications(dataset_key, publication_key):
            raise DataFetchError(
                "Formal calendar publication history exists without a current pointer",
                code="CALENDAR_FORMAL_POINTER_MISSING",
            )

        try:
            transition = decide_calendar_publication_transition(
                proposed_seal=proposed_recorded_seal,
                expected_pointer=request.expected_pointer,
                actual_pointer=actual_pointer,
                current_record=current_record,
                activation_id=request.activation_id,
            )
        except CalendarFormalPublicationError as error:
            raise DataFetchError(str(error), code=error.code) from error

        if transition is CalendarPublicationTransition.EXACT_CURRENT_REPLAY:
            if current_record is None:
                raise DataFetchError(
                    "Exact current replay has no persisted publication record",
                    code="CALENDAR_PUBLICATION_REPLAY_INVALID",
                )
            pair = self._audit_port.verify_current_replay(
                current_record,
                principal=principal,
            )
            self._verify_audit_pair(
                pair,
                record=current_record,
                expected_actor=principal.user_id,
                as_of=None,
            )
            post_audit_checked_at = self._clock_now()
            self._validate_post_audit(
                record=current_record,
                principal=principal,
                started_at=now,
                checked_at=post_audit_checked_at,
            )
            return CalendarFormalPublicationCommit(
                record=current_record,
                pointer=actual_pointer,
                transition=transition,
                audit_pair=pair,
                post_audit_checked_at=post_audit_checked_at,
            )

        self._reject_existing_publication_hash(
            dataset_key=dataset_key,
            publication_key=publication_key,
            publication_hash=proposed_recorded_seal.publication_hash,
        )

        published_at = self._clock_now()
        self._validate_new_publication_time(
            published_at=published_at,
            principal=principal,
            seal=proposed_recorded_seal,
            previous_pointer=actual_pointer,
            transition=transition,
        )
        if transition is CalendarPublicationTransition.FORWARD_PUBLISH:
            if current_record is None:
                raise DataFetchError(
                    "Forward calendar publication has no exact current record",
                    code="CALENDAR_POINTER_TARGET_INVALID",
                )
            previous_pair = self._audit_port.verify_published_integrity(
                current_record, as_of=published_at
            )
            self._verify_audit_pair(
                previous_pair,
                record=current_record,
                expected_actor=None,
                as_of=published_at,
            )
            self._assert_principal_live(principal)
        record = self._persist_new_publication(
            seal=proposed_recorded_seal,
            publication_id=publication_id,
            member_id=member_id,
            activation_id=request.activation_id,
            published_at=published_at,
            previous_record=current_record,
            pointer_model=pointer_model,
            previous_pointer=actual_pointer,
            transition=transition,
        )
        pair = self._audit_port.record_published(
            record,
            principal=principal,
        )
        self._verify_audit_pair(
            pair,
            record=record,
            expected_actor=principal.user_id,
            as_of=None,
        )
        post_audit_checked_at = self._clock_now()
        self._validate_post_audit(
            record=record,
            principal=principal,
            started_at=published_at,
            checked_at=post_audit_checked_at,
        )
        persisted_pointer = self._read_pointer(dataset_key, publication_key)
        if persisted_pointer is None or (
            pointer_model is not None and persisted_pointer.pointer_id != pointer_model.pointer_id
        ):
            raise DataFetchError(
                "Formal calendar pointer disappeared before commit verification",
                code="CALENDAR_FORMAL_POINTER_MISMATCH",
            )
        pointer = self._pointer_expectation(persisted_pointer, dataset_key, publication_key)
        return CalendarFormalPublicationCommit(
            record=record,
            pointer=pointer,
            transition=transition,
            audit_pair=pair,
            post_audit_checked_at=post_audit_checked_at,
        )

    def read_current(
        self,
        query: ReadCurrentExchangeCalendarPublicationQuery,
    ) -> CurrentPublishedExchangeCalendar | None:
        """Read exact current publication/Audit rows in one caller-owned outer transaction.

        The caller must open exactly one atomic block on ``database_alias``. The
        repository joins that transaction so the pointer, source, catalog, and
        Audit integrity checks share one database view.
        """

        if type(query) is not ReadCurrentExchangeCalendarPublicationQuery:
            raise DataFetchError(
                "Formal calendar current-read query is not typed",
                code="CALENDAR_CURRENT_READ_QUERY_INVALID",
            )
        try:
            query.__post_init__()
        except CalendarFormalPublicationApplicationError as error:
            raise DataFetchError(str(error), code=error.code) from error
        connection = self._connection()
        self._require_single_caller_transaction(
            connection,
            error_code="CALENDAR_FORMAL_READ_TRANSACTION_OWNER_INVALID",
            operation="read",
        )
        self._require_router_alias()
        self._require_postgresql_read_committed(connection)
        self._acquire_catalog_fence(connection)
        publication_key = exchange_calendar_publication_key(query.exchange)
        self._acquire_scope_fence(connection, query.dataset_key, publication_key)
        pointer_hint = self._read_pointer(query.dataset_key, publication_key)
        if pointer_hint is None:
            if self._has_scope_publications(query.dataset_key, publication_key):
                raise DataFetchError(
                    "Formal calendar publication history exists without a current pointer",
                    code="CALENDAR_FORMAL_POINTER_MISSING",
                )
            return None
        hint = self._pointer_expectation(pointer_hint, query.dataset_key, publication_key)
        if hint.is_absent:
            raise DataFetchError(
                "Formal calendar pointer contains an empty placeholder",
                code="CALENDAR_FORMAL_POINTER_PLACEHOLDER",
            )
        snapshot_ids = self._snapshot_ids_for_publication(hint.publication_id)
        snapshots, facts = self._lock_and_rebuild_snapshots(snapshot_ids)
        pointer_model = self._lock_pointer(query.dataset_key, publication_key)
        if pointer_model is None:
            raise DataFetchError(
                "Formal calendar pointer disappeared during read",
                code="CALENDAR_FORMAL_POINTER_MISMATCH",
            )
        pointer = self._pointer_expectation(pointer_model, query.dataset_key, publication_key)
        if pointer != hint:
            raise DataFetchError(
                "Formal calendar pointer changed during the exact read",
                code="CALENDAR_FORMAL_POINTER_MISMATCH",
            )
        record = self._load_record(
            publication_id=pointer.publication_id,
            activation_id=pointer.activation_id,
            snapshots=snapshots,
            facts=facts,
            knowledge_cutoff=query.as_of,
            lock_rows=True,
        )
        try:
            result = CurrentPublishedExchangeCalendar(
                record=record,
                pointer=pointer,
                as_of=query.as_of,
            )
        except CalendarFormalPublicationApplicationError as error:
            raise DataFetchError(str(error), code=error.code) from error
        pair = self._audit_port.verify_published_integrity(
            record,
            as_of=query.as_of,
        )
        self._verify_audit_pair(pair, record=record, expected_actor=None, as_of=query.as_of)
        return result

    def load_exact(
        self,
        reference: ExchangeCalendarSnapshotReference,
        *,
        known_at: datetime,
    ) -> CalendarPublicationPreparationContext | None:
        """Load exact source/catalog/current evidence inside one caller-owned UoW.

        This read returns only data known by ``known_at``. It never selects a
        latest source, writes publication rows, or treats an expired current
        publication as a fresh source. The caller must own one outer atomic
        block on ``database_alias``; SQLite uses the existing zero-row catalog
        update only to reserve that transaction's write slot.
        """

        if type(reference) is not ExchangeCalendarSnapshotReference:
            raise DataFetchError(
                "Calendar preparation requires an exact snapshot reference",
                code="CALENDAR_FORMAL_PREPARATION_REFERENCE_INVALID",
            )
        try:
            reference.__post_init__()
        except ExchangeCalendarError as error:
            raise DataFetchError(str(error), code=error.code) from error
        if not _is_utc_datetime(known_at):
            raise DataFetchError(
                "Calendar preparation cutoff must be an aware UTC datetime",
                code="CALENDAR_FORMAL_PREPARATION_CUTOFF_INVALID",
            )

        connection = self._connection()
        self._require_single_caller_transaction(
            connection,
            error_code="CALENDAR_FORMAL_PREPARATION_TRANSACTION_OWNER_INVALID",
            operation="preparation",
        )
        self._require_router_alias()
        self._require_postgresql_read_committed(connection)

        try:
            self._acquire_catalog_fence(connection)
            raw_id = _parse_uuid(reference.raw_payload_id, "raw_payload_id")
            dataset_hint = (
                RawPayloadModel._default_manager.using(self._using)
                .filter(payload_id=raw_id)
                .values_list("dataset_key", flat=True)
                .first()
            )
            if dataset_hint is None:
                return None
            if (
                type(dataset_hint) is not str
                or not dataset_hint
                or dataset_hint.strip() != dataset_hint
            ):
                raise DataFetchError(
                    "Calendar source RawPayload has an invalid dataset scope",
                    code="CALENDAR_FORMAL_SOURCE_SCOPE_INVALID",
                )

            publication_key = exchange_calendar_publication_key(reference.exchange)
            self._acquire_scope_fence(connection, dataset_hint, publication_key)

            active_contracts = list(
                DatasetContractModel._default_manager.using(self._using)
                .filter(dataset_key=dataset_hint, active=True)
                .order_by("contract_version", "schema_version", "pk")
            )
            if len(active_contracts) != 1:
                code = (
                    "CALENDAR_FORMAL_CONTRACT_MISSING"
                    if not active_contracts
                    else "CALENDAR_FORMAL_CONTRACT_AMBIGUOUS"
                )
                raise DataFetchError(
                    "Calendar preparation requires exactly one active dataset contract",
                    code=code,
                )
            selected_contract = active_contracts[0]
            contract, policy_model = self._load_active_catalog(
                dataset_key=dataset_hint,
                contract_version=selected_contract.contract_version,
                schema_version=selected_contract.schema_version,
                knowledge_cutoff=known_at,
            )

            candidate_snapshot_id = str(_parse_uuid(reference.snapshot_id, "snapshot_id"))
            candidate_exists = (
                ExchangeCalendarSnapshotFactModel._default_manager.using(self._using)
                .filter(snapshot_id=UUID(candidate_snapshot_id))
                .exists()
            )
            if not candidate_exists:
                return None

            pointer_hint_model = self._read_pointer(dataset_hint, publication_key)
            pointer_hint = self._pointer_expectation(
                pointer_hint_model,
                dataset_hint,
                publication_key,
            )
            old_snapshot_ids: tuple[str, ...] = ()
            if pointer_hint_model is not None:
                if pointer_hint.is_absent:
                    raise DataFetchError(
                        "Formal calendar pointer contains an empty placeholder",
                        code="CALENDAR_FORMAL_POINTER_PLACEHOLDER",
                    )
                old_snapshot_ids = self._snapshot_ids_for_publication(pointer_hint.publication_id)

            source_ids = tuple(sorted({candidate_snapshot_id, *old_snapshot_ids}))
            snapshots, facts = self._lock_and_rebuild_snapshots(source_ids)
            snapshot = snapshots.get(candidate_snapshot_id)
            fact_model = facts.get(candidate_snapshot_id)
            if snapshot is None or fact_model is None:
                raise DataFetchError(
                    "Exact calendar preparation source disappeared during locking",
                    code="CALENDAR_FORMAL_SOURCE_MISSING",
                )
            if snapshot.reference() != reference:
                return None
            if snapshot.first_seen_at > known_at or snapshot.recorded_at > known_at:
                return None
            if snapshot.raw_reference.dataset_key != dataset_hint:
                raise DataFetchError(
                    "Calendar RawPayload dataset scope changed after the lookup hint",
                    code="CALENDAR_FORMAL_SOURCE_SCOPE_DRIFT",
                )

            pointer_model = self._lock_pointer(dataset_hint, publication_key)
            pointer = self._pointer_expectation(pointer_model, dataset_hint, publication_key)
            if pointer != pointer_hint:
                raise DataFetchError(
                    "Formal calendar pointer changed during preparation",
                    code="CALENDAR_FORMAL_POINTER_MISMATCH",
                )
            if pointer_model is None:
                if self._has_scope_publications(dataset_hint, publication_key):
                    raise DataFetchError(
                        "Formal calendar publication history exists without a current pointer",
                        code="CALENDAR_FORMAL_POINTER_MISSING",
                    )
            else:
                if pointer.is_absent:
                    raise DataFetchError(
                        "Formal calendar pointer contains an empty placeholder",
                        code="CALENDAR_FORMAL_POINTER_PLACEHOLDER",
                    )
                current_record = self._load_record(
                    publication_id=pointer.publication_id,
                    activation_id=pointer.activation_id,
                    snapshots=snapshots,
                    facts=facts,
                    knowledge_cutoff=known_at,
                    lock_rows=True,
                )
                try:
                    transition = decide_calendar_publication_transition(
                        proposed_seal=current_record.seal,
                        expected_pointer=pointer,
                        actual_pointer=pointer,
                        current_record=current_record,
                        activation_id=current_record.activation_id,
                    )
                except CalendarFormalPublicationError as error:
                    raise DataFetchError(str(error), code=error.code) from error
                if transition is not CalendarPublicationTransition.EXACT_CURRENT_REPLAY:
                    raise DataFetchError(
                        "Current calendar pointer did not resolve to its exact publication",
                        code="CALENDAR_FORMAL_POINTER_TARGET_INVALID",
                    )
                pair = self._audit_port.verify_published_integrity(
                    current_record,
                    as_of=known_at,
                )
                self._verify_audit_pair(
                    pair,
                    record=current_record,
                    expected_actor=None,
                    as_of=known_at,
                )

            try:
                seal = self._build_seal(
                    snapshot=snapshot,
                    fact_model=fact_model,
                    contract=contract,
                    policy_model=policy_model,
                    member_id=str(uuid4()),
                    publication_id=str(uuid4()),
                )
                context = CalendarPublicationPreparationContext(
                    snapshot=snapshot,
                    contract=contract.to_domain(),
                    contract_recorded_at=contract.created_at,
                    policy=policy_model.to_domain(),
                    policy_recorded_at=policy_model.created_at,
                    member_reference=seal.member_reference,
                    current_pointer=pointer,
                )
                context.validate()
            except CalendarFormalPublicationError as error:
                raise DataFetchError(str(error), code=error.code) from error
            except CalendarPublicationOperationsError as error:
                raise DataFetchError(str(error), code=error.code) from error
            return context
        except DataFetchError:
            raise
        except DatabaseError as error:
            raise DataFetchError(
                "Formal calendar preparation storage is unavailable",
                code="CALENDAR_FORMAL_STORAGE_UNAVAILABLE",
            ) from error

    @property
    def database_alias(self) -> str:
        """Return the explicit alias used by every source and publication row."""

        return self._using

    def _connection(self) -> BaseDatabaseWrapper:
        """Resolve the alias or convert a missing configured connection to a typed block."""

        try:
            return connections[self._using]
        except (KeyError, LookupError, ConnectionDoesNotExist) as error:
            raise DataFetchError(
                "Formal calendar database alias is unavailable",
                code="CALENDAR_FORMAL_DATABASE_UNAVAILABLE",
            ) from error

    def _require_router_alias(self) -> None:
        """Require all relevant ORM reads and writes to route to this same alias."""

        for model in _PUBLICATION_MODELS:
            if (
                router.db_for_read(model) != self._using
                or router.db_for_write(model) != self._using
            ):
                raise DataFetchError(
                    "Formal calendar ORM models do not share the configured database alias",
                    code="CALENDAR_FORMAL_ROUTER_ALIAS_MISMATCH",
                )
        if self._audit_port.database_alias != self._using:
            raise DataFetchError(
                "Formal calendar Audit port uses another database alias",
                code="CALENDAR_PUBLICATION_AUDIT_ALIAS_MISMATCH",
            )

    @staticmethod
    def _require_postgresql_read_committed(connection: BaseDatabaseWrapper) -> None:
        """Reject PostgreSQL isolation that can hide changes predating our fences."""

        if connection.vendor != "postgresql":
            return
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('transaction_isolation')")
                row = cursor.fetchone()
        except DatabaseError as error:
            raise DataFetchError(
                "Formal calendar transaction isolation is unavailable",
                code="CALENDAR_FORMAL_ISOLATION_UNAVAILABLE",
            ) from error
        if (
            not isinstance(row, tuple)
            or len(row) != 1
            or type(row[0]) is not str
            or row[0] != "read committed"
        ):
            raise DataFetchError(
                "Formal calendar reads and writes require PostgreSQL READ COMMITTED",
                code="CALENDAR_FORMAL_ISOLATION_UNSUPPORTED",
            )

    def _require_single_caller_transaction(
        self,
        connection: BaseDatabaseWrapper,
        *,
        error_code: str = "CALENDAR_FORMAL_TRANSACTION_OWNER_INVALID",
        operation: str = "publication",
    ) -> None:
        """Require one caller-owned outer atomic block on the selected alias."""

        if (
            connection.alias != self._using
            or not connection.in_atomic_block
            or connection.get_autocommit()
            or len(connection.atomic_blocks) != 1
        ):
            raise DataFetchError(
                f"Formal calendar {operation} requires one matching caller-owned outer transaction",
                code=error_code,
            )

    @staticmethod
    def _validate_principal(
        principal: LockedCalendarPublisherPrincipal,
        *,
        expected_database_alias: str,
    ) -> None:
        """Recheck the locked authenticated principal fields at this write boundary."""

        try:
            valid = (
                principal.actor_type == "django_user"
                and type(principal.user_id) is int
                and principal.user_id > 0
                and principal.actor_id == f"django-user:{principal.user_id}"
                and principal.permission_codename == CALENDAR_PUBLISH_PERMISSION_CODENAME
                and type(principal.permission_id) is int
                and principal.permission_id > 0
                and type(principal.database_alias) is str
                and principal.database_alias == expected_database_alias
                and isinstance(principal.verified_at, datetime)
                and principal.verified_at.tzinfo is not None
                and principal.verified_at.utcoffset() == timedelta(0)
            )
        except (AttributeError, TypeError) as error:
            raise DataFetchError(
                "Formal calendar publisher principal is incomplete",
                code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
            ) from error
        if not valid:
            raise DataFetchError(
                "Formal calendar publisher principal is not bound to a user and permission",
                code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
            )

    @staticmethod
    def _assert_principal_live(principal: LockedCalendarPublisherPrincipal) -> None:
        """Recheck the authority lease and preserve its typed expiry failure."""

        try:
            principal.assert_live()
        except AttributeError as error:
            raise DataFetchError(
                "Formal calendar publisher principal has no live lease",
                code="CALENDAR_PUBLICATION_AUTHORITY_INVALID",
            ) from error

    def _acquire_catalog_fence(self, connection: BaseDatabaseWrapper) -> None:
        """Fence catalog phantoms before reading config rows, without row-lock inversion."""

        if connection.vendor == "postgresql":
            # SET LOCAL remains in force for scope and row locks through the
            # caller-owned transaction, then PostgreSQL restores its prior value.
            tables = sorted(model._meta.db_table for model in _CATALOG_MODELS)
            try:
                with connection.cursor() as cursor:
                    previous_timeout = _read_pg_lock_timeout(cursor)
                    _set_pg_lock_timeout(cursor, _bounded_pg_lock_timeout_ms(previous_timeout))
                    for table_name in tables:
                        cursor.execute(
                            f"LOCK TABLE {connection.ops.quote_name(table_name)} IN SHARE MODE"
                        )
            except DatabaseError as error:
                raise DataFetchError(
                    "Formal calendar catalog fence is unavailable",
                    code="CALENDAR_FORMAL_STORAGE_UNAVAILABLE",
                ) from error
            return
        if connection.vendor == "sqlite":
            table_name = connection.ops.quote_name(_SQLITE_FENCE_MODEL._meta.db_table)
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"UPDATE {table_name} SET dataset_key=dataset_key WHERE 1=0")
            except DatabaseError as error:
                raise DataFetchError(
                    "Formal calendar SQLite catalog write fence is unavailable",
                    code="CALENDAR_FORMAL_STORAGE_UNAVAILABLE",
                ) from error
            return
        raise DataFetchError(
            "Formal calendar publication supports only PostgreSQL and SQLite",
            code="CALENDAR_FORMAL_DATABASE_UNSUPPORTED",
        )

    def _acquire_scope_fence(
        self,
        connection: BaseDatabaseWrapper,
        dataset_key: str,
        publication_key: str,
    ) -> None:
        """Serialize readers and writers for one exact dataset/exchange scope."""

        if connection.vendor != "postgresql":
            return
        lock_key = ScopedAdvisoryLockKey(
            domain="data-center.formal-exchange-calendar-publication",
            components=(dataset_key, publication_key),
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    [derive_scoped_advisory_lock_id(lock_key)],
                )
        except DatabaseError as error:
            raise DataFetchError(
                "Formal calendar scope lock is unavailable",
                code="CALENDAR_FORMAL_STORAGE_UNAVAILABLE",
            ) from error

    def _load_active_catalog(
        self,
        *,
        dataset_key: str,
        contract_version: str,
        schema_version: str,
        knowledge_cutoff: datetime,
    ) -> tuple[DatasetContractModel, DatasetPublicationPolicyModel]:
        """Read exactly one active, version-matching contract and publication policy."""

        contracts = list(
            DatasetContractModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key, active=True)
            .order_by("contract_version", "schema_version", "pk")
        )
        if len(contracts) != 1:
            code = (
                "CALENDAR_FORMAL_CONTRACT_MISSING"
                if not contracts
                else "CALENDAR_FORMAL_CONTRACT_AMBIGUOUS"
            )
            raise DataFetchError("Formal calendar requires exactly one active contract", code=code)
        contract = contracts[0]
        if (contract.contract_version, contract.schema_version) != (
            contract_version,
            schema_version,
        ):
            raise DataFetchError(
                "Formal calendar proposal does not use the active contract version",
                code="CALENDAR_FORMAL_CONTRACT_VERSION_MISMATCH",
            )

        policies = list(
            DatasetPublicationPolicyModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key, active=True)
            .order_by("contract_version", "schema_version", "policy_version", "pk")
        )
        if len(policies) != 1:
            code = (
                "CALENDAR_FORMAL_POLICY_MISSING"
                if not policies
                else "CALENDAR_FORMAL_POLICY_AMBIGUOUS"
            )
            raise DataFetchError("Formal calendar requires exactly one active policy", code=code)
        policy = policies[0]
        if (policy.contract_version, policy.schema_version) != (
            contract_version,
            schema_version,
        ):
            raise DataFetchError(
                "Formal calendar policy does not match the active contract version",
                code="CALENDAR_FORMAL_POLICY_VERSION_MISMATCH",
            )
        self._validate_catalog_clock(contract, knowledge_cutoff)
        self._validate_catalog_clock(policy, knowledge_cutoff)
        try:
            contract.to_domain()
            policy.to_domain()
        except (TypeError, ValueError) as error:
            raise DataFetchError(
                "Formal calendar active catalog row is invalid",
                code="CALENDAR_FORMAL_CATALOG_INVALID",
            ) from error
        return contract, policy

    def _load_exact_catalog_for_publication(
        self,
        publication: CanonicalPublicationModel,
        *,
        knowledge_cutoff: datetime,
    ) -> tuple[DatasetContractModel, DatasetPublicationPolicyModel]:
        """Load the exact versioned catalog rows named by a current publication."""

        policies = list(
            DatasetPublicationPolicyModel._default_manager.using(self._using)
            .filter(
                dataset_key=publication.dataset_key,
                policy_version=publication.policy_version,
            )
            .order_by("contract_version", "schema_version", "pk")
        )
        if len(policies) != 1:
            code = (
                "CALENDAR_FORMAL_POLICY_MISSING"
                if not policies
                else "CALENDAR_FORMAL_POLICY_AMBIGUOUS"
            )
            raise DataFetchError("Current publication's exact policy is unavailable", code=code)
        policy = policies[0]
        contracts = list(
            DatasetContractModel._default_manager.using(self._using)
            .filter(
                dataset_key=publication.dataset_key,
                contract_version=policy.contract_version,
                schema_version=policy.schema_version,
            )
            .order_by("pk")
        )
        if len(contracts) != 1:
            code = (
                "CALENDAR_FORMAL_CONTRACT_MISSING"
                if not contracts
                else "CALENDAR_FORMAL_CONTRACT_AMBIGUOUS"
            )
            raise DataFetchError("Current publication's exact contract is unavailable", code=code)
        contract = contracts[0]
        self._validate_catalog_clock(contract, knowledge_cutoff)
        self._validate_catalog_clock(policy, knowledge_cutoff)
        try:
            contract.to_domain()
            policy.to_domain()
        except (TypeError, ValueError) as error:
            raise DataFetchError(
                "Current publication's exact catalog row is invalid",
                code="CALENDAR_FORMAL_CATALOG_INVALID",
            ) from error
        return contract, policy

    @staticmethod
    def _validate_catalog_clock(
        row: DatasetContractModel | DatasetPublicationPolicyModel,
        cutoff: datetime,
    ) -> None:
        """Reject configuration not yet known at the operation's knowledge cutoff."""

        created_at = row.created_at
        updated_at = row.updated_at
        if not _is_utc_datetime(created_at) or not _is_utc_datetime(updated_at):
            raise DataFetchError(
                "Formal calendar catalog row has invalid knowledge timestamps",
                code="CALENDAR_FORMAL_CATALOG_CLOCK_INVALID",
            )
        if created_at > cutoff or updated_at > cutoff:
            raise DataFetchError(
                "Formal calendar catalog row was not known at the requested cutoff",
                code="CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN",
            )

    def _snapshot_ids_for_publication(self, publication_id: str | None) -> tuple[str, ...]:
        """Read the exact source row IDs needed before taking source row locks."""

        parsed_id = _parse_uuid(publication_id, "publication_id")
        rows = list(
            PublicationMemberModel._default_manager.using(self._using)
            .filter(publication_id=parsed_id)
            .order_by("member_id")
            .values_list("source_record_id", "fact_pk")
        )
        if len(rows) != 1:
            raise DataFetchError(
                "Formal calendar current publication must have exactly one member",
                code="CALENDAR_FORMAL_MEMBER_CARDINALITY_INVALID",
            )
        source_id, fact_pk = rows[0]
        if type(source_id) is not str or source_id != fact_pk:
            raise DataFetchError(
                "Formal calendar member source identity is inconsistent",
                code="CALENDAR_FORMAL_MEMBER_BINDING_INVALID",
            )
        return (str(_parse_uuid(source_id, "snapshot_id")),)

    def _lock_and_rebuild_snapshots(
        self,
        snapshot_ids: Sequence[str],
    ) -> tuple[
        dict[str, ExchangeCalendarSnapshot],
        dict[str, ExchangeCalendarSnapshotFactModel],
    ]:
        """Lock exact RawPayload rows before immutable fact rows and reparse bytes."""

        unique_ids = tuple(sorted(set(snapshot_ids)))
        if not unique_ids:
            raise DataFetchError(
                "Formal calendar publication has no source snapshot identity",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        parsed_ids = tuple(_parse_uuid(value, "snapshot_id") for value in unique_ids)
        raw_links = list(
            ExchangeCalendarSnapshotFactModel._default_manager.using(self._using)
            .filter(snapshot_id__in=parsed_ids)
            .order_by("raw_payload_id", "snapshot_id")
            .values_list("snapshot_id", "raw_payload_id")
        )
        if len(raw_links) != len(parsed_ids):
            raise DataFetchError(
                "One or more exact calendar source snapshots are missing",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        raw_ids = tuple(sorted({raw_id for _snapshot_id, raw_id in raw_links}))
        locked_raw_rows = list(
            RawPayloadModel._default_manager.using(self._using)
            .select_for_update()
            .filter(payload_id__in=raw_ids)
            .order_by("payload_id")
        )
        if len(locked_raw_rows) != len(raw_ids):
            raise DataFetchError(
                "One or more retained calendar RawPayload rows are missing",
                code="CALENDAR_FORMAL_RAW_PAYLOAD_MISSING",
            )
        facts = tuple(
            ExchangeCalendarSnapshotFactModel._default_manager.using(self._using)
            .select_for_update()
            .select_related("raw_payload")
            .filter(snapshot_id__in=parsed_ids)
            .order_by("snapshot_id")
        )
        if len(facts) != len(parsed_ids):
            raise DataFetchError(
                "One or more exact calendar source snapshots changed during locking",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        raw_by_id = {str(row.payload_id): row for row in locked_raw_rows}
        snapshots: dict[str, ExchangeCalendarSnapshot] = {}
        facts_by_id: dict[str, ExchangeCalendarSnapshotFactModel] = {}
        for fact in facts:
            raw_row = raw_by_id.get(str(fact.raw_payload_id))
            if raw_row is None or fact.raw_payload_id != fact.raw_payload.payload_id:
                raise DataFetchError(
                    "Calendar fact points to another locked RawPayload",
                    code="CALENDAR_FORMAL_RAW_PAYLOAD_BINDING_INVALID",
                )
            snapshot = DjangoExchangeCalendarSnapshotRepository._to_domain(fact)
            if snapshot.snapshot_id in snapshots:
                raise DataFetchError(
                    "Duplicate calendar source identity was returned",
                    code="CALENDAR_FORMAL_SOURCE_AMBIGUOUS",
                )
            snapshots[snapshot.snapshot_id] = snapshot
            facts_by_id[snapshot.snapshot_id] = fact
        return snapshots, facts_by_id

    def _build_seal(
        self,
        *,
        snapshot: ExchangeCalendarSnapshot,
        fact_model: ExchangeCalendarSnapshotFactModel,
        contract: DatasetContractModel,
        policy_model: DatasetPublicationPolicyModel,
        member_id: str,
        publication_id: str,
    ) -> CalendarFormalPublicationSeal:
        """Reconstruct the complete seal from locked source and catalog storage."""

        try:
            policy = policy_model.to_domain()
            ttl = contract.calendar_response_max_age_seconds
            if type(ttl) is not int:
                raise DataFetchError(
                    "Formal calendar contract has no explicit response-age TTL",
                    code="CALENDAR_FORMAL_TTL_MISSING",
                )
            member = PublicationMember(
                member_id=member_id,
                publication_id=publication_id,
                dataset_key=policy.dataset.value,
                natural_key=calendar_snapshot_natural_key(
                    snapshot.exchange,
                    snapshot.coverage_start,
                    snapshot.coverage_end,
                ),
                source=snapshot.provider_name,
                source_record_id=snapshot.snapshot_id,
                fact_table=ExchangeCalendarSnapshotFactModel._meta.db_table,
                fact_pk=snapshot.snapshot_id,
                observed_at=None,
                raw_payload_hash=snapshot.raw_reference.payload_hash,
                quality_status="accepted",
                revision_number=1,
                available_at=None,
                fetched_at=snapshot.first_seen_at,
                source_published_at=None,
                raw_payload_scope="record_response_body",
                fact_content_hash=canonical_fact_content_hash(fact_model),
            )
            member_reference = CalendarPublicationMemberReference(
                member=member,
                snapshot_content_hash=snapshot.content_hash,
                snapshot_record_digest=snapshot.record_digest,
                codec_version=CalendarNullableMemberCodecVersion.V1,
            )
            return create_calendar_formal_publication_seal(
                dataset=DatasetKey(
                    value=policy.dataset.value,
                    contract_version=contract.contract_version,
                    schema_version=contract.schema_version,
                ),
                exchange=snapshot.exchange,
                calendar_response_max_age_seconds=ttl,
                contract_recorded_at=contract.created_at,
                policy=policy,
                policy_recorded_at=policy_model.created_at,
                snapshot=snapshot,
                member_reference=member_reference,
            )
        except CalendarFormalPublicationError as error:
            raise DataFetchError(str(error), code=error.code) from error
        except (TypeError, ValueError) as error:
            raise DataFetchError(
                "Formal calendar source or catalog could not be sealed",
                code="CALENDAR_FORMAL_SEAL_INVALID",
            ) from error

    def _lock_pointer(
        self, dataset_key: str, publication_key: str
    ) -> CanonicalPublicationPointerModel | None:
        """Lock the exact current pointer after catalog and source rows."""

        try:
            return (
                CanonicalPublicationPointerModel._default_manager.using(self._using)
                .select_for_update()
                .filter(dataset_key=dataset_key, publication_key=publication_key)
                .first()
            )
        except DatabaseError as error:
            raise DataFetchError(
                "Formal calendar pointer lock is unavailable",
                code="CALENDAR_FORMAL_STORAGE_UNAVAILABLE",
            ) from error

    def _read_pointer(
        self, dataset_key: str, publication_key: str
    ) -> CanonicalPublicationPointerModel | None:
        """Read a pointer hint before source locks; it is rechecked after locking."""

        return (
            CanonicalPublicationPointerModel._default_manager.using(self._using)
            .filter(dataset_key=dataset_key, publication_key=publication_key)
            .first()
        )

    @staticmethod
    def _pointer_expectation(
        model: CanonicalPublicationPointerModel | None,
        dataset_key: str,
        publication_key: str,
    ) -> CalendarPublicationPointerExpectation:
        """Decode the persisted pointer without accepting incomplete placeholders."""

        if model is None:
            return CalendarPublicationPointerExpectation(
                dataset_key=dataset_key,
                publication_key=publication_key,
                pointer_id=None,
                publication_id=None,
                publication_hash=None,
                activation_id=None,
                updated_at=None,
            )
        if (
            model.dataset_key != dataset_key
            or model.publication_key != publication_key
            or model.publication_id is None
            or not model.publication_hash
            or not model.activation_id
            or not _is_utc_datetime(model.updated_at)
        ):
            raise DataFetchError(
                "Formal calendar pointer is a partial or malformed placeholder",
                code="CALENDAR_FORMAL_POINTER_PLACEHOLDER",
            )
        try:
            return CalendarPublicationPointerExpectation(
                dataset_key=model.dataset_key,
                publication_key=model.publication_key,
                pointer_id=str(model.pointer_id),
                publication_id=str(model.publication_id),
                publication_hash=model.publication_hash,
                activation_id=model.activation_id,
                updated_at=model.updated_at,
            )
        except CalendarFormalPublicationError as error:
            raise DataFetchError(str(error), code=error.code) from error

    def _load_record(
        self,
        *,
        publication_id: str | None,
        activation_id: str | None,
        snapshots: dict[str, ExchangeCalendarSnapshot],
        facts: dict[str, ExchangeCalendarSnapshotFactModel],
        knowledge_cutoff: datetime,
        lock_rows: bool,
    ) -> CalendarFormalPublicationRecord:
        """Rebuild a publication, member, coverage and source from exact DB rows."""

        parsed_id = _parse_uuid(publication_id, "publication_id")
        publications = CanonicalPublicationModel._default_manager.using(self._using)
        members = PublicationMemberModel._default_manager.using(self._using)
        coverages = CoverageSnapshotModel._default_manager.using(self._using)
        if lock_rows:
            publications = publications.select_for_update()
            members = members.select_for_update()
            coverages = coverages.select_for_update()
        try:
            publication = publications.get(publication_id=parsed_id)
        except CanonicalPublicationModel.DoesNotExist as error:
            raise DataFetchError(
                "Formal calendar pointer target is missing",
                code="CALENDAR_FORMAL_POINTER_TARGET_INVALID",
            ) from error
        member_rows = list(members.filter(publication_id=parsed_id).order_by("member_id"))
        coverage_rows = list(coverages.filter(publication_id=parsed_id).order_by("coverage_id"))
        if len(member_rows) != 1 or len(coverage_rows) != 1:
            raise DataFetchError(
                "Formal calendar publication requires exactly one member and coverage row",
                code="CALENDAR_FORMAL_PUBLICATION_CARDINALITY_INVALID",
            )
        member_model = member_rows[0]
        coverage_model = coverage_rows[0]
        source_id = _parse_uuid(member_model.source_record_id, "snapshot_id")
        snapshot = snapshots.get(str(source_id))
        if snapshot is None:
            raise DataFetchError(
                "Formal calendar publication's source was not locked",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        fact_model = facts.get(snapshot.snapshot_id)
        if fact_model is None:
            raise DataFetchError(
                "Formal calendar publication source fact was not locked",
                code="CALENDAR_FORMAL_SOURCE_MISSING",
            )
        contract, policy_model = self._load_exact_catalog_for_publication(
            publication,
            knowledge_cutoff=knowledge_cutoff,
        )
        generated_member_id = str(member_model.member_id)
        expected_seal = self._build_seal(
            snapshot=snapshot,
            fact_model=fact_model,
            contract=contract,
            policy_model=policy_model,
            member_id=generated_member_id,
            publication_id=str(publication.publication_id),
        )
        expected_member = expected_seal.member_reference.member
        try:
            actual_member = member_model.to_domain()
        except (TypeError, ValueError) as error:
            raise DataFetchError(
                "Formal calendar publication member is corrupt",
                code="CALENDAR_FORMAL_MEMBER_INVALID",
            ) from error
        if actual_member != expected_member:
            raise DataFetchError(
                "Formal calendar member differs from its exact source fact",
                code="CALENDAR_FORMAL_MEMBER_BINDING_INVALID",
            )
        self._validate_publication_row(
            publication,
            seal=expected_seal,
            member=actual_member,
            coverage=coverage_model,
            activation_id=activation_id,
            knowledge_cutoff=knowledge_cutoff,
        )
        published_at = publication.published_at
        if published_at is None or not _is_utc_datetime(published_at):
            raise DataFetchError(
                "Formal calendar publication has no exact activation time",
                code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
            )
        try:
            lifecycle = CalendarPublicationLifecycle(publication.state)
            return CalendarFormalPublicationRecord(
                seal=expected_seal,
                publication_id=str(publication.publication_id),
                activation_id=activation_id or "",
                lifecycle=lifecycle,
                published_at=published_at,
                superseded_at=publication.superseded_at,
            )
        except (CalendarFormalPublicationError, TypeError, ValueError) as error:
            code = (
                error.code
                if isinstance(error, CalendarFormalPublicationError)
                else "CALENDAR_FORMAL_RECORD_INVALID"
            )
            raise DataFetchError(
                "Formal calendar publication lifecycle is invalid",
                code=code,
            ) from error

    @staticmethod
    def _validate_publication_row(
        publication: CanonicalPublicationModel,
        *,
        seal: CalendarFormalPublicationSeal,
        member: PublicationMember,
        coverage: CoverageSnapshotModel,
        activation_id: str | None,
        knowledge_cutoff: datetime,
    ) -> None:
        """Reject any publication, member or coverage mutation outside the seal."""

        del activation_id  # The exact activation identity is stored by the current pointer.
        if (
            publication.dataset_key != seal.dataset.value
            or publication.publication_key != seal.publication_key
            or publication.policy_version != seal.policy.policy_version
            or publication.selected_source != seal.snapshot_provider_name
            or publication.publication_hash != seal.publication_hash
            or publication.member_manifest_hash != seal.member_manifest_hash
            or publication.member_count != 1
            or publication.conflict_count != 0
            or publication.coverage_requested_count != 1
            or publication.coverage_eligible_count != 1
            or publication.coverage_selected_count != 1
            or publication.coverage_missing_count != 0
            or publication.coverage_conflict_count != 0
            or publication.reinstated_at is not None
            or publication.blocked_reason
            or type(publication.scope_blocks) is not list
            or publication.scope_blocks != []
            or publication.must_not_use_for_decision
            or publication.created_by != "calendar-formal-publication"
            or publication.run_id is not None
            or publication.as_of != publication.published_at
            or publication.members_sealed_at != publication.published_at
            or publication.published_at is None
            or not _is_utc_datetime(publication.published_at)
            or not _is_utc_datetime(publication.created_at)
            or not _is_utc_datetime(publication.updated_at)
            or publication.created_at > knowledge_cutoff
            or publication.updated_at > knowledge_cutoff
        ):
            raise DataFetchError(
                "Formal calendar publication row is corrupt or not known at cutoff",
                code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
            )
        if (
            member.dataset_key != seal.dataset.value
            or member.publication_id != str(publication.publication_id)
            or member.source != seal.snapshot_provider_name
            or member.source_record_id != seal.snapshot.snapshot_id
            or coverage.publication_id != publication.publication_id
            or coverage.coverage_id != publication.publication_id
            or coverage.requested_count != 1
            or coverage.eligible_count != 1
            or coverage.selected_count != 1
            or coverage.missing_count != 0
            or coverage.conflict_count != 0
            or coverage.generated_at != publication.published_at
        ):
            raise DataFetchError(
                "Formal calendar member or coverage row is not bound to the publication",
                code="CALENDAR_FORMAL_COVERAGE_BINDING_INVALID",
            )

    def _has_scope_publications(self, dataset_key: str, publication_key: str) -> bool:
        """Reject a missing pointer when any publication already occupies its scope."""

        return (
            CanonicalPublicationModel._default_manager.using(self._using)
            .filter(
                dataset_key=dataset_key,
                publication_key=publication_key,
            )
            .exists()
        )

    def _reject_existing_publication_hash(
        self,
        *,
        dataset_key: str,
        publication_key: str,
        publication_hash: str,
    ) -> None:
        """Prevent reactivation of a superseded or otherwise historical target."""

        exists = (
            CanonicalPublicationModel._default_manager.using(self._using)
            .filter(
                dataset_key=dataset_key,
                publication_key=publication_key,
                publication_hash=publication_hash,
            )
            .exists()
        )
        if exists:
            raise DataFetchError(
                "Formal calendar content already has a historical publication row",
                code="CALENDAR_FORMAL_REACTIVATION_UNSUPPORTED",
            )

    def _persist_new_publication(
        self,
        *,
        seal: CalendarFormalPublicationSeal,
        publication_id: str,
        member_id: str,
        activation_id: str,
        published_at: datetime,
        previous_record: CalendarFormalPublicationRecord | None,
        pointer_model: CanonicalPublicationPointerModel | None,
        previous_pointer: CalendarPublicationPointerExpectation,
        transition: CalendarPublicationTransition,
    ) -> CalendarFormalPublicationRecord:
        """Insert one immutable publication/member/coverage and move its pointer."""

        if transition is CalendarPublicationTransition.FIRST_PUBLISH:
            if pointer_model is not None or previous_record is not None:
                raise DataFetchError(
                    "First calendar publication cannot reuse an existing pointer",
                    code="CALENDAR_POINTER_CAS_MISMATCH",
                )
        elif transition is CalendarPublicationTransition.FORWARD_PUBLISH:
            previous_time = previous_pointer.updated_at
            if (
                pointer_model is None
                or previous_record is None
                or previous_time is None
                or published_at <= previous_time
            ):
                raise DataFetchError(
                    "Calendar forward publication time must strictly advance the pointer",
                    code="CALENDAR_PUBLICATION_FORWARD_TIME_INVALID",
                )
        else:
            raise DataFetchError(
                "Unsupported formal calendar persistence transition",
                code="CALENDAR_PUBLICATION_TRANSITION_INVALID",
            )
        record = CalendarFormalPublicationRecord(
            seal=seal,
            publication_id=publication_id,
            activation_id=activation_id,
            lifecycle=CalendarPublicationLifecycle.PUBLISHED,
            published_at=published_at,
        )
        member = seal.member_reference.member
        try:
            publication_model = CanonicalPublicationModel._default_manager.using(
                self._using
            ).create(
                publication_id=UUID(publication_id),
                dataset_key=seal.dataset.value,
                publication_key=seal.publication_key,
                policy_version=seal.policy.policy_version,
                state="published",
                selected_source=member.source,
                publication_hash=seal.publication_hash,
                member_manifest_hash=seal.member_manifest_hash,
                member_count=1,
                conflict_count=0,
                coverage_requested_count=1,
                coverage_eligible_count=1,
                coverage_selected_count=1,
                coverage_missing_count=0,
                coverage_conflict_count=0,
                as_of=published_at,
                published_at=published_at,
                superseded_at=None,
                reinstated_at=None,
                must_not_use_for_decision=False,
                blocked_reason="",
                created_by="calendar-formal-publication",
                run_id=None,
                scope_blocks=[],
                members_sealed_at=published_at,
            )
            PublicationMemberModel._default_manager.using(self._using).create(
                member_id=UUID(member_id),
                publication_id=UUID(publication_id),
                dataset_key=member.dataset_key,
                natural_key=member.natural_key,
                source=member.source,
                source_record_id=member.source_record_id,
                fact_table=member.fact_table,
                fact_pk=member.fact_pk,
                observed_at=member.observed_at,
                raw_payload_hash=member.raw_payload_hash,
                quality_status=member.quality_status,
                revision_number=member.revision_number,
                available_at=member.available_at,
                fetched_at=member.fetched_at,
                source_published_at=member.source_published_at,
                raw_payload_scope=member.raw_payload_scope,
                fact_content_hash=member.fact_content_hash,
            )
            CoverageSnapshotModel._default_manager.using(self._using).create(
                coverage_id=UUID(publication_id),
                publication_id=UUID(publication_id),
                requested_count=1,
                eligible_count=1,
                selected_count=1,
                missing_count=0,
                conflict_count=0,
                generated_at=published_at,
            )
            if transition is CalendarPublicationTransition.FORWARD_PUBLISH:
                assert previous_record is not None
                superseded = (
                    CanonicalPublicationModel._default_manager.using(self._using)
                    .filter(
                        publication_id=UUID(previous_record.publication_id),
                        state="published",
                        superseded_at__isnull=True,
                        reinstated_at__isnull=True,
                        published_at=previous_record.published_at,
                    )
                    .update(
                        state="superseded",
                        superseded_at=published_at,
                        updated_at=published_at,
                    )
                )
                if superseded != 1:
                    raise DataFetchError(
                        "Previous calendar publication changed before supersession",
                        code="CALENDAR_PUBLICATION_FORWARD_CONFLICT",
                    )
            self._move_pointer(
                pointer_model=pointer_model,
                previous_pointer=previous_pointer,
                dataset_key=seal.dataset.value,
                publication_key=seal.publication_key,
                publication_id=UUID(publication_id),
                publication_hash=seal.publication_hash,
                activation_id=activation_id,
                published_at=published_at,
                transition=transition,
            )
        except IntegrityError as error:
            raise DataFetchError(
                "Formal calendar publication uniqueness or row constraint failed",
                code="CALENDAR_FORMAL_WRITE_CONFLICT",
            ) from error
        except DatabaseError as error:
            raise DataFetchError(
                "Formal calendar publication storage is unavailable",
                code="CALENDAR_FORMAL_STORAGE_UNAVAILABLE",
            ) from error
        if publication_model.publication_id != UUID(record.publication_id):
            raise DataFetchError(
                "Formal calendar publication row identity differs from its record",
                code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
            )
        return record

    def _move_pointer(
        self,
        *,
        pointer_model: CanonicalPublicationPointerModel | None,
        previous_pointer: CalendarPublicationPointerExpectation,
        dataset_key: str,
        publication_key: str,
        publication_id: UUID,
        publication_hash: str,
        activation_id: str,
        published_at: datetime,
        transition: CalendarPublicationTransition,
    ) -> None:
        """Insert first pointer or compare-and-swap its exact prior epoch."""

        pointers = CanonicalPublicationPointerModel._default_manager.using(self._using)
        if transition is CalendarPublicationTransition.FIRST_PUBLISH:
            if pointer_model is not None or not previous_pointer.is_absent:
                raise DataFetchError(
                    "First calendar publication pointer must still be absent",
                    code="CALENDAR_POINTER_CAS_MISMATCH",
                )
            pointer = pointers.create(
                dataset_key=dataset_key,
                publication_key=publication_key,
                publication_id=publication_id,
                publication_hash=publication_hash,
                activation_id=activation_id,
            )
            updated = pointers.filter(pointer_id=pointer.pointer_id).update(updated_at=published_at)
        else:
            if pointer_model is None or previous_pointer.updated_at is None:
                raise DataFetchError(
                    "Forward calendar pointer is missing its prior epoch",
                    code="CALENDAR_POINTER_CAS_MISMATCH",
                )
            updated = pointers.filter(
                pointer_id=UUID(previous_pointer.pointer_id or ""),
                dataset_key=previous_pointer.dataset_key,
                publication_key=previous_pointer.publication_key,
                publication_id=UUID(previous_pointer.publication_id or ""),
                publication_hash=previous_pointer.publication_hash,
                activation_id=previous_pointer.activation_id,
                updated_at=previous_pointer.updated_at,
            ).update(
                publication_id=publication_id,
                publication_hash=publication_hash,
                activation_id=activation_id,
                updated_at=published_at,
            )
        if updated != 1:
            raise DataFetchError(
                "Formal calendar pointer compare-and-swap failed",
                code="CALENDAR_POINTER_CAS_MISMATCH",
            )

    def _verify_audit_pair(
        self,
        pair: CalendarPublicationAuditPair,
        *,
        record: CalendarFormalPublicationRecord,
        expected_actor: int | None,
        as_of: datetime | None,
    ) -> None:
        """Require every returned event/outbox field to bind this persisted record."""

        if type(pair) is not CalendarPublicationAuditPair:
            raise DataFetchError(
                "Formal calendar Audit port returned no typed event/outbox pair",
                code="CALENDAR_FORMAL_AUDIT_INTEGRITY_INVALID",
            )
        try:
            pair.__post_init__()
        except CalendarFormalPublicationApplicationError as error:
            raise DataFetchError(str(error), code=error.code) from error
        if (
            pair.database_alias != self._using
            or pair.dataset_key != record.seal.dataset.value
            or pair.exchange != record.seal.exchange
            or pair.publication_id != record.publication_id
            or pair.publication_hash != record.seal.publication_hash
            or pair.recorded_at != record.published_at
            or (expected_actor is not None and pair.actor_user_id != expected_actor)
            or (as_of is not None and pair.recorded_at > as_of)
        ):
            raise DataFetchError(
                "Formal calendar Audit receipt does not bind its publication or cutoff",
                code="CALENDAR_FORMAL_AUDIT_INTEGRITY_INVALID",
            )

    def _validate_new_publication_time(
        self,
        *,
        published_at: datetime,
        principal: LockedCalendarPublisherPrincipal,
        seal: CalendarFormalPublicationSeal,
        previous_pointer: CalendarPublicationPointerExpectation,
        transition: CalendarPublicationTransition,
    ) -> None:
        """Enforce source/config/authority chronology and strict forward movement."""

        if published_at < principal.verified_at:
            raise DataFetchError(
                "Calendar publication time precedes locked publisher verification",
                code="CALENDAR_PUBLICATION_AUTHORITY_TIME_INVALID",
            )
        if published_at < max(
            seal.snapshot_recorded_at,
            seal.contract_recorded_at,
            seal.policy_recorded_at,
        ):
            raise DataFetchError(
                "Calendar publication time precedes its source or catalog knowledge",
                code="CALENDAR_FORMAL_KNOWLEDGE_TIME_INVALID",
            )
        previous_time = previous_pointer.updated_at
        if transition is CalendarPublicationTransition.FORWARD_PUBLISH and (
            previous_time is None or published_at <= previous_time
        ):
            raise DataFetchError(
                "Calendar forward publication time must strictly advance the pointer",
                code="CALENDAR_PUBLICATION_FORWARD_TIME_INVALID",
            )

    def _validate_post_audit(
        self,
        *,
        record: CalendarFormalPublicationRecord,
        principal: LockedCalendarPublisherPrincipal,
        started_at: datetime,
        checked_at: datetime,
    ) -> None:
        """Revalidate lease, monotonic clock, and response TTL after Audit I/O."""

        self._assert_principal_live(principal)
        self._validate_principal(principal, expected_database_alias=self._using)
        if checked_at < started_at or checked_at < principal.verified_at:
            raise DataFetchError(
                "Calendar repository clock moved backward after Audit I/O",
                code="CALENDAR_FORMAL_CLOCK_MOVED_BACKWARD",
            )
        try:
            if not record.is_effective_at(checked_at):
                raise DataFetchError(
                    "Calendar source response TTL expired before transaction completion",
                    code="CALENDAR_FORMAL_TTL_EXPIRED",
                )
        except CalendarFormalPublicationError as error:
            raise DataFetchError(str(error), code=error.code) from error

    def _clock_now(self) -> datetime:
        """Read the injected clock and require exact timezone-aware UTC semantics."""

        value = self._clock()
        if not _is_utc_datetime(value):
            raise DataFetchError(
                "Formal calendar repository clock must return an aware UTC datetime",
                code="CALENDAR_FORMAL_CLOCK_INVALID",
            )
        return value.astimezone(UTC)


def _read_pg_lock_timeout(cursor: CursorWrapper) -> str:
    """Read one PostgreSQL lock timeout setting without exposing credentials."""

    cursor.execute("SELECT current_setting('lock_timeout')")
    row = cursor.fetchone()
    if not isinstance(row, tuple) or len(row) != 1 or type(row[0]) is not str:
        raise DataFetchError(
            "PostgreSQL formal calendar lock timeout is unavailable",
            code="CALENDAR_FORMAL_LOCK_TIMEOUT_INVALID",
        )
    _parse_pg_lock_timeout_ms(row[0])
    return row[0]


def _set_pg_lock_timeout(cursor: CursorWrapper, value: str | int) -> None:
    """Set a transaction-local lock timeout using a parameter, not SQL text."""

    cursor.execute(
        "SELECT set_config('lock_timeout', %s, true)",
        [f"{value}ms" if type(value) is int else value],
    )


def _bounded_pg_lock_timeout_ms(previous: str) -> str | int:
    """Apply a five-second ceiling while preserving stricter caller precision."""

    previous_ms = _parse_pg_lock_timeout_ms(previous)
    if previous_ms <= 0 or previous_ms > Decimal(_LOCK_TIMEOUT_MS):
        return _LOCK_TIMEOUT_MS
    return previous.strip()


def _parse_pg_lock_timeout_ms(value: str) -> Decimal:
    """Convert PostgreSQL's timeout string to exact milliseconds."""

    match = _LOCK_TIMEOUT_RE.fullmatch(value.strip())
    if match is None:
        raise DataFetchError(
            "PostgreSQL formal calendar lock timeout has an unsupported format",
            code="CALENDAR_FORMAL_LOCK_TIMEOUT_INVALID",
        )
    amount_text = match.group("amount")
    if amount_text is None:
        raise DataFetchError(
            "PostgreSQL formal calendar lock timeout has no duration",
            code="CALENDAR_FORMAL_LOCK_TIMEOUT_INVALID",
        )
    unit = match.group("unit") or "ms"
    return Decimal(amount_text) * _LOCK_TIMEOUT_SECONDS[unit] * Decimal(1000)


def _is_utc_datetime(value: object) -> bool:
    """Return whether a value is an exact UTC-aware datetime."""

    if type(value) is not datetime or value.tzinfo is None:
        return False
    offset = value.utcoffset()
    return offset is not None and offset.total_seconds() == 0


def _parse_uuid(value: str | None, field_name: str) -> UUID:
    """Parse a canonical UUID or raise a stable storage-evidence block."""

    if type(value) is not str:
        raise DataFetchError(
            f"Formal calendar {field_name} is unavailable",
            code="CALENDAR_FORMAL_IDENTITY_INVALID",
        )
    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as error:
        raise DataFetchError(
            f"Formal calendar {field_name} is malformed",
            code="CALENDAR_FORMAL_IDENTITY_INVALID",
        ) from error
    if str(parsed) != value:
        raise DataFetchError(
            f"Formal calendar {field_name} is not canonical",
            code="CALENDAR_FORMAL_IDENTITY_INVALID",
        )
    return parsed


__all__ = ["DjangoFormalExchangeCalendarPublicationRepository"]
