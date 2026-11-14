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

    def read_locked_assessment_lineage(
        self, assessment: CorporateActionTaxAssessment
    ) -> tuple[Header, ...]:
        """Return the fully verified revision chain for this locked idempotency stream.

        The caller owns a READ COMMITTED transaction. The physical account and
        every header in the stream are locked before scope, parent links,
        clocks, and immutable retained material are checked. No history outside
        this account and idempotency key is treated as part of the chain.
        """
        connection = connections[self._using]
        if not connection.in_atomic_block:
            raise _blocked("Assessment replay checks require the caller-owned atomic UOW.")
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                if cursor.fetchone() != ("read committed",):
                    raise _blocked("Assessment replay checks require PostgreSQL READ COMMITTED.")
        assessment.verify_integrity()
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
        if not rows:
            return ()

        expected_scope = (
            assessment.account_id,
            assessment.owner_user_id,
            assessment.asset_code,
            assessment.security_id,
            action.corporate_action_id,
            assessment.history.record_date,
            assessment.target_settlement_date,
            assessment.calculation.disposition_id,
            assessment.calculation.idempotency_key,
        )
        rows_by_id: dict[int, Header] = {}
        rows_by_revision: dict[str, Header] = {}
        children_by_parent: dict[int, list[int]] = {}
        roots: list[Header] = []
        for row in rows:
            row_id = recorded_id(row)
            revision_id = row.assessment_revision_id
            parent_id = row.__dict__.get("supersedes_id")
            parent_revision_id = row.supersedes_assessment_revision_id
            if (
                row_id in rows_by_id
                or type(revision_id) is not str
                or not revision_id
                or revision_id in rows_by_revision
            ):
                raise _blocked("Assessment stream contains duplicate or invalid row identities.")
            actual_scope = (
                row.account_id,
                row.owner_user_id,
                row.asset_code,
                row.security_id,
                row.corporate_action_id,
                row.record_date,
                row.settlement_date,
                row.disposition_id,
                row.idempotency_key,
            )
            if actual_scope != expected_scope:
                raise _blocked("Assessment stream crosses an owner, asset or settlement scope.")
            rows_by_id[row_id] = row
            rows_by_revision[revision_id] = row
            if parent_id is None:
                if parent_revision_id is not None:
                    raise _blocked("Assessment predecessor id and revision reference disagree.")
                roots.append(row)
                continue
            if type(parent_id) is not int or parent_id <= 0 or type(parent_revision_id) is not str:
                raise _blocked("Assessment predecessor reference is invalid or incomplete.")
            children_by_parent.setdefault(parent_id, []).append(row_id)

        if len(roots) != 1:
            raise _blocked("Assessment stream does not have exactly one retained lineage root.")
        for row in rows:
            parent_id = row.__dict__.get("supersedes_id")
            parent_revision_id = row.supersedes_assessment_revision_id
            if parent_id is None:
                continue
            parent = rows_by_id.get(cast(int, parent_id))
            if parent is None or parent.assessment_revision_id != parent_revision_id:
                raise _blocked("Assessment predecessor is absent or references another revision.")
            if len(children_by_parent.get(cast(int, parent_id), ())) != 1:
                raise _blocked("Assessment stream branches from a retained revision.")

        lineage: list[Header] = []
        visited: set[int] = set()
        current = roots[0]
        while True:
            current_id = recorded_id(current)
            if current_id in visited:
                raise _blocked("Assessment stream contains a revision cycle.")
            visited.add(current_id)
            lineage.append(current)
            child_ids = children_by_parent.get(current_id, [])
            if not child_ids:
                break
            if len(child_ids) != 1:
                raise _blocked("Assessment stream branches from a retained revision.")
            current = rows_by_id[child_ids[0]]
        if len(visited) != len(rows):
            raise _blocked("Assessment stream contains a cycle or disconnected revision.")

        previous_recorded_at: datetime | None = None
        for row in lineage:
            recorded_at = row.recorded_at
            if (
                type(recorded_at) is not datetime
                or recorded_at.tzinfo is None
                or recorded_at.utcoffset() is None
            ):
                raise _blocked("Assessment lineage contains a missing or naive recording clock.")
            try:
                recorded_at_utc = recorded_at.astimezone(UTC)
            except (OverflowError, ValueError) as error:
                raise _blocked(
                    "Assessment lineage recording clock is not representable."
                ) from error
            if previous_recorded_at is not None and recorded_at_utc < previous_recorded_at:
                raise _blocked("Assessment lineage recording clocks move backwards.")
            previous_recorded_at = recorded_at_utc

        for row in lineage:
            self.verify_retained_integrity(row)
        return tuple(lineage)

    def find_exact_semantic_head(
        self, assessment: CorporateActionTaxAssessment
    ) -> StoredTaxAssessment | None:
        """Read a fully matching locked current head without appending any material."""
        lineage = self.read_locked_assessment_lineage(assessment)
        if not lineage:
            return None
        head = lineage[-1]
        if head.semantic_sha256 != assessment.semantic_sha256:
            return None
        self.verify_stored(head, assessment)
        return StoredTaxAssessment(head, True)

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

    def verify_retained_integrity(self, header: Header) -> dict[str, object]:
        """Verify immutable historical material without claiming current tax eligibility.

        Financial readback also verifies the original Audit/Outbox pair. This
        method supplies neither new assessment facts nor write permission.
        """
        semantic = read_material(header.semantic_payload_json, header.semantic_sha256)
        read_material(header.observation_manifest_json, header.observation_manifest_sha256)
        calculation = read_material(header.calculation_payload_json, header.calculation_sha256)
        if semantic.get("schema") not in {
            "corporate-action-deferred-tax-assessment.v1",
            "corporate-action-deferred-tax-assessment.v2",
        } or calculation != semantic.get("calculation"):
            raise _blocked("Historical assessment schema or calculation differs.")

        def component(name: str) -> dict[str, object]:
            """Narrow one original JSON component before inspecting its fields."""
            value = semantic.get(name)
            if type(value) is not dict or any(type(key) is not str for key in value):
                raise _blocked("Historical assessment component is incomplete.")
            return cast(dict[str, object], value)

        scope = component("assessment_scope")
        action = component("action_revision")
        policy = component("policy")
        history = component("settlement_history")
        dispositions = history.get("daily_net_dispositions")
        if type(dispositions) is not list:
            raise _blocked("Historical assessment dispositions are missing.")
        targets = [
            row
            for row in dispositions
            if type(row) is dict
            and row.get("settlement_date") == header.settlement_date.isoformat()
        ]
        if len(targets) != 1:
            raise _blocked("Historical assessment target disposition is not unique.")
        expected: dict[str, object] = {
            "account_id": scope.get("account_id"),
            "owner_user_id": scope.get("owner_user_id"),
            "asset_code": scope.get("asset_code"),
            "security_id": scope.get("security_id"),
            "corporate_action_id": scope.get("corporate_action_id"),
            "source_namespace": action.get("source_namespace"),
            "source_record_id": action.get("source_record_id"),
            "source_event_id": action.get("source_event_id"),
            "action_source_revision_id": action.get("source_revision_id"),
            "action_source_revision_sha256": action.get("source_revision_sha256"),
            "action_source_payload_sha256": action.get("source_payload_sha256"),
            "settlement_source_revision_id": history.get("source_revision_id"),
            "settlement_source_revision_sha256": history.get("source_revision_sha256"),
            "policy_id": policy.get("policy_id"),
            "policy_version": policy.get("version"),
            "policy_source_identity": policy.get("source_identity"),
            "policy_source_sha256": policy.get("source_sha256"),
            "policy_sha256": policy.get("policy_sha256"),
            "disposition_id": targets[0].get("disposition_id"),
            "idempotency_key": calculation.get("idempotency_key"),
        }
        for name, value in expected.items():
            if value is None or getattr(header, name) != value:
                raise _blocked("Historical assessment columns differ from sealed original facts.")
        for column, value in (
            (header.record_date, scope.get("record_date")),
            (header.settlement_date, scope.get("target_settlement_date")),
        ):
            if column.isoformat() != value:
                raise _blocked("Historical assessment dates differ from sealed original facts.")
        for component_name, id_column, hash_column in (
            ("date_rule", header.settlement_date_rule_id, header.settlement_date_rule_sha256),
            ("calendar", header.settlement_calendar_id, header.settlement_calendar_sha256),
        ):
            value = history.get(component_name)
            if (
                type(value) is not dict
                or value.get("id") != id_column
                or value.get("sha256") != hash_column
            ):
                raise _blocked("Historical settlement rule or calendar differs.")
        statutory = component("statutory_source_revision_set")
        if statutory.get("source_revision_set_sha256") != header.statutory_revision_set_sha256:
            raise _blocked("Historical statutory source revision set differs.")
        for name in ("gross_dividend_amount", "taxable_dividend_amount", "withholding_amount"):
            if getattr(header, f"{name}_text") != calculation.get(name):
                raise _blocked("Historical assessment amounts differ from retained calculation.")
        rows = tuple(
            Allocation._default_manager.using(self._using)
            .filter(assessment_id=recorded_id(header))
            .order_by("ordinal")
        )
        allocations = calculation.get("allocations")
        if type(allocations) is not list or len(rows) != len(allocations):
            raise _blocked("Historical assessment allocations are incomplete.")
        for ordinal, (row, expected_allocation) in enumerate(
            zip(rows, allocations, strict=True), 1
        ):
            payload = read_material(row.allocation_payload_json, row.allocation_sha256)
            if (
                row.ordinal != ordinal
                or payload != expected_allocation
                or row.lot_id != payload.get("lot_id")
                or row.recorded_at != header.recorded_at
            ):
                raise _blocked("Historical assessment allocation differs from original evidence.")
        return semantic


__all__ = [
    "DjangoCorporateActionTaxAssessmentRepository",
    "StoredTaxAssessment",
    "TaxAssessmentPersistedAuthority",
]
