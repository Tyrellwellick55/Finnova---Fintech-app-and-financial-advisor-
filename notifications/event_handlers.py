"""Notification event handlers for the EventHub backbone."""

import logging
from decimal import Decimal

from eventhub.dispatcher import subscribe

logger = logging.getLogger(__name__)


def _safe_money(value) -> str:
    try:
        return f"₹{Decimal(str(value)):,.2f}"
    except Exception:
        return f"₹{value}"


def _notify_payment_succeeded(ev):
    try:
        from notifications.services import NotificationService

        meta = ev.metadata or {}
        amount = _safe_money(meta.get('amount'))
        ref = meta.get('reference_id') or meta.get('payment_reference')

        NotificationService.create_notification(
            user=ev.actor,
            organization=ev.organization,
            source='eventhub',
            event_type='PAYMENT_SUCCEEDED',
            severity='INFO',
            title='Payment successful',
            message=f"{amount} payment completed{f' (Ref: {ref})' if ref else ''}.",
            related_app='payments_core',
            related_model='PaymentIntent',
            related_id=str(meta.get('payment_intent_id') or ''),
            action_hint='View payment details',
            action_url=meta.get('action_url'),
            metadata=meta,
        )
    except Exception:
        logger.exception('Failed to create notification for payment success')


def _notify_payment_failed(ev):
    try:
        from notifications.services import NotificationService

        meta = ev.metadata or {}
        amount = _safe_money(meta.get('amount'))
        reason = meta.get('error') or meta.get('reason') or 'Payment failed'

        NotificationService.create_notification(
            user=ev.actor,
            organization=ev.organization,
            source='eventhub',
            event_type='PAYMENT_FAILED',
            severity='HIGH',
            title='Payment failed',
            message=f"{amount} payment failed: {reason}",
            related_app='payments_core',
            related_model='PaymentIntent',
            related_id=str(meta.get('payment_intent_id') or ''),
            action_hint='Try again',
            action_url=meta.get('action_url'),
            metadata=meta,
            requires_acknowledgment=False,
        )
    except Exception:
        logger.exception('Failed to create notification for payment failure')


def _notify_autopilot_approval(ev):
    try:
        from notifications.services import NotificationService

        meta = ev.metadata or {}
        amount = _safe_money(meta.get('amount'))
        title = 'Autopilot approval needed'
        msg = f"Autopilot recommends paying {meta.get('label','a bill')} for {amount}."
        if meta.get('why'):
            msg += f" Reason: {meta['why']}"

        NotificationService.create_notification(
            user=ev.actor,
            organization=ev.organization,
            source='eventhub',
            event_type='AUTOPILOT_APPROVAL_REQUESTED',
            severity='MEDIUM',
            title=title,
            message=msg,
            related_app='finnova_autopilot',
            related_model='ApprovalRequest',
            related_id=str(meta.get('approval_id') or ''),
            action_hint='Review approvals',
            action_url=meta.get('action_url'),
            requires_acknowledgment=True,
            metadata=meta,
        )
    except Exception:
        logger.exception('Failed to create notification for autopilot approval')




def _notify_invoice_created(ev):
    try:
        from notifications.services import NotificationService

        meta = ev.metadata or {}
        amount = _safe_money(meta.get('amount'))
        inv = meta.get('invoice_number') or 'invoice'
        client = meta.get('client_name') or 'client'

        NotificationService.create_notification(
            user=ev.actor,
            organization=ev.organization,
            source='eventhub',
            event_type='AGENCY_INVOICE_CREATED',
            severity='INFO',
            title='Invoice created',
            message=f"{inv} created for {client} • Amount {amount}.",
            related_app='agency',
            related_model='Invoice',
            related_id=str(meta.get('invoice_id') or ''),
            action_hint='View receivables',
            action_url=meta.get('action_url'),
            metadata=meta,
        )
    except Exception:
        logger.exception('Failed to create notification for invoice creation')


def _notify_invoice_paid(ev):
    try:
        from notifications.services import NotificationService

        meta = ev.metadata or {}
        amount = _safe_money(meta.get('amount'))
        inv = meta.get('invoice_number') or 'invoice'
        client = meta.get('client_name') or 'client'

        NotificationService.create_notification(
            user=ev.actor,
            organization=ev.organization,
            source='eventhub',
            event_type='AGENCY_INVOICE_PAID',
            severity='INFO',
            title='Invoice paid',
            message=f"{inv} marked as PAID for {client} • Amount {amount}.",
            related_app='agency',
            related_model='Invoice',
            related_id=str(meta.get('invoice_id') or ''),
            action_hint='View receivables',
            action_url=meta.get('action_url'),
            metadata=meta,
        )
    except Exception:
        logger.exception('Failed to create notification for invoice paid')


subscribe('AGENCY_INVOICE_CREATED', _notify_invoice_created)
subscribe('AGENCY_INVOICE_PAID', _notify_invoice_paid)

subscribe('PAYMENT_SUCCEEDED', _notify_payment_succeeded)
subscribe('PAYMENT_FAILED', _notify_payment_failed)
subscribe('AUTOPILOT_APPROVAL_REQUESTED', _notify_autopilot_approval)
