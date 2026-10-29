from ..models import BookingHistory


def record(booking, action, *, from_status="", to_status="", actor=None, actor_label=None,
           reason="", details=None):
    label = actor_label or ((actor.email or actor.username) if actor else "system")
    return BookingHistory.objects.create(
        booking=booking, action=action, from_status=from_status, to_status=to_status,
        actor=actor, actor_label=label, reason=(reason or "")[:255], details=details or {},
    )