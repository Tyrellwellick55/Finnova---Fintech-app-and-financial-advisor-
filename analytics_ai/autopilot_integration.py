import json
from datetime import timedelta
from django.db import transaction, models
from django.utils import timezone
from typing import Dict, List

from finnova_autopilot.models import AutopilotDecision, RuleEngine
from payments_core.models import PaymentAccount, PaymentTransaction, PaymentTransaction
from finance.models import Expense, Income
from .services import FinancialAnalyticsService
from .models import FinancialInsight

class AutopilotIntegrationService:
    """Integrates analytics with autopilot system"""
    
    @staticmethod
    def process_transaction_for_autopilot(transaction) -> Dict:
        """
        Process transaction and make autopilot decisions
        Returns: {'decision': AutopilotDecision, 'actions': List}
        """
        user = transaction.user
        analytics_service = FinancialAnalyticsService(user)
        
        # 1. Analyze transaction
        analysis = analytics_service.analyze_monthly_finances()
        
        # 2. Check against autopilot rules
        decisions = []
        
        # Rule 1: Large transaction check
        if float(transaction.amount) > 10000:
            decision = AutopilotDecision.objects.create(
                user=user,
                trigger_type='LARGE_TRANSACTION',
                action_taken='ALERT_SENT',
                status='COMPLETED',
                metadata={
                    'transaction_id': transaction.id,
                    'amount': float(transaction.amount),
                    'threshold': 10000
                }
            )
            decisions.append(decision)
            
            # Create insight
            FinancialInsight.objects.create(
                user=user,
                insight_type='TREND',
                title='Large Transaction Processed',
                description=f'Autopilot processed large transaction of â‚¹{transaction.amount}',
                severity='MEDIUM'
            )
        
        # Rule 2: Category-based rules (use Expense for spending analysis)
        if getattr(transaction, "category", None):
            category_rules = RuleEngine.objects.filter(
                user=user,
                rule_type='CATEGORY_LIMIT',
                is_active=True,
                condition_value__category=getattr(transaction.category, "name", None),
            )

            for rule in category_rules:
                month_start = timezone.now().replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0
                )
                category_spent = (
                    Expense.objects.filter(
                        user=user,
                        category=transaction.category,
                        date__gte=month_start,
                    ).aggregate(total=models.Sum("amount"))["total"]
                    or 0
                )

                limit = rule.condition_value.get("limit", 0)

                if category_spent > limit:
                    action_result = AutopilotIntegrationService._execute_rule_action(
                        rule, transaction
                    )

                    decision = AutopilotDecision.objects.create(
                        user=user,
                        trigger_type="CATEGORY_LIMIT_EXCEEDED",
                        action_taken=json.dumps(action_result),
                        status="COMPLETED",
                        metadata={
                            "rule_id": rule.id,
                            "category": getattr(transaction.category, "name", ""),
                            "spent": float(category_spent),
                            "limit": limit,
                            "transaction_id": transaction.id,
                        },
                    )
                    decisions.append(decision)

        # Rule 3: Balance protection â€“ use primary payment account
        wallet = (
            PaymentAccount.objects.filter(user=user, is_active=True)
            .order_by("-is_primary", "-created_at")
            .first()
        )
        if wallet and wallet.balance < 1000:  # Low balance
            decision = AutopilotDecision.objects.create(
                user=user,
                trigger_type='LOW_BALANCE',
                action_taken='SPENDING_FREEZE',
                status='COMPLETED',
                metadata={
                    'balance': float(wallet.balance),
                    'transaction_id': transaction.id
                }
            )
            decisions.append(decision)
        
        return {
            'decisions': decisions,
            'analysis': analysis,
            'transaction_processed': True
        }
    
    @staticmethod
    def _execute_rule_action(rule: RuleEngine, transaction) -> Dict:
        """Execute autopilot rule action"""
        from notifications.services import create_notification_event
        
        action_type = rule.action_type
        
        # Dispatch table for rule actions
        def notify_action():
            create_notification_event(
                user=transaction.user,
                source="AUTOPILOT",
                event_type="RULE_TRIGGERED",
                title=f"Category Limit Exceeded: {transaction.category.name}",
                message=f"You've exceeded your monthly limit for {transaction.category.name}",
                action_hint="Review your spending in this category."
            )
            return {'action': 'notification_sent', 'status': 'success'}
        
        def block_action():
            # Mark transaction for review
            transaction.status = 'PENDING_REVIEW'
            transaction.save()
            return {'action': 'transaction_blocked', 'status': 'success'}
        
        def redirect_action():
            # Redirect to savings instead of spending by moving funds between accounts.
            from payments_core.models import PaymentAccount, PaymentTransaction, PaymentTransaction, PaymentTransaction

            main_account = (
                PaymentAccount.objects.filter(
                    user=transaction.user, is_active=True
                )
                .order_by("-is_primary", "-created_at")
                .first()
            )
            savings_account, _ = PaymentAccount.objects.get_or_create(
                user=transaction.user,
                account_type="SAVINGS",
                defaults={
                    "account_number": PaymentAccount.generate_account_number(),
                    "currency": "INR",
                    "is_active": True,
                },
            )

            if not main_account or main_account.balance < transaction.amount:
                return {
                    "action": "redirect_failed",
                    "status": "insufficient_funds",
                }

            PaymentTransaction.objects.create(
                account=main_account,
                transaction_type="DEBIT",
                amount=transaction.amount,
                description="Autopilot redirected spending to savings",
                reference=f"AUTO-SAVE-{transaction.id}",
                balance_before=main_account.balance,
                balance_after=main_account.balance - transaction.amount,
                metadata={"original_txn_id": str(transaction.id)},
            )

            main_account.update_balance(-transaction.amount)
            savings_account.update_balance(transaction.amount)

            return {
                "action": "redirected_to_savings",
                "amount": float(transaction.amount),
            }
        
        actions = {
            'NOTIFY': notify_action,
            'BLOCK': block_action,
            'REDIRECT': redirect_action,
        }
        
        action_handler = actions.get(action_type)
        return action_handler() if action_handler else {'action': 'no_action', 'status': 'skipped'}
    
    @staticmethod
    def generate_autopilot_report(user, days: int = 30) -> Dict:
        """Generate autopilot activity report"""
        end_date = timezone.now()
        start_date = end_date - timedelta(days=days)
        
        decisions = AutopilotDecision.objects.filter(
            user=user,
            created_at__gte=start_date,
            created_at__lte=end_date
        )
        
        # Calculate savings from autopilot
        savings_transactions = PaymentTransaction.objects.filter(
            user=user,
            description__contains='Autopilot',
            transaction_transaction_date__gte=start_date
        )
        
        total_savings = sum(float(t.amount) for t in savings_transactions)
        
        # Count prevented overspending
        blocked_transactions = PaymentTransaction.objects.filter(
            user=user,
            status='BLOCKED_BY_AUTOPILOT',
            transaction_transaction_date__gte=start_date
        )
        
        prevented_spending = sum(float(t.amount) for t in blocked_transactions)
        
        return {
            'period': {'start': start_date, 'end': end_date},
            'total_decisions': decisions.count(),
            'by_trigger_type': dict(decisions.values_list('trigger_type').annotate(count=models.Count('id'))),
            'total_savings_generated': total_savings,
            'prevented_overspending': prevented_spending,
            'success_rate': (decisions.filter(status='COMPLETED').count() / decisions.count() * 100) if decisions.count() > 0 else 0,
            'recent_decisions': list(decisions.order_by('-created_at')[:10].values(
                'trigger_type', 'action_taken', 'created_at', 'metadata'
            ))
        }
