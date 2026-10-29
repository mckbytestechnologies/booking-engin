import hashlib
import logging

from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from config.net import client_ip

from .access import is_staff_member

audit = logging.getLogger("app.audit")


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    audit.info("login ok user=%s staff=%s ip=%s", user.pk, is_staff_member(user),
               client_ip(request) if request else "-")


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    # A short hash lets you spot repeated attempts on one account without storing the email.
    who = hashlib.sha256((credentials.get("username") or "").strip().lower().encode()).hexdigest()[:12]
    audit.warning("login failed id=%s ip=%s", who, client_ip(request) if request else "-")