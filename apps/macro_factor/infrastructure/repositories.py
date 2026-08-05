"""Repository for append-only R3 macro-factor research results."""

from __future__ import annotations

import json
from typing import cast

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.macro_factor.domain.entities import ImmutableMacroFactorResearchRecord

from .models import MacroFactorResearchResultModel


class MacroFactorResearchResultRepository:
    """Persist complete external R3 evidence without update or delete paths."""

    def add(
        self,
        record: ImmutableMacroFactorResearchRecord,
    ) -> ImmutableMacroFactorResearchRecord:
        """Append one record and reject a reused immutable identity."""

        if MacroFactorResearchResultModel._default_manager.filter(
            result_id=record.result_id
        ).exists():
            raise ValueError("macro-factor research result already exists")
        decoded = json.loads(record.payload_json)
        if not isinstance(decoded, dict):
            raise ValueError("macro-factor payload must be a JSON object")
        payload = cast(dict[str, object], decoded)
        try:
            with transaction.atomic():
                model = MacroFactorResearchResultModel(
                    result_id=record.result_id,
                    factor_version=record.factor_version,
                    target_code=record.target_code,
                    evidence_produced_at=record.evidence_produced_at,
                    pit_manifest_id=record.pit_manifest_id,
                    pit_manifest_hash=record.pit_manifest_hash,
                    code_version=record.code_version,
                    parameter_version=record.parameter_version,
                    external_evidence_id=record.external_evidence_id,
                    lifecycle_status=record.lifecycle_status.value,
                    content_hash=record.content_hash,
                    payload=payload,
                    research_only=record.research_only,
                    must_not_use_for_decision=record.must_not_use_for_decision,
                )
                model.full_clean()
                model.save(force_insert=True)
        except (IntegrityError, ValidationError) as exc:
            raise ValueError("invalid macro-factor research result") from exc
        return model.to_domain()

    def get(self, result_id: str) -> ImmutableMacroFactorResearchRecord | None:
        """Return one immutable research record by result identity."""

        model = MacroFactorResearchResultModel._default_manager.filter(result_id=result_id).first()
        return model.to_domain() if model is not None else None


__all__ = ["MacroFactorResearchResultRepository"]
