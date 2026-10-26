"""Authenticated owner API contracts for publish, revoke, and audit-backed reads."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.account.infrastructure.identity_models import AccountProfileModel
from apps.risk_center.application.m1_rebalance_risk_policy import (
    GetM1RiskPolicyQualificationUseCase,
)
from apps.risk_center.domain.m1_rebalance_risk_policy import RiskQualificationState
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_models import (
    M1RebalanceRiskPolicyRevisionModel,
)
from apps.risk_center.infrastructure.m1_rebalance_risk_policy_repository import (
    DjangoM1RiskPolicyRevisionRepository,
)
from apps.risk_center.infrastructure.models import RiskPolicyAuditModel
from apps.risk_center.m1_rebalance_risk_policy_composition import (
    build_m1_risk_policy_application,
)
from apps.simulated_trading.application.m1_rebalance_risk_policy import (
    build_m1_risk_source_snapshot,
)
from apps.simulated_trading.infrastructure.m1_risk_policy_account_source_reader import (
    DjangoM1RiskPolicyAccountSourceReader,
)
from apps.simulated_trading.m1_risk_policy_composition import (
    build_strategy_m1_risk_source_reader,
)
from apps.strategy.infrastructure.models import PositionManagementRuleModel
from tests.integration.simulated_trading import test_readonly_rebalance_plan_owner_api as owner_case


class _KeyedAPIClient(APIClient):
    """Give every ordinary test submission a distinct key unless a retry is explicit."""

    def __init__(self) -> None:
        """Initialize a local counter for independent owner submissions."""

        super().__init__()
        self._submission_number = 0

    def post(
        self,
        path: str,
        data: object | None = None,
        format: str | None = None,
        content_type: str | None = None,
        **extra: object,
    ) -> Response:
        """Supply one stable test key; explicit retry calls pass the same header."""

        if "HTTP_IDEMPOTENCY_KEY" not in extra:
            self._submission_number += 1
            extra["HTTP_IDEMPOTENCY_KEY"] = f"m1-risk-test-{self._submission_number}"
        return super().post(
            path,
            data=data,
            format=format,
            content_type=content_type,
            **extra,
        )


def _payload(
    *,
    effective_from: str,
    actor_user_id: int,
    strategy_id: int | None = None,
) -> dict[str, object]:
    """Return explicit owner limits and deliberately spoofable actor data."""

    payload: dict[str, object] = {
        "effective_from": effective_from,
        "effective_until": (timezone.now() + timedelta(days=30)).isoformat(),
        "reason": "I reviewed current account inputs and approve this M1 preview policy.",
        "actor_user_id": actor_user_id,
        "max_single_position_applicability": "applicable",
        "max_single_position_limit_pct": "19",
        "max_total_position_applicability": "applicable",
        "max_total_position_limit_pct": "90",
        "max_stop_loss_applicability": "applicable",
        "max_stop_loss_limit_pct": "7",
    }
    if strategy_id is not None:
        payload["strategy_id"] = strategy_id
    return payload


@pytest.mark.django_db
def test_owner_publish_uses_authenticated_actor_and_returns_distinct_version_contract() -> None:
    """The publisher records an authenticated owner decision, not client actor_id."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-publish-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    stranger = get_user_model().objects.create_user(
        username=f"m1-risk-stranger-{uuid4().hex}",
        password="unused",
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    effective_from = (timezone.now() + timedelta(minutes=5)).isoformat()

    response = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        _payload(effective_from=effective_from, actor_user_id=stranger.pk),
        format="json",
    )

    assert response.status_code == 201
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    body = response.json()
    assert body["risk_policy_version"]
    assert body["legacy_rule_version"] is None
    assert body["publication_status"] == "published"
    assert body["risk_falsification"]["status"] == "not_evaluated"
    assert body["risk_falsification"]["conditions"][0]["threshold_pct"] == "19.000"
    revision = DjangoM1RiskPolicyRevisionRepository().list_revisions(account_id=account.pk)[0]
    assert revision.actor_user_id == owner.pk
    assert revision.actor_user_id != stranger.pk
    assert revision.risk_policy_version == body["risk_policy_version"]
    assert revision.known_at == datetime.fromisoformat(str(body["known_at"]))
    publish_audit = RiskPolicyAuditModel.objects.get(
        target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
        target_id=revision.risk_policy_version,
        action="publish",
    )
    assert publish_audit.actor_id == owner.pk


@pytest.mark.django_db
def test_non_owner_and_unauthenticated_users_cannot_publish_or_revoke() -> None:
    """Both endpoint operations remain scoped to the current authenticated owner."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-owner-boundary-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    stranger = get_user_model().objects.create_user(
        username=f"m1-risk-stranger-boundary-{uuid4().hex}",
        password="unused",
    )
    effective_from = (timezone.now() + timedelta(minutes=5)).isoformat()
    client = _KeyedAPIClient()
    payload = _payload(effective_from=effective_from, actor_user_id=owner.pk)

    unauthenticated_publish = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        payload,
        format="json",
    )
    client.force_authenticate(user=stranger)
    forbidden_publish = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        payload,
        format="json",
    )

    assert unauthenticated_publish.status_code == 403
    assert forbidden_publish.status_code == 403
    assert forbidden_publish["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert (
        RiskPolicyAuditModel.objects.filter(
            target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION
        ).count()
        == 0
    )
    assert owner.pk != stranger.pk

    client.force_authenticate(user=owner)
    published = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        payload,
        format="json",
    )
    assert published.status_code == 201
    version = published.json()["risk_policy_version"]
    client.force_authenticate(user=stranger)
    forbidden_revoke = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/{version}/revoke/",
        {"reason": "A non-owner cannot revoke this policy."},
        format="json",
    )
    assert forbidden_revoke.status_code == 403
    assert (
        RiskPolicyAuditModel.objects.filter(
            target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
            action="revoke",
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_owner_revocation_is_append_only_effective_and_duplicate_is_conflict() -> None:
    """The version remains intact while an actual actor/reason audit makes it unusable."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-revoke-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    start = timezone.now() + timedelta(minutes=5)
    published = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        _payload(effective_from=start.isoformat(), actor_user_id=owner.pk),
        format="json",
    )
    assert published.status_code == 201
    version = published.json()["risk_policy_version"]
    repository = DjangoM1RiskPolicyRevisionRepository()
    original = repository.list_revisions(account_id=account.pk)[0]
    original_values = (
        original.reason,
        original.source_snapshot,
        original.effective_from,
        original.effective_until,
    )

    revoke_url = f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/{version}/revoke/"
    revoked = client.post(
        revoke_url,
        {"reason": "I withdraw the current M1 risk decision."},
        format="json",
    )
    duplicate = client.post(
        revoke_url,
        {"reason": "Duplicate revocation request."},
        format="json",
    )

    assert revoked.status_code == 200
    assert revoked["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    revoked_body = revoked.json()
    assert revoked_body["revoked_by_user_id"] == owner.pk
    assert revoked_body["revocation_reason"] == "I withdraw the current M1 risk decision."
    assert duplicate.status_code == 409
    assert duplicate["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    after = repository.list_revisions(account_id=account.pk)[0]
    assert (after.reason, after.source_snapshot, after.effective_from, after.effective_until) == (
        original_values
    )
    assert after.revoked_at is not None
    assert after.revoked_by_user_id == owner.pk
    assert after.risk_policy_version == version
    revoke_audit = RiskPolicyAuditModel.objects.get(
        target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
        target_id=version,
        action="revoke",
    )
    assert revoke_audit.actor_id == owner.pk
    assert revoke_audit.reason == revoked_body["revocation_reason"]

    account_source = DjangoM1RiskPolicyAccountSourceReader().read_owner_source(
        account_id=account.pk
    )
    assert account_source is not None
    strategy_selection = build_strategy_m1_risk_source_reader().get_owner_inspection_selection(
        account.pk,
        owner.pk,
    )
    source_snapshot = build_m1_risk_source_snapshot(
        account_source=account_source,
        strategy_selection=strategy_selection,
    )
    read_case = GetM1RiskPolicyQualificationUseCase(repository)
    qualification = read_case.execute(
        account_id=account.pk,
        as_of=max(after.revoked_at, after.effective_from) + timedelta(seconds=1),
        current_source=source_snapshot,
    )
    assert qualification.state is RiskQualificationState.REVOKED
    assert qualification.ready_for_buy is False


@pytest.mark.django_db
def test_missing_or_cross_account_revocation_returns_json_not_found() -> None:
    """Version IDs are scoped to their account path and missing versions do not audit."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-missing-version-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    other_owner, other_account = owner_case._create_owner_account(
        username=f"m1-risk-other-account-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    missing = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/{uuid4()}/revoke/",
        {"reason": "No matching version was found."},
        format="json",
    )
    assert missing.status_code == 404
    assert missing["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    cross_publish = client.post(
        f"/api/account/accounts/{other_account.pk}/m1-risk-policy-revisions/",
        _payload(
            effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
            actor_user_id=owner.pk,
        ),
        format="json",
    )
    assert cross_publish.status_code == 403
    published = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        _payload(
            effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
            actor_user_id=owner.pk,
        ),
        format="json",
    )
    assert published.status_code == 201
    version = published.json()["risk_policy_version"]
    client.force_authenticate(user=other_owner)
    cross_account = client.post(
        f"/api/account/accounts/{other_account.pk}/m1-risk-policy-revisions/{version}/revoke/",
        {"reason": "A different account cannot revoke this version."},
        format="json",
    )

    assert cross_account.status_code == 404
    assert cross_account["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert (
        RiskPolicyAuditModel.objects.filter(
            target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
            action="revoke",
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_publish_requires_an_explicit_aware_interval() -> None:
    """DRF cannot turn a naive client timestamp into a server-local policy date."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-naive-window-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    payload = _payload(
        effective_from=(timezone.now() + timedelta(minutes=5)).replace(tzinfo=None).isoformat(),
        actor_user_id=owner.pk,
    )

    response = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        payload,
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert (
        RiskPolicyAuditModel.objects.filter(
            target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION
        ).count()
        == 0
    )


@pytest.mark.django_db
def test_policy_reader_returns_active_owner_version_for_preview_cutoff() -> None:
    """The same RiskCenter public read use case feeds the existing inspection preview."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-read-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    start = timezone.now() + timedelta(minutes=5)
    response = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        _payload(effective_from=start.isoformat(), actor_user_id=owner.pk),
        format="json",
    )
    assert response.status_code == 201

    repository = DjangoM1RiskPolicyRevisionRepository()
    revision = repository.list_revisions(account_id=account.pk)[0]
    account_source = DjangoM1RiskPolicyAccountSourceReader().read_owner_source(
        account_id=account.pk
    )
    assert account_source is not None
    selection = build_strategy_m1_risk_source_reader().get_owner_inspection_selection(
        account.pk,
        owner.pk,
    )
    qualification = build_m1_risk_policy_application().qualify.execute(
        account_id=account.pk,
        as_of=revision.effective_from,
        current_source=build_m1_risk_source_snapshot(
            account_source=account_source,
            strategy_selection=selection,
        ),
    )

    assert qualification.state is RiskQualificationState.QUALIFIED
    assert qualification.revision is not None
    assert qualification.revision.risk_policy_version == revision.risk_policy_version
    assert qualification.ready_for_buy is True


@pytest.mark.django_db
def test_publish_binds_owner_strategy_rule_content_and_detects_changed_source() -> None:
    """The real version is bound to the exact owner Strategy rule content."""

    user_model = get_user_model()
    user_model._default_manager.bulk_create(
        [user_model(username=f"strategy-profile-offset-{uuid4().hex}")]
    )
    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-strategy-source-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    owner_profile = AccountProfileModel.objects.get(user=owner)
    assert owner.pk != owner_profile.pk
    strategy = owner_case._create_strategy(
        user=owner,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    start = timezone.now() + timedelta(minutes=5)
    payload = _payload(
        effective_from=start.isoformat(),
        actor_user_id=owner.pk,
        strategy_id=strategy.pk,
    )
    response = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        payload,
        format="json",
    )

    assert response.status_code == 201
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    body = response.json()
    assert body["source_binding"]["strategy_selection_state"] == "configured"
    assert body["source_binding"]["strategy_id"] == strategy.pk
    revision = DjangoM1RiskPolicyRevisionRepository().list_revisions(account_id=account.pk)[0]
    assert revision.source_snapshot.strategy_id == strategy.pk
    assert revision.source_snapshot.position_rule_source_json is not None
    account_source = DjangoM1RiskPolicyAccountSourceReader().read_owner_source(
        account_id=account.pk
    )
    assert account_source is not None
    strategy_source_reader = build_strategy_m1_risk_source_reader()
    selection = strategy_source_reader.get_owner_inspection_selection(
        account.pk,
        owner.pk,
        strategy.pk,
    )
    assert selection.validated_selection_state == "configured"
    application = build_m1_risk_policy_application()
    original_qualification = application.qualify.execute(
        account_id=account.pk,
        as_of=revision.effective_from,
        current_source=build_m1_risk_source_snapshot(
            account_source=account_source,
            strategy_selection=selection,
        ),
    )

    rule = PositionManagementRuleModel.objects.get(strategy_id=strategy.pk)
    rule.buy_condition_expr = "current_price > 100"
    rule.save(update_fields=("buy_condition_expr",))
    changed_selection = strategy_source_reader.get_owner_inspection_selection(
        account.pk,
        owner.pk,
        strategy.pk,
    )
    changed_qualification = application.qualify.execute(
        account_id=account.pk,
        as_of=revision.effective_from,
        current_source=build_m1_risk_source_snapshot(
            account_source=account_source,
            strategy_selection=changed_selection,
        ),
    )

    assert original_qualification.state is RiskQualificationState.QUALIFIED
    assert changed_qualification.state is RiskQualificationState.SOURCE_CHANGED
    assert changed_qualification.ready_for_buy is False


@pytest.mark.django_db
def test_owner_cannot_publish_using_another_users_strategy_source() -> None:
    """A caller cannot bind a risk version to a foreign Strategy primary key."""

    user_model = get_user_model()
    user_model._default_manager.bulk_create([user_model(username=f"profile-offset-{uuid4().hex}")])
    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-local-owner-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    owner_profile = AccountProfileModel.objects.get(user=owner)
    assert owner.pk != owner_profile.pk
    stranger = get_user_model().objects.create_user(
        username=f"m1-risk-foreign-strategy-owner-{uuid4().hex}",
        password="unused",
    )
    foreign_strategy = owner_case._create_strategy(
        user=stranger,
        target_weights={owner_case.ASSET_BUY: 0.10},
        max_position_pct=20.0,
        max_total_position_pct=95.0,
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        _payload(
            effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
            actor_user_id=owner.pk,
            strategy_id=foreign_strategy.pk,
        ),
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert "STRATEGY_SELECTION_SOURCE_UNKNOWN" in response.json()["reason_codes"]
    assert M1RebalanceRiskPolicyRevisionModel.objects.filter(account_id=account.pk).count() == 0


@pytest.mark.django_db
def test_publish_retry_replays_exact_version_and_changed_body_conflicts() -> None:
    """A transport retry returns the committed source without creating a second version."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-idempotent-publish-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    path = f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/"
    payload = _payload(
        effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
        actor_user_id=owner.pk,
    )

    first = client.post(
        path,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="publish-retry-1",
    )
    retry = client.post(
        path,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="publish-retry-1",
    )
    changed_payload = dict(payload)
    changed_payload["max_total_position_limit_pct"] = "89"
    changed = client.post(
        path,
        changed_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="publish-retry-1",
    )

    assert first.status_code == retry.status_code == 201
    assert first.json() == retry.json()
    assert changed.status_code == 409
    assert changed.json()["code"] == "M1_RISK_POLICY_IDEMPOTENCY_CONFLICT"
    assert M1RebalanceRiskPolicyRevisionModel.objects.filter(account_id=account.pk).count() == 1
    assert (
        RiskPolicyAuditModel.objects.filter(
            target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
            target_id=first.json()["risk_policy_version"],
            action="publish",
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_authenticated_publish_requires_idempotency_key() -> None:
    """Mutation requests without an explicit submission identity are rejected."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-idempotency-required-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    client = APIClient()
    client.force_authenticate(user=owner)
    response = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        _payload(
            effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
            actor_user_id=owner.pk,
        ),
        format="json",
    )

    assert response.status_code == 400
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert response.json()["code"] == "M1_RISK_POLICY_IDEMPOTENCY_KEY_REQUIRED"
    assert M1RebalanceRiskPolicyRevisionModel.objects.filter(account_id=account.pk).count() == 0


@pytest.mark.django_db
def test_invalid_nonnullable_account_limit_cannot_be_declared_not_applicable() -> None:
    """An out-of-range stored cap becomes source-unknown even with an owner N/A claim."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-invalid-cap-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    account.max_position_pct = 101.0
    account.save(update_fields=("max_position_pct",))
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    payload = _payload(
        effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
        actor_user_id=owner.pk,
    )
    payload["max_single_position_applicability"] = "not_applicable"
    payload["max_single_position_limit_pct"] = ""
    payload["max_single_position_not_applicable_reason"] = (
        "Owner claims no single-position limit applies."
    )

    response = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        payload,
        format="json",
    )
    source = DjangoM1RiskPolicyAccountSourceReader().read_owner_source(account_id=account.pk)

    assert response.status_code == 400
    assert response["Content-Type"].split(";", maxsplit=1)[0] == "application/json"
    assert "ACCOUNT_MAX_SINGLE_POSITION_SOURCE_UNKNOWN" in response.json()["reason_codes"]
    assert source is not None
    assert source.max_single_position_pct is None
    assert source.invalid_limit_fields == ("max_single_position_pct",)
    assert M1RebalanceRiskPolicyRevisionModel.objects.filter(account_id=account.pk).count() == 0


@pytest.mark.django_db
def test_publish_retry_rechecks_live_owner_before_idempotent_replay() -> None:
    """An old owner cannot retrieve a replay after the account has changed hands."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-idempotency-old-owner-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    next_owner = get_user_model().objects.create_user(
        username=f"m1-risk-idempotency-new-owner-{uuid4().hex}",
        password="unused",
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    path = f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/"
    payload = _payload(
        effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
        actor_user_id=owner.pk,
    )
    first = client.post(
        path,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="old-owner-publish",
    )
    assert first.status_code == 201

    account.user_id = next_owner.pk
    account.save(update_fields=("user",))
    retry = client.post(
        path,
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="old-owner-publish",
    )

    assert retry.status_code == 403
    assert retry.json()["code"] == "M1_RISK_POLICY_OWNER_REQUIRED"
    assert M1RebalanceRiskPolicyRevisionModel.objects.filter(account_id=account.pk).count() == 1


@pytest.mark.django_db
def test_revoke_retry_returns_original_audit_and_changed_reason_conflicts() -> None:
    """A revoke retry replays one immutable event; a changed body cannot replace it."""

    owner, account = owner_case._create_owner_account(
        username=f"m1-risk-idempotent-revoke-{uuid4().hex}",
        positions=(),
        stop_loss_pct=8.0,
    )
    client = _KeyedAPIClient()
    client.force_authenticate(user=owner)
    published = client.post(
        f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/",
        _payload(
            effective_from=(timezone.now() + timedelta(minutes=5)).isoformat(),
            actor_user_id=owner.pk,
        ),
        format="json",
    )
    assert published.status_code == 201
    version = published.json()["risk_policy_version"]
    path = f"/api/account/accounts/{account.pk}/m1-risk-policy-revisions/{version}/revoke/"
    request_body = {"reason": "I withdraw this exact M1 risk decision."}

    first = client.post(
        path,
        request_body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="revoke-retry-1",
    )
    retry = client.post(
        path,
        request_body,
        format="json",
        HTTP_IDEMPOTENCY_KEY="revoke-retry-1",
    )
    changed = client.post(
        path,
        {"reason": "A changed revocation request."},
        format="json",
        HTTP_IDEMPOTENCY_KEY="revoke-retry-1",
    )

    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    assert changed.status_code == 409
    assert changed.json()["code"] == "M1_RISK_POLICY_IDEMPOTENCY_CONFLICT"
    assert (
        RiskPolicyAuditModel.objects.filter(
            target_type=RiskPolicyAuditModel.TARGET_M1_REBALANCE_REVISION,
            target_id=version,
            action="revoke",
        ).count()
        == 1
    )
