from rest_framework import status as http
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from accounts.access import properties_with_role
from accounts.permissions import HasPropertyRole, IsPropertyManager, IsStaffMember
from bookings.api import error_response, m
from bookings.models import ExtensionRequest
from bookings.services import lifecycle, stay
from bookings.services.balance import outstanding
from bookings.services.booking import Selection
from bookings.services.errors import BookingError, UnknownBooking, UnknownProperty
from properties.models import StaffAssignment
from rooms.models import Room

from .selectors import refund_tasks_for, refunds_for, scoped_bookings
from .serializers import (CancelSerializer, CheckOutSerializer, DecisionSerializer, ExtendSerializer,
                          ExtensionSerializer, HistorySerializer, HousekeepingSerializer,
                          ManualBookingSerializer, MarkPaidSerializer, RefundSerializer,
                          RefundTaskSerializer, StaffBookingSerializer)


class MeView(APIView):                       # default permission: authenticated
    def get(self, request):
        u = request.user
        roles = StaffAssignment.objects.filter(user=u).select_related("property")
        return Response({
            "id": u.id, "email": u.email, "name": u.get_full_name(), "is_superuser": u.is_superuser,
            "roles": [{"property": a.property.slug, "role": a.role} for a in roles],
        })


class StaffBookingViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsStaffMember, HasPropertyRole]
    serializer_class = StaffBookingSerializer
    lookup_field = "reference"
    lookup_value_regex = "HB-[A-Z0-9]{8}"
    filterset_fields = {
        "status": ["exact"], "payment_status": ["exact"], "source": ["exact"],
        "property__slug": ["exact"], "check_in": ["gte", "lte"],
    }
    search_fields = ["reference", "customer_name", "customer_email", "customer_phone"]
    ordering_fields = ["check_in", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # Scoped here, so another property's booking is a 404 (existence is not revealed).
        return scoped_bookings(self.request.user).select_related("property", "room")

    @action(detail=True, methods=["post"])
    def cancel(self, request, reference=None):
        booking = self.get_object()          # scoped queryset + object permission
        s = CancelSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            outcome = lifecycle.cancel_booking(
                booking.pk, actor=request.user, reason=s.validated_data["reason"],
                waive_penalty=s.validated_data["waive_penalty"])
        except BookingError as exc:
            return error_response(exc)
        return Response({"reference": booking.reference, "status": "CANCELLED", "free": outcome.free,
                         "waived": outcome.waived, "penalty": m(outcome.penalty),
                         "refund_due": m(outcome.refund)})

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, reference=None):
        booking = self.get_object()
        s = MarkPaidSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            booking = lifecycle.record_payment(booking.pk, actor=request.user, **s.validated_data)
        except BookingError as exc:
            return error_response(exc)
        return Response({"reference": booking.reference, "payment_status": booking.payment_status})

    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, reference=None):
        booking = self.get_object()
        try:
            b = stay.check_in(booking.pk, actor=request.user)
        except BookingError as exc:
            return error_response(exc)
        return Response({"reference": b.reference, "status": b.status,
                         "actual_check_in": b.actual_check_in,
                         "housekeeping_warning": b.room.housekeeping_status != Room.HousekeepingStatus.CLEAN})

    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, reference=None):
        booking = self.get_object()
        s = CheckOutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            b = stay.check_out(booking.pk, actor=request.user, **s.validated_data)
        except BookingError as exc:
            return error_response(exc)
        return Response({"reference": b.reference, "status": b.status,
                         "actual_check_out": b.actual_check_out, "balance_due": m(outstanding(b))})

    @action(detail=True, methods=["post"], url_path="no-show")
    def no_show(self, request, reference=None):
        booking = self.get_object()
        try:
            outcome = stay.mark_no_show(booking.pk, actor=request.user)
        except BookingError as exc:
            return error_response(exc)
        return Response({"reference": booking.reference, "status": "NO_SHOW",
                         "penalty": m(outcome.penalty), "refund_due": m(outcome.refund)})

    @action(detail=True, methods=["post"])
    def extend(self, request, reference=None):
        booking = self.get_object()
        s = ExtendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            stay.extend_now(booking.pk, actor=request.user, new_check_out=s.validated_data["new_check_out"],
                            note=s.validated_data["note"])
        except BookingError as exc:
            return error_response(exc)
        booking.refresh_from_db()
        return Response({"reference": booking.reference, "check_out": booking.check_out,
                         "total": m(booking.total_amount), "balance_due": m(outstanding(booking))})

    @action(detail=True, methods=["get"])
    def history(self, request, reference=None):
        booking = self.get_object()
        return Response(HistorySerializer(booking.history.all(), many=True).data)


class RefundQueueView(ListAPIView):
    permission_classes = [IsPropertyManager]
    serializer_class = RefundSerializer

    def get_queryset(self):
        return refunds_for(self.request.user)


class ManualBookingView(APIView):
    permission_classes = [IsStaffMember]

    def post(self, request):
        s = ManualBookingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        prop = properties_with_role(request.user).filter(slug=d["property"]).first()
        if prop is None:                                   # unassigned property: existence not revealed
            return error_response(UnknownProperty("Unknown property."))
        try:
            result = lifecycle.create_manual_booking(
                actor=request.user, property=prop, source=d["source"],
                selections=[Selection(key=i["key"], quantity=i["quantity"], guests=i.get("guests"))
                            for i in d["items"]],
                check_in=d["check_in"], check_out=d["check_out"],
                guest={k: d.get(k, "") for k in ("first_name", "last_name", "email", "phone",
                                                 "special_request", "internal_notes")},
            )
        except BookingError as exc:
            return error_response(exc)
        return Response({
            "group_ref": result["group_ref"], "total": m(result["total"]),
            "bookings": [{"reference": b.reference, "room": b.room.number, "total": m(b.total_amount)}
                         for b in result["bookings"]],
        }, status=http.HTTP_201_CREATED)


class RefundTaskListView(ListAPIView):
    permission_classes = [IsPropertyManager]
    serializer_class = RefundTaskSerializer

    def get_queryset(self):
        return refund_tasks_for(self.request.user)


class RefundTaskCompleteView(APIView):
    permission_classes = [IsPropertyManager]

    def post(self, request, pk):
        task = refund_tasks_for(request.user).filter(pk=pk).first()
        if task is None:
            return error_response(UnknownBooking("Unknown refund task."))
        try:
            lifecycle.complete_refund(task.pk, actor=request.user)
        except BookingError as exc:
            return error_response(exc)
        return Response({"id": task.pk, "status": "DONE"})


class ExtensionListView(ListAPIView):
    permission_classes = [IsStaffMember]
    serializer_class = ExtensionSerializer
    filterset_fields = ["status"]

    def get_queryset(self):
        return ExtensionRequest.objects.filter(
            booking__property__in=properties_with_role(self.request.user)).select_related("booking")


class _ExtensionDecisionView(APIView):
    permission_classes = [IsStaffMember]

    def decide(self, pk, actor, note):
        raise NotImplementedError

    def post(self, request, pk):
        ext = ExtensionRequest.objects.filter(
            pk=pk, booking__property__in=properties_with_role(request.user)).select_related("booking").first()
        if ext is None:                                   # another property's request: 404
            return error_response(UnknownBooking("Unknown extension request."))
        s = DecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            ext = self.decide(ext.pk, request.user, s.validated_data["note"])
        except BookingError as exc:
            return error_response(exc)
        return Response({"id": ext.pk, "booking": ext.booking.reference, "status": ext.status})


class ExtensionApproveView(_ExtensionDecisionView):
    def decide(self, pk, actor, note):
        return stay.approve_extension(pk, actor=actor, note=note)


class ExtensionRejectView(_ExtensionDecisionView):
    def decide(self, pk, actor, note):
        return stay.reject_extension(pk, actor=actor, note=note)


class HousekeepingView(APIView):
    permission_classes = [IsStaffMember]

    def post(self, request, pk):
        room = Room.objects.filter(pk=pk, property__in=properties_with_role(request.user)).first()
        if room is None:
            return error_response(UnknownBooking("Unknown room."))
        s = HousekeepingSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        Room.objects.filter(pk=room.pk).update(housekeeping_status=s.validated_data["status"])
        return Response({"room": room.number, "housekeeping_status": s.validated_data["status"]})