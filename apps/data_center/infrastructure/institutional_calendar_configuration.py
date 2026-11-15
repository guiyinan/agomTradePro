"""Explicit database configuration for the bounded institutional-calendar source."""

from __future__ import annotations

from datetime import datetime
from typing import cast

from apps.data_center.application.institutional_calendar_sources import InstitutionalSourcePolicy
from apps.data_center.infrastructure.models import ProviderConfigModel
from core.exceptions import DataValidationError


def decode_institutional_source_policy(value: object) -> InstitutionalSourcePolicy:
    """Narrow operator JSON to the complete typed qualification contract."""
    if not isinstance(value, dict):
        raise _invalid()
    raw = cast(dict[str, object], value)
    text_keys = (
        "source_id",
        "event_type",
        "rule_version",
        "catalogue_sha256",
        "timezone_name",
        "attribution",
        "valid_until",
    )
    if any(not isinstance(raw.get(key), str) for key in text_keys):
        raise _invalid()
    urls = raw.get("allowed_urls")
    if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
        raise _invalid()
    try:
        return InstitutionalSourcePolicy(
            source_id=cast(str, raw["source_id"]),
            event_type=cast(str, raw["event_type"]),
            rule_version=cast(str, raw["rule_version"]),
            catalogue_sha256=cast(str, raw["catalogue_sha256"]),
            timezone_name=cast(str, raw["timezone_name"]),
            attribution=cast(str, raw["attribution"]),
            allowed_urls=tuple(cast(list[str], urls)),
            valid_until=datetime.fromisoformat(cast(str, raw["valid_until"])),
        )
    except ValueError as error:
        raise _invalid() from error


class DjangoInstitutionalCalendarPolicyReader:
    """Select a unique active public-document source with no guessed fallback."""

    def __init__(self, *, using: str = "default") -> None:
        """Bind the configured data-center database alias."""
        self._using = using

    def read_policy(self) -> InstitutionalSourcePolicy | None:
        """Return no qualification for absent, ambiguous or malformed configuration."""
        rows = list(
            ProviderConfigModel.objects.using(self._using).filter(
                source_type="public_document",
                is_active=True,
                extra_config__has_key="institutional_calendar",
            )[:2]
        )
        if len(rows) != 1:
            return None
        row = rows[0]
        try:
            extra = cast(dict[str, object], row.extra_config)
            policy = decode_institutional_source_policy(extra.get("institutional_calendar"))
        except DataValidationError:
            return None
        return policy if row.name == policy.source_id else None


def _invalid() -> DataValidationError:
    """Report source configuration errors without publishing operator input."""
    return DataValidationError(
        "Institutional-calendar source policy is invalid.",
        code="INSTITUTIONAL_SOURCE_POLICY_INVALID",
    )


__all__ = ["DjangoInstitutionalCalendarPolicyReader", "decode_institutional_source_policy"]
