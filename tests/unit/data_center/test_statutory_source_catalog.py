from __future__ import annotations

import sys
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone
from hashlib import sha256

import pytest

from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)

_BODY = b"synthetic catalog fixture"


def _date(value: date) -> StatutorySourceDateEvidence:
    return StatutorySourceDateEvidence(
        precision=StatutorySourceDatePrecision.DATE,
        date_value=value,
    )


def _revision(
    *,
    document_id: str = "SYNTHETIC-001",
    source_version: str = "fixture-v1",
    url: str = "https://example.invalid/law",
    issuer: str = "Synthetic publisher",
    title: str = "Synthetic law fixture",
) -> StatutorySourceDocumentRevision:
    return StatutorySourceDocumentRevision(
        document_id=document_id,
        source_version=source_version,
        canonical_url=url,
        issuer=issuer,
        title=title,
        legal_number="SYNTHETIC-LEG-001",
        publication_date=_date(date(2001, 2, 3)),
        effective_date=_date(date(2001, 3, 4)),
        body_sha256=sha256(_BODY).hexdigest(),
        body_size_bytes=len(_BODY),
    )


def _rule(
    revision: StatutorySourceDocumentRevision | None = None,
    *,
    max_bytes: int | None = None,
    media_types: frozenset[str] = frozenset({"text/html"}),
) -> StatutorySourceDocumentCaptureRule:
    selected = revision or _revision()
    return StatutorySourceDocumentCaptureRule(
        revision=selected,
        max_bytes=len(_BODY) if max_bytes is None else max_bytes,
        allowed_media_types=media_types,
    )


def _profile(
    documents: tuple[StatutorySourceDocumentCaptureRule, ...] | None = None,
    *,
    hosts: frozenset[str] = frozenset({"example.invalid"}),
    age: int = 3600,
) -> StatutorySourceCatalogProfile:
    return StatutorySourceCatalogProfile(
        profile_id="synthetic-profile",
        version="fixture-v1",
        publisher_code="synthetic-publisher",
        enabled=True,
        allowed_hosts=hosts,
        max_capture_age_seconds=age,
        documents=(_rule(),) if documents is None else documents,
    )


def test_catalog_is_frozen_and_hash_binds_explicit_configuration() -> None:
    first = _profile(hosts=frozenset({"example.invalid", "docs.example.invalid"}))
    reordered = _profile(hosts=frozenset({"docs.example.invalid", "example.invalid"}))

    assert first.content_sha256 == reordered.content_sha256
    assert len(first.content_sha256) == 64
    assert _profile(age=3601).content_sha256 != first.content_sha256
    assert _profile((_rule(_revision(title="Changed synthetic fixture")),)).content_sha256 != (
        first.content_sha256
    )
    base = _profile()
    changed_profiles = (
        replace(base, profile_id="another-synthetic-profile"),
        replace(base, version="fixture-v2"),
        replace(base, publisher_code="another-synthetic-publisher"),
        replace(base, enabled=False),
        replace(base, allowed_hosts=frozenset({"example.invalid", "docs.example.invalid"})),
        replace(base, max_capture_age_seconds=3601),
        replace(base, documents=(_rule(max_bytes=len(_BODY) + 1),)),
        replace(base, documents=(_rule(media_types=frozenset({"application/pdf"})),)),
    )
    assert all(item.content_sha256 != base.content_sha256 for item in changed_profiles)
    with pytest.raises(FrozenInstanceError):
        first.enabled = False  # type: ignore[misc]


def test_capture_rule_normalizes_only_explicit_concrete_media_types() -> None:
    rule = _rule(media_types=frozenset({"TEXT/HTML", "application/pdf"}))

    assert rule.allowed_media_types == frozenset({"text/html", "application/pdf"})

    for media_types in (
        frozenset(),
        frozenset({"text/*"}),
        frozenset({"text/html; charset=utf-8"}),
        {"text/html"},
    ):
        with pytest.raises(ValueError):
            _rule(media_types=media_types)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "host",
    (
        "*.example.invalid",
        "Example.invalid",
        "https://example.invalid",
        "example.invalid/path",
        "127.0.0.1",
        "2001:db8::1",
        "bad_label.example",
        "example.invalid.",
        "-bad.example",
        "bad-.example",
    ),
)
def test_profile_rejects_noncanonical_or_non_dns_allowed_hosts(host: str) -> None:
    with pytest.raises(ValueError):
        _profile(hosts=frozenset({host}))


def test_profile_requires_explicit_matching_host_and_nonempty_typed_rules() -> None:
    with pytest.raises(ValueError, match="does not match"):
        _profile(hosts=frozenset({"other.invalid"}))
    with pytest.raises(ValueError):
        _profile(documents=())
    with pytest.raises(ValueError):
        StatutorySourceCatalogProfile(
            profile_id="synthetic-profile",
            version="fixture-v1",
            publisher_code="synthetic-publisher",
            enabled=True,
            allowed_hosts={"example.invalid"},  # type: ignore[arg-type]
            max_capture_age_seconds=3600,
            documents=(_rule(),),
        )
    with pytest.raises(ValueError, match="exact capture rules"):
        _profile(documents=(object(),))  # type: ignore[arg-type]


@pytest.mark.parametrize("age", (0, -1, True, 1.5, 10**30))
def test_profile_rejects_invalid_or_unrepresentable_capture_age(age: object) -> None:
    with pytest.raises(ValueError):
        _profile(age=age)  # type: ignore[arg-type]


@pytest.mark.parametrize("max_bytes", (0, -1, True, 1.5, sys.maxsize, len(_BODY) - 1))
def test_capture_rule_rejects_invalid_or_insufficient_byte_cap(max_bytes: object) -> None:
    with pytest.raises(ValueError):
        _rule(max_bytes=max_bytes)  # type: ignore[arg-type]


def test_profile_rejects_duplicate_native_revision_and_canonical_url() -> None:
    base = _revision()
    with pytest.raises(ValueError, match="duplicate native revision"):
        _profile((_rule(base), _rule(base)))

    different_revision_same_url = _revision(document_id="SYNTHETIC-002")
    with pytest.raises(ValueError, match="duplicate canonical URL"):
        _profile((_rule(base), _rule(different_revision_same_url)))


@pytest.mark.parametrize(
    "field,value",
    (
        ("profile_id", ""),
        ("profile_id", "  invalid"),
        ("version", "v\n1"),
        ("publisher_code", "publisher\x7f"),
        ("enabled", 1),
    ),
)
def test_profile_rejects_invalid_identity_and_flag_values(field: str, value: object) -> None:
    arguments: dict[str, object] = {
        "profile_id": "synthetic-profile",
        "version": "fixture-v1",
        "publisher_code": "synthetic-publisher",
        "enabled": True,
        "allowed_hosts": frozenset({"example.invalid"}),
        "max_capture_age_seconds": 3600,
        "documents": (_rule(),),
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        StatutorySourceCatalogProfile(**arguments)  # type: ignore[arg-type]


def test_source_timezone_evidence_remains_bound_in_catalog_digest() -> None:
    instant_revision = StatutorySourceDocumentRevision(
        document_id="SYNTHETIC-INSTANT-001",
        source_version="fixture-v1",
        canonical_url="https://example.invalid/instant-law",
        issuer="Synthetic publisher",
        title="Synthetic instant fixture",
        legal_number="SYNTHETIC-LEG-002",
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.INSTANT,
            instant_value=datetime(2001, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=8))),
        ),
        effective_date=StatutorySourceDateEvidence(precision=StatutorySourceDatePrecision.UNKNOWN),
        body_sha256=sha256(_BODY).hexdigest(),
        body_size_bytes=len(_BODY),
    )
    utc_revision = replace(
        instant_revision,
        publication_date=StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.INSTANT,
            instant_value=datetime(2001, 2, 2, 20, 5, tzinfo=UTC),
        ),
    )
    assert instant_revision.source_revision_sha256 == utc_revision.source_revision_sha256
    assert (
        _profile((_rule(instant_revision),)).content_sha256
        != _profile((_rule(utc_revision),)).content_sha256
    )


def test_capture_rule_rejects_untyped_revision_and_media_container() -> None:
    with pytest.raises(ValueError, match="exact source document revision"):
        StatutorySourceDocumentCaptureRule(
            revision=object(),  # type: ignore[arg-type]
            max_bytes=len(_BODY),
            allowed_media_types=frozenset({"text/html"}),
        )
    with pytest.raises(ValueError, match="frozenset of exact strings"):
        StatutorySourceDocumentCaptureRule(
            revision=_revision(),
            max_bytes=len(_BODY),
            allowed_media_types={"text/html"},  # type: ignore[arg-type]
        )
