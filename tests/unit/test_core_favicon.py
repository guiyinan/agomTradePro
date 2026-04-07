import pytest
from django.test import Client


@pytest.mark.django_db
def test_favicon_route_returns_no_content() -> None:
    response = Client().get("/favicon.ico")

    assert response.status_code == 204
