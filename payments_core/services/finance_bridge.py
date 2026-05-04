from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Optional

from finance.models import Expense, Income
from finance.services.posting import post_expense, post_income
from payments_core.models import PaymentTransaction

from .payment_integrator import PaymentIntegrator

logger = logging.getLogger(__name__)


class PaymentFinanceBridge:
    """Single bridge for syncing payment transactions into finance.

    Purpose:
    - avoid duplicate inline sync logic across dashboard/views/engines
    - keep idempotency based on the finance `payment_reference` string
    - make GET dashboards read-only; actual sync should call this service explicitly
    """

    @staticmethod
    def get_reference(transaction: PaymentTransaction) -> str:
        if getattr(transaction, 'payment_intent_id', None) and getattr(transaction.payment_intent, 'reference_id', None):
            return str(transaction.payment_intent.reference_id)
        if getattr(transaction, 'reference', None):
            return str(transaction.reference)
        return str(transaction.id)

    @classmethod
    def is_transaction_synced(cls, user, transaction: PaymentTransaction) -> bool:
        reference = cls.get_reference(transaction)
        return (
            Expense.objects.filter(user=user, payment_reference=reference).exists()
            or Income.objects.filter(user=user, payment_reference=reference).exists()
        )

    @classmethod
    def sync_transaction(cls, user, transaction: PaymentTransaction, *, risk_analysis: Optional[Dict[str, Any]] = None):
        reference = cls.get_reference(transaction)
        if cls.is_transaction_synced(user, transaction):
            if transaction.transaction_type == 'DEBIT':
                return Expense.objects.filter(user=user, payment_reference=reference).first()
            return Income.objects.filter(user=user, payment_reference=reference).first()

        payment_intent = getattr(transaction, 'payment_intent', None)
        organization = getattr(transaction, 'organization', None) or getattr(payment_intent, 'organization', None)
        description = transaction.description or transaction.reference or 'Payment transaction'
        merchant = transaction.merchant or (payment_intent.metadata.get('merchant') if payment_intent and payment_intent.metadata else None) or 'Payment'
        category = transaction.category or PaymentIntegrator.auto_categorize_transaction(transaction)

        if transaction.transaction_type == 'DEBIT':
            expense = post_expense(
                organization=organization,
                user=user,
                amount=abs(transaction.amount),
                merchant=merchant,
                category=category or 'OTHER',
                memo=f"Payment: {description}",
                payment_reference=reference,
                related_payment=payment_intent,
                related_transaction=transaction,
            )
            metadata = dict(getattr(expense, 'metadata', {}) or {})
            metadata.update({
                'source': 'payments_bridge',
                'transaction_reference': transaction.reference,
                'transaction_id': str(transaction.id),
            })
            if risk_analysis:
                metadata['risk_analysis'] = risk_analysis
                if 'risk_score' in risk_analysis:
                    metadata['risk_score'] = risk_analysis.get('risk_score')
            expense.metadata = metadata
            expense.payment_intent = payment_intent or expense.payment_intent
            expense.save(update_fields=['metadata', 'payment_intent', 'updated_at'])
            return expense

        source = 'Payment Credit'
        if payment_intent and payment_intent.payment_method in {'REFUND', 'TOPUP', 'DEPOSIT'}:
            source = payment_intent.get_payment_method_display()
        elif description:
            source = description[:200]

        income = post_income(
            organization=organization,
            user=user,
            amount=abs(transaction.amount),
            source=source,
            category='OTHER',
            memo=f"Credit: {description}",
            payment_reference=reference,
            related_payment=payment_intent,
            related_transaction=transaction,
        )
        metadata = dict(getattr(income, 'metadata', {}) or {})
        metadata.update({
            'source': 'payments_bridge',
            'transaction_reference': transaction.reference,
            'transaction_id': str(transaction.id),
        })
        if risk_analysis:
            metadata['risk_analysis'] = risk_analysis
        income.metadata = metadata
        income.save(update_fields=['metadata', 'updated_at'])
        return income
