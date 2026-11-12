from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256

import pytest

from apps.data_center.application.statutory_source_catalog import (
    StatutorySourceCatalogDecodeError,
    decode_statutory_source_catalog_profile,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDatePrecision,
)

_BODY = b"synthetic law bytes"


def _valid_config() -> dict[str, object]:
    return {
        "schema_version": "data_center.statutory_source_catalog.v1",
        "profile_id": "synthetic-profile",
        "version": "fixture-v1",
        "publisher_code": "synthetic-publisher",
        "enabled": True,
        "allowed_hosts": ["example.invalid"],
        "max_capture_age_seconds": 3600,
        "documents": [
            {
                "revision": {
                    "document_id": "SYNTHETIC-001",
                    "source_version": "fixture-v1",
                    "canonical_url": "https://example.invalid/synthetic-law",
                    "issuer": "Synthetic publisher",
                    "title": "Synthetic statutory document",
                    "legal_number": "SYNTHETIC-LAW-001",
                    "publication_date": {"precision": "date", "value": "2001-02-03"},
                    "effective_date": {"precision": "unknown", "value": None},
                    "body_sha256": sha256(_BODY).hexdigest(),
                    "body_size_bytes": len(_BODY),
                },
                "max_bytes": len(_BODY),
                "allowed_media_types": ["text/html"],
            }
        ],
    }


def test_decoder_returns_explicit_domain_value_without_claiming_qualification() -> None:
    profile = decode_statutory_source_catalog_profile(_valid_config())

    assert profile.enabled is True
    assert profile.documents[0].revision.publication_date.date_value == date(2001, 2, 3)
    assert profile.documents[0].revision.effective_date.precision is (
        StatutorySourceDatePrecision.UNKNOWN
    )
    assert len(profile.content_sha256) == 64


@pytest.mark.parametrize(
    "field",
    [
        "profile_id",
        "version",
        "publisher_code",
        "document_id",
        "source_version",
        "issuer",
        "title",
        "legal_number",
        "canonical_url",
    ],
)
def test_decoded_json_surrogate_is_rejected_before_a_profile_can_claim_a_hash(field: str) -> None:
    """JSON accepts escaped surrogates, but accepted source facts must be UTF-8 hashable."""
    config = _valid_config()
    if field in {"profile_id", "version", "publisher_code"}:
        config[field] = "invalid-\ud800"
    else:
        documents = config["documents"]
        assert type(documents) is list
        documents[0]["revision"][field] = (
            "https://example.invalid/\ud800" if field == "canonical_url" else "invalid-\ud800"
        )
    with pytest.raises(StatutorySourceCatalogDecodeError):
        decode_statutory_source_catalog_profile(config)


def test_decoder_preserves_canonical_source_timezone_offset() -> None:
    config = _valid_config()
    documents = config["documents"]
    assert type(documents) is list
    revision = documents[0]["revision"]
    revision["publication_date"] = {
        "precision": "instant",
        "value": "2001-02-03T04:05:06+08:00",
    }

    profile = decode_statutory_source_catalog_profile(config)
    instant = profile.documents[0].revision.publication_date.instant_value

    assert instant == datetime(2001, 2, 2, 20, 5, 6, tzinfo=UTC)
    assert instant is not None and instant.utcoffset() == timedelta(hours=8)
    assert instant is not None and instant.strftime("%z") == "+0800"


def _expect_invalid(config: object) -> None:
    with pytest.raises(StatutorySourceCatalogDecodeError) as caught:
        decode_statutory_source_catalog_profile(config)
    assert caught.value.code == "STATUTORY_SOURCE_CATALOG_DECODE_INVALID"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda data: data.pop("enabled"),
        lambda data: data.__setitem__("unexpected", "value"),
        lambda data: data.__setitem__("schema_version", "unknown.v2"),
        lambda data: data.__setitem__("enabled", 1),
        lambda data: data.__setitem__("max_capture_age_seconds", True),
        lambda data: data.__setitem__("max_capture_age_seconds", "3600"),
        lambda data: data.__setitem__("allowed_hosts", "example.invalid"),
        lambda data: data.__setitem__("allowed_hosts", ["example.invalid", "example.invalid"]),
        lambda data: data.__setitem__("documents", []),
        lambda data: data.__setitem__("documents", "not-an-array"),
    ),
)
def test_decoder_rejects_top_level_shape_and_type_errors(mutate: object) -> None:
    config = _valid_config()
    mutate(config)  # type: ignore[operator]
    _expect_invalid(config)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda rule: rule.pop("max_bytes"),
        lambda rule: rule.__setitem__("extra", "value"),
        lambda rule: rule.__setitem__("max_bytes", True),
        lambda rule: rule.__setitem__("max_bytes", str(len(_BODY))),
        lambda rule: rule.__setitem__("allowed_media_types", ["text/*"]),
        lambda rule: rule.__setitem__("allowed_media_types", ["text/html; charset=utf-8"]),
        lambda rule: rule.__setitem__("allowed_media_types", ["text/html", "text/html"]),
        lambda rule: rule.__setitem__("allowed_media_types", ["TEXT/HTML", "text/html"]),
        lambda rule: rule.__setitem__("allowed_media_types", "text/html"),
    ),
)
def test_decoder_rejects_capture_rule_shape_and_type_errors(mutate: object) -> None:
    config = _valid_config()
    documents = config["documents"]
    assert type(documents) is list
    mutate(documents[0])  # type: ignore[operator]
    _expect_invalid(config)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda revision: revision.pop("body_sha256"),
        lambda revision: revision.__setitem__("unexpected", "value"),
        lambda revision: revision.__setitem__("body_size_bytes", True),
        lambda revision: revision.__setitem__("body_size_bytes", str(len(_BODY))),
        lambda revision: revision.__setitem__("canonical_url", "http://example.invalid/law"),
        lambda revision: revision.__setitem__("canonical_url", "https://other.invalid/law"),
    ),
)
def test_decoder_rejects_revision_shape_type_and_scope_errors(mutate: object) -> None:
    config = _valid_config()
    documents = config["documents"]
    assert type(documents) is list
    revision = documents[0]["revision"]
    mutate(revision)  # type: ignore[operator]
    _expect_invalid(config)


@pytest.mark.parametrize(
    "date_evidence",
    (
        {"precision": "date", "value": "2001-2-03"},
        {"precision": "date", "value": "2001-02-03T00:00:00"},
        {"precision": "instant", "value": "2001-02-03T04:05:06"},
        {"precision": "instant", "value": "2001-02-03T04:05:06Z"},
        {"precision": "instant", "value": "2001-02-03 04:05:06+08:00"},
        {"precision": "unknown", "value": "2001-02-03"},
        {"precision": "unknown", "value": None, "extra": False},
        {"precision": "made-up", "value": None},
    ),
)
def test_decoder_rejects_noncanonical_or_mismatched_source_date_evidence(
    date_evidence: dict[str, object],
) -> None:
    config = _valid_config()
    documents = config["documents"]
    assert type(documents) is list
    revision = documents[0]["revision"]
    revision["publication_date"] = date_evidence
    _expect_invalid(config)


def test_decoder_rejects_non_object_and_does_not_coerce_identifiers() -> None:
    _expect_invalid("{}")
    config = _valid_config()
    config["profile_id"] = 3
    _expect_invalid(config)


def test_decoder_rejects_duplicate_native_identity_or_url() -> None:
    config = _valid_config()
    documents = config["documents"]
    assert type(documents) is list
    documents.append(deepcopy(documents[0]))
    _expect_invalid(config)


def test_decoder_rejects_duplicate_canonical_url_with_distinct_revision_identity() -> None:
    config = _valid_config()
    documents = config["documents"]
    assert type(documents) is list
    second = deepcopy(documents[0])
    second["revision"]["document_id"] = "SYNTHETIC-002"
    documents.append(second)
    _expect_invalid(config)
