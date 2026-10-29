import secrets

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from core.models import TimeStampedModel
from properties.models import Property
from rooms.models import Room
from django.utils.functional import cached_property

REF_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O/1/I/L


def generate_reference():
    return "HB-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(8))


class BookingQuerySet(models.QuerySet):
    def overlapping(self, check_in, check_out):
        return self.filter(check_in__lt=check_out, check_out__gt=check_in)

    def blocking(self, now=None):
        now = now or timezone.now()
        always = [Booking.Status.CONFIRMED, Booking.Status.CHECKED_IN, Booking.Status.CHECKED_OUT]
        return self.filter(
            Q(status__in=always)
            | Q(status=Booking.Status.PENDING, expires_at__isnull=True)
            | Q(status=Booking.Status.PENDING, expires_at__gt=now)
        )


class Booking(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CHECKED_IN = "CHECKED_IN", "Checked in"
        CHECKED_OUT = "CHECKED_OUT", "Checked out"
        CANCELLED = "CANCELLED", "Cancelled"
        NO_SHOW = "NO_SHOW", "No show"
        EXPIRED = "EXPIRED", "Expired"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PENDING = "PENDING", "Pending"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"
        REFUNDED = "REFUNDED", "Refunded"
        FAILED = "FAILED", "Failed"
        EXTENSION = "EXTENSION", "Extension"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    class Source(models.TextChoices):
        ONLINE = "ONLINE", "Online"
        ADMIN_MANUAL = "ADMIN_MANUAL", "Admin manual"
        WALK_IN = "WALK_IN", "Walk-in"

    reference = models.CharField(max_length=20, unique=True, default=generate_reference, editable=False)
    # One payment can cover several rooms; Module 5 fills this in.
    group_ref = models.CharField(max_length=20, blank=True, db_index=True)

    property = models.ForeignKey(Property, on_delete=models.PROTECT, related_name="bookings")
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="bookings")
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="bookings"
    )
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20)

    check_in = models.DateField()
    check_out = models.DateField()
    guests = models.PositiveSmallIntegerField(default=1)

    # Snapshots taken at booking time; later rate changes never rewrite history.
    price_per_night = models.DecimalField(max_digits=10, decimal_places=2)
    additional_charges = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING, db_index=True)
    payment_status = models.CharField(max_length=15, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    source = models.CharField(max_length=15, choices=Source.choices, default=Source.ONLINE)
    expires_at = models.DateTimeField(null=True, blank=True)   # hold deadline for PENDING
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                      help_text="Only meaningful while PARTIALLY_PAID")
    actual_check_in = models.DateTimeField(null=True, blank=True)
    actual_check_out = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")
    checked_out_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")
    special_requests = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    objects = BookingQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(check_out__gt=F("check_in")), name="booking_checkout_after_checkin"),
            models.CheckConstraint(condition=Q(guests__gte=1), name="booking_guests_min_1"),
            models.CheckConstraint(
                condition=Q(price_per_night__gte=0) & Q(total_amount__gte=0)
                & Q(additional_charges__gte=0) & Q(discount__gte=0) & Q(tax_amount__gte=0),
                name="booking_amounts_non_negative",
            ),
            models.CheckConstraint(condition=Q(amount_paid__gte=0), name="booking_amount_paid_non_negative"),
        ]
        indexes = [
            models.Index(fields=["room", "check_in", "check_out"]),   # overlap lookups
            models.Index(fields=["status", "expires_at"]),            # hold-expiry job
        ]

    @cached_property
    def nights(self):
        # Derived, not stored, so it can never disagree with the dates.
        return (self.check_out - self.check_in).days

    def __str__(self):
        return f"{self.reference} ({self.room})"


class RoomBlock(TimeStampedModel):
    """Maintenance or manual block. Same half-open [start, end) rule as bookings."""

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="blocks")
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["start_date"]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gt=F("start_date")), name="block_end_after_start"),
        ]
        indexes = [models.Index(fields=["room", "start_date", "end_date"])]

    def __str__(self):
        return f"{self.room} blocked {self.start_date} to {self.end_date}"

class EmailOTP(TimeStampedModel):
    """One-time email verification code. Only a keyed hash of the code is stored."""

    email = models.EmailField(db_index=True)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["email", "created_at"])]

    def __str__(self):
        return f"OTP for {self.email}"

class Payment(TimeStampedModel):
    class Status(models.TextChoices):
        CREATED = "CREATED", "Created"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        REFUND_REQUIRED = "REFUND_REQUIRED", "Refund required"

    group_ref = models.CharField(max_length=20, db_index=True)
    razorpay_order_id = models.CharField(max_length=64, unique=True)
    razorpay_payment_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    amount = models.PositiveIntegerField(help_text="Paise (1/100 rupee)")
    currency = models.CharField(max_length=3, default="INR")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED, db_index=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive")]

    def __str__(self):
        return f"{self.razorpay_order_id} ({self.status})"

class BookingHistory(TimeStampedModel):
    """Append-only audit trail for a booking."""

    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        STATUS_CHANGE = "STATUS_CHANGE", "Status change"
        PAYMENT = "PAYMENT", "Payment recorded"
        REFUND = "REFUND", "Refund completed"
        EXTENSION = "EXTENSION", "Extension"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="history")
    action = models.CharField(max_length=15, choices=Action.choices)
    from_status = models.CharField(max_length=15, blank=True)
    to_status = models.CharField(max_length=15, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    actor_label = models.CharField(max_length=254)          # survives user deletion
    reason = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["booking", "created_at"])]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError("Booking history is append-only.")
        super().save(*args, **kwargs)


class RefundTask(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DONE = "DONE", "Done"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="refund_tasks")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="refund_amount_positive")]
        
class ExtensionRequest(TimeStampedModel):
    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name="extensions")
    original_check_out = models.DateField()
    requested_check_out = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="+")
    requested_by_label = models.CharField(max_length=254)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=255, blank=True)
    # Filled on approval: what the added nights cost and at which rate.
    added_nights = models.PositiveSmallIntegerField(null=True, blank=True)
    rate_per_night = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    added_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [models.CheckConstraint(
            condition=Q(requested_check_out__gt=F("original_check_out")), name="extension_dates_ordered")]

    def __str__(self):
        return f"Extension of {self.booking.reference} to {self.requested_check_out} ({self.status})"


class EmailNotification(TimeStampedModel):
    """Outbox row. Written in the booking's transaction, sent after it commits."""

    class Kind(models.TextChoices):
        BOOKING_CONFIRMED = "BOOKING_CONFIRMED", "Booking confirmed"
        BOOKING_CANCELLED = "BOOKING_CANCELLED", "Booking cancelled"
        CHECKED_IN = "CHECKED_IN", "Checked in"
        CHECKED_OUT = "CHECKED_OUT", "Checked out"
        EXTENSION_REQUESTED = "EXTENSION_REQUESTED", "Extension requested"
        EXTENSION_APPROVED = "EXTENSION_APPROVED", "Extension approved"
        EXTENSION_REJECTED = "EXTENSION_REJECTED", "Extension rejected"
        ADMIN_NEW_BOOKING = "ADMIN_NEW_BOOKING", "New booking (admin)" 

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENDING = "SENDING", "Sending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    booking = models.ForeignKey(Booking, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="emails")
    kind = models.CharField(max_length=30, choices=Kind.choices)
    to_email = models.EmailField()
    subject = models.CharField(max_length=200)
    body_text = models.TextField()
    body_html = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.CharField(max_length=500, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    dedupe_key = models.CharField(max_length=120, unique=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} to {self.to_email} ({self.status})"