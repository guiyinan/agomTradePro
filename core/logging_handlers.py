"""Custom logging handlers used by the application."""

import logging

from .log_buffer import append_record


class InMemoryLogHandler(logging.Handler):
    """Push formatted logs into an in-memory ring buffer for admin viewing."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            append_record(record, message)
        except Exception:
            self.handleError(record)
