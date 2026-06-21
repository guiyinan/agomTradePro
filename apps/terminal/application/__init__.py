"""Terminal Application Layer public exports.

Package-level exports are resolved lazily to avoid importing infrastructure
composition helpers while lightweight application modules are being loaded.
"""

__all__ = [
    'ExecuteCommandUseCase',
    'ExecuteCommandRequest',
    'ExecuteCommandResponse',
    'ListCommandsUseCase',
    'CreateCommandUseCase',
    'UpdateCommandUseCase',
    'DeleteCommandUseCase',
    'CommandExecutionService',
]


def __getattr__(name: str):
    """Resolve legacy package-level imports without eager side effects."""

    if name == 'CommandExecutionService':
        from .services import CommandExecutionService

        return CommandExecutionService
    if name in {
        'ExecuteCommandUseCase',
        'ExecuteCommandRequest',
        'ExecuteCommandResponse',
        'ListCommandsUseCase',
        'CreateCommandUseCase',
        'UpdateCommandUseCase',
        'DeleteCommandUseCase',
    }:
        from . import use_cases

        return getattr(use_cases, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
