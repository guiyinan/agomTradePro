"""Exact source, catalog and transaction support for restricted publications."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import ParamSpec, Protocol, TypeVar
from uuid import UUID

from django.core.exceptions import ObjectDoesNotExist
from django.db import DatabaseError, connections, models, router

from apps.data_center.application.price_limit_formal_publication_audit_port import (
    PriceLimitPublicationAuditPair,
)
from apps.data_center.application.price_limit_publication_authority import (
    PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME,
    LockedPriceLimitPublisherPrincipal,
)
from apps.data_center.application.price_limit_publication_operations import (
    PriceLimitPublicationScope,
    require_utc,
)
from apps.data_center.domain.formal_price_limit_publication import (
    PriceLimitFormalPublicationRecord,
    PriceLimitFormalPublicationSeal,
    PriceLimitPublicationError,
    PriceLimitPublicationEventKind,
    PriceLimitPublicationPointerExpectation,
    PriceLimitPublicationTimelineEvent,
    create_price_limit_formal_publication_seal,
    validate_price_limit_publication_timeline,
)
from apps.data_center.domain.publication_member_codec import PriceLimitNullableMemberCodecVersion
from core.exceptions import DataFetchError
from shared.infrastructure.postgres_advisory_lock import (
    ScopedAdvisoryLockKey,
    derive_scoped_advisory_lock_id,
)

from .catalog_models import DatasetContractModel, DatasetPublicationPolicyModel
from .fact_and_operational_models import RawPayloadModel
from .price_limit_snapshot_models import PriceLimitSnapshotFactModel
from .price_limit_snapshot_repository import DjangoPriceLimitSnapshotRepository
from .publication_fact_evidence import canonical_fact_content_hash
from .publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)

DATASET = "equity.price.limit"
REFERENCE_STATE = "reference_published"
SUPERSEDED_STATE = "reference_superseded"
REFERENCE_REASON = "PRICE_LIMIT_REFERENCE_ONLY"
_MODELS: tuple[type[models.Model], ...] = (
    DatasetContractModel,
    DatasetPublicationPolicyModel,
    RawPayloadModel,
    PriceLimitSnapshotFactModel,
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    PublicationMemberModel,
    CoverageSnapshotModel,
    PublicationRollbackModel,
)
_Parameters = ParamSpec("_Parameters")
_Return = TypeVar("_Return")


def storage_errors(function: Callable[_Parameters, _Return]) -> Callable[_Parameters, _Return]:
    """Map invalid persisted values and backend failures to stable application failures."""

    @wraps(function)
    def guarded(*args: _Parameters.args, **kwargs: _Parameters.kwargs) -> _Return:
        try:
            return function(*args, **kwargs)
        except PriceLimitPublicationError:
            raise
        except DatabaseError as error:
            raise DataFetchError(
                "Price-limit storage is unavailable",
                code="PRICE_LIMIT_STORAGE_UNAVAILABLE",
                status_code=503,
            ) from error
        except (ValueError, TypeError, ObjectDoesNotExist) as error:
            raise blocked(
                "PRICE_LIMIT_STORED_EVIDENCE_INVALID", "Stored publication evidence is invalid"
            ) from error

    return guarded


def blocked(code: str, message: str) -> DataFetchError:
    """Expose stable reference-publication failures without eligibility fallback."""
    return DataFetchError(message, code=code, status_code=409)


@dataclass(frozen=True, slots=True)
class _History:
    """One fully audited and source-replayed scope history."""

    records: tuple[PriceLimitFormalPublicationRecord, ...]
    events: tuple[PriceLimitPublicationTimelineEvent, ...]
    pointer: PriceLimitPublicationPointerExpectation


class _PriceLimitAuditAliasPort(Protocol):
    """Alias identity shared by the manager and reference audit adapters."""

    @property
    def database_alias(self) -> str:
        """Return the database alias bound to this audit adapter."""


class _PriceLimitHistoryAuditReader(Protocol):
    """Verify exact scope history through a capability-specific audit adapter."""

    def get_first_transition(
        self,
        *,
        publication_id: str,
        publication_hash: str,
        publication_key: str,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Read one exact publication's first transition pair within the scope."""

    def verify_transition(
        self,
        record: PriceLimitFormalPublicationRecord,
        event: PriceLimitPublicationTimelineEvent,
        *,
        server_now: datetime,
    ) -> PriceLimitPublicationAuditPair:
        """Verify one exact reconstructed transition and its outbox pair."""


class _PriceLimitPublicationSupport:
    """Share exact storage validation between the narrow reader and writer."""

    _using: str
    _audit: _PriceLimitAuditAliasPort

    def _fence(
        self,
        scope: PriceLimitPublicationScope,
        principal: LockedPriceLimitPublisherPrincipal,
        server_now: datetime,
    ) -> None:
        require_utc(server_now)
        scope.__post_init__()
        principal.assert_live()
        if (
            principal.database_alias != self._using
            or principal.permission_codename != PRICE_LIMIT_PUBLISH_PERMISSION_CODENAME
            or principal.actor_type != "django_user"
            or principal.actor_id != f"django-user:{principal.user_id}"
        ):
            raise blocked(
                "PRICE_LIMIT_TRANSACTION_INVALID", "One authorized caller transaction is required"
            )
        self._fence_scope_transaction(scope)

    def _fence_reference(
        self,
        scope: PriceLimitPublicationScope,
        server_now: datetime,
    ) -> None:
        """Fence a market reference read without asserting a publisher capability."""

        require_utc(server_now)
        scope.__post_init__()
        self._fence_scope_transaction(scope)

    def _fence_scope_transaction(
        self,
        scope: PriceLimitPublicationScope,
    ) -> None:
        """Hold the common alias, catalog and exact-scope transaction fences."""

        connection = connections[self._using]
        if (
            self._using != "default"
            or self._audit.database_alias != self._using
            or not connection.in_atomic_block
            or connection.get_autocommit()
            or len(connection.atomic_blocks) != 1
        ):
            raise blocked(
                "PRICE_LIMIT_TRANSACTION_INVALID", "One authorized caller transaction is required"
            )
        for model in _MODELS:
            if (
                router.db_for_read(model) != self._using
                or router.db_for_write(model) != self._using
            ):
                raise blocked(
                    "PRICE_LIMIT_ALIAS_MISMATCH",
                    "All source/publication models must share one alias",
                )
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_setting('transaction_isolation')")
                if cursor.fetchone() != ("read committed",):
                    raise blocked("PRICE_LIMIT_ISOLATION_INVALID", "READ COMMITTED is required")
                cursor.execute("SELECT setting::bigint FROM pg_settings WHERE name='lock_timeout'")
                row = cursor.fetchone()
                if row is None:
                    raise blocked("PRICE_LIMIT_LOCK_TIMEOUT_INVALID", "Lock timeout is unavailable")
                old_timeout = int(row[0])
                timeout = min(old_timeout, 5000) if old_timeout > 0 else 5000
                cursor.execute("SELECT set_config('lock_timeout', %s, true)", [str(timeout)])
                for model in sorted(
                    (DatasetContractModel, DatasetPublicationPolicyModel),
                    key=lambda item: item._meta.db_table,
                ):
                    cursor.execute(
                        f"LOCK TABLE {connection.ops.quote_name(model._meta.db_table)} IN SHARE MODE"
                    )
                scope_lock = ScopedAdvisoryLockKey(
                    domain="data-center.formal-price-limit-publication",
                    components=(DATASET, scope.publication_key),
                )
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s)", [derive_scoped_advisory_lock_id(scope_lock)]
                )
        elif connection.vendor == "sqlite":
            table = connection.ops.quote_name(DatasetContractModel._meta.db_table)
            with connection.cursor() as cursor:
                cursor.execute(f"UPDATE {table} SET dataset_key=dataset_key WHERE 1=0")
        else:
            raise blocked("PRICE_LIMIT_DATABASE_UNSUPPORTED", "Unsupported publication database")

    def _active_catalog(
        self, server_now: datetime
    ) -> tuple[DatasetContractModel, DatasetPublicationPolicyModel]:
        contracts = list(
            DatasetContractModel.objects.using(self._using).filter(dataset_key=DATASET, active=True)
        )
        policies = list(
            DatasetPublicationPolicyModel.objects.using(self._using).filter(
                dataset_key=DATASET, active=True
            )
        )
        if len(contracts) != 1 or len(policies) != 1:
            raise blocked(
                "PRICE_LIMIT_CATALOG_UNAVAILABLE",
                "Exactly one active contract and policy are required",
            )
        contract, policy = contracts[0], policies[0]
        if (
            contract.to_domain().key != policy.to_domain().dataset
            or policy.to_domain().member_codec_version
            is not PriceLimitNullableMemberCodecVersion.V1
        ):
            raise blocked(
                "PRICE_LIMIT_CATALOG_MISMATCH", "Active catalog does not bind the exact limit codec"
            )
        for row in (contract, policy):
            require_utc(row.created_at)
            require_utc(row.updated_at)
            if row.created_at > server_now or row.updated_at > server_now:
                raise blocked("PRICE_LIMIT_CATALOG_NOT_KNOWN", "Catalog postdates this operation")
        return contract, policy

    def _exact_catalog(
        self, identity: str
    ) -> tuple[DatasetContractModel, DatasetPublicationPolicyModel]:
        matches = [
            row
            for row in DatasetPublicationPolicyModel.objects.using(self._using).filter(
                dataset_key=DATASET
            )
            if row.to_domain().identity == identity
        ]
        if len(matches) != 1:
            raise blocked(
                "PRICE_LIMIT_POLICY_UNAVAILABLE",
                "Exact historical policy is unavailable or changed",
            )
        policy = matches[0]
        contracts = list(
            DatasetContractModel.objects.using(self._using).filter(
                dataset_key=DATASET,
                contract_version=policy.contract_version,
                schema_version=policy.schema_version,
            )
        )
        if len(contracts) != 1:
            raise blocked(
                "PRICE_LIMIT_CONTRACT_UNAVAILABLE", "Exact historical contract is unavailable"
            )
        return contracts[0], policy

    def _source_seal(
        self,
        snapshot_id: str,
        scope: PriceLimitPublicationScope,
        contract: DatasetContractModel,
        policy: DatasetPublicationPolicyModel,
        server_now: datetime,
    ) -> PriceLimitFormalPublicationSeal:
        raw_ids = list(
            PriceLimitSnapshotFactModel.objects.using(self._using)
            .filter(snapshot_id=UUID(snapshot_id))
            .values_list("raw_payload_id", flat=True)
        )
        if len(raw_ids) != 1:
            raise blocked("PRICE_LIMIT_SOURCE_MISSING", "Exact saved source is unavailable")
        list(RawPayloadModel.objects.using(self._using).select_for_update().filter(pk__in=raw_ids))
        fact = (
            PriceLimitSnapshotFactModel.objects.using(self._using)
            .select_for_update()
            .select_related("raw_payload")
            .get(pk=UUID(snapshot_id))
        )
        snapshot = DjangoPriceLimitSnapshotRepository._to_domain(fact)
        if snapshot.candidate.raw_reference.request_scope_sha256 != scope.request_scope_hash():
            raise blocked(
                "PRICE_LIMIT_SOURCE_SCOPE_MISMATCH",
                "Source belongs to another provider/security/day",
            )
        if (
            snapshot.recorded_at > server_now
            or snapshot.candidate.response_completed_at > server_now
        ):
            raise blocked("PRICE_LIMIT_SOURCE_NOT_KNOWN", "Source was not known at this operation")
        return create_price_limit_formal_publication_seal(
            dataset_contract=contract.to_domain(),
            contract_recorded_at=contract.created_at,
            policy=policy.to_domain(),
            policy_recorded_at=policy.created_at,
            snapshot=snapshot,
            fact_content_hash=canonical_fact_content_hash(fact),
        )

    def _pointer(
        self, scope: PriceLimitPublicationScope
    ) -> PriceLimitPublicationPointerExpectation:
        row = (
            CanonicalPublicationPointerModel.objects.using(self._using)
            .select_for_update()
            .filter(dataset_key=DATASET, publication_key=scope.publication_key)
            .first()
        )
        if row is None:
            return PriceLimitPublicationPointerExpectation(
                DATASET, scope.publication_key, None, None, None, None, None
            )
        return PriceLimitPublicationPointerExpectation(
            DATASET,
            scope.publication_key,
            str(row.pointer_id),
            str(row.publication_id) if row.publication_id is not None else None,
            row.publication_hash or None,
            row.activation_id or None,
            row.updated_at,
        )

    def _history(
        self,
        scope: PriceLimitPublicationScope,
        audit_reader: _PriceLimitHistoryAuditReader,
        server_now: datetime,
    ) -> _History:
        pointer = self._pointer(scope)
        rows = list(
            CanonicalPublicationModel.objects.using(self._using)
            .select_for_update()
            .filter(dataset_key=DATASET, publication_key=scope.publication_key)
            .order_by("publication_id")
        )
        records: list[PriceLimitFormalPublicationRecord] = []
        events: list[PriceLimitPublicationTimelineEvent] = []
        for row in rows:
            if row.state not in {REFERENCE_STATE, SUPERSEDED_STATE} or row.published_at is None:
                raise blocked(
                    "PRICE_LIMIT_PUBLICATION_STATE_INVALID", "Unexpected publication history state"
                )
            members = list(
                PublicationMemberModel.objects.using(self._using)
                .select_for_update()
                .filter(publication_id=row.publication_id)
            )
            if len(members) != 1:
                raise blocked("PRICE_LIMIT_MEMBER_INVALID", "Expected one exact price-limit member")
            member = members[0]
            contract, policy = self._exact_catalog(row.policy_version)
            seal = self._source_seal(member.fact_pk, scope, contract, policy, server_now)
            pair = audit_reader.get_first_transition(
                publication_id=str(row.publication_id),
                publication_hash=row.publication_hash,
                publication_key=scope.publication_key,
                server_now=server_now,
            )
            event = pair.timeline_event
            if row.created_by != f"django-user:{pair.actor_user_id}":
                raise blocked(
                    "PRICE_LIMIT_PUBLICATION_ACTOR_MISMATCH",
                    "Original publication actor differs from its Audit record",
                )
            record = PriceLimitFormalPublicationRecord(
                seal, str(row.publication_id), row.published_at, event.event_id
            )
            self._validate_persisted(row, member, record)
            audit_reader.verify_transition(record, event, server_now=server_now)
            records.append(record)
            events.append(event)
        by_id = {record.publication_id: record for record in records}
        for rollback in (
            PublicationRollbackModel.objects.using(self._using)
            .select_for_update()
            .filter(dataset_key=DATASET, publication_key=scope.publication_key)
            .order_by("observed_at")
        ):
            target = by_id.get(str(rollback.target_publication_id))
            previous = by_id.get(str(rollback.previous_publication_id))
            if target is None or previous is None:
                raise blocked(
                    "PRICE_LIMIT_ROLLBACK_TARGET_MISSING", "Rollback references unavailable history"
                )
            event = PriceLimitPublicationTimelineEvent(
                PriceLimitPublicationEventKind.ROLLBACK,
                str(rollback.rollback_id),
                DATASET,
                scope.publication_key,
                previous.publication_id,
                previous.publication_hash,
                target.publication_id,
                target.publication_hash,
                rollback.observed_at,
                rollback.to_domain(),
            )
            audit_reader.verify_transition(target, event, server_now=server_now)
            events.append(event)
        # Sorting merely presents the verified events to the continuity validator;
        # equal times remain invalid and UUIDs never break ties.
        ordered = tuple(sorted(events, key=lambda event: event.transitioned_at))
        if any(event.transitioned_at > server_now for event in ordered):
            raise blocked(
                "PRICE_LIMIT_HISTORY_FROM_FUTURE", "History postdates the server observation"
            )
        result = _History(tuple(records), ordered, pointer)
        validate_price_limit_publication_timeline(
            records=result.records, events=result.events, current_pointer=pointer
        )
        for row in rows:
            expected_state = (
                REFERENCE_STATE
                if str(row.publication_id) == pointer.publication_id
                else SUPERSEDED_STATE
            )
            if row.state != expected_state:
                raise blocked(
                    "PRICE_LIMIT_PUBLICATION_STATE_INVALID",
                    "Stored lifecycle differs from current pointer",
                )
        return result

    def _validate_persisted(
        self,
        row: CanonicalPublicationModel,
        member: PublicationMemberModel,
        record: PriceLimitFormalPublicationRecord,
    ) -> None:
        seal = record.seal
        expected_member = seal.member_evidence.to_publication_member(
            publication_id=record.publication_id, member_id=str(member.member_id)
        )
        coverage = (
            CoverageSnapshotModel.objects.using(self._using)
            .select_for_update()
            .filter(publication_id=row.publication_id)
            .first()
        )
        if (
            row.publication_hash != seal.publication_hash
            or row.member_manifest_hash != seal.member_manifest_hash
            or row.selected_source != seal.snapshot.candidate.provider_name
            or row.member_count != 1
            or row.conflict_count != 0
            or row.coverage_requested_count != 1
            or row.coverage_eligible_count != 1
            or row.coverage_selected_count != 1
            or row.coverage_missing_count != 0
            or row.coverage_conflict_count != 0
            or row.must_not_use_for_decision is not True
            or row.blocked_reason != REFERENCE_REASON
            or row.scope_blocks != []
            or row.run_id is not None
            or row.members_sealed_at != row.published_at
            or row.as_of != row.published_at
            or member.to_domain() != expected_member
            or coverage is None
            or coverage.requested_count != 1
            or coverage.eligible_count != 1
            or coverage.selected_count != 1
            or coverage.missing_count != 0
            or coverage.conflict_count != 0
            or coverage.generated_at != row.published_at
        ):
            raise blocked(
                "PRICE_LIMIT_PUBLICATION_EVIDENCE_CORRUPT",
                "Persisted publication/member/coverage differs from the sealed source",
            )
