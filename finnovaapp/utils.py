# utils.py
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
import json

def calculate_savings_score(income, expenses):
    """
    Calculate savings score (0-100)
    """
    if income <= 0:
        return 0
    
    savings_rate = ((income - expenses) / income) * 100
    savings_score = min(max(savings_rate, 0), 100)
    return round(savings_score, 2)

def calculate_risk_level(income, expenses, volatility_score=0):
    """
    Calculate risk level based on financial metrics
    """
    if income <= 0:
        return 'HIGH'
    
    savings_rate = ((income - expenses) / income) * 100
    
    if savings_rate > 30:
        return 'LOW'
    elif savings_rate > 10:
        return 'MEDIUM'
    else:
        return 'HIGH'

def get_financial_insights(user, start_date=None, end_date=None):
    """
    Generate basic financial insights if AI module is not available
    """
    if start_date is None:
        start_date = timezone.now().date().replace(day=1)
    if end_date is None:
        end_date = timezone.now().date()
    
    from finance.models import Income, Expense
    from django.db.models import Sum
    
    total_income = Income.objects.filter(
        user=user,
        date__range=[start_date, end_date]
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    total_expenses = Expense.objects.filter(
        user=user,
        date__range=[start_date, end_date]
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    
    insights = []
    
    if total_income > 0:
        savings_rate = ((total_income - total_expenses) / total_income) * 100
        
        if savings_rate < 0:
            insights.append({
                'title': 'Negative Savings',
                'message': f'Your expenses exceed income by {abs(savings_rate):.1f}%. Consider reducing expenses.',
                'severity': 'HIGH',
                'category': 'SAVINGS'
            })
        elif savings_rate < 10:
            insights.append({
                'title': 'Low Savings Rate',
                'message': f'Your savings rate is {savings_rate:.1f}%. Try to increase it to at least 20%.',
                'severity': 'MEDIUM',
                'category': 'SAVINGS'
            })
        elif savings_rate > 30:
            insights.append({
                'title': 'Excellent Savings',
                'message': f'Great job! Your savings rate is {savings_rate:.1f}%.',
                'severity': 'LOW',
                'category': 'POSITIVE'
            })
    
    return insights

def format_currency(amount, currency='INR'):
    """
    Format currency based on locale
    """
    if currency == 'INR':
        return f'₹{amount:,.2f}'
    elif currency == 'USD':
        return f'${amount:,.2f}'
    elif currency == 'EUR':
        return f'€{amount:,.2f}'
    else:
        return f'{amount:,.2f} {currency}'

def _active_org(request):
    """Get the active organization from the request."""
    return getattr(request, "active_organization", None)

def _scoped_queryset(queryset, organization=None):
    """Filter a queryset by organization if the model supports it."""
    from django.db.models import Q
    fields = {field.name for field in queryset.model._meta.get_fields()}
    if "organization" not in fields:
        return queryset
    if organization is None:
        return queryset.filter(organization__isnull=True)
    return queryset.filter(Q(organization=organization) | Q(organization__isnull=True))

def _wants_json(request):
    """Check if the request wants a JSON response."""
    accept = request.headers.get("Accept", "")
    return request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in accept

def _resolve_finance_account(user, organization=None, create_if_missing=False):
    """Resolve a user's finance account safely."""
    from finance.models import Account
    queryset = Account.objects.filter(user=user)
    if organization:
        queryset = queryset.filter(organization=organization)
    else:
        queryset = queryset.filter(organization__isnull=True)
    
    account = (
        queryset.filter(is_primary=True, is_active=True).first()
        or queryset.filter(is_primary=True).first()
        or queryset.filter(is_active=True).first()
        or queryset.first()
    )
    if account or not create_if_missing:
        return account
    
    return Account.objects.create(
        user=user,
        organization=organization,
        name="Primary Finance Account",
        account_type="SAVINGS",
        opening_balance=Decimal("0.00"),
        current_balance=Decimal("0.00"),
        is_primary=True,
        is_active=True,
    )

def _resolve_payment_account(user, organization=None, create_if_missing=False):
    """Resolve a user's payment account safely."""
    from payments_core.models import PaymentAccount
    queryset = PaymentAccount.objects.filter(user=user)
    if organization:
        queryset = queryset.filter(organization=organization)
    else:
        queryset = queryset.filter(organization__isnull=True)
        
    account = (
        queryset.filter(is_primary=True, is_active=True).first()
        or queryset.filter(is_primary=True).first()
        or queryset.filter(is_active=True).first()
        or queryset.first()
    )
    if account or not create_if_missing:
        return account
    
    return PaymentAccount.objects.create(
        user=user,
        organization=organization,
        account_number=PaymentAccount.generate_account_number(),
        is_primary=True,
        is_active=True,
        balance=Decimal("0.00"),
        available_balance=Decimal("0.00"),
    )
