"""PostgreSQL reader for an exact historical formal-calendar publication."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from django.db import DatabaseError, router

from apps.data_center.application.calendar_catalog_bootstrap import CALENDAR_DATASET_KEY
from apps.data_center.application.calendar_formal_publication_audit_port import (
    CalendarFormalPublicationAuditPort,
)
from apps.data_center.application.calendar_historical_publication_audit_port import (
    CalendarHistoricalPublicationAuditPort,
)
from apps.data_center.application.formal_exchange_calendar_publication import (
    CalendarFormalPublicationApplicationError,
)
from apps.data_center.application.formal_exchange_calendar_publication_history import (
    HistoricalCalendarPublicationRecord,
    HistoricalPublishedExchangeCalendar,
    ReadExchangeCalendarPublicationAsOfQuery,
)
from apps.data_center.domain.calendar_publication_window import CalendarPublicationLifecycle
from apps.data_center.domain.formal_exchange_calendar_publication import (
    CalendarFormalPublicationSeal,
    exchange_calendar_publication_key,
)
from apps.data_center.infrastructure.catalog_models import (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)
from core.exceptions import DataFetchError

from .calendar_catalog_history_guard import calendar_catalog_history_guard_applied_at
from .formal_exchange_calendar_publication_support import (
    _FormalExchangeCalendarPublicationSupport,
    _is_utc_datetime,
    _parse_uuid,
)


class DjangoFormalExchangeCalendarPublicationHistoryReader(
    _FormalExchangeCalendarPublicationSupport
):
    """Rebuild exact historical source/publication evidence in a caller UOW."""

    def __init__(
        self,
        *,
        audit_port: CalendarFormalPublicationAuditPort,
        historical_audit_port: CalendarHistoricalPublicationAuditPort,
        using: str,
        clock: Callable[[], datetime],
    ) -> None:
        """Bind the existing evidence helpers to a single explicit database alias."""

        if type(using) is not str or not using or using.strip() != using:
            raise DataFetchError(
                "Formal calendar history reader requires an explicit database alias",
                code="CALENDAR_FORMAL_DATABASE_ALIAS_INVALID",
            )
        self._using = using
        self._audit_port = audit_port
        self._historical_audit_port = historical_audit_port
        self._clock = clock

    def read_publication_as_of(
        self,
        query: ReadExchangeCalendarPublicationAsOfQuery,
    ) -> HistoricalPublishedExchangeCalendar:
        """Return one exact publication whose sealed window contains ``as_of``.

        This method deliberately does not read the mutable current pointer. It
        verifies the publication, retained source, catalog seal, interval,
        scope timeline, and exact Audit event/outbox pair independently.
        """

        if type(query) is not ReadExchangeCalendarPublicationAsOfQuery:
            raise DataFetchError(
                "Formal calendar history read requires a typed exact query",
                code="CALENDAR_HISTORY_QUERY_INVALID",
            )
        query.__post_init__()
        connection = self._connection()
        self._require_single_caller_transaction(
            connection,
            error_code="CALENDAR_HISTORY_TRANSACTION_OWNER_INVALID",
            operation="historical read",
        )
        self._require_router_alias()
        self._require_rollback_router_alias()
        if self._historical_audit_port.database_alias != self._using:
            raise DataFetchError(
                "Historical calendar Audit port uses another database alias",
                code="CALENDAR_PUBLICATION_AUDIT_ALIAS_MISMATCH",
            )
        self._require_postgresql_read_committed(connection)
        self._acquire_catalog_fence(connection)
        publication_key = exchange_calendar_publication_key(query.exchange)
        self._acquire_scope_fence(connection, query.dataset_key, publication_key)
        server_now = self._clock_now()
        if query.as_of > server_now:
            raise DataFetchError(
                "Formal calendar history cutoff cannot be in the future",
                code="CALENDAR_HISTORY_FUTURE_CUTOFF",
            )
        guard_applied_at = calendar_catalog_history_guard_applied_at(
            connection,
            server_now=server_now,
        )

        try:
            publication_id = _parse_uuid(query.publication_id, "publication_id")
            publication = (
                CanonicalPublicationModel._default_manager.using(self._using)
                .select_for_update()
                .filter(publication_id=publication_id)
                .first()
            )
            if publication is None:
                raise DataFetchError(
                    "Exact formal calendar publication is missing",
                    code="CALENDAR_HISTORY_PUBLICATION_MISSING",
                )
            if (
                publication.dataset_key != query.dataset_key
                or publication.publication_key != publication_key
                or publication.publication_hash != query.publication_hash
            ):
                raise DataFetchError(
                    "Exact formal calendar publication belongs to another identity or scope",
                    code="CALENDAR_HISTORY_SCOPE_MISMATCH",
                )
            guarded_history = (
                guard_applied_at is not None
                and _is_utc_datetime(publication.created_at)
                and _is_utc_datetime(publication.published_at)
                and publication.created_at > guard_applied_at
                and publication.published_at > guard_applied_at
            )
            self._validate_scope_history(
                dataset_key=query.dataset_key,
                publication_key=publication_key,
                target_publication_id=publication.publication_id,
                as_of=query.as_of,
                server_now=server_now,
            )

            members = list(
                PublicationMemberModel._default_manager.using(self._using)
                .select_for_update()
                .filter(publication_id=publication_id)
                .order_by("member_id")
            )
            coverages = list(
                CoverageSnapshotModel._default_manager.using(self._using)
                .select_for_update()
                .filter(publication_id=publication_id)
                .order_by("coverage_id")
            )
            if len(members) != 1 or len(coverages) != 1:
                raise DataFetchError(
                    "Formal calendar history requires exactly one member and coverage row",
                    code="CALENDAR_FORMAL_PUBLICATION_CARDINALITY_INVALID",
                )
            snapshot_ids = self._snapshot_ids_for_publication(query.publication_id)
            snapshots, facts = self._lock_and_rebuild_snapshots(snapshot_ids)
            snapshot = snapshots.get(snapshot_ids[0])
            fact_model = facts.get(snapshot_ids[0])
            if snapshot is None or fact_model is None:
                raise DataFetchError(
                    "Historical calendar source fact or original payload is unavailable",
                    code="CALENDAR_FORMAL_SOURCE_MISSING",
                )
            contract, policy_model = self._load_historical_catalog(
                publication,
                as_of=query.as_of,
                server_now=server_now,
                guarded_history=guarded_history,
            )
            seal = self._build_seal(
                snapshot=snapshot,
                fact_model=fact_model,
                contract=contract,
                policy_model=policy_model,
                member_id=str(members[0].member_id),
                publication_id=query.publication_id,
            )
            try:
                actual_member = members[0].to_domain()
            except (TypeError, ValueError) as error:
                raise DataFetchError(
                    "Historical calendar publication member is corrupt",
                    code="CALENDAR_FORMAL_MEMBER_INVALID",
                ) from error
            if actual_member != seal.member_reference.member:
                raise DataFetchError(
                    "Historical calendar member differs from its exact source fact",
                    code="CALENDAR_FORMAL_MEMBER_BINDING_INVALID",
                )

            self._validate_publication_row(
                publication,
                seal=seal,
                member=actual_member,
                coverage=coverages[0],
                activation_id=None,
                knowledge_cutoff=server_now,
            )
            record = self._historical_record(
                publication=publication,
                seal=seal,
                as_of=query.as_of,
                server_now=server_now,
                guarded_history=guarded_history,
            )
            audit_pair = self._historical_audit_port.verify_historical_published_integrity(
                record,
                as_of=query.as_of,
            )
            if audit_pair.database_alias != self._using:
                raise DataFetchError(
                    "Historical calendar Audit receipt uses another database alias",
                    code="CALENDAR_PUBLICATION_AUDIT_ALIAS_MISMATCH",
                )
            try:
                return HistoricalPublishedExchangeCalendar(
                    record=record,
                    audit_pair=audit_pair,
                    as_of=query.as_of,
                )
            except CalendarFormalPublicationApplicationError as error:
                raise DataFetchError(str(error), code=error.code) from error
        except DataFetchError:
            raise
        except DatabaseError as error:
            raise DataFetchError(
                "Formal calendar historical evidence is unavailable",
                code="CALENDAR_HISTORY_STORAGE_UNAVAILABLE",
            ) from error

    def _require_rollback_router_alias(self) -> None:
        """Require rollback evidence to be read from the same database alias."""

        if (
            router.db_for_read(PublicationRollbackModel) != self._using
            or router.db_for_write(PublicationRollbackModel) != self._using
        ):
            raise DataFetchError(
                "Calendar rollback evidence does not share the publication database",
                code="CALENDAR_FORMAL_ROUTER_ALIAS_MISMATCH",
            )

    def _load_historical_catalog(
        self,
        publication: CanonicalPublicationModel,
        *,
        as_of: datetime,
        server_now: datetime,
        guarded_history: bool,
    ) -> tuple[DatasetContractModel, DatasetPublicationPolicyModel]:
        """Read exact inactive-or-active catalog versions under installed guards."""

        if not _is_utc_datetime(publication.published_at):
            raise DataFetchError(
                "Historical calendar publication has no exact published clock",
                code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
            )

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
            raise DataFetchError(
                "Historical calendar's exact publication policy is unavailable",
                code=code,
            )
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
            raise DataFetchError(
                "Historical calendar's exact dataset contract is unavailable",
                code=code,
            )
        contract = contracts[0]
        for label, row in (("contract", contract), ("policy", policy)):
            if (
                not _is_utc_datetime(row.created_at)
                or not _is_utc_datetime(row.updated_at)
                or row.created_at > as_of
                or row.updated_at > server_now
                or (
                    not guarded_history
                    and (row.updated_at > as_of or row.updated_at > publication.published_at)
                )
            ):
                raise DataFetchError(
                    f"Historical calendar {label} was not known or has a future clock",
                    code="CALENDAR_FORMAL_CONFIGURATION_NOT_KNOWN",
                )
        try:
            contract.to_domain()
            policy.to_domain()
        except (TypeError, ValueError) as error:
            raise DataFetchError(
                "Historical calendar's exact catalog rows are invalid",
                code="CALENDAR_FORMAL_CATALOG_INVALID",
            ) from error
        if publication.dataset_key != CALENDAR_DATASET_KEY:
            raise DataFetchError(
                "Historical formal calendar dataset is outside the guarded scope",
                code="CALENDAR_HISTORY_SCOPE_MISMATCH",
            )
        return contract, policy

    @staticmethod
    def _historical_record(
        *,
        publication: CanonicalPublicationModel,
        seal: CalendarFormalPublicationSeal,
        as_of: datetime,
        server_now: datetime,
        guarded_history: bool,
    ) -> HistoricalCalendarPublicationRecord:
        """Build a pointer-free historical record from the actual lifecycle row."""

        if (
            type(publication.published_at) is not datetime
            or not _is_utc_datetime(publication.published_at)
            or publication.published_at > as_of
            or not _is_utc_datetime(publication.created_at)
            or publication.created_at > as_of
            or not _is_utc_datetime(publication.updated_at)
            or publication.updated_at > server_now
            or publication.reinstated_at is not None
        ):
            raise DataFetchError(
                "Historical calendar publication row has invalid knowledge or rollback clocks",
                code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
            )
        try:
            lifecycle = CalendarPublicationLifecycle(publication.state)
        except (TypeError, ValueError) as error:
            raise DataFetchError(
                "Historical calendar publication lifecycle is unsupported",
                code="CALENDAR_FORMAL_LIFECYCLE_INVALID",
            ) from error
        if lifecycle is CalendarPublicationLifecycle.PUBLISHED:
            if publication.superseded_at is not None or publication.updated_at > as_of:
                raise DataFetchError(
                    "Historical current publication was updated after the requested cutoff",
                    code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
                )
        elif lifecycle is CalendarPublicationLifecycle.SUPERSEDED:
            if (
                not _is_utc_datetime(publication.superseded_at)
                or publication.superseded_at < publication.published_at
                or publication.updated_at != publication.superseded_at
                or (not guarded_history and publication.updated_at > as_of)
            ):
                raise DataFetchError(
                    "Historical supersession is not the exact forward lifecycle update",
                    code="CALENDAR_FORMAL_PUBLICATION_ROW_INVALID",
                )
        else:
            raise DataFetchError(
                "Historical calendar rollback or reinstatement is unsupported",
                code="CALENDAR_FORMAL_LIFECYCLE_UNSUPPORTED",
            )
        if type(seal) is not CalendarFormalPublicationSeal:
            raise DataFetchError(
                "Historical calendar seal has an invalid type",
                code="CALENDAR_FORMAL_SEAL_INVALID",
            )
        record = HistoricalCalendarPublicationRecord(
            seal=seal,
            publication_id=str(publication.publication_id),
            lifecycle=lifecycle,
            published_at=publication.published_at,
            superseded_at=publication.superseded_at,
        )
        if not record.is_effective_at(as_of):
            raise DataFetchError(
                "Historical calendar is outside its exact TTL and lifecycle window",
                code="CALENDAR_HISTORY_NOT_EFFECTIVE",
            )
        return record

    def _validate_scope_history(
        self,
        *,
        dataset_key: str,
        publication_key: str,
        target_publication_id: UUID,
        as_of: datetime,
        server_now: datetime,
    ) -> None:
        """Reject rollback, gaps, overlaps, duplicate starts, and ambiguous winners."""

        rollback_rows = PublicationRollbackModel._default_manager.using(self._using).filter(
            dataset_key=dataset_key,
            publication_key=publication_key,
        )
        if rollback_rows.exists():
            raise DataFetchError(
                "Formal calendar history contains a rollback transition",
                code="CALENDAR_HISTORY_ROLLBACK_UNSUPPORTED",
            )
        rows = list(
            CanonicalPublicationModel._default_manager.using(self._using)
            .select_for_update()
            .filter(
                dataset_key=dataset_key,
                publication_key=publication_key,
                state__in=("published", "superseded"),
            )
            .order_by("published_at", "publication_id")
        )
        if not rows:
            raise DataFetchError(
                "Formal calendar history has no published interval",
                code="CALENDAR_HISTORY_PUBLICATION_MISSING",
            )
        matching_ids = [
            row.publication_id for row in rows if row.publication_id == target_publication_id
        ]
        if len(matching_ids) != 1:
            raise DataFetchError(
                "Requested publication is absent from its exact scope history",
                code="CALENDAR_HISTORY_SCOPE_MISMATCH",
            )
        seen_starts: set[datetime] = set()
        for index, row in enumerate(rows):
            if (
                not _is_utc_datetime(row.published_at)
                or row.published_at > server_now
                or not _is_utc_datetime(row.created_at)
                or row.created_at > server_now
                or not _is_utc_datetime(row.updated_at)
                or row.updated_at > server_now
                or row.reinstated_at is not None
                or row.published_at in seen_starts
            ):
                raise DataFetchError(
                    "Formal calendar scope has duplicate, future, or rollback lifecycle evidence",
                    code="CALENDAR_HISTORY_TIMELINE_INVALID",
                )
            seen_starts.add(row.published_at)
            if row.state == CalendarPublicationLifecycle.SUPERSEDED.value:
                if (
                    index == len(rows) - 1
                    or not _is_utc_datetime(row.superseded_at)
                    or row.superseded_at < row.published_at
                    or row.updated_at != row.superseded_at
                ):
                    raise DataFetchError(
                        "Formal calendar scope has a malformed supersession interval",
                        code="CALENDAR_HISTORY_TIMELINE_INVALID",
                    )
            elif row.state == CalendarPublicationLifecycle.PUBLISHED.value:
                if row.superseded_at is not None or index != len(rows) - 1:
                    raise DataFetchError(
                        "Formal calendar scope has more than one current lifecycle interval",
                        code="CALENDAR_HISTORY_TIMELINE_INVALID",
                    )
            if index > 0 and rows[index - 1].superseded_at != row.published_at:
                raise DataFetchError(
                    "Formal calendar publication intervals overlap or leave a lifecycle gap",
                    code="CALENDAR_HISTORY_TIMELINE_INVALID",
                )
        active = [
            row
            for row in rows
            if _is_utc_datetime(row.published_at)
            and row.published_at <= as_of
            and (row.superseded_at is None or as_of < row.superseded_at)
        ]
        if len(active) != 1 or active[0].publication_id != target_publication_id:
            raise DataFetchError(
                "Historical cutoff has no unique exact publication winner",
                code="CALENDAR_HISTORY_TIMELINE_AMBIGUOUS",
            )


__all__ = ["DjangoFormalExchangeCalendarPublicationHistoryReader"]
