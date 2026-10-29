import re

from django.core.exceptions import ValidationError


def normalize_phone(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not 10 <= len(digits) <= 15:
        raise ValidationError("Enter a valid phone number (10-15 digits).")
    return digits