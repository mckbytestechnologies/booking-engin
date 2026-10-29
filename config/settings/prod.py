from .base import *  # noqa: F401,F403

DEBUG = False

# Behind NGINX: it terminates HTTPS and tells Django through this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)        # noqa: F405
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])        # noqa: F405  e.g. https://yourdomain.com

# Start small: HSTS tells browsers "HTTPS only" for this long, and cannot be undone early.
# Raise to 31536000 (1 year) once HTTPS has worked for a few weeks.
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=3600)          # noqa: F405
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"