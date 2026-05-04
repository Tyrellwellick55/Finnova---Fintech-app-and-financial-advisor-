from notifications.services import NotificationService

def _transaction_user(transaction):
    return getattr(transaction, 'user', None) or getattr(getattr(transaction, 'account', None), 'user', None)


def notify_transaction_failed(transaction):
     user = _transaction_user(transaction)
     if user is None:
         return
     NotificationService.create_notification(
         user=user,
         source='finance.transaction',
         event_type='PAYMENT',
         severity='HIGH',
         title='Transaction Failed',
         message=f'Transaction {transaction.id} for amount {transaction.amount} failed.',
         action_hint='Please check your account balance and try again.',
         related_app='finance',
         related_model='Transaction',
         related_id=str(transaction.id)
     )

def notify_large_transaction(transaction, threshold):
     user = _transaction_user(transaction)
     if user is None:
         return
     NotificationService.create_notification(
         user=user,
         source='finance.transaction',
         event_type='FINANCE',
         severity='MEDIUM',
         title='Large Transaction',
         message=f'Transaction {transaction.id} for amount {transaction.amount} exceeds the threshold of {threshold}.',
         action_hint='Review the transaction.',
         related_app='finance',
         related_model='Transaction',
         related_id=str(transaction.id)
     )

def notify_fraud_detected(user, transaction, risk_score):
    """
    Notify about potential fraud
    """
    NotificationService.create_notification(
        user=user,
        source='finance.fraud_detection',
        event_type='FRAUD',
        severity='CRITICAL',
        title='Potential Fraud Detected',
        message=f'Unusual transaction pattern detected. Risk score: {risk_score}',
        related_app='finance',
        related_model='Transaction',
        related_id=str(transaction.id),
        requires_acknowledgment=True,
        metadata={'risk_score': risk_score, 'transaction_id': transaction.id}
    )

def notify_daily_summary(user, summary_data):
    """
    Send daily financial summary
    """
    NotificationService.create_notification(
        user=user,
        source='finance.daily_summary',
        event_type='FINANCE',
        severity='INFO',
        title='Daily Finance Summary',
        message=f"Today's activity: {summary_data.get('transactions', 0)} transactions, "
                f"Total: ${summary_data.get('total_amount', 0)}",
        action_hint='View detailed report',
        action_url='/finance/reports/'
    )
