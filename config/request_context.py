import contextvars

# "-" means "no request in progress" (a management command, a test without a request).
request_id_var = contextvars.ContextVar("request_id", default="-")