import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_config_center_snapshot_is_staff_only_and_executes_no_database_writes():
    regular = User.objects.create_user(username="snapshot-regular", password="testpass123")
    staff = User.objects.create_user(
        username="snapshot-staff",
        password="testpass123",
        is_staff=True,
    )
    client = APIClient()
    client.force_authenticate(user=regular)
    denied = client.get("/api/system/config-center/")
    assert denied.status_code == 403

    client.force_authenticate(user=staff)
    with CaptureQueriesContext(connection) as queries:
        response = client.get("/api/system/config-center/")

    assert response.status_code == 200
    assert response.json()["data"]["sections"]
    write_sql = [
        query["sql"]
        for query in queries.captured_queries
        if query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
    ]
    assert write_sql == []
