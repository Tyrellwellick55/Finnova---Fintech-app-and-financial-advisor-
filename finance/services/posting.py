"""Finance posting utilities.

Purpose:
- Ensure every real-world financial action (payments, invoices, autopilot bills)
  posts to the finance ledger automatically.
- Keep the public API simple: post_income / post_expense.

These helpers are idempotent if you pass a stable `payment_reference`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.utils import timezone

from eventhub.services import emit_event

from finance.models import Account, Income, Expense


def _get_primary_account(user, organization=None) -> Account:
    """Return the primary Finance account for user+org, creating one atomically if absent."""
    acct = (
        Account.objects.filter(user=user, organization=organization, is_primary=True)
        .order_by('-updated_at')
        .first()
    )
    if acct:
        return acct

    # Use get_or_create with select_for_update to avoid duplicate primary accounts
    # under concurrent invoice payments.
    with transaction.atomic():
        acct = (
            Account.objects.select_for_update()
            .filter(user=user, organization=organization, is_primary=True)
            .first()
        )
        if acct:
            return acct
        acct, _ = Account.objects.get_or_create(
            user=user,
            organization=organization,
            is_primary=True,
            defaults={
                'name': 'Primary Wallet',
                'account_type': 'WALLET',
                'opening_balance': Decimal('0.00'),
                'current_balance': Decimal('0.00'),
                'currency': getattr(user, 'preferred_currency', 'INR') or 'INR',
                'is_active': True,
                'include_in_total': True,
                'notes': 'Auto-created primary account',
            },
        )
    return acct


@transaction.atomic
def post_income(
    *,
    organization,
    user,
    amount,
    source: str,
    category: str = 'BUSINESS',
    memo: str = '',
    description: str = '',
    payment_reference: Optional[str] = None,
    related_payment=None,
    related_transaction=None,
):
    amount = Decimal(amount)
    account = _get_primary_account(user, organization)

    if payment_reference:
        existing = Income.objects.filter(
            organization=organization,
            user=user,
            payment_reference=payment_reference,
        ).first()
        if existing:
            return existing

    income = Income.objects.create(
        organization=organization,
        user=user,
        account=account,
        amount=amount,
        source=source,
        category=category,
        date=timezone.now().date(),
        description=(memo or ''),
        payment_reference=payment_reference,
        is_verified=True,
        metadata={
            'source': 'auto_post',
            'related_payment_id': str(getattr(related_payment, 'id', '')) if related_payment else None,
            'related_transaction_id': str(getattr(related_transaction, 'id', '')) if related_transaction else None,
        },
    )

    # Update account balance
    try:
        account.update_balance()
    except Exception:
        pass

    emit_event(
        event_type='FINANCE_INCOME_POSTED',
        organization=organization,
        actor=user,
        metadata={'income_id': str(income.id), 'amount': str(amount), 'source': source},
        idempotency_key=f"FIN_INCOME:{payment_reference}" if payment_reference else None,
        also_audit=True,
        audit_kwargs={
            'source': 'FINANCE',
            'action': 'CREATE',
            'severity': 'INFO',
            'description': f'Income posted: {source} ({amount})',
            'target_model': 'finance.Income',
            'target_id': str(income.id),
            'related_payment': related_payment,
            'related_transaction': related_transaction,
        },
        also_notify=False,
    )

    return income


@transaction.atomic
def post_expense(
    *,
    organization,
    user,
    amount,
    merchant: str,
    category: str = 'OTHER',
    memo: str = '',
    payment_reference: Optional[str] = None,
    related_payment=None,
    related_transaction=None,
):
    amount = Decimal(amount)
    account = _get_primary_account(user, organization)

    if payment_reference:
        existing = Expense.objects.filter(
            organization=organization,
            user=user,
            payment_reference=payment_reference,
        ).first()
        if existing:
            return existing

    expense = Expense.objects.create(
        organization=organization,
        user=user,
        account=account,
        amount=amount,
        merchant=merchant,
        category=category,
        date=timezone.now().date(),
        description=(memo or ''),
        payment_reference=payment_reference,
        is_verified=True,
        metadata={
            'source': 'auto_post',
            'related_payment_id': str(getattr(related_payment, 'id', '')) if related_payment else None,
            'related_transaction_id': str(getattr(related_transaction, 'id', '')) if related_transaction else None,
        },
    )

    try:
        account.update_balance()
    except Exception:
        pass

    emit_event(
        event_type='FINANCE_EXPENSE_POSTED',
        organization=organization,
        actor=user,
        metadata={'expense_id': str(expense.id), 'amount': str(amount), 'merchant': merchant},
        idempotency_key=f"FIN_EXPENSE:{payment_reference}" if payment_reference else None,
        also_audit=True,
        audit_kwargs={
            'source': 'FINANCE',
            'action': 'CREATE',
            'severity': 'INFO',
            'description': f'Expense posted: {merchant} ({amount})',
            'target_model': 'finance.Expense',
            'target_id': str(expense.id),
            'related_payment': related_payment,
            'related_transaction': related_transaction,
        },
        also_notify=False,
    )

    return expense
