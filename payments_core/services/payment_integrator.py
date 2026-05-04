# payments_core/services/payment_integrator.py
import logging
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

class PaymentIntegrator:
    """Integrate payments with other modules"""

    @staticmethod
    def _resolve_finance_account(user, create_if_missing=False):
        """Resolve finance account used by Income/Expense records."""
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
                name='Primary Financial Account',
                account_type='SAVINGS',
                opening_balance=Decimal('0.00'),
                current_balance=Decimal('0.00'),
                is_primary=True,
                is_active=True,
            )
        return None
    
    @staticmethod
    def auto_categorize_transaction(transaction):
        """
        Automatically categorize transactions based on description
        """
        try:
            description = transaction.description.lower() if transaction.description else ''
            
            # Map to finance.Expense.EXPENSE_CATEGORIES codes

            # Food & Dining
            food_keywords = ['swiggy', 'zomato', 'uber eats', 'food', 'restaurant', 'cafe', 'pizza', 'burger']
            if any(keyword in description for keyword in food_keywords):
                return 'FOOD'
            
            # Shopping
            shopping_keywords = ['amazon', 'flipkart', 'myntra', 'shopping', 'store', 'mall', 'retail']
            if any(keyword in description for keyword in shopping_keywords):
                return 'SHOPPING'
            
            # Entertainment
            entertainment_keywords = ['netflix', 'prime video', 'hotstar', 'movie', 'theatre', 'concert']
            if any(keyword in description for keyword in entertainment_keywords):
                return 'ENTERTAINMENT'
            
            # Travel
            travel_keywords = ['uber', 'ola', 'makemytrip', 'flight', 'train', 'bus', 'travel']
            if any(keyword in description for keyword in travel_keywords):
                return 'TRAVEL'
            
            # Bills & Utilities
            bill_keywords = ['electricity', 'water', 'gas', 'mobile', 'internet', 'bill', 'utility', 'recharge']
            if any(keyword in description for keyword in bill_keywords):
                return 'BILLS'
            
            # Groceries
            grocery_keywords = ['bigbasket', 'groceries', 'supermarket', 'vegetable', 'fruit', 'dmart']
            if any(keyword in description for keyword in grocery_keywords):
                return 'GROCERIES'
            
            # Health
            health_keywords = ['hospital', 'clinic', 'pharmacy', 'medicine', 'doctor']
            if any(keyword in description for keyword in health_keywords):
                return 'HEALTH'
            
            # Default category
            return 'OTHER'
            
        except Exception as e:
            logger.error(f"Error auto-categorizing transaction: {str(e)}")
            return 'OTHER'
    
    @staticmethod
    def get_payment_analytics(user):
        """Get comprehensive payment analytics for user"""
        try:
            from ..models import PaymentIntent, PaymentTransaction
            
            today = timezone.now().date()
            month_start = today.replace(day=1)
            
            # Monthly statistics
            monthly_payments = PaymentIntent.objects.filter(
                user=user,
                created_at__date__gte=month_start,
                status='SUCCESS'
            )
            
            monthly_transactions = PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__date__gte=month_start
            )
            
            # Calculate totals
            total_spent = sum(p.amount for p in monthly_payments)
            transaction_count = monthly_transactions.count()
            
            # Payment method breakdown
            payment_methods = {}
            for payment in monthly_payments:
                method = payment.payment_method
                payment_methods[method] = payment_methods.get(method, 0) + float(payment.amount)
            
            # Category breakdown
            categories = {}
            for trans in monthly_transactions.filter(transaction_type='DEBIT'):
                category = trans.category or 'UNCATEGORIZED'
                categories[category] = categories.get(category, 0) + float(abs(trans.amount))
            
            # Success rate
            total_payments = PaymentIntent.objects.filter(
                user=user,
                created_at__date__gte=month_start
            ).count()
            
            successful_payments = monthly_payments.count()
            success_rate = (successful_payments / total_payments * 100) if total_payments > 0 else 0
            
            # Average transaction
            avg_transaction = total_spent / monthly_payments.count() if monthly_payments.exists() else 0
            
            return {
                'monthly_spending': float(total_spent),
                'transaction_count': transaction_count,
                'payment_methods': payment_methods,
                'categories': categories,
                'success_rate': success_rate,
                'avg_transaction': float(avg_transaction),
                'period': {
                    'start': month_start,
                    'end': today
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting payment analytics: {str(e)}")
            return {
                'monthly_spending': 0,
                'transaction_count': 0,
                'payment_methods': {},
                'categories': {},
                'success_rate': 0,
                'avg_transaction': 0,
                'period': {'start': None, 'end': None}
            }
    
    @staticmethod
    def sync_with_finance_module(user, payment_intent):
        """Sync a successful payment into the Finance ledger.

        This is a best-effort bridge used by legacy flows (e.g. transfer_money).
        The preferred mechanism is EventHub handlers + finance.services.posting,
        but keeping this call makes older pages work without refactors.

        Idempotency is enforced via payment_reference (= payment_intent.reference_id).
        """
        try:
            from finance.services.posting import post_expense, post_income

            if payment_intent.status != 'SUCCESS':
                return {'synced': False, 'reason': 'not_success'}

            purpose = (payment_intent.metadata or {}).get('purpose')

            # Treat most methods as expenses (debits), except explicit credit purposes.
            debit_methods = {'CARD', 'UPI', 'NETBANKING', 'WALLET', 'BANK_TRANSFER', 'CASH'}
            credit_methods = {'REFUND', 'TOPUP', 'DEPOSIT'}

            if payment_intent.payment_method in debit_methods:
                # Expense
                merchant = (payment_intent.metadata or {}).get('merchant') or 'Payment'
                category = (payment_intent.metadata or {}).get('category') or 'OTHER'

                if purpose == 'TRANSFER':
                    category = 'OTHER'
                    merchant = merchant or 'Transfer'
                    memo = f"Transfer: {payment_intent.description}"
                else:
                    memo = f"Payment: {payment_intent.description}"

                expense = post_expense(
                    organization=payment_intent.organization,
                    user=user,
                    amount=payment_intent.amount,
                    merchant=merchant,
                    category=category,
                    memo=memo,
                    payment_reference=payment_intent.reference_id,
                    related_payment=payment_intent,
                )
                return {'synced': True, 'type': 'expense', 'id': getattr(expense, 'id', None)}

            if payment_intent.payment_method in credit_methods:
                income = post_income(
                    organization=payment_intent.organization,
                    user=user,
                    amount=payment_intent.amount,
                    source=purpose or 'PAYMENT_CREDIT',
                    category='BUSINESS',
                    memo=f"Credit: {payment_intent.description}",
                    payment_reference=payment_intent.reference_id,
                    related_payment=payment_intent,
                )
                return {'synced': True, 'type': 'income', 'id': getattr(income, 'id', None)}

            return {'synced': False, 'reason': 'unknown_method'}

        except Exception as e:
            logger.error(f"Finance sync failed: {str(e)}")
            return {'synced': False, 'error': str(e)}

    
    @staticmethod
    def trigger_autopilot_rules(user, transaction_data):
        """
        Trigger autopilot rules based on transaction
        """
        try:
            from finnova_autopilot.models import AutomationRule
            
            rules = AutomationRule.objects.filter(
                user=user,
                is_active=True,
                trigger_event='PAYMENT'
            )
            
            triggered_rules = []
            for rule in rules:
                # Check rule conditions
                if PaymentIntegrator._check_rule_conditions(rule, transaction_data):
                    # Execute rule action
                    result = PaymentIntegrator._execute_rule_action(rule, transaction_data)
                    triggered_rules.append({
                        'rule_id': rule.id,
                        'rule_name': rule.name,
                        'action': rule.action,
                        'result': result
                    })
            
            return triggered_rules
            
        except ImportError:
            logger.debug("Autopilot module not available")
            return []
        except Exception as e:
            logger.error(f"Error triggering autopilot rules: {str(e)}")
            return []
    
    @staticmethod
    def _check_rule_conditions(rule, transaction_data):
        """Check if rule conditions are met"""
        # Simple condition checking - can be expanded
        conditions = rule.conditions or {}
        
        if 'amount_greater_than' in conditions:
            if transaction_data['amount'] <= conditions['amount_greater_than']:
                return False
        
        if 'category_matches' in conditions:
            if transaction_data.get('category') != conditions['category_matches']:
                return False
        
        return True
    
    @staticmethod
    def _execute_rule_action(rule, transaction_data):
        """Execute rule action"""
        try:
            if rule.action == 'CREATE_ALERT':
                # Create alert
                from finnova_autopilot.models import Alert
                Alert.objects.create(
                    user=rule.user,
                    category='RISK',
                    source='AUTOPILOT',
                    severity='MEDIUM',
                    title=f"Rule triggered: {rule.name}",
                    message=f"Transaction of ₹{transaction_data['amount']} triggered rule",
                    metadata={
                        'rule_id': rule.id,
                        'transaction_data': transaction_data
                    }
                )
                return 'Alert created'
            
            elif rule.action == 'BLOCK_CARD':
                # Block card (simplified)
                logger.info(f"Rule would block card for transaction: {transaction_data}")
                return 'Card block action triggered'
            
            elif rule.action == 'NOTIFY_USER':
                # Send notification
                from notifications.models import Notification
                Notification.objects.create(
                    user=rule.user,
                    title="Rule Alert",
                    message=f"Rule '{rule.name}' was triggered by your transaction",
                    category='AUTOPILOT',
                    severity='INFO'
                )
                return 'Notification sent'
            
            return 'Action executed'
            
        except Exception as e:
            logger.error(f"Error executing rule action: {str(e)}")
            return f'Error: {str(e)}'
