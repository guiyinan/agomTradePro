"""Typed configured-origin source evidence; legal applicability remains unqualified."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from apps.data_center.domain.provider_document_response import normalize_document_content_type
from apps.data_center.domain.statutory_source_catalog import StatutorySourceCatalogProfile
from apps.data_center.domain.statutory_source_documents import StatutorySourceDocumentBundle
from core.exceptions import DataValidationError


def _invalid(
    message: str, code: str = "STATUTORY_SOURCE_BUNDLE_READ_INVALID"
) -> DataValidationError:
    """Return a stable source-read failure without granting partial qualification."""
    return DataValidationError(message, code=code)


@dataclass(frozen=True, slots=True)
class ConfiguredStatutorySourceBundleRead:
    """Exact bytes and real observations checked against one explicit catalog.

    A fresh capture and configured publisher consistency establish neither
    current law nor suitability for any financial decision. Consumers must
    independently qualify the retained legal provisions and runtime policy.
    """

    bundle: StatutorySourceDocumentBundle
    bodies: tuple[bytes, ...] = field(repr=False)
    provider_id: int
    catalog: StatutorySourceCatalogProfile
    configuration_sha256: str
    checked_at: datetime

    def __post_init__(self) -> None:
        """Validate exact complete bytes, catalog scope and original capture ages."""
        if (
            type(self.bundle) is not StatutorySourceDocumentBundle
            or type(self.catalog) is not StatutorySourceCatalogProfile
            or not self.catalog.enabled
            or type(self.provider_id) is not int
            or self.provider_id <= 0
            or type(self.configuration_sha256) is not str
            or len(self.configuration_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.configuration_sha256)
        ):
            raise _invalid("Exact source bundle and enabled catalog bindings are required.")
        if (
            type(self.checked_at) is not datetime
            or self.checked_at.tzinfo is None
            or self.checked_at.utcoffset() is None
        ):
            raise _invalid("Source read cutoff must be an aware server instant.")
        try:
            self.checked_at.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _invalid("Source read cutoff must be representable in UTC.") from error
        if type(self.bodies) is not tuple or len(self.bodies) != len(self.bundle.captures):
            raise _invalid("Source bodies must cover every exact bundle member.")
        rules = {rule.revision.identity_key: rule for rule in self.catalog.documents}
        for capture, body in zip(self.bundle.captures, self.bodies, strict=True):
            rule = rules.get(capture.revision.identity_key)
            if rule is None or rule.revision != capture.revision:
                raise _invalid(
                    "Retained source revision differs from the configured catalog.",
                    "STATUTORY_SOURCE_BUNDLE_CATALOG_MISMATCH",
                )
            if (
                type(body) is not bytes
                or not capture.revision.verifies_source_document(body)
                or not capture.body_reference.verifies(body)
            ):
                raise _invalid(
                    "Retained source body failed exact readback integrity.",
                    "STATUTORY_SOURCE_BODY_INTEGRITY_FAILED",
                )
            try:
                media_type = normalize_document_content_type(capture.content_type)
            except ValueError as error:
                raise _invalid("Retained source content type is invalid.") from error
            if len(body) > rule.max_bytes or media_type not in rule.allowed_media_types:
                raise _invalid("Retained source exceeds configured byte or MIME limits.")
            if (
                capture.captured_at > self.checked_at
                or self.checked_at - capture.captured_at
                > timedelta(seconds=self.catalog.max_capture_age_seconds)
            ):
                raise _invalid(
                    "Retained source is outside its original observation window.",
                    "STATUTORY_SOURCE_CAPTURE_OUTSIDE_WINDOW",
                )

    @property
    def source_observed_at(self) -> datetime:
        """Return the oldest actual response completion in the complete source set."""
        return min(capture.captured_at for capture in self.bundle.captures)

    @property
    def freshness_status(self) -> Literal["fresh"]:
        """Describe only capture age at checked_at, never legal currency."""
        return "fresh"

    @property
    def reliability(self) -> Literal["unqualified"]:
        """Keep legal/policy reliability unqualified despite verified byte integrity."""
        return "unqualified"

    @property
    def must_not_use_for_decision(self) -> Literal[True]:
        """Require independent legal applicability and decision-policy qualification."""
        return True

    @property
    def blocked_reason(self) -> Literal["statutory_legal_qualification_required"]:
        """Publish a stable reason instead of implying that latest capture means law."""
        return "statutory_legal_qualification_required"


class ConfiguredStatutorySourceBundleReaderProtocol(Protocol):
    """Public Data Center boundary for exact configured evidence and source bytes."""

    def read_retained_bundle(
        self, *, bundle_id: str, version: str
    ) -> ConfiguredStatutorySourceBundleRead:
        """Read only the named retained bundle; do not fall back or refresh implicitly."""
        ...


__all__ = ["ConfiguredStatutorySourceBundleRead", "ConfiguredStatutorySourceBundleReaderProtocol"]
