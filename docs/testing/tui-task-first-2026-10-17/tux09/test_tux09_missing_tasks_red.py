"""Old shared source must expose the two required user task screens."""

import pytest
from django.contrib.auth.models import User
from django.test import Client


@pytest.mark.django_db
@pytest.mark.parametrize("screen", ["task.today-focus", "task.portfolio-check"])
def test_required_task_screen_is_published(screen: str) -> None:
    """A real authenticated metadata read must reach the requested task."""

    user = User.objects.create_user(username="tux09-red-screen")
    client = Client()
    client.force_login(user)
    response = client.get(f"/api/tui/screens/{screen}/")
    assert response["Content-Type"].split(";", 1)[0] == "application/json"
    assert response.status_code == 200
    assert response.json()["screen"]["key"] == screen
