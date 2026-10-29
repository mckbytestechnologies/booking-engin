import logging

from django.conf import settings
from rest_framework import status as http
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler
from rest_framework.views import set_rollback

from .request_context import request_id_var

log = logging.getLogger(__name__)

CODES = {
    400: "bad_request", 401: "not_authenticated", 403: "permission_denied", 404: "not_found",
    405: "method_not_allowed", 415: "unsupported_media_type", 429: "throttled",
}


def _body(code, message, **extra):
    return {"error": {"code": code, "message": message, "request_id": request_id_var.get(), **extra}}


def api_exception_handler(exc, context):
    response = drf_handler(exc, context)

    if response is None:                                    # an unexpected exception: a bug
        request = context.get("request")
        log.exception("Unhandled API error on %s %s", getattr(request, "method", "?"),
                      getattr(request, "path", "?"))
        set_rollback()
        return Response(
            _body("server_error", "Something went wrong on our side. If it keeps happening, "
                                  "quote the request ID when you contact us."),
            status=http.HTTP_500_INTERNAL_SERVER_ERROR)

    data = response.data
    if isinstance(exc, ValidationError):
        if getattr(settings, "API_WRAP_VALIDATION", False):
            response.data = _body("validation_error", "Please correct the highlighted fields.", fields=data)
        return response                                      # default: the old shape, unchanged

    if isinstance(data, dict) and "error" in data:           # already in our shape
        return response

    detail = data.get("detail") if isinstance(data, dict) else None
    response.data = _body(CODES.get(response.status_code, "error"),
                          str(detail or "The request could not be completed."))
    return response