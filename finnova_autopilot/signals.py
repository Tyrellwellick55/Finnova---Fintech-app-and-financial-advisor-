"""Signals for Finnova Autopilot."""

import logging
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction as db_transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from analytics_ai.fraud_ai import detect_fraud
from finance.models import Expense, Income
from notifications.services import NotificationService
from payments_core.models import PaymentAccount, PaymentTransaction

from .models import (
    Alert,
    ApprovalRequest,
    AutopilotProfile,
    FinancialHealthScore,
    FraudEvent,
    SmartBill,
)

User = get_user_model()
logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def create_wallet_and_profile(sender, instance, created, **kwargs):
    if not created:
        return

    try:
        PaymentAccount.objects.get_or_create(
            user=instance,
            is_primary=True,
            defaults={
                "balance": Decimal("1000.00"),
                "available_balance": Decimal("1000.00"),
                "account_type": "WALLET",
                "currency": "INR",
                "account_number": PaymentAccount.generate_account_number(),
                "is_active": True,
            },
        )
        AutopilotProfile.resolve_for_user(
            instance,
            defaults={
                "is_active": True,
                "risk_tolerance": "MODERATE",
                "auto_pay_bills": True,
                "auto_transfer_to_savings": True,
                "fraud_detection_enabled": True,
            },
        )
        FinancialHealthScore.objects.get_or_create(
            user=instance,
            defaults={
                "overall_score": 500,
                "grade": "C",
                "components": {},
                "trend": "STABLE",
            },
        )
    except Exception:
        logger.exception("Error creating Autopilot defaults for user %s", instance.username)


@receiver(post_save, sender=Income)
def create_income_transaction(sender, instance, created, **kwargs):
    from django.conf import settings

    if not created or not getattr(settings, "AUTOPILOT_CREATE_TRANSACTIONS_FROM_FINANCE", False):
        return

    try:
        account = PaymentAccount.objects.get(user=instance.user, is_primary=True)
        PaymentTransaction.objects.create(
            account=account,
            amount=instance.amount,
            transaction_type="CREDIT",
            description=f"Income: {instance.source}",
            status="SUCCESS",
            reference=f"INC-{instance.id}",
            balance_before=account.balance,
            balance_after=account.balance + instance.amount,
            metadata={"income_id": str(instance.id), "source": instance.source},
        )
        account.update_balance(instance.amount)
        NotificationService.create_notification(
            user=instance.user,
            source="finnovaautopilot.income",
            event_type="INCOME_RECEIVED",
            title="Income Received",
            message=f"Income of Rs. {instance.amount} received from {instance.source}.",
            severity="INFO",
            action_hint="View transaction details",
            action_url="/finance/transactions/",
            metadata={"income_id": str(instance.id)},
        )
    except PaymentAccount.DoesNotExist:
        logger.error("No payment account found for income user %s", instance.user.username)
    except Exception:
        logger.exception("Error creating income transaction for %s", instance.id)


@receiver(post_save, sender=Expense)
def create_expense_transaction(sender, instance, created, **kwargs):
    from django.conf import settings

    if not created or not getattr(settings, "AUTOPILOT_CREATE_TRANSACTIONS_FROM_FINANCE", False):
        return

    try:
        account = PaymentAccount.objects.get(user=instance.user, is_primary=True)
        PaymentTransaction.objects.create(
            account=account,
            amount=instance.amount,
            transaction_type="DEBIT",
            description=f"Expense: {instance.description}",
            status="SUCCESS",
            reference=f"EXP-{instance.id}",
            balance_before=account.balance,
            balance_after=account.balance - instance.amount,
            metadata={"expense_id": str(instance.id), "category": instance.category},
        )
        account.update_balance(-instance.amount)
    except PaymentAccount.DoesNotExist:
        logger.error("No payment account found for expense user %s", instance.user.username)
    except Exception:
        logger.exception("Error creating expense transaction for %s", instance.id)


@receiver(post_save, sender=PaymentTransaction)
def handle_transaction(sender, instance, created, **kwargs):
    if not created or instance.status != "SUCCESS" or not instance.account:
        return

    account = instance.account
    if not account.is_active:
        instance.status = "FAILED"
        metadata = instance.metadata or {}
        metadata["failure_reason"] = "Account is inactive"
        instance.metadata = metadata
        instance.save(update_fields=["status", "metadata"])
        return

    try:
        if instance.transaction_type == "DEBIT":
            try:
                fraud_result = detect_fraud(instance.account.user, instance)
                if fraud_result and fraud_result.get("risk") in {"HIGH", "CRITICAL"}:
                    FraudEvent.objects.create(
                        user=instance.account.user,
                        transaction_id=str(instance.id),
                        risk_level=fraud_result.get("risk", "MEDIUM"),
                        reason=fraud_result.get("reason", "Suspicious activity detected"),
                        auto_action=fraud_result.get("action", "PAUSE"),
                        metadata=fraud_result.get("details", {}),
                    )
                    if fraud_result.get("action") in {"PAUSE", "FREEZE"}:
                        account.is_active = False
                        account.save(update_fields=["is_active"])
                    NotificationService.create_notification(
                        user=instance.account.user,
                        source="analytics_ai.fraud",
                        event_type="SECURITY",
                        title="Suspicious Activity Detected",
                        message=fraud_result.get("reason", "Unusual transaction detected"),
                        severity="CRITICAL",
                        requires_acknowledgment=True,
                        action_hint="Review transaction",
                    )
            except Exception:
                logger.exception("Fraud detection error for transaction %s", instance.id)
    except Exception:
        logger.exception("Error processing payment transaction %s", instance.id)


@receiver(pre_save, sender=SmartBill)
def update_bill_status(sender, instance, **kwargs):
    today = timezone.localdate()
    if instance.due_date < today and instance.status == "PENDING":
        instance.status = "OVERDUE"


@receiver(post_save, sender=SmartBill)
def schedule_bill_payment(sender, instance, created, **kwargs):
    if not created or not instance.auto_pay or instance.status != "PENDING":
        return
    try:
        days_until_due = (instance.due_date - timezone.localdate()).days
        if 0 <= days_until_due <= instance.auto_pay_days_before:
            logger.info("Bill %s is ready for approval review on %s", instance.id, instance.due_date)
    except Exception:
        logger.exception("Error scheduling bill review for %s", instance.id)


def process_due_bills():
    """Queue due bills for manual approval instead of paying them automatically."""
    today = timezone.localdate()
    due_bills = SmartBill.objects.filter(
        due_date__lte=today,
        status__in=["PENDING", "OVERDUE"],
        auto_pay=True,
    ).select_related("user", "organization")

    results = {"queued": 0, "blocked": 0, "skipped": 0, "failed": 0}

    for bill in due_bills:
        user = bill.user
        account = (
            PaymentAccount.objects.filter(user=user, is_primary=True, is_active=True).first()
            or PaymentAccount.objects.filter(user=user, is_primary=True).first()
            or PaymentAccount.objects.filter(user=user, is_active=True).first()
            or PaymentAccount.objects.filter(user=user).first()
        )
        profile, _ = AutopilotProfile.resolve_for_user(user, organization=getattr(bill, "organization", None))

        if not profile or not profile.is_active:
            results["skipped"] += 1
            continue
        if not account or not account.is_active:
            results["blocked"] += 1
            continue

        try:
            with db_transaction.atomic():
                if bill.due_date < today and bill.status == "PENDING":
                    bill.status = "OVERDUE"
                    bill.save(update_fields=["status", "updated_at"])

                if account.available_balance < bill.amount:
                    Alert.objects.get_or_create(
                        user=user,
                        title=f"Insufficient balance: {bill.biller_name}",
                        message=f"Autopilot cannot queue payment for {bill.biller_name} because available balance is below Rs. {bill.amount}.",
                        category="PAYMENT",
                        severity="HIGH",
                        source="AUTOPILOT",
                        defaults={
                            "action_required": True,
                            "action_url": "/autopilot/bills/",
                            "related_bill": bill,
                        },
                    )
                    results["blocked"] += 1
                    continue

                approval, created = ApprovalRequest.objects.get_or_create(
                    user=user,
                    organization=getattr(bill, "organization", None),
                    bill=bill,
                    status="PENDING",
                    defaults={
                        "request_type": "BILL_PAYMENT",
                        "title": f"Pay bill: {bill.biller_name}",
                        "description": f"Due {bill.due_date}. Category: {bill.biller_category}",
                        "amount": bill.amount,
                        "why": "Bill is due now and Finnova requires visible approval before execution.",
                        "metadata": {
                            "biller": bill.biller_name,
                            "due_date": str(bill.due_date),
                            "category": bill.biller_category,
                        },
                    },
                )
                if not created:
                    results["skipped"] += 1
                    continue

                Alert.objects.create(
                    user=user,
                    title=f"Bill ready for approval: {bill.biller_name}",
                    message=f"Review and approve payment of Rs. {bill.amount} for {bill.biller_name}.",
                    category="PAYMENT",
                    severity="MEDIUM",
                    source="AUTOPILOT",
                    action_required=True,
                    action_url="/autopilot/approvals/",
                    related_bill=bill,
                )
                NotificationService.create_notification(
                    user=user,
                    source="finnova_autopilot.bill",
                    event_type="FINANCE",
                    title="Bill Approval Requested",
                    message=f"Review bill payment for {bill.biller_name} (Rs. {bill.amount}).",
                    severity="INFO",
                    action_hint="Review approvals",
                    action_url="/autopilot/approvals/",
                )
                results["queued"] += 1
        except Exception:
            logger.exception("Error queuing approval for bill %s", bill.id)
            results["failed"] += 1

    return results


def ready():
    """Import this module in apps.py ready()."""
    return None


# ── Income split trigger — fires when any Income record is created ─────────────
@receiver(post_save, sender=Income)
def trigger_income_split_plan(sender, instance, created, **kwargs):
    """When income arrives, Autopilot immediately builds a money plan and creates
    an ApprovalRequest for the user to review."""
    if not created:
        return
    try:
        from finnovaapp.utils import _active_org
        from .product_views import _build_income_split_plan
        from .models import ApprovalRequest, AutopilotProfile

        user = instance.user
        org  = getattr(instance, 'organization', None)

        profile, _ = AutopilotProfile.resolve_for_user(user, organization=org)
        if not profile or not profile.is_active:
            return

        plan_data = _build_income_split_plan(instance, user, org)

        approval, created_approval = ApprovalRequest.objects.get_or_create(
            user=user,
            organization=org,
            request_type='INCOME_SPLIT',
            status='PENDING',
            defaults={
                'title': f'Income plan — ₹{instance.amount:,.0f}',
                'description': (
                    f'Autopilot has built a money plan for ₹{instance.amount:,.0f} '
                    f'from {getattr(instance, "source", "") or instance.description or "income"}.'
                ),
                'amount': instance.amount,
                'metadata': {
                    **plan_data,
                    'income_id': str(instance.id),
                    'source_label': getattr(instance, 'source', '') or instance.description or '',
                },
            },
        )

        if created_approval:
            NotificationService.create_notification(
                user=user,
                source='finnova_autopilot.income',
                event_type='FINANCE',
                title='Income received — plan ready',
                message=(
                    f'₹{instance.amount:,.0f} has arrived. '
                    f'Autopilot has built your money plan. Spendable: ₹{plan_data.get("spendable", 0):,.0f}.'
                ),
                severity='INFO',
                action_hint='Review and approve',
                action_url=f'/autopilot/income/{approval.id}/split/',
            )
            logger.info(
                'Income split plan created for user %s — ₹%s',
                user.username, instance.amount
            )
    except Exception:
        logger.exception('income_split trigger failed for income %s', instance.id)
