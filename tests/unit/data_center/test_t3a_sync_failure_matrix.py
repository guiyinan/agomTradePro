"""T3A failure-audit contracts for every Data Center synchronization capability."""

from __future__ import annotations

from datetime import date

import pytest

from apps.data_center.application.dtos import (
    SyncCapitalFlowRequest,
    SyncFinancialRequest,
    SyncFundNavRequest,
    SyncNewsRequest,
    SyncPriceRequest,
    SyncQuoteRequest,
    SyncSectorMembershipRequest,
    SyncValuationRequest,
)
from apps.data_center.application.sync_use_cases import (
    SyncCapitalFlowUseCase,
    SyncFinancialUseCase,
    SyncFundNavUseCase,
    SyncNewsUseCase,
    SyncPriceUseCase,
    SyncQuoteUseCase,
    SyncSectorMembershipUseCase,
    SyncValuationUseCase,
)
from apps.data_center.domain.entities import ProviderConfig, RawAudit
from tests.unit.data_center.audited_sync_test_support import (
    CollectingDataFetchAuditWriter,
    CollectingDataPublicationAuditWriter,
    FixedSyncClock,
    FixedSyncIdentityIssuer,
    InMemorySyncUnitOfWork,
    bind_raw_audit,
)

START = date(2024, 1, 1)
END = date(2024, 12, 31)


class _Provider:
    def provider_name(self) -> str:
        return "fixture-provider"

    def _fail(self) -> list[object]:
        raise RuntimeError("provider unavailable")

    def fetch_price_history(self, *_args: object) -> list[object]:
        return self._fail()

    def fetch_quote_snapshots(self, *_args: object) -> list[object]:
        return self._fail()

    def fetch_fund_nav(self, *_args: object) -> list[object]:
        return self._fail()

    def fetch_financials(self, *_args: object, **_kwargs: object) -> list[object]:
        return self._fail()

    def fetch_valuations(self, *_args: object) -> list[object]:
        return self._fail()

    def fetch_sector_memberships(self, *_args: object, **_kwargs: object) -> list[object]:
        return self._fail()

    def fetch_news(self, *_args: object, **_kwargs: object) -> list[object]:
        return self._fail()

    def fetch_capital_flows(self, *_args: object, **_kwargs: object) -> list[object]:
        return self._fail()


class _ProviderRepository:
    def __init__(self) -> None:
        self.config = ProviderConfig(
            id=1,
            name="fixture-provider",
            source_type="akshare",
            is_active=True,
            priority=1,
            api_key="",
            api_secret="",
            http_url="",
            api_endpoint="",
            extra_config={},
            description="",
        )
        self.saved: list[ProviderConfig] = []

    def get_by_id(self, _provider_id: int) -> ProviderConfig:
        return self.config

    def save(self, config: ProviderConfig) -> ProviderConfig:
        self.saved.append(config)
        return config


class _Registry:
    def __init__(self) -> None:
        self.failures: list[tuple[object, ...]] = []

    def get_by_id(self, _provider_id: int) -> _Provider:
        return _Provider()

    def record_failure(self, *args: object) -> None:
        self.failures.append(args)

    def record_success(self, *_args: object) -> None:
        return None


class _FactRepository:
    def bulk_upsert(self, _facts: list[object]) -> int:
        return 0

    def bulk_insert(self, _facts: list[object]) -> int:
        return 0


class _AuditRepository:
    def __init__(self) -> None:
        self.items: list[RawAudit] = []

    def log(self, audit: RawAudit) -> RawAudit:
        persisted = bind_raw_audit(audit)
        self.items.append(persisted)
        return persisted


@pytest.mark.parametrize(
    ("use_case_type", "sync_request"),
    [
        (SyncPriceUseCase, SyncPriceRequest(1, "000001.SZ", START, END)),
        (SyncQuoteUseCase, SyncQuoteRequest(1, ["000001.SZ"])),
        (SyncFundNavUseCase, SyncFundNavRequest(1, "510300.SH", START, END)),
        (SyncFinancialUseCase, SyncFinancialRequest(1, "000001.SZ", 4)),
        (SyncValuationUseCase, SyncValuationRequest(1, "000001.SZ", START, END)),
        (
            SyncSectorMembershipUseCase,
            SyncSectorMembershipRequest(1, sector_code="BK001", effective_date=START),
        ),
        (SyncNewsUseCase, SyncNewsRequest(1, "000001.SZ", 5)),
        (SyncCapitalFlowUseCase, SyncCapitalFlowRequest(1, "000001.SZ", "5d")),
    ],
)
def test_sync_failure_is_audited_and_reraised(
    use_case_type: type[object],
    sync_request: object,
) -> None:
    provider_repo = _ProviderRepository()
    registry = _Registry()
    audit_repo = _AuditRepository()
    dependencies: dict[str, object] = {
        "provider_repo": provider_repo,
        "provider_registry": registry,
        "fact_repo": _FactRepository(),
        "raw_audit_repo": audit_repo,
    }
    if use_case_type in {SyncPriceUseCase, SyncQuoteUseCase}:
        dependencies.update(
            sync_identity_issuer=FixedSyncIdentityIssuer(),
            sync_unit_of_work=InMemorySyncUnitOfWork(),
            data_fetch_audit_writer=CollectingDataFetchAuditWriter(),
            data_publication_audit_writer=CollectingDataPublicationAuditWriter(),
            clock=FixedSyncClock(),
        )
    use_case = use_case_type(
        **dependencies,
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        use_case.execute(sync_request)

    assert audit_repo.items[-1].status == "error"
    assert audit_repo.items[-1].row_count == 0
    if isinstance(use_case, (SyncPriceUseCase, SyncQuoteUseCase)):
        assert provider_repo.saved[-1].extra_config["provider_last_status"] == "degraded"
        assert registry.failures
