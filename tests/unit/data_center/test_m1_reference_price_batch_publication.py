"""Contracts for one explicit multi-security M1 close-reference publication."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

import apps.data_center.m1_reference_price_publication_composition as m1_composition
from apps.audit.application.data_publication_audit import (
    DataPublicationManifestAuditObservation,
    DataPublicationRawAuditManifestReference,
)
from apps.audit.domain.system_audit_event import AuditScopeRef
from apps.data_center.application.current_publication_staging import (
    CurrentPublicationStageCommand,
    CurrentPublicationStagedCandidate,
    CurrentPublicationStagingUseCase,
)
from apps.data_center.application.dtos import SyncResult
from apps.data_center.application.m1_reference_price_batch_publication import (
    M1ReferencePriceBatchPublicationCommand,
    M1ReferencePriceBatchPublicationError,
    M1ReferencePriceBatchPublicationUseCase,
)
from apps.data_center.application.publication_activation import (
    ActivateCanonicalPublicationGroupUseCase,
    CurrentPublicationPointerSnapshot,
    PublicationActivationError,
    PublicationActivationGroupAuditWriter,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
    PublicationActivationManifestAuditWrite,
)
from apps.data_center.application.publication_quality import RecordPublicationQualityUseCase
from apps.data_center.application.sync_market_use_cases import SyncPriceUseCase
from apps.data_center.application.sync_transaction import DataCenterSyncClock
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationMember,
    PublicationState,
)
from apps.data_center.domain.entities import ProviderConfig, RawAuditReference
from apps.data_center.domain.enums import DataCapability
from apps.data_center.domain.protocols import (
    ProviderConfigRepositoryProtocol,
    ProviderRegistryProtocol,
)
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditReference,
)
from apps.data_center.infrastructure.m1_reference_price_batch_publication_audit import (
    M1ReferencePriceBatchPublicationAuditWriter,
)
from core.integration.data_center_audit import (
    SystemAuditEventOutboxCommit,
    SystemAuditReaderContext,
)

_ASSET_CODES = ("600036.SH", "601398.SH")
_THREE_ASSET_CODES = (*_ASSET_CODES, "000001.SZ")
_TARGET_DATE = date(2026, 11, 3)
_NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
_PROVIDER = ProviderConfig(
    id=17,
    name="Tushare Pro",
    source_type="tushare",
    is_active=True,
    priority=1,
    api_key="",
    api_secret="",
    http_url="",
    api_endpoint="",
    extra_config={},
    description="",
)


def _reference(asset_code: str, raw_audit_id: int) -> RawAuditReference:
    """Return one independent exact sync lineage for a requested security."""

    return RawAuditReference(
        raw_audit_id=str(raw_audit_id),
        version="1",
        content_hash=sha256(asset_code.encode()).hexdigest(),
        run_id=str(uuid4()),
        ingested_run_id=str(uuid4()),
    )


def _sync_result(asset_code: str, raw_audit_id: int) -> SyncResult:
    """Return one exact successful historical-price sync result."""

    reference = _reference(asset_code, raw_audit_id)
    return SyncResult(
        domain=DataCapability.HISTORICAL_PRICE.value,
        provider_name=_PROVIDER.name,
        stored_count=1,
        status="success",
        run_id=reference.run_id,
        ingested_run_id=reference.ingested_run_id,
        stored_asset_codes=(asset_code,),
        raw_audit_reference=reference,
    )


class _Sync:
    """Record exact calls and return a prebuilt per-security sync outcome."""

    def __init__(self, outcomes: dict[str, SyncResult | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[int, str, date]] = []

    def execute_exact_daily(
        self,
        *,
        provider_id: int,
        asset_code: str,
        target_trade_date: date,
    ) -> SyncResult:
        """Return the configured outcome for one exact daily request."""

        self.calls.append((provider_id, asset_code, target_trade_date))
        outcome = self.outcomes[asset_code]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _ProviderRepository:
    """Expose one active configured Tushare provider."""

    def get_by_id(self, provider_id: int) -> ProviderConfig | None:
        """Return the provider only when its requested id matches."""

        return _PROVIDER if provider_id == _PROVIDER.id else None


class _PublicationRepository:
    """Expose the current alias required by the quality use case constructor."""

    unit_of_work_key = "django:default"


class _Clock:
    """Provide monotonically increasing aware application timestamps."""

    def __init__(self) -> None:
        self._calls = 0

    def now(self) -> datetime:
        """Return a test clock instant without consulting external state."""

        self._calls += 1
        return _NOW + timedelta(seconds=self._calls)


class _Staging:
    """Capture one exact batch staging command and return its sealed candidate."""

    def __init__(
        self,
        *,
        omit_last_raw_audit: bool = False,
        substitute_last_raw_audit: bool = False,
    ) -> None:
        self.omit_last_raw_audit = omit_last_raw_audit
        self.substitute_last_raw_audit = substitute_last_raw_audit
        self.calls: list[CurrentPublicationStageCommand] = []
        self.staged: CurrentPublicationStagedCandidate | None = None

    def execute(self, command: CurrentPublicationStageCommand) -> CurrentPublicationStagedCandidate:
        """Build a typed candidate from all passed member and raw-audit bindings."""

        self.calls.append(command)
        raw_references = tuple(
            CandidateRawAuditReference(
                raw_audit_id=item.reference.raw_audit_id,
                version=item.reference.version,
                content_hash=item.reference.content_hash,
                provider_name=_PROVIDER.name,
                capability=DataCapability.HISTORICAL_PRICE.value,
                run_id=item.reference.run_id,
                ingested_run_id=item.reference.ingested_run_id,
            )
            for item in command.raw_audit_bindings
        )
        if self.omit_last_raw_audit:
            raw_references = raw_references[:-1]
        if self.substitute_last_raw_audit:
            if not raw_references:
                raise AssertionError("staging fixture cannot substitute an empty RawAudit set")
            raw_references = (
                *raw_references[:-1],
                replace(raw_references[-1], run_id=str(uuid4())),
            )
        publication_id = str(uuid4())
        publication_hash = "a" * 64
        count = len(command.asset_codes)
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key="equity.price.bar",
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            policy_version="p2:unit-test",
            state=PublicationState.CANDIDATE,
            selected_source="tushare",
            publication_hash=publication_hash,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid4()),
                publication_id=publication_id,
                requested_count=count,
                eligible_count=count,
                selected_count=count,
                generated_at=command.published_at,
            ),
            member_count=count,
            created_by="tests.m1_batch",
            run_id=command.run_id,
        )
        manifest = CandidateRawAuditManifest.create(
            publication_id=publication_id,
            publication_hash=publication_hash,
            run_id=command.run_id,
            dataset_key="equity.price.bar",
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            task_attempt_id=command.task_attempt_id,
            raw_audits=raw_references,
        )
        self.staged = CurrentPublicationStagedCandidate(
            publication=publication,
            manifest=manifest,
        )
        return self.staged


class _AuditWriter:
    """Provide the exact activation alias required by the application use case."""

    database_alias = "default"


class _Capture:
    """Carry a minimal complete-authority capability for the use-case boundary."""

    database_alias = "default"
    authority_fence = object()
    authority_proof = object()


class _Activation:
    """Record the single CAS request and return its exact published candidate."""

    def __init__(self, staging: _Staging) -> None:
        self.staging = staging
        self.calls: list[PublicationActivationGroupRequest] = []
        self.audit_writers: list[object] = []
        self.fences: list[object] = []
        self.proofs: list[object] = []

    def execute(
        self,
        request: PublicationActivationGroupRequest,
        *,
        audit_writer: PublicationActivationGroupAuditWriter,
        authority_fence: object,
        authority_proof: object,
    ) -> tuple[CanonicalPublication, ...]:
        """Return the one candidate after recording its activation evidence."""

        self.calls.append(request)
        self.audit_writers.append(audit_writer)
        self.fences.append(authority_fence)
        self.proofs.append(authority_proof)
        if self.staging.staged is None:
            raise AssertionError("activation cannot run before candidate staging")
        publication = replace(
            self.staging.staged.publication,
            state=PublicationState.PUBLISHED,
            published_at=_NOW + timedelta(seconds=4),
        )
        return (publication,)


def _reader_context() -> SystemAuditReaderContext:
    """Return a current fixture context issued through the production factory."""

    return SystemAuditReaderContext._from_authority(
        authority_source_id="fixture:m1-batch-authority",
        authority_source_version="1",
        actor_id="django-user:17",
        user_id=17,
        tenant_id="fixture-tenant",
        owner_id="fixture-owner",
        authority_content_hash="b" * 64,
        is_authenticated=True,
        is_staff=True,
        role="admin",
        authority_state="active",
        authority_recorded_at=_NOW - timedelta(minutes=1),
        authority_valid_until=_NOW + timedelta(hours=1),
    )


def _build_use_case(
    *,
    sync: _Sync,
    staging: _Staging | None = None,
) -> tuple[M1ReferencePriceBatchPublicationUseCase, _Staging, _Activation]:
    """Compose the application use case from typed test-boundary collaborators."""

    actual_staging = staging or _Staging()
    activation = _Activation(actual_staging)
    context = _reader_context()

    def preflight_authority(*, as_of: datetime) -> SystemAuditReaderContext:
        """Return one capability-bearing context for the requested cutoff."""

        del as_of
        return context

    def capture_authority(
        *,
        as_of: datetime,
        preflight_context: SystemAuditReaderContext,
    ) -> _Capture:
        """Preserve the exact context passed through the capture boundary."""

        del as_of
        assert preflight_context is context
        return _Capture()

    def read_pointer(
        dataset_key: str,
        publication_key: str,
    ) -> CurrentPublicationPointerSnapshot:
        """Return an empty current pointer for the CAS contract case."""

        assert dataset_key == "equity.price.bar"
        assert publication_key == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        return CurrentPublicationPointerSnapshot(None, None)

    def build_audit_writer() -> PublicationActivationGroupAuditWriter:
        """Return the required exact-alias group audit capability."""

        return cast(PublicationActivationGroupAuditWriter, _AuditWriter())

    use_case = M1ReferencePriceBatchPublicationUseCase(
        price_sync=cast(SyncPriceUseCase, sync),
        provider_repository=cast(ProviderConfigRepositoryProtocol, _ProviderRepository()),
        staging=cast(CurrentPublicationStagingUseCase, actual_staging),
        activate_group=cast(ActivateCanonicalPublicationGroupUseCase, activation),
        audit_writer_factory=build_audit_writer,
        authority_preflight=preflight_authority,
        authority_capture=capture_authority,
        current_pointer_reader=read_pointer,
        clock=cast(DataCenterSyncClock, _Clock()),
    )
    return use_case, actual_staging, activation


def test_batch_command_requires_two_or_more_unique_canonical_securities() -> None:
    """Reject singleton, duplicate, aliased, and non-date scope before syncing."""

    valid = M1ReferencePriceBatchPublicationCommand(
        provider_id=17,
        asset_codes=_ASSET_CODES,
        target_trade_date=_TARGET_DATE,
    )
    assert valid.asset_codes == _ASSET_CODES
    assert (
        M1ReferencePriceBatchPublicationCommand(
            provider_id=17,
            asset_codes=_THREE_ASSET_CODES,
            target_trade_date=_TARGET_DATE,
        ).asset_codes
        == _THREE_ASSET_CODES
    )

    for codes, trade_date in (
        ((), _TARGET_DATE),
        (("600036.SH",), _TARGET_DATE),
        ((_ASSET_CODES[0], _ASSET_CODES[0]), _TARGET_DATE),
        (("600036", _ASSET_CODES[1]), _TARGET_DATE),
        (_ASSET_CODES, datetime(2026, 11, 3, tzinfo=UTC)),
    ):
        with pytest.raises(M1ReferencePriceBatchPublicationError):
            M1ReferencePriceBatchPublicationCommand(
                provider_id=17,
                asset_codes=codes,
                target_trade_date=trade_date,
            )


def test_three_exact_members_stage_and_activate_as_one_candidate() -> None:
    """Bind a larger explicit set to one staged candidate and one CAS activation."""

    sync = _Sync(
        {
            asset_code: _sync_result(asset_code, 41 + index)
            for index, asset_code in enumerate(_THREE_ASSET_CODES)
        }
    )
    use_case, staging, activation = _build_use_case(sync=sync)
    command = M1ReferencePriceBatchPublicationCommand(
        provider_id=17,
        asset_codes=_THREE_ASSET_CODES,
        target_trade_date=_TARGET_DATE,
    )

    result = use_case.execute(command)

    assert sync.calls == [(17, asset_code, _TARGET_DATE) for asset_code in _THREE_ASSET_CODES]
    assert len(staging.calls) == 1
    stage_command = staging.calls[0]
    assert stage_command.asset_codes == _THREE_ASSET_CODES
    assert stage_command.required_observation_date == _TARGET_DATE
    assert len(stage_command.raw_audit_bindings) == 3
    assert tuple(item.reference.raw_audit_id for item in stage_command.raw_audit_bindings) == (
        "41",
        "42",
        "43",
    )
    assert len(activation.calls) == 1
    request = activation.calls[0]
    assert len(request.candidates) == 1
    assert request.candidates[0].dataset_key == "equity.price.bar"
    assert request.candidates[0].publication_key == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
    assert len(activation.audit_writers) == 1
    assert type(activation.audit_writers[0]) is _AuditWriter
    assert result.publication.state is PublicationState.PUBLISHED
    assert result.publication.member_count == 3
    assert len(result.sync_results) == 3


def test_second_sync_failure_never_stages_or_activates_a_partial_batch() -> None:
    """Do not stage the first security when the next exact sync fails."""

    sync = _Sync(
        {
            _ASSET_CODES[0]: _sync_result(_ASSET_CODES[0], 51),
            _ASSET_CODES[1]: RuntimeError("second exact capture failed"),
        }
    )
    use_case, staging, activation = _build_use_case(sync=sync)

    with pytest.raises(RuntimeError, match="second exact capture failed"):
        use_case.execute(
            M1ReferencePriceBatchPublicationCommand(
                provider_id=17,
                asset_codes=_ASSET_CODES,
                target_trade_date=_TARGET_DATE,
            )
        )

    assert len(sync.calls) == 2
    assert staging.calls == []
    assert activation.calls == []


@pytest.mark.parametrize(
    ("omit_last_raw_audit", "substitute_last_raw_audit", "expected_reason"),
    (
        (
            True,
            False,
            "staged M1 candidate differs from its exact batch scope",
        ),
        (
            False,
            True,
            "staged M1 manifest contains a substituted RawAudit reference",
        ),
    ),
)
def test_substituted_or_incomplete_batch_manifest_blocks_activation(
    omit_last_raw_audit: bool,
    substitute_last_raw_audit: bool,
    expected_reason: str,
) -> None:
    """Require every exact per-security RawAudit before invoking the CAS port."""

    sync = _Sync(
        {
            _ASSET_CODES[0]: _sync_result(_ASSET_CODES[0], 61),
            _ASSET_CODES[1]: _sync_result(_ASSET_CODES[1], 62),
        }
    )
    use_case, staging, activation = _build_use_case(
        sync=sync,
        staging=_Staging(
            omit_last_raw_audit=omit_last_raw_audit,
            substitute_last_raw_audit=substitute_last_raw_audit,
        ),
    )

    with pytest.raises(M1ReferencePriceBatchPublicationError, match=expected_reason):
        use_case.execute(
            M1ReferencePriceBatchPublicationCommand(
                provider_id=17,
                asset_codes=_ASSET_CODES,
                target_trade_date=_TARGET_DATE,
            )
        )

    assert len(staging.calls) == 1
    assert activation.calls == []
    assert activation.audit_writers == []


def test_public_factory_composes_batch_writer_and_preserves_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expose a separately wired batch factory without altering the single-symbol path."""

    environments: list[str] = []

    def build_sync(**kwargs: object) -> _Sync:
        """Record the chosen environment and return an inert exact-sync boundary."""

        environment = kwargs.get("environment")
        assert type(environment) is str
        environments.append(environment)
        return _Sync({})

    def get_audit_writers(*, environment: str, using: str) -> tuple[object, ...]:
        """Return a same-alias publication quality writer placeholder."""

        assert using == "default"
        environments.append(environment)
        return (None, None, None, None, None, None, None, SimpleNamespace(database_alias=using))

    monkeypatch.setattr(m1_composition, "make_system_audited_sync_price_use_case", build_sync)
    monkeypatch.setattr(m1_composition, "get_data_reliability_audit_writers", get_audit_writers)
    monkeypatch.setattr(
        m1_composition,
        "get_data_publication_activation_audit_writer",
        lambda **_kwargs: _Delegate(),
    )
    monkeypatch.setattr(
        m1_composition,
        "CanonicalPublicationRepository",
        _PublicationRepository,
    )
    monkeypatch.setattr(m1_composition, "PriceBarRepository", object)
    monkeypatch.setattr(m1_composition, "PublicationPolicyRepository", object)
    monkeypatch.setattr(
        m1_composition,
        "CurrentPublicationRebuildUseCase",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        m1_composition,
        "DjangoCandidateRawAuditMetadataResolver",
        lambda *, using: SimpleNamespace(database_alias=using),
    )
    monkeypatch.setattr(
        m1_composition,
        "DjangoCurrentPublicationStagingRepository",
        lambda *, using, publication_repository: SimpleNamespace(database_alias=using),
    )
    monkeypatch.setattr(
        m1_composition,
        "CurrentPublicationStagingUseCase",
        lambda **_kwargs: _Staging(),
    )
    monkeypatch.setattr(
        m1_composition,
        "DjangoPublicationActivationGroupRepository",
        lambda *, using: SimpleNamespace(database_alias=using),
    )
    monkeypatch.setattr(m1_composition, "DjangoDataCenterSyncClock", _Clock)

    use_case = m1_composition.build_m1_reference_price_batch_publication_use_case(
        provider_repository=cast(ProviderConfigRepositoryProtocol, _ProviderRepository()),
        provider_registry=cast(ProviderRegistryProtocol, object()),
        environment="development",
    )

    audit_writer = use_case._audit_writer_factory()
    assert type(audit_writer) is M1ReferencePriceBatchPublicationAuditWriter
    assert audit_writer.database_alias == "default"
    assert environments == ["development", "development"]


def _audit_write(
    raw_count: int | None = None,
    *,
    asset_codes: tuple[str, ...] = _ASSET_CODES,
    publication_state: PublicationState = PublicationState.PUBLISHED,
) -> tuple[
    PublicationActivationGroupRequest,
    tuple[PublicationActivationManifestAuditWrite, ...],
    tuple[RawAuditReference, ...],
]:
    """Build an exact typed M1 audit write with an optionally short manifest."""

    references = tuple(
        _reference(asset_code, 71 + index) for index, asset_code in enumerate(asset_codes)
    )
    candidate_refs = tuple(
        CandidateRawAuditReference(
            raw_audit_id=reference.raw_audit_id,
            version=reference.version,
            content_hash=reference.content_hash,
            provider_name=_PROVIDER.name,
            capability=DataCapability.HISTORICAL_PRICE.value,
            run_id=reference.run_id,
            ingested_run_id=reference.ingested_run_id,
        )
        for reference in (references if raw_count is None else references[:raw_count])
    )
    publication_id = str(uuid4())
    aggregate_run_id = str(uuid4())
    publication_hash = "c" * 64
    manifest = CandidateRawAuditManifest.create(
        publication_id=publication_id,
        publication_hash=publication_hash,
        run_id=aggregate_run_id,
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        task_attempt_id=f"m1-reference-price-batch:{aggregate_run_id}",
        raw_audits=candidate_refs,
    )
    coverage = CoverageSnapshot(
        coverage_id=str(uuid4()),
        publication_id=publication_id,
        requested_count=len(asset_codes),
        eligible_count=len(asset_codes),
        selected_count=len(asset_codes),
        generated_at=_NOW,
    )
    publication = CanonicalPublication(
        publication_id=publication_id,
        dataset_key="equity.price.bar",
        publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        policy_version="p2:unit-test",
        state=publication_state,
        selected_source="tushare",
        publication_hash=publication_hash,
        coverage=coverage,
        member_count=len(asset_codes),
        run_id=aggregate_run_id,
        published_at=(
            _NOW + timedelta(seconds=1)
            if publication_state in {PublicationState.PUBLISHED, PublicationState.SUPERSEDED}
            else None
        ),
        superseded_at=(
            _NOW + timedelta(seconds=2)
            if publication_state is PublicationState.SUPERSEDED
            else None
        ),
        blocked_reason=(
            "unit-test blocked publication" if publication_state is PublicationState.BLOCKED else ""
        ),
    )
    members = tuple(
        PublicationMember(
            member_id=str(uuid4()),
            publication_id=publication_id,
            dataset_key="equity.price.bar",
            natural_key=asset_code,
            source="tushare",
            source_record_id=references[index].run_id,
            fact_table="data_center_price_bar",
            fact_pk=str(index + 1),
            observed_at=_NOW,
        )
        for index, asset_code in enumerate(asset_codes)
    )
    audit_references = tuple(
        DataPublicationRawAuditManifestReference(
            raw_audit_id=item.raw_audit_id,
            version=item.version,
            content_hash=item.content_hash,
        )
        for item in manifest.raw_audits
    )
    observation = DataPublicationManifestAuditObservation(
        dataset_key=publication.dataset_key,
        publication_key=publication.publication_key,
        publication_id=publication.publication_id,
        publication_version=publication.policy_version,
        publication_hash=publication.publication_hash,
        provider_key=publication.selected_source,
        run_id=publication.run_id,
        member_count=publication.member_count,
        coverage_requested_count=coverage.requested_count,
        coverage_eligible_count=coverage.eligible_count,
        coverage_selected_count=coverage.selected_count,
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        manifest_hash=manifest.manifest_hash,
        raw_audit_count=manifest.raw_audit_count,
        raw_audit_hash=manifest.raw_audit_hash,
        raw_audits=audit_references,
        occurred_at=_NOW,
        recorded_at=_NOW + timedelta(seconds=2),
        scope=AuditScopeRef(tenant_id="fixture-tenant", owner_id="fixture-owner"),
    )
    write = PublicationActivationManifestAuditWrite(
        publication=publication,
        members=members,
        manifest=manifest,
        observation=observation,
    )
    request = PublicationActivationGroupRequest(
        activation_id=str(uuid4()),
        candidates=(
            PublicationActivationGroupCandidate(
                dataset_key=publication.dataset_key,
                publication_key=publication.publication_key,
                candidate_publication_id=publication.publication_id,
                candidate_publication_hash=publication.publication_hash,
            ),
        ),
    )
    return request, (write,), references


class _Delegate:
    """Capture one group-manifest audit append."""

    database_alias = "default"

    def __init__(self) -> None:
        self.calls: list[
            tuple[
                PublicationActivationGroupRequest,
                tuple[PublicationActivationManifestAuditWrite, ...],
            ]
        ] = []

    def append_manifest_group_required(
        self,
        *,
        request: PublicationActivationGroupRequest,
        writes: tuple[PublicationActivationManifestAuditWrite, ...],
    ) -> tuple[SystemAuditEventOutboxCommit, ...]:
        """Return one committed manifest event after retaining the exact write."""

        self.calls.append((request, writes))
        return (cast(SystemAuditEventOutboxCommit, object()),)


class _QualityRecorder:
    """Capture quality audits, preserving each real RawAudit run identity."""

    database_alias = "default"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, str]] = []

    def execute(
        self,
        *,
        publication_id: str,
        run_id: str,
        ingested_run_id: str,
        provider_key: str,
    ) -> None:
        """Record the exact raw lineage passed by the batch audit adapter."""

        self.calls.append((publication_id, run_id, ingested_run_id, provider_key))


def test_batch_audit_adapter_preserves_every_real_raw_audit_lineage() -> None:
    """Append one manifest group and per-source quality audits in lineage order."""

    request, writes, references = _audit_write()
    delegate = _Delegate()
    quality = _QualityRecorder()
    writer = M1ReferencePriceBatchPublicationAuditWriter(
        delegate=cast(PublicationActivationGroupAuditWriter, delegate),
        quality_recorder=cast(RecordPublicationQualityUseCase, quality),
    )

    commits = writer.append_manifest_group_required(request=request, writes=writes)

    assert len(commits) == 1
    assert delegate.calls == [(request, writes)]
    publication = writes[0].publication
    assert quality.calls == [
        (publication.publication_id, item.run_id, item.ingested_run_id, "tushare")
        for item in references
    ]


def test_batch_audit_adapter_accepts_three_exact_members_and_raw_audits() -> None:
    """Allow any explicit finite set of at least two complete source members."""

    request, writes, references = _audit_write(asset_codes=_THREE_ASSET_CODES)
    delegate = _Delegate()
    quality = _QualityRecorder()
    writer = M1ReferencePriceBatchPublicationAuditWriter(
        delegate=cast(PublicationActivationGroupAuditWriter, delegate),
        quality_recorder=cast(RecordPublicationQualityUseCase, quality),
    )

    writer.append_manifest_group_required(request=request, writes=writes)

    assert writes[0].publication.member_count == 3
    assert len(writes[0].members) == 3
    assert writes[0].manifest.raw_audit_count == 3
    assert len(quality.calls) == 3
    assert [call[1:3] for call in quality.calls] == [
        (item.run_id, item.ingested_run_id) for item in references
    ]


@pytest.mark.parametrize(
    "publication_state",
    (PublicationState.CANDIDATE, PublicationState.PUBLISHED),
)
def test_batch_audit_adapter_accepts_pre_switch_and_published_snapshots(
    publication_state: PublicationState,
) -> None:
    """Accept the immutable candidate snapshot and exact already-published replay state."""

    request, writes, references = _audit_write(publication_state=publication_state)
    delegate = _Delegate()
    quality = _QualityRecorder()
    writer = M1ReferencePriceBatchPublicationAuditWriter(
        delegate=cast(PublicationActivationGroupAuditWriter, delegate),
        quality_recorder=cast(RecordPublicationQualityUseCase, quality),
    )

    commits = writer.append_manifest_group_required(request=request, writes=writes)

    assert writes[0].publication.state is publication_state
    if publication_state is PublicationState.CANDIDATE:
        assert writes[0].publication.published_at is None
    else:
        assert writes[0].publication.published_at is not None
    assert len(commits) == 1
    assert delegate.calls == [(request, writes)]
    assert quality.calls == [
        (writes[0].publication.publication_id, item.run_id, item.ingested_run_id, "tushare")
        for item in references
    ]


@pytest.mark.parametrize(
    "publication_state",
    (PublicationState.SUPERSEDED, PublicationState.BLOCKED),
)
def test_batch_audit_adapter_rejects_non_current_publication_states(
    publication_state: PublicationState,
) -> None:
    """Keep superseded and blocked snapshots outside the group-audit write boundary."""

    request, writes, _references = _audit_write(publication_state=publication_state)
    delegate = _Delegate()
    quality = _QualityRecorder()
    writer = M1ReferencePriceBatchPublicationAuditWriter(
        delegate=cast(PublicationActivationGroupAuditWriter, delegate),
        quality_recorder=cast(RecordPublicationQualityUseCase, quality),
    )

    with pytest.raises(
        PublicationActivationError,
        match="M1 batch publication or RawAudit identity differs",
    ):
        writer.append_manifest_group_required(request=request, writes=writes)

    assert delegate.calls == []
    assert quality.calls == []


def test_batch_audit_adapter_rejects_a_short_raw_manifest() -> None:
    """Reject an audit manifest that does not cover all published members."""

    request, writes, _references = _audit_write(raw_count=1)
    delegate = _Delegate()
    quality = _QualityRecorder()
    writer = M1ReferencePriceBatchPublicationAuditWriter(
        delegate=cast(PublicationActivationGroupAuditWriter, delegate),
        quality_recorder=cast(RecordPublicationQualityUseCase, quality),
    )

    with pytest.raises(PublicationActivationError, match="RawAudit"):
        writer.append_manifest_group_required(request=request, writes=writes)

    assert delegate.calls == []
    assert quality.calls == []


def test_batch_audit_adapter_rejects_member_raw_audit_count_mismatch() -> None:
    """Reject an omitted member before delegating manifest or quality writes."""

    request, writes, _references = _audit_write()
    delegate = _Delegate()
    quality = _QualityRecorder()
    writer = M1ReferencePriceBatchPublicationAuditWriter(
        delegate=cast(PublicationActivationGroupAuditWriter, delegate),
        quality_recorder=cast(RecordPublicationQualityUseCase, quality),
    )

    with pytest.raises(
        PublicationActivationError,
        match="manifest audit write identity differs",
    ):
        incomplete_write = replace(writes[0], members=writes[0].members[:-1])
        writer.append_manifest_group_required(request=request, writes=(incomplete_write,))

    assert delegate.calls == []
    assert quality.calls == []
