import logging
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from properties.models import Property

from ..models import Booking, EmailOTP
from .errors import BookingError
from .stay import mark_no_show
from .transitions import apply_transition

log = logging.getLogger(__name__)
S = Booking.Status


def expire_holds(now=None):
    now = now or timezone.now()
    ids = list(Booking.objects.filter(status=S.PENDING, expires_at__lte=now).values_list("pk", flat=True))
    done = 0
    for pk in ids:
        with transaction.atomic():
            b = Booking.objects.select_for_update().filter(pk=pk).first()
            if b is None or b.status != S.PENDING or b.expires_at is None or b.expires_at > now:
                continue                      # paid or changed since we listed it
            apply_transition(b, S.EXPIRED, reason="Hold expired")
            done += 1
    return done


def auto_no_shows(now=None):
    now = now or timezone.now()
    done = 0
    for prop in Property.objects.all():
        today = now.astimezone(ZoneInfo(prop.timezone)).date()
        ids = list(Booking.objects.filter(property=prop, status=S.CONFIRMED, check_in__lt=today)
                   .values_list("pk", flat=True))
        for pk in ids:
            try:
                mark_no_show(pk, now=now)
                done += 1
            except BookingError as exc:
                log.warning("Auto no-show skipped for booking %s: %s", pk, exc.code)
    return done


def cleanup_otps(now=None):
    now = now or timezone.now()
    return EmailOTP.objects.filter(created_at__lt=now - timedelta(days=1)).delete()[0]