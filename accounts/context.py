from django.utils.functional import SimpleLazyObject

from .access import Role, is_staff_member


def staff_flag(request):
    user = getattr(request, "user", None)
    return {
        "is_staff_member": SimpleLazyObject(lambda: is_staff_member(user)),
        "is_manager": SimpleLazyObject(lambda: is_staff_member(user, Role.MANAGER)),
    }