# payments_core/services/ai_predictor.py
import logging
from decimal import Decimal
from django.utils import timezone
from datetime import datetime, timedelta
import random  # For demo predictions - replace with actual ML in production

logger = logging.getLogger(__name__)

class AIPredictor:
    """AI/ML predictions for payments and finances"""
    
    @staticmethod
    def predict_cashflow(user, days=30):
        """Predict cash flow for next N days"""
        try:
            from ..models import PaymentTransaction, Subscription
            
            # Get historical data
            ninety_days_ago = timezone.now() - timedelta(days=90)
            transactions = PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__gte=ninety_days_ago
            )
            
            # Get upcoming subscriptions
            upcoming_subscriptions = Subscription.objects.filter(
                user=user,
                status='ACTIVE',
                next_billing_date__lte=timezone.now().date() + timedelta(days=days)
            )
            
            # Simple prediction algorithm (replace with actual ML)
            daily_spending = AIPredictor._calculate_daily_spending(transactions)
            current_balance = user.payment_accounts.filter(is_primary=True).first().balance
            
            # Generate predictions
            predictions = []
            balance = float(current_balance)
            today = timezone.now().date()
            
            for day in range(days):
                date = today + timedelta(days=day)
                
                # Daily spending prediction
                daily_prediction = daily_spending * random.uniform(0.8, 1.2)  # Add randomness
                
                # Check for subscription payments
                subscription_payments = sum(
                    float(sub.amount) for sub in upcoming_subscriptions 
                    if sub.next_billing_date == date
                )
                
                # Update balance
                balance -= (daily_prediction + subscription_payments)
                
                predictions.append({
                    'date': date.isoformat(),
                    'predicted_spending': round(daily_prediction, 2),
                    'subscription_payments': round(subscription_payments, 2),
                    'predicted_balance': round(balance, 2)
                })
            
            return {
                'success': True,
                'predictions': predictions,
                'current_balance': float(current_balance),
                'average_daily_spending': round(daily_spending, 2),
                'upcoming_subscriptions': [
                    {
                        'name': sub.name,
                        'amount': float(sub.amount),
                        'date': sub.next_billing_date.isoformat()
                    }
                    for sub in upcoming_subscriptions
                ]
            }
            
        except Exception as e:
            logger.error(f"Error predicting cashflow: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'predictions': []
            }
    
    @staticmethod
    def _calculate_daily_spending(transactions):
        """Calculate average daily spending from transactions"""
        try:
            debit_transactions = [t for t in transactions if t.transaction_type == 'DEBIT']
            
            if not debit_transactions:
                return 0
            
            total_spent = sum(abs(t.amount) for t in debit_transactions)
            
            # Get date range
            dates = [t.transaction_date.date() for t in debit_transactions]
            if dates:
                days_count = (max(dates) - min(dates)).days + 1
                return float(total_spent) / max(days_count, 1)
            
            return float(total_spent) / 30  # Fallback to 30 days
            
        except Exception:
            return 0
    
    @staticmethod
    def analyze_spending_patterns(user):
        """Analyze spending patterns and provide insights"""
        try:
            from ..models import PaymentTransaction
            
            # Get last 90 days of transactions
            ninety_days_ago = timezone.now() - timedelta(days=90)
            transactions = PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__gte=ninety_days_ago,
                transaction_type='DEBIT'
            )
            
            if not transactions.exists():
                return {
                    'total_insights': 0,
                    'insights': [],
                    'summary': 'No spending data available'
                }
            
            insights = []
            
            # Insight 1: High spending category
            categories = {}
            for t in transactions:
                category = t.category or 'UNCATEGORIZED'
                categories[category] = categories.get(category, 0) + float(abs(t.amount))
            
            if categories:
                top_category = max(categories.items(), key=lambda x: x[1])
                insights.append({
                    'type': 'HIGH_SPENDING_CATEGORY',
                    'title': f'High spending in {top_category[0]}',
                    'description': f'You spent ₹{top_category[1]:,.2f} on {top_category[0]} in the last 90 days',
                    'severity': 'MEDIUM',
                    'suggestion': 'Consider setting a budget for this category'
                })
            
            # Insight 2: Spending trend
            monthly_totals = AIPredictor._calculate_monthly_totals(transactions)
            if len(monthly_totals) >= 2:
                last_month = monthly_totals[-1]
                prev_month = monthly_totals[-2] if len(monthly_totals) >= 2 else 0
                
                if last_month > prev_month * 1.3:  # 30% increase
                    insights.append({
                        'type': 'SPENDING_INCREASE',
                        'title': 'Spending increased significantly',
                        'description': f'Your spending increased by {(last_month/prev_month-1)*100:.0f}% compared to last month',
                        'severity': 'HIGH',
                        'suggestion': 'Review your recent expenses'
                    })
            
            # Insight 3: Unusual transactions
            unusual_transactions = AIPredictor._find_unusual_transactions(transactions)
            if unusual_transactions:
                insights.append({
                    'type': 'UNUSUAL_TRANSACTIONS',
                    'title': 'Unusual transaction detected',
                    'description': f'Found {len(unusual_transactions)} transactions significantly larger than your average',
                    'severity': 'MEDIUM',
                    'suggestion': 'Verify these transactions are legitimate'
                })
            
            # Insight 4: Weekend vs weekday spending
            weekend_spending, weekday_spending = AIPredictor._analyze_weekend_spending(transactions)
            if weekend_spending > weekday_spending * 1.5:  # 50% more on weekends
                insights.append({
                    'type': 'WEEKEND_SPENDING',
                    'title': 'Higher spending on weekends',
                    'description': 'You tend to spend more on weekends than weekdays',
                    'severity': 'LOW',
                    'suggestion': 'Plan weekend activities with a budget'
                })
            
            return {
                'total_insights': len(insights),
                'insights': insights[:5],  # Limit to 5 insights
                'summary': f'Found {len(insights)} insights in your spending patterns',
                'total_spent': sum(float(abs(t.amount)) for t in transactions),
                'transaction_count': transactions.count()
            }
            
        except Exception as e:
            logger.error(f"Error analyzing spending patterns: {str(e)}")
            return {
                'total_insights': 0,
                'insights': [],
                'summary': 'Unable to analyze spending patterns',
                'error': str(e)
            }
    
    @staticmethod
    def _calculate_monthly_totals(transactions):
        """Calculate monthly spending totals"""
        monthly = {}
        for t in transactions:
            month_key = t.transaction_date.strftime('%Y-%m')
            monthly[month_key] = monthly.get(month_key, 0) + float(abs(t.amount))
        
        # Sort by month
        return [amount for _, amount in sorted(monthly.items())]
    
    @staticmethod
    def _find_unusual_transactions(transactions):
        """Find transactions that are unusually large"""
        if not transactions:
            return []
        
        amounts = [float(abs(t.amount)) for t in transactions]
        avg_amount = sum(amounts) / len(amounts)
        std_amount = (sum((x - avg_amount) ** 2 for x in amounts) / len(amounts)) ** 0.5
        
        unusual = []
        for t in transactions:
            if float(abs(t.amount)) > avg_amount + (2 * std_amount):  # More than 2 standard deviations
                unusual.append(t)
        
        return unusual
    
    @staticmethod
    def _analyze_weekend_spending(transactions):
        """Analyze weekend vs weekday spending"""
        weekend_total = 0
        weekday_total = 0
        weekend_count = 0
        weekday_count = 0
        
        for t in transactions:
            amount = float(abs(t.amount))
            weekday = t.transaction_date.weekday()  # 0=Monday, 6=Sunday
            
            if weekday >= 5:  # Saturday or Sunday
                weekend_total += amount
                weekend_count += 1
            else:
                weekday_total += amount
                weekday_count += 1
        
        # Calculate averages
        weekend_avg = weekend_total / max(weekend_count, 1)
        weekday_avg = weekday_total / max(weekday_count, 1)
        
        return weekend_avg, weekday_avg
    
    @staticmethod
    def detect_anomalies(user):
        """Detect anomalous transactions and log security events"""
        try:
            from ..models import PaymentTransaction
            from ..services.risk_analyzer import RiskAnalyzer
            from audit.models import AuditLog
            from notifications.services import NotificationService
            
            # Get recent transactions
            thirty_days_ago = timezone.now() - timedelta(days=30)
            transactions = PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__gte=thirty_days_ago,
                transaction_type='DEBIT'
            ).order_by('-transaction_date')[:50]
            
            anomalies = []
            
            for transaction in transactions:
                risk_analysis = RiskAnalyzer.analyze_transaction(transaction)
                
                if risk_analysis['is_suspicious']:
                    anomaly_data = {
                        'transaction_id': str(transaction.id),
                        'date': transaction.transaction_date.isoformat(),
                        'amount': float(transaction.amount),
                        'description': transaction.description,
                        'risk_score': risk_analysis['risk_score'],
                        'risk_level': risk_analysis['risk_level'],
                        'flags': risk_analysis['flags']
                    }
                    anomalies.append(anomaly_data)
                    
                    # LOG TO AUDIT (Security Event)
                    if not AuditLog.objects.filter(metadata__transaction_id=str(transaction.id), action='SECURITY_ANOMALY').exists():
                        AuditLog.objects.create(
                            actor=user,
                            action='SECURITY_ANOMALY',
                            description=f"Suspicious transaction detected: ₹{transaction.amount} at {transaction.description}",
                            severity='CRITICAL' if risk_analysis['risk_level'] == 'CRITICAL' else 'HIGH',
                            metadata=anomaly_data
                        )
                        
                        # NOTIFY USER
                        NotificationService.create_notification(
                            user=user,
                            title="⚠️ Unusual Activity Detected",
                            message=f"We detected a suspicious transaction of ₹{transaction.amount} for {transaction.description}. Please review.",
                            notification_type='SECURITY',
                            priority='HIGH'
                        )
            
            return {
                'total_anomalies': len(anomalies),
                'anomalies': anomalies,
                'high_risk_count': len([a for a in anomalies if a['risk_level'] in ['HIGH', 'CRITICAL']])
            }
            
        except Exception as e:
            logger.error(f"Error detecting anomalies: {str(e)}")
            return {
                'total_anomalies': 0,
                'anomalies': [],
                'error': str(e)
            }
    
    @staticmethod
    def generate_recommendations(user):
        """Generate financial recommendations"""
        try:
            from ..models import PaymentTransaction
            
            recommendations = []
            
            # Get spending data
            thirty_days_ago = timezone.now() - timedelta(days=30)
            transactions = PaymentTransaction.objects.filter(
                account__user=user,
                transaction_date__gte=thirty_days_ago,
                transaction_type='DEBIT'
            )
            
            if transactions.exists():
                total_spent = sum(float(abs(t.amount)) for t in transactions)
                avg_daily = total_spent / 30
                
                # Recommendation 1: Budget suggestion
                if avg_daily > 1000:  # More than ₹1000 per day
                    recommendations.append({
                        'type': 'BUDGET_SUGGESTION',
                        'title': 'Consider setting a daily budget',
                        'description': f'Your average daily spending is ₹{avg_daily:,.2f}. Setting a budget could help manage expenses.',
                        'priority': 'HIGH',
                        'action': 'CREATE_BUDGET'
                    })
                
                # Recommendation 2: Category optimization
                categories = {}
                for t in transactions:
                    category = t.category or 'UNCATEGORIZED'
                    categories[category] = categories.get(category, 0) + float(abs(t.amount))
                
                if categories:
                    top_category = max(categories.items(), key=lambda x: x[1])
                    if top_category[1] > total_spent * 0.4:  # More than 40% of spending
                        recommendations.append({
                            'type': 'CATEGORY_OPTIMIZATION',
                            'title': f'High spending in {top_category[0]}',
                            'description': f'{top_category[0]} accounts for {(top_category[1]/total_spent*100):.0f}% of your spending.',
                            'priority': 'MEDIUM',
                            'action': 'REVIEW_CATEGORY_SPENDING'
                        })
            
            # Recommendation 3: Savings opportunity
            account = user.payment_accounts.filter(is_primary=True).first()
            if account and account.balance > 10000:  # More than ₹10,000
                recommendations.append({
                    'type': 'SAVINGS_OPPORTUNITY',
                    'title': 'Consider moving funds to savings',
                    'description': f'You have ₹{account.balance:,.2f} in your account. Consider moving some to savings.',
                    'priority': 'LOW',
                    'action': 'CREATE_SAVINGS_GOAL'
                })
            
            return {
                'total_recommendations': len(recommendations),
                'recommendations': recommendations[:3],  # Top 3 recommendations
                'generated_at': timezone.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error generating recommendations: {str(e)}")
            return {
                'total_recommendations': 0,
                'recommendations': [],
                'error': str(e)
            }