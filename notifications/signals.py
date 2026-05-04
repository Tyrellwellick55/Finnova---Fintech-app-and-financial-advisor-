from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import NotificationPreference
from .services import NotificationService

User = get_user_model()

def _transaction_user(transaction):
    return getattr(transaction, 'user', None) or getattr(getattr(transaction, 'account', None), 'user', None)


@receiver(post_save, sender=User)
def create_user_notification_preferences(sender, instance, created, **kwargs):
    """
    Automatically create notification preferences for new users
    """
    if created:
        NotificationPreference.objects.create(user=instance)


# Signal handlers for other apps
def handle_finance_alert(sender, transaction, alert_type, **kwargs):
    """
    Handle alerts from finance app
    """
    from payments_core.models import PaymentTransaction  # Avoid circular import
    
    severity_map = {
        'FRAUD': 'CRITICAL',
        'LARGE_TRANSACTION': 'HIGH',
        'UNUSUAL_ACTIVITY': 'MEDIUM',
        'DAILY_SUMMARY': 'INFO'
    }

    user = _transaction_user(transaction)
    if user is None:
        return
    
    NotificationService.create_notification(
        user=user,
        source='finance.transaction',
        event_type='FINANCE',
        severity=severity_map.get(alert_type, 'MEDIUM'),
        title=f"Finance Alert: {alert_type.replace('_', ' ').title()}",
        message=f"Transaction {transaction.id} triggered {alert_type} alert",
        related_app='finance',
        related_model='PaymentTransaction',
        related_id=str(transaction.id),
        metadata={
            'amount': str(transaction.amount),
            'currency': getattr(transaction, 'currency', 'INR'),
            'alert_type': alert_type
        }
    )


def handle_autopilot_event(sender, event, **kwargs):
    """
    Handle events from Finnova AutoPilot
    """
    
    NotificationService.create_notification(
        user=event.user,
        source='finnovaautopilot.event',
        event_type='AUTOPILOT',
        severity=event.severity,
        title=f"AutoPilot: {event.event_type}",
        message=event.description,
        related_app='finnovaautopilot',
        related_model='AutoPilotEvent',
        related_id=str(event.id),
        action_hint=event.recommended_action,
        metadata={
            'event_type': event.event_type,
            'confidence': event.confidence_score,
            'trigger': event.trigger_source
        }
    )


def handle_payment_event(sender, payment, status_change, **kwargs):
    """
    Handle payment events
    """
    from payments_core.models import PaymentIntent
    
    if status_change == 'FAILED':
        NotificationService.create_from_template(
            template_id='PAYMENT_FAILED',
            user=payment.user,
            context={
                'payment_id': payment.id,
                'amount': payment.amount,
                'reason': payment.failure_reason
            },
            related_app='payments_core',
            related_model='Payment',
            related_id=str(payment.id)
        )
    
    elif status_change == 'COMPLETED':
        NotificationService.create_from_template(
            template_id='PAYMENT_COMPLETED',
            user=payment.user,
            context={
                'payment_id': payment.id,
                'amount': payment.amount,
                'recipient': payment.recipient_name
            },
            related_app='payments_core',
            related_model='PaymentIntent',
            related_id=str(payment.id)
        )


def handle_audit_alert(sender, audit_log, alert_type, **kwargs):
    """
    Handle audit system alerts
    """
    from audit.models import AuditLog
    
    NotificationService.create_notification(
        user=getattr(audit_log, 'actor', None),
        source='audit.system',
        event_type='AUDIT',
        severity='HIGH' if alert_type == 'SUSPICIOUS' else 'MEDIUM',
        title=f"Audit Alert: {alert_type} Activity",
        message=f"Unusual activity detected in audit log {audit_log.id}",
        related_app='audit',
        related_model='AuditLog',
        related_id=str(audit_log.id),
        requires_acknowledgment=True,
        metadata={
            'action': audit_log.action,
            'ip_address': getattr(audit_log, 'actor_ip', None),
            'user_agent': getattr(audit_log, 'actor_user_agent', None)
        }
    )
