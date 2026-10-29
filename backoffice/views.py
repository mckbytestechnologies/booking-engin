# from django.contrib.auth.mixins import LoginRequiredMixin
# from django.core.exceptions import PermissionDenied
# from django.views.generic import TemplateView

# from accounts.access import is_staff_member

# from .selectors import dashboard_rows


# class StaffRequiredMixin(LoginRequiredMixin):
#     """Anonymous -> login page. Logged in but not staff -> 403. Enforced on the server."""

#     def dispatch(self, request, *args, **kwargs):
#         if request.user.is_authenticated and not is_staff_member(request.user):
#             raise PermissionDenied
#         return super().dispatch(request, *args, **kwargs)


# class DashboardView(StaffRequiredMixin, TemplateView):
#     template_name = "backoffice/dashboard.html"

#     def get_context_data(self, **kwargs):
#         ctx = super().get_context_data(**kwargs)
#         ctx["rows"] = dashboard_rows(self.request.user)
#         return ctx

import logging
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from accounts.access import Role, is_staff_member, properties_with_role
from accounts.views import ThrottledLoginView
from bookings.models import Booking
from bookings.services import lifecycle, stay
from bookings.services.availability import availability_groups
from bookings.services.balance import outstanding
from bookings.services.booking import Selection
from bookings.services.errors import BookingError, InvalidDates, InvalidSelection
from bookings.services.transitions import actor_kinds
from properties.models import Property, PropertyImage
from rooms.models import Room, RoomImage

from .forms import (BookingFilterForm, ManualGuestForm, ManualSearchForm, PropertyForm,
                    PropertyImageForm, RoomForm, RoomImageForm)
from .selectors import dashboard_rows, scoped_bookings

audit = logging.getLogger("app.audit")

class StaffRequiredMixin(LoginRequiredMixin):
    """Anonymous -> staff login. Logged in but not staff -> 403. Enforced on the server."""
    login_url = "staff_login"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not is_staff_member(request.user):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class StaffLoginView(ThrottledLoginView):
    """Same lockout and generic errors as the guest login, but only staff may sign in here."""
    template_name = "backoffice/login.html"
    redirect_authenticated_user = False

    def get_default_redirect_url(self):
        return reverse("staff_dashboard")

    def form_valid(self, form):
        if not is_staff_member(form.get_user()):
            form.add_error(None, "This account does not have staff access.")
            return self.form_invalid(form)
        return super().form_valid(form)


class DashboardView(StaffRequiredMixin, TemplateView):
    template_name = "backoffice/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["rows"] = dashboard_rows(self.request.user)
        return ctx


class BookingListView(StaffRequiredMixin, ListView):
    template_name = "backoffice/booking_list.html"
    context_object_name = "bookings"
    paginate_by = 25

    def get_queryset(self):
        qs = scoped_bookings(self.request.user).select_related("property", "room")
        self.form = BookingFilterForm(self.request.GET or None,
                                      properties=properties_with_role(self.request.user))
        if self.form.is_bound and self.form.is_valid():
            d = self.form.cleaned_data
            if d["q"]:
                q = d["q"].strip()
                qs = qs.filter(Q(reference__icontains=q) | Q(customer_name__icontains=q)
                               | Q(customer_email__icontains=q) | Q(customer_phone__icontains=q))
            if d["status"]:
                qs = qs.filter(status=d["status"])
            if d["property"]:
                qs = qs.filter(property__slug=d["property"])
            if d["date_from"]:
                qs = qs.filter(check_in__gte=d["date_from"])
            if d["date_to"]:
                qs = qs.filter(check_in__lte=d["date_to"])
        return qs.order_by("-created_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop("page", None)
        ctx["form"] = self.form
        ctx["querystring"] = urlencode(params)
        return ctx


def allowed_actions(user, booking):
    """Which buttons to show. A convenience only: every service re-checks role and state."""
    S, P = Booking.Status, Booking.PaymentStatus
    kinds = actor_kinds(user, booking)
    desk = "receptionist" in kinds
    today = booking.property.local_today()
    pay_ok = booking.payment_status != P.PAID and not (
        booking.payment_status == P.UNPAID and booking.source == Booking.Source.ONLINE)
    return {
        "check_in": desk and booking.status == S.CONFIRMED and booking.check_in <= today < booking.check_out,
        "check_out": desk and booking.status == S.CHECKED_IN,
        "cancel": desk and booking.status in (S.PENDING, S.CONFIRMED),
        "mark_paid": desk and booking.status in (S.CONFIRMED, S.CHECKED_IN) and pay_ok,
        "no_show": desk and booking.status == S.CONFIRMED and today > booking.check_in,
        "extend": desk and booking.status in (S.CONFIRMED, S.CHECKED_IN),
        "manager": "manager" in kinds,
    }


class BookingDetailView(StaffRequiredMixin, View):
    template_name = "backoffice/booking_detail.html"

    def get(self, request, reference):
        booking = get_object_or_404(scoped_bookings(request.user).select_related("property", "room"),
                                    reference=reference)         # another property's booking: 404
        return render(request, self.template_name, {
            "b": booking, "history": booking.history.all(), "balance": outstanding(booking),
            "actions": allowed_actions(request.user, booking),
        })


# ---- action handlers: each returns a success message or raises a BookingError ----
def _on(request, name):
    return request.POST.get(name) == "on"


def _check_in(request, b):
    stay.check_in(b.pk, actor=request.user)
    return "Guest checked in."


def _check_out(request, b):
    stay.check_out(b.pk, actor=request.user, override_unpaid=_on(request, "override_unpaid"),
                   release_unused_nights=_on(request, "release_unused_nights"),
                   reason=request.POST.get("reason", ""))
    return "Guest checked out. The room is now marked dirty."


def _cancel(request, b):
    o = lifecycle.cancel_booking(b.pk, actor=request.user, reason=request.POST.get("reason", ""),
                                 waive_penalty=_on(request, "waive_penalty"))
    return f"Booking cancelled. Fee ₹{o.penalty}; refund due ₹{o.refund}."


def _mark_paid(request, b):
    method = request.POST.get("method", "")
    if method not in ("CASH", "CARD", "UPI"):
        raise InvalidSelection("Choose a payment method.")
    lifecycle.record_payment(b.pk, actor=request.user, method=method, note=request.POST.get("note", ""))
    return "Payment recorded."


def _no_show(request, b):
    o = stay.mark_no_show(b.pk, actor=request.user)
    return f"Marked as no-show. Fee ₹{o.penalty}; refund due ₹{o.refund}."


def _extend(request, b):
    try:
        new_out = forms.DateField(input_formats=["%Y-%m-%d"]).clean(request.POST.get("new_check_out", ""))
    except ValidationError:
        raise InvalidDates("Enter a valid new check-out date.")
    stay.extend_now(b.pk, actor=request.user, new_check_out=new_out)
    b.refresh_from_db()
    return f"Stay extended to {b.check_out:%d %b %Y}. Balance due ₹{outstanding(b)}."


ACTIONS = {"check-in": _check_in, "check-out": _check_out, "cancel": _cancel,
           "mark-paid": _mark_paid, "no-show": _no_show, "extend": _extend}


class BookingActionView(StaffRequiredMixin, View):
    """POST only (a GET returns 405). The services enforce role, state and locking."""

    def post(self, request, reference, action):
        handler = ACTIONS.get(action)
        booking = get_object_or_404(scoped_bookings(request.user), reference=reference)
        if handler is None:
            raise PermissionDenied
        try:
            text = handler(request, booking)
        except BookingError as exc:
            messages.error(request, exc.message)
        else:
            messages.success(request, text)
        return redirect("staff_booking_detail", reference=reference)

# ================================================================== manual booking
def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ManualBookingView(StaffRequiredMixin, View):
    """Step 1 (GET): pick property and dates, see what is free. Step 2 (POST): rooms + guest.
    The booking itself goes through the same locked, priced creation path as online bookings."""
    template_name = "backoffice/manual_booking.html"

    def _search(self, request, data):
        props = list(properties_with_role(request.user).order_by("name"))
        return ManualSearchForm(data, properties=props), {p.slug: p for p in props}

    @staticmethod
    def _selections(post):
        out = []
        for name, value in post.items():
            if name.startswith("qty__") and _int(value) > 0:
                key = name[5:]
                out.append(Selection(key=key, quantity=min(_int(value), 10),
                                     guests=_int(post.get("guests__" + key)) or None))
        return out

    def _groups(self, d, post=None):
        groups = availability_groups(d["check_in"], d["check_out"], d["property"])
        for g in groups:
            for item in g["items"]:
                item["qty"] = _int(post.get("qty__" + item["key"])) if post else 0
        return groups

    def get(self, request):
        data = request.GET if "check_in" in request.GET else None
        search, _ = self._search(request, data)
        groups = self._groups(search.cleaned_data) if search.is_bound and search.is_valid() else None
        return render(request, self.template_name,
                      {"search": search, "guest": ManualGuestForm(), "groups": groups})

    def post(self, request):
        search, props = self._search(request, request.POST)
        guest = ManualGuestForm(request.POST)
        groups = None
        if search.is_valid():
            d = search.cleaned_data
            groups = self._groups(d, request.POST)
            selections = self._selections(request.POST)
            if not selections:
                messages.error(request, "Choose at least one room.")
            elif guest.is_valid():
                info = dict(guest.cleaned_data)
                source = info.pop("source")
                try:
                    result = lifecycle.create_manual_booking(
                        actor=request.user, property=props[d["property"]], selections=selections,
                        check_in=d["check_in"], check_out=d["check_out"], guest=info, source=source)
                except BookingError as exc:
                    messages.error(request, exc.message)
                else:
                    messages.success(request, f"Booked {len(result['bookings'])} room(s), total "
                                              f"₹{result['total']}. Record the payment when the guest pays.")
                    return redirect("staff_booking_detail", reference=result["bookings"][0].reference)
        return render(request, self.template_name, {"search": search, "guest": guest, "groups": groups})


# ================================================================== properties and rooms (managers)
class ManagerRequiredMixin(LoginRequiredMixin):
    login_url = "staff_login"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not is_staff_member(request.user, Role.MANAGER):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def managed_properties(user):
    return properties_with_role(user, Role.MANAGER)


def managed_rooms(user):
    return Room.objects.filter(property__in=managed_properties(user))


class AuditMixin:
    """Logs who changed what (field names only, never values) and confirms to the user."""

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.info("%s pk=%s saved by user=%s changed=%s", self.object.__class__.__name__,
                   self.object.pk, self.request.user.pk, ",".join(form.changed_data) or "-")
        messages.success(self.request, "Saved.")
        return response


class PropertyListView(ManagerRequiredMixin, ListView):
    template_name = "backoffice/property_list.html"
    context_object_name = "properties"

    def get_queryset(self):
        return managed_properties(self.request.user).order_by("name")


class PropertyCreateView(AuditMixin, ManagerRequiredMixin, CreateView):
    template_name = "backoffice/form.html"
    form_class = PropertyForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_superuser:
            raise PermissionDenied                       # only a superuser opens a new property
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_context_data(self, **kw):
        return {**super().get_context_data(**kw), "title": "New property", "back_url": reverse("staff_properties")}

    def get_success_url(self):
        return reverse("staff_property_edit", args=[self.object.pk])


class PropertyUpdateView(AuditMixin, ManagerRequiredMixin, UpdateView):
    template_name = "backoffice/form.html"
    form_class = PropertyForm

    def get_queryset(self):
        return managed_properties(self.request.user)     # another property: 404

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "user": self.request.user}

    def get_success_url(self):
        return reverse("staff_properties")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(title=f"Edit {self.object.name}", back_url=reverse("staff_properties"),
                   images=self.object.images.all(), image_form=PropertyImageForm(),
                   image_add_url=reverse("staff_property_image_add", args=[self.object.pk]),
                   image_delete_name="staff_property_image_delete", owner_pk=self.object.pk,
                   note="Changing check-in/out times, time zone or the cancellation window also "
                        "changes the deadlines shown for existing bookings.")
        return ctx


class RoomListView(ManagerRequiredMixin, ListView):
    template_name = "backoffice/room_list.html"
    context_object_name = "rooms"

    def get_queryset(self):
        qs = managed_rooms(self.request.user).select_related("property", "room_type", "bed_type")
        slug = self.request.GET.get("property")
        if slug:
            qs = qs.filter(property__slug=slug)
        return qs.order_by("property__name", "number")

    def get_context_data(self, **kw):
        return {**super().get_context_data(**kw), "properties": managed_properties(self.request.user)}


class RoomCreateView(AuditMixin, ManagerRequiredMixin, CreateView):
    template_name = "backoffice/form.html"
    form_class = RoomForm

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "properties": managed_properties(self.request.user)}

    def get_initial(self):
        prop = managed_properties(self.request.user).filter(slug=self.request.GET.get("property", "")).first()
        return {"property": prop.pk} if prop else {}

    def get_context_data(self, **kw):
        return {**super().get_context_data(**kw), "title": "New room", "back_url": reverse("staff_rooms")}

    def get_success_url(self):
        return reverse("staff_room_edit", args=[self.object.pk])      # next: add photos


class RoomUpdateView(AuditMixin, ManagerRequiredMixin, UpdateView):
    template_name = "backoffice/form.html"
    form_class = RoomForm

    def get_queryset(self):
        return managed_rooms(self.request.user)

    def get_form_kwargs(self):
        return {**super().get_form_kwargs(), "properties": managed_properties(self.request.user)}

    def get_success_url(self):
        return reverse("staff_rooms")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(title=f"Edit room {self.object.number} · {self.object.property.name}",
                   back_url=reverse("staff_rooms"), images=self.object.images.all(),
                   image_form=RoomImageForm(),
                   image_add_url=reverse("staff_room_image_add", args=[self.object.pk]),
                   image_delete_name="staff_room_image_delete", owner_pk=self.object.pk,
                   note="A new price applies to new bookings only. Existing bookings keep the price "
                        "they were made at.")
        return ctx


# ---- images
class _ImageAddView(ManagerRequiredMixin, View):
    form_class = None
    fk = ""
    back = ""

    def owner(self, request, pk):
        raise NotImplementedError

    def post(self, request, pk):
        owner = self.owner(request, pk)
        form = self.form_class(request.POST, request.FILES)
        if form.is_valid():
            img = form.save(commit=False)
            setattr(img, self.fk, owner)
            img.save()
            messages.success(request, "Photo added.")
        else:
            messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect(self.back, pk=owner.pk)


class _ImageDeleteView(ManagerRequiredMixin, View):
    image_model = None
    fk = ""
    back = ""

    def owner(self, request, pk):
        raise NotImplementedError

    def post(self, request, pk, image_id):
        owner = self.owner(request, pk)
        img = get_object_or_404(self.image_model, pk=image_id, **{self.fk: owner})
        img.image.delete(save=False)                     # remove the file too
        img.delete()
        messages.success(request, "Photo removed.")
        return redirect(self.back, pk=owner.pk)


class PropertyImageAddView(_ImageAddView):
    form_class, fk, back = PropertyImageForm, "property", "staff_property_edit"

    def owner(self, request, pk):
        return get_object_or_404(managed_properties(request.user), pk=pk)


class PropertyImageDeleteView(_ImageDeleteView):
    image_model, fk, back = PropertyImage, "property", "staff_property_edit"

    def owner(self, request, pk):
        return get_object_or_404(managed_properties(request.user), pk=pk)


class RoomImageAddView(_ImageAddView):
    form_class, fk, back = RoomImageForm, "room", "staff_room_edit"

    def owner(self, request, pk):
        return get_object_or_404(managed_rooms(request.user), pk=pk)


class RoomImageDeleteView(_ImageDeleteView):
    image_model, fk, back = RoomImage, "room", "staff_room_edit"

    def owner(self, request, pk):
        return get_object_or_404(managed_rooms(request.user), pk=pk)