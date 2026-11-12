"""Strict decoder for explicit statutory-source capture catalog candidates."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal, TypedDict, TypeGuard, cast

from apps.data_center.domain.provider_document_response import (
    normalize_document_media_type_allowlist,
)
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDateEvidence,
    StatutorySourceDatePrecision,
    StatutorySourceDocumentRevision,
)
from core.exceptions import DataValidationError

_SCHEMA_VERSION = "data_center.statutory_source_catalog.v1"
_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")

_PROFILE_FIELDS = frozenset(
    {
        "schema_version",
        "profile_id",
        "version",
        "publisher_code",
        "enabled",
        "allowed_hosts",
        "max_capture_age_seconds",
        "documents",
    }
)
_RULE_FIELDS = frozenset({"revision", "max_bytes", "allowed_media_types"})
_REVISION_FIELDS = frozenset(
    {
        "document_id",
        "source_version",
        "canonical_url",
        "issuer",
        "title",
        "legal_number",
        "publication_date",
        "effective_date",
        "body_sha256",
        "body_size_bytes",
    }
)
_DATE_FIELDS = frozenset({"precision", "value"})


class StatutorySourceDateEvidenceJSON(TypedDict):
    """Exact JSON representation of precision-preserving source date facts."""

    precision: Literal["unknown", "date", "instant"]
    value: str | None


class StatutorySourceDocumentRevisionJSON(TypedDict):
    """Exact publisher-native revision fields accepted by the decoder."""

    document_id: str
    source_version: str
    canonical_url: str
    issuer: str
    title: str
    legal_number: str
    publication_date: StatutorySourceDateEvidenceJSON
    effective_date: StatutorySourceDateEvidenceJSON
    body_sha256: str
    body_size_bytes: int


class StatutorySourceDocumentCaptureRuleJSON(TypedDict):
    """One capture rule with an explicit revision, byte bound, and MIME set."""

    revision: StatutorySourceDocumentRevisionJSON
    max_bytes: int
    allowed_media_types: list[str]


class StatutorySourceCatalogProfileJSON(TypedDict):
    """Versioned JSON object for an unqualified source-capture profile."""

    schema_version: Literal["data_center.statutory_source_catalog.v1"]
    profile_id: str
    version: str
    publisher_code: str
    enabled: bool
    allowed_hosts: list[str]
    max_capture_age_seconds: int
    documents: list[StatutorySourceDocumentCaptureRuleJSON]


class StatutorySourceCatalogDecodeError(DataValidationError):
    """The explicit catalog JSON cannot be narrowed into validated Domain data."""

    default_message = "显式法定来源目录配置无效"
    default_code = "STATUTORY_SOURCE_CATALOG_DECODE_INVALID"


def _invalid(field: str, reason: str) -> StatutorySourceCatalogDecodeError:
    """Return one stable error without echoing untrusted configuration values."""

    return StatutorySourceCatalogDecodeError(f"{field}: {reason}")


def _is_string_object(value: object) -> TypeGuard[dict[str, object]]:
    """Narrow an exact built-in dictionary whose keys are exact strings."""

    if type(value) is not dict:
        return False
    raw = cast(dict[object, object], value)
    return all(type(key) is str for key in raw)


def _require_object_fields(
    value: object,
    *,
    expected_fields: frozenset[str],
    field: str,
) -> dict[str, object]:
    """Require a JSON object with every declared field and no extras."""

    if not _is_string_object(value):
        raise _invalid(field, "must be an exact JSON object with string keys")
    if frozenset(value) != expected_fields:
        raise _invalid(field, "required fields are missing or unknown fields are present")
    return value


def _require_string(value: object, *, field: str) -> str:
    """Require an exact JSON string without scalar coercion."""

    if type(value) is not str:
        raise _invalid(field, "must be a string")
    return value


def _require_exact_int(value: object, *, field: str) -> int:
    """Require an exact JSON integer, rejecting booleans and floats."""

    if type(value) is not int:
        raise _invalid(field, "must be an exact integer")
    return value


def _parse_date_evidence(value: object, *, field: str) -> StatutorySourceDateEvidence:
    """Decode one exact canonical date/instant or explicit unknown value."""

    raw = _require_object_fields(value, expected_fields=_DATE_FIELDS, field=field)
    precision_text = _require_string(raw["precision"], field=f"{field}.precision")
    date_text = raw["value"]
    if precision_text == StatutorySourceDatePrecision.UNKNOWN.value:
        if date_text is not None:
            raise _invalid(f"{field}.value", "must be null for unknown precision")
        return StatutorySourceDateEvidence(precision=StatutorySourceDatePrecision.UNKNOWN)
    if precision_text == StatutorySourceDatePrecision.DATE.value:
        text = _require_string(date_text, field=f"{field}.value")
        if _DATE_PATTERN.fullmatch(text) is None:
            raise _invalid(f"{field}.value", "must be a canonical YYYY-MM-DD date")
        try:
            parsed_date = date.fromisoformat(text)
        except ValueError as error:
            raise _invalid(f"{field}.value", "must be a canonical YYYY-MM-DD date") from error
        if parsed_date.isoformat() != text:
            raise _invalid(f"{field}.value", "must be a canonical YYYY-MM-DD date")
        return StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.DATE,
            date_value=parsed_date,
        )
    if precision_text == StatutorySourceDatePrecision.INSTANT.value:
        text = _require_string(date_text, field=f"{field}.value")
        try:
            parsed_instant = datetime.fromisoformat(text)
        except ValueError as error:
            raise _invalid(f"{field}.value", "must be a canonical aware ISO datetime") from error
        if parsed_instant.tzinfo is None or parsed_instant.utcoffset() is None:
            raise _invalid(f"{field}.value", "must be a canonical aware ISO datetime")
        if parsed_instant.isoformat() != text:
            raise _invalid(f"{field}.value", "must be a canonical aware ISO datetime")
        return StatutorySourceDateEvidence(
            precision=StatutorySourceDatePrecision.INSTANT,
            instant_value=parsed_instant,
        )
    raise _invalid(f"{field}.precision", "is unsupported")


def _parse_revision(value: object, *, field: str) -> StatutorySourceDocumentRevision:
    """Narrow one exact source revision object into the existing Domain type."""

    raw = _require_object_fields(value, expected_fields=_REVISION_FIELDS, field=field)
    revision = cast(StatutorySourceDocumentRevisionJSON, raw)
    try:
        return StatutorySourceDocumentRevision(
            document_id=_require_string(revision["document_id"], field=f"{field}.document_id"),
            source_version=_require_string(
                revision["source_version"], field=f"{field}.source_version"
            ),
            canonical_url=_require_string(
                revision["canonical_url"], field=f"{field}.canonical_url"
            ),
            issuer=_require_string(revision["issuer"], field=f"{field}.issuer"),
            title=_require_string(revision["title"], field=f"{field}.title"),
            legal_number=_require_string(revision["legal_number"], field=f"{field}.legal_number"),
            publication_date=_parse_date_evidence(
                revision["publication_date"], field=f"{field}.publication_date"
            ),
            effective_date=_parse_date_evidence(
                revision["effective_date"], field=f"{field}.effective_date"
            ),
            body_sha256=_require_string(revision["body_sha256"], field=f"{field}.body_sha256"),
            body_size_bytes=_require_exact_int(
                revision["body_size_bytes"], field=f"{field}.body_size_bytes"
            ),
        )
    except ValueError as error:
        raise _invalid(field, "failed Domain validation") from error


def _parse_rule(value: object, *, index: int) -> StatutorySourceDocumentCaptureRule:
    """Narrow one exact source-capture rule."""

    field = f"documents[{index}]"
    raw = _require_object_fields(value, expected_fields=_RULE_FIELDS, field=field)
    rule = cast(StatutorySourceDocumentCaptureRuleJSON, raw)
    raw_media_types = rule["allowed_media_types"]
    if type(raw_media_types) is not list or not raw_media_types:
        raise _invalid(f"{field}.allowed_media_types", "must be a non-empty JSON array")
    media_type_values = cast(list[object], raw_media_types)
    media_types = tuple(
        _require_string(item, field=f"{field}.allowed_media_types[{index}]")
        for index, item in enumerate(media_type_values)
    )
    if len(set(media_types)) != len(media_types):
        raise _invalid(f"{field}.allowed_media_types", "contains duplicate MIME types")
    try:
        normalized_media_types = normalize_document_media_type_allowlist(frozenset(media_types))
    except ValueError as error:
        raise _invalid(f"{field}.allowed_media_types", "contains an invalid MIME type") from error
    if len(normalized_media_types) != len(media_types):
        raise _invalid(f"{field}.allowed_media_types", "contains duplicate MIME types")
    try:
        return StatutorySourceDocumentCaptureRule(
            revision=_parse_revision(rule["revision"], field=f"{field}.revision"),
            max_bytes=_require_exact_int(rule["max_bytes"], field=f"{field}.max_bytes"),
            allowed_media_types=normalized_media_types,
        )
    except ValueError as error:
        raise _invalid(field, "failed Domain validation") from error


def decode_statutory_source_catalog_profile(value: object) -> StatutorySourceCatalogProfile:
    """Decode a strict, already-parsed JSON object into an unqualified profile.

    Every source identity, host, capture age, byte limit, MIME allowlist, and
    source date is explicit. Structural hashes do not authenticate source
    origin, establish current legal status, or activate a policy.
    """

    raw = _require_object_fields(value, expected_fields=_PROFILE_FIELDS, field="catalog")
    profile = cast(StatutorySourceCatalogProfileJSON, raw)
    if _require_string(profile["schema_version"], field="schema_version") != _SCHEMA_VERSION:
        raise _invalid("schema_version", "is unsupported")
    raw_hosts = profile["allowed_hosts"]
    if type(raw_hosts) is not list or not raw_hosts:
        raise _invalid("allowed_hosts", "must be a non-empty JSON array")
    host_values = cast(list[object], raw_hosts)
    hosts = tuple(
        _require_string(host, field=f"allowed_hosts[{index}]")
        for index, host in enumerate(host_values)
    )
    if len(set(hosts)) != len(hosts):
        raise _invalid("allowed_hosts", "contains duplicate host entries")
    raw_documents = profile["documents"]
    if type(raw_documents) is not list or not raw_documents:
        raise _invalid("documents", "must be a non-empty JSON array")
    document_values = cast(list[object], raw_documents)
    rules = tuple(_parse_rule(item, index=index) for index, item in enumerate(document_values))
    try:
        return StatutorySourceCatalogProfile(
            profile_id=_require_string(profile["profile_id"], field="profile_id"),
            version=_require_string(profile["version"], field="version"),
            publisher_code=_require_string(profile["publisher_code"], field="publisher_code"),
            enabled=_require_exact_bool(profile["enabled"], field="enabled"),
            allowed_hosts=frozenset(hosts),
            max_capture_age_seconds=_require_exact_int(
                profile["max_capture_age_seconds"], field="max_capture_age_seconds"
            ),
            documents=rules,
        )
    except ValueError as error:
        raise _invalid("catalog", "failed Domain validation") from error


def _require_exact_bool(value: object, *, field: str) -> bool:
    """Require an exact JSON boolean."""

    if type(value) is not bool:
        raise _invalid(field, "must be a boolean")
    return value


__all__ = [
    "StatutorySourceCatalogDecodeError",
    "StatutorySourceCatalogProfileJSON",
    "StatutorySourceDateEvidenceJSON",
    "StatutorySourceDocumentCaptureRuleJSON",
    "StatutorySourceDocumentRevisionJSON",
    "decode_statutory_source_catalog_profile",
]
