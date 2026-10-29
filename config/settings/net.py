from django.conf import settings


def client_ip(request):
    """The real client address. X-Forwarded-For can be forged by the client, so we only trust
    the entries added by OUR proxies: with N proxies, the Nth entry from the right."""
    remote = request.META.get("REMOTE_ADDR", "")
    n = settings.TRUSTED_PROXY_COUNT
    if n <= 0:
        return remote
    parts = [p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    return parts[-n] if len(parts) >= n else remote