"""Pure tests for policy-benchmark methodology bundle activation."""

import hashlib
import json
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from apps.portfolio.domain.policy_benchmark_definition import (
    PolicyBenchmarkConstituentDefinition,
    PolicyBenchmarkMethodologyRef,
    PortfolioPolicyBenchmarkDefinition,
)
from apps.portfolio.domain.policy_benchmark_methodology_activation import (
    POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_ARTIFACT_TYPE,
    POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CAPABILITY,
    PolicyBenchmarkMethodologyActivationActor,
    PolicyBenchmarkMethodologyActivationSubject,
    PolicyBenchmarkMethodologyBundle,
    PolicyBenchmarkMethodologyBundleActivation,
    validate_policy_benchmark_methodology_activation_root,
    validate_policy_benchmark_methodology_activation_successor,
)

NOW = datetime(2026, 8, 13, 6, tzinfo=UTC)


def _ref(kind: str, marker: str = "a") -> PolicyBenchmarkMethodologyRef:
    return PolicyBenchmarkMethodologyRef(
        owner="portfolio",
        artifact_type=kind,
        artifact_id=f"{kind}-cn-v1",
        artifact_version="v1",
        content_hash=marker * 64,
        recorded_at=NOW - timedelta(hours=1),
        valid_until=NOW + timedelta(days=30),
    )


def _definition(**changes: object) -> PortfolioPolicyBenchmarkDefinition:
    values: dict[str, object] = {
        "definition_id": "balanced-policy-benchmark",
        "definition_version": "v1",
        "base_currency": "CNY",
        "constituents": (
            PolicyBenchmarkConstituentDefinition("CSI300", "000300.SH", "CNY", Decimal("0.6"), 0),
            PolicyBenchmarkConstituentDefinition(
                "CGB_TOTAL_RETURN", "CBA00101.CS", "CNY", Decimal("0.4"), 1
            ),
        ),
        "trading_calendar_ref": _ref("trading_calendar_definition"),
        "price_fixing_ref": _ref("price_fixing_methodology"),
        "fx_fixing_ref": _ref("fx_fixing_methodology"),
        "corporate_action_ref": _ref("corporate_action_methodology"),
        "cost_tax_ref": _ref("cost_tax_methodology"),
        "valuation_timezone": "Asia/Shanghai",
        "valuation_cutoff": "15:00:00",
        "evaluation_window_days": 252,
        "max_price_age_seconds": 86400,
        "max_fx_age_seconds": 86400,
        "missing_price_policy": "fail_closed",
        "missing_fx_policy": "fail_closed",
        "recorded_at": NOW,
        "valid_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return PortfolioPolicyBenchmarkDefinition(**values)  # type: ignore[arg-type]


def _actor(actor_id: str, user_id: int) -> PolicyBenchmarkMethodologyActivationActor:
    return PolicyBenchmarkMethodologyActivationActor(
        actor_id=actor_id,
        user_id=user_id,
        role="benchmark_configurator",
    )


def _subject(
    definition: PortfolioPolicyBenchmarkDefinition,
    *,
    requested_at: datetime = NOW + timedelta(hours=1),
    supersedes: str | None = None,
    version: str = "v1",
) -> PolicyBenchmarkMethodologyActivationSubject:
    return PolicyBenchmarkMethodologyActivationSubject.create(
        subject_id=f"activate-{definition.definition_id}",
        subject_version=version,
        definition=definition,
        requested_by=_actor("requester", 101),
        requested_at=requested_at,
        supersedes_activation_hash=supersedes,
    )


def _activation(
    subject: PolicyBenchmarkMethodologyActivationSubject,
    *,
    issued_at: datetime = NOW + timedelta(hours=2),
    version: str = "v1",
) -> PolicyBenchmarkMethodologyBundleActivation:
    return PolicyBenchmarkMethodologyBundleActivation.create(
        activation_id=f"activation-{subject.definition_id}",
        activation_version=version,
        subject=subject,
        approved_by=_actor("approver", 202),
        issued_at=issued_at,
    )


def _canonical_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def test_bundle_is_one_ordered_five_source_artifact_and_replacements_rehash() -> None:
    definition = _definition()
    bundle = PolicyBenchmarkMethodologyBundle.from_definition(definition)
    source_types = tuple(ref.artifact_type for ref in bundle.methodology_refs)

    assert source_types == (
        "corporate_action_methodology",
        "cost_tax_methodology",
        "fx_fixing_methodology",
        "price_fixing_methodology",
        "trading_calendar_definition",
    )
    changed_definition = _definition(price_fixing_ref=_ref("price_fixing_methodology", "b"))
    changed = PolicyBenchmarkMethodologyBundle.from_definition(changed_definition)
    assert changed.bundle_hash != bundle.bundle_hash
    assert "bundle" not in {
        field.name for field in fields(PolicyBenchmarkMethodologyBundleActivation)
    }
    assert "subject" in {field.name for field in fields(PolicyBenchmarkMethodologyBundleActivation)}


def test_bundle_hash_is_canonical_and_ref_order_is_sealed() -> None:
    bundle = PolicyBenchmarkMethodologyBundle.from_definition(_definition())
    payload = bundle.to_payload()
    supplied_hash = payload.pop("bundle_hash")

    assert supplied_hash == _canonical_hash(payload)
    with pytest.raises(ValueError, match="fixed complete order"):
        replace(
            bundle,
            methodology_refs=tuple(reversed(bundle.methodology_refs)),
            bundle_hash="",
        )
    with pytest.raises(TypeError, match="exact Domain"):
        replace(
            bundle,
            methodology_refs=({"artifact_type": "corporate_action_methodology"},) * 5,  # type: ignore[arg-type]
            bundle_hash="",
        )


def test_subject_binds_exact_definition_identity_content_clocks_and_bundle() -> None:
    definition = _definition()
    subject = _subject(definition)

    assert subject.definition_id == definition.definition_id
    assert subject.definition_version == definition.definition_version
    assert subject.definition_identity_hash == definition.identity_hash
    assert subject.definition_content_hash == definition.content_hash
    assert subject.definition_recorded_at == definition.recorded_at
    assert subject.definition_valid_until == definition.valid_until
    assert subject.valid_until == definition.valid_until == subject.bundle.valid_until
    with pytest.raises(TypeError, match="exact PortfolioPolicyBenchmarkDefinition"):
        PolicyBenchmarkMethodologyActivationSubject.create(
            subject_id="subject",
            subject_version="v1",
            definition={"definition_id": definition.definition_id},  # type: ignore[arg-type]
            requested_by=_actor("requester", 101),
            requested_at=NOW + timedelta(hours=1),
            supersedes_activation_hash=None,
        )


def test_validity_is_exact_definition_and_five_ref_minimum() -> None:
    definition = _definition()
    subject = _subject(definition)

    with pytest.raises(ValueError, match="validity must agree"):
        replace(
            subject,
            definition_valid_until=subject.valid_until - timedelta(seconds=1),
            content_hash="",
        )
    with pytest.raises(ValueError, match="methodology minimum"):
        replace(
            subject.bundle,
            valid_until=subject.bundle.valid_until - timedelta(seconds=1),
            bundle_hash="",
        )


def test_requester_and_approver_are_distinct_server_human_staff() -> None:
    subject = _subject(_definition())

    with pytest.raises(ValueError, match="server-authenticated human staff"):
        replace(_actor("requester", 101), authentication_source="client")
    with pytest.raises(ValueError, match="self approval"):
        replace(
            _activation(subject),
            approved_by=_actor(subject.requested_by.actor_id, 999),
            content_hash="",
        )
    with pytest.raises(ValueError, match="self approval"):
        replace(
            _activation(subject),
            approved_by=_actor("different-actor", subject.requested_by.user_id),
            content_hash="",
        )


def test_server_clocks_reject_naive_inverted_and_expired_values() -> None:
    definition = _definition()
    with pytest.raises(ValueError, match="timezone-aware"):
        _subject(definition, requested_at=datetime(2026, 8, 13, 7))
    with pytest.raises(ValueError, match="not knowable"):
        _subject(definition, requested_at=NOW - timedelta(seconds=1))

    subject = _subject(definition)
    with pytest.raises(ValueError, match="outside"):
        _activation(subject, issued_at=subject.requested_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="outside"):
        _activation(subject, issued_at=subject.valid_until)
    with pytest.raises(ValueError, match="clock_source"):
        replace(subject, clock_source="client", content_hash="")


def test_activation_authority_only_enables_configuration_bundle() -> None:
    activation = _activation(_subject(_definition()))
    payload = activation.to_payload()

    assert activation.owner == "portfolio"
    assert (
        activation.capability
        == activation.artifact_type
        == "policy_benchmark_methodology_bundle_activation"
    )
    assert activation.permission == "benchmark_configuration_only"
    assert activation.activates_configuration_bundle is True
    assert activation.daily_valuation_authority is False
    assert activation.broker_execution_authority is False
    assert activation.must_not_execute is True
    assert payload["daily_valuation_authority"] is False
    assert payload["broker_execution_authority"] is False
    with pytest.raises(ValueError, match="authority is fixed"):
        replace(activation, permission="broker_execution", content_hash="")
    assert (
        POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_CAPABILITY
        == POLICY_BENCHMARK_METHODOLOGY_ACTIVATION_ARTIFACT_TYPE
    )


def test_activation_hash_uses_canonical_json_and_utc_z_clocks() -> None:
    activation = _activation(_subject(_definition()))
    payload = activation.to_payload()
    supplied_hash = payload.pop("content_hash")
    payload.pop("activates_configuration_bundle")
    payload.pop("daily_valuation_authority")
    payload.pop("broker_execution_authority")
    payload.pop("must_not_execute")

    assert supplied_hash == _canonical_hash(payload)
    assert payload["issued_at"].endswith("Z")  # type: ignore[union-attr]
    with pytest.raises(ValueError, match="content_hash"):
        replace(activation, issued_at=activation.issued_at + timedelta(seconds=1))


def test_root_and_successor_allow_exact_bundle_replacement_without_fork() -> None:
    root = _activation(_subject(_definition()))
    validate_policy_benchmark_methodology_activation_root(root)

    next_definition = _definition(
        definition_version="v2",
        price_fixing_ref=_ref("price_fixing_methodology", "b"),
        recorded_at=NOW + timedelta(hours=3),
    )
    successor = _activation(
        _subject(
            next_definition,
            requested_at=NOW + timedelta(hours=4),
            supersedes=root.content_hash,
            version="v2",
        ),
        issued_at=NOW + timedelta(hours=5),
        version="v2",
    )
    validate_policy_benchmark_methodology_activation_successor(root, successor)
    assert successor.subject.definition_content_hash != root.subject.definition_content_hash
    assert successor.subject.bundle.bundle_hash != root.subject.bundle.bundle_hash

    with pytest.raises(ValueError, match="predecessor"):
        validate_policy_benchmark_methodology_activation_successor(
            successor,
            replace(
                successor,
                subject=replace(
                    successor.subject,
                    supersedes_activation_hash=root.content_hash,
                    requested_at=NOW + timedelta(hours=6),
                    content_hash="",
                ),
                issued_at=NOW + timedelta(hours=7),
                content_hash="",
            ),
        )


def test_root_predecessor_cross_definition_and_nonadvancing_clocks_fail_closed() -> None:
    root = _activation(_subject(_definition()))
    with pytest.raises(ValueError, match="must not declare"):
        validate_policy_benchmark_methodology_activation_root(
            _activation(_subject(_definition(), supersedes="c" * 64))
        )

    other_definition = _definition(definition_id="other-policy-benchmark")
    other = _activation(
        _subject(
            other_definition,
            requested_at=NOW + timedelta(hours=3),
            supersedes=root.content_hash,
        ),
        issued_at=NOW + timedelta(hours=4),
    )
    with pytest.raises(ValueError, match="logical benchmark"):
        validate_policy_benchmark_methodology_activation_successor(root, other)

    same_clock = replace(
        other,
        subject=replace(
            other.subject,
            definition_id=root.subject.definition_id,
            definition_identity_hash=root.subject.definition_identity_hash,
            requested_at=root.issued_at,
            content_hash="",
        ),
        issued_at=root.issued_at,
        content_hash="",
    )
    with pytest.raises(ValueError, match="request clock must advance"):
        validate_policy_benchmark_methodology_activation_successor(root, same_clock)


def test_domain_module_has_no_framework_cross_app_or_individual_activation_surface() -> None:
    source = Path("apps/portfolio/domain/policy_benchmark_methodology_activation.py").read_text(
        encoding="utf-8"
    )
    activation_fields = {field.name for field in fields(PolicyBenchmarkMethodologyBundleActivation)}

    assert "django" not in source
    assert "from apps." not in source
    assert "import apps." not in source
    assert (
        not {
            "corporate_action_activation",
            "cost_tax_activation",
            "fx_fixing_activation",
            "price_fixing_activation",
            "trading_calendar_activation",
        }
        & activation_fields
    )
    assert "PolicyBenchmarkMethodologyRef(" not in source
