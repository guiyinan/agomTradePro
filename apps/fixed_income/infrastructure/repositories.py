"""Repositories for immutable fixed-income research results."""

from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.fixed_income.domain.entities import ImmutableResearchResult

from .models import FixedIncomeResearchResultModel


class FixedIncomeResearchResultRepository:
    """Persist and retrieve append-only fixed-income research evidence."""

    def add(self, result: ImmutableResearchResult) -> ImmutableResearchResult:
        """Insert one result and reject duplicate identities."""

        if FixedIncomeResearchResultModel._default_manager.filter(
            result_id=result.result_id
        ).exists():
            raise ValueError("fixed-income research result already exists")
        try:
            payload = json.loads(result.payload_json)
            with transaction.atomic():
                model = FixedIncomeResearchResultModel(
                    result_id=result.result_id,
                    bond_id=result.bond_id,
                    valuation_at=result.valuation_at,
                    settlement_date=result.settlement_date,
                    method_version=result.method_version,
                    input_hash=result.input_hash,
                    output_hash=result.output_hash,
                    status=result.status.value,
                    payload=payload,
                    publication_ids=list(result.publication_ids),
                    publication_evidence=[
                        {
                            "dataset_key": seal.dataset_key,
                            "publication_key": seal.publication_key,
                            "publication_id": seal.publication_id,
                            "policy_version": seal.policy_version,
                            "semantic_version": seal.semantic_version,
                            "content_hash": seal.content_hash,
                        }
                        for seal in result.publication_seals
                    ],
                    blocked_reasons=list(result.blocked_reasons),
                    research_only=result.research_only,
                    must_not_execute=result.must_not_execute,
                    must_not_use_for_decision=result.must_not_use_for_decision,
                )
                model.full_clean()
                model.save(force_insert=True)
        except (IntegrityError, ValidationError) as exc:
            raise ValueError("invalid fixed-income research result") from exc
        stored = model.to_domain()
        if stored != result:
            raise ValueError("fixed-income research result round-trip mismatch")
        return stored

    def get(self, result_id: str) -> ImmutableResearchResult | None:
        """Return one immutable result by stable identity."""

        model = FixedIncomeResearchResultModel._default_manager.filter(result_id=result_id).first()
        return model.to_domain() if model is not None else None
