# ruff: noqa: F403, F405
"""Split tests from test_api_and_use_cases.py: use_cases."""

from .api_and_use_cases_support import *


@pytest.mark.django_db
def test_non_admin_answer_chain_masks_technical_fields(write_capability, regular_user):
    use_case = RouteMessageUseCase()

    response = use_case.execute(
        RouteRequestDTO(
            message="runtime reset",
            entrypoint="terminal",
            context={
                "user_id": regular_user.id,
                "user_is_admin": False,
                "mcp_enabled": True,
                "answer_chain_enabled": True,
            },
        )
    )

    assert response.answer_chain["visibility"] == "masked"
    steps = response.answer_chain["steps"]
    assert all("technical_details" not in step for step in steps)
    assert write_capability.capability_key not in steps[1]["summary"]
    assert write_capability.name in steps[1]["summary"]
