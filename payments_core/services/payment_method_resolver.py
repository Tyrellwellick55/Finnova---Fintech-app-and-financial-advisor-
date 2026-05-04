"""Standardize payment method selection.

Problem this solves:
- Some code paths use CardToken/UPIID objects
- Some use raw UPI VPA strings
- Autopilot sometimes picks a method automatically

This resolver returns a normalized dict for downstream processors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ResolvedPaymentMethod:
    method: str  # CARD / UPI / NETBANKING / BANK_TRANSFER / WALLET / CASH / AUTO
    card_token_id: Optional[str] = None
    upi_vpa: Optional[str] = None
    bank_code: Optional[str] = None


def resolve_for_intent(payment_intent) -> ResolvedPaymentMethod:
    """Resolve payment method requirements from a PaymentIntent."""

    method = (payment_intent.payment_method or '').upper()

    if method == 'CARD':
        if not payment_intent.card_token_id:
            raise ValueError('CARD payment requires a saved card token.')
        return ResolvedPaymentMethod(method='CARD', card_token_id=str(payment_intent.card_token_id))

    if method == 'UPI':
        if not payment_intent.upi_vpa:
            raise ValueError('UPI payment requires a UPI VPA (upi_vpa).')
        return ResolvedPaymentMethod(method='UPI', upi_vpa=payment_intent.upi_vpa)

    if method in {'NETBANKING', 'BANK_TRANSFER', 'WALLET', 'CASH', 'AUTO', 'REFUND', 'TOPUP', 'DEPOSIT'}:
        return ResolvedPaymentMethod(method=method)

    raise ValueError(f'Unsupported payment method: {method}')
