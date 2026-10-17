"""Read exact current or preparation publication evidence."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from django.db import DatabaseError

from apps.data_center.application.calendar_publication_operations import (
    CalendarPublicationOperationsError,
    CalendarPublicationPreparationContext,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
    CurrentPublishedExchangeCalendar,
    ReadCurrentExchangeCalendarPublicationQuery,
)
from apps.data_center.domain.exchange_calendar import (
    ExchangeCalendarError,
    ExchangeCalendarSnapshotReference,
)
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationError,
    CalendarPublicationTransition,
    decide_calendar_publication_transition,
    exchange_calendar_publication_key,
)
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.fact_and_operational_models import (
    ExchangeCalendarSnapshotFactModel,
    RawPayloadModel,
)
from core.exceptions import DataFetchError

from .formal_exchange_calendar_publication_support import (
    _FormalExchangeCalendarPublicationSupport,
    _is_utc_datetime,
    _parse_uuid,
)


class _FormalExchangeCalendarPublicationReader(_FormalExchangeCalendarPublicationSupport):
    """Read exact source evidence and current pointer state without writing."""

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
