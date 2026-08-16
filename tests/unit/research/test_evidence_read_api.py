"""Security and exact-selector tests for staff-only Research evidence APIs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.handlers.wsgi import WSGIRequest
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.research.domain.evidence_contracts import (
    ArtifactRef,
    ClaimKind,
    DecisionPermission,
    EvidenceEnvelope,
    EvidenceOperatorSpec,
    MethodKind,
    TrackRecordSnapshot,
    build_legacy_unverified_envelope,
)
from apps.research.interface.evidence_api_views import (
    EvidenceEnvelopeDetailView,
    EvidenceOperatorSpecDetailView,
    EvidenceTrackRecordDetailView,
)

AS_OF = datetime(2026, 8, 12, 9, tzinfo=UTC)
LATER = AS_OF + timedelta(days=30)


def _artifact() -> ArtifactRef:
    return ArtifactRef(
        owner="research",
        artifact_type="scenario_forecast",
        artifact_id="forecast-1",
        artifact_version="v1",
        content_hash="a" * 64,
    )


def _operator() -> EvidenceOperatorSpec:
    return EvidenceOperatorSpec.create(
        operator_id="operator-1",
        operator_version="v1",
        research_family="scenario",
        output_artifact_type="scenario_forecast",
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        required_input_roles=(),
        dependency_flags=frozenset(),
        maximum_permission=DecisionPermission.DISPLAY_ONLY,
        requires_track_record=False,
        activated_at=AS_OF - timedelta(days=1),
        valid_until=LATER,
    )


def _track_record() -> TrackRecordSnapshot:
    return TrackRecordSnapshot(
        snapshot_id="track-1",
        snapshot_version="v1",
        artifact=_artifact(),
        target="scenario-probability",
        horizon="21d",
        sample_policy_id="r7-oos-policy",
        sample_policy_version="v1",
        evaluated_at=AS_OF - timedelta(minutes=1),
        valid_until=LATER,
        eligible=0,
        resolved=0,
        unresolved=0,
        censored=0,
        invalidated=0,
        n_eff=Decimal(0),
        coverage=Decimal(0),
        market_regimes=(),
        primary_metric_code=None,
        primary_metric_unit=None,
        metric_direction=None,
        primary_metric_value=None,
        benchmark_metric_value=None,
        skill_delta=None,
        confidence_interval_low=None,
        confidence_interval_high=None,
        drift_detected=False,
        promotion_ref=ArtifactRef(
            owner="research",
            artifact_type="promotion_decision",
            artifact_id="promotion-1",
            artifact_version="v1",
            content_hash="b" * 64,
        ),
        outcome_refs=(),
        content_hash="",
    )


def _envelope() -> EvidenceEnvelope:
    return build_legacy_unverified_envelope(
        output_artifact=_artifact(),
        claim_kind=ClaimKind.FORECAST,
        method_kind=MethodKind.STATISTICAL,
        evaluated_at=AS_OF,
        valid_until=LATER,
    )


class _FakeFacade:
    def __init__(
        self,
        *,
        operator: EvidenceOperatorSpec | None = None,
        track: TrackRecordSnapshot | None = None,
        envelope: EvidenceEnvelope | None = None,
    ) -> None:
        self.operator = operator
        self.track = track
        self.envelope = envelope
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get_operator_spec(self, **kwargs: object) -> EvidenceOperatorSpec | None:
        self.calls.append(("operator", kwargs))
        return self.operator

    def get_track_record(self, **kwargs: object) -> TrackRecordSnapshot | None:
        self.calls.append(("track", kwargs))
        return self.track

    def get_envelope(self, **kwargs: object) -> EvidenceEnvelope | None:
        self.calls.append(("envelope", kwargs))
        return self.envelope


def _staff() -> SimpleNamespace:
    return SimpleNamespace(pk=1, is_authenticated=True, is_staff=True, is_superuser=False)


def _user() -> SimpleNamespace:
    return SimpleNamespace(pk=2, is_authenticated=True, is_staff=False, is_superuser=False)


def _operator_request(factory: APIRequestFactory, method: str = "get") -> WSGIRequest:
    request = getattr(factory, method)(
        "/api/research/evidence/operator-specs/operator-1/versions/v1/",
        {"expected_content_hash": _operator().content_hash, "as_of": AS_OF.isoformat()},
        format="json",
    )
    return request


def test_all_evidence_views_require_authenticated_staff_and_expose_no_write_handler() -> None:
    for view_type in (
        EvidenceOperatorSpecDetailView,
        EvidenceTrackRecordDetailView,
        EvidenceEnvelopeDetailView,
    ):
        assert view_type.permission_classes == [IsAuthenticated, IsAdminUser]
        assert view_type.http_method_names == ["get", "head", "options"]
        assert not any(
            method in view_type.__dict__ for method in ("post", "put", "patch", "delete")
        )


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_operator_api_rejects_every_write_method(method: str) -> None:
    factory = APIRequestFactory()
    request = _operator_request(factory, method)
    force_authenticate(request, user=_staff())

    response = EvidenceOperatorSpecDetailView.as_view()(request, "operator-1", "v1")

    assert response.status_code == 405


def test_operator_api_rejects_anonymous_and_non_staff_before_reading() -> None:
    factory = APIRequestFactory()
    facade = _FakeFacade(operator=_operator())
    with patch(
        "apps.research.interface.evidence_api_views.make_evidence_read_facade",
        return_value=facade,
    ):
        anonymous = EvidenceOperatorSpecDetailView.as_view()(
            _operator_request(factory), "operator-1", "v1"
        )
        user_request = _operator_request(factory)
        force_authenticate(user_request, user=_user())
        non_staff = EvidenceOperatorSpecDetailView.as_view()(user_request, "operator-1", "v1")

    assert anonymous.status_code in (401, 403)
    assert non_staff.status_code == 403
    assert facade.calls == []


def test_operator_api_requires_exact_hash_and_as_of_then_returns_canonical_payload() -> None:
    factory = APIRequestFactory()
    operator = _operator()
    facade = _FakeFacade(operator=operator)
    request = _operator_request(factory)
    force_authenticate(request, user=_staff())

    with patch(
        "apps.research.interface.evidence_api_views.make_evidence_read_facade",
        return_value=facade,
    ):
        response = EvidenceOperatorSpecDetailView.as_view()(request, "operator-1", "v1")

    assert response.status_code == 200
    assert response.data["content_hash"] == operator.content_hash
    assert response.data["claim_kind"] == "forecast"
    assert facade.calls == [
        (
            "operator",
            {
                "operator_id": "operator-1",
                "operator_version": "v1",
                "expected_content_hash": operator.content_hash,
                "as_of": AS_OF,
            },
        )
    ]


@pytest.mark.parametrize(
    "query",
    [
        {"as_of": AS_OF.isoformat()},
        {"expected_content_hash": "a" * 64},
        {"expected_content_hash": "A" * 64, "as_of": AS_OF.isoformat()},
        {"expected_content_hash": "a" * 64, "as_of": "not-a-time"},
        {
            "expected_content_hash": "a" * 64,
            "as_of": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    ],
)
def test_operator_api_rejects_missing_or_invalid_exact_selector(query: dict[str, str]) -> None:
    factory = APIRequestFactory()
    request = factory.get("/api/research/evidence/operator-specs/operator-1/versions/v1/", query)
    force_authenticate(request, user=_staff())

    response = EvidenceOperatorSpecDetailView.as_view()(request, "operator-1", "v1")

    assert response.status_code == 400


def test_exact_lookup_miss_is_non_enumerating_not_found() -> None:
    factory = APIRequestFactory()
    request = _operator_request(factory)
    force_authenticate(request, user=_staff())
    with patch(
        "apps.research.interface.evidence_api_views.make_evidence_read_facade",
        return_value=_FakeFacade(),
    ):
        response = EvidenceOperatorSpecDetailView.as_view()(request, "operator-1", "v1")

    assert response.status_code == 404
    assert response.data == {
        "error": "Exact evidence was not found at the requested cutoff.",
        "code": "API_ERROR",
    }


def test_track_record_api_preserves_decimal_text_and_pit_selector() -> None:
    factory = APIRequestFactory()
    track = _track_record()
    facade = _FakeFacade(track=track)
    request = factory.get(
        "/api/research/evidence/track-records/track-1/versions/v1/",
        {"expected_content_hash": track.content_hash, "as_of": AS_OF.isoformat()},
    )
    force_authenticate(request, user=_staff())

    with patch(
        "apps.research.interface.evidence_api_views.make_evidence_read_facade",
        return_value=facade,
    ):
        response = EvidenceTrackRecordDetailView.as_view()(request, "track-1", "v1")

    assert response.status_code == 200
    assert response.data["n_eff"] == "0"
    assert response.data["coverage"] == "0"
    assert response.data["content_hash"] == track.content_hash
    assert facade.calls[0][1]["as_of"] == AS_OF


def test_envelope_api_requires_output_owner_in_path_and_passes_it_to_application() -> None:
    factory = APIRequestFactory()
    envelope = _envelope()
    facade = _FakeFacade(envelope=envelope)
    request = factory.get(
        "/api/research/evidence/envelopes/research/scenario_forecast/" "forecast-1/versions/v1/",
        {"expected_content_hash": envelope.content_hash, "as_of": AS_OF.isoformat()},
    )
    force_authenticate(request, user=_staff())

    with patch(
        "apps.research.interface.evidence_api_views.make_evidence_read_facade",
        return_value=facade,
    ):
        response = EvidenceEnvelopeDetailView.as_view()(
            request,
            "research",
            "scenario_forecast",
            "forecast-1",
            "v1",
        )

    assert response.status_code == 200
    assert response.data["must_not_use_for_decision"] is True
    assert response.data["must_not_execute"] is True
    assert facade.calls[0][1]["output_owner"] == "research"
    assert facade.calls[0][1]["expected_content_hash"] == envelope.content_hash


def test_envelope_route_contains_owner_and_all_exact_identity_components() -> None:
    source = Path("apps/research/interface/api_urls.py").read_text(encoding="utf-8")

    assert '"evidence/envelopes/<str:output_owner>/<str:output_artifact_type>/"' in source
    assert '"<str:output_artifact_id>/versions/<str:output_artifact_version>/"' in source
