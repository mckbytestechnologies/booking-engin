from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from .forms import SearchForm
from .models import Booking
from .services.availability import availability_groups


def build_room_data(groups):
    """Everything the detail modal shows, from the database. Nothing hard-coded."""
    data = {}
    for g in groups:
        p = g["property"]
        for item in g["items"]:
            data[item["key"]] = {
                "title": item["room_type"], "property": p.name,
                "address": f"{p.address_line}, {p.city}, {p.state}",
                "images": item["image_urls"], "description": item["description"],
                "amenities": item["amenity_names"],
                "bed": f"{item['bed_type']} - {item['bed_count']}",
                "cancellation": f"Free cancellation up to {p.free_cancellation_hours} hours before check-in.",
                "times": f"Check-in {p.check_in_time:%I:%M %p} | Check-out {p.check_out_time:%I:%M %p}",
            }
    return data


class EngineView(View):
    template_name = "bookings/engine.html"

    def get(self, request):
        today = timezone.localdate()
        form = SearchForm(request.GET or None)
        errors = []
        if request.GET and form.is_valid():
            check_in, check_out = form.cleaned_data["check_in"], form.cleaned_data["check_out"]
            slug = form.cleaned_data.get("property") or None
        else:
            if request.GET:
                errors = [e for errs in form.errors.values() for e in errs]
            check_in, check_out, slug = today, today + timedelta(days=1), None

        groups = availability_groups(check_in, check_out, slug)
        return render(request, self.template_name, {
            "groups": groups, "room_data": build_room_data(groups),
            "check_in": check_in, "check_out": check_out, "today": today,
            "site_name": settings.SITE_NAME, "form_errors": errors,
            "otp_enabled": settings.BOOKING_REQUIRE_EMAIL_VERIFICATION,
            "site": settings.SITE_CONTACT,
        })


class SuccessView(View):
    template_name = "bookings/success.html"

    def get(self, request):
        ref = request.GET.get("ref", "")
        if ref not in request.session.get("booking_groups", []):
            raise Http404                      # not this visitor's booking
        bookings = list(Booking.objects.filter(group_ref=ref).select_related("property", "room"))
        if not bookings:
            raise Http404

        statuses = {b.status for b in bookings}
        if statuses == {Booking.Status.CONFIRMED}:
            state = "confirmed"
        elif Booking.Status.PENDING in statuses:
            state = "pending"
        else:
            state = "failed"
        return render(request, self.template_name,
                      {"bookings": bookings, "group_ref": ref, "state": state})