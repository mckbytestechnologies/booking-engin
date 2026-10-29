from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from ..models import Booking
from .pricing import money
from .balance import paid_amount

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class CancellationOutcome:
    free: bool
    deadline: datetime
    penalty: Decimal
    refund: Decimal          # what goes back to the guest (only if they have paid)
    paid: bool
    waived: bool = False


def free_deadline(booking):
    prop = booking.property
    start = datetime.combine(booking.check_in, prop.check_in_time, tzinfo=ZoneInfo(prop.timezone))
    return start - timedelta(hours=prop.free_cancellation_hours)


def assess(booking, now=None):
    """Pure policy: free until the deadline, then first night + its tax (capped at the total)."""
    now = now or timezone.now()
    deadline = free_deadline(booking)
    paid = booking.payment_status == Booking.PaymentStatus.PAID
    free = booking.status == Booking.Status.PENDING or now <= deadline    # an unpaid hold costs nothing
    if free:
        penalty = ZERO
    else:
        rate = Decimal(booking.property.tax_percent) / 100
        penalty = min(money(booking.price_per_night * (1 + rate)), booking.total_amount)
    refund = money(booking.total_amount - penalty) if paid else ZERO
    return CancellationOutcome(free, deadline, penalty, refund, paid)

def assess(booking, now=None):
    """Pure policy: free until the deadline, then first night + its tax (capped at the total)."""
    now = now or timezone.now()
    deadline = free_deadline(booking)
    paid = paid_amount(booking)
    free = booking.status == Booking.Status.PENDING or now <= deadline    # an unpaid hold costs nothing
    if free:
        penalty = ZERO
    else:
        rate = Decimal(booking.property.tax_percent) / 100
        penalty = min(money(booking.price_per_night * (1 + rate)), booking.total_amount)
    refund = money(max(ZERO, paid - penalty))
    return CancellationOutcome(free, deadline, penalty, refund, paid > 0)