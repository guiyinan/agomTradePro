"""Account-locked immutable assessment storage; the caller must also commit Audit/Outbox."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from django.db import connections

from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentAllocationModel as Allocation,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel as Header,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    _activate_tax_assessment_uow,
    _claim_tax_assessment_insert,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from core.exceptions import BusinessLogicError


def _blocked(message: str, code: str = "TAX_ASSESSMENT_STORAGE_BLOCKED") -> BusinessLogicError:
    """Classify incomplete, conflicting or unsafe retained assessment evidence."""
    return BusinessLogicError(message, code=code)


def canonical_json(value: object) -> str:
    """Encode exact JSON material at the storage boundary without coercing Decimals."""
    try:
        text = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        text.encode("utf-8")
    except (TypeError, ValueError) as error:
        raise _blocked("Assessment material is not canonical UTF-8 JSON.") from error
    return text


def material_sha256(value: str) -> str:
    """Hash already canonical, representable material."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_material(value: str, digest: str) -> dict[str, object]:
    """Verify a complete stored object instead of trusting its declared hash."""
    try:
        parsed: object = json.loads(value)
    except (TypeError, ValueError) as error:
        raise _blocked("Stored assessment material is invalid JSON.") from error
    if type(parsed) is not dict or any(type(key) is not str for key in parsed):
        raise _blocked("Stored assessment material must be an exact JSON object.")
    if canonical_json(parsed) != value or material_sha256(value) != digest:
        raise _blocked("Stored assessment material or its checksum differs.")
    return cast(dict[str, object], parsed)


def recorded_id(row: Header | Allocation) -> int:
    """Narrow a persisted ORM primary key before using it as evidence."""
    value: object = row.pk
    if type(value) is not int or value <= 0:
        raise _blocked("Assessment storage returned an invalid primary key.")
    return value


@dataclass(frozen=True, slots=True)
class TaxAssessmentPersistedAuthority:
    """Original verified grant and Audit scope references, never independent authority."""

    grant_id: str
    grant_version: str
    grant_sha256: str
    tenant_id: str
    owner_id: str

    def __post_init__(self) -> None:
        """Require bounded exact reference fields for the already verified scope."""
        for value in (self.grant_id, self.grant_version, self.tenant_id, self.owner_id):
            if (
                type(value) is not str
                or not value
                or len(value) > 192
                or any(c.isspace() or ord(c) < 32 for c in value)
            ):
                raise _blocked("Original assessment authority reference is invalid.")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError as error:
                raise _blocked("Original authority reference is invalid UTF-8.") from error
        if (
            type(self.grant_sha256) is not str
            or len(self.grant_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.grant_sha256)
        ):
            raise _blocked("Original authority content hash is invalid.")


@dataclass(frozen=True, slots=True)
class StoredTaxAssessment:
    """A locked persisted header and whether the original complete facts were reused."""

    header: Header
    replayed: bool


class DjangoCorporateActionTaxAssessmentRepository:
    """Persist evidence under the physical account lock, without writing any balance.

    This adapter is private to the audited Root UOW. It requires its caller's
    transaction; it does not authorize a user or expose an unaudited factory.
    """

    def __init__(self, *, using: str) -> None:
        """Bind storage to the same explicit alias as its outer Audit/Outbox UOW."""
        if type(using) is not str or not using or any(c.isspace() for c in using):
            raise _blocked("An explicit assessment database alias is required.")
        self._using = using

    def append_locked(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        authority: TaxAssessmentPersistedAuthority,
        recorded_at: datetime,
    ) -> StoredTaxAssessment:
        """Append one complete revision, or return the original semantic retry."""
        connection = connections[self._using]
        if not connection.in_atomic_block:
            raise _blocked("Assessment appends require the caller's atomic Audit/Outbox UOW.")
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                if cursor.fetchone() != ("read committed",):
                    raise _blocked("Assessment appends require PostgreSQL READ COMMITTED.")
        if (
            type(recorded_at) is not datetime
            or recorded_at.tzinfo is None
            or recorded_at.utcoffset() is None
        ):
            raise _blocked("The assessment recording clock must be aware.")
        try:
            recorded_at.astimezone(UTC)
        except (OverflowError, ValueError) as error:
            raise _blocked("The recording clock must be representable in UTC.") from error
        assessment.verify_integrity()
        authority.__post_init__()
        account = (
            SimulatedAccountModel._default_manager.using(self._using)
            .select_for_update()
            .filter(pk=assessment.account_id)
            .first()
        )
        if account is None or account.user_id != assessment.owner_user_id:
            raise _blocked(
                "The exact physical account owner is required.", "TAX_ASSESSMENT_OWNER_REQUIRED"
            )
        action = assessment.action
        if (
            Header._default_manager.using(self._using)
            .filter(
                account_id=assessment.account_id,
                security_id=assessment.security_id,
                source_namespace=action.source_namespace,
                source_event_id=action.source_event_id,
            )
            .exclude(corporate_action_id=action.corporate_action_id)
            .exists()
        ):
            raise _blocked(
                "Native action identity is already bound to another canonical action.",
                "TAX_ASSESSMENT_ACTION_ALIAS_CONFLICT",
            )
        rows = tuple(
            Header._default_manager.using(self._using)
            .select_for_update()
            .filter(
                account_id=assessment.account_id,
                idempotency_key=assessment.calculation.idempotency_key,
            )
            .order_by("id")
        )
        head: Header | None = None
        if rows:
            parent_ids = {
                cast(int, row.__dict__["supersedes_id"])
                for row in rows
                if row.__dict__.get("supersedes_id") is not None
            }
            heads = tuple(row for row in rows if recorded_id(row) not in parent_ids)
            if len(heads) != 1:
                raise _blocked("Assessment stream does not have exactly one retained lineage head.")
            head = heads[0]
            for row in rows:
                if (
                    row.owner_user_id,
                    row.asset_code,
                    row.security_id,
                    row.corporate_action_id,
                    row.record_date,
                    row.settlement_date,
                    row.disposition_id,
                ) != (
                    assessment.owner_user_id,
                    assessment.asset_code,
                    assessment.security_id,
                    action.corporate_action_id,
                    assessment.history.record_date,
                    assessment.target_settlement_date,
                    assessment.calculation.disposition_id,
                ):
                    raise _blocked("Assessment stream crosses an owner, asset or settlement scope.")
            if head.semantic_sha256 == assessment.semantic_sha256:
                self.verify_stored(head, assessment)
                return StoredTaxAssessment(head, True)
            if any(row.assessment_revision_id == assessment.assessment_revision_id for row in rows):
                raise _blocked(
                    "An assessment revision is already bound to different or superseded facts.",
                    "TAX_ASSESSMENT_REVISION_CONFLICT",
                )
            if (
                assessment.supersedes_assessment_revision_id != head.assessment_revision_id
                or recorded_at <= head.recorded_at
            ):
                raise _blocked(
                    "A changed assessment requires an explicit later successor of the exact head.",
                    "TAX_ASSESSMENT_SUCCESSOR_REQUIRED",
                )
        elif assessment.supersedes_assessment_revision_id is not None:
            raise _blocked("The first assessment cannot reference an absent predecessor.")
        observation = read_material(
            assessment.observation_manifest_json, assessment.observation_manifest_sha256
        )
        proof = observation.get("ownership_proof")
        captures = observation.get("source_capture_manifest")
        if type(proof) is not dict or type(captures) is not dict:
            raise _blocked("Assessment observation evidence is incomplete.")
        clocks = [proof.get("ownership_snapshot_observed_at")]
        members = captures.get("captures")
        if type(members) is not list:
            raise _blocked("Assessment source capture membership is incomplete.")
        clocks.extend(member.get("captured_at") for member in members if type(member) is dict)
        for value in clocks:
            if type(value) is not str:
                raise _blocked("Assessment source observation clock is missing.")
            instant = datetime.fromisoformat(value)
            if instant.tzinfo is None or instant.utcoffset() is None or instant > recorded_at:
                raise _blocked("Assessment evidence was not observed before recording.")
        semantic = read_material(assessment.semantic_payload_json, assessment.semantic_sha256)
        calculation = semantic["calculation"]
        calculation_json = canonical_json(calculation)
        values: dict[str, object] = {
            "account_id": assessment.account_id,
            "owner_user_id": assessment.owner_user_id,
            "authority_grant_id": authority.grant_id,
            "authority_grant_version": authority.grant_version,
            "authority_grant_sha256": authority.grant_sha256,
            "audit_tenant_id": authority.tenant_id,
            "audit_owner_id": authority.owner_id,
            "assessment_revision_id": assessment.assessment_revision_id,
            "supersedes_id": recorded_id(head) if head else None,
            "supersedes_assessment_revision_id": assessment.supersedes_assessment_revision_id,
            "asset_code": assessment.asset_code,
            "security_id": assessment.security_id,
            "corporate_action_id": action.corporate_action_id,
            "source_namespace": action.source_namespace,
            "source_record_id": action.source_record_id,
            "source_event_id": action.source_event_id,
            "action_source_revision_id": action.source_revision_id,
            "action_source_revision_sha256": action.source_revision_sha256,
            "action_source_payload_sha256": action.source_payload_sha256,
            "settlement_source_revision_id": assessment.history.source_revision_id,
            "settlement_source_revision_sha256": assessment.history.source_revision_sha256,
            "record_date": assessment.history.record_date,
            "settlement_date": assessment.target_settlement_date,
            "settlement_date_rule_id": assessment.history.settlement_date_rule_id,
            "settlement_date_rule_sha256": assessment.history.settlement_date_rule_sha256,
            "settlement_calendar_id": assessment.history.settlement_calendar_id,
            "settlement_calendar_sha256": assessment.history.settlement_calendar_sha256,
            "policy_id": assessment.policy.policy_id,
            "policy_version": assessment.policy.version,
            "policy_source_identity": assessment.policy.source_identity,
            "policy_source_sha256": assessment.policy.source_sha256,
            "policy_sha256": assessment.policy.policy_sha256,
            "statutory_revision_set_sha256": assessment.statutory_source_bundle.source_revision_set_sha256,
            "disposition_id": assessment.calculation.disposition_id,
            "idempotency_key": assessment.calculation.idempotency_key,
            "semantic_payload_json": assessment.semantic_payload_json,
            "semantic_sha256": assessment.semantic_sha256,
            "observation_manifest_json": assessment.observation_manifest_json,
            "observation_manifest_sha256": assessment.observation_manifest_sha256,
            "calculation_payload_json": calculation_json,
            "calculation_sha256": material_sha256(calculation_json),
            "recorded_at": recorded_at,
        }
        if type(calculation) is not dict:
            raise _blocked("Assessment calculation material is invalid.")
        for field in ("gross_dividend_amount", "taxable_dividend_amount", "withholding_amount"):
            values[f"{field}_text"] = calculation[field]
        allocations: object = calculation.get("allocations")
        if type(allocations) is not list or not allocations:
            raise _blocked("A settled disposition requires complete FIFO allocations.")
        with _activate_tax_assessment_uow() as token:
            header = Header(**values)
            with _claim_tax_assessment_insert(
                token=token, using=self._using, model_type=Header, expected_values=values
            ):
                header.save(using=self._using)
            for ordinal, allocation in enumerate(allocations, 1):
                if type(allocation) is not dict or type(allocation.get("lot_id")) is not str:
                    raise _blocked("FIFO allocation material is invalid.")
                payload = canonical_json(allocation)
                allocation_values: dict[str, object] = {
                    "assessment_id": recorded_id(header),
                    "ordinal": ordinal,
                    "lot_id": allocation["lot_id"],
                    "allocation_payload_json": payload,
                    "allocation_sha256": material_sha256(payload),
                    "recorded_at": recorded_at,
                }
                item = Allocation(**allocation_values)
                with _claim_tax_assessment_insert(
                    token=token,
                    using=self._using,
                    model_type=Allocation,
                    expected_values=allocation_values,
                ):
                    item.save(using=self._using)
        self.verify_stored(header, assessment)
        return StoredTaxAssessment(header, False)

    def verify_stored(self, header: Header, assessment: CorporateActionTaxAssessment) -> None:
        """Verify original material, stable calculation, every column and ordered allocation."""
        semantic = read_material(header.semantic_payload_json, header.semantic_sha256)
        read_material(header.observation_manifest_json, header.observation_manifest_sha256)
        calculation = read_material(header.calculation_payload_json, header.calculation_sha256)
        if (
            header.semantic_payload_json != assessment.semantic_payload_json
            or calculation != semantic.get("calculation")
        ):
            raise _blocked(
                "Retained semantic/calculation facts differ from the verified assessment."
            )
        expected: dict[str, object] = {
            "account_id": assessment.account_id,
            "owner_user_id": assessment.owner_user_id,
            "asset_code": assessment.asset_code,
            "security_id": assessment.security_id,
            "corporate_action_id": assessment.action.corporate_action_id,
            "source_namespace": assessment.action.source_namespace,
            "source_record_id": assessment.action.source_record_id,
            "source_event_id": assessment.action.source_event_id,
            "action_source_revision_id": assessment.action.source_revision_id,
            "action_source_revision_sha256": assessment.action.source_revision_sha256,
            "action_source_payload_sha256": assessment.action.source_payload_sha256,
            "settlement_source_revision_id": assessment.history.source_revision_id,
            "settlement_source_revision_sha256": assessment.history.source_revision_sha256,
            "record_date": assessment.history.record_date,
            "settlement_date": assessment.target_settlement_date,
            "settlement_date_rule_id": assessment.history.settlement_date_rule_id,
            "settlement_date_rule_sha256": assessment.history.settlement_date_rule_sha256,
            "settlement_calendar_id": assessment.history.settlement_calendar_id,
            "settlement_calendar_sha256": assessment.history.settlement_calendar_sha256,
            "policy_id": assessment.policy.policy_id,
            "policy_version": assessment.policy.version,
            "policy_source_identity": assessment.policy.source_identity,
            "policy_source_sha256": assessment.policy.source_sha256,
            "policy_sha256": assessment.policy.policy_sha256,
            "statutory_revision_set_sha256": assessment.statutory_source_bundle.source_revision_set_sha256,
            "disposition_id": assessment.calculation.disposition_id,
            "idempotency_key": assessment.calculation.idempotency_key,
            "semantic_sha256": assessment.semantic_sha256,
        }
        for key, value in expected.items():
            if getattr(header, key) != value:
                raise _blocked(
                    "Retained assessment columns differ from the sealed semantic material."
                )
        for field in ("gross_dividend_amount", "taxable_dividend_amount", "withholding_amount"):
            if getattr(header, f"{field}_text") != calculation.get(field):
                raise _blocked("Retained assessment amount differs from its calculation.")
        rows = tuple(
            Allocation._default_manager.using(self._using)
            .filter(assessment_id=recorded_id(header))
            .order_by("ordinal")
        )
        expected_allocations = calculation.get("allocations")
        if type(expected_allocations) is not list or len(rows) != len(expected_allocations):
            raise _blocked("Retained assessment allocation membership is incomplete.")
        for ordinal, (row, expected_allocation) in enumerate(
            zip(rows, expected_allocations, strict=True), 1
        ):
            payload = read_material(row.allocation_payload_json, row.allocation_sha256)
            if (
                row.ordinal != ordinal
                or payload != expected_allocation
                or row.lot_id != payload.get("lot_id")
                or row.recorded_at != header.recorded_at
            ):
                raise _blocked(
                    "Retained FIFO allocation differs from the exact original ordered set."
                )


__all__ = [
    "DjangoCorporateActionTaxAssessmentRepository",
    "StoredTaxAssessment",
    "TaxAssessmentPersistedAuthority",
]
