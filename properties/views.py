from django.db.models import Prefetch
from django.views.generic import DetailView, ListView, TemplateView

from rooms.models import Room

from .models import Property


def active_properties():
    return Property.objects.filter(is_active=True).prefetch_related("amenities", "images")


class HomeView(TemplateView):
    template_name = "home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["featured"] = active_properties()[:6]
        return ctx


class PropertyListView(ListView):
    template_name = "properties/property_list.html"
    context_object_name = "properties"
    paginate_by = 9

    def get_queryset(self):
        qs = active_properties()
        city = self.request.GET.get("city", "").strip()
        if city:
            qs = qs.filter(city__iexact=city)
        return qs


class PropertyDetailView(DetailView):
    template_name = "properties/property_detail.html"
    context_object_name = "property"

    def get_queryset(self):
        rooms = Room.objects.filter(operational_status=Room.OperationalStatus.ACTIVE) \
            .select_related("room_type", "bed_type").order_by("number")
        return active_properties().prefetch_related(Prefetch("rooms", queryset=rooms, to_attr="active_rooms"))