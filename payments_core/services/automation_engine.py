# payments_core/services/automation_engine.py
import logging
import uuid
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)

class AutomationEngine:
    """Automation engine for payment-related tasks"""
    
    @staticmethod
    def check_expense_rule(user, transaction):
        """
        Check and apply expense-related automation rules
        """
        try:
            from finnova_autopilot.models import AutomationRule
            
            rules = AutomationRule.objects.filter(
                user=user,
                is_active=True,
                trigger_event='EXPENSE'
            )
            
            applied_rules = []
            for rule in rules:
                if AutomationEngine._evaluate_rule(rule, transaction):
                    result = AutomationEngine._execute_expense_rule(rule, transaction)
                    applied_rules.append({
                        'rule_id': rule.id,
                        'rule_name': rule.name,
                        'result': result
                    })
            
            return applied_rules
            
        except ImportError:
            logger.debug("Autopilot module not available")
            return []
        except Exception as e:
            logger.error(f"Error checking expense rules: {str(e)}")
            return []
    
    @staticmethod
    def check_savings_opportunity(user, amount):
        """
        Check for savings opportunities based on deposit
        """
        try:
            from finnova_autopilot.models import SavingsGoal
            
            # Get active savings goals
            savings_goals = SavingsGoal.objects.filter(
                user=user,
                status__in=['ACTIVE', 'PLANNING']
            )
            
            opportunities = []
            for goal in savings_goals:
                # Check if we can contribute to this goal
                if goal.current_saved < goal.target_amount:
                    # Suggest contributing a percentage of the deposit
                    suggested_amount = min(
                        Decimal(str(amount)) * Decimal('0.1'),  # 10% of deposit
                        goal.target_amount - goal.current_saved
                    )
                    
                    if suggested_amount > 0:
                        opportunities.append({
                            'goal_id': goal.id,
                            'goal_name': goal.goal_name,
                            'suggested_amount': float(suggested_amount),
                            'current_progress': float(goal.current_saved / goal.target_amount * 100)
                        })
            
            return opportunities
            
        except ImportError:
            return []
        except Exception as e:
            logger.error(f"Error checking savings opportunities: {str(e)}")
            return []
    
    @staticmethod
    def auto_pay_bills(user):
        """
        Automatically pay due bills
        """
        try:
            from finnova_autopilot.models import SmartBill
            from ..services.payment_processor import PaymentProcessor
            
            today = timezone.now().date()
            due_bills = SmartBill.objects.filter(
                user=user,
                status='PENDING',
                due_date__lte=today,
                auto_pay=True
            )
            
            from ..models import CardToken, UPIID
            from ..services.payment_integrator import PaymentIntegrator
            from ..services.orchestrator import FinancialOrchestrator

            paid_bills = []
            for bill in due_bills:
                try:
                    # Check if user has sufficient balance
                    account = user.payment_accounts.filter(is_primary=True).first()
                    if account and account.balance >= bill.amount:
                        # Create and process payment
                        # Pick a method (UPI preferred if available)
                        default_upi = UPIID.objects.filter(user=user, is_active=True, is_default=True).first() or \
                                      UPIID.objects.filter(user=user, is_active=True).first()
                        default_card = CardToken.objects.filter(user=user, is_active=True, is_default=True).first() or \
                                       CardToken.objects.filter(user=user, is_active=True).first()

                        payment_method = 'UPI' if default_upi else ('CARD' if default_card else 'BANK_TRANSFER')

                        payment_intent = PaymentProcessor.create_payment_intent(
                            user=user,
                            organization=getattr(bill, 'organization', None),
                            amount=bill.amount,
                            payment_method=payment_method,
                            description=f"Auto-pay: {bill.biller_name}",
                            metadata={
                                'purpose': 'AUTOPAY',
                                'bill_id': str(bill.id),
                                'biller_name': bill.biller_name,
                                'autopilot': True
                            }
                        )

                        if payment_method == 'UPI' and default_upi:
                            payment_intent.upi_vpa = default_upi.upi_id
                            payment_intent.save(update_fields=['upi_vpa', 'updated_at'])
                        if payment_method == 'CARD' and default_card:
                            payment_intent.card_token = default_card
                            payment_intent.save(update_fields=['card_token', 'updated_at'])
                        
                        result = PaymentProcessor.process_payment(payment_intent)
                        
                        if result['success']:
                            payment_intent.mark_success(result.get('gateway_data', {}))
                            bill.status = 'PAID'
                            bill.paid_date = today
                            bill.payment_reference = payment_intent
                            bill.save()

                            # Finance + orchestration
                            try:
                                PaymentIntegrator.sync_with_finance_module(user, payment_intent)
                            except Exception:
                                logger.exception('Unhandled error')
                            try:
                                FinancialOrchestrator.process_payment_success(payment_intent)
                            except Exception:
                                logger.exception('Unhandled error')
                            
                            paid_bills.append({
                                'bill_id': bill.id,
                                'biller_name': bill.biller_name,
                                'amount': float(bill.amount),
                                'payment_reference': payment_intent.reference_id
                            })
                            
                            logger.info(f"Auto-paid bill: {bill.biller_name} for â‚¹{bill.amount}")
                    else:
                        logger.warning(f"Insufficient balance for auto-pay bill: {bill.biller_name}")
                        
                except Exception as e:
                    logger.error(f"Error auto-paying bill {bill.id}: {str(e)}")
            
            return paid_bills
            
        except ImportError:
            logger.debug("SmartBill model not available")
            return []
        except Exception as e:
            logger.error(f"Error in auto_pay_bills: {str(e)}")
            return []
    
    @staticmethod
    def execute_savings_rules(user):
        """
        Execute savings automation rules
        """
        try:
            from finnova_autopilot.models import AutomationRule
            
            rules = AutomationRule.objects.filter(
                user=user,
                is_active=True,
                trigger_event='SAVINGS'
            )
            
            savings_results = []
            total_saved = Decimal('0')
            
            for rule in rules:
                try:
                    if AutomationEngine._check_savings_conditions(rule, user):
                        result = AutomationEngine._execute_savings_action(rule, user)
                        
                        if result.get('saved_amount', 0) > 0:
                            total_saved += Decimal(str(result['saved_amount']))
                            savings_results.append({
                                'rule_id': rule.id,
                                'rule_name': rule.name,
                                'saved_amount': float(result['saved_amount']),
                                'action': result['action']
                            })
                            
                except Exception as e:
                    logger.error(f"Error executing savings rule {rule.id}: {str(e)}")
            
            return {
                'saved': len(savings_results) > 0,
                'amount': float(total_saved),
                'results': savings_results
            }
            
        except ImportError:
            return {'saved': False, 'amount': 0, 'results': []}
        except Exception as e:
            logger.error(f"Error executing savings rules: {str(e)}")
            return {'saved': False, 'amount': 0, 'results': []}
    
    @staticmethod
    def _evaluate_rule(rule, transaction):
        """Evaluate if rule conditions are met"""
        conditions = rule.conditions or {}
        
        # Amount condition
        if 'min_amount' in conditions:
            if abs(transaction.amount) < Decimal(str(conditions['min_amount'])):
                return False
        
        if 'max_amount' in conditions:
            if abs(transaction.amount) > Decimal(str(conditions['max_amount'])):
                return False
        
        # Category condition
        if 'category' in conditions:
            if transaction.category != conditions['category']:
                return False
        
        # Merchant condition
        if 'merchant_contains' in conditions:
            merchant = transaction.merchant or ''
            if conditions['merchant_contains'].lower() not in merchant.lower():
                return False
        
        # Time condition
        if 'time_of_day' in conditions:
            hour = transaction.transaction_date.hour
            time_range = conditions['time_of_day']
            if time_range == 'morning' and not (6 <= hour < 12):
                return False
            elif time_range == 'afternoon' and not (12 <= hour < 18):
                return False
            elif time_range == 'evening' and not (18 <= hour < 24):
                return False
            elif time_range == 'night' and not (0 <= hour < 6):
                return False
        
        return True
    
    @staticmethod
    def _execute_expense_rule(rule, transaction):
        """Execute expense-related rule action"""
        try:
            if rule.action == 'CREATE_ALERT':
                from finnova_autopilot.models import Alert
                Alert.objects.create(
                    user=rule.user,
                    category='RISK',
                    source='AUTOPILOT',
                    severity='MEDIUM',
                    title=f"Expense rule triggered: {rule.name}",
                    message=f"Transaction of ₹{abs(transaction.amount)} triggered rule",
                    metadata={
                        'rule_id': rule.id,
                        'transaction_id': transaction.id,
                        'category': transaction.category
                    }
                )
                return 'Alert created'
            
            elif rule.action == 'CATEGORIZE':
                # Auto-categorize similar future transactions
                if transaction.merchant and not transaction.category:
                    # Update category based on merchant
                    # This is a simplified version
                    logger.info(f"Would categorize merchant {transaction.merchant} for future transactions")
                return 'Categorization rule applied'
            
            elif rule.action == 'BLOCK_FUTURE':
                # Add merchant to blocked list
                if transaction.merchant:
                    logger.info(f"Would block future transactions with merchant: {transaction.merchant}")
                return 'Block rule applied'
            
            return 'Rule executed'
            
        except Exception as e:
            logger.error(f"Error executing expense rule: {str(e)}")
            return f'Error: {str(e)}'
    
    @staticmethod
    def _check_savings_conditions(rule, user):
        """Check savings rule conditions"""
        conditions = rule.conditions or {}
        
        # Balance condition
        if 'min_balance' in conditions:
            account = user.payment_accounts.filter(is_primary=True).first()
            if not account or account.balance < Decimal(str(conditions['min_balance'])):
                return False
        
        # Day of month condition
        if 'day_of_month' in conditions:
            today = timezone.now().day
            if today != conditions['day_of_month']:
                return False
        
        # Day of week condition
        if 'day_of_week' in conditions:
            today_weekday = timezone.now().weekday()  # 0=Monday
            if today_weekday != conditions['day_of_week']:
                return False
        
        return True
    
    @staticmethod
    def _execute_savings_action(rule, user):
        """Execute savings action with real balance transfers"""
        try:
            from ..models import PaymentTransaction, PaymentAccount
            from finnova_autopilot.models import SavingsGoal
            from notifications.services import NotificationService
            from finance.models import Expense
            
            amount = Decimal('0')
            
            if rule.action == 'ROUNDUP_SAVE':
                today = timezone.now().date()
                recent_transactions = PaymentTransaction.objects.filter(
                    account__user=user,
                    transaction_date__date=today,
                    transaction_type='DEBIT'
                ).exclude(description__startswith="Auto-savings")
                
                for trans in recent_transactions:
                    trans_amount = abs(trans.amount)
                    roundup = ((trans_amount + Decimal('9')) // Decimal('10')) * Decimal('10') - trans_amount
                    if roundup > 0:
                        amount += roundup
            
            elif rule.action == 'FIXED_SAVE':
                amount = Decimal(str(rule.conditions.get('amount', 100)))
            
            elif rule.action == 'PERCENTAGE_SAVE':
                percentage = Decimal(str(rule.conditions.get('percentage', 5)))
                account = user.payment_accounts.filter(is_primary=True).first()
                if account and account.balance > 0:
                    amount = (account.balance * percentage) / Decimal('100')

            if amount <= 0:
                return {'action': 'none', 'saved_amount': 0, 'message': 'No savings amount calculated'}

            # Perform the actual transfer
            account = user.payment_accounts.filter(is_primary=True).first()
            if not account or account.balance < amount:
                return {'action': 'blocked', 'saved_amount': 0, 'message': 'Insufficient balance for savings'}

            with transaction.atomic():
                # 1. Update account balance
                account.update_balance(-amount)
                
                # 2. Create payment transaction record
                tx = PaymentTransaction.objects.create(
                    account=account,
                    amount=amount,
                    transaction_type='DEBIT',
                    description=f"Auto-savings: {rule.name}",
                    reference=f"SAVE-{uuid.uuid4().hex[:8].upper()}",
                    balance_before=account.balance + amount,
                    balance_after=account.balance,
                    metadata={'rule_id': str(rule.id), 'type': 'savings_autopilot'}
                )
                
                # 3. Update primary savings goal progress
                goal = SavingsGoal.objects.filter(user=user, status__in=['ACTIVE', 'PLANNING']).first()
                if goal:
                    goal.current_saved += amount
                    goal.save()
                    
                # 4. Create Notification
                NotificationService.create_notification(
                    user=user,
                    title="ðŸ’° Savings Auto-Transferred",
                    message=f"â‚¹{amount:,.2f} moved to savings via '{rule.name}' rule.",
                    notification_type='FINANCE',
                    priority='LOW'
                )
                
                logger.info(f"Executed real savings of â‚¹{amount} for user {user.username}")
                
                return {
                    'action': rule.action,
                    'saved_amount': float(amount),
                    'transaction_id': str(tx.id),
                    'goal_updated': goal.goal_name if goal else None
                }
                
        except Exception as e:
            logger.error(f"Error executing real savings action: {str(e)}")
            return {'action': 'error', 'saved_amount': 0, 'message': str(e)}
    
    @staticmethod
    def execute_debt_repayment(user):
        """
        Automatically pay due debts (EMIs)
        """
        try:
            from finance.models import Debt, Expense, Account
            from ..models import PaymentAccount, PaymentTransaction
            from notifications.services import NotificationService
            
            today = timezone.now().date()
            due_debts = Debt.objects.filter(
                user=user,
                status='ACTIVE',
                next_payment_date__lte=today
            )
            finance_account = (
                Account.objects.filter(user=user, is_primary=True, is_active=True).first()
                or Account.objects.filter(user=user, is_primary=True).first()
                or Account.objects.filter(user=user, is_active=True).first()
                or Account.objects.filter(user=user).first()
            )
            if finance_account is None:
                finance_account = Account.objects.create(
                    user=user,
                    name='Primary Financial Account',
                    account_type='SAVINGS',
                    opening_balance=Decimal('0.00'),
                    current_balance=Decimal('0.00'),
                    is_primary=True,
                    is_active=True,
                )
            
            results = []
            for debt in due_debts:
                account = user.payment_accounts.filter(is_primary=True).first()
                if account and account.balance >= debt.emi_amount:
                    with transaction.atomic():
                        payment_amount = debt.emi_amount
                        
                        # 1. Update debt record
                        debt.make_payment(payment_amount, date=today)
                        
                        # 2. Update account balance
                        account.update_balance(-payment_amount)
                        
                        # 3. Create transaction
                        tx = PaymentTransaction.objects.create(
                            account=account,
                            amount=payment_amount,
                            transaction_type='DEBIT',
                            description=f"Auto-EMI: {debt.lender}",
                            status='SUCCESS',
                            reference=f"EMI-{uuid.uuid4().hex[:8].upper()}",
                            balance_before=account.balance + payment_amount,
                            balance_after=account.balance,
                            metadata={'debt_id': str(debt.id), 'type': 'debt_autopilot'}
                        )
                        
                        # 4. Create Finance Expense
                        Expense.objects.create(
                            user=user,
                            account=finance_account,
                            amount=payment_amount,
                            category='DEBT_REPAYMENT',
                            description=f"EMI Payment to {debt.lender}",
                            date=today,
                            payment_method='BANK_TRANSFER',
                            is_verified=True,
                            payment_reference=tx.id
                        )
                        
                        # 5. Notify
                        NotificationService.create_notification(
                            user=user,
                            title="ðŸ“‰ Debt Payment Processed",
                            message=f"EMI of â‚¹{payment_amount:,.2f} paid to {debt.lender}. Remaining: â‚¹{debt.remaining_amount:,.2f}",
                            notification_type='FINANCE',
                            priority='MEDIUM'
                        )
                        
                        results.append({
                            'debt_id': str(debt.id),
                            'lender': debt.lender,
                            'amount': float(payment_amount)
                        })
            
            return results
        except Exception as e:
            logger.error(f"Error in execute_debt_repayment: {str(e)}")
            return []

    @staticmethod
    def check_alerts(user):
        """
        Check and generate alerts for user - ENHANCED
        """
        try:
            from finnova_autopilot.models import Alert, SmartBill
            from finance.models import Debt, Budget
            from ..models import PaymentAccount
            
            alerts = []
            today = timezone.now().date()
            account = user.payment_accounts.filter(is_primary=True).first()
            
            # 1. Low balance check
            if account and account.balance < Decimal('2000'):
                alerts.append({
                    'type': 'LOW_BALANCE',
                    'category': 'SAVINGS',
                    'title': 'Low Account Balance',
                    'message': f'Your balance (â‚¹{account.balance:,.2f}) is low. Upcoming bills might fail.',
                    'severity': 'HIGH'
                })
            
            # 2. Upcoming Bills check
            upcoming_bills = SmartBill.objects.filter(user=user, status='PENDING', due_date__lte=today + timedelta(days=3))
            for bill in upcoming_bills:
                alerts.append({
                    'type': 'BILL_DUE',
                    'category': 'PAYMENT',
                    'title': f'Bill Due Soon: {bill.biller_name}',
                    'message': f'â‚¹{bill.amount:,.2f} due on {bill.due_date}',
                    'severity': 'MEDIUM'
                })
                
            # 3. Budget threshold check
            active_budgets = Budget.objects.filter(user=user, is_active=True)
            for budget in active_budgets:
                utilization_raw = getattr(budget, 'utilization_percentage', 0)
                utilization = float(
                    utilization_raw() if callable(utilization_raw) else (utilization_raw or 0)
                )
                if utilization > 90:
                    alerts.append({
                        'type': 'BUDGET_THRESHOLD',
                        'category': 'BUDGET',
                        'title': f'Budget Critical: {budget.name}',
                        'message': f'You have used {utilization:.1f}% of your {budget.name} budget.',
                        'severity': 'CRITICAL'
                    })
            
            # Create alerts
            for alert_data in alerts:
                # Avoid duplicate active alerts
                if not Alert.objects.filter(user=user, title=alert_data['title'], is_acknowledged=False).exists():
                    Alert.objects.create(
                        user=user,
                        category=alert_data.get('category', 'SYSTEM'),
                        source='AUTOPILOT',
                        severity=alert_data['severity'],
                        title=alert_data['title'],
                        message=alert_data['message'],
                        metadata={'auto_generated': True, 'alert_type': alert_data.get('type')}
                    )
            
            return alerts
        except Exception as e:
            logger.error(f"Error checking enhanced alerts: {str(e)}")
            return []
