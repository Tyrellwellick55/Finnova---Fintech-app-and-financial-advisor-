# services.py
from decimal import Decimal
from datetime import timedelta

from django.utils import timezone
from django.db.models import Sum

from .models import CustomUser, UserProfile, LoginHistory, UserSession
from finance.models import Income, Expense
from payments_core.models import PaymentAccount, PaymentTransaction
from finnova_autopilot.models import SmartBill
from notifications.models import Notification

# Advanced AI helpers – all calls are wrapped in try/except so the
# dashboard continues to work even if this module changes or is removed.
from analytics_ai.algorithms import (  # type: ignore
    savings_monthly_score,
    financial_risk_level,
    predict_next_month_expenses,
    spending_pattern_analysis,
    investment_recommendations,
)

def get_comprehensive_dashboard(user):
    """
    Get complete, AI‑enhanced dashboard data for a user.

    This function is defensive by design: any failure in downstream
    modules (AI, autopilot, notifications, etc.) returns safe defaults
    instead of breaking the main dashboard.
    """
    try:
        # Prefer a primary wallet, then fall back to any active wallet
        wallet = (
            PaymentAccount.objects.filter(user=user, is_active=True)
            .order_by('-is_primary', '-created_at')
            .first()
        )

        today = timezone.now()
        first_day = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Core income / expense metrics
        total_income = (
            Income.objects.filter(user=user, date__gte=first_day)
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )

        total_expenses = (
            Expense.objects.filter(user=user, date__gte=first_day)
            .aggregate(total=Sum('amount'))['total']
            or Decimal('0')
        )

        pending_bills = SmartBill.objects.filter(
            user=user, status='PENDING'
        ).count()

        # AI scores – always safe fallbacks
        try:
            savings_score = savings_monthly_score(
                float(total_income), float(total_expenses)
            )
        except Exception:
            savings_score = 50

        try:
            risk_level = financial_risk_level(
                float(total_income), float(total_expenses)
            )
        except Exception:
            risk_level = 'MEDIUM RISK'

        # Build simple monthly expense history for the last 6 "months"
        monthly_data = {}
        for i in range(6):
            month_date = today - timedelta(days=30 * i)
            month_start = month_date.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if i == 0:
                month_end = today
            else:
                next_month = month_start + timedelta(days=32)
                month_end = next_month.replace(day=1) - timedelta(days=1)

            month_expenses = (
                Expense.objects.filter(
                    user=user,
                    date__gte=month_start,
                    date__lte=month_end,
                ).aggregate(total=Sum('amount'))['total']
                or Decimal('0')
            )

            month_key = month_start.strftime('%Y-%m')
            monthly_data[month_key] = float(month_expenses)

        try:
            predicted_expense = predict_next_month_expenses(monthly_data)
        except Exception:
            predicted_expense = 0.0

        # Recent transactions
        recent_transactions = (
            PaymentTransaction.objects.filter(account__user=user)
            .order_by('-transaction_date')[:10]
        )

        # Spending by category
        spending_by_category = (
            Expense.objects.filter(user=user, date__gte=first_day)
            .values('category')
            .annotate(total=Sum('amount'))
            .order_by('-total')[:5]
        )

        # Upcoming smart bills
        upcoming_bills = SmartBill.objects.filter(
            user=user,
            due_date__gte=today.date(),
            status='PENDING',
        ).order_by('due_date')[:5]

        # Deeper AI analysis (optional)
        try:
            spending_analysis = spending_pattern_analysis(user.id)
        except Exception:
            spending_analysis = {}

        try:
            investment_recommendation = investment_recommendations(
                float(wallet.balance) if wallet else 0.0,
                float(total_income),
                risk_level,
            )
        except Exception:
            investment_recommendation = 'Start with a savings account'

        # Unread notifications
        unread_notifications = Notification.objects.filter(
            user=user, is_read=False
        ).count()

        # Autopilot flag from profile (if available)
        try:
            autopilot_enabled = user.profile.notification_preferences.get(
                'autopilot_enabled', True
            )
        except Exception:
            autopilot_enabled = True

        return {
            'wallet': wallet,
            'balance': wallet.balance if wallet else Decimal('0'),
            'wallet_status': getattr(wallet, 'wallet_status', 'ACTIVE')
            if wallet
            else 'INACTIVE',
            'total_income': total_income,
            'total_expenses': total_expenses,
            'net_flow': total_income - total_expenses,
            'pending_bills': pending_bills,
            'savings_score': savings_score,
            'risk_level': risk_level,
            'predicted_expense': predicted_expense,
            'recent_transactions': recent_transactions,
            'spending_by_category': spending_by_category,
            'upcoming_bills': upcoming_bills,
            'spending_analysis': spending_analysis,
            'investment_recommendation': investment_recommendation,
            'unread_notifications': unread_notifications,
            'autopilot_enabled': autopilot_enabled,
            'currency': getattr(wallet, 'currency', None)
            or getattr(user, 'preferred_currency', 'INR'),
        }

    except Exception as e:
        # Return safe, self‑contained defaults
        return {
            'wallet': None,
            'balance': Decimal('0'),
            'wallet_status': 'ACTIVE',
            'total_income': Decimal('0'),
            'total_expenses': Decimal('0'),
            'net_flow': Decimal('0'),
            'pending_bills': 0,
            'savings_score': 0,
            'risk_level': 'MEDIUM RISK',
            'predicted_expense': 0.0,
            'recent_transactions': [],
            'spending_by_category': [],
            'upcoming_bills': [],
            'spending_analysis': {},
            'investment_recommendation': 'Start with a savings account',
            'unread_notifications': 0,
            'autopilot_enabled': True,
            'currency': 'INR',
            'error': str(e),
        }

def create_login_history(user, request, success=True, failure_reason=None):
    """
    Create login history entry - WITHOUT ipware dependency
    """
    # Get IP address using Django's built-in method
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(',')[0]
    else:
        ip_address = request.META.get('REMOTE_ADDR', '0.0.0.0')
    
    # Create login history
    login_history = LoginHistory.objects.create(
        user=user if user else None,
        ip_address=ip_address,
        user_agent=request.META.get('HTTP_USER_AGENT', ''),
        success=success,
        failure_reason=failure_reason,
        metadata={
            'referer': request.META.get('HTTP_REFERER', ''),
            'method': request.method,
            'path': request.path,
        }
    )
    
    return login_history

def create_user_session(user, request, session_key):
    """
    Create or update user session - WITHOUT ipware dependency
    """
    # Get IP address using Django's built-in method
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(',')[0]
    else:
        ip_address = request.META.get('REMOTE_ADDR', '0.0.0.0')
    
    # Calculate expiry (default Django session expiry)
    from django.conf import settings
    expires_at = timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE)
    
    session, created = UserSession.objects.update_or_create(
        session_key=session_key,
        defaults={
            'user': user,
            'ip_address': ip_address,
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'expires_at': expires_at,
            'is_active': True,
            'metadata': {
                'login_time': timezone.now().isoformat(),
                'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
            }
        }
    )
    
    return session

try:
    # Prefer the optional third‑party helper if installed.
    from ipware import get_client_ip  # type: ignore
except Exception:

    def get_client_ip(request):
        """
        Get client IP address from the request.

        This is a lightweight replacement used when `ipware`
        is not installed, and is safe to import anywhere.
        """
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            return x_forwarded_for.split(',')[0]
        return request.META.get('REMOTE_ADDR', '0.0.0.0')
