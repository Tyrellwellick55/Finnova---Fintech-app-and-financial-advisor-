"""Finance EventHub handlers.

These subscribe to DomainEvents and keep the Finance ledger in sync
without requiring every UI route to call finance posting utilities.

Rules:
- If a PAYMENT_SUCCEEDED references an invoice_id, the agency handler posts income.
- If it references a bill_id or purpose=TRANSFER, we post an expense.
"""

import logging

from eventhub.dispatcher import subscribe

logger = logging.getLogger(__name__)


def _handle_payment_succeeded(ev):
    try:
        from finance.services.posting import post_expense

        meta = ev.metadata or {}
        org = ev.organization
        user = ev.actor
        if user is None:
            return

        # Agency pipeline handles invoice income
        if meta.get('invoice_id'):
            return

        reference = meta.get('payment_reference') or meta.get('reference_id')
        if not reference:
            return

        # Bill payments
        bill_id = meta.get('bill_id') or (meta.get('metadata') or {}).get('bill_id')
        purpose = meta.get('purpose') or (meta.get('metadata') or {}).get('purpose')
        source = meta.get('source') or (meta.get('metadata') or {}).get('source')

        # Determine whether this should be an expense posting
        is_transfer = str(purpose).upper() == 'TRANSFER'
        is_bill = bool(bill_id) or (source in {'AUTOPAY_DEMO', 'MANUAL_BILL_PAY_DEMO', 'AUTOPAY', 'BILL_PAY'})

        if not (is_transfer or is_bill):
            return

        merchant = meta.get('merchant') or meta.get('biller_name') or ('Transfer' if is_transfer else 'Bill payment')
        category = meta.get('category') or ('OTHER' if is_transfer else 'BILLS')
        memo = meta.get('description') or (f"Transfer: {meta.get('description','')}" if is_transfer else f"Bill payment: {merchant}")

        post_expense(
            organization=org,
            user=user,
            amount=meta.get('amount') or 0,
            merchant=merchant,
            category=category,
            memo=memo,
            payment_reference=reference,
        )

    except Exception:
        logger.debug('Finance handler failed for PAYMENT_SUCCEEDED', exc_info=True)


subscribe('PAYMENT_SUCCEEDED', _handle_payment_succeeded)
