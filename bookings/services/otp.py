import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from ..models import EmailOTP
from .errors import OtpDeliveryFailed, OtpInvalid, OtpThrottled

logger = logging.getLogger(__name__)

TTL_MINUTES = 10
RESEND_SECONDS = 60
MAX_ATTEMPTS = 5


def normalize_email(email):
    return (email or "").strip().lower()


def _hash(email, code):
    return hmac.new(settings.SECRET_KEY.encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def send_otp(email):
    email = normalize_email(email)
    now = timezone.now()

    last = EmailOTP.objects.filter(email=email).first()          # newest (Meta.ordering)
    if last and (now - last.created_at).total_seconds() < RESEND_SECONDS:
        raise OtpThrottled("Please wait a minute before requesting another code.")

    code = f"{secrets.randbelow(10 ** 6):06d}"
    with transaction.atomic():
        # Only the newest code is ever valid.
        EmailOTP.objects.filter(email=email, verified_at__isnull=True).update(expires_at=now)
        otp = EmailOTP.objects.create(
            email=email, code_hash=_hash(email, code), expires_at=now + timedelta(minutes=TTL_MINUTES)
        )

    try:
        send_mail(
            subject="Your verification code",
            message=(f"Your verification code is {code}.\n\n"
                     f"It expires in {TTL_MINUTES} minutes. If you did not request it, ignore this email."),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    except Exception:
        logger.exception("OTP email delivery failed")             # the code itself is never logged
        otp.delete()
        raise OtpDeliveryFailed("We could not send the email. Please try again shortly.")


def verify_otp(email, code):
    email = normalize_email(email)
    now = timezone.now()
    error = None

    with transaction.atomic():
        otp = (EmailOTP.objects.select_for_update()
               .filter(email=email, verified_at__isnull=True, expires_at__gt=now)
               .order_by("-created_at").first())
        if otp is None:
            error = "This code has expired or was not found. Request a new one."
        elif otp.attempts >= MAX_ATTEMPTS:
            error = "Too many incorrect attempts. Request a new code."
        else:
            otp.attempts += 1                                     # counted before comparing
            if hmac.compare_digest(otp.code_hash, _hash(email, code)):
                otp.verified_at = now
            else:
                error = "Incorrect code."
            otp.save(update_fields=["attempts", "verified_at"])

    if error:                                                     # raise AFTER commit so attempts persist
        raise OtpInvalid(error)

import time

VERIFIED_WINDOW_SECONDS = 30 * 60


def mark_verified(session, email):
    session["verified_email"] = email
    session["verified_at"] = time.time()


def is_verified(session, email):
    if session.get("verified_email") != email:
        return False
    return 0 <= time.time() - session.get("verified_at", 0) <= VERIFIED_WINDOW_SECONDS


def clear_verified(session):
    session.pop("verified_email", None)
    session.pop("verified_at", None)