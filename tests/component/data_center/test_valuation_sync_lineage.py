"""Current valuation facts and audits share their issued sync identity."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.db import connection

from apps.audit.application.data_fetch_audit import DataFetchAuditObservation
from apps.data_center.application.current_valuation_sync import (
    SyncCurrentValuationBatchUseCase,
)
from apps.data_center.application.sync_transaction import DataFetchAuditWriter
from apps.data_center.domain.entities import ProviderConfig, RawAudit, ValuationFact
from apps.data_center.infrastructure.audited_sync_runtime import (
    DjangoDataCenterSyncUnitOfWork,
    DjangoSyncExecutionIdentityIssuer,
)
from apps.data_center.infrastructure.control_plane_repositories import (
    SyncExecutionIdentityRepository,
)
from apps.data_center.infrastructure.models import (
    RawAuditModel,
    SyncExecutionIdentityModel,
    ValuationFactModel,
)
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from apps.data_center.infrastructure.valuation_fact_repository import ValuationFactRepository

_NOW = datetime(2026, 9, 29, 8, 30, tzinfo=UTC)
_AS_OF = date(2026, 9, 29)
_ASSET = "009991.SZ"


def _provider_config() -> ProviderConfig:
    return ProviderConfig(
        id=1,
        name="lineage-provider",
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


class _Provider:
    def provider_name(self) -> str:
        return "lineage-provider"

    def fetch_current_valuations(
        self, _asset_codes: list[str], _as_of_date: date
    ) -> list[ValuationFact]:
        return [
            ValuationFact(
                asset_code=_ASSET,
                val_date=_AS_OF,
                source="provider-source",
                observed_at=_NOW,
                fetched_at=_NOW,
            )
        ]


class _ProviderConfigRepository:
    unit_of_work_key = "django:default"

    def __init__(self) -> None:
        self.config = _provider_config()

    def get_by_id(self, _provider_id: int) -> ProviderConfig:
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.config = config
        return config


class _ProviderRegistry:
    def get_by_id(self, _provider_id: int) -> _Provider:
        return _Provider()

    def record_success(self, *_args: object) -> None:
        return None

    def record_failure(self, *_args: object) -> None:
        return None

    def get_all_statuses(self) -> list[object]:
        return []


class _FetchAuditWriter:
    database_alias = "default"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.observations: list[DataFetchAuditObservation] = []

    def write(self, observation: DataFetchAuditObservation) -> object:
        assert connection.in_atomic_block
        if self.fail:
            raise RuntimeError("fetch audit write failed")
        self.observations.append(observation)
        return object()


class _Clock:
    def now(self) -> datetime:
        return _NOW


class _FailAfterFactWrite:
    unit_of_work_key = "django:default"

    def __init__(self, repository: ValuationFactRepository) -> None:
        self.repository = repository

    def bulk_upsert(self, facts: list[ValuationFact]) -> int:
        self.repository.bulk_upsert(facts)
        raise RuntimeError("fact write failed after persistence")


class _FailAfterRawAuditWrite:
    unit_of_work_key = "django:default"

    def __init__(self, repository: RawAuditRepository) -> None:
        self.repository = repository

    def log(self, audit: RawAudit) -> RawAudit:
        self.repository.log(audit)
        raise RuntimeError("raw audit write failed after persistence")


class _FailingHealthUseCase(SyncCurrentValuationBatchUseCase):
    def _persist_provider_health_metric(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError("provider health write failed")


def _use_case(
    *,
    provider_repository: _ProviderConfigRepository,
    fact_repository: object,
    raw_audit_repository: object,
    identity_repository: SyncExecutionIdentityRepository,
    fetch_audit_writer: DataFetchAuditWriter,
    use_case_type: type[SyncCurrentValuationBatchUseCase] = SyncCurrentValuationBatchUseCase,
) -> SyncCurrentValuationBatchUseCase:
    identity_issuer = DjangoSyncExecutionIdentityIssuer(identity_repository, using="default")
    unit_of_work = DjangoDataCenterSyncUnitOfWork(
        (
            provider_repository,
            fact_repository,  # type: ignore[arg-type]
            raw_audit_repository,  # type: ignore[arg-type]
            identity_repository,
        ),
        fetch_audit_writer,
        using="default",
    )
    return use_case_type(
        provider_repo=provider_repository,
        provider_registry=_ProviderRegistry(),
        fact_repo=fact_repository,  # type: ignore[arg-type]
        raw_audit_repo=raw_audit_repository,  # type: ignore[arg-type]
        sync_identity_issuer=identity_issuer,
        sync_unit_of_work=unit_of_work,
        data_fetch_audit_writer=fetch_audit_writer,
        clock=_Clock(),
    )


@pytest.mark.django_db
def test_valuation_success_persists_identity_fact_raw_audit_and_event_together() -> None:
    provider_repository = _ProviderConfigRepository()
    fact_repository = ValuationFactRepository()
    raw_audit_repository = RawAuditRepository()
    identity_repository = SyncExecutionIdentityRepository()
    fetch_audit_writer = _FetchAuditWriter()
    use_case = _use_case(
        provider_repository=provider_repository,
        fact_repository=fact_repository,
        raw_audit_repository=raw_audit_repository,
        identity_repository=identity_repository,
        fetch_audit_writer=fetch_audit_writer,
    )

    result = use_case.execute(
        provider_id=1,
        asset_codes=[_ASSET],
        as_of_date=_AS_OF,
        require_exact_asset_codes=True,
    )

    assert result.status == "success"
    assert result.run_id and result.ingested_run_id
    assert result.raw_audit_reference.run_id == result.run_id
    assert result.raw_audit_reference.ingested_run_id == result.ingested_run_id
    fact = fact_repository.get_latest(_ASSET)
    assert fact is not None
    assert fact.ingested_run_id == result.ingested_run_id
    audit = RawAuditModel.objects.get(pk=result.raw_audit_reference.raw_audit_id)
    assert str(audit.run_id) == result.run_id
    assert str(audit.ingested_run_id) == result.ingested_run_id
    assert audit.content_hash == result.raw_audit_reference.content_hash
    identity = SyncExecutionIdentityModel.objects.get(run_id=result.run_id)
    assert str(identity.ingested_run_id) == result.ingested_run_id
    assert fetch_audit_writer.observations[0].raw_audit_id == str(audit.pk)
    assert fetch_audit_writer.observations[0].raw_audit_content_hash == audit.content_hash


@pytest.mark.parametrize("failed_stage", ["fact", "raw_audit", "fetch_audit", "health"])
@pytest.mark.django_db
def test_valuation_write_failure_rolls_back_the_complete_lineage(failed_stage: str) -> None:
    provider_repository = _ProviderConfigRepository()
    fact_repository = ValuationFactRepository()
    raw_audit_repository = RawAuditRepository()
    identity_repository = SyncExecutionIdentityRepository()
    fetch_audit_writer = _FetchAuditWriter(fail=failed_stage == "fetch_audit")
    selected_fact_repository: object = fact_repository
    selected_raw_audit_repository: object = raw_audit_repository
    if failed_stage == "fact":
        selected_fact_repository = _FailAfterFactWrite(fact_repository)
    elif failed_stage == "raw_audit":
        selected_raw_audit_repository = _FailAfterRawAuditWrite(raw_audit_repository)
    use_case_type = (
        _FailingHealthUseCase if failed_stage == "health" else SyncCurrentValuationBatchUseCase
    )
    use_case = _use_case(
        provider_repository=provider_repository,
        fact_repository=selected_fact_repository,
        raw_audit_repository=selected_raw_audit_repository,
        identity_repository=identity_repository,
        fetch_audit_writer=fetch_audit_writer,
        use_case_type=use_case_type,
    )

    with pytest.raises(RuntimeError):
        use_case.execute(provider_id=1, asset_codes=[_ASSET], as_of_date=_AS_OF)

    assert not ValuationFactModel.objects.filter(asset_code=_ASSET).exists()
    assert not RawAuditModel.objects.filter(capability="valuation").exists()
    assert not SyncExecutionIdentityModel.objects.filter(
        dataset_key="equity.valuation.fact"
    ).exists()
