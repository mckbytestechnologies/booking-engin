from django.http import HttpResponseServerError
from django.template import loader

from .request_context import request_id_var


def server_error(request, template_name="500.html"):
    """Custom 500 page. Standalone, because the database or a context processor may be what failed."""
    rid = getattr(request, "request_id", None) or request_id_var.get()
    try:
        html = loader.render_to_string(template_name, {"request_id": rid})
    except Exception:
        html = f"<h1>Something went wrong</h1><p>Request ID: {rid}</p>"
    return HttpResponseServerError(html)