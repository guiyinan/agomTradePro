from apps.prompt.application.evaluation_use_cases import PromotePromptVersion, RunPromptEvaluation
from apps.prompt.infrastructure.evaluation_repository import PromptEvaluationRepository


def make_run_prompt_evaluation() -> RunPromptEvaluation:
    return RunPromptEvaluation(PromptEvaluationRepository())


def make_promote_prompt_version() -> PromotePromptVersion:
    return PromotePromptVersion(PromptEvaluationRepository())

