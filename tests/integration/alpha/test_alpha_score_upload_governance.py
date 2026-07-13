"""Governance contracts for Alpha score-cache preview and commit APIs."""

from copy import deepcopy
from datetime import date, timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient


def _payload(**overrides):
    today = date.today()
    payload = {
        "universe_id": "csi300",
        "asof_date": (today - timedelta(days=1)).isoformat(),
        "intended_trade_date": today.isoformat(),
        "model_id": "governed-model",
        "model_artifact_hash": "artifact-1",
        "scope": "user",
        "scores": [
            {
                "code": "000001.sz",
                "score": 0.9,
                "rank": 1,
                "factors": {"momentum": 0.8},
                "confidence": 0.95,
                "source": "local_qlib",
            }
        ],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def upload_clients(db):
    user_model = get_user_model()
    user = user_model.objects.create_user(username="alpha-upload-user", password="unused")
    staff = user_model.objects.create_user(
        username="alpha-upload-staff", password="unused", is_staff=True
    )
    user_client = APIClient()
    user_client.force_authenticate(user=user)
    staff_client = APIClient()
    staff_client.force_authenticate(user=staff)
    return user, user_client, staff_client


@pytest.mark.django_db
def test_preview_is_write_free_and_reports_exact_create_target(upload_clients):
    from apps.alpha.infrastructure.models import AlphaScoreCacheModel

    _, user_client, _ = upload_clients
    before = AlphaScoreCacheModel._default_manager.count()
    with CaptureQueriesContext(connection) as queries:
        response = user_client.post(
            "/api/alpha/scores/upload/preview/", data=_payload(), format="json"
        )

    assert response.status_code == 200
    preview = response.json()["preview"]
    assert preview["operation"] == "create"
    assert preview["scope"] == "user"
    assert preview["incoming_codes"] == ["000001.SZ"]
    assert preview["writes"] == ["alpha_score_cache"]
    assert AlphaScoreCacheModel._default_manager.count() == before
    sql = "\n".join(query["sql"].upper() for query in queries.captured_queries)
    assert "INSERT " not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql


@pytest.mark.django_db
def test_preview_and_commit_share_the_exact_upsert_target(upload_clients):
    from apps.alpha.infrastructure.models import AlphaScoreCacheModel

    user, user_client, _ = upload_clients
    payload = _payload()
    first = user_client.post("/api/alpha/scores/upload/", data=payload, format="json")
    assert first.status_code == 201

    replacement = deepcopy(payload)
    replacement["scores"][0]["score"] = 0.75
    preview = user_client.post("/api/alpha/scores/upload/preview/", data=replacement, format="json")
    assert preview.status_code == 200
    assert preview.json()["preview"]["operation"] == "update"
    assert preview.json()["preview"]["existing"]["id"] == first.json()["id"]

    committed = user_client.post("/api/alpha/scores/upload/", data=replacement, format="json")
    assert committed.status_code == 200
    assert committed.json()["id"] == first.json()["id"]
    target = AlphaScoreCacheModel._default_manager.get(pk=first.json()["id"])
    assert target.user_id == user.pk
    assert target.scores[0]["score"] == 0.75


@pytest.mark.django_db
def test_system_preview_requires_staff(upload_clients):
    _, user_client, staff_client = upload_clients
    payload = _payload(scope="system")
    assert (
        user_client.post(
            "/api/alpha/scores/upload/preview/", data=payload, format="json"
        ).status_code
        == 403
    )
    response = staff_client.post("/api/alpha/scores/upload/preview/", data=payload, format="json")
    assert response.status_code == 200
    assert response.json()["preview"]["scope"] == "system"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        _payload(unknown=True),
        _payload(scores=[]),
        _payload(scores=[{"code": "A", "score": "NaN", "rank": 1}]),
        _payload(
            scores=[
                {"code": "A", "score": 1, "rank": 1},
                {"code": "a", "score": 2, "rank": 2},
            ]
        ),
        _payload(
            scores=[
                {"code": "A", "score": 1, "rank": 1},
                {"code": "B", "score": 2, "rank": 1},
            ]
        ),
        _payload(
            asof_date=date.today().isoformat(),
            intended_trade_date=(date.today() - timedelta(days=1)).isoformat(),
        ),
        _payload(
            scores=[{"code": str(index), "score": 1, "rank": index + 1} for index in range(1001)]
        ),
    ],
)
def test_upload_contract_rejects_ambiguous_or_unbounded_payloads(upload_clients, payload):
    _, user_client, _ = upload_clients
    response = user_client.post("/api/alpha/scores/upload/preview/", data=payload, format="json")
    assert response.status_code == 400
