from bookings.models import Booking


def link_guest_bookings(user):
    """Attach earlier guest bookings made with this email. Only call this for an email
    that has been verified (registration verifies it by OTP before creating the user)."""
    return Booking.objects.filter(customer__isnull=True, customer_email__iexact=user.email) \
        .update(customer=user)