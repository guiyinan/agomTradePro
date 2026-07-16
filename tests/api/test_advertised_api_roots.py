"""Contracts for API roots advertised by the global API index."""

import pytest


@pytest.mark.django_db
def test_realtime_api_root_is_discoverable(authenticated_client):
    response = authenticated_client.get("/api/realtime/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    endpoints = response.json()["endpoints"]
    assert endpoints["prices"] == "/api/realtime/prices/"
    assert endpoints["health"] == "/api/realtime/health/"


@pytest.mark.django_db
def test_tui_api_root_is_discoverable(authenticated_client):
    response = authenticated_client.get("/api/tui/")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    endpoints = response.json()["endpoints"]
    assert endpoints["catalog"] == "/api/tui/catalog/"
    assert endpoints["registry"] == "/api/tui/registry/"


@pytest.mark.django_db
def test_realtime_page_entry_redirects_to_governed_workbench(
    authenticated_client,
):
    response = authenticated_client.get("/realtime/")

    assert response.status_code == 302
    assert response["Location"] == "/tui/"
