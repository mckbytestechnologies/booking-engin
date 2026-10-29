import hashlib

from django.core.cache import cache
from config.net import client_ip

WINDOW = 15 * 60
MAX_IP_EMAIL = 5
MAX_EMAIL = 20


def _ip(request):
    return request.META.get("REMOTE_ADDR", "")


def _keys(request, email):
    h = hashlib.sha256(email.encode()).hexdigest()[:32]
    return f"login:ipe:{_ip(request)}:{h}", f"login:e:{h}"


def _bump(key, window):
    cache.add(key, 0, window)
    return cache.incr(key)


def is_locked(request, email):
    ipe, e = _keys(request, email)
    return cache.get(ipe, 0) >= MAX_IP_EMAIL or cache.get(e, 0) >= MAX_EMAIL


def record_failure(request, email):
    for key in _keys(request, email):
        _bump(key, WINDOW)


def clear(request, email):
    cache.delete(_keys(request, email)[0])


def hit(scope, request, limit, window):
    """Count one use of a scope for this IP. True once the limit is exceeded."""
    return _bump(f"rl:{scope}:{_ip(request)}", window) > limit

def _ip(request):
    return client_ip(request)