"""Stage-specific frozen-manifest contracts for financial capacity workflows."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacitySliceAttempt,
    FinancialCapacityWorkflowError,
    FinancialPublicationSlice,
)
from apps.data_center.application.financial_publication_capacity import (
    FinancialCapacityWorkflow,
    InMemoryFinancialCapacityCheckpointRepository,
)
from apps.data_center.infrastructure import financial_publication_capacity_runtime as runtime


@dataclass(frozen=True, slots=True)
class _FactRow:
    """Small persisted-fact shape consumed at the infrastructure boundary."""

    id: int
    asset_code: str
    report_date: date
    available_at: datetime
    announcement_date: date | None
    basis: str
    source_record_id: str = ""


@dataclass(frozen=True, slots=True)
class _AssetRow:
    """One active asset code returned by the asset universe query."""

    code: str


class _ListQuery:
    """Provide only the queryset operations used by the manifest source."""

    def __init__(self, rows: tuple[object, ...]) -> None:
        self.rows = rows
        self.ordering: tuple[str, ...] = ()
        self.only_fields: tuple[str, ...] = ()
        self.filters: dict[str, object] = {}
        self.iterator_chunk_size: int | None = None
        self.iterator_called = False

    def filter(self, *args: object, **kwargs: object) -> _ListQuery:
        self.filters.update(kwargs)
        return self

    def only(self, *fields: str) -> _ListQuery:
        self.only_fields = fields
        return self

    def order_by(self, *fields: str) -> _ListQuery:
        self.ordering = fields
        return self

    def values_list(self, field: str, *, flat: bool) -> tuple[str, ...]:
        assert field == "code"
        assert flat is True
        return tuple(cast(str, getattr(row, field)) for row in self.rows)

    def values(self, field: str) -> _ListQuery:
        """Represent a single-column subquery without materializing its values."""

        assert field == "code"
        return self

    def __iter__(self) -> Iterator[object]:
        return iter(self.rows)

    def iterator(self, *, chunk_size: int) -> Iterator[object]:
        """Record streaming use and return the deterministic fixture rows."""

        self.iterator_called = True
        self.iterator_chunk_size = chunk_size
        return iter(self.rows)


class _Manager:
    """Return a deterministic local queryset double for infrastructure tests."""

    def __init__(self, query: _ListQuery) -> None:
        self.query = query

    def filter(self, *args: object, **kwargs: object) -> _ListQuery:
        return self.query.filter(*args, **kwargs)


def _binding(environment: str) -> FinancialCapacityBinding:
    """Build a complete synthetic runtime binding for each manifest stage."""

    return FinancialCapacityBinding(
        environment=environment,
        candidate_sha="a" * 40,
        provider_id=17,
        provider_name="AKShare Public",
        provider_source="akshare",
        provider_identity_sha256="b" * 64,
        contract_id="akshare.financial-main-data.notice-date",
        contract_version="2026-10-04.v1",
        contract_sha256="c" * 64,
        parser_id="akshare-financial-row-parser.v1",
        parser_sha256="d" * 64,
        deployment_region="isolated-test" if environment == "isolated" else "production-test",
        publication_policy_version="3",
        publication_policy_sha256="e" * 64,
        isolation_attestation_sha256="f" * 64 if environment == "isolated" else "",
    )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    (
        ("available_at", datetime(2026, 9, 26, tzinfo=UTC)),
        ("report_date", date(2026, 9, 24)),
        ("asset_code", "000002.SZ"),
        ("period_end", date(2026, 3, 31)),
        ("source_record_id", "different-row-id"),
        ("raw_payload_hash", "9" * 64),
        ("announced_at", datetime(2026, 9, 26, tzinfo=UTC)),
        (
            "extra",
            {
                "financial_response_capture_id": "changed-financial-capture",
                "financial_source_time_capture_id": "source-time-capture",
                "financial_source_time_body_sha256": "2" * 64,
            },
        ),
        (
            "extra",
            {
                "financial_response_capture_id": "financial-capture",
                "financial_source_time_capture_id": "changed-source-time-capture",
                "financial_source_time_body_sha256": "2" * 64,
            },
        ),
        (
            "extra",
            {
                "financial_response_capture_id": "financial-capture",
                "financial_source_time_capture_id": "source-time-capture",
                "financial_source_time_body_sha256": "9" * 64,
            },
        ),
    ),
)
def test_manifest_typed_witness_must_match_persisted_fact_fields(
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    replacement: object,
) -> None:
    """A schema marker cannot hide disagreement between witness and persisted fields."""

    announcement_date = date(2026, 9, 25)
    available_at = datetime(2026, 9, 25, tzinfo=UTC)
    contract = SimpleNamespace(
        source_timezone="Asia/Shanghai",
        contract_id="akshare.financial-main-data.notice-date",
        contract_version="2026-10-04.v1",
        contract_sha256="c" * 64,
    )
    witness = SimpleNamespace(
        artifact_reference=SimpleNamespace(
            capture_id="source-time-capture",
            body_sha256="2" * 64,
        ),
        available_at=available_at,
        announced_at=available_at,
        financial_announced_date=announcement_date,
        native_asset_code="000001.SZ",
        native_period_end=date(2026, 6, 30),
        financial_native_row_id="native-row-id",
        source_timezone=contract.source_timezone,
        governed_match_contract_id=contract.contract_id,
        governed_match_contract_version=contract.contract_version,
        governed_match_contract_sha256=contract.contract_sha256,
    )
    decision = SimpleNamespace(
        artifact_reference=SimpleNamespace(
            capture_id="financial-capture",
            evidence=SimpleNamespace(body_sha256="1" * 64),
        ),
        source_time_witness=witness,
        native_asset_code="000001.SZ",
        native_period_end=date(2026, 6, 30),
        native_row_id="native-row-id",
    )
    row = SimpleNamespace(
        available_at=available_at,
        report_date=announcement_date,
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        source_record_id="native-row-id",
        raw_payload_hash="1" * 64,
        announced_at=available_at,
        extra={
            "financial_response_capture_id": "financial-capture",
            "financial_source_time_capture_id": "source-time-capture",
            "financial_source_time_body_sha256": "2" * 64,
        },
        decision_evidence={"schema": "financial-fact-decision-evidence.v2"},
    )
    monkeypatch.setattr(runtime, "decode_financial_decision_evidence", lambda _raw: decision)
    monkeypatch.setattr(runtime, "akshare_notice_date_match_contract", lambda: contract)

    assert runtime._typed_announcement_row_matches(row, announcement_date) is True
    setattr(row, field_name, replacement)
    assert runtime._typed_announcement_row_matches(row, announcement_date) is False


def _install_runtime_doubles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    asset_codes: tuple[str, ...],
    rows: tuple[_FactRow, ...],
    artifact_root: Path,
) -> tuple[_ListQuery, _ListQuery]:
    """Install local query doubles and the explicit retained-body configuration."""

    asset_query = _ListQuery(tuple(_AssetRow(code) for code in asset_codes))
    fact_query = _ListQuery(rows)
    monkeypatch.setattr(
        runtime,
        "AssetMasterModel",
        SimpleNamespace(_default_manager=_Manager(asset_query)),
    )
    monkeypatch.setattr(
        runtime,
        "FinancialFactModel",
        SimpleNamespace(_default_manager=_Manager(fact_query)),
    )
    monkeypatch.setattr(
        runtime,
        "resolve_financial_response_artifact_config",
        lambda: SimpleNamespace(root=artifact_root),
    )
    monkeypatch.setattr(
        runtime,
        "get_provider_config_repository",
        lambda: SimpleNamespace(get_active_by_type=lambda _source: (SimpleNamespace(id=17),)),
    )
    monkeypatch.setattr(
        runtime,
        "_typed_source_identity",
        lambda row: {"fact_id": row.id},
    )
    return asset_query, fact_query


def test_qualification_freezes_one_deterministic_isolated_typed_slice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The isolated path selects and independently verifies exactly one typed pair."""

    announcement_date = date(2026, 9, 25)
    rows = (
        _FactRow(
            1,
            "000001.SZ",
            announcement_date,
            datetime(2026, 9, 25, tzinfo=UTC),
            announcement_date,
            "typed_source_time_verified",
        ),
        _FactRow(
            2,
            "000001.SZ",
            announcement_date,
            datetime(2026, 9, 25, tzinfo=UTC),
            announcement_date,
            "typed_source_time_verified",
        ),
        _FactRow(
            3,
            "000002.SH",
            announcement_date,
            datetime(2026, 9, 25, tzinfo=UTC),
            announcement_date,
            "typed_source_time_verified",
        ),
    )
    asset_query, fact_query = _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ", "000002.SH"),
        rows=rows,
        artifact_root=tmp_path,
    )
    verified: list[dict[str, object]] = []

    def verify(**kwargs: object) -> object:
        verified.append(kwargs)
        return object()

    monkeypatch.setattr(runtime, "_seed_date", lambda row: (row.announcement_date, row.basis))
    monkeypatch.setattr(runtime, "_typed_announcement_row_matches", lambda *_: True)
    monkeypatch.setattr(runtime, "_verify_persisted_pair", verify)

    manifest = runtime._DjangoFinancialCapacityManifestReader().freeze(
        stage="qualification",
        environment="isolated",
        binding=_binding("isolated"),
    )

    assert manifest.slices == (runtime.FinancialPublicationSlice("000001.SZ", announcement_date),)
    assert len(verified) == 1
    assert verified[0]["stored_count"] == 2
    assert verified[0]["artifact_root"] == tmp_path
    assert verified[0]["provider_started_at"] == datetime.min.replace(tzinfo=UTC)
    assert asset_query.ordering == ("code",)
    assert fact_query.ordering == ("asset_code", "-available_at", "-id")
    assert fact_query.filters["source"] == "akshare"
    assert fact_query.filters["asset_code__in"] is asset_query
    assert fact_query.filters["decision_evidence__schema"] == (
        "financial-fact-decision-evidence.v2"
    )
    assert fact_query.iterator_called is True
    assert fact_query.iterator_chunk_size == runtime._FINANCIAL_CAPACITY_MANIFEST_CHUNK_SIZE


@pytest.mark.parametrize(
    ("stage", "environment"),
    (("capacity_rehearsal", "isolated"), ("formal_publication", "production")),
)
def test_full_manifest_streams_newest_typed_row_and_stops_after_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    stage: str,
    environment: str,
) -> None:
    """The complete manifest keeps one newest typed row per asset without caching history."""

    older = date(2026, 6, 30)
    newer = date(2026, 9, 30)
    rows = (
        _FactRow(
            1,
            "000001.SZ",
            newer,
            datetime(2026, 10, 1, tzinfo=UTC),
            newer,
            "typed_source_time_verified",
        ),
        _FactRow(
            2,
            "000001.SZ",
            older,
            datetime(2026, 7, 1, tzinfo=UTC),
            older,
            "typed_source_time_verified",
        ),
        _FactRow(
            3,
            "000002.SH",
            newer,
            datetime(2026, 10, 2, tzinfo=UTC),
            newer,
            "typed_source_time_verified",
        ),
        _FactRow(
            4,
            "000002.SH",
            older,
            datetime(2026, 7, 2, tzinfo=UTC),
            older,
            "typed_source_time_verified",
        ),
    )
    _asset_query, fact_query = _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ", "000002.SH"),
        rows=rows,
        artifact_root=tmp_path,
    )
    monkeypatch.setattr(runtime, "_seed_date", lambda row: (row.announcement_date, row.basis))
    monkeypatch.setattr(runtime, "_typed_announcement_row_matches", lambda *_: True)

    manifest = runtime._DjangoFinancialCapacityManifestReader().freeze(
        stage=stage,
        environment=environment,
        binding=_binding(environment),
    )

    assert manifest.slices == (
        runtime.FinancialPublicationSlice("000001.SZ", newer),
        runtime.FinancialPublicationSlice("000002.SH", newer),
    )
    assert fact_query.iterator_called is True
    assert fact_query.iterator_chunk_size == runtime._FINANCIAL_CAPACITY_MANIFEST_CHUNK_SIZE


def test_qualification_allows_more_than_one_hundred_metric_rows_for_one_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The distinct-candidate guard does not mistake one report's metrics for many dates."""

    announcement_date = date(2026, 9, 25)
    rows = tuple(
        _FactRow(
            index,
            "000001.SZ",
            announcement_date,
            datetime(2026, 9, 25, tzinfo=UTC),
            announcement_date,
            "typed_source_time_verified",
        )
        for index in range(1, 151)
    )
    _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ",),
        rows=rows,
        artifact_root=tmp_path,
    )
    monkeypatch.setattr(runtime, "_seed_date", lambda row: (row.announcement_date, row.basis))
    monkeypatch.setattr(runtime, "_typed_announcement_row_matches", lambda *_: True)
    verified: list[dict[str, object]] = []
    monkeypatch.setattr(
        runtime,
        "_verify_persisted_pair",
        lambda **kwargs: verified.append(kwargs),
    )

    manifest = runtime._DjangoFinancialCapacityManifestReader().freeze(
        stage="qualification",
        environment="isolated",
        binding=_binding("isolated"),
    )

    assert manifest.slices == (runtime.FinancialPublicationSlice("000001.SZ", announcement_date),)
    assert len(verified) == 1
    assert verified[0]["stored_count"] == 150


def test_manifest_candidate_guard_counts_distinct_typed_pair_candidates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Many distinct malformed report identities stop the manifest scan safely."""

    rows = tuple(
        _FactRow(
            index,
            "000001.SZ",
            date(2020 + index, 1, 1),
            datetime(2026, 9, 25, tzinfo=UTC),
            None,
            "untrusted_typed_marker",
        )
        for index in (1, 2, 3)
    )
    _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ",),
        rows=rows,
        artifact_root=tmp_path,
    )
    monkeypatch.setattr(runtime, "_FINANCIAL_CAPACITY_MAX_TYPED_CANDIDATES_PER_ASSET", 2)
    monkeypatch.setattr(runtime, "_seed_date", lambda _row: (None, "unavailable"))

    with pytest.raises(FinancialCapacityWorkflowError, match="candidate guard exceeded"):
        runtime._DjangoFinancialCapacityManifestReader().freeze(
            stage="formal_publication",
            environment="production",
            binding=_binding("production"),
        )


def test_manifest_scan_guard_blocks_unbounded_typed_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A pathological typed-history scan stops at the configured per-asset bound."""

    rows = tuple(
        _FactRow(
            index,
            "000001.SZ",
            date(2026, 9, 25),
            datetime(2026, 9, 25, tzinfo=UTC),
            None,
            "untrusted_typed_marker",
        )
        for index in (1, 2, 3)
    )
    _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ",),
        rows=rows,
        artifact_root=tmp_path,
    )
    monkeypatch.setattr(runtime, "_FINANCIAL_CAPACITY_MAX_TYPED_ROWS_PER_ASSET", 2)
    monkeypatch.setattr(runtime, "_seed_date", lambda _row: (None, "unavailable"))

    with pytest.raises(FinancialCapacityWorkflowError, match="scan guard exceeded"):
        runtime._DjangoFinancialCapacityManifestReader().freeze(
            stage="formal_publication",
            environment="production",
            binding=_binding("production"),
        )


def test_qualification_without_typed_source_time_fails_closed_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Legacy available_at/announced_at rows cannot seed an isolated qualification."""

    legacy_date = date(2026, 9, 25)
    _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ",),
        rows=(
            _FactRow(
                1,
                "000001.SZ",
                legacy_date,
                datetime(2026, 9, 25, tzinfo=UTC),
                legacy_date,
                "legacy_available_at_date_untrusted",
            ),
        ),
        artifact_root=tmp_path,
    )
    verifier_calls: list[object] = []
    monkeypatch.setattr(runtime, "_seed_date", lambda row: (row.announcement_date, row.basis))
    monkeypatch.setattr(runtime, "_typed_announcement_row_matches", lambda *_: True)
    monkeypatch.setattr(
        runtime, "_verify_persisted_pair", lambda **_: verifier_calls.append(object())
    )

    class _BindingSource:
        def snapshot(self, *, environment: str, candidate_sha: str) -> FinancialCapacityBinding:
            assert environment == "isolated"
            assert candidate_sha == "a" * 40
            return _binding("isolated")

    class _CountingRunner:
        def __init__(self) -> None:
            self.calls: list[FinancialPublicationSlice] = []

        def execute(
            self,
            *,
            binding: FinancialCapacityBinding,
            item: FinancialPublicationSlice,
        ) -> FinancialCapacitySliceAttempt:
            self.calls.append(item)
            raise AssertionError("provider egress must not follow a missing typed seed")

    class _UnusedPublisher:
        def execute(
            self,
            *,
            binding: FinancialCapacityBinding,
            asset_codes: tuple[str, ...],
        ) -> str:
            raise AssertionError("publication is unavailable during qualification")

    runner = _CountingRunner()
    workflow = FinancialCapacityWorkflow(
        checkpoint_repository=InMemoryFinancialCapacityCheckpointRepository(),
        binding_source=_BindingSource(),
        manifest_source=runtime._DjangoFinancialCapacityManifestReader(),
        slice_runner=runner,
        publisher=_UnusedPublisher(),
        qualification_ceiling_source=SimpleNamespace(get_qualification=lambda **_: None),
        production_ceiling_source=SimpleNamespace(get=lambda **_: None),
        authority_validator=SimpleNamespace(is_current=lambda: True),
        clock=lambda: datetime(2026, 10, 8, tzinfo=UTC),
    )

    with pytest.raises(FinancialCapacityWorkflowError, match="isolated typed announcement seed"):
        workflow.start_qualification(
            workflow_id="qualification-without-typed-evidence",
            candidate_sha="a" * 40,
            total_provider_request_budget=2,
        )

    assert verifier_calls == []
    assert runner.calls == []


def test_formal_manifest_still_requires_typed_source_time_for_every_active_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Production cannot downgrade to one seed when any active asset lacks evidence."""

    announcement_date = date(2026, 9, 25)
    _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ", "000002.SH"),
        rows=(
            _FactRow(
                1,
                "000001.SZ",
                announcement_date,
                datetime(2026, 9, 25, tzinfo=UTC),
                announcement_date,
                "typed_source_time_verified",
            ),
            _FactRow(
                2,
                "000002.SH",
                announcement_date,
                datetime(2026, 9, 25, tzinfo=UTC),
                announcement_date,
                "legacy_available_at_date_untrusted",
            ),
        ),
        artifact_root=tmp_path,
    )
    monkeypatch.setattr(runtime, "_seed_date", lambda row: (row.announcement_date, row.basis))
    monkeypatch.setattr(runtime, "_typed_announcement_row_matches", lambda *_: True)

    with pytest.raises(
        FinancialCapacityWorkflowError, match="typed announcement scope is incomplete"
    ):
        runtime._DjangoFinancialCapacityManifestReader().freeze(
            stage="formal_publication",
            environment="production",
            binding=_binding("production"),
        )


def test_manifest_stage_must_match_bound_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A caller cannot route a production binding through the isolated N=1 selector."""

    _install_runtime_doubles(
        monkeypatch,
        asset_codes=("000001.SZ",),
        rows=(),
        artifact_root=tmp_path,
    )

    with pytest.raises(FinancialCapacityWorkflowError, match="stage and binding environment"):
        runtime._DjangoFinancialCapacityManifestReader().freeze(
            stage="qualification",
            environment="isolated",
            binding=_binding("production"),
        )


@pytest.mark.django_db
def test_formal_manifest_uses_asset_subquery_for_5572_active_assets() -> None:
    """The full production scope stays below SQLite bind limits and uses bounded queries."""

    from apps.data_center.infrastructure.models import AssetMasterModel

    AssetMasterModel.objects.bulk_create(
        [
            AssetMasterModel(
                code=f"{index:06d}.SZ",
                name=f"Security {index}",
                short_name=f"S{index}",
                asset_type="stock",
                exchange="SZSE",
                is_active=True,
            )
            for index in range(1, 5_573)
        ],
        batch_size=500,
    )

    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(
            FinancialCapacityWorkflowError,
            match="typed announcement scope is incomplete",
        ):
            runtime._DjangoFinancialCapacityManifestReader().freeze(
                stage="formal_publication",
                environment="production",
                binding=_binding("production"),
            )

    sql = " ".join(query["sql"] for query in queries.captured_queries).upper()
    assert len(queries) == 2
    assert " IN (SELECT " in sql
    assert "000001.SZ" not in sql
    assert "005572.SZ" not in sql
