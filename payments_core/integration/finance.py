# payments_core/services/finance.py
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone
from django.db.models import Sum

from ..models import PaymentIntent, PaymentAccount
from ..services.payment_processor import PaymentProcessor
from finnova_autopilot.models import FinancialHealthScore

logger = logging.getLogger(__name__)

class FinancePaymentIntegration:
    """Integration between payments and finance features"""

    @staticmethod
    def _resolve_finance_account(user, create_if_missing=False):
        """Resolve finance account for expense/income linking."""
        from finance.models import Account

        account = (
            Account.objects.filter(user=user, is_primary=True, is_active=True).first()
            or Account.objects.filter(user=user, is_primary=True).first()
            or Account.objects.filter(user=user, is_active=True).first()
            or Account.objects.filter(user=user).first()
        )
        if account:
            return account

        if create_if_missing:
            return Account.objects.create(
                user=user,
                name="Primary Financial Account",
                account_type="SAVINGS",
                opening_balance=Decimal('0.00'),
                current_balance=Decimal('0.00'),
                is_primary=True,
                is_active=True,
            )

        return None
    
    @staticmethod
    def pay_bill(user, bill_data, payment_method='UPI'):
        """
        Pay a bill through payments system
        """
        try:
            # Extract bill data
            amount = bill_data.get('amount')
            bill_type = bill_data.get('bill_type', 'Utility')
            biller_name = bill_data.get('biller_name', 'Unknown')
            due_date = bill_data.get('due_date')
            
            if not amount:
                return {'success': False, 'error': 'Amount is required'}
            
            # Create payment
            result = PaymentProcessor.create_payment_intent(
                user=user,
                amount=amount,
                payment_method=payment_method,
                description=f"Bill Payment: {bill_type} - {biller_name}",
                metadata={
                    'bill_type': bill_type,
                    'biller_name': biller_name,
                    'due_date': due_date.isoformat() if due_date else None,
                    'finance_integration': True
                }
            )
            
            # Process payment
            process_result = PaymentProcessor.process_payment(result)
            
            if process_result['success']:
                result.mark_success(process_result.get('gateway_data', {}))
                
                # Return success response
                return {
                    'success': True,
                    'payment_intent': result,
                    'message': f'Bill payment of ₹{amount} successful'
                }
            else:
                result.mark_failed(process_result.get('error', 'Payment failed'))
                return {
                    'success': False,
                    'error': process_result.get('error', 'Payment failed'),
                    'payment_intent': result
                }
                
        except Exception as e:
            logger.error(f"Error paying bill: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def create_income_deposit(user, amount, source, description=""):
        """
        Deposit income to account
        """
        try:
            # Get user's account
            account = PaymentAccount.objects.filter(user=user, is_primary=True).first()
            if not account:
                return {'success': False, 'error': 'No payment account found'}
            
            # Create deposit intent as CREATED, then mark_success.
            # Balance updates + transaction creation are handled by payments_core signals.
            payment_intent = PaymentIntent.objects.create(
                user=user,
                account=account,
                reference_id=PaymentIntent.generate_reference_id(),
                amount=amount,
                payment_method='DEPOSIT',
                description=description or f"Income deposit from {source}",
                status='CREATED',
                metadata={
                    'source': source,
                    'type': 'income_deposit',
                    'finance_integration': True
                }
            )
            payment_intent.mark_success({'mode': 'DUMMY', 'source': source})
            
            logger.info(f"Income deposit of ₹{amount} from {source} for user {user.username}")
            
            return {
                'success': True,
                'payment_intent': payment_intent,
                'message': f'Deposit of ₹{amount} successful'
            }
            
        except Exception as e:
            logger.error(f"Error creating income deposit: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def transfer_between_accounts(user, from_account_id, to_account_id, amount, description=""):
        """
        Transfer money between accounts
        """
        try:
            from_account = PaymentAccount.objects.get(id=from_account_id, user=user)
            to_account = PaymentAccount.objects.get(id=to_account_id, user=user)
            
            # Check if sufficient balance
            if from_account.balance < amount:
                return {'success': False, 'error': 'Insufficient balance'}
            
            from django.db import transaction
            with transaction.atomic():
                # Debit intent (source)
                debit_intent = PaymentIntent.objects.create(
                    user=user,
                    account=from_account,
                    reference_id=PaymentIntent.generate_reference_id(),
                    amount=amount,
                    payment_method='BANK_TRANSFER',
                    description=f"Transfer to {to_account.account_number}: {description}",
                    status='CREATED',
                    metadata={
                        'transfer_type': 'internal',
                        'to_account': str(to_account.id),
                        'finance_integration': True,
                    },
                )

                # Credit intent (destination) - treat as DEPOSIT so it credits
                credit_intent = PaymentIntent.objects.create(
                    user=user,
                    account=to_account,
                    reference_id=PaymentIntent.generate_reference_id(),
                    amount=amount,
                    payment_method='DEPOSIT',
                    description=f"Transfer from {from_account.account_number}: {description}",
                    status='CREATED',
                    metadata={
                        'transfer_type': 'internal',
                        'from_account': str(from_account.id),
                        'finance_integration': True,
                    },
                )

                debit_intent.mark_success({'mode': 'DUMMY', 'transfer': 'debit'})
                credit_intent.mark_success({'mode': 'DUMMY', 'transfer': 'credit'})
            
            logger.info(f"Internal transfer of ₹{amount} from {from_account.account_number} to {to_account.account_number}")
            
            return {
                'success': True,
                'debit_intent': debit_intent,
                'credit_intent': credit_intent,
                'message': f'Transfer of ₹{amount} successful'
            }
            
        except PaymentAccount.DoesNotExist:
            return {'success': False, 'error': 'Account not found'}
        except Exception as e:
            logger.error(f"Error transferring between accounts: {str(e)}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def update_financial_health(user):
        """
        Update financial health score for a user
        """
        try:
            from finance.services.finance_engine import FinanceEngine

            # Calculate financial health
            health_data = FinanceEngine.calculate_financial_health(user)

            # Update or create FinancialHealthScore
            health_score, created = FinancialHealthScore.objects.get_or_create(
                user=user,
                defaults={
                    'overall_score': health_data['overall_score'],
                    'components': health_data,
                    'insights': [],
                    'recommendations': [],
                }
            )

            if not created:
                health_score.overall_score = health_data['overall_score']
                health_score.components = health_data
                health_score.save()

            logger.info(f"Updated financial health for user {user.username}: {health_data['overall_score']}")

            return {
                'success': True,
                'health_score': health_score,
                'message': 'Financial health updated successfully'
            }

        except Exception as e:
            logger.error(f"Error updating financial health: {str(e)}")
            return {'success': False, 'error': str(e)}

    @staticmethod
    def check_budget_impact(user, amount, category=None):
        """Evaluate impact of a transaction on active budgets."""
        try:
            from finance.models import Budget

            amount = Decimal(str(amount or 0))
            impacted = []
            alerts = []

            budgets = Budget.objects.filter(user=user, is_active=True)
            if category:
                budgets = budgets.filter(name__icontains=category) | budgets.filter(metadata__category=category)

            for budget in budgets.distinct():
                budget.update_spending()
                current_spending = Decimal(str(budget.current_spending or 0))
                projected = current_spending + amount
                utilization = float((projected / budget.amount * 100) if budget.amount else 0)
                status = 'SAFE'
                if utilization >= 100:
                    status = 'EXCEEDED'
                elif utilization >= float(budget.alert_threshold):
                    status = 'NEAR_LIMIT'

                impacted.append({
                    'budget_id': str(budget.id),
                    'budget_name': budget.name,
                    'current_spending': float(current_spending),
                    'projected_spending': float(projected),
                    'budget_amount': float(budget.amount),
                    'projected_utilization': round(utilization, 2),
                    'status': status,
                })

                if status in {'EXCEEDED', 'NEAR_LIMIT'}:
                    alerts.append({
                        'title': f"Budget impact: {budget.name}",
                        'status': status,
                        'projected_utilization': round(utilization, 2),
                    })

            return {
                'success': True,
                'amount': float(amount),
                'category': category,
                'impacted_budgets': impacted,
                'alerts': alerts,
            }
        except Exception as e:
            logger.error(f"Error checking budget impact: {str(e)}")
            return {'success': False, 'error': str(e), 'impacted_budgets': [], 'alerts': []}

    @staticmethod
    def get_integrated_financial_data(user):
        """Aggregate finance + payments numbers for integrated dashboards."""
        try:
            from finance.models import Income, Expense
            from finnova_autopilot.models import SmartBill
            from finance.services.finance_engine import FinanceEngine

            today = timezone.now().date()
            month_start = today.replace(day=1)

            total_income = (
                Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum('amount'))['total']
                or Decimal('0.00')
            )
            total_expenses = (
                Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum('amount'))['total']
                or Decimal('0.00')
            )

            net_savings = total_income - total_expenses
            savings_rate = float((net_savings / total_income * 100) if total_income > 0 else 0)

            payment_account = (
                PaymentAccount.objects.filter(user=user, is_primary=True, is_active=True).first()
                or PaymentAccount.objects.filter(user=user, is_primary=True).first()
                or PaymentAccount.objects.filter(user=user).first()
            )
            pending_bills = SmartBill.objects.filter(
                user=user,
                status='PENDING',
                due_date__gte=today,
            ).count()

            health = FinanceEngine.calculate_financial_health(user)

            return {
                'total_income': float(total_income),
                'total_expenses': float(total_expenses),
                'net_savings': float(net_savings),
                'savings_rate': round(savings_rate, 2),
                'wallet_balance': float(payment_account.balance) if payment_account else 0,
                'pending_bills': pending_bills,
                'financial_health_score': health.get('overall_score', 0),
            }
        except Exception as e:
            logger.error(f"Error building integrated financial data: {str(e)}")
            return {
                'total_income': 0,
                'total_expenses': 0,
                'net_savings': 0,
                'savings_rate': 0,
                'wallet_balance': 0,
                'pending_bills': 0,
                'financial_health_score': 0,
                'error': str(e),
            }

    @staticmethod
    def generate_comprehensive_report(user, report_type='COMPREHENSIVE', timeframe='MONTHLY'):
        """Generate report payload expected by integrated views."""
        try:
            from finance.services.finance_engine import FinanceEngine

            today = timezone.now().date()
            tf = (timeframe or 'MONTHLY').upper()
            if tf == 'WEEKLY':
                start_date = today - timedelta(days=7)
            elif tf == 'QUARTERLY':
                start_date = today - timedelta(days=90)
            elif tf == 'YEARLY':
                start_date = today - timedelta(days=365)
            else:
                start_date = today.replace(day=1)

            report_data = FinanceEngine.generate_financial_report(
                user=user,
                report_type=report_type,
                start_date=start_date,
                end_date=today,
            )
            report_data['start_date'] = start_date
            report_data['end_date'] = today
            report_data['timeframe'] = tf
            return report_data
        except Exception as e:
            logger.error(f"Error generating comprehensive report: {str(e)}")
            return {
                'report_type': report_type,
                'start_date': timezone.now().date(),
                'end_date': timezone.now().date(),
                'summary': {},
                'error': str(e),
            }

    @staticmethod
    def get_user_financial_context(user):
        """Context block used by audit and transaction-monitoring views."""
        try:
            from finance.models import Income, Expense, Budget
            from finnova_autopilot.models import SmartBill

            today = timezone.now().date()
            month_start = today.replace(day=1)

            income = (
                Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum('amount'))['total']
                or Decimal('0.00')
            )
            expense = (
                Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum('amount'))['total']
                or Decimal('0.00')
            )
            budget_total = (
                Budget.objects.filter(user=user, is_active=True).aggregate(total=Sum('amount'))['total']
                or Decimal('0.00')
            )
            pending_bills = SmartBill.objects.filter(user=user, status='PENDING').count()

            return {
                'monthly_income': float(income),
                'monthly_expense': float(expense),
                'monthly_net': float(income - expense),
                'active_budget_total': float(budget_total),
                'pending_bills': pending_bills,
                'health': FinancialHealthScore.objects.filter(user=user).first(),
            }
        except Exception as e:
            logger.error(f"Error getting user financial context: {str(e)}")
            return {'error': str(e)}

    @staticmethod
    def generate_monthly_report(user, month=None, year=None):
        """Monthly report helper used by legacy payment utilities."""
        try:
            from finance.services.finance_engine import FinanceEngine

            now = timezone.now().date()
            month = int(month or now.month)
            year = int(year or now.year)

            start_date = date(year, month, 1)
            if month == 12:
                end_date = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end_date = date(year, month + 1, 1) - timedelta(days=1)

            report = FinanceEngine.generate_financial_report(
                user=user,
                report_type='MONTHLY',
                start_date=start_date,
                end_date=end_date,
            )
            report['start_date'] = start_date
            report['end_date'] = end_date
            report['month'] = month
            report['year'] = year
            return report
        except Exception as e:
            logger.error(f"Error generating monthly report: {str(e)}")
            return {'error': str(e), 'month': month, 'year': year}

    @staticmethod
    def calculate_financial_health(user):
        """Legacy compatibility wrapper used by payment utility code."""
        try:
            from finance.services.finance_engine import FinanceEngine

            health = FinanceEngine.calculate_financial_health(user)
            return {
                'score': health.get('overall_score', 0),
                'overall_score': health.get('overall_score', 0),
                'savings_score': health.get('savings_score', 0),
                'expense_score': health.get('expense_score', 0),
                'emergency_score': health.get('emergency_score', 0),
                'debt_score': health.get('debt_score', 0),
            }
        except Exception as e:
            logger.error(f"Error calculating financial health: {str(e)}")
            return {'score': 0, 'overall_score': 0, 'error': str(e)}
