"""Contract tests for the versioned owner-consent document."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import FrozenInstanceError

import pytest

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.simulated_corporate_action_consent_terms import (
    SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
    SimulatedCorporateActionConsentTerms,
    require_simulated_corporate_action_consent_terms,
)
from core.exceptions import ConfigurationError

_GOLDEN_TERMS_SHA256 = "6ee0ad13d2e0b9cff885bfdf9d1e0e2ccb837c0943bf2cab6cf90d8410031165"


def _terms() -> SimulatedCorporateActionConsentTerms:
    """Load exactly the reviewed version and pinned document digest."""
    return require_simulated_corporate_action_consent_terms(
        configured_version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        configured_sha256=_GOLDEN_TERMS_SHA256,
    )


def test_terms_document_is_frozen_canonical_and_pins_all_three_capabilities() -> None:
    terms = _terms()

    assert terms.version == "simulated-corporate-action-owner-terms.v2"
    capabilities_by_code = {item.code: item for item in terms.capabilities}
    assert tuple(item.code for item in terms.capabilities) == tuple(
        sorted(capability.value for capability in SimulatedCorporateActionWriteCapability)
    )
    assert len(terms.capabilities) == 3
    assert all(item.title and item.description for item in terms.capabilities)
    assert (
        "应得权益"
        in capabilities_by_code[
            SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE.value
        ].description
    )
    assert (
        "模拟到账"
        in capabilities_by_code[
            SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE.value
        ].description
    )
    assert (
        "不执行扣款"
        in capabilities_by_code[
            SimulatedCorporateActionWriteCapability.TAX_ASSESS.value
        ].description
    )
    assert (
        "余额不足"
        in capabilities_by_code[
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD.value
        ].description
    )
    assert (
        "不卖出资产"
        in capabilities_by_code[
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD.value
        ].description
    )
    assert any("有限有效期" in item for item in terms.general_limits)
    assert any("随时撤销" in item for item in terms.general_limits)
    assert any("不会向真实券商发出指令" in item for item in terms.general_limits)
    assert any("真实完税凭证" in item for item in terms.general_limits)

    payload = json.loads(terms.canonical_json)
    assert payload["domain"] == "agomtradepro.account.corporate-action-owner-consent"
    assert payload["schema_version"] == "account.corporate-action-owner-terms.v1"
    assert terms.canonical_json.encode("utf-8").decode("utf-8") == terms.canonical_json
    assert hashlib.sha256(terms.canonical_json.encode("utf-8")).hexdigest() == terms.sha256
    assert terms.sha256 == _GOLDEN_TERMS_SHA256

    with pytest.raises(FrozenInstanceError):
        terms.version = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        terms.capabilities[0].title = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("version", "digest"),
    (
        ("simulated-corporate-action-owner-terms.v1", _GOLDEN_TERMS_SHA256),
        (SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2, "0" * 64),
        (SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2, _GOLDEN_TERMS_SHA256.upper()),
        ("", _GOLDEN_TERMS_SHA256),
        (SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2, "not-a-sha256"),
    ),
)
def test_unknown_or_mismatched_configured_terms_fail_closed(
    version: str,
    digest: str,
) -> None:
    with pytest.raises(ConfigurationError):
        require_simulated_corporate_action_consent_terms(
            configured_version=version,
            configured_sha256=digest,
        )


@pytest.mark.parametrize(
    ("version", "digest"),
    ((None, _GOLDEN_TERMS_SHA256), (SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2, None)),
)
def test_non_string_configuration_fails_closed(version: object, digest: object) -> None:
    with pytest.raises(ConfigurationError):
        require_simulated_corporate_action_consent_terms(
            configured_version=version,  # type: ignore[arg-type]
            configured_sha256=digest,  # type: ignore[arg-type]
        )


def test_configured_version_and_hash_are_both_required_arguments() -> None:
    parameters = inspect.signature(require_simulated_corporate_action_consent_terms).parameters

    assert parameters["configured_version"].default is inspect.Parameter.empty
    assert parameters["configured_sha256"].default is inspect.Parameter.empty
