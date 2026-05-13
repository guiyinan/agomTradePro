"""Custom staticfiles finders for project-specific filtering."""

from __future__ import annotations

from collections.abc import Iterator

from django.contrib.staticfiles.finders import AppDirectoriesFinder


class ProjectAppDirectoriesFinder(AppDirectoriesFinder):
    """Filter known third-party duplicate admin assets during collection."""

    _JAZZMIN_DUPLICATE_ADMIN_PATHS = {
        "admin/js/cancel.js",
        "admin/js/popup_response.js",
    }

    def list(self, ignore_patterns: list[str]) -> Iterator[tuple[str, object]]:
        """Yield app static files, excluding duplicate Jazzmin admin shims."""
        for path, storage in super().list(ignore_patterns):
            normalized_path = path.replace("\\", "/")
            location = str(getattr(storage, "location", ""))
            if (
                normalized_path in self._JAZZMIN_DUPLICATE_ADMIN_PATHS
                and "jazzmin" in location.replace("\\", "/").lower()
            ):
                continue
            yield path, storage
