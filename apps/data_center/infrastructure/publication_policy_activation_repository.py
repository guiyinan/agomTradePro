"""Django transaction boundary for candidate-bound policy activation."""

from __future__ import annotations

import hashlib
import json
from typing import Final, cast

from django.db import connection, models, transaction

from apps.data_center.application.publication_policy_activation import (
    CatalogFingerprint,
    PublicationPolicyActivationError,
    PublicationPolicyActivationExpectedState,
    PublicationPolicyActivationRepositoryProtocol,
    PublicationPolicyActivationRequest,
    PublicationPolicyActivationResult,
    PublishedCurrentMetadata,
)
from apps.data_center.domain.contracts import DatasetKey, PublicationPolicy

from .catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from .publication_policy_activation_timeout import postgres_timeout_guard
from .publication_policy_repository import PublicationPolicyRepository
from .publication_rollback_models import CanonicalPublicationModel

LOCK_TIMEOUT_MS: Final[int] = 5_000
STATEMENT_TIMEOUT_MS: Final[int] = 35_000
_SHARED_TABLES: Final[tuple[str, ...]] = tuple(
    sorted(
        (
            DataOwnerRegistrationModel._meta.db_table,
            DatasetContractModel._meta.db_table,
            DatasetProviderBindingModel._meta.db_table,
        )
    )
)
_CATALOG_MODELS: Final[tuple[tuple[str, type[models.Model]], ...]] = tuple(
    sorted(
        (
            (DatasetContractModel._meta.db_table, DatasetContractModel),
            (DatasetProviderBindingModel._meta.db_table, DatasetProviderBindingModel),
            (DataOwnerRegistrationModel._meta.db_table, DataOwnerRegistrationModel),
        ),
        key=lambda item: item[0],
    )
)
_PUBLICATION_METADATA_FIELDS: Final[tuple[str, ...]] = (
    "dataset_key",
    "publication_id",
    "policy_version",
    "publication_hash",
    "member_count",
    "as_of",
    "published_at",
    "must_not_use_for_decision",
    "blocked_reason",
)


class DjangoPublicationPolicyActivationRepository(PublicationPolicyActivationRepositoryProtocol):
    """Lock, compare, and activate only the policy rows in one transaction."""

    def __init__(
        self,
        *,
        lock_timeout_ms: int = LOCK_TIMEOUT_MS,
        statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
    ) -> None:
        if type(lock_timeout_ms) is not int or not 1 <= lock_timeout_ms <= 60_000:
            raise ValueError("lock_timeout_ms must be between 1 and 60000 milliseconds")
        if (
            type(statement_timeout_ms) is not int
            or statement_timeout_ms < lock_timeout_ms
            or statement_timeout_ms > 300_000
        ):
            raise ValueError(
                "statement_timeout_ms must be at least lock_timeout_ms and at most 300000"
            )
        self._lock_timeout_ms = lock_timeout_ms
        self._statement_timeout_ms = statement_timeout_ms
        self._policy_repository = PublicationPolicyRepository()

    def preview(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        """Run the complete preflight without changing any persisted row."""

        return self._run(request, commit=False)

    def execute(
        self, request: PublicationPolicyActivationRequest
    ) -> PublicationPolicyActivationResult:
        """Commit the exact candidate after rechecking every expected boundary."""

        return self._run(request, commit=True)

    def _run(
        self,
        request: PublicationPolicyActivationRequest,
        *,
        commit: bool,
    ) -> PublicationPolicyActivationResult:
        """Execute a read-only or committing activation inside one outer transaction."""

        with postgres_timeout_guard(
            self._lock_timeout_ms, self._statement_timeout_ms
        ) as timeout_guard:
            with transaction.atomic():
                timeout_guard.apply()
                # Lock metadata/config before the policy table.  The policy table
                # lock closes the active-policy phantom gap while stable
                # per-dataset row locks are acquired below.
                self._lock_shared_tables()
                self._lock_policy_table()
                self._assert_active_contract_keys(request.expected_state)
                self._assert_candidate_non_targets(request)
                active_before = self._locked_active_policies(request.expected_state)
                self._assert_expected_active_policies(request.expected_state, active_before)
                # Publication writers acquire their policy lock before their
                # publication lock.  Follow that order to avoid a cross-boundary
                # deadlock while still freezing old current metadata for compare.
                self._lock_publication_table()
                baseline_before = self._catalog_fingerprints()
                self._assert_catalog_baseline(request.expected_state, baseline_before)
                publications_before = self._published_current_metadata()
                self._assert_published_current_metadata(request.expected_state, publications_before)

                active_after = active_before
                if commit:
                    for candidate in sorted(
                        request.candidate_policies,
                        key=lambda policy: policy.dataset.value,
                    ):
                        if candidate.dataset.value in request.target_dataset_keys:
                            self._policy_repository.save(candidate)
                    active_after = self._locked_active_policies(request.expected_state)
                    self._assert_expected_post_activation(request, active_after)

                baseline_after = self._catalog_fingerprints()
                if baseline_after != baseline_before:
                    raise PublicationPolicyActivationError(
                        "unrelated catalog fingerprints changed during policy activation"
                    )
                if baseline_after != request.expected_state.unrelated_catalog_baseline:
                    raise PublicationPolicyActivationError(
                        "unrelated catalog fingerprints differ from expected preflight"
                    )
                publications_after = self._published_current_metadata()
                if publications_after != publications_before:
                    raise PublicationPolicyActivationError(
                        "existing current publication metadata changed during policy activation"
                    )
                if publications_after != request.expected_state.published_current_metadata:
                    raise PublicationPolicyActivationError(
                        "existing current publication metadata differs from expected preflight"
                    )
                return PublicationPolicyActivationResult(
                    preview=not commit,
                    activated=commit,
                    target_dataset_keys=request.target_dataset_keys,
                    active_policy_identities=tuple(
                        (policy.dataset.value, policy.identity) for policy in active_after
                    ),
                    catalog_fingerprints=baseline_after,
                    published_current_metadata=publications_after,
                )

    def _lock_shared_tables(self) -> None:
        """Acquire stable SHARE locks for metadata and configuration tables."""

        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                for table_name in _SHARED_TABLES:
                    cursor.execute(
                        f"LOCK TABLE {connection.ops.quote_name(table_name)} IN SHARE MODE"
                    )
            return
        if connection.vendor == "sqlite":
            # SQLite has no PostgreSQL table-lock syntax.  Reading every
            # metadata row in deterministic order still exercises the same
            # preflight boundary for the isolated component database.
            for _table_name, model in _CATALOG_MODELS:
                list(model._default_manager.order_by("pk").values_list("pk", flat=True))
            return
        raise PublicationPolicyActivationError(
            f"unsupported database vendor for policy activation: {connection.vendor}"
        )

    def _lock_policy_table(self) -> None:
        """Prevent policy inserts/updates while active rows are compared."""

        if connection.vendor == "postgresql":
            table_name = connection.ops.quote_name(DatasetPublicationPolicyModel._meta.db_table)
            with connection.cursor() as cursor:
                cursor.execute(f"LOCK TABLE {table_name} IN SHARE ROW EXCLUSIVE MODE")
            return
        if connection.vendor == "sqlite":
            return
        raise PublicationPolicyActivationError(
            f"unsupported database vendor for policy activation: {connection.vendor}"
        )

    def _lock_publication_table(self) -> None:
        """Freeze existing publication metadata after policy locks are held."""

        if connection.vendor == "postgresql":
            table_name = connection.ops.quote_name(CanonicalPublicationModel._meta.db_table)
            with connection.cursor() as cursor:
                cursor.execute(f"LOCK TABLE {table_name} IN SHARE MODE")
            return
        if connection.vendor == "sqlite":
            list(
                CanonicalPublicationModel._default_manager.order_by("pk").values_list(
                    "pk", flat=True
                )
            )
            return
        raise PublicationPolicyActivationError(
            f"unsupported database vendor for policy activation: {connection.vendor}"
        )

    def _assert_active_contract_keys(
        self, expected: PublicationPolicyActivationExpectedState
    ) -> None:
        """Require the active contract versions observed at activation to match."""

        rows = list(
            DatasetContractModel._default_manager.filter(active=True)
            .order_by("dataset_key", "contract_version", "schema_version", "pk")
            .values("dataset_key", "contract_version", "schema_version")
        )
        actual = tuple(
            DatasetKey(
                value=str(row["dataset_key"]),
                contract_version=str(row["contract_version"]),
                schema_version=str(row["schema_version"]),
            )
            for row in cast(list[dict[str, object]], rows)
        )
        expected_keys = tuple(
            sorted(
                (
                    key.value,
                    key.contract_version,
                    key.schema_version,
                )
                for key in expected.active_contract_keys
            )
        )
        actual_keys = tuple(
            sorted((key.value, key.contract_version, key.schema_version) for key in actual)
        )
        if actual_keys != expected_keys:
            raise PublicationPolicyActivationError(
                "active Dataset Contract versions differ from expected preflight"
            )

    def _locked_active_policies(
        self, expected: PublicationPolicyActivationExpectedState
    ) -> tuple[PublicationPolicy, ...]:
        """Lock every expected active policy in stable dataset-key order."""

        active_rows = list(
            DatasetPublicationPolicyModel._default_manager.select_for_update()
            .filter(active=True)
            .order_by("dataset_key", "contract_version", "schema_version", "policy_version", "pk")
        )
        actual_keys = [row.dataset_key for row in active_rows]
        expected_keys = [policy.dataset.value for policy in expected.active_policies]
        if len(set(actual_keys)) != len(actual_keys) or set(actual_keys) != set(expected_keys):
            raise PublicationPolicyActivationError(
                "active publication policy dataset set differs from expected preflight"
            )

        policies: list[PublicationPolicy] = []
        for dataset_key in sorted(expected_keys):
            policy = self._policy_repository.get_locked_active(dataset_key)
            if policy is None:
                raise PublicationPolicyActivationError(
                    f"active publication policy is missing for {dataset_key}"
                )
            policies.append(policy)
        if len({policy.dataset.value for policy in policies}) != len(policies):
            raise PublicationPolicyActivationError("active publication policy keys are ambiguous")
        return tuple(policies)

    def _assert_expected_active_policies(
        self,
        expected: PublicationPolicyActivationExpectedState,
        actual: tuple[PublicationPolicy, ...],
    ) -> None:
        """Compare complete policy decision content as well as identity."""

        expected_by_key = {policy.dataset.value: policy for policy in expected.active_policies}
        actual_by_key = {policy.dataset.value: policy for policy in actual}
        if set(actual_by_key) != set(expected_by_key):
            raise PublicationPolicyActivationError(
                "active publication policy dataset set differs from expected preflight"
            )
        for dataset_key in sorted(expected_by_key):
            expected_policy = expected_by_key[dataset_key]
            actual_policy = actual_by_key[dataset_key]
            if actual_policy.identity != expected_policy.identity:
                raise PublicationPolicyActivationError(
                    f"active publication policy identity drifted for {dataset_key}"
                )
            if (
                actual_policy.content_hash != expected_policy.content_hash
                or actual_policy != expected_policy
            ):
                raise PublicationPolicyActivationError(
                    f"active publication policy decision content drifted for {dataset_key}"
                )

    def _assert_candidate_non_targets(self, request: PublicationPolicyActivationRequest) -> None:
        """Reject a candidate manifest that changes any non-target decision."""

        expected_by_key = {
            policy.dataset.value: policy for policy in request.expected_state.active_policies
        }
        for candidate in request.candidate_policies:
            if candidate.dataset.value not in request.target_dataset_keys:
                expected = expected_by_key[candidate.dataset.value]
                if candidate != expected:
                    raise PublicationPolicyActivationError(
                        f"non-target policy content changed for {candidate.dataset.value}"
                    )

    def _assert_expected_post_activation(
        self,
        request: PublicationPolicyActivationRequest,
        actual: tuple[PublicationPolicy, ...],
    ) -> None:
        """Require exact target candidates and unchanged non-target policies."""

        candidate_by_key = {policy.dataset.value: policy for policy in request.candidate_policies}
        expected_by_key = {
            policy.dataset.value: policy for policy in request.expected_state.active_policies
        }
        actual_by_key = {policy.dataset.value: policy for policy in actual}
        if set(actual_by_key) != set(candidate_by_key):
            raise PublicationPolicyActivationError(
                "active publication policy dataset set changed unexpectedly"
            )
        for dataset_key in sorted(actual_by_key):
            expected_policy = candidate_by_key[dataset_key]
            actual_policy = actual_by_key[dataset_key]
            if (
                actual_policy != expected_policy
                or actual_policy.identity != expected_policy.identity
            ):
                raise PublicationPolicyActivationError(
                    f"activated publication policy differs from candidate for {dataset_key}"
                )
            if (
                dataset_key not in request.target_dataset_keys
                and actual_policy != expected_by_key[dataset_key]
            ):
                raise PublicationPolicyActivationError(
                    f"non-target policy changed for {dataset_key}"
                )
        active_count = DatasetPublicationPolicyModel._default_manager.filter(active=True).count()
        if active_count != len(actual):
            raise PublicationPolicyActivationError(
                "active publication policy uniqueness check failed"
            )

    def _catalog_fingerprints(self) -> tuple[CatalogFingerprint, ...]:
        """Hash all persisted fields for the three unrelated catalog tables."""

        fingerprints: list[CatalogFingerprint] = []
        for table_name, model in _CATALOG_MODELS:
            raw_rows = list(model._default_manager.order_by("pk").values())
            rows = cast(list[dict[str, object]], raw_rows)
            encoded = json.dumps(
                rows,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
                allow_nan=False,
            ).encode("utf-8")
            fingerprints.append(
                CatalogFingerprint(
                    table_name=table_name,
                    row_count=len(rows),
                    sha256=hashlib.sha256(encoded).hexdigest(),
                )
            )
        return tuple(fingerprints)

    @staticmethod
    def _assert_catalog_baseline(
        expected: PublicationPolicyActivationExpectedState,
        actual: tuple[CatalogFingerprint, ...],
    ) -> None:
        """Compare row counts and complete persisted row-set hashes."""

        expected_by_table = {item.table_name: item for item in expected.unrelated_catalog_baseline}
        actual_by_table = {item.table_name: item for item in actual}
        if actual_by_table != expected_by_table:
            raise PublicationPolicyActivationError(
                "unrelated catalog fingerprints differ from expected preflight"
            )

    @staticmethod
    def _published_current_metadata() -> tuple[PublishedCurrentMetadata, ...]:
        """Read exact identity metadata for every published current head."""

        raw_rows = list(
            CanonicalPublicationModel._default_manager.filter(
                state="published", publication_key="current"
            )
            .order_by("dataset_key", "publication_id")
            .values(*_PUBLICATION_METADATA_FIELDS)
        )
        rows = cast(list[dict[str, object]], raw_rows)
        result: list[PublishedCurrentMetadata] = []
        for row in rows:
            member_count = row["member_count"]
            if type(member_count) is not int:
                raise PublicationPolicyActivationError(
                    "current publication member_count is not an integer"
                )
            result.append(
                PublishedCurrentMetadata(
                    dataset_key=str(row["dataset_key"]),
                    publication_id=str(row["publication_id"]),
                    policy_version=str(row["policy_version"]),
                    publication_hash=str(row["publication_hash"]),
                    member_count=member_count,
                    as_of=(str(row["as_of"]) if row["as_of"] is not None else None),
                    published_at=(
                        str(row["published_at"]) if row["published_at"] is not None else None
                    ),
                    must_not_use_for_decision=bool(row["must_not_use_for_decision"]),
                    blocked_reason=str(row["blocked_reason"] or ""),
                )
            )
        return tuple(result)

    @staticmethod
    def _assert_published_current_metadata(
        expected: PublicationPolicyActivationExpectedState,
        actual: tuple[PublishedCurrentMetadata, ...],
    ) -> None:
        """Reject any pre-existing current publication drift before policy writes."""

        if actual != expected.published_current_metadata:
            raise PublicationPolicyActivationError(
                "existing current publication metadata differs from expected preflight"
            )


__all__ = [
    "DjangoPublicationPolicyActivationRepository",
    "LOCK_TIMEOUT_MS",
    "STATEMENT_TIMEOUT_MS",
]
