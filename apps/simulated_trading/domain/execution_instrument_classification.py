"""Explicit simulated asset classification sealed to an exact source identity.

The selector is an operator-authored mapping, not provider truth or execution
authority.  Its v2 item carries an explicit simulated asset type; this module
never infers a type from a code, market, board, or provider label.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .execution_current_reference import ExecutionInstrumentIdentityEvidenceV2
from .execution_settlement_identity import IdentityEvidenceValidationError
from .execution_settlement_identity import _normalize_utc as _normalize_identity_utc
from .execution_settlement_identity import _object as _identity_object
from .execution_settlement_identity import _parse_utc as _parse_identity_utc
from .execution_settlement_identity import _parse_uuid as _parse_identity_uuid
from .execution_settlement_identity import _require_prefixed_hash as _require_identity_hash
from .execution_settlement_identity import _require_token as _require_identity_token
from .execution_settlement_identity import _utc_text as _identity_utc_text

_SELECTOR_V2_SCHEMA = "normal-simulated-current-reference-selection.v2"
_CLASSIFICATION_V1_SCHEMA = "simulated-instrument-classification-evidence.v1"
_SELECTOR_PURPOSE = "normal_simulated_current_reference"


def _canonical_hash(payload: dict[str, object]) -> str:
    """Hash a strict payload with the current-reference canonical JSON rules."""

    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as error:
        raise IdentityEvidenceValidationError("CLASSIFICATION_JSON_INVALID") from error
    return hashlib.sha256(encoded).hexdigest()


def _exact_object(value: object, keys: frozenset[str]) -> dict[str, object]:
    """Require one exact JSON object and reject missing or unknown keys."""

    return _identity_object(value, keys)


@dataclass(frozen=True, slots=True)
class ExecutionCurrentReferenceSelectorItemV2:
    """Pin one source occurrence and its explicit simulated asset classification."""

    security_id: str
    asset_code: str
    source_code: str
    snapshot_id: UUID
    snapshot_content_hash: str
    snapshot_record_digest: str
    mapping_record_id: UUID
    mapping_id: str
    mapping_version: str
    mapping_content_hash: str
    mapping_record_digest: str
    simulated_asset_type: str

    def __post_init__(self) -> None:
        """Validate every source pin and require an explicit type token."""

        for name in ("security_id", "asset_code", "source_code", "mapping_id", "mapping_version"):
            _require_identity_token(getattr(self, name), name)
        _require_identity_token(self.simulated_asset_type, "simulated_asset_type")
        for name in ("snapshot_id", "mapping_record_id"):
            if type(getattr(self, name)) is not UUID:
                raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_UUID_INVALID")
        for name in (
            "snapshot_content_hash",
            "snapshot_record_digest",
            "mapping_content_hash",
            "mapping_record_digest",
        ):
            _require_identity_hash(getattr(self, name))

    def to_payload(self) -> dict[str, object]:
        """Return a fresh exact item payload without inferred fields."""

        self.__post_init__()
        return {
            "security_id": self.security_id,
            "asset_code": self.asset_code,
            "source_code": self.source_code,
            "snapshot_id": str(self.snapshot_id),
            "snapshot_content_hash": self.snapshot_content_hash,
            "snapshot_record_digest": self.snapshot_record_digest,
            "mapping_record_id": str(self.mapping_record_id),
            "mapping_id": self.mapping_id,
            "mapping_version": self.mapping_version,
            "mapping_content_hash": self.mapping_content_hash,
            "mapping_record_digest": self.mapping_record_digest,
            "simulated_asset_type": self.simulated_asset_type,
        }

    @classmethod
    def from_payload(cls, payload: object) -> ExecutionCurrentReferenceSelectorItemV2:
        """Strictly decode one exact selector item, including its required type."""

        expected = frozenset(
            {
                "security_id",
                "asset_code",
                "source_code",
                "snapshot_id",
                "snapshot_content_hash",
                "snapshot_record_digest",
                "mapping_record_id",
                "mapping_id",
                "mapping_version",
                "mapping_content_hash",
                "mapping_record_digest",
                "simulated_asset_type",
            }
        )
        fields = _exact_object(payload, expected)
        return cls(
            security_id=_require_identity_token(fields["security_id"], "security_id"),
            asset_code=_require_identity_token(fields["asset_code"], "asset_code"),
            source_code=_require_identity_token(fields["source_code"], "source_code"),
            snapshot_id=_parse_identity_uuid(fields["snapshot_id"]),
            snapshot_content_hash=_require_identity_hash(fields["snapshot_content_hash"]),
            snapshot_record_digest=_require_identity_hash(fields["snapshot_record_digest"]),
            mapping_record_id=_parse_identity_uuid(fields["mapping_record_id"]),
            mapping_id=_require_identity_token(fields["mapping_id"], "mapping_id"),
            mapping_version=_require_identity_token(fields["mapping_version"], "mapping_version"),
            mapping_content_hash=_require_identity_hash(fields["mapping_content_hash"]),
            mapping_record_digest=_require_identity_hash(fields["mapping_record_digest"]),
            simulated_asset_type=_require_identity_token(
                fields["simulated_asset_type"], "simulated_asset_type"
            ),
        )


@dataclass(frozen=True, slots=True)
class ExecutionCurrentReferenceSelectorV2:
    """Bind the complete active selector, including all typed selector items."""

    purpose: str
    max_local_reference_age_seconds: int
    items: tuple[ExecutionCurrentReferenceSelectorItemV2, ...]

    def __post_init__(self) -> None:
        """Validate the complete selector and reject contradictory duplicate keys."""

        if type(self.purpose) is not str or self.purpose != _SELECTOR_PURPOSE:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_PURPOSE_INVALID")
        if (
            type(self.max_local_reference_age_seconds) is not int
            or self.max_local_reference_age_seconds <= 0
        ):
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_AGE_INVALID")
        if type(self.items) is not tuple or any(
            type(item) is not ExecutionCurrentReferenceSelectorItemV2 for item in self.items
        ):
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_ITEMS_INVALID")
        security_ids: set[str] = set()
        asset_codes: set[str] = set()
        source_codes: set[str] = set()
        for item in self.items:
            item.__post_init__()
            if (
                item.security_id in security_ids
                or item.asset_code in asset_codes
                or item.source_code in source_codes
            ):
                raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_DUPLICATE_ITEM")
            security_ids.add(item.security_id)
            asset_codes.add(item.asset_code)
            source_codes.add(item.source_code)

    @property
    def content_hash(self) -> str:
        """Return the canonical hash of the complete versioned selector."""

        return _canonical_hash(self.to_payload())

    def to_payload(self) -> dict[str, object]:
        """Return a fresh complete selector payload, preserving item order."""

        self.__post_init__()
        return {
            "schema": _SELECTOR_V2_SCHEMA,
            "purpose": self.purpose,
            "max_local_reference_age_seconds": self.max_local_reference_age_seconds,
            "items": [item.to_payload() for item in self.items],
        }

    @classmethod
    def from_payload(cls, payload: object) -> ExecutionCurrentReferenceSelectorV2:
        """Strictly decode the v2 selector; v1 continues through its original parser."""

        fields = _exact_object(
            payload,
            frozenset(
                {
                    "schema",
                    "purpose",
                    "max_local_reference_age_seconds",
                    "items",
                }
            ),
        )
        if type(fields["schema"]) is not str or fields["schema"] != _SELECTOR_V2_SCHEMA:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_SCHEMA_INVALID")
        purpose = fields["purpose"]
        if type(purpose) is not str:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_PURPOSE_INVALID")
        age = fields["max_local_reference_age_seconds"]
        if type(age) is not int:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_AGE_INVALID")
        raw_items = fields["items"]
        if type(raw_items) is not list:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_ITEMS_INVALID")
        return cls(
            purpose=purpose,
            max_local_reference_age_seconds=age,
            items=tuple(
                ExecutionCurrentReferenceSelectorItemV2.from_payload(item) for item in raw_items
            ),
        )


@dataclass(frozen=True, slots=True)
class SimulatedInstrumentClassificationEvidenceV1:
    """Bind operator-selected type to the exact active selector and source receipt.

    This is a local simulation classification only. It does not authenticate a
    provider, qualify unknown source clocks, or grant decision/execution authority.
    """

    selector: ExecutionCurrentReferenceSelectorV2
    identity_evidence: ExecutionInstrumentIdentityEvidenceV2
    read_at: datetime

    def __post_init__(self) -> None:
        """Revalidate selector, source identity, and the exact read cutoff."""

        if type(self.selector) is not ExecutionCurrentReferenceSelectorV2:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_TYPE_INVALID")
        if type(self.identity_evidence) is not ExecutionInstrumentIdentityEvidenceV2:
            raise IdentityEvidenceValidationError("CLASSIFICATION_IDENTITY_TYPE_INVALID")
        self.selector.__post_init__()
        self.identity_evidence.__post_init__()
        cutoff = _normalize_identity_utc(self.read_at, "read_at")
        object.__setattr__(self, "read_at", cutoff)
        selection = self.identity_evidence.selection
        if (
            self.selector.content_hash != selection.selector_content_hash
            or self.selector.purpose != selection.purpose
            or self.selector.max_local_reference_age_seconds
            != selection.max_local_reference_age_seconds
            or cutoff != selection.selected_at
        ):
            raise IdentityEvidenceValidationError("CLASSIFICATION_SELECTOR_BINDING_MISMATCH")
        self.identity_evidence.validate_at(as_of=cutoff)
        if self._matching_items() is None:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SOURCE_BINDING_MISMATCH")

    def _matching_items(self) -> ExecutionCurrentReferenceSelectorItemV2 | None:
        """Return only the one selector item bound to every identity source pin."""

        identity = self.identity_evidence
        source = identity.source_evidence
        matches = tuple(
            item
            for item in self.selector.items
            if item.security_id == identity.security_id
            and item.asset_code == identity.asset_code
            and item.source_code == source.source_code
            and item.snapshot_id == source.snapshot_id
            and item.snapshot_content_hash == source.snapshot_content_hash
            and item.snapshot_record_digest == source.snapshot_record_digest
            and item.mapping_record_id == source.mapping_record_id
            and item.mapping_id == source.mapping_id
            and item.mapping_version == source.mapping_version
            and item.mapping_content_hash == source.mapping_content_hash
            and item.mapping_record_digest == source.mapping_record_digest
        )
        return matches[0] if len(matches) == 1 else None

    @property
    def simulated_asset_type(self) -> str:
        """Return the explicit operator-selected type for the bound exact item."""

        self.__post_init__()
        item = self._matching_items()
        if item is None:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SOURCE_BINDING_MISMATCH")
        return item.simulated_asset_type

    @property
    def content_hash(self) -> str:
        """Return the canonical hash of selector, source evidence, and read cutoff."""

        return _canonical_hash(self.to_payload())

    def validate_at(self, *, as_of: datetime) -> None:
        """Require this classification and nested source evidence at a later cutoff."""

        self.__post_init__()
        cutoff = _normalize_identity_utc(as_of, "as_of")
        if cutoff < self.read_at:
            raise IdentityEvidenceValidationError("CLASSIFICATION_NOT_KNOWN_AT_CUTOFF")
        self.identity_evidence.validate_at(as_of=cutoff)

    def to_payload(self) -> dict[str, object]:
        """Return a fresh canonical envelope retaining all selector and source pins."""

        self.__post_init__()
        return {
            "schema": _CLASSIFICATION_V1_SCHEMA,
            "selector": self.selector.to_payload(),
            "identity_evidence": self.identity_evidence.to_payload(),
            "read_at": _identity_utc_text(self.read_at),
        }

    @classmethod
    def from_payload(cls, payload: object) -> SimulatedInstrumentClassificationEvidenceV1:
        """Strictly decode one complete selector-to-source classification envelope."""

        fields = _exact_object(
            payload,
            frozenset({"schema", "selector", "identity_evidence", "read_at"}),
        )
        if type(fields["schema"]) is not str or fields["schema"] != _CLASSIFICATION_V1_SCHEMA:
            raise IdentityEvidenceValidationError("CLASSIFICATION_SCHEMA_INVALID")
        return cls(
            selector=ExecutionCurrentReferenceSelectorV2.from_payload(fields["selector"]),
            identity_evidence=ExecutionInstrumentIdentityEvidenceV2.from_payload(
                fields["identity_evidence"]
            ),
            read_at=_parse_identity_utc(fields["read_at"]),
        )
