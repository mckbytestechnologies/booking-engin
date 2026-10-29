from django.urls import path
from rest_framework.routers import SimpleRouter

from . import api, views
from . import api, catalog, views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="staff_dashboard"),
    path("login/", views.StaffLoginView.as_view(), name="staff_login"),
    path("bookings/", views.BookingListView.as_view(), name="staff_bookings"),
    path("bookings/new/", views.ManualBookingView.as_view(), name="staff_new_booking"),
    path("bookings/<str:reference>/", views.BookingDetailView.as_view(), name="staff_booking_detail"),
    path("bookings/<str:reference>/<str:action>/", views.BookingActionView.as_view(), name="staff_booking_action"),
    path("properties/", views.PropertyListView.as_view(), name="staff_properties"),
    path("properties/new/", views.PropertyCreateView.as_view(), name="staff_property_new"),
    path("properties/<int:pk>/", views.PropertyUpdateView.as_view(), name="staff_property_edit"),
    path("properties/<int:pk>/images/add/", views.PropertyImageAddView.as_view(), name="staff_property_image_add"),
    path("properties/<int:pk>/images/<int:image_id>/delete/", views.PropertyImageDeleteView.as_view(), name="staff_property_image_delete"),
    path("rooms/", views.RoomListView.as_view(), name="staff_rooms"),
    path("rooms/new/", views.RoomCreateView.as_view(), name="staff_room_new"),
    path("rooms/<int:pk>/", views.RoomUpdateView.as_view(), name="staff_room_edit"),
    path("rooms/<int:pk>/images/add/", views.RoomImageAddView.as_view(), name="staff_room_image_add"),
    path("rooms/<int:pk>/images/<int:image_id>/delete/", views.RoomImageDeleteView.as_view(), name="staff_room_image_delete"),
        # Catalogue
    path("catalogue/amenities/", catalog.AmenityList.as_view(), name="staff_amenities"),
    path("catalogue/amenities/new/", catalog.AmenityCreate.as_view(), name="staff_amenity_new"),
    path("catalogue/amenities/<int:pk>/", catalog.AmenityUpdate.as_view(), name="staff_amenity_edit"),
    path("catalogue/amenities/<int:pk>/delete/", catalog.AmenityDelete.as_view(), name="staff_amenity_delete"),
    path("catalogue/bed-types/", catalog.BedTypeList.as_view(), name="staff_bedtypes"),
    path("catalogue/bed-types/new/", catalog.BedTypeCreate.as_view(), name="staff_bedtype_new"),
    path("catalogue/bed-types/<int:pk>/", catalog.BedTypeUpdate.as_view(), name="staff_bedtype_edit"),
    path("catalogue/bed-types/<int:pk>/delete/", catalog.BedTypeDelete.as_view(), name="staff_bedtype_delete"),
    path("catalogue/room-types/", catalog.RoomTypeList.as_view(), name="staff_roomtypes"),
    path("catalogue/room-types/new/", catalog.RoomTypeCreate.as_view(), name="staff_roomtype_new"),
    path("catalogue/room-types/<int:pk>/", catalog.RoomTypeUpdate.as_view(), name="staff_roomtype_edit"),
    path("catalogue/room-types/<int:pk>/delete/", catalog.RoomTypeDelete.as_view(), name="staff_roomtype_delete"),
    # Staff team (superuser only)
    path("team/", catalog.TeamList.as_view(), name="staff_team"),
    path("team/new/", catalog.TeamCreate.as_view(), name="staff_team_new"),
    path("team/<int:pk>/", catalog.TeamUpdate.as_view(), name="staff_team_edit"),
    path("team/<int:pk>/delete/", catalog.TeamDelete.as_view(), name="staff_team_delete"),
    # Room blocks
    path("blocks/", catalog.BlockList.as_view(), name="staff_blocks"),
    path("blocks/new/", catalog.BlockCreate.as_view(), name="staff_block_new"),
    path("blocks/<int:pk>/delete/", catalog.BlockDelete.as_view(), name="staff_block_delete"),
]

router = SimpleRouter()
router.register("staff/bookings", api.StaffBookingViewSet, basename="staff-booking")

api_urlpatterns = [
    path("me/", api.MeView.as_view(), name="api_me"),
    path("staff/payments/refunds/", api.RefundQueueView.as_view(), name="staff_refunds"),
    path("staff/manual-bookings/", api.ManualBookingView.as_view(), name="staff_manual_booking"),
    path("staff/refund-tasks/", api.RefundTaskListView.as_view(), name="staff_refund_tasks"),
    path("staff/refund-tasks/<int:pk>/complete/", api.RefundTaskCompleteView.as_view(), name="staff_refund_complete"),
    path("staff/extensions/", api.ExtensionListView.as_view(), name="staff_extensions"),
    path("staff/extensions/<int:pk>/approve/", api.ExtensionApproveView.as_view(), name="staff_extension_approve"),
    path("staff/extensions/<int:pk>/reject/", api.ExtensionRejectView.as_view(), name="staff_extension_reject"),
    path("staff/rooms/<int:pk>/housekeeping/", api.HousekeepingView.as_view(), name="staff_housekeeping"),
] + router.urls