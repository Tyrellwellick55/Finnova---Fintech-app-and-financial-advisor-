from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from finance.models import Expense, Income
from payments_core.models import PaymentAccount

from ..models import (
    Alert,
    ApprovalRequest,
    AutopilotProfile,
    AutomationRule,
    FinancialHealthScore,
    SavingsGoal,
    SmartBill,
    TransactionPattern,
)
from .ai_advisor import AIAdvisor
from notifications.services import NotificationService

logger = logging.getLogger(__name__)


class AutomationEngine:
    """Focused Autopilot engine for safe, reviewable guidance."""

    @staticmethod
    def _payment_account(user):
        return (
            PaymentAccount.objects.filter(user=user, is_primary=True, is_active=True).first()
            or PaymentAccount.objects.filter(user=user, is_primary=True).first()
            or PaymentAccount.objects.filter(user=user, is_active=True).first()
            or PaymentAccount.objects.filter(user=user).first()
        )

    @staticmethod
    def _create_alert(
        user,
        *,
        title,
        message,
        category,
        severity,
        source="AUTOPILOT",
        action_required=False,
        action_url="",
        related_bill=None,
        action_data=None,
    ):
        defaults = {
            "action_required": action_required,
            "action_url": action_url or None,
            "related_bill": related_bill,
            "action_data": action_data or {},
        }
        alert, created = Alert.objects.get_or_create(
            user=user,
            title=title,
            message=message,
            category=category,
            severity=severity,
            source=source,
            is_read=False,
            defaults=defaults,
        )
        
        # Also create a central notification
        try:
            NotificationService.create_notification(
                user=user,
                source=source,
                event_type=category,
                severity=severity if severity in ['INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL'] else 'INFO',
                title=title,
                message=message,
                action_url=action_url,
                related_app='autopilot',
                related_model='Alert',
                related_id=str(alert.id),
                metadata={'alert_id': str(alert.id)}
            )
        except Exception:
            logger.exception("Failed to create linked notification for autopilot alert")

        return alert

    @classmethod
    def run_daily_automation(cls, user):
        profile, _ = AutopilotProfile.resolve_for_user(user)
        results = {
            "bill_payments": cls.process_bill_payments(user),
            "savings_transfers": cls.process_savings_transfers(user),
            "investment_checks": cls.check_investment_opportunities(user),
            "alerts_generated": cls.generate_alerts(user),
            "patterns_detected": cls.detect_patterns(user),
            "health_score_updated": bool(cls.update_financial_health(user)),
        }
        profile.last_run = timezone.now()
        profile.save(update_fields=["last_run", "updated_at"])
        return results

    @classmethod
    def process_bill_payments(cls, user):
        """Queue due bills for approval instead of executing hidden payments."""
        profile, _ = AutopilotProfile.resolve_for_user(user)
        cutoff = timezone.localdate() + timedelta(days=profile.auto_pay_days_before)
        bills = SmartBill.objects.filter(
            user=user,
            status="PENDING",
            due_date__lte=cutoff,
            auto_pay=True,
        ).select_related("payment_reference", "organization")

        queued = []
        total_amount = Decimal("0.00")
        account = cls._payment_account(user)

        for bill in bills:
            try:
                with transaction.atomic():
                    if bill.payment_reference_id or bill.status == "PAID":
                        continue

                    if bill.amount > profile.max_autopay_amount:
                        cls._create_alert(
                            user,
                            title="Autopay paused (amount too high)",
                            message=(
                                f"Autopilot will not queue Rs. {bill.amount} for {bill.biller_name} "
                                f"because the configured cap is Rs. {profile.max_autopay_amount}."
                            ),
                            category="PAYMENT",
                            severity="MEDIUM",
                            action_required=True,
                            action_url="/autopilot/bills/",
                            related_bill=bill,
                        )
                        continue

                    if account is None or account.available_balance < bill.amount:
                        cls._create_alert(
                            user,
                            title=f"Insufficient balance: {bill.biller_name}",
                            message=(
                                f"Autopilot cannot queue payment for {bill.biller_name} because "
                                f"available balance is below Rs. {bill.amount}."
                            ),
                            category="PAYMENT",
                            severity="HIGH",
                            action_required=True,
                            action_url="/autopilot/bills/",
                            related_bill=bill,
                        )
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
                            "why": (
                                f"Due in {profile.auto_pay_days_before} days, balance is sufficient, "
                                "and Finnova requires a visible approval before execution."
                            ),
                            "metadata": {
                                "biller": bill.biller_name,
                                "due_date": str(bill.due_date),
                                "category": bill.biller_category,
                            },
                        },
                    )
                    if not created:
                        continue

                    cls._create_alert(
                        user,
                        title=f"Bill ready for approval: {bill.biller_name}",
                        message=f"Review and approve payment of Rs. {bill.amount} for {bill.biller_name}.",
                        category="PAYMENT",
                        severity="MEDIUM",
                        action_required=True,
                        action_url="/autopilot/approvals/",
                        related_bill=bill,
                    )
                    queued.append(
                        {
                            "bill_id": str(bill.id),
                            "biller_name": bill.biller_name,
                            "amount": float(bill.amount),
                            "approval_id": str(approval.id),
                        }
                    )
                    total_amount += bill.amount
            except Exception:
                logger.exception("Failed queuing bill approval for %s", bill.id)

        return {"paid_count": 0, "approval_count": len(queued), "total_amount": total_amount, "approvals": queued}

    @classmethod
    def auto_pay_bills(cls, user):
        """Compatibility wrapper used by payments flows."""
        return cls.process_bill_payments(user).get("approvals", [])

    @classmethod
    def process_savings_transfers(cls, user):
        """Create savings recommendations instead of moving money silently."""
        rules = AutomationRule.objects.filter(user=user, rule_type__in=["SAVINGS_TRANSFER", "SAVINGS"], is_active=True)
        recommendations = []
        total_amount = Decimal("0.00")

        for rule in rules:
            try:
                if not cls.check_rule_trigger(rule):
                    continue
                amount = cls.calculate_transfer_amount(rule, user)
                if amount <= 0:
                    continue

                goal = SavingsGoal.objects.filter(user=user, status="ACTIVE").order_by("priority", "target_date").first()
                goal_name = goal.goal_name if goal else "your savings plan"
                cls._create_alert(
                    user,
                    title=f"Savings review: {rule.name}",
                    message=f"Review moving Rs. {amount} toward {goal_name}.",
                    category="SAVINGS",
                    severity="INFO",
                    action_required=True,
                    action_url="/autopilot/savings/",
                    action_data={
                        "rule_id": str(rule.id),
                        "goal_id": str(goal.id) if goal else "",
                        "amount": float(amount),
                    },
                )
                recommendations.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "saved_amount": float(amount),
                    }
                )
                total_amount += amount
                rule.execution_count += 1
                rule.last_executed = timezone.now()
                rule.save(update_fields=["execution_count", "last_executed"])
            except Exception:
                logger.exception("Failed creating savings recommendation for rule %s", rule.id)

        return {"suggested_count": len(recommendations), "total_amount": total_amount, "results": recommendations}

    @classmethod
    def execute_savings_rules(cls, user):
        """Compatibility wrapper used by payments flows."""
        result = cls.process_savings_transfers(user)
        return {"saved": False, "amount": float(result["total_amount"]), "results": result["results"]}

    @classmethod
    def check_rule_trigger(cls, rule):
        now = timezone.now()
        schedule_type = getattr(rule, "schedule_type", "IMMEDIATE")
        schedule_value = getattr(rule, "schedule_value", {}) or {}

        if schedule_type == "IMMEDIATE":
            return True
        if schedule_type in {"SCHEDULED", "RECURRING"}:
            schedule = str(schedule_value.get("schedule") or schedule_value.get("frequency") or "MONTHLY").upper()
            if schedule == "MONTHLY":
                return now.day == 1
            if schedule == "WEEKLY":
                return now.weekday() == 0
        if getattr(rule, "rule_type", "") == "INCOME":
            return Income.objects.filter(user=rule.user, date=now.date()).exists()
        return SmartBill.objects.filter(user=rule.user, status="PENDING", due_date__lte=now.date() + timedelta(days=3)).exists()

    @classmethod
    def calculate_transfer_amount(cls, rule, user):
        action_value = getattr(rule, "action_value", {}) or {}
        condition_value = getattr(rule, "condition_value", {}) or {}

        def to_decimal(value, default="0.00"):
            try:
                return Decimal(str(value))
            except Exception:
                return Decimal(default)

        amount_type = action_value.get("amount_type") or condition_value.get("amount_type") or "FIXED"
        if amount_type == "FIXED":
            return to_decimal(action_value.get("amount") or condition_value.get("amount") or 0)
        if amount_type == "PERCENTAGE":
            today = timezone.localdate()
            month_start = today.replace(day=1)
            monthly_income = Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            monthly_income = monthly_income or Decimal("0.00")
            percentage = to_decimal(str(action_value.get("percentage") or condition_value.get("percentage") or "0").replace("%", ""), "0")
            return (monthly_income * percentage) / Decimal("100")
        if amount_type == "REMAINING":
            today = timezone.localdate()
            month_start = today.replace(day=1)
            monthly_income = Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            monthly_expense = Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            remaining = (monthly_income or Decimal("0.00")) - (monthly_expense or Decimal("0.00"))
            return max(remaining, Decimal("0.00"))
        return Decimal("0.00")

    @classmethod
    def generate_alerts(cls, user):
        alerts_generated = []
        today = timezone.localdate()

        overdue_bills = SmartBill.objects.filter(user=user, status="PENDING", due_date__lt=today)
        for bill in overdue_bills:
            alert = cls._create_alert(
                user,
                title="Bill overdue",
                message=f"Your {bill.biller_name} bill of Rs. {bill.amount} is overdue.",
                category="PAYMENT",
                severity="CRITICAL",
                action_required=True,
                action_url="/autopilot/bills/",
                related_bill=bill,
            )
            alerts_generated.append({"type": "PAYMENT", "title": alert.title, "severity": alert.severity})

        profile, _ = AutopilotProfile.resolve_for_user(user)
        monthly_budget = profile.monthly_budget or Decimal("0.00")
        if monthly_budget > 0:
            month_start = today.replace(day=1)
            monthly_expense = Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            monthly_expense = monthly_expense or Decimal("0.00")
            budget_percentage = (monthly_expense / monthly_budget) * 100 if monthly_budget else 0
            if budget_percentage >= profile.budget_alert_threshold:
                alert = cls._create_alert(
                    user,
                    title="Budget warning",
                    message=f"You have used {budget_percentage:.1f}% of your monthly budget.",
                    category="BUDGET",
                    severity="HIGH" if budget_percentage >= 100 else "MEDIUM",
                    action_required=True,
                    action_url="/finance/budgets/",
                )
                alerts_generated.append({"type": "BUDGET", "title": alert.title, "severity": alert.severity})

        account = cls._payment_account(user)
        if account and account.balance < Decimal("1000.00"):
            alert = cls._create_alert(
                user,
                title="Low balance alert",
                message=f"Your available cash balance is low: Rs. {account.balance}.",
                category="SAVINGS",
                severity="HIGH",
                action_required=True,
                action_url="/finance/",
            )
            alerts_generated.append({"type": "SAVINGS", "title": alert.title, "severity": alert.severity})

        return alerts_generated

    @classmethod
    def check_alerts(cls, user):
        alerts = cls.generate_alerts(user)
        if alerts:
            return alerts
        recent = Alert.objects.filter(user=user).order_by("-alert_time")[:5]
        return [{"type": alert.category, "title": alert.title, "severity": alert.severity} for alert in recent]

    @classmethod
    def detect_patterns(cls, user):
        cutoff = timezone.localdate() - timedelta(days=90)
        expenses = list(Expense.objects.filter(user=user, date__gte=cutoff).order_by("-date"))
        incomes = list(Income.objects.filter(user=user, date__gte=cutoff).order_by("-date"))
        if not expenses and not incomes:
            return 0

        updates = 0
        category_groups = defaultdict(list)
        merchant_groups = defaultdict(list)
        income_groups = defaultdict(list)

        for expense in expenses:
            category_groups[expense.category or "OTHER"].append(expense)
            merchant = (expense.description or "").strip()
            if merchant:
                merchant_groups[merchant[:200]].append(expense)

        for income in incomes:
            source = (income.source or "").strip()
            if source:
                income_groups[source[:200]].append(income)

        for category, items in category_groups.items():
            if len(items) < 3:
                continue
            total = sum((item.amount for item in items), Decimal("0.00"))
            avg_amount = total / len(items)
            TransactionPattern.objects.update_or_create(
                user=user,
                pattern_type="CATEGORY",
                pattern_name=f"Recurring {category.title()} spending",
                defaults={
                    "pattern_data": {"average_amount": float(avg_amount), "count": len(items)},
                    "confidence_score": min(Decimal("95.00"), Decimal(str(60 + len(items) * 5))),
                    "frequency": "MONTHLY",
                    "is_active": True,
                    "related_category": category,
                    "last_observed": timezone.now(),
                    "observation_count": len(items),
                    "metadata": {"description": f"Repeated {category.lower()} spending in the last 90 days."},
                },
            )
            updates += 1

        for merchant, items in merchant_groups.items():
            if len(items) < 3:
                continue
            total = sum((item.amount for item in items), Decimal("0.00"))
            avg_amount = total / len(items)
            TransactionPattern.objects.update_or_create(
                user=user,
                pattern_type="MERCHANT",
                pattern_name=f"Recurring merchant: {merchant}",
                defaults={
                    "pattern_data": {"average_amount": float(avg_amount), "count": len(items)},
                    "confidence_score": min(Decimal("95.00"), Decimal(str(65 + len(items) * 5))),
                    "frequency": "MONTHLY",
                    "is_active": True,
                    "related_merchant": merchant,
                    "last_observed": timezone.now(),
                    "observation_count": len(items),
                    "metadata": {"description": f"Repeated merchant spending for {merchant}."},
                },
            )
            updates += 1

        for source, items in income_groups.items():
            if len(items) < 2:
                continue
            total = sum((item.amount for item in items), Decimal("0.00"))
            avg_amount = total / len(items)
            TransactionPattern.objects.update_or_create(
                user=user,
                pattern_type="INCOME",
                pattern_name=f"Recurring income: {source}",
                defaults={
                    "pattern_data": {"average_amount": float(avg_amount), "count": len(items)},
                    "confidence_score": min(Decimal("90.00"), Decimal(str(60 + len(items) * 10))),
                    "frequency": "MONTHLY",
                    "is_active": True,
                    "related_merchant": source,
                    "last_observed": timezone.now(),
                    "observation_count": len(items),
                    "metadata": {"description": f"Repeated income from {source}."},
                },
            )
            updates += 1

        if expenses:
            average_expense = sum((expense.amount for expense in expenses), Decimal("0.00")) / len(expenses)
            anomalies = [expense for expense in expenses if expense.amount >= average_expense * Decimal("2")]
            if anomalies:
                TransactionPattern.objects.update_or_create(
                    user=user,
                    pattern_type="AMOUNT",
                    pattern_name="Large spending anomalies",
                    defaults={
                        "pattern_data": {
                            "count": len(anomalies),
                            "largest_amount": float(max(expense.amount for expense in anomalies)),
                        },
                        "confidence_score": Decimal("75.00"),
                        "frequency": "IRREGULAR",
                        "is_anomaly": True,
                        "is_active": True,
                        "last_observed": timezone.now(),
                        "observation_count": len(anomalies),
                        "metadata": {"description": "Large expenses that materially exceed recent averages."},
                    },
                )
                updates += 1

        return updates

    @classmethod
    def discover_transaction_patterns(cls, user):
        cls.detect_patterns(user)
        patterns = TransactionPattern.objects.filter(user=user, is_active=True).order_by("-confidence_score")[:5]
        return [
            {
                "id": str(pattern.id),
                "type": pattern.pattern_type,
                "name": pattern.pattern_name,
                "description": (pattern.metadata or {}).get("description", pattern.pattern_name),
                "confidence": float(pattern.confidence_score),
            }
            for pattern in patterns
        ]

    @classmethod
    def update_financial_health(cls, user):
        try:
            health_score, _ = FinancialHealthScore.objects.get_or_create(user=user)
            health_score.calculate_score()
            return health_score
        except Exception:
            logger.exception("Financial health update error for user %s", user.id)
            return None

    @classmethod
    def check_investment_opportunities(cls, user):
        try:
            return AIAdvisor.get_investment_recommendations(user)[:3]
        except Exception:
            logger.exception("Investment recommendation error for user %s", user.id)
            return []

    @classmethod
    def check_condition(cls, condition_type, condition_value, data):
        condition_value = condition_value or {}
        amount = Decimal(str(data.get("amount") or "0"))
        category = str(data.get("category") or "")
        merchant = str(data.get("merchant") or "")
        balance = Decimal(str(data.get("balance") or "0"))
        threshold = Decimal(str(condition_value.get("threshold") or "0"))

        if condition_type == "AMOUNT_GREATER":
            return amount > threshold
        if condition_type == "AMOUNT_LESS":
            return amount < threshold
        if condition_type == "CATEGORY_MATCH":
            return category and category == str(condition_value.get("category") or "")
        if condition_type == "MERCHANT":
            expected = str(condition_value.get("merchant") or "")
            return bool(expected) and expected.lower() in merchant.lower()
        if condition_type == "BALANCE":
            return balance < threshold
        if condition_type == "PATTERN":
            return str(data.get("pattern_id") or "") == str(condition_value.get("pattern_id") or "")
        return False

    @classmethod
    def execute_rule(cls, rule, trigger_data=None):
        trigger_data = trigger_data or {}
        if not cls.check_condition(rule.condition_type, rule.condition_value, trigger_data):
            return {"executed": False, "reason": "Condition not met"}

        user = rule.user
        action_message = (rule.action_value or {}).get("message") or rule.description or rule.name

        if rule.action_type in {"ALERT", "NOTIFY", "REVIEW"}:
            alert = cls._create_alert(
                user,
                title=f"Rule triggered: {rule.name}",
                message=action_message,
                category="SYSTEM" if rule.action_type != "REVIEW" else "RISK",
                severity="MEDIUM",
                action_required=rule.action_type == "REVIEW",
                action_url="/autopilot/alerts/" if rule.action_type != "REVIEW" else "/autopilot/approvals/",
                action_data={"rule_id": str(rule.id)},
            )
            return {"executed": True, "alert_id": str(alert.id)}

        if rule.action_type == "SAVE":
            amount = cls.calculate_transfer_amount(rule, user)
            cls._create_alert(
                user,
                title=f"Savings suggestion: {rule.name}",
                message=f"Review moving Rs. {amount} into savings.",
                category="SAVINGS",
                severity="INFO",
                action_required=True,
                action_url="/autopilot/savings/",
                action_data={"rule_id": str(rule.id), "amount": float(amount)},
            )
            return {"executed": True, "suggested_amount": float(amount)}

        if rule.action_type == "PAY_BILL":
            bill = trigger_data.get("bill")
            if not isinstance(bill, SmartBill):
                bill = SmartBill.objects.filter(user=user, status="PENDING").order_by("due_date").first()
            if bill is None:
                return {"executed": False, "reason": "No pending bill available"}
            approval, _ = ApprovalRequest.objects.get_or_create(
                user=user,
                organization=getattr(bill, "organization", None),
                bill=bill,
                status="PENDING",
                defaults={
                    "request_type": "BILL_PAYMENT",
                    "title": f"Pay bill: {bill.biller_name}",
                    "description": f"Triggered by rule {rule.name}.",
                    "amount": bill.amount,
                    "why": f"Rule {rule.name} recommended reviewing this bill for payment.",
                    "metadata": {"rule_id": str(rule.id)},
                },
            )
            return {"executed": True, "approval_id": str(approval.id)}

        return {"executed": False, "reason": f"Unsupported action type: {rule.action_type}"}

    @classmethod
    def check_expense_rule(cls, user, transaction_record):
        rules = AutomationRule.objects.filter(user=user, is_active=True)
        balance = getattr(getattr(transaction_record, "account", None), "balance", Decimal("0.00"))
        trigger_data = {
            "amount": getattr(transaction_record, "amount", Decimal("0.00")),
            "category": getattr(transaction_record, "category", "") or "",
            "merchant": getattr(transaction_record, "merchant", "") or getattr(transaction_record, "description", ""),
            "balance": balance,
        }
        results = []
        for rule in rules:
            try:
                result = cls.execute_rule(rule, trigger_data)
                if result.get("executed"):
                    results.append(result)
            except Exception:
                logger.exception("Rule execution failed for %s", rule.id)
        return results
