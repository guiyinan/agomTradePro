import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.agent_runtime.infrastructure.models import (
    AgentExecutionRecordModel,
    AgentGuardrailDecisionModel,
    AgentHandoffModel,
    AgentProposalModel,
    AgentTaskModel,
    AgentTimelineEventModel,
)


@pytest.fixture
def staff_user(django_user_model):
    return django_user_model.objects.create_user(
        username="ops_staff",
        password="test-pass",
        is_staff=True,
    )


@pytest.fixture
def operator_user(django_user_model):
    user = django_user_model.objects.create_user(
        username="ops_operator",
        password="test-pass",
    )
    group, _ = Group.objects.get_or_create(name="operator")
    user.groups.add(group)
    return user


@pytest.fixture
def regular_user(django_user_model):
    return django_user_model.objects.create_user(
        username="ops_regular",
        password="test-pass",
    )


@pytest.fixture
def runtime_task(staff_user):
    task = AgentTaskModel._default_manager.create(
        request_id="atr_ops_page_001",
        task_domain="research",
        task_type="macro_review",
        status="needs_human",
        requires_human=True,
        input_payload={"symbol": "510300"},
        created_by=staff_user,
    )
    AgentTimelineEventModel._default_manager.create(
        request_id=task.request_id,
        task=task,
        event_type="task_created",
        event_source="api",
        event_payload={"note": "created"},
    )
    AgentGuardrailDecisionModel._default_manager.create(
        request_id=task.request_id,
        task=task,
        decision="escalated",
        reason_code="human_required",
        message="Need manual review",
        evidence={"threshold": "high"},
        requires_human=True,
    )
    AgentExecutionRecordModel._default_manager.create(
        request_id=task.request_id,
        task=task,
        execution_status="failed",
        error_details={"code": "upstream_timeout"},
    )
    AgentHandoffModel._default_manager.create(
        request_id=task.request_id,
        task=task,
        from_agent="research-bot",
        to_agent="human-operator",
        handoff_reason="Need human approval",
        handoff_payload={"summary": "escalated"},
        handoff_status="completed",
    )
    return task


@pytest.fixture
def generated_proposal(runtime_task, staff_user):
    return AgentProposalModel._default_manager.create(
        request_id="apr_ops_page_001",
        task=runtime_task,
        proposal_type="signal_create",
        status="generated",
        risk_level="medium",
        approval_required=True,
        approval_status="pending",
        proposal_payload={"action": "create_signal"},
        created_by=staff_user,
    )


@pytest.fixture
def submitted_proposal(runtime_task, staff_user):
    return AgentProposalModel._default_manager.create(
        request_id="apr_ops_page_002",
        task=runtime_task,
        proposal_type="signal_create",
        status="submitted",
        risk_level="medium",
        approval_required=True,
        approval_status="pending",
        proposal_payload={"action": "submit_signal"},
        created_by=staff_user,
    )


@pytest.mark.django_db
def test_operator_pages_allow_staff_and_operator(client, staff_user, operator_user, regular_user):
    task_list_url = reverse("agent_runtime_pages:task_list")

    client.force_login(regular_user)
    regular_response = client.get(task_list_url)
    assert regular_response.status_code == 403

    client.force_login(operator_user)
    operator_response = client.get(task_list_url)
    assert operator_response.status_code == 200

    client.force_login(staff_user)
    staff_response = client.get(task_list_url)
    assert staff_response.status_code == 200


@pytest.mark.django_db
def test_task_detail_page_renders_timeline_guardrails_and_handoffs(client, staff_user, runtime_task, generated_proposal):
    client.force_login(staff_user)

    response = client.get(reverse("agent_runtime_pages:task_detail", args=[runtime_task.id]))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert runtime_task.request_id in content
    assert "Timeline" in content
    assert "Guardrails" in content
    assert "Handoffs" in content
    assert generated_proposal.request_id in content


@pytest.mark.django_db
def test_proposal_detail_submit_action_transitions_generated_proposal(client, staff_user, generated_proposal):
    client.force_login(staff_user)
    url = reverse("agent_runtime_pages:proposal_detail", args=[generated_proposal.id])

    response = client.post(url, {"action": "submit"}, follow=True)

    assert response.status_code == 200
    generated_proposal.refresh_from_db()
    assert generated_proposal.status == "submitted"
    assert AgentGuardrailDecisionModel._default_manager.filter(proposal=generated_proposal).exists()


@pytest.mark.django_db
def test_proposal_detail_approve_and_execute_actions(client, staff_user, submitted_proposal):
    client.force_login(staff_user)
    url = reverse("agent_runtime_pages:proposal_detail", args=[submitted_proposal.id])

    approve_response = client.post(
        url,
        {"action": "approve", "reason": "Looks good"},
        follow=True,
    )
    assert approve_response.status_code == 200

    submitted_proposal.refresh_from_db()
    assert submitted_proposal.status == "approved"
    assert submitted_proposal.approval_status == "approved"

    execute_response = client.post(url, {"action": "execute"}, follow=True)
    assert execute_response.status_code == 200

    submitted_proposal.refresh_from_db()
    assert submitted_proposal.status == "executed"
    assert AgentExecutionRecordModel._default_manager.filter(proposal=submitted_proposal).exists()
