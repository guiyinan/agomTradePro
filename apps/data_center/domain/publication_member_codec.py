"""Exact identifiers for policy-bound nullable publication member codecs."""

from __future__ import annotations

from enum import StrEnum
from typing import TypeAlias

from .control_plane import CalendarNullableMemberCodecVersion


class PriceLimitNullableMemberCodecVersion(StrEnum):
    """Explicit codec versions for price-limit facts with unknown source clocks."""

    V1 = "price-limit-nullable-member-v1"


PublicationMemberCodecVersion: TypeAlias = (
    CalendarNullableMemberCodecVersion | PriceLimitNullableMemberCodecVersion
)
"""Codec enum values permitted in the publication policy field."""


def decode_publication_member_codec(value: str | None) -> PublicationMemberCodecVersion | None:
    """Decode only the exact registered nullable-member codec identifiers."""

    if value is None:
        return None
    if type(value) is not str:
        raise TypeError("publication member codec must be text or null")
    if value == CalendarNullableMemberCodecVersion.V1.value:
        return CalendarNullableMemberCodecVersion.V1
    if value == PriceLimitNullableMemberCodecVersion.V1.value:
        return PriceLimitNullableMemberCodecVersion.V1
    raise ValueError("publication member codec is not supported")


__all__ = [
    "PriceLimitNullableMemberCodecVersion",
    "PublicationMemberCodecVersion",
    "decode_publication_member_codec",
]
