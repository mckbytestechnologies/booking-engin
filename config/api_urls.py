from django.urls import include, path
from rest_framework.routers import DefaultRouter

from properties.api_views import PropertyViewSet
from rooms.api_views import RoomViewSet

router = DefaultRouter()
router.register("properties", PropertyViewSet, basename="property")
router.register("rooms", RoomViewSet, basename="room")

urlpatterns = [
    path("", include(router.urls)),
]