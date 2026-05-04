"""Audit event handlers for the EventHub backbone."""

import logging

from eventhub.dispatcher import subscribe

logger = logging.getLogger(__name__)


def _severity_for_event(event_type: str) -> str:
    if event_type in {'PAYMENT_FAILED', 'ANOMALY_DETECTED'}:
        return 'HIGH'
    if event_type in {'PAYMENT_REFUNDED', 'AUTOPILOT_APPROVAL_REQUESTED'}:
        return 'MEDIUM'
    return 'LOW'


def _log_event(ev):
    """Persist a DomainEvent into AuditLog (best-effort)."""
    try:
        from audit.models import AuditLog

        AuditLog.objects.create(
            organization=ev.organization,
            actor=ev.actor,
            action=ev.event_type,
            description=(ev.metadata or {}).get('description')
            or f"{ev.event_type}",
            severity=_severity_for_event(ev.event_type),
            source='EVENTHUB',
            correlation_id=ev.correlation_id,
            metadata=ev.metadata or {},
        )
    except Exception as e:
        logger.exception("Failed to write AuditLog for DomainEvent", extra={"event_id": str(ev.id)})
        # Do not raise: audit logging must never break the product.


for _t in [
    'PAYMENT_INITIATED',
    'PAYMENT_SUCCEEDED',
    'PAYMENT_FAILED',
    'PAYMENT_REFUNDED',
    'AUTOPILOT_APPROVAL_REQUESTED',
    'AUTOPILOT_EXECUTED',
    'ANOMALY_DETECTED',
    'AGENCY_CLIENT_CREATED',
    'AGENCY_PROJECT_CREATED',
    'AGENCY_INVOICE_CREATED',
    'AGENCY_INVOICE_PAID',
]:
    subscribe(_t, _log_event)
