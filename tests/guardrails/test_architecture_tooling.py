import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_script_module(script_name: str, module_name: str):
    script_path = REPO_ROOT / "scripts" / script_name
    sys.path.insert(0, str(script_path.parent))
    try:
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(module_name, None)
        sys.path.pop(0)


def test_check_architecture_delta_parse_added_lines_tracks_only_added_lines():
    module = _load_script_module(
        "check_architecture_delta.py",
        "test_check_architecture_delta",
    )
    diff_text = """diff --git a/apps/prompt/interface/views.py b/apps/prompt/interface/views.py
+++ b/apps/prompt/interface/views.py
@@ -10,2 +10,4 @@
 keep_one
+from apps.ai_provider.infrastructure.client_factory import AIClientFactory
 keep_two
+from ..infrastructure.repositories import DjangoPromptRepository
@@ -40,0 +43,2 @@
+queryset = PromptTemplateORM._default_manager.all()
+serializer_class = PromptTemplateSerializer
"""

    added_lines = module.parse_added_lines(diff_text)

    assert added_lines == {
        "apps/prompt/interface/views.py": {11, 13, 43, 44},
    }


def test_check_architecture_delta_filters_violations_to_added_lines():
    module = _load_script_module(
        "check_architecture_delta.py",
        "test_check_architecture_delta_filter",
    )
    violations = [
        {"source_path": "apps/prompt/interface/views.py", "lineno": 11, "rule_id": "a"},
        {"source_path": "apps/prompt/interface/views.py", "lineno": 12, "rule_id": "b"},
        {"source_path": "apps/equity/interface/views.py", "lineno": 5, "rule_id": "c"},
    ]
    added_lines = {
        "apps/prompt/interface/views.py": {11},
        "apps/equity/interface/views.py": {8},
    }

    filtered = module.filter_violations_to_added_lines(violations, added_lines)

    assert filtered == [
        {"source_path": "apps/prompt/interface/views.py", "lineno": 11, "rule_id": "a"},
    ]


def test_scaffold_application_providers_renders_grouped_imports():
    module = _load_script_module(
        "scaffold_application_providers.py",
        "test_scaffold_application_providers",
    )
    specs = [
        module.ProviderSpec(
            function_name="get_prompt_repository",
            module_path="apps.prompt.infrastructure.repositories",
            symbol_name="DjangoPromptRepository",
        ),
        module.ProviderSpec(
            function_name="get_execution_log_repository",
            module_path="apps.prompt.infrastructure.repositories",
            symbol_name="DjangoExecutionLogRepository",
        ),
        module.ProviderSpec(
            function_name="get_ai_client_factory",
            module_path="apps.ai_provider.infrastructure.client_factory",
            symbol_name="AIClientFactory",
        ),
    ]

    content = module.render_provider_module("prompt", specs)

    assert '"""Provider helpers for prompt application consumers."""' in content
    assert "from apps.ai_provider.infrastructure.client_factory import AIClientFactory" in content
    assert "from apps.prompt.infrastructure.repositories import (" in content
    assert "DjangoExecutionLogRepository" in content
    assert "DjangoPromptRepository" in content
    assert "def get_prompt_repository() -> DjangoPromptRepository:" in content
    assert "return DjangoPromptRepository()" in content
