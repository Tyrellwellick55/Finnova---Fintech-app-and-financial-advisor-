"""Agency EventHub handlers.

Goal: keep Agency invoices consistent with payments.

If a payment succeeds and its metadata references an invoice, we automatically:
- mark the invoice as PAID (idempotent)
- post Income into finance (idempotent)
- emit AGENCY_INVOICE_PAID so UI feeds/notifications stay consistent
"""

from __future__ import annotations

import logging

from eventhub.dispatcher import subscribe, emit

logger = logging.getLogger(__name__)


def _invoice_from_payment_metadata(meta):
    invoice_id = meta.get('invoice_id')
    if not invoice_id:
        return None
    try:
        from agency.models import Invoice

        return Invoice.objects.filter(id=invoice_id).select_related('client').first()
    except Exception:
        return None


def _sync_payment_succeeded_to_invoice(ev):
    """On PAYMENT_SUCCEEDED, mark invoice paid if the payment references one."""
    try:
        meta = ev.metadata or {}

        # Try resolve invoice
        invoice = _invoice_from_payment_metadata(meta)

        if invoice is None and meta.get('payment_intent_id'):
            # Fallback: PaymentIntent linked to invoice via FK
            try:
                from payments_core.models import PaymentIntent
                from agency.models import Invoice

                intent = PaymentIntent.objects.filter(id=meta.get('payment_intent_id')).first()
                if intent:
                    invoice = Invoice.objects.filter(payment_intent=intent).select_related('client').first()
            except Exception:
                invoice = None

        if invoice is None:
            return

        if invoice.status == invoice.STATUS_PAID:
            return

        # Mark invoice paid
        payment_ref = meta.get('reference_id') or meta.get('payment_reference')
        invoice.mark_paid(reference=payment_ref)

        # Post income to finance ledger (idempotent)
        try:
            from finance.services.posting import post_income

            post_income(
                organization=invoice.organization,
                user=ev.actor or invoice.created_by,
                amount=invoice.amount,
                source='Agency Invoice Payment',
                category='BUSINESS',
                memo=f"Invoice paid: {invoice.invoice_number}",
                payment_reference=payment_ref,
            )
        except Exception:
            logger.debug('Finance auto-post income failed for invoice', exc_info=True)

        # Emit invoice paid event (idempotent)
        try:
            emit(
                'AGENCY_INVOICE_PAID',
                actor=ev.actor,
                organization=invoice.organization,
                idempotency_key=f"agency:invoice_paid:{invoice.id}:{payment_ref}",
                metadata={
                    'invoice_id': str(invoice.id),
                    'invoice_number': invoice.invoice_number,
                    'client_name': (invoice.client.company_name or invoice.client.name),
                    'amount': str(invoice.amount),
                    'payment_reference': payment_ref,
                    'description': f"Invoice paid: {invoice.invoice_number}",
                },
            )
        except Exception:
            logger.debug('EventHub emit failed for AGENCY_INVOICE_PAID', exc_info=True)

    except Exception:
        logger.exception('Agency handler failed for PAYMENT_SUCCEEDED')


subscribe('PAYMENT_SUCCEEDED', _sync_payment_succeeded_to_invoice)
