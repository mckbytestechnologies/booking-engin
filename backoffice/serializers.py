from rest_framework import serializers

from bookings.forms import GuestDetailsForm
from bookings.models import Booking, BookingHistory, ExtensionRequest, Payment, RefundTask
from bookings.serializers import SelectionSerializer
from bookings.services.balance import outstanding
from rooms.models import Room


class StaffBookingSerializer(serializers.ModelSerializer):
    property = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    room = serializers.CharField(source="room.number", read_only=True)
    nights = serializers.IntegerField(read_only=True)
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "reference", "group_ref", "property", "room", "customer_name", "customer_email",
            "customer_phone", "check_in", "check_out", "nights", "guests", "price_per_night",
            "additional_charges", "discount", "tax_amount", "total_amount", "amount_paid",
            "balance_due", "status", "payment_status", "source", "actual_check_in",
            "actual_check_out", "special_requests", "internal_notes", "created_at",
        ]
        read_only_fields = fields

    def get_balance_due(self, obj):
        return f"{outstanding(obj):.2f}"


class RefundSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["group_ref", "razorpay_order_id", "razorpay_payment_id", "amount", "currency", "created_at"]
        read_only_fields = fields


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    waive_penalty = serializers.BooleanField(default=False)


class MarkPaidSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=["CASH", "CARD", "UPI"])
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CheckOutSerializer(serializers.Serializer):
    override_unpaid = serializers.BooleanField(default=False)
    release_unused_nights = serializers.BooleanField(default=False)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class ExtendSerializer(serializers.Serializer):
    new_check_out = serializers.DateField()
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class DecisionSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class HousekeepingSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Room.HousekeepingStatus.choices)


class ManualBookingSerializer(serializers.Serializer):
    property = serializers.SlugField()
    source = serializers.ChoiceField(choices=[Booking.Source.ADMIN_MANUAL, Booking.Source.WALK_IN])
    check_in = serializers.DateField()
    check_out = serializers.DateField()
    items = SelectionSerializer(many=True, allow_empty=False, max_length=10)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    email = serializers.CharField(max_length=254)
    phone = serializers.CharField(max_length=30)
    special_request = serializers.CharField(max_length=500, required=False, allow_blank=True)
    internal_notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)

    def validate(self, attrs):
        form = GuestDetailsForm(attrs)             # the same guest rules as the public flow
        if not form.is_valid():
            raise serializers.ValidationError(
                {f: [str(e) for e in errs] for f, errs in form.errors.items()})
        attrs.update(form.cleaned_data)
        return attrs


class RefundTaskSerializer(serializers.ModelSerializer):
    booking = serializers.CharField(source="booking.reference", read_only=True)

    class Meta:
        model = RefundTask
        fields = ["id", "booking", "amount", "reason", "status", "created_at"]
        read_only_fields = fields


class ExtensionSerializer(serializers.ModelSerializer):
    booking = serializers.CharField(source="booking.reference", read_only=True)

    class Meta:
        model = ExtensionRequest
        fields = ["id", "booking", "original_check_out", "requested_check_out", "status",
                  "added_nights", "rate_per_night", "added_amount", "decision_note",
                  "created_at", "decided_at"]
        read_only_fields = fields


class HistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingHistory
        fields = ["created_at", "action", "from_status", "to_status", "actor_label", "reason", "details"]
        read_only_fields = fields