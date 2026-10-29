from django.urls import path

from . import api, views

page_urlpatterns = [
    path("", views.EngineView.as_view(), name="booking_engine"),
    path("success/", views.SuccessView.as_view(), name="booking_success"),
]

api_urlpatterns = [
    # Availability and booking
    path("availability/", api.AvailabilityView.as_view(), name="booking_availability"),
    path("quotes/", api.QuoteView.as_view(), name="booking_quote"),
    path("holds/", api.HoldView.as_view(), name="booking_hold"),

    # Email OTP verification
    path("otp/send/", api.OtpSendView.as_view(), name="booking_send_otp"),
    path("otp/verify/", api.OtpVerifyView.as_view(), name="booking_verify_otp"),

    # Razorpay payments
    path("payments/orders/", api.PaymentOrderView.as_view(), name="booking_create_order"),
    path("payments/verify/", api.PaymentVerifyView.as_view(), name="booking_verify_payment"),
    path("payments/webhook/", api.RazorpayWebhookView.as_view(), name="booking_payment_webhook"),
]