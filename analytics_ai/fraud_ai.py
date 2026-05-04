from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg
from django.utils import timezone

from payments_core.models import PaymentTransaction


def detect_fraud(user, transaction):
    """Lightweight fraud heuristic using real payment transaction fields."""
    recent_txns = PaymentTransaction.objects.filter(
        account__user=user,
        transaction_type='DEBIT',
        status='SUCCESS',
        transaction_date__gte=timezone.now() - timedelta(minutes=5),
    )

    total_recent = sum((tx.amount for tx in recent_txns), Decimal('0.00'))
    if total_recent > Decimal('5000.00'):
        return {
            'risk': 'HIGH',
            'reason': 'High transaction velocity detected',
            'action': 'PAUSE',
        }

    avg = (
        PaymentTransaction.objects.filter(
            account__user=user,
            transaction_type='DEBIT',
            status='SUCCESS',
        ).aggregate(avg_amount=Avg('amount'))['avg_amount']
        or Decimal('0.00')
    )

    if avg and transaction.amount > (avg * Decimal('4')):
        return {
            'risk': 'CRITICAL',
            'reason': 'Transaction amount unusually high',
            'action': 'FREEZE',
        }

    return {
        'risk': 'LOW',
        'reason': 'Normal behavior',
        'action': 'NONE',
    }
