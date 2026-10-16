"""Malformed provider bodies fail at the declared JSON input boundary."""

import pytest

from apps.data_center.domain.provider_response import parse_provider_response_json


@pytest.mark.parametrize(
    "body",
    (
        b'{"value":1e9999999999999999999999999999999}',
        b'{"value":"\xff"}',
    ),
    ids=("decimal-exponent-outside-runtime-range", "invalid-utf8-response-body"),
)
def test_invalid_numeric_or_text_body_is_a_stable_validation_failure(body: bytes) -> None:
    """Keep provider-controlled parse failures inside the ValueError contract."""
    with pytest.raises(ValueError):
        parse_provider_response_json(body)
