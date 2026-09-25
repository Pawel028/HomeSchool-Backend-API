"""Guardian OTP generation and delivery.

Providers: console (writes the code to the application log: dev/test/nonprod only, refused in prod by config),
webhook (POSTs {"to", "message"} to your SMS gateway over HTTPS), disabled (always fails).

OTP_STATIC_TEST_CODE (dev/nonprod only, never prod): when set, every generated code is this fixed value
instead of a random one, so a group of testers can all be told the same code out of band rather than each
needing real SMS delivery. Delivery (console/webhook/disabled) still runs as configured; only generation
is affected.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import urllib.error
import urllib.request
import uuid

from app.config import get_settings
from app.errors import ApiError

log = logging.getLogger("app.otp")


def new_code() -> str:
    s = get_settings()
    if s.otp_static_test_code:
        return s.otp_static_test_code
    return f"{secrets.randbelow(10**6):06d}"


def digest(verification_id: uuid.UUID, code: str) -> str:
    return hashlib.sha256(f"{verification_id}:{code}".encode()).hexdigest()


def matches(verification_id: uuid.UUID, code: str, stored: str | None) -> bool:
    return bool(stored) and hmac.compare_digest(digest(verification_id, code), stored)


def deliver(phone: str, code: str) -> None:
    s = get_settings()
    message = f"Your HomeSchool verification code is {code}. It expires in {s.otp_ttl_minutes} minutes."
    if s.otp_provider == "console":
        log.warning("OTP (console provider) for ****%s: %s", phone[-4:], code)
        return
    if s.otp_provider == "webhook" and s.otp_webhook_url:
        body = json.dumps({"to": phone, "message": message}).encode()
        req = urllib.request.Request(
            s.otp_webhook_url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {s.otp_webhook_token.get_secret_value()}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310 (https enforced by config)
                if resp.status >= 300:
                    raise ApiError(503, "delivery_failed")
        except (urllib.error.URLError, TimeoutError):
            log.error("OTP webhook delivery failed")
            raise ApiError(503, "delivery_failed") from None
        return
    raise ApiError(503, "delivery_failed", "Verification codes cannot be sent right now.")
