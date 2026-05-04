"""
Light‑weight service helpers for the finnova_autopilot app.

This package exposes:

- `create_event_notification`   (used by `analytics_ai.nudges`)
- `log_audit_event` passthrough (used by wallet/finance code)
- `AutomationEngine`            (from `.automation_engine`)
"""

import logging
from typing import Optional

from audit.services import log_audit_event  # re‑exported helper
from notifications.services import NotificationService

from .automation_engine import AutomationEngine

logger = logging.getLogger(__name__)


def create_event_notification(
    user,
    source: str,
    event_type: str,
    severity: str,
    title: str,
    message: str,
    action_hint: Optional[str] = None,
    action_url: Optional[str] = None,
    metadata: Optional[dict] = None,
):
    """
    Generic helper used by AI/autopilot code paths to raise a notification.

    This is intentionally thin and delegates to `NotificationService`
    so it stays consistent with the rest of the notifications system.
    """
    try:
        return NotificationService.create_notification(
            user=user,
            source=source or "AUTOPILOT",
            event_type=event_type or "INFO",
            severity=severity or "INFO",
            title=title,
            message=message,
            action_hint=action_hint,
            action_url=action_url,
            metadata=metadata or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to create event notification: %s", exc, exc_info=True)
        return None


__all__ = [
    "create_event_notification",
    "log_audit_event",
    "AutomationEngine",
]

