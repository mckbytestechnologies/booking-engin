from rest_framework.permissions import BasePermission

from .access import Role, has_role_at, is_staff_member


class IsStaffMember(BasePermission):
    """Holds at least min_role at any property (or is a superuser)."""
    message = "Staff access required."
    min_role = Role.RECEPTIONIST

    def has_permission(self, request, view):
        return is_staff_member(request.user, self.min_role)


class IsPropertyManager(IsStaffMember):
    message = "Manager access required."
    min_role = Role.MANAGER


class HasPropertyRole(BasePermission):
    """Object-level: the object's property must be one the user may act on."""
    min_role = Role.RECEPTIONIST

    def has_object_permission(self, request, view, obj):
        return has_role_at(request.user, obj.property_id, self.min_role)