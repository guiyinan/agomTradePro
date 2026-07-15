"""Structural contracts for the Dashboard Alpha homepage query."""

from apps.dashboard.application.alpha_homepage import AlphaHomepageQuery
from apps.dashboard.application.alpha_homepage_candidates import AlphaCandidateMixin
from apps.dashboard.application.alpha_homepage_exit_watch import AlphaExitWatchMixin
from apps.dashboard.application.alpha_homepage_history import AlphaHistoryMixin
from apps.dashboard.application.alpha_homepage_runtime import AlphaRuntimeMixin


def test_alpha_homepage_query_composes_private_collaborators() -> None:
    """Keep one public query while delegating the four internal responsibilities."""
    assert issubclass(AlphaHomepageQuery, AlphaExitWatchMixin)
    assert issubclass(AlphaHomepageQuery, AlphaRuntimeMixin)
    assert issubclass(AlphaHomepageQuery, AlphaCandidateMixin)
    assert issubclass(AlphaHomepageQuery, AlphaHistoryMixin)

    for public_method in (
        "execute",
        "list_history",
        "get_history_detail",
    ):
        assert callable(getattr(AlphaHomepageQuery, public_method))
