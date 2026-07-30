"""Tests for shared DRF request-payload narrowing."""

import pytest
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from shared.request_payload import request_data_mapping


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"count": 2}, {"count": 2}),
        ([{"count": 2}], {}),
    ],
)
def test_request_data_mapping_accepts_only_object_bodies(
    body: object,
    expected: dict[str, object],
) -> None:
    """Object bodies are copied while array bodies become empty input."""

    factory = APIRequestFactory()
    request = APIView().initialize_request(factory.post("/", body, format="json"))

    assert isinstance(request, Request)
    assert request_data_mapping(request) == expected
