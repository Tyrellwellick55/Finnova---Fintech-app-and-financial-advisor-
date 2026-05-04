# payments_core/services/orchestrator.py
import logging
from decimal import Decimal
from django.utils import timezone
from django.db import transaction

from payments_core.models import PaymentIntent, PaymentTransaction, PaymentAccount
from finance.models import Expense, Income, Budget, FinancialMetric
from finnova_autopilot.models import SmartBill, Alert, AutopilotProfile
from analytics_ai.services import FinancialAnalyticsService
from notifications.services import NotificationService

logger = logging.getLogger(__name__)

class FinancialOrchestrator:
    """
    Central orchestrator for all financial events in the Finnova ecosystem.
    Ensures that any action in one module ripples correctly through others.
    """

    @staticmethod
    def process_payment_success(payment_intent):
        """
        Handles everything that should happen when a payment is successful.
        1. Create Finance Expense/Income
        2. Update Analytics
        3. Trigger Autopilot Rules
        4. Send Notifications
        5. Log in Audit (handled by signals/views)
        """
        try:
            with transaction.atomic():
                user = payment_intent.user
                
                # 1. Sync with Finance Module
                from .payment_integrator import PaymentIntegrator
                finance_sync = PaymentIntegrator.sync_with_finance_module(user, payment_intent)
                
                # 2. Trigger Autopilot Rules
                from .automation_engine import AutomationEngine
                # Create a mock transaction record if it doesn't exist for rule checking
                tx_record = PaymentTransaction.objects.get_or_create(
                    payment_intent=payment_intent,
                    defaults={
                        'account': payment_intent.account,
                        'amount': -payment_intent.amount if payment_intent.payment_method not in ['REFUND', 'TOPUP'] else payment_intent.amount,
                        'transaction_type': 'DEBIT' if payment_intent.payment_method not in ['REFUND', 'TOPUP'] else 'CREDIT',
                        'status': 'SUCCESS',
                        'description': payment_intent.description
                    }
                )[0]
                
                # Check for expense rules/fraud
                AutomationEngine.check_expense_rule(user, tx_record)
                
                # 3. Update Financial Health & Analytics
                analytics_service = FinancialAnalyticsService(user)
                analytics_service.calculate_financial_health()
                
                # 4. Check for Savings Opportunities
                if payment_intent.payment_method in ['REFUND', 'TOPUP']:
                    AutomationEngine.check_savings_opportunity(user, payment_intent.amount)
                
                # 5. Ensure Daily Metrics are updated
                from finance.services.finance_engine import FinanceEngine
                FinanceEngine.generate_daily_metrics(user)

                logger.info(f"Orchestrated success for payment {payment_intent.reference_id}")
                return True
        except Exception as e:
            logger.error(f"Orchestration failure for payment {payment_intent.reference_id}: {str(e)}")
            return False

    @staticmethod
    def execute_autopilot_routine(user):
        """
        Executes a full autopilot routine for a user.
        1. Pay Due Bills
        2. Run Savings Transfers
        3. Check for Alerts
        4. Update Insights
        """
        try:
            from .automation_engine import AutomationEngine
            
            # 1. Process Bill Payments
            paid_bills = AutomationEngine.auto_pay_bills(user)
            
            # 2. Process Debt Repayments (New)
            paid_debts = AutomationEngine.execute_debt_repayment(user)
            
            # 3. Process Savings Transfers (Realized)
            savings_results = AutomationEngine.execute_savings_rules(user)
            
            # 4. Generate Alerts
            AutomationEngine.check_alerts(user)
            
            # 5. Refresh Analytics
            analytics_service = FinancialAnalyticsService(user)
            analytics_service.analyze_monthly_finances()
            
            return {
                'bills_paid': len(paid_bills),
                'debts_paid': len(paid_debts),
                'savings_amount': savings_results.get('amount', 0),
                'status': 'SUCCESS'
            }
        except Exception as e:
            logger.error(f"Autopilot orchestration failure for user {user.username}: {str(e)}")
            return {'status': 'FAILED', 'error': str(e)}
