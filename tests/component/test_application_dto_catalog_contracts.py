"""Architecture and serialization contracts for Application DTO catalogs."""

from dataclasses import fields, is_dataclass
from importlib import import_module
from pathlib import Path
from types import ModuleType

import pytest

DTO_MODULES = {
    "apps.agent_runtime.application.dtos": 10,
    "apps.alpha.application.dtos": 2,
    "apps.dashboard.application.dtos": 2,
    "apps.pulse.application.dtos": 1,
    "apps.sentiment.application.dtos": 2,
    "apps.share.application.dtos": 5,
    "apps.strategy.application.dtos": 5,
}


def _local_dto_classes(module: ModuleType) -> list[type[object]]:
    return [
        value
        for name, value in vars(module).items()
        if isinstance(value, type)
        and value.__module__ == module.__name__
        and (name.endswith("DTO") or name.endswith("Request") or name.endswith("Response"))
    ]


@pytest.mark.parametrize(("module_name", "minimum_count"), DTO_MODULES.items())
def test_application_dto_catalog_is_typed_and_framework_free(
    module_name: str,
    minimum_count: int,
) -> None:
    """DTO modules must publish typed dataclasses without framework coupling."""

    module = import_module(module_name)
    dto_classes = _local_dto_classes(module)

    assert len(dto_classes) >= minimum_count, module_name
    for dto_class in dto_classes:
        assert is_dataclass(dto_class), f"{module_name}.{dto_class.__name__}"
        dto_fields = fields(dto_class)
        assert dto_fields, f"{module_name}.{dto_class.__name__}"
        assert all(field.type is not None for field in dto_fields)

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "django." not in source
    assert ".infrastructure" not in source
