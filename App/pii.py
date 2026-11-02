"""PII/secret masking that runs before external model calls and log writes."""
import re

_PATTERNS = [
    (re.compile(r"(?i)\b(password|passcode|passwd|pwd|pin)\s*[:=]?\s*[^\s,;]+"), r"\1=[REDACTED_SECRET]"),
    (re.compile(r"(?<!\w)\d{4}[ -]?\d{4}[ -]?\d{4}(?!\w)"), "[REDACTED_ID]"),
    (re.compile(r"(?i)(?<![A-Z0-9])[A-Z]{5}[0-9]{4}[A-Z](?![A-Z0-9])"), "[REDACTED_ID]"),
    (re.compile(r"(?<!\w)(?:\+?91[ -]?)?[6-9]\d{4}[ -]?\d{5}(?!\w)"), "[REDACTED_PHONE]"),
    (re.compile(r"(?<!\w)00000[ -]?00000(?!\w)"), "[REDACTED_PHONE]"),
]
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def mask_sensitive_text(text: str, allowed_email: str | None = None) -> str:
    """Mask passwords, Indian identity-number patterns, phone numbers and third-party email."""
    value = str(text or "")
    for pattern, replacement in _PATTERNS:
        value = pattern.sub(replacement, value)
    def replace_email(match):
        address = match.group(0)
        return address if allowed_email and address.casefold() == allowed_email.casefold() else "[REDACTED_EMAIL]"
    return _EMAIL.sub(replace_email, value)


def mask_ticket_text(ticket: dict) -> dict:
    """Return a shallow copy with user-authored text masked; keep the stored ticket untouched."""
    result = dict(ticket)
    requester = result.get("requester") or {}
    allowed = requester.get("email")
    for key in ("short_description", "description"):
        if key in result:
            result[key] = mask_sensitive_text(result[key], allowed_email=allowed)
    return result
