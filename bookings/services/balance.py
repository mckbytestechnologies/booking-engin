from decimal import Decimal

from ..models import Booking
from .pricing import money

ZERO = Decimal("0.00")


def paid_amount(booking):
    P = Booking.PaymentStatus
    if booking.payment_status == P.PAID:
        return money(booking.total_amount)
    if booking.payment_status == P.PARTIALLY_PAID:
        return money(min(booking.amount_paid, booking.total_amount))
    return ZERO


def outstanding(booking):
    return max(ZERO, money(booking.total_amount) - paid_amount(booking))