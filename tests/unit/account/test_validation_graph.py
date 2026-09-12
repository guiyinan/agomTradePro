"""Unit tests for bounded Account graph validation and decode reuse."""

from __future__ import annotations

import pytest

from apps.account.domain.validation_graph import (
    reuse_validated_decode,
    validation_graph_operation,
)


def test_equal_exact_json_payload_reuses_one_successful_decode_per_operation() -> None:
    calls = 0

    @reuse_validated_decode("test-equal-json")
    def decode(payload: object) -> object:
        nonlocal calls
        calls += 1
        if type(payload) is not dict:
            raise TypeError("payload must be an exact dictionary")
        return object()

    @validation_graph_operation
    def decode_twice() -> tuple[object, object]:
        return decode({"nested": ["same", 1]}), decode({"nested": ["same", 1]})

    first, second = decode_twice()

    assert first is second
    assert calls == 1


def test_non_exact_json_tree_never_bypasses_decoder_validation() -> None:
    calls = 0

    class DictionarySubclass(dict[str, object]):
        pass

    @reuse_validated_decode("test-exact-types")
    def decode(payload: object) -> object:
        nonlocal calls
        calls += 1
        if type(payload) is not dict:
            raise TypeError("payload must be an exact dictionary")
        return object()

    @validation_graph_operation
    def decode_valid_then_subclass() -> None:
        decode({"value": "same"})
        with pytest.raises(TypeError, match="exact dictionary"):
            decode(DictionarySubclass({"value": "same"}))

    decode_valid_then_subclass()

    assert calls == 2


def test_decode_cache_does_not_escape_operation_scope() -> None:
    calls = 0

    @reuse_validated_decode("test-operation-scope")
    def decode(payload: object) -> object:
        nonlocal calls
        calls += 1
        return object()

    first = decode({"value": "same"})
    second = decode({"value": "same"})

    assert first is not second
    assert calls == 2
