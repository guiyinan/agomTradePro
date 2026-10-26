"""Static Django model metadata checks; these tests issue no database queries."""

from __future__ import annotations

from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    AppendOnlyFeeEvidenceQuerySet,
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
    FeeCorrectionEvidencePolicyQuerySet,
)


def test_append_only_models_use_guarded_base_managers() -> None:
    """Default and base-manager querysets share the normal mutation guards."""

    append_only_models = (
        FeeCorrectionEvidenceArtifactModel,
        FeeCorrectionEvidenceBindingModel,
    )
    for model in append_only_models:
        assert model._meta.base_manager_name == "objects"
        assert isinstance(model._base_manager.get_queryset(), AppendOnlyFeeEvidenceQuerySet)

    policy_model = FeeCorrectionEvidencePolicyModel
    assert policy_model._meta.base_manager_name == "objects"
    assert isinstance(
        policy_model._base_manager.get_queryset(), FeeCorrectionEvidencePolicyQuerySet
    )


def test_hash_length_constraints_are_declared_in_model_state() -> None:
    """Artifact and binding model state retain the SHA-256 length checks."""

    expected = {
        ("feecorrectionevidenceartifactmodel", "sim_fee_ev_art_hash_length_ck"),
        ("feecorrectionevidencebindingmodel", "sim_fee_ev_bind_hash_length_ck"),
    }
    model_constraints = {
        (model._meta.model_name, constraint.name)
        for model in (
            FeeCorrectionEvidenceArtifactModel,
            FeeCorrectionEvidenceBindingModel,
        )
        for constraint in model._meta.constraints
    }
    assert expected <= model_constraints
