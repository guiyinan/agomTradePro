# ruff: noqa: F821


def get_active_scenarios(repository):
    scenarios = repository.list_active()
    if not scenarios:
        raise ScenarioConfigurationUnavailable("No approved scenario revision is active")
    return scenarios


def get_active_allocation_policy(repository):
    policy = repository.get_active_version()
    if policy is None:
        raise AllocationPolicyUnavailable("No approved allocation policy is active")
    return policy
