"""Composition keeps one source-time verifier across write and publication paths."""

from types import SimpleNamespace
from typing import cast

import pytest

from apps.data_center.application.financial_source_time_verifier import (
    FinancialSourceTimeContractMatcher,
)
from apps.data_center.application.interface_services import (
    make_backfill_sync_financial_use_case,
    make_sync_financial_use_case,
)
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
