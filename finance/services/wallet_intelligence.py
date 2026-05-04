# finance/services/wallet_intelligence.py - COMPLETELY REWRITTEN
from decimal import Decimal, ROUND_DOWN
from datetime import timedelta
import uuid
from django.utils import timezone
from django.db import transaction as db_transaction
from django.db.models import Sum, Q
import logging

from payments_core.models import PaymentAccount as Wallet, PaymentTransaction as AutopilotTransaction
from analytics_ai.algorithms import savings_monthly_score, financial_personality, generate_financial_tips
from finnova_autopilot.services import log_audit_event
from notifications.services import create_notification
from ..models import Income, Expense, FinancialMetric
from .finance_engine import FinanceEngine

logger = logging.getLogger(__name__)

class WalletIntelligence:
    """AI-powered wallet management and optimization"""
    
    @staticmethod
    def safe_wallet_transfer(sender_wallet, receiver_wallet, amount, reason, 
                           user=None, category='TRANSFER'):
        """
        Safely transfers money between wallets with validations, logging, and protection rules
        
        Args:
            sender_wallet: Source wallet object
            receiver_wallet: Destination wallet object
            amount: Decimal amount to transfer
            reason: String description
            user: User object (optional, defaults to sender_wallet.user)
            category: Transaction category
        """
        amount = Decimal(amount)
        
        # Validation checks
        if not sender_wallet.is_active:
            raise ValueError("Sender account is not active")
        
        if not receiver_wallet.is_active:
            raise ValueError("Receiver account is not active")
        
        if sender_wallet.balance < amount:
            raise ValueError(f"Insufficient funds. Available: ₹{sender_wallet.balance}, Required: ₹{amount}")
        
        # Protection check: limit maximum transfer amount
        MAX_TRANSFER_LIMIT = Decimal('1000000.00')
        if amount > MAX_TRANSFER_LIMIT:
            raise ValueError(f"Transfer amount exceeds maximum limit of ₹{MAX_TRANSFER_LIMIT}")
        
        # Daily limit check (₹50,000 per day)
        today = timezone.now().date()
        daily_transfers = AutopilotTransaction.objects.filter(
            account=sender_wallet,
            transaction_type='DEBIT',
            transaction_date__date=today,
            category='TRANSFER'
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        
        if daily_transfers + amount > Decimal('50000.00'):
            raise ValueError(f"Daily transfer limit exceeded. Transferred today: ₹{daily_transfers}")
        
        # Perform transfer in a transaction
        with db_transaction.atomic():
            sender_before = sender_wallet.balance
            receiver_before = receiver_wallet.balance

            # Update balances using the canonical atomic updater
            sender_wallet.update_balance(-amount)
            receiver_wallet.update_balance(amount)

            sender_after = sender_wallet.balance
            receiver_after = receiver_wallet.balance

            ref = uuid.uuid4().hex[:12]

            # Create transactions for both wallets (PaymentTransaction requires reference + balance snapshots)
            AutopilotTransaction.objects.create(
                account=sender_wallet,
                organization=getattr(sender_wallet, 'organization', None),
                amount=amount,
                transaction_type='DEBIT',
                description=f"Transfer to {receiver_wallet.account_type}: {reason}",
                category=category,
                status='SUCCESS',
                reference=f"XFER-{ref}-D",
                balance_before=sender_before,
                balance_after=sender_after,
                metadata={
                    'receiver_account_id': str(receiver_wallet.id),
                    'reason': reason,
                    'type': 'INTERNAL_TRANSFER'
                }
            )
            
            AutopilotTransaction.objects.create(
                account=receiver_wallet,
                organization=getattr(receiver_wallet, 'organization', None),
                amount=amount,
                transaction_type='CREDIT',
                description=f"Transfer from {sender_wallet.account_type}: {reason}",
                category=category,
                status='SUCCESS',
                reference=f"XFER-{ref}-C",
                balance_before=receiver_before,
                balance_after=receiver_after,
                metadata={
                    'sender_account_id': str(sender_wallet.id),
                    'reason': reason,
                    'type': 'INTERNAL_TRANSFER'
                }
            )
            
            # Log audit event
            log_audit_event(
                actor=sender_wallet.user,
                action="ACCOUNT_TRANSFER",
                severity="MEDIUM",
                description=f"Account transfer: ₹{amount} from {sender_wallet.account_type} to {receiver_wallet.account_type}",
                metadata={
                    "amount": str(amount),
                    "sender_account": sender_wallet.account_type,
                    "receiver_account": receiver_wallet.account_type,
                    "reason": reason
                }
            )
            
            # Send notification
            create_notification(
                user=sender_wallet.user,
                title="Transfer Completed",
                message=f"₹{amount} transferred to {receiver_wallet.account_type} account",
                notification_type='TRANSACTION',
                priority='LOW'
            )
        
        logger.info(f"Transfer successful: ₹{amount} from user {sender_wallet.user.username}")
        return True
    
    @staticmethod
    def auto_protect_savings(user):
        """
        Automatically moves funds to savings wallet based on user spending patterns
        and financial health
        """
        try:
            # Get user wallets
            main_wallet = Wallet.objects.get(user=user, account_type='WALLET')
            savings_wallet, created = Wallet.objects.get_or_create(
                user=user,
                account_type='SAVINGS',
                defaults={
                    'balance': 0,
                    'currency': 'INR',
                    'is_active': True
                }
            )
            
            # Calculate current month's financial metrics
            today = timezone.now().date()
            month_start = today.replace(day=1)
            
            # Calculate using FinanceEngine
            monthly_summary = FinanceEngine.calculate_monthly_summary(user, today.year, today.month)
            total_income = monthly_summary['totals']['income']
            total_expense = monthly_summary['totals']['expense']
            
            # Calculate savings score using AI
            score = savings_monthly_score(total_income, total_expense)
            
            # Determine personality
            personality = financial_personality(score)
            
            # Get financial tips
            tips = generate_financial_tips(score)
            
            # Decision logic based on personality and score
            protect_amount = Decimal('0.00')
            recommendation = None
            
            if personality == 'overspender' and score < 30:
                # Urgent protection needed
                protect_amount = main_wallet.balance * Decimal('0.15')  # 15% of balance
                recommendation = "Urgent savings needed due to overspending pattern"
            
            elif personality == 'spender' and 30 <= score < 50:
                # Moderate protection
                protect_amount = main_wallet.balance * Decimal('0.10')  # 10% of balance
                recommendation = "Regular savings recommended"
            
            elif personality == 'balanced' and 50 <= score < 80:
                # Standard savings
                protect_amount = main_wallet.balance * Decimal('0.05')  # 5% of balance
                recommendation = "Maintaining good savings habit"
            
            elif personality == 'saver' and score >= 80:
                # Already saving well, small boost
                protect_amount = main_wallet.balance * Decimal('0.03')  # 3% of balance
                recommendation = "Excellent savings behavior - small auto-save"
            
            # Apply minimum and maximum limits
            MIN_PROTECT = Decimal('100.00')
            MAX_PROTECT = Decimal('10000.00')
            
            if protect_amount < MIN_PROTECT:
                protect_amount = MIN_PROTECT
            
            if protect_amount > MAX_PROTECT:
                protect_amount = MAX_PROTECT
            
            # Ensure we don't take more than available (keep minimum ₹500 in main)
            MIN_MAIN_BALANCE = Decimal('500.00')
            available_for_protect = main_wallet.balance - MIN_MAIN_BALANCE
            
            if available_for_protect > MIN_PROTECT:
                protect_amount = min(protect_amount, available_for_protect)
                
                # Execute transfer
                WalletIntelligence.safe_wallet_transfer(
                    sender_wallet=main_wallet,
                    receiver_wallet=savings_wallet,
                    amount=protect_amount.quantize(Decimal('0.01'), rounding=ROUND_DOWN),
                    reason=f"Auto-savings protection ({personality}, score: {score})",
                    user=user,
                    category='SAVINGS'
                )
                
                # Create comprehensive notification
                create_notification(
                    user=user,
                    title="💰 Auto-Savings Activated",
                    message=f"₹{protect_amount} moved to savings. {recommendation}",
                    notification_type='SAVINGS',
                    priority='MEDIUM',
                    metadata={
                        'amount': str(protect_amount),
                        'savings_score': score,
                        'personality': personality,
                        'tips': tips
                    }
                )
                
                return {
                    'protected': True,
                    'amount': protect_amount,
                    'savings_score': score,
                    'personality': personality,
                    'recommendation': recommendation,
                    'tips': tips
                }
            
            return {
                'protected': False,
                'reason': 'Insufficient funds for auto-savings',
                'savings_score': score,
                'personality': personality,
                'tips': tips
            }
            
        except Exception as e:
            logger.error(f"Auto-protect savings failed: {str(e)}")
            return {'protected': False, 'error': str(e)}
    
    @staticmethod
    def wallet_suggestions(user):
        """
        Provides AI-powered wallet suggestions based on user behavior
        Returns comprehensive suggestions with priorities
        """
        suggestions = []
        
        try:
            # Get all user wallets
            wallets = Wallet.objects.filter(user=user)
            main_wallet = wallets.filter(account_type='WALLET').first()
            savings_wallet = wallets.filter(account_type='SAVINGS').first()
            
            if not main_wallet:
                suggestions.append({
                    'priority': 'HIGH',
                    'title': 'Setup Main Wallet',
                    'description': 'Create a main wallet to start managing your finances',
                    'action': 'CREATE_WALLET',
                    'action_data': {'wallet_type': 'MAIN'}
                })
                return suggestions
            
            # 1. Low balance check
            if main_wallet.balance < Decimal('1000.00'):
                suggestions.append({
                    'priority': 'HIGH',
                    'title': 'Low Wallet Balance',
                    'description': f'Your main wallet balance is low (₹{main_wallet.balance}). Consider adding funds.',
                    'action': 'ADD_FUNDS',
                    'action_data': {'amount': '5000', 'source': 'BANK_TRANSFER'}
                })
            
            # 2. No savings wallet check
            if not savings_wallet:
                suggestions.append({
                    'priority': 'MEDIUM',
                    'title': 'Create Savings Wallet',
                    'description': 'Create a savings wallet to start building your emergency fund',
                    'action': 'CREATE_WALLET',
                    'action_data': {'wallet_type': 'SAVINGS'}
                })
            elif savings_wallet.balance < Decimal('10000.00'):
                # 3. Insufficient savings check (less than ₹10,000)
                suggestions.append({
                    'priority': 'MEDIUM',
                    'title': 'Boost Your Savings',
                    'description': f'Your savings (₹{savings_wallet.balance}) are below recommended emergency fund level',
                    'action': 'TRANSFER_TO_SAVINGS',
                    'action_data': {'amount': '5000', 'from_wallet': main_wallet.id}
                })
            
            # 4. High main wallet balance (idle money)
            if main_wallet.balance > Decimal('50000.00'):
                suggestions.append({
                    'priority': 'LOW',
                    'title': 'Consider Investment',
                    'description': f'You have ₹{main_wallet.balance} idle in your main wallet. Consider investing or moving to savings.',
                    'action': 'INVESTMENT_SUGGESTION',
                    'action_data': {'amount': str(main_wallet.balance * Decimal('0.3'))}
                })
            
            # 5. Check transaction patterns
            today = timezone.now().date()
            week_ago = today - timedelta(days=7)
            
            weekly_transactions = AutopilotTransaction.objects.filter(
                account__user=user,
                transaction_date__date__gte=week_ago
            ).count()
            
            if weekly_transactions < 2:
                suggestions.append({
                    'priority': 'LOW',
                    'title': 'Low Transaction Activity',
                    'description': 'Few transactions this week. Consider reviewing your financial activity.',
                    'action': 'REVIEW_FINANCES',
                    'action_data': {}
                })
            
            # 6. Get AI-based suggestions from analytics
            try:
                from analytics_ai.services import get_wallet_insights
                ai_insights = get_wallet_insights(user)
                if ai_insights:
                    suggestions.extend(ai_insights)
            except ImportError:
                logger.exception('Unhandled error')
            
            # Sort by priority (HIGH > MEDIUM > LOW)
            priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2}
            suggestions.sort(key=lambda x: priority_order.get(x['priority'], 3))
            
            return suggestions
            
        except Exception as e:
            logger.error(f"Wallet suggestions failed: {str(e)}")
            return [{
                'priority': 'HIGH',
                'title': 'System Error',
                'description': 'Unable to generate wallet suggestions. Please try again.',
                'action': 'CONTACT_SUPPORT',
                'action_data': {}
            }]
    
    @staticmethod
    def optimize_wallet_allocation(user, target_allocation=None):
        """
        Optimize wallet allocation based on user's financial goals and patterns
        """
        if target_allocation is None:
            target_allocation = {
                'MAIN': Decimal('0.40'),    # 40% for daily expenses
                'SAVINGS': Decimal('0.30'),  # 30% for savings
                'INVESTMENT': Decimal('0.20'), # 20% for investments
                'BILLS': Decimal('0.10')     # 10% for bill payments
            }
        
        try:
            # Get current balances
            wallets = {w.account_type: w for w in Wallet.objects.filter(user=user)}
            total_balance = sum(w.balance for w in wallets.values())
            
            if total_balance <= 0:
                return {'optimized': False, 'reason': 'No funds to optimize'}
            
            # Calculate current allocation
            current_allocation = {}
            for wallet_type, wallet in wallets.items():
                current_allocation[wallet_type] = wallet.balance / total_balance if total_balance > 0 else Decimal('0')
            
            # Calculate transfers needed
            transfers = []
            for wallet_type, target_percent in target_allocation.items():
                target_amount = total_balance * target_percent
                
                if wallet_type in wallets:
                    current_amount = wallets[wallet_type].balance
                    difference = target_amount - current_amount
                    
                    if difference > Decimal('100.00'):  # Minimum transfer amount
                        # Find source wallet with excess
                        for source_type, source_wallet in wallets.items():
                            if source_type != wallet_type and source_wallet.balance > target_allocation.get(source_type, Decimal('0')) * total_balance:
                                transfer_amount = min(
                                    difference,
                                    source_wallet.balance - (target_allocation.get(source_type, Decimal('0')) * total_balance)
                                )
                                
                                if transfer_amount > Decimal('100.00'):
                                    transfers.append({
                                        'from': source_wallet,
                                        'to': wallets[wallet_type],
                                        'amount': transfer_amount,
                                        'reason': f'Optimization: {source_type} → {wallet_type}'
                                    })
                                    difference -= transfer_amount
                
                elif difference > Decimal('1000.00'):
                    # Need to create this wallet type
                    suggestions.append({
                        'priority': 'MEDIUM',
                        'title': f'Create {wallet_type} Wallet',
                        'description': f'Create a {wallet_type.lower()} wallet for better fund allocation',
                        'action': 'CREATE_WALLET',
                        'action_data': {'wallet_type': wallet_type}
                    })
            
            # Execute transfers
            executed_transfers = []
            for transfer in transfers:
                try:
                    WalletIntelligence.safe_wallet_transfer(
                        sender_wallet=transfer['from'],
                        receiver_wallet=transfer['to'],
                        amount=transfer['amount'],
                        reason=transfer['reason'],
                        user=user,
                        category='OPTIMIZATION'
                    )
                    executed_transfers.append(transfer)
                except Exception as e:
                    logger.error(f"Optimization transfer failed: {str(e)}")
            
            if executed_transfers:
                return {
                    'optimized': True,
                    'transfers': len(executed_transfers),
                    'message': f'Optimized {len(executed_transfers)} wallet allocations'
                }
            
            return {
                'optimized': False,
                'reason': 'No optimization needed or insufficient funds',
                'current_allocation': current_allocation,
                'target_allocation': target_allocation
            }
            
        except Exception as e:
            logger.error(f"Wallet optimization failed: {str(e)}")
            return {'optimized': False, 'error': str(e)}