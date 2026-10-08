"""Composition keeps one source-time verifier across write and publication paths."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from apps.data_center import financial_source_time_composition as composition
from apps.data_center.application.financial_source_time_verifier import (
    FinancialSourceTimeContractMatcher,
)
from apps.data_center.application.interface_services import (
    make_backfill_sync_financial_use_case,
    make_sync_financial_use_case,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.financial_source_time_contract import (
    FinancialSourceTimeMatchContract,
)
from apps.data_center.financial_source_time_composition import (
    _MATCHERS,
    _resolve_contract_matcher,
    verify_provider_financial_source_time_evidence,
    verify_retained_financial_source_time_evidence,
)
from apps.data_center.publication_rebuild_composition import (
    build_current_publication_rebuild,
)


def test_financial_sync_builders_share_provider_and_repository_verifiers() -> None:
    for factory in (make_sync_financial_use_case, make_backfill_sync_financial_use_case):
        use_case = factory()
        assert (
            use_case._source_time_artifact_verifier
            is verify_provider_financial_source_time_evidence
        )
        assert (
            use_case._facts._source_time_evidence_verifier
            is verify_retained_financial_source_time_evidence
        )


def test_current_financial_publication_uses_the_repository_verifier() -> None:
    rebuild = build_current_publication_rebuild(dataset_keys=("equity.financial.fact",))
    assert len(rebuild._rebuilders) == 1
    candidate_repository = rebuild._rebuilders[0]._candidates
    assert (
        candidate_repository._source_time_evidence_verifier
        is verify_retained_financial_source_time_evidence
    )


def test_matcher_registry_uses_exact_contract_identity_not_parser_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two governed contracts may share a parser label without sharing a matcher."""

    first = cast(
        FinancialSourceTimeMatchContract,
        SimpleNamespace(
            identity=("provider-a", "notice-contract", "v1", "1" * 64),
            parser_version="shared-parser.v1",
        ),
    )
    second = cast(
        FinancialSourceTimeMatchContract,
        SimpleNamespace(
            identity=("provider-b", "notice-contract", "v1", "2" * 64),
            parser_version="shared-parser.v1",
        ),
    )
    unregistered = cast(
        FinancialSourceTimeMatchContract,
        SimpleNamespace(
            identity=("provider-c", "notice-contract", "v1", "3" * 64),
            parser_version="shared-parser.v1",
        ),
    )
    digest_substitution = cast(
        FinancialSourceTimeMatchContract,
        SimpleNamespace(
            identity=("provider-a", "notice-contract", "v1", "4" * 64),
            parser_version="shared-parser.v1",
        ),
    )
    first_matcher = cast(FinancialSourceTimeContractMatcher, object())
    second_matcher = cast(FinancialSourceTimeContractMatcher, object())
    legacy_parser_matcher = cast(FinancialSourceTimeContractMatcher, object())
    monkeypatch.setitem(_MATCHERS, first.identity, first_matcher)
    monkeypatch.setitem(_MATCHERS, second.identity, second_matcher)
    monkeypatch.setitem(
        cast(dict[object, FinancialSourceTimeContractMatcher], _MATCHERS),
        "shared-parser.v1",
        legacy_parser_matcher,
    )

    assert _resolve_contract_matcher(first) is first_matcher
    assert _resolve_contract_matcher(second) is second_matcher
    assert _resolve_contract_matcher(unregistered) is None
    assert _resolve_contract_matcher(digest_substitution) is None


def test_provider_verifier_uses_logical_source_and_binds_the_exact_provider_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Display names may vary while active source type and audit row ID remain exact."""

    evidence = cast(
        FinancialFactDecisionEvidence,
        SimpleNamespace(
            artifact_reference=SimpleNamespace(
                evidence=SimpleNamespace(request_scope=SimpleNamespace(provider_name="akshare"))
            )
        ),
    )
    expected_ids: list[int | None] = []

    def verify(
        _decision_evidence: FinancialFactDecisionEvidence,
        *,
        environment: str | None,
        expected_provider_id: int | None,
        expected_run_id: UUID | None,
    ) -> bool:
        assert environment is None
        assert expected_run_id is None
        expected_ids.append(expected_provider_id)
        return expected_provider_id == 17

    monkeypatch.setattr(composition, "_verify_source_time_evidence", verify)
    provider = ProviderConfig(
        id=17,
        name="AKShare Public",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="test provider",
    )

    assert verify_provider_financial_source_time_evidence(provider, evidence) is True
    assert expected_ids == [17]
    assert (
        verify_provider_financial_source_time_evidence(
            replace(provider, source_type="tushare"), evidence
        )
        is False
    )
    assert expected_ids == [17]
    assert (
        verify_provider_financial_source_time_evidence(replace(provider, is_active=False), evidence)
        is False
    )
    assert expected_ids == [17]
    assert (
        verify_provider_financial_source_time_evidence(replace(provider, id=18), evidence) is False
    )
    assert expected_ids == [17, 18]


def test_provider_verifier_passes_explicit_s6_artifact_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An explicit S6 root reaches the shared verifier for isolated evidence reads."""

    evidence = cast(
        FinancialFactDecisionEvidence,
        SimpleNamespace(
            artifact_reference=SimpleNamespace(
                evidence=SimpleNamespace(request_scope=SimpleNamespace(provider_name="akshare"))
            )
        ),
    )
    artifact_root = tmp_path / "s6-artifacts"
    observed: list[tuple[int | None, Path | None]] = []

    def verify(
        _decision_evidence: FinancialFactDecisionEvidence,
        *,
        environment: str | None,
        expected_provider_id: int | None,
        artifact_storage_root: Path | None,
        expected_run_id: UUID | None,
    ) -> bool:
        assert environment is None
        assert expected_run_id is None
        observed.append((expected_provider_id, artifact_storage_root))
        return True

    monkeypatch.setattr(composition, "_verify_source_time_evidence", verify)
    provider = ProviderConfig(
        id=17,
        name="AKShare Public",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="test provider",
    )

    assert (
        verify_provider_financial_source_time_evidence(
            provider,
            evidence,
            artifact_storage_root=artifact_root,
        )
        is True
    )
    assert observed == [(17, artifact_root)]
