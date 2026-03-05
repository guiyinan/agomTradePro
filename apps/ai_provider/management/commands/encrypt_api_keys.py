"""
Compatibility command entrypoint.

Keep the command discoverable at the standard Django location while
reusing the infrastructure implementation.
"""

from apps.ai_provider.infrastructure.management.commands.encrypt_api_keys import Command

