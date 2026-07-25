"""Prompt persistence, provider, and external-service adapters.

HTTP/DRF serializers belong to :mod:`apps.prompt.interface.serializers`; this
package intentionally exposes no shortcut imports so importing infrastructure
does not initialize ORM models or bypass the application facade.
"""

__all__: tuple[str, ...] = ()
