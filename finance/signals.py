# finance/signals.py - CORRECTED & ENHANCED
import contextlib
from datetime import timedelta
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.db import transaction as db_transaction

from finance.notify import notify_large_transaction, notify_transaction_failed
from payments_core.models import PaymentTransaction, PaymentAccount
from .models import Income, Expense, Budget, FinancialGoal, FinancialMetric
from notifications.services import NotificationService, create_notification
import logging

logger = logging.getLogger(__name__)


def detect_unusual_spending(recent_expenses_qs, new_amount):
    """Very lightweight anomaly check.

    We keep this deterministic + fast (no ML required) so it works in SQLite.
    Flags as unusual if the new amount is > 3x the 7-day average, or > 2x the
    max in the last 7 days (when there is history).
    """
    try:
        amounts = list(recent_expenses_qs.values_list('amount', flat=True)[:200])
        if not amounts:
            return False
        avg = sum(amounts) / len(amounts)
        mx = max(amounts)
        return (avg > 0 and new_amount > (avg * 3)) or (mx > 0 and new_amount > (mx * 2))
    except Exception:
        return False

@receiver(post_save, sender=Income)
def create_transaction_for_income(sender, instance, created, **kwargs):
    """Create transaction when income is added with proper validation"""
    if created:
        try:
            # If this income came from a PaymentIntent sync, do NOT create another PaymentTransaction.
            if getattr(instance, 'payment_intent_id', None) or instance.payment_reference:
                return

            # Get or create payment account
            account, account_created = PaymentAccount.objects.get_or_create(
                user=instance.user,
                is_primary=True,
                defaults={
                    'balance': 0,
                    'account_type': 'WALLET',
                    'currency': getattr(instance.account, 'currency', 'INR'),
                    'is_active': True,
                    'account_number': PaymentAccount.generate_account_number()
                }
            )
            
            # Idempotency: avoid duplicates
            ref = f"INC-{instance.id}"
            if PaymentTransaction.objects.filter(reference=ref).exists():
                return

            # Create payment transaction
            PaymentTransaction.objects.create(
                account=account,
                amount=instance.amount,
                transaction_type='CREDIT',
                description=f"Income: {instance.source}",
                category='INCOME',
                status='SUCCESS',
                reference=ref,
                balance_before=account.balance,
                balance_after=account.balance + instance.amount,
                metadata={
                    'income_id': str(instance.id),
                    'source': instance.source
                }
            )
            
            # Update account balance
            account.update_balance(instance.amount)
            
            # Create notification
            create_notification(
                user=instance.user,
                title="Income Recorded",
                message=f"₹{instance.amount} added from {instance.source}",
                notification_type='FINANCE',
                priority='LOW'
            )
            
            # Generate daily metrics
            from .services.finance_engine import FinanceEngine
            FinanceEngine.generate_daily_metrics(instance.user)
            
        except Exception as e:
            logger.error(f"Income transaction creation failed: {str(e)}")
            # Don't fail the save, just log

@receiver(post_save, sender=Expense)
def create_transaction_for_expense(sender, instance, created, **kwargs):
    """Create transaction when expense is added with fraud detection"""
    if not created:
        return
    try:
        # Get primary account
        account = PaymentAccount.objects.get(user=instance.user, is_primary=True)

        # Check for unusual spending (fraud detection)
        recent_expenses = Expense.objects.filter(
            user=instance.user,
            date__gte=timezone.now().date() - timedelta(days=7)
        ).exclude(id=instance.id)

        # If this expense came from a PaymentIntent sync, do NOT create another PaymentTransaction.
        if getattr(instance, 'payment_intent_id', None) or instance.payment_reference:
            return

        if detect_unusual_spending(recent_expenses, instance.amount):
            instance.requires_review = True
            instance.save()

            create_notification(
                user=instance.user,
                title="Unusual Expense Detected",
                message=f"₹{instance.amount} expense flagged for review",
                notification_type='SECURITY',
                priority='HIGH'
            )

        # Idempotency guard
        ref = f"EXP-{instance.id}"
        if PaymentTransaction.objects.filter(reference=ref).exists():
            return

        # Create transaction
        PaymentTransaction.objects.create(
            account=account,
            amount=instance.amount,
            transaction_type='DEBIT',
            description=f"Expense: {instance.description}",
            category=instance.category,
            status='SUCCESS',
            reference=ref,
            balance_before=account.balance,
            balance_after=account.balance - instance.amount,
            metadata={
                'expense_id': str(instance.id),
                'merchant': instance.merchant
            }
        )

        # Update balance
        account.update_balance(-instance.amount)

        # Update budget if exists
        if instance.budget_category:
            instance.budget_category.update_spending()

        # Check all budgets
        from .services.finance_engine import FinanceEngine
        FinanceEngine.update_budget_spending(instance.user)

    except PaymentAccount.DoesNotExist:
        logger.error(f"No primary account found for user {instance.user.username}")
    except Exception as e:
        logger.error(f"Expense transaction creation failed: {str(e)}")

@receiver(pre_save, sender=Budget)
def check_budget_status(sender, instance, **kwargs):
    """Check budget status before saving"""
    if instance.pk:  # Only for updates
        with contextlib.suppress(Budget.DoesNotExist):
            old_instance = Budget.objects.get(pk=instance.pk)

            # If budget amount changed significantly (>20%)
            if abs(old_instance.amount - instance.amount) / old_instance.amount > 0.2:
                create_notification(
                    user=instance.user,
                    title="Budget Amount Changed",
                    message=f"Budget '{instance.name}' amount changed from ₹{old_instance.amount} to ₹{instance.amount}",
                    notification_type='BUDGET',
                    priority='MEDIUM'
                )

@receiver(post_save, sender=FinancialGoal)
def goal_progress_notification(sender, instance, created, **kwargs):
    """Send notifications for goal progress"""
    if not created and instance.progress_percentage >= 50:
        # Send milestone notification
        create_notification(
            user=instance.user,
            title="Goal Progress Update",
            message=f"You're {instance.progress_percentage:.1f}% towards your goal: {instance.name}",
            notification_type='GOAL',
            priority='LOW'
        )
    
    if instance.progress_percentage >= 100 and instance.status == 'ACHIEVED':
        create_notification(
            user=instance.user,
            title="🎉 Goal Achieved!",
            message=f"Congratulations! You've achieved your goal: {instance.name}",
            notification_type='GOAL',
            priority='HIGH'
        )



@receiver(post_save, sender=PaymentTransaction)
def handle_payment_transaction_notification(sender, instance, created, **kwargs):
    """
    Unified notification handler for payment transactions
    """
    if instance.status == 'FAILED':
        notify_transaction_failed(instance)
        
        # Enhanced notification for failures
        NotificationService.create_notification(
            user=instance.account.user,
            source='payments.transaction',
            event_type='FINANCE',
            severity='HIGH',
            title='Transaction Failed',
            message=f'Your transaction of ₹{instance.amount} failed.',
            related_app='payments_core',
            related_model='PaymentTransaction',
            related_id=str(instance.id),
            requires_acknowledgment=True
        )
        return

    # Check for large transactions (created or updated to success)
    if instance.amount > 10000:
        notify_large_transaction(instance, 10000)
        
        NotificationService.create_notification(
            user=instance.account.user,
            source='payments.transaction',
            event_type='FINANCE',
            severity='HIGH',
            title=f'Large Transaction: ₹{instance.amount}',
            message=f'A large transaction of ₹{instance.amount} was processed.',
            related_app='payments_core',
            related_model='PaymentTransaction',
            related_id=str(instance.id),
            action_hint='Review transaction'
        )