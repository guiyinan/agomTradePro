"""Trusted identity-only definitions for Evidence operator-spec governance."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, cast

from django.utils import timezone

from apps.research.application.evidence_operator_spec_lifecycle import (
    EvidenceOperatorSpecCorruption,
    EvidenceOperatorSpecUnavailable,
)
from apps.research.domain.evidence_contracts import EvidenceOperatorSpec
from apps.research.domain.evidence_operator_spec_lifecycle import (
    ActivatedEvidenceOperatorSpec,
    EvidenceOperatorSpecDefinition,
)
from apps.research.infrastructure.evidence_models import EvidenceOperatorSpecModel
from apps.research.infrastructure.evidence_operator_spec_lifecycle_repository import (
    DjangoEvidenceOperatorSpecLifecycleRepository,
)
from apps.research.infrastructure.evidence_repository import (
    EvidenceRepositoryCorruption,
    _restore_operator,
)


class EvidenceOperatorSpecDefinitionClock(Protocol):
    """Authoritative clock for trusted definition resolution."""

    def now(self) -> datetime:
        """Return one timezone-aware server timestamp."""


class DjangoEvidenceOperatorSpecDefinitionClock:
    """Django timezone-backed definition clock."""

    def now(self) -> datetime:
        """Return the current timezone-aware server timestamp."""

        return cast(datetime, timezone.now())


class EvidenceOperatorSpecLifecycleReader(Protocol):
    """Narrow activation reader used to bind one exact predecessor."""

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Return an already activated exact version, when present."""

    def get_head(
        self,
        *,
        operator_id: str,
        as_of: datetime,
    ) -> ActivatedEvidenceOperatorSpec | None:
        """Return the complete chain head knowable at the cutoff."""


class DjangoEvidenceOperatorSpecDefinitionProvider:
    """Resolve a canonical spec and predecessor without caller-authored hashes."""

    __slots__ = ("_clock", "_lifecycle", "_using")

    def __init__(
        self,
        *,
        using: str = "default",
        clock: EvidenceOperatorSpecDefinitionClock | None = None,
        lifecycle: EvidenceOperatorSpecLifecycleReader | None = None,
    ) -> None:
        self._using = using
        self._clock = clock or DjangoEvidenceOperatorSpecDefinitionClock()
        self._lifecycle = lifecycle or DjangoEvidenceOperatorSpecLifecycleRepository(using=using)

    def get_exact(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpecDefinition | None:
        """Return one exact trusted definition known and effective at ``as_of``."""

        _require_token(operator_id, "operator_id")
        _require_token(operator_version, "operator_version")
        _require_aware(as_of, "as_of")
        now = self._clock.now()
        _require_aware(now, "Research definition server clock")
        if as_of > now:
            raise EvidenceOperatorSpecUnavailable(
                "future operator specification definition as_of is not permitted"
            )
        spec = self._get_canonical_spec(
            operator_id=operator_id,
            operator_version=operator_version,
            as_of=as_of,
        )
        if spec is None or not spec.activated_at <= as_of < spec.valid_until:
            return None
        first_activation = self._lifecycle.get_exact(
            operator_id=operator_id,
            operator_version=operator_version,
            as_of=as_of,
        )
        head = self._lifecycle.get_head(operator_id=operator_id, as_of=as_of)
        final_activation = self._lifecycle.get_exact(
            operator_id=operator_id,
            operator_version=operator_version,
            as_of=as_of,
        )
        if first_activation != final_activation:
            raise EvidenceOperatorSpecCorruption(
                "operator specification activation changed during definition resolution"
            )
        if final_activation is not None:
            if final_activation.operator_spec != spec:
                raise EvidenceOperatorSpecCorruption(
                    "activated operator specification differs from its canonical definition"
                )
            return final_activation.definition
        if head is not None and head.operator_spec.operator_version == operator_version:
            raise EvidenceOperatorSpecCorruption(
                "operator specification chain head lacks its exact activation identity"
            )
        return EvidenceOperatorSpecDefinition.create(
            operator_spec=spec,
            supersedes_activation_hash=(head.content_hash if head is not None else None),
        )

    def _get_canonical_spec(
        self,
        *,
        operator_id: str,
        operator_version: str,
        as_of: datetime,
    ) -> EvidenceOperatorSpec | None:
        models = list(
            EvidenceOperatorSpecModel._default_manager.using(self._using).filter(
                operator_id=operator_id,
                operator_version=operator_version,
            )
        )
        if not models:
            return None
        try:
            restored = tuple(_restore_operator(model) for model in models)
        except EvidenceRepositoryCorruption as error:
            raise EvidenceOperatorSpecCorruption(
                "canonical operator specification failed integrity checks"
            ) from error
        matches = tuple(
            (model, spec)
            for model, spec in zip(models, restored, strict=True)
            if spec.operator_id == operator_id and spec.operator_version == operator_version
        )
        if len(models) != 1 or len(matches) != 1:
            raise EvidenceOperatorSpecCorruption(
                "canonical operator specification identity is ambiguous"
            )
        model, spec = matches[0]
        return spec if model.recorded_at <= as_of else None


def _require_token(value: object, field_name: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded non-blank token")


def _require_aware(value: object, field_name: str) -> None:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


__all__ = [
    "DjangoEvidenceOperatorSpecDefinitionClock",
    "DjangoEvidenceOperatorSpecDefinitionProvider",
    "EvidenceOperatorSpecDefinitionClock",
    "EvidenceOperatorSpecLifecycleReader",
]
