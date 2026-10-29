import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, FormView, ListView, UpdateView

from accounts.access import Role, is_staff_member
from bookings.models import Booking, RoomBlock
from properties.models import Amenity, StaffAssignment
from rooms.models import BedType, Room, RoomType

from .catalog_forms import (AmenityForm, BedTypeForm, RoomBlockForm, RoomTypeForm,
                            StaffForm, StaffRoleForm)
from .views import AuditMixin, ManagerRequiredMixin, managed_rooms

audit = logging.getLogger("app.audit")


class SuperuserRequiredMixin(LoginRequiredMixin):
    login_url = "staff_login"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


# ================================================================== generic list
class RowsListView(ListView):
    """One table template for every list. Subclasses say what a row contains."""
    template_name = "backoffice/catalog_list.html"
    title = ""
    headers = ()
    new_name = ""
    new_label = ""
    edit_name = ""
    delete_name = ""
    empty = "Nothing here yet."
    hint = ""

    def row(self, obj):
        raise NotImplementedError

    def can_delete(self, user):
        return user.is_superuser

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        deletable = self.can_delete(self.request.user)
        ctx["rows"] = [{
            "cells": self.row(o),
            "edit": reverse(self.edit_name, args=[o.pk]) if self.edit_name else "",
            "delete": reverse(self.delete_name, args=[o.pk]) if self.delete_name and deletable else "",
        } for o in ctx["object_list"]]
        ctx.update(title=self.title, headers=self.headers, new_url=reverse(self.new_name),
                   new_label=self.new_label, empty=self.empty, hint=self.hint)
        return ctx


# ================================================================== generic delete
class _DeleteView(LoginRequiredMixin, View):
    """POST only. Protected rows (still used by a room, for example) are refused politely."""
    login_url = "staff_login"
    model = None
    back = ""

    def allowed(self, user):
        return user.is_superuser

    def queryset(self, request):
        return self.model.objects.all()

    def post(self, request, pk):
        if not self.allowed(request.user):
            raise PermissionDenied
        obj = get_object_or_404(self.queryset(request), pk=pk)
        name = str(obj)
        try:
            with transaction.atomic():
                obj.delete()
        except ProtectedError:
            messages.error(request, f"'{name}' is still in use, so it cannot be deleted. "
                                    f"Remove it from rooms or bookings first.")
        else:
            audit.info("%s pk=%s deleted by user=%s", self.model.__name__, pk, request.user.pk)
            messages.success(request, f"'{name}' deleted.")
        return redirect(self.back)


# ================================================================== generic add / edit
class CatalogFormMixin(AuditMixin, ManagerRequiredMixin):
    template_name = "backoffice/form.html"
    back_name = ""
    label = ""
    action = ""

    def get_success_url(self):
        return reverse(self.back_name)

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "title": f"{self.action} {self.label}",
                "back_url": reverse(self.back_name)}


# ---------------------------------------------------------------- amenities
class AmenityList(ManagerRequiredMixin, RowsListView):
    title, new_name, new_label = "Amenities", "staff_amenity_new", "New amenity"
    edit_name, delete_name = "staff_amenity_edit", "staff_amenity_delete"
    headers = ("Name", "Applies to", "Visible", "Used by")
    hint = "Amenities are the Wi-Fi, parking, kitchen and similar tags shown on properties and rooms."

    def get_queryset(self):
        return Amenity.objects.annotate(n_prop=Count("properties", distinct=True),
                                        n_room=Count("rooms", distinct=True)).order_by("name")

    def row(self, o):
        return [o.name, o.get_scope_display(), "Yes" if o.is_active else "Hidden",
                f"{o.n_prop} properties, {o.n_room} rooms"]


class AmenityCreate(CatalogFormMixin, CreateView):
    model, form_class, back_name, label, action = Amenity, AmenityForm, "staff_amenities", "amenity", "New"


class AmenityUpdate(CatalogFormMixin, UpdateView):
    model, form_class, back_name, label, action = Amenity, AmenityForm, "staff_amenities", "amenity", "Edit"


class AmenityDelete(_DeleteView):
    model, back = Amenity, "staff_amenities"


# ---------------------------------------------------------------- bed types
class BedTypeList(ManagerRequiredMixin, RowsListView):
    title, new_name, new_label = "Bed types", "staff_bedtype_new", "New bed type"
    edit_name, delete_name = "staff_bedtype_edit", "staff_bedtype_delete"
    headers = ("Name", "Rooms using it")

    def get_queryset(self):
        return BedType.objects.annotate(n=Count("rooms")).order_by("name")

    def row(self, o):
        return [o.name, o.n]


class BedTypeCreate(CatalogFormMixin, CreateView):
    model, form_class, back_name, label, action = BedType, BedTypeForm, "staff_bedtypes", "bed type", "New"


class BedTypeUpdate(CatalogFormMixin, UpdateView):
    model, form_class, back_name, label, action = BedType, BedTypeForm, "staff_bedtypes", "bed type", "Edit"


class BedTypeDelete(_DeleteView):
    model, back = BedType, "staff_bedtypes"


# ---------------------------------------------------------------- room types
class RoomTypeList(ManagerRequiredMixin, RowsListView):
    title, new_name, new_label = "Room types", "staff_roomtype_new", "New room type"
    edit_name, delete_name = "staff_roomtype_edit", "staff_roomtype_delete"
    headers = ("Name", "Description", "Rooms")

    def get_queryset(self):
        return RoomType.objects.annotate(n=Count("rooms")).order_by("name")

    def row(self, o):
        text = o.description.strip()
        return [o.name, (text[:70] + "...") if len(text) > 70 else text or "-", o.n]


class RoomTypeCreate(CatalogFormMixin, CreateView):
    model, form_class, back_name, label, action = RoomType, RoomTypeForm, "staff_roomtypes", "room type", "New"


class RoomTypeUpdate(CatalogFormMixin, UpdateView):
    model, form_class, back_name, label, action = RoomType, RoomTypeForm, "staff_roomtypes", "room type", "Edit"


class RoomTypeDelete(_DeleteView):
    model, back = RoomType, "staff_roomtypes"


# ================================================================== staff team (superuser only)
class TeamList(SuperuserRequiredMixin, RowsListView):
    title, new_name, new_label = "Staff team", "staff_team_new", "Add staff member"
    edit_name, delete_name = "staff_team_edit", "staff_team_delete"
    headers = ("Name", "Email", "Property", "Role")
    empty = "No staff have been assigned yet."
    hint = "A role is per property. Removing a role removes that person's access to the property."

    def get_queryset(self):
        return StaffAssignment.objects.select_related("user", "property").order_by("property__name", "user__email")

    def row(self, o):
        return [o.user.get_full_name() or o.user.username, o.user.email, o.property.name, o.get_role_display()]


class TeamCreate(SuperuserRequiredMixin, FormView):
    template_name = "backoffice/form.html"
    form_class = StaffForm

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "title": "Add staff member",
                "back_url": reverse("staff_team"),
                "note": "A new email creates the account with the password you set. An existing "
                        "email just gains this role. Staff do not get access to the Django admin."}

    def form_valid(self, form):
        a = form.save()
        audit.info("StaffAssignment pk=%s created by user=%s role=%s", a.pk, self.request.user.pk, a.role)
        messages.success(self.request, f"{a.user.email} is now {a.get_role_display()} at {a.property.name}.")
        return redirect("staff_team")


class TeamUpdate(AuditMixin, SuperuserRequiredMixin, UpdateView):
    template_name = "backoffice/form.html"
    model = StaffAssignment
    form_class = StaffRoleForm

    def get_success_url(self):
        return reverse("staff_team")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "back_url": reverse("staff_team"),
                "title": f"Change role: {self.object.user.email} at {self.object.property.name}"}


class TeamDelete(_DeleteView):
    model, back = StaffAssignment, "staff_team"


# ================================================================== room blocks (managers)
class BlockList(ManagerRequiredMixin, RowsListView):
    title, new_name, new_label = "Room blocks", "staff_block_new", "Block a room"
    delete_name = "staff_block_delete"
    headers = ("Room", "From", "Until (free again)", "Reason")
    empty = "No rooms are blocked."
    hint = "A blocked room cannot be booked for those dates. Use it for repairs or owner use."

    def can_delete(self, user):
        return is_staff_member(user, Role.MANAGER)

    def get_queryset(self):
        return (RoomBlock.objects.filter(room__in=managed_rooms(self.request.user))
                .select_related("room", "room__property").order_by("-start_date"))

    def row(self, o):
        return [str(o.room), o.start_date.strftime("%d %b %Y"), o.end_date.strftime("%d %b %Y"), o.reason]


class BlockCreate(AuditMixin, ManagerRequiredMixin, CreateView):
    template_name = "backoffice/form.html"
    form_class = RoomBlockForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "rooms": managed_rooms(self.request.user)}

    def get_success_url(self):
        return reverse("staff_blocks")

    def get_context_data(self, **kwargs):
        return {**super().get_context_data(**kwargs), "title": "Block a room", "back_url": reverse("staff_blocks"),
                "note": "Blocking is refused if the room already has a booking in those dates. "
                        "Cancel or move those bookings first."}

    def form_valid(self, form):
        room, start, end = (form.cleaned_data[k] for k in ("room", "start_date", "end_date"))
        with transaction.atomic():
            Room.objects.select_for_update().get(pk=room.pk)       # same lock the booking flow takes
            clashes = list(Booking.objects.filter(room_id=room.pk).overlapping(start, end)
                           .blocking().values_list("reference", flat=True)[:3])
            if clashes:
                form.add_error(None, "This room already has bookings in those dates: "
                                     + ", ".join(clashes) + ".")
                return self.form_invalid(form)
            form.instance.created_by = self.request.user
            return super().form_valid(form)


class BlockDelete(_DeleteView):
    model, back = RoomBlock, "staff_blocks"

    def allowed(self, user):
        return is_staff_member(user, Role.MANAGER)

    def queryset(self, request):
        return RoomBlock.objects.filter(room__in=managed_rooms(request.user))