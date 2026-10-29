import logging

import requests
from django.conf import settings

from .errors import PaymentGatewayError

logger = logging.getLogger(__name__)
API = "https://api.razorpay.com/v1"


def create_order(amount, currency, receipt, notes=None):
    try:
        resp = requests.post(
            f"{API}/orders",
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
            json={"amount": amount, "currency": currency, "receipt": receipt, "notes": notes or {}},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        logger.exception("Razorpay order creation failed")
        raise PaymentGatewayError("The payment service is unavailable. Please try again shortly.")