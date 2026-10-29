class BookingError(Exception):
    code = "booking_error"
    status_code = 400

    def __init__(self, message=""):
        super().__init__(message)
        self.message = message


class InvalidDates(BookingError):
    code = "invalid_dates"


class InvalidSelection(BookingError):
    code = "invalid_selection"


class PricingError(BookingError):
    code = "pricing_error"


class RoomUnavailable(BookingError):
    code = "room_unavailable"
    status_code = 409          # valid request, but the world changed

class OtpInvalid(BookingError):
    code = "otp_invalid"


class OtpThrottled(BookingError):
    code = "otp_throttled"
    status_code = 429


class OtpDeliveryFailed(BookingError):
    code = "otp_delivery_failed"
    status_code = 503

class UnknownGroup(BookingError):
    code = "unknown_group"
    status_code = 404


class HoldExpired(BookingError):
    code = "hold_expired"
    status_code = 409


class AlreadyPaid(BookingError):
    code = "already_paid"
    status_code = 409


class PaymentNotConfigured(BookingError):
    code = "payments_not_configured"
    status_code = 503


class PaymentGatewayError(BookingError):
    code = "payment_gateway_error"
    status_code = 502


class PaymentSignatureInvalid(BookingError):
    code = "payment_signature_invalid"


class PaymentNotFound(BookingError):
    code = "payment_not_found"
    status_code = 404


class PaymentAmountMismatch(BookingError):
    code = "payment_amount_mismatch"


class PaymentConflict(BookingError):
    code = "payment_conflict"
    status_code = 409

class InvalidTransition(BookingError):
    code = "invalid_transition"
    status_code = 409


class NotPermitted(BookingError):
    code = "not_permitted"
    status_code = 403


class ReasonRequired(BookingError):
    code = "reason_required"


class UnknownBooking(BookingError):
    code = "unknown_booking"
    status_code = 404


class UnknownProperty(BookingError):
    code = "unknown_property"
    status_code = 404

class PaymentOutstanding(BookingError):
    code = "payment_outstanding"
    status_code = 409


class ExtensionConflict(BookingError):
    code = "extension_conflict"
    status_code = 409