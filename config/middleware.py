import logging
import re
import time
import uuid

from django.conf import settings

from .request_context import request_id_var

log = logging.getLogger("app.request")
VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestIdMiddleware:
    """Gives each request an ID, logs one summary line, and returns the ID in a header.
    Never logs bodies, headers or query strings: they can contain emails, OTP codes and signatures."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.headers.get("X-Request-ID", "")
        rid = incoming if VALID_ID.match(incoming) else uuid.uuid4().hex[:16]
        request.request_id = rid
        token = request_id_var.set(rid)
        start = time.monotonic()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = rid
            self._log(request, response, start)
            return response
        finally:
            request_id_var.reset(token)

    @staticmethod
    def _log(request, response, start):
        if request.path.startswith(settings.STATIC_URL):
            return
        ms = int((time.monotonic() - start) * 1000)
        user = getattr(request, "_cached_user", None)          # already loaded: no extra database query
        uid = user.pk if user is not None and user.is_authenticated else "-"
        status = response.status_code
        level = logging.INFO if status < 400 else logging.WARNING if status < 500 else logging.ERROR
        log.log(level, "%s %s %s %sms user=%s", request.method, request.path, status, ms, uid)