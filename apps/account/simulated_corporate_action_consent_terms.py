"""Pinned, human-readable terms for explicit simulated-action owner consent."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from core.exceptions import ConfigurationError

SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2 = "simulated-corporate-action-owner-terms.v2"
_TERMS_DOMAIN = "agomtradepro.account.corporate-action-owner-consent"
_TERMS_SCHEMA = "account.corporate-action-owner-terms.v1"
_INTRODUCTION = (
    "本授权仅适用于模拟公司行为操作。请查看下方能力说明，系统只记录您明确选择且页面列出的能力。"
)
_GENERAL_LIMITS = (
    "授权仅限页面展示的准确模拟账户、明确勾选的能力及有限有效期。",
    "您可随时撤销；事实缺失或来源、持仓历史、政策未通过核验时，相应操作会被阻止。",
    "所有操作均为模拟，不会向真实券商发出指令，也不会生成真实完税凭证。",
)


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionConsentCapabilityTerms:
    """One fixed capability description included in the offered terms."""

    code: str
    title: str
    description: str


_CAPABILITIES = (
    SimulatedCorporateActionConsentCapabilityTerms(
        code=SimulatedCorporateActionWriteCapability.TAX_ASSESS.value,
        title="模拟税额评估",
        description="允许记录经来源、持仓历史和适用政策核验的模拟税额评估；此能力本身不执行扣款。",
    ),
    SimulatedCorporateActionConsentCapabilityTerms(
        code=SimulatedCorporateActionWriteCapability.TAX_WITHHOLD.value,
        title="模拟税款扣除",
        description="允许仅从可用模拟现金中扣除已到期评估的税额；余额不足时显示待扣，不卖出资产或提交订单。",
    ),
    SimulatedCorporateActionConsentCapabilityTerms(
        code=SimulatedCorporateActionWriteCapability.CASH_STAGE_WRITE.value,
        title="现金分红模拟权益与模拟到账",
        description="允许按已声明的现金分红条款模拟应得权益与模拟到账。",
    ),
)


def _canonical_document_json() -> str:
    """Serialize the fixed document using stable UTF-8 JSON conventions."""
    payload: dict[str, object] = {
        "domain": _TERMS_DOMAIN,
        "schema_version": _TERMS_SCHEMA,
        "version": SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        "introduction": _INTRODUCTION,
        "capabilities": [
            {"code": item.code, "title": item.title, "description": item.description}
            for item in _CAPABILITIES
        ],
        "general_limits": list(_GENERAL_LIMITS),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionConsentTerms:
    """Immutable whole consent document and its canonical content digest."""

    version: str
    introduction: str
    capabilities: tuple[SimulatedCorporateActionConsentCapabilityTerms, ...]
    general_limits: tuple[str, ...]
    canonical_json: str
    sha256: str

    def __post_init__(self) -> None:
        """Reject objects that do not exactly represent the pinned V2 document."""
        if (
            type(self.version) is not str
            or self.version != SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2
        ):
            raise ValueError("consent terms version is not the pinned V2 version")
        if type(self.introduction) is not str or self.introduction != _INTRODUCTION:
            raise ValueError("consent terms introduction does not match the pinned document")
        if type(self.capabilities) is not tuple or self.capabilities != _CAPABILITIES:
            raise ValueError("consent capability terms do not match the pinned document")
        if any(
            type(item) is not SimulatedCorporateActionConsentCapabilityTerms
            for item in self.capabilities
        ):
            raise TypeError("consent capabilities must be exact frozen terms values")
        if type(self.general_limits) is not tuple or self.general_limits != _GENERAL_LIMITS:
            raise ValueError("consent limits do not match the pinned document")
        if any(type(item) is not str for item in self.general_limits):
            raise TypeError("consent limits must be strings")
        expected_json = _canonical_document_json()
        if type(self.canonical_json) is not str or self.canonical_json != expected_json:
            raise ValueError("consent canonical JSON does not match the pinned document")
        expected_sha256 = hashlib.sha256(expected_json.encode("utf-8")).hexdigest()
        if type(self.sha256) is not str or self.sha256 != expected_sha256:
            raise ValueError("consent terms digest does not match canonical UTF-8 JSON")


def require_simulated_corporate_action_consent_terms(
    configured_version: str,
    configured_sha256: str,
) -> SimulatedCorporateActionConsentTerms:
    """Return the pinned V2 document only when explicit configuration matches it."""
    canonical_json = _canonical_document_json()
    computed_sha256 = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    if (
        type(configured_version) is not str
        or type(configured_sha256) is not str
        or configured_version != SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2
        or configured_sha256 != computed_sha256
    ):
        raise ConfigurationError(
            "simulated corporate-action consent terms configuration is unknown or mismatched"
        )

    return SimulatedCorporateActionConsentTerms(
        version=SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2,
        introduction=_INTRODUCTION,
        capabilities=_CAPABILITIES,
        general_limits=_GENERAL_LIMITS,
        canonical_json=canonical_json,
        sha256=computed_sha256,
    )


__all__ = [
    "SIMULATED_CORPORATE_ACTION_OWNER_TERMS_V2",
    "SimulatedCorporateActionConsentCapabilityTerms",
    "SimulatedCorporateActionConsentTerms",
    "require_simulated_corporate_action_consent_terms",
]
