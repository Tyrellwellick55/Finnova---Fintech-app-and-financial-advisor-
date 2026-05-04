"""payments_core signals.

These signals handle side-effects for PaymentIntent status transitions.

Key goals:
- Idempotent processing (avoid double-debits / duplicate transactions)
- Correctly detect status changes (pre_save captures old status)
"""

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from decimal import Decimal
import logging

from .models import PaymentIntent, PaymentAccount, PaymentTransaction
from eventhub.dispatcher import emit

logger = logging.getLogger(__name__)

@receiver(pre_save, sender=PaymentIntent)
def _capture_old_status(sender, instance, **kwargs):
    """Capture previous status so post_save can reliably detect transitions."""
    if not instance.pk:
        instance._old_status = None
        return
    try:
        instance._old_status = PaymentIntent.objects.only('status').get(pk=instance.pk).status
    except PaymentIntent.DoesNotExist:
        instance._old_status = None


@receiver(post_save, sender=PaymentIntent)
def process_payment(sender, instance, created=False, **kwargs):
    """Process side-effects when PaymentIntent transitions to SUCCESS."""
    try:
        old_status = getattr(instance, '_old_status', None)
        if instance.status != 'SUCCESS' or old_status == 'SUCCESS':
            return

        # Idempotency: if a transaction already exists for this intent, do nothing
        if PaymentTransaction.objects.filter(payment_intent=instance).exists():
            return

        account = instance.account
        amount = Decimal(instance.amount)

        # Determine debit/credit
        debit_methods = {'CARD', 'UPI', 'NETBANKING', 'BANK_TRANSFER', 'WALLET', 'CASH'}
        credit_methods = {'REFUND', 'TOPUP', 'DEPOSIT'}

        if instance.payment_method in debit_methods:
            balance_before = account.balance
            account.update_balance(-amount)
            balance_after = account.balance

            PaymentTransaction.objects.create(
                account=account,
                organization=instance.organization,
                payment_intent=instance,
                transaction_type='DEBIT',
                status='SUCCESS',
                amount=amount,
                description=instance.description or f"{instance.payment_method} Payment",
                reference=f"PAY-{instance.reference_id}",
                balance_before=balance_before,
                balance_after=balance_after,
                category=instance.metadata.get('category'),
                merchant=instance.metadata.get('merchant'),
                metadata=instance.metadata,
            )

        elif instance.payment_method in credit_methods:
            balance_before = account.balance
            account.update_balance(amount)
            balance_after = account.balance

            PaymentTransaction.objects.create(
                account=account,
                organization=instance.organization,
                payment_intent=instance,
                transaction_type='CREDIT',
                status='SUCCESS',
                amount=amount,
                description=instance.description or f"{instance.payment_method}",
                reference=f"CR-{instance.reference_id}",
                balance_before=balance_before,
                balance_after=balance_after,
                category=instance.metadata.get('category'),
                merchant=instance.metadata.get('merchant'),
                metadata=instance.metadata,
            )

        logger.info(f"Processed payment intent {instance.reference_id} for account {account.account_number}")

        # Emit standardized domain event (cross-module backbone)
        try:
            action_url = None
            try:
                action_url = reverse('payments:download_receipt', args=[instance.reference_id])
            except Exception:
                action_url = None

            emit(
                'PAYMENT_SUCCEEDED',
                actor=instance.user,
                organization=instance.organization,
                idempotency_key=f"payment:{instance.id}:SUCCESS",
                metadata={
                    'payment_intent_id': str(instance.id),
                    'reference_id': instance.reference_id,
                    'payment_reference': instance.reference_id,
                    'amount': float(instance.amount),
                    'payment_method': instance.payment_method,
                    'gateway': instance.gateway,
                    'description': instance.description,
                    'status': instance.status,
                    'invoice_id': (instance.metadata or {}).get('invoice_id'),
                    'action_url': action_url,
                },
            )
        except Exception:
            logger.debug('EventHub emit failed for PAYMENT_SUCCEEDED', exc_info=True)

    except Exception as e:
        logger.error(f"Error processing payment intent {instance.reference_id}: {str(e)}")

@receiver(post_save, sender=PaymentIntent)
def payment_status_events(sender, instance, **kwargs):
    """Emit standardized status-change events.

    Notifications/audit/analytics should subscribe to EventHub events, not raw model transitions.
    """
    try:
        old_status = getattr(instance, '_old_status', None)
        if old_status is None or old_status == instance.status:
            return

        event_map = {
            'PROCESSING': 'PAYMENT_INITIATED',
            'SUCCESS': 'PAYMENT_SUCCEEDED',
            'FAILED': 'PAYMENT_FAILED',
            'REFUNDED': 'PAYMENT_REFUNDED',
        }
        ev_type = event_map.get(instance.status)
        if not ev_type:
            return

        emit(
            ev_type,
            actor=instance.user,
            organization=instance.organization,
            idempotency_key=f"payment:{instance.id}:{instance.status}",
            metadata={
                'payment_intent_id': str(instance.id),
                'reference_id': instance.reference_id,
                'amount': float(instance.amount),
                'payment_method': instance.payment_method,
                'gateway': instance.gateway,
                'description': instance.description,
                'old_status': old_status,
                'new_status': instance.status,
                'error': instance.error_message,
            },
        )

    except Exception as e:
        logger.error(f"Error emitting payment status event: {str(e)}")