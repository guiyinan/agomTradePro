from apps.research.application.use_cases import EvaluatePromotion, RegisterExperiment, RunTrial
from apps.research.infrastructure.repositories import ResearchRegistryRepository


def make_register_experiment() -> RegisterExperiment:
    return RegisterExperiment(ResearchRegistryRepository())


def make_run_trial() -> RunTrial:
    return RunTrial(ResearchRegistryRepository())


def make_evaluate_promotion() -> EvaluatePromotion:
    return EvaluatePromotion(ResearchRegistryRepository())

