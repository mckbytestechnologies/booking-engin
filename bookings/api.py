# import json
# import logging

# from django.conf import settings
# from rest_framework import status
# from rest_framework.permissions import AllowAny
# from rest_framework.response import Response
# from rest_framework.throttling import ScopedRateThrottle
# from rest_framework.views import APIView

# from .models import Payment
# from .serializers import (
#     AvailabilityQuerySerializer,
#     HoldRequestSerializer,
#     OtpSendSerializer,
#     OtpVerifySerializer,
#     PaymentOrderSerializer,
#     PaymentVerifySerializer,
#     QuoteRequestSerializer,
# )
# from .services import payments
# from .services.availability import availability_groups
# from .services.booking import Selection, create_hold, quote_selections
# from .services.errors import BookingError, PaymentConflict, UnknownGroup
# from .services.otp import normalize_email, send_otp, verify_otp

# from rest_framework import status as http
# from rest_framework.decorators import action
# from rest_framework.generics import ListAPIView
# from rest_framework.response import Response
# from rest_framework.views import APIView
# from rest_framework.viewsets import ReadOnlyModelViewSet

# from accounts.access import properties_with_role
# from accounts.permissions import HasPropertyRole, IsPropertyManager, IsStaffMember
# from bookings.api import error_response, m
# from bookings.models import ExtensionRequest
# from bookings.services import lifecycle, stay
# from bookings.services.balance import outstanding
# from bookings.services.booking import Selection
# from bookings.services.errors import BookingError, UnknownBooking, UnknownProperty
# from properties.models import StaffAssignment
# from rooms.models import Room

# from .selectors import refund_tasks_for, refunds_for, scoped_bookings
# from .serializers import (CancelSerializer, CheckOutSerializer, DecisionSerializer, ExtendSerializer,
#                           ExtensionSerializer, HistorySerializer, HousekeepingSerializer,
#                           ManualBookingSerializer, MarkPaidSerializer, RefundSerializer,
#                           RefundTaskSerializer, StaffBookingSerializer)

# logger = logging.getLogger(__name__)

# PRIVATE_KEYS = ("free_room_ids", "room_ids")


# def m(value):
#     """Money is always a 2-decimal string, never a float."""
#     return f"{value:.2f}"


# def error_response(exc):
#     return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status_code)


# def _selections(items):
#     return [Selection(key=i["key"], quantity=i["quantity"], guests=i.get("guests")) for i in items]


# def _public_item(item):
#     data = {k: v for k, v in item.items() if k not in PRIVATE_KEYS}
#     data["price"] = m(item["price"])
#     return data


# class AvailabilityView(APIView):
#     permission_classes = [AllowAny]

#     def get(self, request):
#         q = AvailabilityQuerySerializer(data=request.query_params)
#         q.is_valid(raise_exception=True)
#         d = q.validated_data
#         groups = availability_groups(d["check_in"], d["check_out"], d.get("property"))
#         return Response({
#             "check_in": d["check_in"], "check_out": d["check_out"],
#             "nights": (d["check_out"] - d["check_in"]).days,
#             "properties": [
#                 {
#                     "id": g["property"].id, "name": g["property"].name, "slug": g["property"].slug,
#                     "room_types": [_public_item(item) for item in g["items"]],
#                 }
#                 for g in groups
#             ],
#         })


# class QuoteView(APIView):
#     permission_classes = [AllowAny]
#     throttle_classes = [ScopedRateThrottle]
#     throttle_scope = "booking_quote"

#     def post(self, request):
#         s = QuoteRequestSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         d = s.validated_data
#         try:
#             quote = quote_selections(_selections(d["items"]), d["check_in"], d["check_out"])
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({
#             "nights": quote["nights"], "count": quote["count"], "guests": quote["guests"],
#             "subtotal": m(quote["subtotal"]), "tax": m(quote["tax"]), "total": m(quote["total"]),
#             "lines": [
#                 {"key": l["key"], "room_type": l["room_type"],
#                  "room_charge": m(l["quote"].room_charge),
#                  "extra_guest_charge": m(l["quote"].extra_guest_charge),
#                  "tax": m(l["quote"].tax), "total": m(l["quote"].total)}
#                 for l in quote["lines"]
#             ],
#         })


# class HoldView(APIView):
#     """Reserve rooms for 30 minutes. Payment (Razorpay) attaches to the group in step 5e."""
#     permission_classes = [AllowAny]
#     throttle_classes = [ScopedRateThrottle]
#     throttle_scope = "booking_hold"

#     def post(self, request):
#         s = HoldRequestSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         d = s.validated_data

#         if settings.BOOKING_REQUIRE_EMAIL_VERIFICATION and request.session.get("verified_email") != d["email"]:
#             return Response({"error": {"code": "email_not_verified",
#                                        "message": "Please verify your email first."}},
#                             status=status.HTTP_403_FORBIDDEN)
#         try:
#             result = create_hold(
#                 selections=_selections(d["items"]),
#                 check_in=d["check_in"], check_out=d["check_out"],
#                 guest={k: d.get(k, "") for k in ("first_name", "last_name", "email", "phone", "special_request")},
#                 user=request.user if request.user.is_authenticated else None,
#             )
#         except BookingError as exc:
#             return error_response(exc)

#         request.session["booking_groups"] = (request.session.get("booking_groups", []) + [result["group_ref"]])[-10:]
#         return Response({
#             "group_ref": result["group_ref"], "total": m(result["total"]),
#             "expires_at": result["expires_at"],
#             "bookings": [{"reference": b.reference, "total": m(b.total_amount)} for b in result["bookings"]],
#         }, status=status.HTTP_201_CREATED)

# class OtpSendView(APIView):
#     permission_classes = [AllowAny]
#     throttle_classes = [ScopedRateThrottle]
#     throttle_scope = "otp_send"

#     def post(self, request):
#         s = OtpSendSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         email = normalize_email(s.validated_data["email"])
#         try:
#             send_otp(email)
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"message": f"Verification code sent to {email}."})


# class OtpVerifyView(APIView):
#     permission_classes = [AllowAny]
#     throttle_classes = [ScopedRateThrottle]
#     throttle_scope = "otp_verify"

#     def post(self, request):
#         s = OtpVerifySerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         email = normalize_email(s.validated_data["email"])
#         try:
#             verify_otp(email, s.validated_data["otp"])
#         except BookingError as exc:
#             return error_response(exc)
#         request.session["verified_email"] = email                 # HoldView checks this
#         return Response({"verified": True})

# class PaymentOrderView(APIView):
#     permission_classes = [AllowAny]
#     throttle_classes = [ScopedRateThrottle]
#     throttle_scope = "payment_order"

#     def post(self, request):
#         s = PaymentOrderSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         group_ref = s.validated_data["group_ref"]
#         if group_ref not in request.session.get("booking_groups", []):
#             return error_response(UnknownGroup("Unknown booking."))      # not this visitor's hold
#         try:
#             payment = payments.create_order(group_ref)
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({
#             "key": settings.RAZORPAY_KEY_ID,            # public key id only; the secret never leaves the server
#             "order_id": payment.razorpay_order_id,
#             "amount": payment.amount, "currency": payment.currency,
#             "group_ref": group_ref, "name": settings.SITE_NAME,
#             "description": "Room booking " + group_ref,
#         })


# class PaymentVerifyView(APIView):
#     permission_classes = [AllowAny]
#     throttle_classes = [ScopedRateThrottle]
#     throttle_scope = "payment_verify"

#     def post(self, request):
#         s = PaymentVerifySerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         d = s.validated_data
#         try:
#             payments.verify_checkout_signature(d["razorpay_order_id"], d["razorpay_payment_id"],
#                                                d["razorpay_signature"])
#             payment = payments.confirm_payment(d["razorpay_order_id"], d["razorpay_payment_id"])
#         except BookingError as exc:
#             return error_response(exc)
#         if payment.status == Payment.Status.REFUND_REQUIRED:
#             return error_response(PaymentConflict(
#                 "Your payment was received but the rooms are no longer available. "
#                 "We will refund it. Please contact us with reference " + payment.group_ref + "."))
#         return Response({"group_ref": payment.group_ref, "status": "confirmed"})


# class RazorpayWebhookView(APIView):
#     """Server-to-server. Authenticated by signature over the raw body, not by session/CSRF."""
#     authentication_classes = []
#     permission_classes = [AllowAny]
#     throttle_classes = []

#     def post(self, request):
#         raw = request.body
#         if not payments.verify_webhook_signature(raw, request.headers.get("X-Razorpay-Signature", "")):
#             return Response({"error": {"code": "bad_signature", "message": "Invalid signature."}}, status=400)
#         try:
#             event = json.loads(raw)
#         except ValueError:
#             return Response({"error": {"code": "bad_payload", "message": "Invalid JSON."}}, status=400)

#         name = event.get("event")
#         entity = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
#         order_id, payment_id = entity.get("order_id"), entity.get("id")
#         try:
#             if name in ("payment.captured", "order.paid") and order_id and payment_id:
#                 payments.confirm_payment(order_id, payment_id, amount=entity.get("amount"))
#             elif name == "payment.failed" and order_id:
#                 payments.mark_failed(order_id)
#         except BookingError as exc:
#             logger.error("Webhook %s ignored: %s", name, exc.code)   # 200 so Razorpay does not retry forever
#         return Response({"status": "ok"})

# from rest_framework import status as http
# from rest_framework.decorators import action
# from rest_framework.generics import ListAPIView
# from rest_framework.response import Response
# from rest_framework.views import APIView
# from rest_framework.viewsets import ReadOnlyModelViewSet

# from accounts.access import properties_with_role
# from accounts.permissions import HasPropertyRole, IsPropertyManager, IsStaffMember

# from bookings.models import ExtensionRequest
# from bookings.services import lifecycle, stay
# from bookings.services.balance import outstanding
# from bookings.services.booking import Selection
# from bookings.services.errors import BookingError, UnknownBooking, UnknownProperty
# from properties.models import StaffAssignment
# from rooms.models import Room

# from .selectors import refund_tasks_for, refunds_for, scoped_bookings
# from .serializers import (CancelSerializer, CheckOutSerializer, DecisionSerializer, ExtendSerializer,
#                           ExtensionSerializer, HistorySerializer, HousekeepingSerializer,
#                           ManualBookingSerializer, MarkPaidSerializer, RefundSerializer,
#                           RefundTaskSerializer, StaffBookingSerializer)


# class MeView(APIView):                       # default permission: authenticated
#     def get(self, request):
#         u = request.user
#         roles = StaffAssignment.objects.filter(user=u).select_related("property")
#         return Response({
#             "id": u.id, "email": u.email, "name": u.get_full_name(), "is_superuser": u.is_superuser,
#             "roles": [{"property": a.property.slug, "role": a.role} for a in roles],
#         })


# class StaffBookingViewSet(ReadOnlyModelViewSet):
#     permission_classes = [IsStaffMember, HasPropertyRole]
#     serializer_class = StaffBookingSerializer
#     lookup_field = "reference"
#     lookup_value_regex = "HB-[A-Z0-9]{8}"
#     filterset_fields = {
#         "status": ["exact"], "payment_status": ["exact"], "source": ["exact"],
#         "property__slug": ["exact"], "check_in": ["gte", "lte"],
#     }
#     search_fields = ["reference", "customer_name", "customer_email", "customer_phone"]
#     ordering_fields = ["check_in", "created_at"]
#     ordering = ["-created_at"]

#     def get_queryset(self):
#         # Scoped here, so another property's booking is a 404 (existence is not revealed).
#         return scoped_bookings(self.request.user).select_related("property", "room")

#     @action(detail=True, methods=["post"])
#     def cancel(self, request, reference=None):
#         booking = self.get_object()          # scoped queryset + object permission
#         s = CancelSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         try:
#             outcome = lifecycle.cancel_booking(
#                 booking.pk, actor=request.user, reason=s.validated_data["reason"],
#                 waive_penalty=s.validated_data["waive_penalty"])
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"reference": booking.reference, "status": "CANCELLED", "free": outcome.free,
#                          "waived": outcome.waived, "penalty": m(outcome.penalty),
#                          "refund_due": m(outcome.refund)})

#     @action(detail=True, methods=["post"], url_path="mark-paid")
#     def mark_paid(self, request, reference=None):
#         booking = self.get_object()
#         s = MarkPaidSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         try:
#             booking = lifecycle.record_payment(booking.pk, actor=request.user, **s.validated_data)
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"reference": booking.reference, "payment_status": booking.payment_status})

#     @action(detail=True, methods=["post"], url_path="check-in")
#     def check_in(self, request, reference=None):
#         booking = self.get_object()
#         try:
#             b = stay.check_in(booking.pk, actor=request.user)
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"reference": b.reference, "status": b.status,
#                          "actual_check_in": b.actual_check_in,
#                          "housekeeping_warning": b.room.housekeeping_status != Room.HousekeepingStatus.CLEAN})

#     @action(detail=True, methods=["post"], url_path="check-out")
#     def check_out(self, request, reference=None):
#         booking = self.get_object()
#         s = CheckOutSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         try:
#             b = stay.check_out(booking.pk, actor=request.user, **s.validated_data)
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"reference": b.reference, "status": b.status,
#                          "actual_check_out": b.actual_check_out, "balance_due": m(outstanding(b))})

#     @action(detail=True, methods=["post"], url_path="no-show")
#     def no_show(self, request, reference=None):
#         booking = self.get_object()
#         try:
#             outcome = stay.mark_no_show(booking.pk, actor=request.user)
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"reference": booking.reference, "status": "NO_SHOW",
#                          "penalty": m(outcome.penalty), "refund_due": m(outcome.refund)})

#     @action(detail=True, methods=["post"])
#     def extend(self, request, reference=None):
#         booking = self.get_object()
#         s = ExtendSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         try:
#             stay.extend_now(booking.pk, actor=request.user, new_check_out=s.validated_data["new_check_out"],
#                             note=s.validated_data["note"])
#         except BookingError as exc:
#             return error_response(exc)
#         booking.refresh_from_db()
#         return Response({"reference": booking.reference, "check_out": booking.check_out,
#                          "total": m(booking.total_amount), "balance_due": m(outstanding(booking))})

#     @action(detail=True, methods=["get"])
#     def history(self, request, reference=None):
#         booking = self.get_object()
#         return Response(HistorySerializer(booking.history.all(), many=True).data)


# class RefundQueueView(ListAPIView):
#     permission_classes = [IsPropertyManager]
#     serializer_class = RefundSerializer

#     def get_queryset(self):
#         return refunds_for(self.request.user)


# class ManualBookingView(APIView):
#     permission_classes = [IsStaffMember]

#     def post(self, request):
#         s = ManualBookingSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         d = s.validated_data
#         prop = properties_with_role(request.user).filter(slug=d["property"]).first()
#         if prop is None:                                   # unassigned property: existence not revealed
#             return error_response(UnknownProperty("Unknown property."))
#         try:
#             result = lifecycle.create_manual_booking(
#                 actor=request.user, property=prop, source=d["source"],
#                 selections=[Selection(key=i["key"], quantity=i["quantity"], guests=i.get("guests"))
#                             for i in d["items"]],
#                 check_in=d["check_in"], check_out=d["check_out"],
#                 guest={k: d.get(k, "") for k in ("first_name", "last_name", "email", "phone",
#                                                  "special_request", "internal_notes")},
#             )
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({
#             "group_ref": result["group_ref"], "total": m(result["total"]),
#             "bookings": [{"reference": b.reference, "room": b.room.number, "total": m(b.total_amount)}
#                          for b in result["bookings"]],
#         }, status=http.HTTP_201_CREATED)


# class RefundTaskListView(ListAPIView):
#     permission_classes = [IsPropertyManager]
#     serializer_class = RefundTaskSerializer

#     def get_queryset(self):
#         return refund_tasks_for(self.request.user)


# class RefundTaskCompleteView(APIView):
#     permission_classes = [IsPropertyManager]

#     def post(self, request, pk):
#         task = refund_tasks_for(request.user).filter(pk=pk).first()
#         if task is None:
#             return error_response(UnknownBooking("Unknown refund task."))
#         try:
#             lifecycle.complete_refund(task.pk, actor=request.user)
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"id": task.pk, "status": "DONE"})


# class ExtensionListView(ListAPIView):
#     permission_classes = [IsStaffMember]
#     serializer_class = ExtensionSerializer
#     filterset_fields = ["status"]

#     def get_queryset(self):
#         return ExtensionRequest.objects.filter(
#             booking__property__in=properties_with_role(self.request.user)).select_related("booking")


# class _ExtensionDecisionView(APIView):
#     permission_classes = [IsStaffMember]

#     def decide(self, pk, actor, note):
#         raise NotImplementedError

#     def post(self, request, pk):
#         ext = ExtensionRequest.objects.filter(
#             pk=pk, booking__property__in=properties_with_role(request.user)).select_related("booking").first()
#         if ext is None:                                   # another property's request: 404
#             return error_response(UnknownBooking("Unknown extension request."))
#         s = DecisionSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         try:
#             ext = self.decide(ext.pk, request.user, s.validated_data["note"])
#         except BookingError as exc:
#             return error_response(exc)
#         return Response({"id": ext.pk, "booking": ext.booking.reference, "status": ext.status})


# class ExtensionApproveView(_ExtensionDecisionView):
#     def decide(self, pk, actor, note):
#         return stay.approve_extension(pk, actor=actor, note=note)


# class ExtensionRejectView(_ExtensionDecisionView):
#     def decide(self, pk, actor, note):
#         return stay.reject_extension(pk, actor=actor, note=note)


# class HousekeepingView(APIView):
#     permission_classes = [IsStaffMember]

#     def post(self, request, pk):
#         room = Room.objects.filter(pk=pk, property__in=properties_with_role(request.user)).first()
#         if room is None:
#             return error_response(UnknownBooking("Unknown room."))
#         s = HousekeepingSerializer(data=request.data)
#         s.is_valid(raise_exception=True)
#         Room.objects.filter(pk=room.pk).update(housekeeping_status=s.validated_data["status"])
#         return Response({"room": room.number, "housekeeping_status": s.validated_data["status"]})

import json
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Payment
from .serializers import (
    AvailabilityQuerySerializer,
    HoldRequestSerializer,
    OtpSendSerializer,
    OtpVerifySerializer,
    PaymentOrderSerializer,
    PaymentVerifySerializer,
    QuoteRequestSerializer,
)
from .services import payments
from .services.availability import availability_groups
from .services.booking import Selection, create_hold, quote_selections
from .services.errors import BookingError, PaymentConflict, UnknownGroup
from .services.otp import normalize_email, send_otp, verify_otp

logger = logging.getLogger(__name__)

PRIVATE_KEYS = ("free_room_ids", "room_ids")


def m(value):
    """Money is always a 2-decimal string, never a float."""
    return f"{value:.2f}"


def error_response(exc):
    return Response({"error": {"code": exc.code, "message": exc.message}}, status=exc.status_code)


def _selections(items):
    return [Selection(key=i["key"], quantity=i["quantity"], guests=i.get("guests")) for i in items]


def _public_item(item):
    data = {k: v for k, v in item.items() if k not in PRIVATE_KEYS}
    data["price"] = m(item["price"])
    return data


class AvailabilityView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        q = AvailabilityQuerySerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        d = q.validated_data
        groups = availability_groups(d["check_in"], d["check_out"], d.get("property"))
        return Response({
            "check_in": d["check_in"], "check_out": d["check_out"],
            "nights": (d["check_out"] - d["check_in"]).days,
            "properties": [
                {
                    "id": g["property"].id, "name": g["property"].name, "slug": g["property"].slug,
                    "room_types": [_public_item(item) for item in g["items"]],
                }
                for g in groups
            ],
        })


class QuoteView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "booking_quote"

    def post(self, request):
        s = QuoteRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            quote = quote_selections(_selections(d["items"]), d["check_in"], d["check_out"])
        except BookingError as exc:
            return error_response(exc)
        return Response({
            "nights": quote["nights"], "count": quote["count"], "guests": quote["guests"],
            "subtotal": m(quote["subtotal"]), "tax": m(quote["tax"]), "total": m(quote["total"]),
            "lines": [
                {"key": l["key"], "room_type": l["room_type"],
                 "room_charge": m(l["quote"].room_charge),
                 "extra_guest_charge": m(l["quote"].extra_guest_charge),
                 "tax": m(l["quote"].tax), "total": m(l["quote"].total)}
                for l in quote["lines"]
            ],
        })


class HoldView(APIView):
    """Reserve rooms for 30 minutes. Payment (Razorpay) attaches to the group in step 5e."""
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "booking_hold"

    def post(self, request):
        s = HoldRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        if settings.BOOKING_REQUIRE_EMAIL_VERIFICATION and request.session.get("verified_email") != d["email"]:
            return Response({"error": {"code": "email_not_verified",
                                       "message": "Please verify your email first."}},
                            status=status.HTTP_403_FORBIDDEN)
        try:
            result = create_hold(
                selections=_selections(d["items"]),
                check_in=d["check_in"], check_out=d["check_out"],
                guest={k: d.get(k, "") for k in ("first_name", "last_name", "email", "phone", "special_request")},
                user=request.user if request.user.is_authenticated else None,
            )
        except BookingError as exc:
            return error_response(exc)

        request.session["booking_groups"] = (request.session.get("booking_groups", []) + [result["group_ref"]])[-10:]
        return Response({
            "group_ref": result["group_ref"], "total": m(result["total"]),
            "expires_at": result["expires_at"],
            "bookings": [{"reference": b.reference, "total": m(b.total_amount)} for b in result["bookings"]],
        }, status=status.HTTP_201_CREATED)


class OtpSendView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_send"

    def post(self, request):
        s = OtpSendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = normalize_email(s.validated_data["email"])
        try:
            send_otp(email)
        except BookingError as exc:
            return error_response(exc)
        return Response({"message": f"Verification code sent to {email}."})


class OtpVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_verify"

    def post(self, request):
        s = OtpVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        email = normalize_email(s.validated_data["email"])
        try:
            verify_otp(email, s.validated_data["otp"])
        except BookingError as exc:
            return error_response(exc)
        request.session["verified_email"] = email                 # HoldView checks this
        return Response({"verified": True})


class PaymentOrderView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_order"

    def post(self, request):
        s = PaymentOrderSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        group_ref = s.validated_data["group_ref"]
        if group_ref not in request.session.get("booking_groups", []):
            return error_response(UnknownGroup("Unknown booking."))      # not this visitor's hold
        try:
            payment = payments.create_order(group_ref)
        except BookingError as exc:
            return error_response(exc)
        return Response({
            "key": settings.RAZORPAY_KEY_ID,            # public key id only; the secret never leaves the server
            "order_id": payment.razorpay_order_id,
            "amount": payment.amount, "currency": payment.currency,
            "group_ref": group_ref, "name": settings.SITE_NAME,
            "description": "Room booking " + group_ref,
        })


class PaymentVerifyView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "payment_verify"

    def post(self, request):
        s = PaymentVerifySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            payments.verify_checkout_signature(d["razorpay_order_id"], d["razorpay_payment_id"],
                                               d["razorpay_signature"])
            payment = payments.confirm_payment(d["razorpay_order_id"], d["razorpay_payment_id"])
        except BookingError as exc:
            return error_response(exc)
        if payment.status == Payment.Status.REFUND_REQUIRED:
            return error_response(PaymentConflict(
                "Your payment was received but the rooms are no longer available. "
                "We will refund it. Please contact us with reference " + payment.group_ref + "."))
        return Response({"group_ref": payment.group_ref, "status": "confirmed"})


class RazorpayWebhookView(APIView):
    """Server-to-server. Authenticated by signature over the raw body, not by session/CSRF."""
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    def post(self, request):
        raw = request.body
        if not payments.verify_webhook_signature(raw, request.headers.get("X-Razorpay-Signature", "")):
            return Response({"error": {"code": "bad_signature", "message": "Invalid signature."}}, status=400)
        try:
            event = json.loads(raw)
        except ValueError:
            return Response({"error": {"code": "bad_payload", "message": "Invalid JSON."}}, status=400)

        name = event.get("event")
        entity = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
        order_id, payment_id = entity.get("order_id"), entity.get("id")
        try:
            if name in ("payment.captured", "order.paid") and order_id and payment_id:
                payments.confirm_payment(order_id, payment_id, amount=entity.get("amount"))
            elif name == "payment.failed" and order_id:
                payments.mark_failed(order_id)
        except BookingError as exc:
            logger.error("Webhook %s ignored: %s", name, exc.code)   # 200 so Razorpay does not retry forever
        return Response({"status": "ok"})