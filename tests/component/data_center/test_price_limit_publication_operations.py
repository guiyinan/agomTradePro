"""Real session, persistence, history and rollback journey for reference price limits."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection, connections
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.urls import include, path
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.application.system_audit_event_outbox import SystemAuditEventOutboxUnavailable
from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.audit.infrastructure.system_audit_outbox_repository import (
    DjangoSystemAuditOutboxRepository,
)
from apps.audit.infrastructure.system_audit_repository import DjangoSystemAuditEventRepository
from apps.data_center.application.publication_activation import (
    PublicationActivationAuditWriter,
    PublicationActivationAuthorityFence,
    PublicationActivationError,
    PublicationActivationRequest,
)
from apps.data_center.domain.control_plane import PublicationRollback, PublicationState
from apps.data_center.infrastructure.catalog_models import DatasetPublicationPolicyModel
from apps.data_center.infrastructure.catalog_runtime_repositories import DatasetContractRepository
from apps.data_center.infrastructure.control_plane_repositories import (
    CanonicalPublicationRepository,
)
from apps.data_center.infrastructure.price_limit_snapshot_repository import (
    DjangoPriceLimitSnapshotRepository,
)
from apps.data_center.infrastructure.publication_activation_repository import (
    DjangoPublicationActivationRepository,
)
from apps.data_center.infrastructure.publication_policy_repository import (
    PublicationPolicyRepository,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
    CanonicalPublicationPointerModel,
    CoverageSnapshotModel,
    PublicationMemberModel,
    PublicationRollbackModel,
)
from tests.component.data_center.test_price_limit_snapshot_repository import _candidate
from tests.support.native_postgres_database import assert_native_postgres_test_database
from tests.unit.data_center.test_formal_price_limit_publication import _contract, _policy

pytestmark = pytest.mark.django_db(transaction=True)
_BASE = "/api/data-center/price-limits/publication/"
_SCOPE = {
    "provider_id": 7,
    "provider_name": "tushare",
    "asset_code": "600000.SH",
    "effective_trade_date": "2026-10-28",
}


def csrf_cookie(request: HttpRequest) -> JsonResponse:
    """Obtain a real CSRF cookie through Django middleware."""
    return JsonResponse({"csrf": get_token(request)})


urlpatterns = [
    path("_test/csrf/", csrf_cookie),
    path("api/data-center/", include("apps.data_center.interface.api_urls")),
]


@pytest.fixture
def management_client(settings: Any, monkeypatch: pytest.MonkeyPatch) -> tuple[APIClient, Any]:
    settings.ROOT_URLCONF = __name__
    settings.SECURE_SSL_REDIRECT = False
    settings.SESSION_ENGINE = "django.contrib.sessions.backends.db"
    monkeypatch.setenv("AGOMTRADEPRO_DISABLE_USER_PROVISIONING_SIGNALS", "1")
    user = get_user_model().objects.create_user(
        username="limit-manager", password="test-only-reference-password"
    )
    # This row must come from actual migrated Meta permissions, not a fixture
    # fallback that hides an omitted migration/post_migrate registration.
    permission = Permission.objects.get(
        content_type__app_label="data_center",
        content_type__model="pricelimitsnapshotfactmodel",
        codename="publish_price_limit",
    )
    user.user_permissions.add(permission)
    client = APIClient(enforce_csrf_checks=True)
    assert client.login(username=user.username, password="test-only-reference-password")
    assert client.get("/_test/csrf/").status_code == 200
    DatasetContractRepository().save(_contract())
    PublicationPolicyRepository().save(_policy())
    return client, user


def _source(*, upper: str = "11.456700", asset: str = "600000.SH") -> str:
    candidate, _ = _candidate(
        upper_price=upper, asset_code=asset, response_completed_at=timezone.now()
    )
    return DjangoPriceLimitSnapshotRepository().save(candidate).snapshot_id


def _post(client: APIClient, endpoint: str, body: dict[str, object], *, csrf: bool = True) -> Any:
    headers = {"HTTP_X_CSRFTOKEN": client.cookies["csrftoken"].value} if csrf else {}
    response = client.post(_BASE + endpoint + "/", body, format="json", **headers)
    assert response["Content-Type"].startswith("application/json")
    return response


def _preview(client: APIClient, snapshot_id: str) -> Any:
    response = _post(client, "preview", {**_SCOPE, "action": "publish", "snapshot_id": snapshot_id})
    assert response.status_code == 200, response.data
    return response


def _publish(client: APIClient, snapshot_id: str) -> Any:
    preview = _preview(client, snapshot_id)
    response = _post(client, "confirm", {"confirmation_token": preview.data["confirmation_token"]})
    assert response.status_code == 200, response.data
    return response


def _price_limit_lifecycle_state() -> tuple[tuple[tuple[str, object], ...], ...]:
    """Snapshot exact persisted rows touched by ordinary publication writers."""
    models = (
        CanonicalPublicationModel,
        PublicationMemberModel,
        CoverageSnapshotModel,
        CanonicalPublicationPointerModel,
        PublicationRollbackModel,
        SystemAuditEventModel,
        SystemAuditOutboxModel,
    )
    return tuple(
        tuple(tuple(sorted(row.items())) for row in model._default_manager.order_by("pk").values())
        for model in models
    )


def test_real_session_publish_replay_forward_history_and_rollback(
    management_client: tuple[APIClient, Any],
    record_testsuite_property: Any,
) -> None:
    client, _ = management_client
    record_testsuite_property("publication_database_vendor", connection.vendor)
    record_testsuite_property("publication_database_name", str(connection.settings_dict["NAME"]))
    if connection.vendor == "postgresql":
        record_testsuite_property(
            "publication_actual_database", assert_native_postgres_test_database()
        )
    first_source = _source()
    preview = _preview(client, first_source)
    assert CanonicalPublicationModel.objects.count() == 0
    assert CanonicalPublicationPointerModel.objects.count() == 0
    request = {"confirmation_token": preview.data["confirmation_token"]}
    first = _post(client, "confirm", request)
    assert first.status_code == 200, first.data
    assert first.data["must_not_use_for_decision"] is True
    assert first.data["must_not_execute"] is True
    assert first.data["snapshot"]["currency"] is None
    count = SystemAuditEventModel.objects.count()
    outbox_count = SystemAuditOutboxModel.objects.count()
    replay = _post(client, "confirm", request)
    assert replay.status_code == 200, replay.data
    assert replay.data["replayed"] is True
    assert SystemAuditEventModel.objects.count() == count
    assert SystemAuditOutboxModel.objects.count() == outbox_count
    second = _publish(client, _source(upper="11.800000"))
    assert first.data["publication_id"] != second.data["publication_id"]
    current = client.get(_BASE + "current/", _SCOPE)
    assert current.status_code == 200, current.data
    assert current["Content-Type"].startswith("application/json")
    assert current.data["publication_id"] == second.data["publication_id"]
    historical = client.get(_BASE + "history/", {**_SCOPE, "as_of": first.data["visible_from"]})
    assert historical.status_code == 200, historical.data
    assert historical["Content-Type"].startswith("application/json")
    assert historical.data["publication_id"] == first.data["publication_id"]
    assert historical.data["visible_from"] == first.data["visible_from"]
    rollback_preview = _post(
        client,
        "preview",
        {
            **_SCOPE,
            "action": "rollback",
            "target_publication_id": first.data["publication_id"],
            "reason": "Source correction reviewed",
        },
    )
    assert rollback_preview.status_code == 200, rollback_preview.data
    rolled_back = _post(
        client, "rollback", {"confirmation_token": rollback_preview.data["confirmation_token"]}
    )
    assert rolled_back.status_code == 200, rolled_back.data
    assert rolled_back.data["publication_id"] == first.data["publication_id"]
    assert rolled_back.data["first_published_at"] == first.data["first_published_at"]
    assert rolled_back.data["visible_from"] > second.data["visible_from"]
    middle = client.get(_BASE + "history/", {**_SCOPE, "as_of": second.data["visible_from"]})
    assert middle.status_code == 200, middle.data
    assert middle.data["publication_id"] == second.data["publication_id"]
    exact = client.get(_BASE + second.data["publication_id"] + "/", _SCOPE)
    assert exact.status_code == 200, exact.data
    assert exact["Content-Type"].startswith("application/json")
    assert exact.data["lookup_basis"] == "exact_identity"
    assert exact.data["visible_from"] is None
    assert exact.data["first_published_at"] == second.data["first_published_at"]
    pointer = CanonicalPublicationPointerModel.objects.get()
    assert (
        CanonicalPublicationRepository().get_current("equity.price.limit", pointer.publication_key)
        is None
    )
    assert (
        CanonicalPublicationRepository().get_as_of(
            "equity.price.limit",
            pointer.publication_key,
            datetime.fromisoformat(second.data["visible_from"]),
        )
        is None
    )
    assert PublicationRollbackModel.objects.count() == 1
    assert PublicationMemberModel.objects.count() == 2
    assert all(
        CanonicalPublicationModel.objects.values_list("must_not_use_for_decision", flat=True)
    )
    _publish(client, _source(upper="12.300000"))
    assert PublicationRollbackModel.objects.all().delete()[0] == 1
    broken = client.get(_BASE + "current/", _SCOPE)
    assert broken.status_code == 422, broken.data
    assert broken.data["code"] == "PRICE_LIMIT_PUBLICATION_EVENT_PREVIOUS_MISMATCH"


def test_preview_is_scope_bound_and_confirmation_requires_real_csrf(
    management_client: tuple[APIClient, Any],
) -> None:
    client, _ = management_client
    foreign = _source(asset="600001.SH")
    wrong = _post(client, "preview", {**_SCOPE, "action": "publish", "snapshot_id": foreign})
    assert wrong.status_code == 409, wrong.data
    assert wrong.data["code"] == "PRICE_LIMIT_SOURCE_SCOPE_MISMATCH"
    source = _source()
    preview = _preview(client, source)
    denied = _post(
        client, "confirm", {"confirmation_token": preview.data["confirmation_token"]}, csrf=False
    )
    assert denied.status_code == 403
    assert CanonicalPublicationModel.objects.count() == 0
    tampered = _post(
        client, "confirm", {"confirmation_token": "x" + preview.data["confirmation_token"]}
    )
    assert tampered.status_code == 400


def test_revoked_permission_blocks_pending_confirmation_and_history(
    management_client: tuple[APIClient, Any],
) -> None:
    client, user = management_client
    preview = _preview(client, _source())
    user.user_permissions.clear()
    result = _post(client, "confirm", {"confirmation_token": preview.data["confirmation_token"]})
    assert result.status_code == 403, result.data
    assert client.get(_BASE + "current/", _SCOPE).status_code == 403
    assert CanonicalPublicationModel.objects.count() == 0


def test_late_confirmation_cannot_overwrite_another_verified_publication(
    management_client: tuple[APIClient, Any],
) -> None:
    client, _ = management_client
    stale = _preview(client, _source())
    _publish(client, _source(upper="12.000000"))
    response = _post(client, "confirm", {"confirmation_token": stale.data["confirmation_token"]})
    assert response.status_code == 409, response.data
    assert response.data["code"] == "PRICE_LIMIT_POINTER_CAS_MISMATCH"
    assert CanonicalPublicationModel.objects.count() == 1


def test_corrupt_member_denies_current_and_history_without_fallback(
    management_client: tuple[APIClient, Any],
) -> None:
    client, _ = management_client
    published = _publish(client, _source())
    assert PublicationMemberModel.objects.update(fact_content_hash="0" * 64) == 1
    current = client.get(_BASE + "current/", _SCOPE)
    history = client.get(_BASE + "history/", {**_SCOPE, "as_of": published.data["visible_from"]})
    assert current.status_code == 409, current.data
    assert history.status_code == 409, history.data
    assert current.data["code"] == "PRICE_LIMIT_PUBLICATION_EVIDENCE_CORRUPT"


def test_scope_day_is_not_inferred_from_a_different_current_pointer(
    management_client: tuple[APIClient, Any],
) -> None:
    client, _ = management_client
    _publish(client, _source())
    other = {**_SCOPE, "effective_trade_date": date(2026, 10, 27).isoformat()}
    response = client.get(_BASE + "current/", other)
    assert response.status_code == 404, response.data
    assert response.data["must_not_execute"] is True


@pytest.mark.parametrize("phase", ["event", "outbox"])
def test_audit_failure_rolls_back_publication_members_and_pointer(
    management_client: tuple[APIClient, Any],
    phase: str,
) -> None:
    client, _ = management_client
    preview = _preview(client, _source())
    before = (SystemAuditEventModel.objects.count(), SystemAuditOutboxModel.objects.count())
    owner, method = (
        (DjangoSystemAuditEventRepository, "append_price_limit_targeted")
        if phase == "event"
        else (DjangoSystemAuditOutboxRepository, "enqueue_targeted")
    )
    with patch.object(
        owner, method, side_effect=SystemAuditEventOutboxUnavailable("injected storage failure")
    ):
        response = _post(
            client, "confirm", {"confirmation_token": preview.data["confirmation_token"]}
        )
    assert response.status_code == 503, response.data
    assert CanonicalPublicationModel.objects.count() == 0
    assert CanonicalPublicationPointerModel.objects.count() == 0
    assert PublicationMemberModel.objects.count() == 0
    assert PublicationRollbackModel.objects.count() == 0
    assert (SystemAuditEventModel.objects.count(), SystemAuditOutboxModel.objects.count()) == before


def test_missing_outbox_is_never_repaired_by_read_or_confirmation_replay(
    management_client: tuple[APIClient, Any],
) -> None:
    client, _ = management_client
    preview = _preview(client, _source())
    request = {"confirmation_token": preview.data["confirmation_token"]}
    committed = _post(client, "confirm", request)
    assert committed.status_code == 200, committed.data
    row = SystemAuditOutboxModel.objects.get()
    table = connection.ops.quote_name(SystemAuditOutboxModel._meta.db_table)
    field = SystemAuditOutboxModel._meta.get_field("outbox_id")
    identity = field.get_db_prep_value(row.outbox_id, connection)
    with connection.cursor() as cursor:
        cursor.execute(f"DELETE FROM {table} WHERE outbox_id=%s", [identity])
        assert cursor.rowcount == 1
    for response in (client.get(_BASE + "current/", _SCOPE), _post(client, "confirm", request)):
        assert response.status_code == 500, response.data
        assert response.data["code"] == "PRICE_LIMIT_PUBLICATION_AUDIT_CORRUPTION"
    assert SystemAuditOutboxModel.objects.count() == 0
    assert SystemAuditEventModel.objects.count() == 1


def test_disabled_current_catalog_blocks_all_management_reads_and_pending_writes(
    management_client: tuple[APIClient, Any],
) -> None:
    client, _ = management_client
    published = _publish(client, _source())
    assert (
        DatasetPublicationPolicyModel.objects.filter(dataset_key="equity.price.limit").update(
            active=False
        )
        == 1
    )
    responses = (
        client.get(_BASE + "current/", _SCOPE),
        client.get(_BASE + "history/", {**_SCOPE, "as_of": published.data["visible_from"]}),
        client.get(_BASE + published.data["publication_id"] + "/", _SCOPE),
    )
    for response in responses:
        assert response.status_code == 409, response.data
        assert response.data["code"] == "PRICE_LIMIT_CATALOG_UNAVAILABLE"


def test_ordinary_publication_writers_cannot_adopt_or_replay_price_limit_lineage(
    management_client: tuple[APIClient, Any],
) -> None:
    """Keep real reference facts and Audit pairs outside ordinary lifecycle writes."""
    client, _ = management_client
    first = _publish(client, _source())
    second = _publish(client, _source(upper="11.800000"))
    rollback_preview = _post(
        client,
        "preview",
        {
            **_SCOPE,
            "action": "rollback",
            "target_publication_id": first.data["publication_id"],
            "reason": "Restore reviewed reference",
        },
    )
    assert rollback_preview.status_code == 200, rollback_preview.data
    rollback_response = _post(
        client,
        "rollback",
        {"confirmation_token": rollback_preview.data["confirmation_token"]},
    )
    assert rollback_response.status_code == 200, rollback_response.data

    reference = CanonicalPublicationModel._default_manager.get(
        publication_id=first.data["publication_id"]
    ).to_domain()
    members = tuple(
        model.to_domain()
        for model in PublicationMemberModel._default_manager.filter(
            publication_id=reference.publication_id
        ).order_by("natural_key")
    )
    state_before = _price_limit_lifecycle_state()
    ordinary_repository = CanonicalPublicationRepository()

    with pytest.raises(ValueError, match="dedicated reference writer"):
        ordinary_repository.save(reference)

    # A caller that relabels the frozen reference row as an ordinary eligible
    # publication must still be stopped at the repository boundary.
    ordinary_eligible = replace(
        reference,
        state=PublicationState.PUBLISHED,
        policy_version="ordinary-spoof-v1",
        must_not_use_for_decision=False,
        blocked_reason="",
    )
    with pytest.raises(ValueError, match="dedicated reference writer"):
        ordinary_repository.save(ordinary_eligible)

    ordinary_candidate = replace(
        reference,
        state=PublicationState.CANDIDATE,
        policy_version="ordinary-spoof-v1",
    )
    activation_repository = DjangoPublicationActivationRepository()
    with pytest.raises(PublicationActivationError, match="dedicated reference writer"):
        activation_repository.stage_candidate_with_members(ordinary_candidate, members)

    # The dedicated dataset guard runs before activation touches its required
    # audit writer or authority fence, so this probe creates no synthetic Audit.
    activation_request = cast(
        PublicationActivationRequest,
        SimpleNamespace(dataset_key="equity.price.limit"),
    )
    with pytest.raises(PublicationActivationError, match="dedicated reference writer"):
        activation_repository.activate_candidate(
            activation_request,
            audit_writer=cast(PublicationActivationAuditWriter, object()),
            authority_fence=cast(PublicationActivationAuthorityFence, object()),
            authority_proof=object(),
        )

    rollback_repository = CanonicalPublicationRepository()
    existing_rollback = PublicationRollbackModel._default_manager.get().to_domain()
    with pytest.raises(ValueError, match="rollback replay no longer matches current state"):
        rollback_repository.rollback(existing_rollback)

    unrecorded_rollback = PublicationRollback(
        target_publication_id=first.data["publication_id"],
        previous_publication_id=second.data["publication_id"],
        reason="Attempt ordinary rollback",
        operator="django-user:7",
        observed_at=timezone.now() + timedelta(seconds=1),
        rollback_id=str(uuid4()),
    )
    with pytest.raises(ValueError, match="dedicated reference writer"):
        rollback_repository.rollback(unrecorded_rollback)

    assert _price_limit_lifecycle_state() == state_before


def test_postgres_two_real_sessions_cannot_both_win_an_absent_pointer(
    management_client: tuple[APIClient, Any],
) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("Two-connection pointer race requires native PostgreSQL")
    assert_native_postgres_test_database()
    first_client, user = management_client
    peer = get_user_model().objects.create_user(
        username="limit-peer", password="test-only-reference-password"
    )
    peer.user_permissions.add(*list(user.user_permissions.all()))
    second_client = APIClient(enforce_csrf_checks=True)
    assert second_client.login(username=peer.username, password="test-only-reference-password")
    assert second_client.get("/_test/csrf/").status_code == 200
    first = _preview(first_client, _source())
    second = _preview(second_client, _source(upper="12.200000"))
    barrier = Barrier(2, timeout=20)

    def confirm(client: APIClient, token: str) -> int:
        connections.close_all()
        try:
            barrier.wait()
            response = _post(client, "confirm", {"confirmation_token": token})
            return int(response.status_code)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [
            pool.submit(confirm, first_client, first.data["confirmation_token"]),
            pool.submit(confirm, second_client, second.data["confirmation_token"]),
        ]
        statuses = [attempt.result(timeout=40) for attempt in attempts]
    assert sorted(statuses) == [200, 409]
    assert CanonicalPublicationPointerModel.objects.count() == 1
    assert CanonicalPublicationModel.objects.count() == 1
    assert SystemAuditEventModel.objects.count() == 1
    assert SystemAuditOutboxModel.objects.count() == 1
