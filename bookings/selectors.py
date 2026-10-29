
from accounts.access import Role, properties_with_role
from bookings.models import Booking, Payment, RefundTask


def scoped_bookings(user):
    """Bookings belonging to properties accessible to the user."""
    return Booking.objects.filter(
        property__in=properties_with_role(user)
    ).select_related("property", "room")


def refunds_for(user):
    """Payments associated with properties managed by the user."""
    return Payment.objects.filter(
        group_ref__in=Booking.objects.filter(
            property__in=properties_with_role(
                user,
                min_role=Role.MANAGER,
            )
        ).values_list("group_ref", flat=True)
    )


def refund_tasks_for(user):
    """Refund tasks associated with properties managed by the user."""
    return RefundTask.objects.filter(
        booking__property__in=properties_with_role(
            user,
            min_role=Role.MANAGER,
        )
    ).select_related("booking", "booking__property", "booking__room")
