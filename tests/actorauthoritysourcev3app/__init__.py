from django.apps import AppConfig


class ActorAuthoritySourceV3TestConfig(AppConfig):
    """Load only the isolated authority-source v3 schema."""

    name = "tests.actorauthoritysourcev3app"
    label = "account"
