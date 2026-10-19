"""Phone number matching, the same whatever CRM or phone system is connected."""
import re

# Tunisian numbers are 8 digits once the +216 / 00216 prefix is dropped. Calls and the CRM write them both
# ways, so numbers are compared on their last 8 digits.
MATCH_DIGITS = 8


def match_key(number: str) -> str | None:
    """The part of a phone number to search the CRM for, or None for extensions and other short numbers."""
    digits = re.sub(r"\D", "", number or "")
    return digits[-MATCH_DIGITS:] if len(digits) >= MATCH_DIGITS else None
