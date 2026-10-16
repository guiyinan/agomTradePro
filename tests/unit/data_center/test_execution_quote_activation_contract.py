"""Closed activation request shapes for execution and full-market quotes."""

from __future__ import annotations

from contextlib import contextmanager
from uuid import uuid4

import pytest

from apps.data_center.application.publication_activation import (
    PublicationActivationError,
    PublicationActivationGroupCandidate,
    PublicationActivationGroupRequest,
)
from apps.data_center.infrastructure.publication_group_activation_repository import (
    DjangoPublicationActivationGroupRepository,
)


def _candidate(dataset_key: str, publication_key: str) -> PublicationActivationGroupCandidate:
    """Build one minimally valid candidate identity for request-shape checks."""

    return PublicationActivationGroupCandidate(
        dataset_key=dataset_key,
        publication_key=publication_key,
        candidate_publication_id=str(uuid4()),
        candidate_publication_hash="a" * 64,
    )


def test_request_accepts_exact_single_execution_quote_candidate() -> None:
    """The only singleton activation is the dedicated execution quote scope."""

    candidate = _candidate("equity.quote.snapshot", "execution")

    request = PublicationActivationGroupRequest(
        activation_id="execution-quote-activation",
        candidates=(candidate,),
    )

    assert request.candidates == (candidate,)


@pytest.mark.parametrize("tampered_field", ["publication_key", "candidate_publication_hash"])
def test_group_repository_revalidates_frozen_request_before_authority_fence(
    tampered_field: str,
) -> None:
    """Mutating frozen transport objects cannot bypass the request constructor checks."""

    candidate = _candidate("equity.quote.snapshot", "execution")
    request = PublicationActivationGroupRequest(
        activation_id="execution-quote-activation",
        candidates=(candidate,),
    )
    if tampered_field == "publication_key":
        object.__setattr__(candidate, "publication_key", "current")
    else:
        object.__setattr__(candidate, "candidate_publication_hash", "bad")

    class _AuditWriter:
        database_alias = "default"

        def append_manifest_required(self, **_kwargs: object) -> None:
            """Satisfy the repository's writer capability check."""

    class _Fence:
        entered = False

        @contextmanager
        def fence_complete(self, _proof: object):
            """Track whether validation opened authority scope."""

            self.entered = True
            yield object()

    fence = _Fence()
    with pytest.raises(PublicationActivationError):
        DjangoPublicationActivationGroupRepository().activate_candidate_group(
            request,
            audit_writer=_AuditWriter(),
            authority_fence=fence,
            authority_proof=object(),
        )

    assert fence.entered is False


@pytest.mark.parametrize(
    "candidates",
    [
        (_candidate("equity.quote.snapshot", "current"),),
        (_candidate("equity.price.bar", "execution"),),
        (
            _candidate("equity.quote.snapshot", "execution"),
            _candidate("equity.price.bar", "current"),
        ),
        (
            _candidate("equity.quote.snapshot", "current"),
            _candidate("equity.price.bar", "current"),
        ),
        (
            _candidate("equity.quote.snapshot", "execution"),
            _candidate("equity.quote.snapshot", "execution"),
        ),
    ],
)
def test_request_rejects_other_singleton_or_mixed_execution_shapes(
    candidates: tuple[PublicationActivationGroupCandidate, ...],
) -> None:
    """No other one/two-item or mixed-key activation can enter the shared UOW."""

    with pytest.raises(PublicationActivationError):
        PublicationActivationGroupRequest(
            activation_id="invalid-execution-quote-activation",
            candidates=candidates,
        )


def test_request_keeps_exact_three_current_market_shape() -> None:
    """The existing quote, price and valuation group remains unchanged."""

    candidates = (
        _candidate("equity.price.bar", "current"),
        _candidate("equity.quote.snapshot", "current"),
        _candidate("equity.valuation.fact", "current"),
    )

    request = PublicationActivationGroupRequest(
        activation_id="full-market-activation",
        candidates=candidates,
    )

    assert tuple(candidate.publication_key for candidate in request.candidates) == (
        "current",
        "current",
        "current",
    )
