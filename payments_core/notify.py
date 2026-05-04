# payments_core/notify.py
import logging

logger = logging.getLogger(__name__)

def notify_payment_status(payment, old_status, new_status):
    """
    Notify about payment status change
    """
    try:
        # Determine notification details based on status
        if new_status == 'SUCCESS':
            title = 'Payment Successful'
            message = f'Your payment {payment.reference_id} for ₹{payment.amount} has been completed successfully.'
            severity = 'INFO'
        elif new_status == 'FAILED':
            title = 'Payment Failed'
            message = f'Your payment {payment.reference_id} for ₹{payment.amount} has failed.'
            if payment.error_message:
                message += f' Reason: {payment.error_message}'
            severity = 'HIGH'
        elif new_status == 'PROCESSING':
            title = 'Payment Processing'
            message = f'Your payment {payment.reference_id} for ₹{payment.amount} is being processed.'
            severity = 'INFO'
        elif new_status == 'CANCELLED':
            title = 'Payment Cancelled'
            message = f'Your payment {payment.reference_id} for ₹{payment.amount} has been cancelled.'
            severity = 'MEDIUM'
        else:
            # Don't notify for other status changes
            return
        
        # Try to use NotificationService if available
        try:
            from notifications.services import NotificationService
            NotificationService.create_notification(
                user=payment.user,
                source='payments_core.payment',
                event_type='PAYMENT',
                severity=severity,
                title=title,
                message=message,
                action_hint='View payment details for more information.',
                related_app='payments_core',
                related_model='PaymentIntent',
                related_id=str(payment.id)
            )
        except ImportError:
            # Fallback to logging if NotificationService is not available
            logger.info(f"Notification: {title} - {message} for user {payment.user.username}")
            
    except Exception as e:
        logger.error(f"Error in notify_payment_status: {str(e)}")

def notify_payment_reminder(user, payment, days_remaining):
    """
    Send payment reminder
    """
    try:
        try:
            from notifications.services import NotificationService
            NotificationService.create_notification(
                user=user,
                source='payments_core.reminder',
                event_type='PAYMENT',
                severity='MEDIUM' if days_remaining > 3 else 'HIGH',
                title=f'Payment Due in {days_remaining} Days',
                message=f'Payment of ₹{payment.amount} is due soon.',
                related_app='payments_core',
                related_model='PaymentIntent',
                related_id=str(payment.id),
                requires_acknowledgment=True
            )
        except ImportError:
            logger.info(f"Payment reminder: ₹{payment.amount} due in {days_remaining} days for user {user.username}")
            
    except Exception as e:
        logger.error(f"Error in notify_payment_reminder: {str(e)}")