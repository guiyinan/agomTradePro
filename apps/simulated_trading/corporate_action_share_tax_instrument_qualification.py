"""Constrain a declared capital-transfer simulation by actual retained instrument facts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from apps.data_center.domain.instrument_reference_snapshot import InstrumentReferenceSnapshotRecord
from apps.simulated_trading.application.corporate_action_share_tax_model import (
    ShareCapitalTaxModelQuery,
)
from apps.simulated_trading.corporate_action_share_tax_policy_composition import (
    ConfiguredShareCapitalTaxModelPolicy,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from core.exceptions import BusinessLogicError


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "当前证券原始币种、上市资料或模拟模型声明不一致。",
        code="SHARE_CAPITAL_TAX_INSTRUMENT_UNVERIFIED",
    )


@dataclass(frozen=True, slots=True)
class ShareCapitalTaxInstrumentEvidence:
    """Original source locator and current-model fingerprint, never real tax eligibility."""

    semantic_sha256: str
    snapshot_id: str
    snapshot_content_sha256: str
    snapshot_record_digest: str
    occurrence_id: str
    reference_response_completed_at: datetime
    known_at: datetime
    valid_until: datetime

    @property
    def must_not_use_for_real_tax_decision(self) -> Literal[True]:
        """Retain the simulation-only interpretation of the declared scope."""
        return True


def qualify_share_capital_tax_instrument(
    *,
    query: ShareCapitalTaxModelQuery,
    configured: ConfiguredShareCapitalTaxModelPolicy,
    classification: SimulatedInstrumentClassificationEvidenceV1,
    snapshot: InstrumentReferenceSnapshotRecord,
    as_of: datetime,
) -> ShareCapitalTaxInstrumentEvidence:
    """Verify actual snapshot/mapping/occurrence, listing dates, currency and model scope."""
    try:
        if (
            type(query) is not ShareCapitalTaxModelQuery
            or type(configured) is not ConfiguredShareCapitalTaxModelPolicy
            or type(classification) is not SimulatedInstrumentClassificationEvidenceV1
            or type(snapshot) is not InstrumentReferenceSnapshotRecord
        ):
            raise _blocked()
        configured.verify_for(query, as_of=as_of)
        classification.validate_at(as_of=as_of)
        snapshot.__post_init__()
        snapshot.content.__post_init__()
        identity = classification.identity_evidence
        native = identity.source_evidence
        mapping = snapshot.mapping_record
        selection = identity.selection
        configuration = configured.configuration
        if (
            classification.read_at != as_of
            or query.source_observed_at > as_of
            or identity.security_id != query.security_id
            or identity.asset_code != query.asset_code
            or classification.simulated_asset_type != configured.simulated_asset_type
            or native.snapshot_id != snapshot.snapshot_id
            or native.snapshot_content_hash != snapshot.content_hash
            or native.snapshot_record_digest != snapshot.record_digest
            or native.snapshot_recorded_at != snapshot.recorded_at
            or native.mapping_record_id != mapping.mapping_record_id
            or native.mapping_content_hash != mapping.content_hash
            or native.mapping_record_digest != mapping.record_digest
            or native.mapping_id != mapping.content.mapping_id
            or native.mapping_version != mapping.content.mapping_version
            or selection.profile_id != configuration.profile_id
            or selection.profile_key != configuration.profile_key
            or selection.profile_version != configuration.profile_version
            or selection.profile_content_hash != configuration.profile_content_sha256
            or selection.runtime_snapshot_id != configuration.snapshot_id
            or selection.runtime_snapshot_hash != configuration.snapshot_sha256
            or selection.environment != configuration.environment
            or selection.profile_activated_at != configuration.profile_activated_at
            or selection.runtime_snapshot_generated_at != configuration.snapshot_generated_at
        ):
            raise _blocked()
        facts = snapshot.content.classify_security(native.source_code)
        if (
            facts is None
            or facts.blocked_reason is not None
            or facts.rule_market != query.exchange.value
            or facts.rule_market != native.rule_market
            or facts.board != native.board
            or facts.source_exchange != native.source_exchange
            or facts.source_market != native.source_market
            or facts.source_currency != query.currency.value
            or facts.list_date is None
            or facts.list_date > query.record_date
            or (facts.delist_date is not None and facts.delist_date <= query.record_date)
        ):
            raise _blocked()
        matching = tuple(
            row
            for group in snapshot.content.fetch_rounds
            for row in group.candidate.records
            if row.ts_code == native.source_code
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
            raise _blocked()
        payload = {
            "schema": "simulated-share-capital-tax-instrument.v1",
            "query_sha256": query.semantic_sha256,
            "model_rule_sha256": configured.model_rule_sha256,
            "configuration_sha256": configuration.identity_sha256,
            "selector_sha256": classification.selector.content_hash,
            "snapshot_id": str(snapshot.snapshot_id),
            "snapshot_digest": snapshot.record_digest,
            "occurrence_id": str(identity.source_occurrence_id),
            "record_date": query.record_date.isoformat(),
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        known_at = max(
            snapshot.recorded_at,
            mapping.recorded_at,
            native.first_seen_at,
            identity.reference_response_completed_at,
            selection.profile_activated_at,
            selection.runtime_snapshot_generated_at,
        )
        deadline = min(configured.valid_until, native.identity_valid_until)
        if not known_at <= as_of < deadline:
            raise _blocked()
        return ShareCapitalTaxInstrumentEvidence(
            fingerprint,
            str(snapshot.snapshot_id),
            snapshot.content_hash,
            snapshot.record_digest,
            str(identity.source_occurrence_id),
            identity.reference_response_completed_at,
            known_at,
            deadline,
        )
    except BusinessLogicError:
        raise
    except (ArithmeticError, AttributeError, TypeError, ValueError) as error:
        raise _blocked() from error
