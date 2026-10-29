from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from bookings import urls as booking_urls
from properties import views as property_views
from rooms import views as room_views
from backoffice import urls as backoffice_urls

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include(booking_urls.api_urlpatterns)),   # availability/, quotes/, holds/
    path("api/v1/", include("config.api_urls")),              # properties/, rooms/
    path("book/", include(booking_urls.page_urlpatterns)),    # /book/, /book/success/
    path("", property_views.HomeView.as_view(), name="home"),
    path("properties/", property_views.PropertyListView.as_view(), name="property_list"),
    path("properties/<slug:slug>/", property_views.PropertyDetailView.as_view(), name="property_detail"),
    path("rooms/<int:pk>/", room_views.RoomDetailView.as_view(), name="room_detail"),
    path("api/v1/", include(backoffice_urls.api_urlpatterns)),
    path("account/", include("accounts.urls")),
    path("staff/", include("backoffice.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler500 = "config.views.server_error"