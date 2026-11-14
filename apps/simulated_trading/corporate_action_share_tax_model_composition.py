"""Compose exact retained share-capital model facts without financial or real-tax authority."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path

from django.db import DEFAULT_DB_ALIAS
from django.utils import timezone

from apps.data_center.domain.security_disclosure_event import (
    SecurityDisclosureEventReadScope,
    SecurityDisclosureExchange,
)
from apps.data_center.instrument_reference_snapshot_composition import (
    read_instrument_reference_snapshot,
)
from apps.data_center.security_disclosure_capture_composition import (
    make_security_disclosure_event_reader,
)
from apps.data_center.statutory_source_capture_composition import (
    ConfiguredStatutorySourceCaptureService,
)
from apps.simulated_trading.application.corporate_action_share_tax_model import (
    CurrentShareCapitalTaxModel,
    ShareCapitalTaxModelQuery,
)
from apps.simulated_trading.application.corporate_action_share_tax_proof import (
    ShareCapitalTaxQualificationProof,
)
from apps.simulated_trading.corporate_action_share_tax_instrument_qualification import (
    qualify_share_capital_tax_instrument,
)
from apps.simulated_trading.corporate_action_share_tax_policy_composition import (
    read_share_capital_tax_policy_for_stage,
)
from apps.simulated_trading.corporate_action_share_tax_statutory_qualification import (
    qualify_share_capital_tax_statutory_evidence,
)
from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionKind,
    CorporateActionStageRequest,
)
from apps.simulated_trading.execution_current_reference_composition import (
    build_current_reference_classification_reader,
)
from apps.simulated_trading.official_disclosure_action_composition import (
    VerifiedSzseActionSourceQualifier,
    _find_current_event_with_complete_lineage,
)
from core.exceptions import BusinessLogicError


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "当前送转模拟税务模型、证券资料或原文证据已变化，请重新核对。",
        code="SHARE_CAPITAL_TAX_MODEL_CURRENT_EVIDENCE_BLOCKED",
    )


class DjangoCurrentShareCapitalTaxQualificationReader:
    """Reopen actual sources twice and reject changed or expired immutable selections."""

    def __init__(
        self,
        *,
        environment: str,
        statutory_provider_id: int,
        statutory_body_store_root: Path,
        action_body_store_root: Path,
        deployment_region: str,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Bind explicit same-alias source stores; no catalog, persona or policy is seeded."""
        if using != DEFAULT_DB_ALIAS or type(environment) is not str or not environment:
            raise _blocked()
        self._environment = environment
        self._using = using
        self._sources = ConfiguredStatutorySourceCaptureService(
            provider_id=statutory_provider_id,
            body_store_root=statutory_body_store_root,
            deployment_region=deployment_region,
            using=using,
        )
        self._action_source = VerifiedSzseActionSourceQualifier(
            body_store_root=action_body_store_root, using=using
        )

    def read_current(
        self, request: CorporateActionStageRequest, *, canonical_account_id: str, as_of: datetime
    ) -> ShareCapitalTaxQualificationProof:
        """Return full exact model proof; this method never writes a financial or consent row."""
        if (
            type(as_of) is not datetime
            or as_of.tzinfo is None
            or as_of.utcoffset() is None
            or as_of > timezone.now()
            or type(request) is not CorporateActionStageRequest
            or request.action_kind is not CorporateActionKind.SHARE_DISTRIBUTION
        ):
            raise _blocked()
        request.__post_init__()
        first = self._read_state(request, canonical_account_id=canonical_account_id, as_of=as_of)
        second_started = timezone.now()
        if second_started < as_of:
            raise _blocked()
        final = self._read_state(
            request, canonical_account_id=canonical_account_id, as_of=second_started
        )
        completed = timezone.now()
        if completed < second_started or first.selection_sha256 != final.selection_sha256:
            raise _blocked()
        final.verify_for(request, as_of=completed)
        return replace(final, checked_at=completed)

    def _read_state(
        self, request: CorporateActionStageRequest, *, canonical_account_id: str, as_of: datetime
    ) -> ShareCapitalTaxQualificationProof:
        """Join full official lineage/body, explicit declaration, actual instrument and source pair."""
        configured = read_share_capital_tax_policy_for_stage(
            request=request,
            canonical_account_id=canonical_account_id,
            environment=self._environment,
            as_of=as_of,
        )
        facts = make_security_disclosure_event_reader(using=self._using).execute(
            SecurityDisclosureEventReadScope(
                as_of=as_of, exchange=SecurityDisclosureExchange.SZSE, asset_code=request.asset_code
            )
        )
        event = _find_current_event_with_complete_lineage(request, facts, verification_at=as_of)
        if event is None or not self._action_source.verify_source(request):
            raise _blocked()
        scope = configured.scope
        query = ShareCapitalTaxModelQuery(
            account_kind=scope.account_kind,
            physical_account_id=request.account_id,
            canonical_account_id=canonical_account_id,
            owner_user_id=request.owner_user_id,
            security_id=request.security_id,
            asset_code=request.asset_code,
            exchange=scope.exchange,
            persona=scope.persona,
            instrument_kind=scope.instrument_kind,
            currency=scope.currency,
            source_namespace=request.source_namespace,
            source_record_id=request.source_record_id,
            source_event_id=request.source_event_id,
            source_revision_id=request.source_revision_id,
            source_revision_sha256=event.content_hash,
            source_payload_sha256=request.source_payload_sha256,
            action_kind=request.action_kind,
            stage=request.stage,
            entry_kind=request.entry_kind,
            capital_source=scope.capital_source,
            record_date=request.record_date,
            effective_date=request.effective_date,
            stage_date=request.stage_date,
            source_observed_at=request.source_observed_at,
        )
        identity_cutoff = timezone.now()
        if identity_cutoff < as_of or identity_cutoff < configured.configuration.checked_at:
            raise _blocked()
        classification = build_current_reference_classification_reader(
            runtime_environment=self._environment
        ).resolve_simulated_instrument_classification(
            security_id=request.security_id, asset_code=request.asset_code, as_of=identity_cutoff
        )
        if classification is None:
            raise _blocked()
        snapshot = read_instrument_reference_snapshot(
            snapshot_id=classification.identity_evidence.source_evidence.snapshot_id
        )
        if snapshot is None:
            raise _blocked()
        instrument = qualify_share_capital_tax_instrument(
            query=query,
            configured=configured,
            classification=classification,
            snapshot=snapshot,
            as_of=identity_cutoff,
        )
        retained = self._sources.read_retained_bundle(
            bundle_id=configured.statutory_bundle_id, version=configured.statutory_bundle_version
        )
        checked = timezone.now()
        if checked < as_of:
            raise _blocked()
        statutory = qualify_share_capital_tax_statutory_evidence(
            query=query, configured=configured, retained=retained, as_of=checked
        )
        latest = read_share_capital_tax_policy_for_stage(
            request=request,
            canonical_account_id=canonical_account_id,
            environment=self._environment,
            as_of=checked,
        )
        if (
            configured.configuration.identity_sha256 != latest.configuration.identity_sha256
            or configured.model_rule_sha256 != latest.model_rule_sha256
        ):
            raise _blocked()
        finished = timezone.now()
        if finished < checked or finished < latest.configuration.checked_at:
            raise _blocked()
        known = max(
            configured.configuration.known_at,
            query.source_observed_at,
            statutory.known_at,
            instrument.known_at,
        )
        deadline = min(configured.valid_until, statutory.valid_until, instrument.valid_until)
        model = CurrentShareCapitalTaxModel(
            query.semantic_sha256,
            scope.persona,
            scope.capital_source,
            statutory.terms,
            statutory.source_1997_198,
            statutory.source_1998_289,
            configured.model_rule_id,
            configured.model_rule_sha256,
            configured.configuration.profile_id,
            configured.configuration.profile_content_sha256,
            configured.configuration.snapshot_id,
            configured.configuration.snapshot_sha256,
            known,
            configured.valid_from,
            deadline,
            finished,
        )
        return ShareCapitalTaxQualificationProof(
            query,
            model,
            self._environment,
            configured.configuration.identity_sha256,
            statutory.source_configuration_sha256,
            statutory.source_bundle_sha256,
            statutory.capture_manifest_sha256,
            instrument.semantic_sha256,
            instrument.snapshot_id,
            instrument.snapshot_content_sha256,
            instrument.snapshot_record_digest,
            instrument.occurrence_id,
            instrument.reference_response_completed_at,
            finished,
            deadline,
        )
