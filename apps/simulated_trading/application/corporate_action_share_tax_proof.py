"""Retain complete finite simulated share-tax qualification with its original clocks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from apps.simulated_trading.application.corporate_action_share_tax_model import (
    CurrentShareCapitalTaxModel,
    ShareCapitalTaxModelQuery,
    _digest,
    _invalid,
    _token,
    _utc,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStageRequest


def _instrument_reference_digest(value: object, field_name: str) -> str:
    """Keep exact native sha256-prefixed pins and previously retained bare pins.

    Current instrument readers compare these values with the actual native
    snapshot before constructing this proof. Historical constructor readback
    preserves the original representation; it never strips or renews a pin.
    """
    if type(value) is not str or re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", value) is None:
        raise _invalid(f"{field_name} must retain a canonical instrument SHA-256 pin")
    return value


@dataclass(frozen=True, slots=True)
class ShareCapitalTaxQualificationProof:
    """One server-built model plus actual configuration, source and instrument witnesses.

    This is simulation evidence only. It neither authenticates an actual taxpayer
    nor grants financial authority independently of the locked owner transaction.
    """

    query: ShareCapitalTaxModelQuery
    model: CurrentShareCapitalTaxModel
    environment: str
    configuration_identity_sha256: str
    source_configuration_sha256: str
    source_bundle_sha256: str
    capture_manifest_sha256: str
    instrument_semantic_sha256: str
    instrument_snapshot_id: str
    instrument_snapshot_content_sha256: str
    instrument_snapshot_record_digest: str
    instrument_occurrence_id: str
    instrument_response_completed_at: datetime
    checked_at: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        """Reject incomplete original evidence and clocks outside its finite window."""
        if (
            type(self.query) is not ShareCapitalTaxModelQuery
            or type(self.model) is not CurrentShareCapitalTaxModel
        ):
            raise _invalid("share model proof requires exact typed query and model")
        self.model.verify_for(self.query, as_of=self.checked_at)
        for name in ("environment", "instrument_snapshot_id", "instrument_occurrence_id"):
            _token(getattr(self, name), name)
        for name in (
            "configuration_identity_sha256",
            "source_configuration_sha256",
            "source_bundle_sha256",
            "capture_manifest_sha256",
            "instrument_semantic_sha256",
        ):
            _digest(getattr(self, name), name)
        for name in ("instrument_snapshot_content_sha256", "instrument_snapshot_record_digest"):
            _instrument_reference_digest(getattr(self, name), name)
        checked = _utc(self.checked_at, "checked_at")
        completed = _utc(self.instrument_response_completed_at, "instrument_response_completed_at")
        deadline = _utc(self.valid_until, "valid_until")
        if not completed <= self.model.known_at <= checked < deadline <= self.model.valid_until:
            raise _invalid("share model proof clocks differ from original instrument/model bounds")

    def verify_for(self, request: CorporateActionStageRequest, *, as_of: datetime) -> None:
        """Bind every immutable posting field and prohibit use beyond the original deadline."""
        self.__post_init__()
        request.__post_init__()
        cutoff = _utc(as_of, "as_of")
        self.model.verify_for(self.query, as_of=cutoff)
        if not self.checked_at <= cutoff < self.valid_until:
            raise _invalid("share model proof expired or was not yet checked")
        pairs = (
            ("physical_account_id", "account_id"),
            ("owner_user_id", "owner_user_id"),
            ("security_id", "security_id"),
            ("asset_code", "asset_code"),
            ("source_namespace", "source_namespace"),
            ("source_record_id", "source_record_id"),
            ("source_event_id", "source_event_id"),
            ("source_revision_id", "source_revision_id"),
            ("source_payload_sha256", "source_payload_sha256"),
            ("action_kind", "action_kind"),
            ("stage", "stage"),
            ("entry_kind", "entry_kind"),
            ("record_date", "record_date"),
            ("effective_date", "effective_date"),
            ("stage_date", "stage_date"),
            ("source_observed_at", "source_observed_at"),
        )
        if any(getattr(self.query, left) != getattr(request, right) for left, right in pairs):
            raise _invalid("share model proof differs from the exact posting request")
        if request.tax_treatment != "not_applicable":
            raise _invalid("the explicit stock-premium model cannot qualify another tax treatment")

    @property
    def selection_sha256(self) -> str:
        """Bind all original facts while excluding only the two repeated read clocks."""
        self.__post_init__()
        payload = asdict(self)
        del payload["checked_at"]
        del payload["model"]["checked_at"]
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                default=_original_scalar,
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
        ).hexdigest()

    @property
    def simulation_only(self) -> Literal[True]:
        """Retain the model's explicit simulation scope."""
        return True

    @property
    def must_not_use_for_real_tax_decision(self) -> Literal[True]:
        """Preserve the prohibition on real-holder and real-tax qualification."""
        return True


def _original_scalar(value: object) -> str:
    """Serialize only original immutable date/time values in the stable witness digest."""
    from datetime import date

    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError("unsupported share proof scalar")
