from notifications.services import NotificationService

def _transaction_user(transaction):
    return getattr(transaction, 'user', None) or getattr(getattr(transaction, 'account', None), 'user', None)


def handle_transaction(transaction, status):
    """
    Handle finance transaction events
    """
    user = _transaction_user(transaction)
    if user is None:
        return

    if status == 'FAILED':
        NotificationService.create_from_template(
            template_id='PAYMENT_FAILED',
            user=user,
            context={
                'payment_id': transaction.id,
                'amount': transaction.amount,
                'reason': transaction.failure_reason
            },
            related_app='finance',
            related_model='Transaction',
            related_id=str(transaction.id)
        )
    elif status == 'SUSPICIOUS':
        NotificationService.create_from_template(
            template_id='FRAUD_DETECTED',
            user=user,
            context={
                'activity_details': f'Suspicious transaction {transaction.id}',
                'risk_level': 'HIGH',
                'recommended_steps': 'Verify transaction immediately'
            },
            related_app='finance',
            related_model='Transaction',
            related_id=str(transaction.id)
        )
