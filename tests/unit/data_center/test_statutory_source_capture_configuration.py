"""Configured publisher origin checks never turn an invalid port into HTTPS default."""

from __future__ import annotations

import pytest

from apps.data_center.application.statutory_source_catalog import (
    decode_statutory_source_catalog_profile,
)
from apps.data_center.infrastructure.models import PublisherCatalogModel
from apps.data_center.statutory_source_capture_composition import _publisher_scope
from core.exceptions import DataValidationError
from tests.unit.data_center.test_statutory_source_catalog_decode import _valid_config


@pytest.mark.parametrize(
    "website", ["https://example.invalid/", "https://example.invalid/index.html"]
)
def test_exact_configured_publisher_origin_is_accepted(website: str) -> None:
    _publisher_scope(
        decode_statutory_source_catalog_profile(_valid_config()),
        PublisherCatalogModel(website=website),
    )


@pytest.mark.parametrize(
    "website",
    [
        "https://example.invalid:0/",
        "https://example.invalid:8443/",
        "https://example.invalid:99999/",
        "https://example.invalid:bad/",
        "http://example.invalid/",
        "https://user:password@example.invalid/",
        "https://example.invalid/#fragment",
        "https://other.invalid/",
        "https://example.invalid.evil.invalid/",
    ],
)
def test_invalid_or_different_publisher_origin_is_rejected(website: str) -> None:
    with pytest.raises(DataValidationError):
        _publisher_scope(
            decode_statutory_source_catalog_profile(_valid_config()),
            PublisherCatalogModel(website=website),
        )
