"""
audit_logger.py — Structured security event logging for spinr.

All security-relevant events (auth, OTP, session, admin access) are emitted
through this module so they can be filtered, aggregated, and alerted on
independently of general application logs.

PII rules enforced here:
  - Phone numbers logged as last-4 digits only (phone_hint)
  - Never log OTP codes, passwords, tokens, or secrets
  - user_id is a UUID — safe to log

Usage:
    from utils.audit_logger import log_security_event, SecurityEvent

    log_security_event(SecurityEvent.OTP_VERIFIED, phone_hint=phone[-4:])
    log_security_event(SecurityEvent.AUTH_FAILED, reason="invalid_jwt", path="/api/rides")
"""

from loguru import logger
import time


class SecurityEvent:
    """Constants for security event names."""
    # OTP lifecycle
    OTP_SENT            = "OTP_SENT"
    OTP_SEND_FAILED     = "OTP_SEND_FAILED"
    OTP_VERIFIED        = "OTP_VERIFIED"
    OTP_INVALID         = "OTP_INVALID"
    OTP_EXPIRED         = "OTP_EXPIRED"
    OTP_RATE_LIMITED    = "OTP_RATE_LIMITED"
    OTP_LOCKOUT_TRIGGERED = "OTP_LOCKOUT_TRIGGERED"

    # Authentication
    AUTH_SUCCESS        = "AUTH_SUCCESS"
    AUTH_FAILED         = "AUTH_FAILED"
    AUTH_SESSION_MISMATCH = "AUTH_SESSION_MISMATCH"
    AUTH_NO_TOKEN       = "AUTH_NO_TOKEN"
    AUTH_TOKEN_EXPIRED  = "AUTH_TOKEN_EXPIRED"

    # Admin access
    ADMIN_ACCESS_GRANTED = "ADMIN_ACCESS_GRANTED"
    ADMIN_ACCESS_DENIED  = "ADMIN_ACCESS_DENIED"

    # User lifecycle
    USER_CREATED        = "USER_CREATED"
    USER_SESSION_CREATED = "USER_SESSION_CREATED"


def log_security_event(event: str, **kwargs) -> None:
    """
    Emit a structured JSON security audit log line.

    The log line is tagged with security=True so it can be filtered separately
    from application logs in Sentry, Datadog, or any log aggregator.

    Args:
        event: One of the SecurityEvent constants (e.g. SecurityEvent.OTP_SENT)
        **kwargs: Additional structured fields. Never include raw credentials,
                  full phone numbers, OTP codes, tokens, or secret keys.

    Example:
        log_security_event(SecurityEvent.OTP_INVALID, phone_hint="7890")
        log_security_event(SecurityEvent.AUTH_FAILED, reason="invalid_jwt", path="/api/rides")
        log_security_event(SecurityEvent.AUTH_SESSION_MISMATCH, user_id="abc-123")
    """
    logger.bind(security=True).info({
        "security_event": event,
        "ts": int(time.time()),
        **kwargs,
    })
