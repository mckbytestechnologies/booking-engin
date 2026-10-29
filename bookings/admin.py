from django.contrib import admin

from .models import Booking, RoomBlock
from .models import Booking, EmailOTP, RoomBlock


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer_name", "property", "room", "check_in", "check_out", "status", "payment_status")
    list_filter = ("status", "payment_status", "source", "property")
    search_fields = ("reference", "customer_name", "customer_email", "customer_phone")
    readonly_fields = ("reference", "created_at", "updated_at")


@admin.register(RoomBlock)
class RoomBlockAdmin(admin.ModelAdmin):
    list_display = ("room", "start_date", "end_date", "reason")
    list_filter = ("room__property",)


@admin.register(EmailOTP)
class EmailOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at", "expires_at", "attempts", "verified_at")
    fields = ("email", "created_at", "expires_at", "attempts", "verified_at")
    readonly_fields = fields

from .models import Booking, EmailOTP, Payment, RoomBlock

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("razorpay_order_id", "group_ref", "amount", "status", "paid_at", "created_at")
    list_filter = ("status",)
    search_fields = ("group_ref", "razorpay_order_id", "razorpay_payment_id")
    readonly_fields = ("group_ref", "razorpay_order_id", "razorpay_payment_id", "amount", "currency", "paid_at")

from .models import Booking, BookingHistory, EmailOTP, Payment, RefundTask, RoomBlock


class BookingHistoryInline(admin.TabularInline):
    model = BookingHistory
    extra = 0
    can_delete = False
    fields = readonly_fields = ("created_at", "action", "from_status", "to_status", "actor_label", "reason", "details")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(RefundTask)
class RefundTaskAdmin(admin.ModelAdmin):
    list_display = ("booking", "amount", "status", "created_at", "completed_at")
    list_filter = ("status",)
    readonly_fields = ("booking", "amount", "reason", "completed_by", "completed_at")

from .models import ExtensionRequest   # merge into the existing models import


@admin.register(ExtensionRequest)
class ExtensionRequestAdmin(admin.ModelAdmin):
    list_display = ("booking", "original_check_out", "requested_check_out", "status", "added_amount", "created_at")
    list_filter = ("status",)
    readonly_fields = ("booking", "original_check_out", "requested_check_out", "requested_by_label",
                       "decided_by", "decided_at", "added_nights", "rate_per_night", "added_amount")


from django.contrib import admin, messages
from .models import EmailNotification            # merge into the existing models import
from .services.notifications import deliver


@admin.register(EmailNotification)
class EmailNotificationAdmin(admin.ModelAdmin):
    list_display = ("kind", "to_email", "status", "attempts", "created_at", "sent_at")
    list_filter = ("status", "kind")
    search_fields = ("to_email", "dedupe_key", "booking__reference")
    readonly_fields = [f.name for f in EmailNotification._meta.fields]
    actions = ["retry_selected"]

    @admin.action(description="Retry selected emails now")
    def retry_selected(self, request, queryset):
        sent = 0
        for mail in queryset.exclude(status=EmailNotification.Status.SENT):
            EmailNotification.objects.filter(pk=mail.pk).update(status="PENDING", attempts=0)
            sent += deliver(mail.pk)
        self.message_user(request, f"{sent} email(s) sent.", messages.INFO)


        