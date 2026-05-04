"""Agency signals.

Keeps receivables (Invoices) consistent with Payments.

Rule:
- If a PaymentIntent succeeds and its metadata contains an invoice_id, we mark
  that invoice as PAID (idempotent).

This makes "Pay invoice" links behave like a real B2B flow:
Invoice -> PaymentIntent -> PaymentTransaction ledger -> Invoice PAID
"""

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from payments_core.models import PaymentIntent

from .models import Invoice

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=PaymentIntent)
def _capture_old_status(sender, instance: PaymentIntent, **kwargs):
    if not instance.pk:
        instance._old_status_for_agency = None
        return
    try:
        instance._old_status_for_agency = PaymentIntent.objects.only('status').get(pk=instance.pk).status
    except PaymentIntent.DoesNotExist:
        instance._old_status_for_agency = None


@receiver(post_save, sender=PaymentIntent)
def sync_invoice_on_payment_success(sender, instance: PaymentIntent, **kwargs):
    """Mark linked invoice as PAID when the payment succeeds."""
    try:
        old_status = getattr(instance, '_old_status_for_agency', None)
        if instance.status != 'SUCCESS' or old_status == 'SUCCESS':
            return

        invoice_id = (instance.metadata or {}).get('invoice_id')
        if not invoice_id:
            return

        try:
            inv = Invoice.objects.select_for_update().get(id=invoice_id, organization=instance.organization)
        except Invoice.DoesNotExist:
            return

        # Idempotent: if already paid, just link the payment intent for receipts.
        if inv.status != Invoice.STATUS_PAID:
            inv.status = Invoice.STATUS_PAID
            inv.paid_date = timezone.now().date()

        inv.payment_intent = instance
        inv.payment_reference = instance.reference_id
        inv.save(update_fields=['status', 'paid_date', 'payment_intent', 'payment_reference', 'updated_at'])

    except Exception:
        logger.exception('Failed to sync invoice from payment intent')
