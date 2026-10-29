from accounts.access import Role, has_role_at

from ..models import Booking, BookingHistory
from .errors import InvalidTransition, NotPermitted
from .history import record

S = Booking.Status

# (from, to) -> actor kinds allowed. "receptionist" means "at least receptionist at that
# property" (managers and superusers hold it too). Anything not listed is forbidden.
RULES = {
    (S.PENDING, S.CONFIRMED): {"system"},
    (S.PENDING, S.CANCELLED): {"owner", "receptionist"},
    (S.PENDING, S.EXPIRED): {"system"},
    (S.CONFIRMED, S.CHECKED_IN): {"receptionist"},
    (S.CONFIRMED, S.CANCELLED): {"owner", "receptionist"},
    (S.CONFIRMED, S.NO_SHOW): {"receptionist", "system"},
    (S.CHECKED_IN, S.CHECKED_OUT): {"receptionist"},
}


def actor_kinds(actor, booking):
    if actor is None:
        return {"system"}
    kinds = set()
    if booking.customer_id and booking.customer_id == actor.id:
        kinds.add("owner")
    if has_role_at(actor, booking.property_id, Role.RECEPTIONIST):
        kinds.add("receptionist")
    if has_role_at(actor, booking.property_id, Role.MANAGER):
        kinds.add("manager")
    return kinds


def apply_transition(booking, to_status, *, actor=None, reason="", details=None):
    """Caller must hold the row lock (inside transaction.atomic + select_for_update)."""
    kinds = actor_kinds(actor, booking)
    if not kinds:
        raise NotPermitted("You are not allowed to change this booking.")
    allowed = RULES.get((booking.status, to_status))
    if allowed is None:
        raise InvalidTransition(f"A {booking.get_status_display().lower()} booking cannot become {to_status.lower()}.")
    if not (kinds & allowed):
        raise NotPermitted("You are not allowed to do this.")

    previous = booking.status
    booking.status = to_status
    if to_status != S.PENDING:
        booking.expires_at = None
    booking.save(update_fields=["status", "expires_at", "updated_at"])
    record(booking, BookingHistory.Action.STATUS_CHANGE, from_status=previous, to_status=to_status,
           actor=actor, reason=reason, details=details)