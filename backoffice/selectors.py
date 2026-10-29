# from django.utils import timezone

# from accounts.access import Role, properties_with_role
# from bookings.models import Booking, Payment
# from bookings.models import RefundTask

# def scoped_bookings(user, min_role=Role.RECEPTIONIST):
#     """The ONLY way staff code should fetch bookings: limited to the user's properties."""
#     return Booking.objects.filter(property__in=properties_with_role(user, min_role))


# def refunds_for(user):
#     props = properties_with_role(user, Role.MANAGER)
#     groups = Booking.objects.filter(property__in=props).values("group_ref")
#     return Payment.objects.filter(status=Payment.Status.REFUND_REQUIRED, group_ref__in=groups)


# def dashboard_rows(user):
#     now = timezone.now()
#     managed = set(properties_with_role(user, Role.MANAGER).values_list("id", flat=True))
#     rows = []
#     for prop in properties_with_role(user).order_by("name"):
#         today = prop.local_today()                      # property-local date, not server date
#         qs = Booking.objects.filter(property=prop)
#         rows.append({
#             "property": prop, "today": today,
#             "arrivals": qs.filter(status=Booking.Status.CONFIRMED, check_in=today).count(),
#             "in_house": qs.filter(status=Booking.Status.CHECKED_IN).count(),
#             "due_out": qs.filter(status=Booking.Status.CHECKED_IN, check_out__lte=today).count(),
#             "holds": qs.filter(status=Booking.Status.PENDING, expires_at__gt=now).count(),
#             "refunds": (Payment.objects.filter(status=Payment.Status.REFUND_REQUIRED,
#                                                group_ref__in=qs.values("group_ref")).count()
#                         if prop.id in managed else None),     # managers only
#         })
#     return rows

# def refund_tasks_for(user):
#     return RefundTask.objects.filter(
#         booking__property__in=properties_with_role(user, Role.MANAGER)
#     ).select_related("booking")

from accounts.access import Role, properties_with_role
from bookings.models import Booking, ExtensionRequest, Payment, RefundTask
from django.utils import timezone
from rooms.models import Room


def scoped_bookings(user, min_role=Role.RECEPTIONIST):
    """The ONLY way staff code should fetch bookings: limited to the user's properties."""
    return Booking.objects.filter(property__in=properties_with_role(user, min_role))


def refunds_for(user):
    props = properties_with_role(user, Role.MANAGER)
    groups = Booking.objects.filter(property__in=props).values("group_ref")
    return Payment.objects.filter(status=Payment.Status.REFUND_REQUIRED, group_ref__in=groups)


def refund_tasks_for(user):
    return RefundTask.objects.filter(
        booking__property__in=properties_with_role(user, Role.MANAGER)
    ).select_related("booking")


def dashboard_rows(user):
    now = timezone.now()
    managed = set(properties_with_role(user, Role.MANAGER).values_list("id", flat=True))
    S = Booking.Status
    rows = []
    for prop in properties_with_role(user).order_by("name"):
        today = prop.local_today()                      # property-local date, not server date
        qs = Booking.objects.filter(property=prop)
        arrivals = qs.filter(status=S.CONFIRMED, check_in=today)
        due_out = qs.filter(status=S.CHECKED_IN, check_out__lte=today)
        rows.append({
            "property": prop, "today": today,
            "arrivals": arrivals.count(),
            "in_house": qs.filter(status=S.CHECKED_IN).count(),
            "due_out": due_out.count(),
            "holds": qs.filter(status=S.PENDING, expires_at__gt=now).count(),
            "pending_extensions": ExtensionRequest.objects.filter(
                booking__property=prop, status=ExtensionRequest.Status.REQUESTED).count(),
            "dirty_rooms": Room.objects.filter(
                property=prop, housekeeping_status=Room.HousekeepingStatus.DIRTY).count(),
            "refunds": (Payment.objects.filter(status=Payment.Status.REFUND_REQUIRED,
                                               group_ref__in=qs.values("group_ref")).count()
                        if prop.id in managed else None),     # managers only
            "arrival_list": list(arrivals.select_related("room").order_by("room__number")[:15]),
            "due_out_list": list(due_out.select_related("room").order_by("room__number")[:15]),
        })
    return rows
