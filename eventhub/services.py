"""Event emission helpers.

DomainEvent is the backbone for cross-module side effects.
This helper also writes AuditLog and (optionally) an in-app Notification
so important actions show up consistently across the product.

Design goals:
- Keep imports minimal to avoid cycles
- Never break business flows if audit/notification fails
- Support idempotency via DomainEvent.idempotency_key
"""

from __future__ import annotations

import uuid

from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

from .models import DomainEvent


def emit_event(
    *,
    event_type: str,
    organization=None,
    actor=None,
    metadata: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
    correlation_id=None,
    module: Optional[str] = None,
    severity: Optional[str] = None,
    action_url: Optional[str] = None,
    also_audit: bool = True,
    audit_kwargs: Optional[Dict[str, Any]] = None,
    also_notify: bool = False,
    notify_user=None,
    notify_kwargs: Optional[Dict[str, Any]] = None,
) -> Tuple[DomainEvent, Optional[object], Optional[object]]:
    """Emit a DomainEvent and optionally create AuditLog/Notification."""

    metadata = metadata or {}
    audit_kwargs = audit_kwargs or {}
    notify_kwargs = notify_kwargs or {}

    evt = DomainEvent.objects.create(
        event_type=event_type,
        organization=organization,
        actor=actor,
        module=module or metadata.get("module"),
        severity=severity or metadata.get("severity"),
        action_url=action_url or metadata.get("action_url"),
        metadata=metadata,
        idempotency_key=idempotency_key,
        correlation_id=(correlation_id or metadata.get('correlation_id') or uuid.uuid4()),
    )

    audit_obj = None
    if also_audit:
        try:
            from audit.models import AuditLog  # lazy import

            audit_obj = AuditLog.objects.create(
                organization=organization,
                actor=actor,
                source=audit_kwargs.get('source', 'SYSTEM'),
                action=audit_kwargs.get('action', 'SYSTEM'),
                severity=audit_kwargs.get('severity', 'INFO'),
                description=audit_kwargs.get('description', event_type),
                details=audit_kwargs.get('details', metadata),
                correlation_id=evt.correlation_id,
                is_success=audit_kwargs.get('is_success', True),
                error_message=audit_kwargs.get('error_message'),
                target_model=audit_kwargs.get('target_model'),
                target_id=audit_kwargs.get('target_id'),
                related_transaction=audit_kwargs.get('related_transaction'),
                related_payment=audit_kwargs.get('related_payment'),
                related_alert=audit_kwargs.get('related_alert'),
                metadata=audit_kwargs.get('metadata', {}),
            )
        except Exception:
            # Audit must never break core flows.
            pass

    notif_obj = None
    if also_notify and notify_user is not None:
        try:
            from notifications.models import Notification  # lazy import

            notif_obj = Notification.objects.create(
                user=notify_user,
                organization=organization,
                title=notify_kwargs.get('title', 'Update'),
                message=notify_kwargs.get('message', event_type),
                category=notify_kwargs.get('category', 'SYSTEM'),
                severity=notify_kwargs.get('severity', 'INFO'),
                delivery_method=notify_kwargs.get('delivery_method', 'IN_APP'),
                delivery_status='DELIVERED',
                action_required=notify_kwargs.get('action_required', False),
                action_type=notify_kwargs.get('action_type'),
                action_url=notify_kwargs.get('action_url'),
                action_data=notify_kwargs.get('action_data', {}),
                related_transaction=notify_kwargs.get('related_transaction'),
                related_payment=notify_kwargs.get('related_payment'),
                related_alert=notify_kwargs.get('related_alert'),
                related_insight=notify_kwargs.get('related_insight'),
                metadata=notify_kwargs.get('metadata', {}),
                created_at=timezone.now(),
            )
        except Exception:
            pass

    return evt, audit_obj, notif_obj
