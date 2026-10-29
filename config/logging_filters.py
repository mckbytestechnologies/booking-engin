import logging

from .request_context import request_id_var


class RequestIdFilter(logging.Filter):
    """Adds %(request_id)s to every log record."""

    def filter(self, record):
        record.request_id = request_id_var.get()
        return True