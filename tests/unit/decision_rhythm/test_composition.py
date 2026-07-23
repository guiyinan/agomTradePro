"""Composition-root contracts for Decision Rhythm interface dependencies."""

from apps.decision_rhythm import composition
from apps.decision_rhythm.application.use_cases import PrecheckDecisionUseCase
from apps.decision_rhythm.interface import dependencies


def test_interface_dependencies_reexport_app_composition_builders() -> None:
    """Interface compatibility imports must resolve to the app composition root."""

    for name in dependencies.__all__:
        assert getattr(dependencies, name) is getattr(composition, name)


def test_precheck_builder_uses_the_supported_constructor_contract() -> None:
    """The precheck builder must instantiate without obsolete keyword arguments."""

    use_case = composition.build_precheck_decision_use_case()

    assert isinstance(use_case, PrecheckDecisionUseCase)
    assert use_case.candidate_repo is not None
    assert use_case.quota_repo is not None
    assert use_case.cooldown_repo is not None
