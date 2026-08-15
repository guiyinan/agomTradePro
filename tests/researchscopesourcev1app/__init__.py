from django.apps import AppConfig


class EvidenceScopeSourceV1TestConfig(AppConfig):
    """Load only the isolated Evidence scope-source v1 schema."""

    name = "tests.researchscopesourcev1app"
    label = "research"
