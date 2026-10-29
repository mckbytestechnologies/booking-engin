from properties.models import Property, StaffAssignment

Role = StaffAssignment.Role
RANK = {Role.RECEPTIONIST: 1, Role.MANAGER: 2}


def _active(user):
    return bool(user is not None and getattr(user, "is_authenticated", False) and user.is_active)


def _roles_at_least(min_role):
    return [r for r, rank in RANK.items() if rank >= RANK[min_role]]


def properties_with_role(user, min_role=Role.RECEPTIONIST):
    """Properties where the user holds at least min_role. Superusers get all of them."""
    if not _active(user):
        return Property.objects.none()
    if user.is_superuser:
        return Property.objects.all()
    return Property.objects.filter(
        staff_assignments__user=user,
        staff_assignments__role__in=_roles_at_least(min_role),
    ).distinct()


def is_staff_member(user, min_role=Role.RECEPTIONIST):
    if not _active(user):
        return False
    return user.is_superuser or properties_with_role(user, min_role).exists()


def has_role_at(user, property_id, min_role=Role.RECEPTIONIST):
    if not _active(user):
        return False
    if user.is_superuser:
        return True
    return StaffAssignment.objects.filter(
        user=user, property_id=property_id, role__in=_roles_at_least(min_role)
    ).exists()