"""Audited routing and dependency composition for share-action revisions."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest

from apps.simulated_trading import audited_corporate_action_posting_composition as audited
from apps.simulated_trading.application.corporate_action_posting import (
    AuditedCorporateActionPostingRepositoryPort,
    AuditedCorporateActionPostingRepositoryProtocol,
    CorporateActionPostingBlockedError,
    CorporateActionPostingReceipt,
    CorporateActionSourceQualificationVerifierProtocol,
    HistoricalAccountOwnershipVerifierProtocol,
    PostCorporateActionStageUseCase,
)
from apps.simulated_trading.audited_share_corporate_action_posting_composition import (
    build_audited_rights_no_effect_use_case,
    build_audited_share_revision_use_case,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionStage,
    CorporateActionStageRequest,
)
from apps.simulated_trading.domain.corporate_action_share_revision import (
    plan_corporate_action_share_revision,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_repository import (
    DjangoCorporateActionPostingRepository,
)
from tests.unit.simulated_trading.test_corporate_action_posting import _request as _cash_request
from tests.unit.simulated_trading.test_corporate_action_share_revision import (
    _correction_requests,
    _rights_no_effect_request,
    _share_request,
)


def test_generic_audited_dispatch_delegates_cash_to_unchanged_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cash request normalization and receipt restoration use their original functions."""

    request = _cash_request()
    requests = (request,)
    receipts = (
        CorporateActionPostingReceipt(
            entry_id=11,
            account_revision=11,
            stage_key=request.stage_key,
            request_payload_sha256=request.payload_sha256,
            replayed=False,
        ),
    )
    calls: list[str] = []

    def prepare_cash(
        values: tuple[CorporateActionStageRequest, ...],
    ) -> tuple[tuple[CorporateActionStageRequest, ...], CorporateActionStageRequest]:
        calls.append("prepare")
        return values, values[0]

    def restore_cash(
        values: tuple[CorporateActionStageRequest, ...],
        results: tuple[CorporateActionPostingReceipt, ...],
    ) -> tuple[CorporateActionPostingReceipt, ...]:
        calls.append("restore")
        assert values == requests and results == receipts
        return results

    monkeypatch.setattr(audited, "_prepare_cash_revision_requests", prepare_cash)
    monkeypatch.setattr(audited, "_restore_cash_revision_receipt_order", restore_cash)

    assert audited._prepare_audited_revision_requests(requests) == (requests, request)
    assert audited._restore_audited_revision_receipt_order(requests, receipts) == receipts
    assert calls == ["prepare", "restore"]


def test_generic_audited_dispatch_normalizes_share_batches_and_restores_caller_order() -> None:
    """The audited adapter uses the Domain plan for writes, gate anchor and replay order."""

    submitted = _correction_requests()
    plan = plan_corporate_action_share_revision(submitted)
    ordered, anchor = audited._prepare_audited_revision_requests(submitted)
    receipts = tuple(
        CorporateActionPostingReceipt(
            entry_id=index,
            account_revision=index,
            stage_key=request.stage_key,
            request_payload_sha256=request.payload_sha256,
            replayed=index % 2 == 0,
        )
        for index, request in enumerate(ordered, start=1)
    )
    restored = audited._restore_audited_revision_receipt_order(submitted, receipts)

    assert ordered == plan.requests
    assert anchor is plan.gate_anchor
    assert tuple(receipt.stage_key for receipt in restored) == tuple(
        request.stage_key for request in submitted
    )


def test_exact_replay_verifier_accepts_only_the_planner_ordered_share_batch() -> None:
    """Replay timestamp bypass is bound to the same canonical tuple and anchor."""

    submitted = _correction_requests()
    canonical, anchor = audited._prepare_audited_revision_requests(submitted)
    verifier = audited._DjangoCorporateActionReplayTimestampVerifier(
        coordinator=SimpleNamespace(database_alias="default"),
        posting=DjangoCorporateActionPostingRepository(using="default"),
        requests=canonical,
        representative=anchor,
        using="default",
    )
    assert verifier.requests == canonical
    with pytest.raises(ValueError, match="canonical tuple"):
        audited._DjangoCorporateActionReplayTimestampVerifier(
            coordinator=SimpleNamespace(database_alias="default"),
            posting=DjangoCorporateActionPostingRepository(using="default"),
            requests=submitted,
            representative=anchor,
            using="default",
        )


@pytest.mark.parametrize(
    "builder,request_value",
    [
        (
            build_audited_share_revision_use_case,
            _share_request(CorporateActionStage.SHARE_ENTITLEMENT),
        ),
        (build_audited_rights_no_effect_use_case, _rights_no_effect_request()),
    ],
)
def test_share_builders_reuse_same_alias_audited_factory_and_proof_ports(
    builder: Callable[..., PostCorporateActionStageUseCase],
    request_value: CorporateActionStageRequest,
) -> None:
    """Share and no-effect rights composition requires injected proof and Audit ports."""

    captured: dict[str, object] = {}

    class _Repository:
        def get_database_alias(self) -> str:
            return "default"

        def post_revision_with_audit(
            self, requests: tuple[CorporateActionStageRequest, ...]
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            captured["requests"] = requests
            return ()

    class _Factory:
        def build_posting_repository(
            self,
            *,
            source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
            ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
            tax_basis_verifier: object | None,
            using: str,
        ) -> AuditedCorporateActionPostingRepositoryPort:
            captured.update(
                source_qualifier=source_qualifier,
                ownership_verifier=ownership_verifier,
                tax_basis_verifier=tax_basis_verifier,
                using=using,
            )
            return cast(AuditedCorporateActionPostingRepositoryPort, _Repository())

    class _SourceQualifier:
        def verify_source(self, value: CorporateActionStageRequest) -> bool:
            del value
            return True

    class _OwnershipVerifier:
        def verify_ownership(self, value: CorporateActionStageRequest) -> bool:
            del value
            return True

    source_qualifier = _SourceQualifier()
    ownership_verifier = _OwnershipVerifier()
    use_case = builder(
        audited_repository=cast(AuditedCorporateActionPostingRepositoryProtocol, _Factory()),
        source_qualifier=cast(CorporateActionSourceQualificationVerifierProtocol, source_qualifier),
        ownership_verifier=cast(HistoricalAccountOwnershipVerifierProtocol, ownership_verifier),
    )
    assert type(use_case) is PostCorporateActionStageUseCase
    use_case.execute((request_value,))
    assert captured["source_qualifier"] is source_qualifier
    assert captured["ownership_verifier"] is ownership_verifier
    assert captured["tax_basis_verifier"] is None
    assert captured["using"] == "default"
    assert captured["requests"] == (request_value,)


def test_share_builder_rejects_missing_proof_ports() -> None:
    """No builder can silently substitute the existing cash-only proof composition."""

    with pytest.raises(CorporateActionPostingBlockedError):
        build_audited_share_revision_use_case(
            audited_repository=cast(AuditedCorporateActionPostingRepositoryProtocol, object()),
            source_qualifier=cast(CorporateActionSourceQualificationVerifierProtocol, None),
            ownership_verifier=cast(HistoricalAccountOwnershipVerifierProtocol, object()),
        )


@pytest.mark.parametrize(
    "builder,request_value",
    [
        (build_audited_share_revision_use_case, _rights_no_effect_request()),
        (
            build_audited_rights_no_effect_use_case,
            _share_request(CorporateActionStage.SHARE_ENTITLEMENT),
        ),
    ],
)
def test_action_builder_rejects_other_family_before_audited_write(
    builder: Callable[..., PostCorporateActionStageUseCase],
    request_value: CorporateActionStageRequest,
) -> None:
    """Share and rights builders retain their exact family-specific stage boundary."""

    post_calls: list[tuple[CorporateActionStageRequest, ...]] = []

    class _Repository:
        def get_database_alias(self) -> str:
            return "default"

        def post_revision_with_audit(
            self, requests: tuple[CorporateActionStageRequest, ...]
        ) -> tuple[CorporateActionPostingReceipt, ...]:
            post_calls.append(requests)
            return ()

    class _Factory:
        def build_posting_repository(
            self,
            *,
            source_qualifier: CorporateActionSourceQualificationVerifierProtocol,
            ownership_verifier: HistoricalAccountOwnershipVerifierProtocol,
            tax_basis_verifier: object | None,
            using: str,
        ) -> AuditedCorporateActionPostingRepositoryPort:
            del source_qualifier, ownership_verifier, tax_basis_verifier
            assert using == "default"
            return cast(AuditedCorporateActionPostingRepositoryPort, _Repository())

    class _SourceQualifier:
        def verify_source(self, value: CorporateActionStageRequest) -> bool:
            del value
            return True

    class _OwnershipVerifier:
        def verify_ownership(self, value: CorporateActionStageRequest) -> bool:
            del value
            return True

    use_case = builder(
        audited_repository=cast(AuditedCorporateActionPostingRepositoryProtocol, _Factory()),
        source_qualifier=cast(
            CorporateActionSourceQualificationVerifierProtocol, _SourceQualifier()
        ),
        ownership_verifier=cast(HistoricalAccountOwnershipVerifierProtocol, _OwnershipVerifier()),
    )
    with pytest.raises(CorporateActionPostingBlockedError) as blocked:
        use_case.execute((request_value,))
    assert blocked.value.code == "CORPORATE_ACTION_STAGE_UNSUPPORTED"
    assert post_calls == []
