# payments_core/services/risk_analyzer.py
import logging
from decimal import Decimal
from django.utils import timezone
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class RiskAnalyzer:
    """Analyze payment transactions for fraud and risk"""
    
    @staticmethod
    def analyze_transaction(transaction):
        """
        Analyze a transaction for potential fraud
        Returns: dict with risk_score (0-100) and flags
        """
        try:
            risk_score = 0
            flags = []
            
            # Check 1: Unusual amount
            avg_transaction = RiskAnalyzer._get_user_avg_transaction(transaction.account.user)
            if avg_transaction and transaction.amount > avg_transaction * Decimal('5'):
                risk_score += 30
                flags.append('Unusually large transaction')
            
            # Check 2: Unusual time
            if not RiskAnalyzer._is_normal_transaction_time():
                risk_score += 20
                flags.append('Transaction at unusual hour')
            
            # Check 3: Multiple rapid transactions
            recent_count = RiskAnalyzer._count_recent_transactions(transaction.account.user)
            if recent_count > 5:  # More than 5 transactions in last hour
                risk_score += 25
                flags.append('Multiple rapid transactions')
            
            # Check 4: New merchant/category
            if RiskAnalyzer._is_new_category(transaction.account.user, transaction.category):
                risk_score += 15
                flags.append('New merchant/category')
            
            # Check 5: International transaction (if applicable)
            if RiskAnalyzer._is_international(transaction):
                risk_score += 20
                flags.append('International transaction')
            
            # Cap risk score at 100
            risk_score = min(risk_score, 100)
            
            return {
                'risk_score': risk_score,
                'risk_level': RiskAnalyzer._get_risk_level(risk_score),
                'flags': flags,
                'is_suspicious': risk_score >= 60
            }
            
        except Exception as e:
            logger.error(f"Error analyzing transaction risk: {str(e)}")
            return {
                'risk_score': 0,
                'risk_level': 'LOW',
                'flags': [],
                'is_suspicious': False
            }
    
    @staticmethod
    def _get_user_avg_transaction(user):
        """Get user's average transaction amount"""
        from ..models import PaymentTransaction
        
        try:
            transactions = PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__gte=timezone.now() - timedelta(days=30)
            ).exclude(transaction_type='CREDIT')
            
            if transactions.exists():
                total = sum(t.amount for t in transactions)
                return abs(total) / transactions.count()
        except Exception:
            logger.exception('Unhandled error')
        return None
    
    @staticmethod
    def _is_normal_transaction_time():
        """Check if current time is normal for transactions"""
        now = timezone.localtime()
        # Normal hours: 8 AM to 10 PM
        return 8 <= now.hour < 22
    
    @staticmethod
    def _count_recent_transactions(user):
        """Count recent transactions in last hour"""
        from ..models import PaymentTransaction
        
        try:
            one_hour_ago = timezone.now() - timedelta(hours=1)
            return PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__gte=one_hour_ago
            ).count()
        except Exception:
            return 0
    
    @staticmethod
    def _is_new_category(user, category):
        """Check if category is new for user"""
        from ..models import PaymentTransaction
        
        if not category:
            return False
            
        try:
            has_previous = PaymentTransaction.objects.filter(
                account__user=user,
                category=category
            ).exists()
            return not has_previous
        except Exception:
            return False
    
    @staticmethod
    def _is_international(transaction):
        """Check if transaction appears to be international"""
        # Check metadata or description for international indicators
        if transaction.metadata and transaction.metadata.get('is_international'):
            return True
        
        international_indicators = ['international', 'overseas', 'foreign', 'abroad']
        description = transaction.description.lower() if transaction.description else ''
        return any(indicator in description for indicator in international_indicators)
    
    @staticmethod
    def _get_risk_level(score):
        """Convert risk score to level"""
        if score >= 80:
            return 'CRITICAL'
        elif score >= 60:
            return 'HIGH'
        elif score >= 40:
            return 'MEDIUM'
        elif score >= 20:
            return 'LOW'
        else:
            return 'VERY_LOW'
    
    @staticmethod
    def analyze_user_behavior(user):
        """Analyze user's overall transaction behavior"""
        from ..models import PaymentTransaction
        
        try:
            # Get last 30 days transactions
            thirty_days_ago = timezone.now() - timedelta(days=30)
            transactions = PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__gte=thirty_days_ago
            )
            
            if not transactions.exists():
                return {
                    'total_transactions': 0,
                    'total_spent': 0,
                    'avg_transaction': 0,
                    'frequent_categories': [],
                    'behavior_score': 100  # No transactions = good score
                }
            
            # Calculate metrics
            total_spent = sum(abs(t.amount) for t in transactions if t.transaction_type == 'DEBIT')
            avg_transaction = total_spent / transactions.filter(transaction_type='DEBIT').count()
            
            # Get frequent categories
            categories = {}
            for t in transactions:
                if t.category:
                    categories[t.category] = categories.get(t.category, 0) + 1
            
            frequent_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)[:5]
            
            # Calculate behavior score (0-100, higher is better)
            behavior_score = RiskAnalyzer._calculate_behavior_score(
                transactions.count(),
                avg_transaction,
                len(set(t.category for t in transactions if t.category))
            )
            
            return {
                'total_transactions': transactions.count(),
                'total_spent': float(total_spent),
                'avg_transaction': float(avg_transaction),
                'frequent_categories': frequent_categories,
                'behavior_score': behavior_score
            }
            
        except Exception as e:
            logger.error(f"Error analyzing user behavior: {str(e)}")
            return {
                'total_transactions': 0,
                'total_spent': 0,
                'avg_transaction': 0,
                'frequent_categories': [],
                'behavior_score': 0
            }
    
    @staticmethod
    def _calculate_behavior_score(transaction_count, avg_amount, unique_categories):
        """Calculate user behavior score"""
        score = 100
        
        # Penalize for too many transactions
        if transaction_count > 50:
            score -= 20
        elif transaction_count > 100:
            score -= 40
        
        # Penalize for very high average transaction
        if avg_amount > 10000:  # ₹10,000
            score -= 15
        elif avg_amount > 50000:  # ₹50,000
            score -= 30
        
        # Reward for diverse categories (shows normal spending)
        if unique_categories >= 3:
            score += 10
        elif unique_categories <= 1:
            score -= 10
        
        return max(0, min(100, score))