"""Typed port for rechecking current facts behind a tax assessment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from apps.simulated_trading.application.corporate_action_tax_window_proof import (
    CorporateActionTaxWindowProof,
)
from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from core.exceptions import BusinessLogicError


def _token(value: object, *, field_name: str, limit: int = 192) -> str:
    """Require one bounded canonical UTF-8 identity token."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        raise BusinessLogicError(f"{field_name} is invalid", code="TAX_QUALIFICATION_INVALID")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise BusinessLogicError(
            f"{field_name} is invalid", code="TAX_QUALIFICATION_INVALID"
        ) from error
    return value


def _digest(value: object, *, field_name: str) -> str:
    """Require one lowercase SHA-256 evidence reference."""

    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise BusinessLogicError(f"{field_name} is invalid", code="TAX_QUALIFICATION_INVALID")
    return value


def _utc(value: object, *, field_name: str) -> datetime:
    """Require one exact aware instant representable in UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise BusinessLogicError(f"{field_name} must be timezone-aware")
    try:
        return value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise BusinessLogicError(f"{field_name} is not representable in UTC") from error


@dataclass(frozen=True, slots=True)
class CurrentTaxAssessmentQualification:
    """Finite current-read facts from an injected trusted qualification provider.

    This DTO is a result contract, not a source authenticator or write grant.
    Its evidence references must be issued by the injected provider after it
    validates current legal sources, policy, date rules and complete history.
    """

    assessment_semantic_sha256: str
    account_id: int
    owner_user_id: int
    canonical_account_id: str
    environment: str
    qualification_id: str
    qualification_sha256: str
    runtime_profile_id: str
    runtime_profile_content_sha256: str
    runtime_snapshot_id: str
    runtime_snapshot_sha256: str
    valid_until: datetime
    official_window_proof: CorporateActionTaxWindowProof | None = None

    def __post_init__(self) -> None:
        """Validate the explicit assessment, owner and runtime evidence binding."""

        _digest(self.assessment_semantic_sha256, field_name="assessment_semantic_sha256")
        if type(self.account_id) is not int or self.account_id <= 0:
            raise BusinessLogicError("qualification account is invalid")
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise BusinessLogicError("qualification owner is invalid")
        _token(self.canonical_account_id, field_name="canonical_account_id")
        _token(self.environment, field_name="environment", limit=64)
        _token(self.qualification_id, field_name="qualification_id")
        _digest(self.qualification_sha256, field_name="qualification_sha256")
        _token(self.runtime_profile_id, field_name="runtime_profile_id")
        _digest(self.runtime_profile_content_sha256, field_name="runtime_profile_content_sha256")
        _token(self.runtime_snapshot_id, field_name="runtime_snapshot_id")
        _digest(self.runtime_snapshot_sha256, field_name="runtime_snapshot_sha256")
        _utc(self.valid_until, field_name="valid_until")
        proof = self.official_window_proof
        if proof is not None:
            if type(proof) is not CorporateActionTaxWindowProof:
                raise BusinessLogicError("tax window proof is untyped")
            proof.__post_init__()
            if (
                proof.assessment_semantic_sha256 != self.assessment_semantic_sha256
                or proof.canonical_account_id != self.canonical_account_id
                or proof.source_reference.account_id != self.account_id
                or proof.source_reference.owner_user_id != self.owner_user_id
                or proof.evidence.runtime_environment != self.environment
                or proof.evidence.expires_at is None
                or self.valid_until > proof.evidence.expires_at
            ):
                raise BusinessLogicError("tax qualification differs from its original window")

    def verify_for(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        canonical_account_id: str,
        environment: str,
        as_of: datetime,
    ) -> None:
        """Require exact assessment and owner scope while this result is current."""

        self.__post_init__()
        if type(assessment) is not CorporateActionTaxAssessment:
            raise BusinessLogicError("a typed tax assessment is required")
        try:
            assessment.verify_integrity()
        except DeferredDividendTaxValidationError as error:
            raise BusinessLogicError(
                "tax assessment integrity is invalid", code="TAX_QUALIFICATION_SCOPE_MISMATCH"
            ) from error
        requested_canonical = _token(canonical_account_id, field_name="canonical_account_id")
        requested_environment = _token(environment, field_name="environment", limit=64)
        cutoff = _utc(as_of, field_name="as_of")
        if (
            self.assessment_semantic_sha256 != assessment.semantic_sha256
            or self.account_id != assessment.account_id
            or self.owner_user_id != assessment.owner_user_id
            or self.canonical_account_id != requested_canonical
            or self.environment != requested_environment
        ):
            raise BusinessLogicError(
                "current qualification differs from the exact assessment scope",
                code="TAX_QUALIFICATION_SCOPE_MISMATCH",
            )
        if cutoff >= _utc(self.valid_until, field_name="valid_until"):
            raise BusinessLogicError(
                "current tax qualification is expired", code="TAX_QUALIFICATION_EXPIRED"
            )
        if self.official_window_proof is not None:
            self.official_window_proof.verify_for_assessment(
                assessment, canonical_account_id=canonical_account_id, environment=environment
            )


@runtime_checkable
class CurrentTaxAssessmentQualificationPort(Protocol):
    """Read current legal, policy, instrument and complete-history qualification."""

    def read_current(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        canonical_account_id: str,
        environment: str,
        using: str,
        as_of: datetime,
    ) -> CurrentTaxAssessmentQualification:
        """Return exact finite facts or raise a business error without qualification."""


__all__ = [
    "CurrentTaxAssessmentQualification",
    "CurrentTaxAssessmentQualificationPort",
]
