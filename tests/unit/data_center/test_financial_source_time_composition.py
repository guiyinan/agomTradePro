"""Composition keeps one source-time verifier across write and publication paths."""

from apps.data_center.application.interface_services import (
    make_backfill_sync_financial_use_case,
    make_sync_financial_use_case,
)
from apps.data_center.financial_source_time_composition import (
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
