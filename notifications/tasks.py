from celery import shared_task
from django.utils import timezone
from .models import Notification
from .services import NotificationManager
import logging

logger = logging.getLogger(__name__)


@shared_task
def cleanup_expired_notifications():
    """
    Clean up expired notifications (run daily)
    """
    try:
        deleted = NotificationManager.cleanup_expired(days=30)
        logger.info(f"Cleaned up {deleted} expired notifications")
        return deleted
    except Exception as e:
        logger.error(f"Failed to cleanup notifications: {str(e)}")
        raise


@shared_task
def deliver_pending_notifications():
    """
    Deliver pending notifications (run every 5 minutes)
    """
    from .services import NotificationService
    
    try:
        # Get notifications that need delivery
        pending = Notification.objects.filter(
            sent_via_email=False,
            sent_via_push=False,
            sent_via_sms=False,
            created_at__gte=timezone.now() - timezone.timedelta(hours=24)
        )[:100]
        
        for notification in pending:
            pref = NotificationService._get_user_preferences(notification.user)
            NotificationService._deliver_notification(notification, pref)
        
        logger.info(f"Processed {len(pending)} pending notifications")
        return len(pending)
        
    except Exception as e:
        logger.error(f"Failed to deliver pending notifications: {str(e)}")
        raise


@shared_task
def send_daily_summary(user_id):
    """
    Send daily notification summary to user
    """
    from django.contrib.auth import get_user_model
    from .services import NotificationService
    
    User = get_user_model()
    
    try:
        user = User.objects.get(id=user_id)
        stats = NotificationManager.get_stats(user)
        
        if stats['unread'] > 0:
            NotificationService.create_notification(
                user=user,
                source='notifications.system',
                event_type='SYSTEM',
                severity='INFO',
                title='Daily Notification Summary',
                message=f"You have {stats['unread']} unread notifications. "
                       f"Including {stats['critical']} critical and {stats['high']} high priority alerts.",
                action_hint='Review your notifications',
                action_url='/notifications',
                metadata={'summary_stats': stats}
            )
        
        return True
    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for daily summary")
        return False