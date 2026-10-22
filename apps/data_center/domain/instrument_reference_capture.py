"""Immutable source-only capture requests and fencing-chain values.

The request binds existing provider and mapping contracts. Claim epochs carry
only a digest of an opaque in-memory capability; they are not authentication
or provider attestations.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceMappingRecord,
)
from apps.data_center.domain.instrument_reference_source import (
    InstrumentReferenceProviderContract,
)

_REQUEST_SCHEMA = "instrument-reference-capture-request.v1"
_CLAIM_SCHEMA = "instrument-reference-capture-claim.v1"
_CLAIM_MARKER_PREFIX = "ircap.v1.claim.marker."
_CLAIM_PAYLOAD_PREFIX = "ircap.v1.claim.payload."
_CLAIM_MARKER_VALUE = "v1"
_MAX_CHECKPOINT_VALUE_BYTES = 500
_MAX_CLAIM_EPOCH = 10**20
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MARKER_NAME = re.compile(r"^ircap\.v1\.claim\.marker\.([0-9]{20})$")
_PAYLOAD_NAME = re.compile(r"^ircap\.v1\.claim\.payload\.([0-9]{20})$")


class InstrumentReferenceCaptureContractError(ValueError):
    """Stable error for invalid capture identity or fencing evidence."""

    def __init__(self, code: str) -> None:
        """Create a validation error containing only a stable reason code."""

        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureScope:
    """One explicit exchange/list-status request within a provider contract."""

    exchange: str
    list_status: str

    def __post_init__(self) -> None:
        """Reject empty, padded, non-text, or control-bearing scope values."""

        _require_identifier(self.exchange, 32, "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_INVALID")
        _require_identifier(self.list_status, 32, "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_INVALID")


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureIdentity:
    """Stable run, batch, idempotency, and occurrence identities for a request."""

    capture_id: UUID
    run_id: UUID
    batch_id: UUID
    idempotency_key: str

    def __post_init__(self) -> None:
        """Recompute deterministic IDs so callers cannot substitute identities."""

        if type(self.capture_id) is not UUID or self.run_id != self.capture_id:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_IDENTITY_INVALID"
            )
        if self.batch_id != _batch_id(self.capture_id):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_IDENTITY_INVALID"
            )
        if self.idempotency_key != _idempotency_key(self.capture_id):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_IDENTITY_INVALID"
            )

    @classmethod
    def for_capture(cls, capture_id: UUID) -> InstrumentReferenceCaptureIdentity:
        """Build stable control-plane identifiers from one caller-owned UUID."""

        if type(capture_id) is not UUID:
            raise InstrumentReferenceCaptureContractError("INSTRUMENT_REFERENCE_CAPTURE_ID_INVALID")
        return cls(
            capture_id=capture_id,
            run_id=capture_id,
            batch_id=_batch_id(capture_id),
            idempotency_key=_idempotency_key(capture_id),
        )

    def occurrence_id(self, scope: InstrumentReferenceCaptureScope) -> UUID:
        """Derive one repeatable occurrence identity for an allowed scope."""

        if type(scope) is not InstrumentReferenceCaptureScope:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_INVALID"
            )
        name = _canonical_json(
            {
                "schema": "instrument-reference-capture-occurrence.v1",
                "capture_id": str(self.capture_id),
                "exchange": scope.exchange,
                "list_status": scope.list_status,
            }
        )
        return uuid5(NAMESPACE_URL, name)


@dataclass(frozen=True, slots=True)
class InstrumentReferenceCaptureRequest:
    """Immutable request descriptor whose digest excludes retry controls.

    Route fields must be stable, non-secret identifiers rather than endpoint
    URLs or credential material.
    ``actor_provenance`` is an asserted source label only; it never proves
    human authentication. Credentials, provider body bytes, and local clocks
    are intentionally absent from this request value.
    """

    capture_id: UUID
    provider_contract: InstrumentReferenceProviderContract
    provider_route_id: str
    provider_route_revision: str
    provider_configuration_id: int
    mapping_record: InstrumentReferenceMappingRecord
    actor_provenance: str | None = field(default=None, repr=False)
    source_only: Literal[True] = True
    repository_alias: Literal["default"] = "default"

    def __post_init__(self) -> None:
        """Validate exact existing contracts before producing stable identity."""

        if type(self.capture_id) is not UUID:
            raise InstrumentReferenceCaptureContractError("INSTRUMENT_REFERENCE_CAPTURE_ID_INVALID")
        if type(self.provider_contract) is not InstrumentReferenceProviderContract:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CONTRACT_INVALID"
            )
        if type(self.mapping_record) is not InstrumentReferenceMappingRecord:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_INVALID"
            )
        _require_identifier(
            self.provider_route_id, 160, "INSTRUMENT_REFERENCE_CAPTURE_ROUTE_INVALID"
        )
        _require_identifier(
            self.provider_route_revision, 160, "INSTRUMENT_REFERENCE_CAPTURE_ROUTE_INVALID"
        )
        if type(self.provider_configuration_id) is not int or self.provider_configuration_id < 1:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PROVIDER_CONFIGURATION_INVALID"
            )
        if self.actor_provenance is not None:
            _require_identifier(
                self.actor_provenance,
                240,
                "INSTRUMENT_REFERENCE_CAPTURE_ACTOR_INVALID",
            )
        if type(self.source_only) is not bool or self.source_only is not True:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SOURCE_ONLY_REQUIRED"
            )
        if type(self.repository_alias) is not str or self.repository_alias != "default":
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_ALIAS_INVALID"
            )
        mapped_exchanges = {
            exchange
            for exchange, _suffix in (
                self.mapping_record.content.source_crosswalk.exchange_suffix_pairs
            )
        }
        if not set(self.provider_contract.exchange_scope).issubset(mapped_exchanges):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MAPPING_SCOPE_MISMATCH"
            )

    @property
    def identity(self) -> InstrumentReferenceCaptureIdentity:
        """Return deterministic control-plane IDs for this capture UUID."""

        return InstrumentReferenceCaptureIdentity.for_capture(self.capture_id)

    @property
    def scopes(self) -> tuple[InstrumentReferenceCaptureScope, ...]:
        """Return the contract's explicit exchange/status Cartesian scope."""

        return tuple(
            InstrumentReferenceCaptureScope(exchange, status)
            for exchange in self.provider_contract.exchange_scope
            for status in self.provider_contract.list_status_scope
        )

    @property
    def request_payload(self) -> dict[str, object]:
        """Return the canonical, secret-free immutable request descriptor."""

        contract = self.provider_contract
        mapping = self.mapping_record
        return {
            "schema": _REQUEST_SCHEMA,
            "capture_id": str(self.capture_id),
            "provider_route_id": self.provider_route_id,
            "provider_route_revision": self.provider_route_revision,
            "provider_configuration_id": self.provider_configuration_id,
            "provider_contract": {
                "contract_id": contract.contract_id,
                "contract_version": contract.contract_version,
                "provider_name": contract.provider_name,
                "dataset_key": contract.dataset_key,
                "api_name": contract.api_name,
                "fields": list(contract.fields),
                "exchange_scope": list(contract.exchange_scope),
                "list_status_scope": list(contract.list_status_scope),
                "content_hash": contract.content_hash,
            },
            "mapping": {
                "mapping_record_id": str(mapping.mapping_record_id),
                "mapping_content_hash": mapping.content_hash,
                "mapping_record_digest": mapping.record_digest,
            },
            "scopes": [
                {"exchange": scope.exchange, "list_status": scope.list_status}
                for scope in self.scopes
            ],
            "repository_alias": self.repository_alias,
            "source_only": self.source_only,
            "actor_provenance": self.actor_provenance,
        }

    @property
    def canonical_request(self) -> str:
        """Return the canonical JSON bytes as text for durable request evidence."""

        return _canonical_json(self.request_payload)

    @property
    def request_sha256(self) -> str:
        """Hash all immutable request inputs without including resume intent."""

        return hashlib.sha256(self.canonical_request.encode("ascii")).hexdigest()

    def occurrence_id(self, scope: InstrumentReferenceCaptureScope) -> UUID:
        """Return a stable occurrence ID only for a scope in this request."""

        if scope not in self.scopes:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_SCOPE_OUTSIDE_REQUEST"
            )
        return self.identity.occurrence_id(scope)


@dataclass(frozen=True, slots=True)
class CaptureOwnerCapability:
    """Opaque 256-bit in-process fencing capability, excluded from repr."""

    _token: bytes = field(repr=False)

    def __post_init__(self) -> None:
        """Require an exact 32-byte token without exposing it in errors."""

        if type(self._token) is not bytes or len(self._token) != 32:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CAPABILITY_INVALID"
            )

    @classmethod
    def generate(cls) -> CaptureOwnerCapability:
        """Generate a fresh in-memory capability using the standard library."""

        return cls(secrets.token_bytes(32))

    @property
    def token_sha256(self) -> str:
        """Return the only capability representation allowed in checkpoint data."""

        return hashlib.sha256(self._token).hexdigest()

    def matches_digest(self, digest: str) -> bool:
        """Compare a stored owner-token hash without revealing token bytes."""

        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            return False
        return hmac.compare_digest(self.token_sha256, digest)


@dataclass(frozen=True, slots=True)
class CaptureClaimEpoch:
    """One canonical, hash-linked claim epoch with no raw owner capability."""

    epoch: int
    request_sha256: str
    owner_token_sha256: str
    previous_claim_sha256: str | None
    claim_sha256: str

    def __post_init__(self) -> None:
        """Check exact scalar types, epoch chronology, and the claim seal."""

        if type(self.epoch) is not int or not 1 <= self.epoch < _MAX_CLAIM_EPOCH:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            )
        _require_digest(self.request_sha256, "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID")
        _require_digest(self.owner_token_sha256, "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID")
        if self.epoch == 1:
            if self.previous_claim_sha256 is not None:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
                )
        else:
            _require_digest(
                self.previous_claim_sha256,
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID",
            )
        _require_digest(self.claim_sha256, "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID")
        if self.claim_sha256 != self._computed_claim_sha256():
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_SEAL_MISMATCH"
            )

    @classmethod
    def issue(
        cls,
        epoch: int,
        request_sha256: str,
        previous_claim_sha256: str | None,
        capability: CaptureOwnerCapability,
    ) -> CaptureClaimEpoch:
        """Create an epoch bound to a request, previous seal, and token hash."""

        if type(capability) is not CaptureOwnerCapability:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CAPABILITY_INVALID"
            )
        if type(epoch) is not int or not 1 <= epoch < _MAX_CLAIM_EPOCH:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            )
        owner_hash = capability.token_sha256
        payload = {
            "schema": _CLAIM_SCHEMA,
            "epoch": epoch,
            "request_sha256": request_sha256,
            "owner_token_sha256": owner_hash,
            "previous_claim_sha256": previous_claim_sha256,
        }
        claim_hash = hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()
        return cls(
            epoch=epoch,
            request_sha256=request_sha256,
            owner_token_sha256=owner_hash,
            previous_claim_sha256=previous_claim_sha256,
            claim_sha256=claim_hash,
        )

    def to_payload(self) -> dict[str, object]:
        """Return safe canonical fields; never include the capability bytes."""

        return {
            "schema": _CLAIM_SCHEMA,
            "epoch": self.epoch,
            "request_sha256": self.request_sha256,
            "owner_token_sha256": self.owner_token_sha256,
            "previous_claim_sha256": self.previous_claim_sha256,
            "claim_sha256": self.claim_sha256,
        }

    def to_checkpoint_value(self) -> str:
        """Encode canonical ASCII checkpoint JSON within the schema's 500-byte cap."""

        encoded = _canonical_json(self.to_payload())
        if len(encoded.encode("ascii")) > _MAX_CHECKPOINT_VALUE_BYTES:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_VALUE_TOO_LONG"
            )
        return encoded

    @classmethod
    def from_checkpoint_value(cls, value: object) -> CaptureClaimEpoch:
        """Decode one exact canonical checkpoint value and verify its digest."""

        if type(value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            )
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            ) from exc
        if len(encoded) > _MAX_CHECKPOINT_VALUE_BYTES:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CHECKPOINT_VALUE_TOO_LONG"
            )
        try:
            parsed_value: object = json.loads(value, object_pairs_hook=_unique_json_object)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            ) from exc
        if type(parsed_value) is not dict:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            )
        parsed = cast(dict[str, object], parsed_value)
        expected = {
            "schema",
            "epoch",
            "request_sha256",
            "owner_token_sha256",
            "previous_claim_sha256",
            "claim_sha256",
        }
        if (
            set(parsed) != expected
            or type(parsed["schema"]) is not str
            or parsed["schema"] != _CLAIM_SCHEMA
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            )
        epoch_value = parsed["epoch"]
        if type(epoch_value) is not int:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            )
        previous_value = parsed["previous_claim_sha256"]
        if previous_value is not None and type(previous_value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID"
            )
        previous: str | None = previous_value if type(previous_value) is str else None
        if _canonical_json(cast(Mapping[str, object], parsed)) != value:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_NONCANONICAL"
            )
        return cls(
            epoch=epoch_value,
            request_sha256=_payload_string(parsed, "request_sha256"),
            owner_token_sha256=_payload_string(parsed, "owner_token_sha256"),
            previous_claim_sha256=previous,
            claim_sha256=_payload_string(parsed, "claim_sha256"),
        )

    def _computed_claim_sha256(self) -> str:
        """Compute the seal over every claim field except its own digest."""

        material = {
            "schema": _CLAIM_SCHEMA,
            "epoch": self.epoch,
            "request_sha256": self.request_sha256,
            "owner_token_sha256": self.owner_token_sha256,
            "previous_claim_sha256": self.previous_claim_sha256,
        }
        return hashlib.sha256(_canonical_json(material).encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class CaptureClaimMarker:
    """Validated fixed marker paired with one claim payload checkpoint."""

    epoch: int
    cursor_name: str
    cursor_value: str

    def __post_init__(self) -> None:
        """Require the exact reserved name and fixed marker value for its epoch."""

        if type(self.epoch) is not int or not 1 <= self.epoch < _MAX_CLAIM_EPOCH:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID"
            )
        if self.cursor_name != _marker_name(self.epoch) or self.cursor_value != _CLAIM_MARKER_VALUE:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID"
            )

    @classmethod
    def for_epoch(cls, epoch: int) -> CaptureClaimMarker:
        """Build the fixed marker expected beside one claim payload row."""

        return cls(epoch, _marker_name(epoch), _CLAIM_MARKER_VALUE)

    @classmethod
    def from_checkpoint(cls, cursor_name: object, cursor_value: object) -> CaptureClaimMarker:
        """Narrow ORM-boundary checkpoint strings into one exact marker."""

        if type(cursor_name) is not str or type(cursor_value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID"
            )
        match = _MARKER_NAME.fullmatch(cursor_name)
        if match is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID"
            )
        try:
            epoch = int(match.group(1))
        except ValueError as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID"
            ) from exc
        return cls(epoch, cursor_name, cursor_value)


@dataclass(frozen=True, slots=True)
class CaptureClaimPayload:
    """Validated payload checkpoint paired with one claim marker epoch."""

    epoch: int
    cursor_name: str
    cursor_value: str

    def __post_init__(self) -> None:
        """Require the reserved payload name and a claim matching its epoch."""

        if (
            type(self.epoch) is not int
            or self.cursor_name != _payload_name(self.epoch)
            or type(self.cursor_value) is not str
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
            )
        claim = CaptureClaimEpoch.from_checkpoint_value(self.cursor_value)
        if claim.epoch != self.epoch:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
            )

    @classmethod
    def for_claim(cls, claim: CaptureClaimEpoch) -> CaptureClaimPayload:
        """Build the fixed payload checkpoint name for one safe claim value."""

        if type(claim) is not CaptureClaimEpoch:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
            )
        return cls(claim.epoch, _payload_name(claim.epoch), claim.to_checkpoint_value())

    @classmethod
    def from_checkpoint(cls, cursor_name: object, cursor_value: object) -> CaptureClaimPayload:
        """Narrow a selected payload checkpoint row and bind its name to its value."""

        if type(cursor_name) is not str or type(cursor_value) is not str:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
            )
        match = _PAYLOAD_NAME.fullmatch(cursor_name)
        if match is None:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
            )
        try:
            epoch = int(match.group(1))
        except ValueError as exc:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
            ) from exc
        return cls(epoch, cursor_name, cursor_value)

    @property
    def claim(self) -> CaptureClaimEpoch:
        """Return the strictly decoded claim carried by this payload row."""

        return CaptureClaimEpoch.from_checkpoint_value(self.cursor_value)


@dataclass(frozen=True, slots=True)
class CaptureClaimHistory:
    """A complete marker/payload view validated as one linear claim chain."""

    request_sha256: str
    markers: tuple[CaptureClaimMarker, ...]
    payloads: tuple[CaptureClaimPayload, ...]

    def __post_init__(self) -> None:
        """Reject missing, duplicate, forked, gapped, or mismatched claim rows."""

        _require_digest(self.request_sha256, "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_HISTORY_INVALID")
        if type(self.markers) is not tuple or type(self.payloads) is not tuple:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_HISTORY_INVALID"
            )
        if any(type(marker) is not CaptureClaimMarker for marker in self.markers):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_HISTORY_INVALID"
            )
        if any(type(payload) is not CaptureClaimPayload for payload in self.payloads):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_HISTORY_INVALID"
            )
        marker_epochs = [marker.epoch for marker in self.markers]
        claims = tuple(payload.claim for payload in self.payloads)
        claim_epochs = [claim.epoch for claim in claims]
        if len(marker_epochs) != len(set(marker_epochs)) or len(claim_epochs) != len(
            set(claim_epochs)
        ):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_DUPLICATE_EPOCH"
            )
        if set(marker_epochs) != set(claim_epochs):
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_MARKER_PAYLOAD_MISMATCH"
            )
        ordered = sorted(claims, key=lambda claim: claim.epoch)
        expected_epochs = list(range(1, len(ordered) + 1))
        if [claim.epoch for claim in ordered] != expected_epochs:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_EPOCH_GAP"
            )
        marker_by_epoch = {marker.epoch: marker for marker in self.markers}
        previous_digest: str | None = None
        for claim in ordered:
            if marker_by_epoch[claim.epoch] != CaptureClaimMarker.for_epoch(claim.epoch):
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID"
                )
            if claim.request_sha256 != self.request_sha256:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_REQUEST_DIGEST_MISMATCH"
                )
            if claim.previous_claim_sha256 != previous_digest:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_CHAIN_INVALID"
                )
            previous_digest = claim.claim_sha256

    @classmethod
    def from_checkpoint_rows(
        cls,
        request_sha256: str,
        marker_rows: tuple[tuple[object, object], ...],
        payload_rows: tuple[tuple[object, object], ...],
    ) -> CaptureClaimHistory:
        """Decode fully selected checkpoint rows without depending on an ORM."""

        if type(marker_rows) is not tuple or type(payload_rows) is not tuple:
            raise InstrumentReferenceCaptureContractError(
                "INSTRUMENT_REFERENCE_CAPTURE_CLAIM_HISTORY_INVALID"
            )
        markers: list[CaptureClaimMarker] = []
        payloads: list[CaptureClaimPayload] = []
        for row in marker_rows:
            if type(row) is not tuple or len(row) != 2:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID"
                )
            markers.append(CaptureClaimMarker.from_checkpoint(row[0], row[1]))
        for row in payload_rows:
            if type(row) is not tuple or len(row) != 2:
                raise InstrumentReferenceCaptureContractError(
                    "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
                )
            payloads.append(CaptureClaimPayload.from_checkpoint(row[0], row[1]))
        return cls(request_sha256, tuple(markers), tuple(payloads))

    @property
    def epochs(self) -> tuple[CaptureClaimEpoch, ...]:
        """Return the decoded payload claims in checkpoint-selection order."""

        return tuple(payload.claim for payload in self.payloads)

    @property
    def next_epoch(self) -> int:
        """Return the next append-only epoch after a validated complete prefix."""

        return len(self.payloads) + 1

    @property
    def latest(self) -> CaptureClaimEpoch | None:
        """Return the latest validated claim, preserving an explicit empty history."""

        if not self.payloads:
            return None
        return max((payload.claim for payload in self.payloads), key=lambda claim: claim.epoch)


def _batch_id(capture_id: UUID) -> UUID:
    """Derive the stable batch UUID from a capture ID and protocol version."""

    return uuid5(
        NAMESPACE_URL,
        f"agomtradepro:data-center:instrument-reference-capture:v1:batch:{capture_id}",
    )


def _idempotency_key(capture_id: UUID) -> str:
    """Return a bounded unique key for the existing generic sync batch row."""

    return f"instrument-reference-capture.v1:{capture_id}"


def _marker_name(epoch: int) -> str:
    """Return a fixed-width marker name that sorts in epoch order."""

    if type(epoch) is not int or not 1 <= epoch < _MAX_CLAIM_EPOCH:
        raise InstrumentReferenceCaptureContractError("INSTRUMENT_REFERENCE_CAPTURE_MARKER_INVALID")
    return f"{_CLAIM_MARKER_PREFIX}{epoch:020d}"


def _payload_name(epoch: int) -> str:
    """Return the fixed-width payload name associated with one claim epoch."""

    if type(epoch) is not int or not 1 <= epoch < _MAX_CLAIM_EPOCH:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_CHECKPOINT_INVALID"
        )
    return f"{_CLAIM_PAYLOAD_PREFIX}{epoch:020d}"


def _canonical_json(payload: Mapping[str, object]) -> str:
    """Serialize a bounded canonical ASCII JSON object or raise a typed error."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise InstrumentReferenceCaptureContractError(
            "INSTRUMENT_REFERENCE_CAPTURE_PAYLOAD_INVALID"
        ) from exc


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys when loading a checkpoint payload."""

    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate checkpoint key")
        value[key] = item
    return value


def _require_identifier(value: object, maximum: int, code: str) -> None:
    """Require bounded exact text without padding or control characters."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise InstrumentReferenceCaptureContractError(code)


def _require_digest(value: object, code: str) -> None:
    """Require one lowercase SHA-256 hex digest without coercion."""

    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise InstrumentReferenceCaptureContractError(code)


def _payload_string(payload: Mapping[str, object], key: str) -> str:
    """Narrow one JSON string field without coercion."""

    value = payload.get(key)
    if type(value) is not str:
        raise InstrumentReferenceCaptureContractError("INSTRUMENT_REFERENCE_CAPTURE_CLAIM_INVALID")
    return value


__all__ = [
    "CaptureClaimEpoch",
    "CaptureClaimHistory",
    "CaptureClaimMarker",
    "CaptureClaimPayload",
    "CaptureOwnerCapability",
    "InstrumentReferenceCaptureContractError",
    "InstrumentReferenceCaptureIdentity",
    "InstrumentReferenceCaptureRequest",
    "InstrumentReferenceCaptureScope",
]
