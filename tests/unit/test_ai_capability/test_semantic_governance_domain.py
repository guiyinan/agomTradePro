"""Domain tests for semantic-key governance values."""

from __future__ import annotations

import pytest

from apps.ai_capability.domain.semantic_governance import (
    SemanticCorrection,
    SemanticCorrectionBatch,
    canonical_batch_fingerprint,
    normalize_semantic_key,
)


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("realtime.alert.create", "realtime.alert.create"),
        ("  events.replay_events  ", "events.replay_events"),
        ("a.b", "a.b"),
        ("alpha_trigger.promotion_v2", "alpha_trigger.promotion_v2"),
    ],
)
def test_normalize_semantic_key_accepts_lowercase_dot_notation(
    raw_value: str,
    expected: str,
) -> None:
    """Valid semantic keys are trimmed without changing their segments."""

    assert normalize_semantic_key(raw_value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "single",
        "Realtime.alert",
        "realtime.Alert",
        "1realtime.alert",
        "realtime.1alert",
        ".realtime.alert",
        "realtime.alert.",
        "realtime..alert",
        "realtime-alert.create",
        "realtime.alert/create",
        "a." + ("b" * 254),
    ],
)
def test_normalize_semantic_key_rejects_invalid_values(value: str) -> None:
    """Invalid syntax and overlong semantic keys are rejected."""

    with pytest.raises(ValueError, match="semantic key"):
        normalize_semantic_key(value)


def test_semantic_correction_validates_set_and_remove_actions() -> None:
    """Set requires a key and remove never accepts a replacement key."""

    correction = SemanticCorrection(
        capability_key="  realtime.create.price_alert  ",
        action="set",
        semantic_key=" realtime.alert.create ",
    )

    assert correction.capability_key == "realtime.create.price_alert"
    assert correction.semantic_key == "realtime.alert.create"

    with pytest.raises(ValueError, match="requires semantic_key"):
        SemanticCorrection(
            capability_key="realtime.create.price_alert",
            action="set",
            semantic_key=None,
        )

    with pytest.raises(ValueError, match="must not include semantic_key"):
        SemanticCorrection(
            capability_key="realtime.create.price_alert",
            action="remove",
            semantic_key="realtime.alert.create",
        )

    with pytest.raises(ValueError, match="action"):
        SemanticCorrection(
            capability_key="realtime.create.price_alert",
            action="replace",
            semantic_key="realtime.alert.create",
        )


def test_semantic_batch_normalizes_metadata_and_preserves_order() -> None:
    """Batch metadata is trimmed while correction order remains authoritative."""

    first = SemanticCorrection("capability.one", "set", "semantic.one")
    second = SemanticCorrection("capability.two", "remove")

    batch = SemanticCorrectionBatch(
        idempotency_key="  batch-001  ",
        reason="  correct catalog collision  ",
        corrections=(first, second),
    )

    assert batch.idempotency_key == "batch-001"
    assert batch.reason == "correct catalog collision"
    assert batch.corrections == (first, second)


@pytest.mark.parametrize(
    ("idempotency_key", "reason", "match"),
    [
        ("", "reason", "idempotency key"),
        ("batch-001", "", "reason"),
    ],
)
def test_semantic_batch_rejects_empty_metadata(
    idempotency_key: str,
    reason: str,
    match: str,
) -> None:
    """Idempotency and audit reason are both required."""

    correction = SemanticCorrection("capability.one", "set", "semantic.one")

    with pytest.raises(ValueError, match=match):
        SemanticCorrectionBatch(idempotency_key, reason, (correction,))


def test_semantic_batch_rejects_empty_duplicate_and_oversized_corrections() -> None:
    """A batch contains one to one hundred unique capability keys."""

    correction = SemanticCorrection("capability.one", "set", "semantic.one")

    with pytest.raises(ValueError, match="at least one"):
        SemanticCorrectionBatch("batch-empty", "reason", ())

    with pytest.raises(ValueError, match="duplicate"):
        SemanticCorrectionBatch(
            "batch-duplicate",
            "reason",
            (correction, correction),
        )

    oversized = tuple(
        SemanticCorrection(
            capability_key=f"capability.item_{index}",
            action="set",
            semantic_key=f"semantic.item_{index}",
        )
        for index in range(101)
    )
    with pytest.raises(ValueError, match="at most 100"):
        SemanticCorrectionBatch("batch-large", "reason", oversized)


def test_semantic_batch_fingerprint_is_stable_and_order_sensitive() -> None:
    """Equivalent values hash equally while correction order changes the hash."""

    first = SemanticCorrection("capability.one", "set", "semantic.one")
    second = SemanticCorrection("capability.two", "remove")
    batch = SemanticCorrectionBatch("batch-001", "reason", (first, second))
    equivalent = SemanticCorrectionBatch("batch-001", "reason", (first, second))
    reordered = SemanticCorrectionBatch("batch-001", "reason", (second, first))

    fingerprint = canonical_batch_fingerprint(batch)

    assert fingerprint == canonical_batch_fingerprint(equivalent)
    assert fingerprint != canonical_batch_fingerprint(reordered)
    assert len(fingerprint) == 64
