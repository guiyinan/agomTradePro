"""Bind explicit simulation tax scope to retained instrument facts.

The current selector remains a local simulation classification. This check
does not authenticate a taxpayer or promote Data Center reference-only data
into real trading or legal authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from apps.data_center.domain.instrument_reference_snapshot import (
    InstrumentReferenceSnapshotError,
    InstrumentReferenceSnapshotRecord,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    IdentityEvidenceValidationError,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxPolicyScope,
)
from core.exceptions import BusinessLogicError


def _blocked(message: str) -> BusinessLogicError:
    """Return a stable block without instrument or currency inference."""
    return BusinessLogicError(message, code="SIMULATED_TAX_INSTRUMENT_BLOCKED")


@dataclass(frozen=True, slots=True)
class SimulatedDividendTaxInstrumentEvidence:
    """Stable current model/source identity with its original local expiry."""

    semantic_sha256: str
    valid_until: datetime

    @property
    def must_not_use_as_real_tax_proof(self) -> Literal[True]:
        """Retain the simulation-only interpretation of the configured scope."""
        return True


def qualify_simulated_dividend_tax_instrument(
    *,
    scope: SimulatedDividendTaxPolicyScope,
    classification: SimulatedInstrumentClassificationEvidenceV1,
    snapshot: InstrumentReferenceSnapshotRecord,
    record_date: date,
    as_of: datetime,
) -> SimulatedDividendTaxInstrumentEvidence:
    """Verify exact current selector pins, CNY and listing coverage at record date.

    The explicit candidate supplies the simulated persona and instrument kind;
    neither is guessed from an asset code. Actual source currency and listing
    dates independently constrain that declaration. No missing date or currency
    receives a default. Read clocks are excluded from stable semantic identity.
    """
    if (
        type(scope) is not SimulatedDividendTaxPolicyScope
        or type(classification) is not SimulatedInstrumentClassificationEvidenceV1
        or type(snapshot) is not InstrumentReferenceSnapshotRecord
        or type(record_date) is not date
        or type(as_of) is not datetime
        or as_of.tzinfo is None
    ):
        raise _blocked("exact typed model, current classification and native snapshot are required")
    try:
        if as_of.utcoffset() is None:
            raise _blocked("instrument cutoff must be timezone-aware")
        current = as_of.astimezone(UTC)
        scope.__post_init__()
        scope.verify_for(
            account_kind="simulated",
            physical_account_id=scope.physical_account_id,
            canonical_account_id=scope.canonical_account_id,
            owner_user_id=scope.owner_user_id,
            security_id=scope.security_id,
            asset_code=scope.asset_code,
            exchange=scope.exchange,
            persona=scope.persona,
            instrument_kind=scope.instrument_kind,
            record_date=record_date,
            as_of=current,
        )
        classification.validate_at(as_of=current)
        snapshot.__post_init__()
        snapshot.content.__post_init__()
        identity = classification.identity_evidence
        source = identity.source_evidence
        mapping = snapshot.mapping_record
        if (
            identity.security_id != scope.security_id
            or identity.asset_code != scope.asset_code
            or source.snapshot_id != snapshot.snapshot_id
            or source.snapshot_content_hash != snapshot.content_hash
            or source.snapshot_record_digest != snapshot.record_digest
            or source.snapshot_recorded_at != snapshot.recorded_at
            or source.mapping_record_id != mapping.mapping_record_id
            or source.mapping_content_hash != mapping.content_hash
            or source.mapping_record_digest != mapping.record_digest
            or source.mapping_id != mapping.content.mapping_id
            or source.mapping_version != mapping.content.mapping_version
        ):
            raise _blocked("current instrument identity differs from exact native snapshot pins")
        facts = snapshot.content.classify_security(source.source_code)
        if (
            facts is None
            or facts.blocked_reason is not None
            or facts.rule_market != scope.exchange.value
            or facts.rule_market != source.rule_market
            or facts.board != source.board
            or facts.source_exchange != source.source_exchange
            or facts.source_market != source.source_market
            or facts.source_currency != scope.currency.value
            or facts.list_date is None
            or facts.list_date > record_date
            or (facts.delist_date is not None and facts.delist_date <= record_date)
        ):
            raise _blocked(
                "native listing, exchange or currency does not support explicit model scope"
            )
        matching = tuple(
            row
            for group in snapshot.content.fetch_rounds
            for row in group.candidate.records
            if row.ts_code == source.source_code
            and row.occurrence_id == identity.source_occurrence_id
        )
        occurrences = tuple(
            row
            for group in snapshot.content.fetch_rounds
            for row in group.candidate.occurrences
            if row.occurrence_id == identity.source_occurrence_id
        )
        if (
            len(matching) != 1
            or len(occurrences) != 1
            or occurrences[0].response_completed_at != identity.reference_response_completed_at
        ):
            raise _blocked(
                "current instrument occurrence is absent or ambiguous in retained source"
            )
        payload: dict[str, object] = {
            "schema": "simulated-dividend-tax-instrument.v1",
            "scope_sha256": scope.semantic_sha256,
            "selector_sha256": classification.selector.content_hash,
            "profile_id": identity.selection.profile_id,
            "profile_sha256": identity.selection.profile_content_hash,
            "runtime_snapshot_id": identity.selection.runtime_snapshot_id,
            "runtime_snapshot_sha256": identity.selection.runtime_snapshot_hash,
            "snapshot_id": str(snapshot.snapshot_id),
            "snapshot_digest": snapshot.record_digest,
            "occurrence_id": str(identity.source_occurrence_id),
            "record_date": record_date.isoformat(),
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return SimulatedDividendTaxInstrumentEvidence(
            semantic_sha256=digest,
            valid_until=min(scope.valid_until, source.identity_valid_until),
        )
    except (
        DeferredDividendTaxValidationError,
        IdentityEvidenceValidationError,
        InstrumentReferenceSnapshotError,
        OverflowError,
        ValueError,
    ) as error:
        raise _blocked("instrument or current model evidence failed exact validation") from error


__all__ = ["SimulatedDividendTaxInstrumentEvidence", "qualify_simulated_dividend_tax_instrument"]
