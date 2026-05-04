import logging
from typing import Optional, List, Dict, Any
from django.db import transaction
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Count, Q

from .models import Notification, NotificationPreference, NotificationTemplate
import json
from datetime import timedelta

User = get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:
    """
    Central service for handling all notification operations
    """
    
    @staticmethod
    def create_notification(
        user,
        source: str,
        event_type: str,
        title: str,
        message: str,
        severity: str = 'INFO',
        related_app: Optional[str] = None,
        related_model: Optional[str] = None,
        related_id: Optional[str] = None,
        action_hint: Optional[str] = None,
        action_url: Optional[str] = None,
        metadata: Optional[Dict] = None,
        requires_acknowledgment: bool = False,
        template_id: Optional[str] = None,
        **kwargs
    ) -> Notification:
        """
        Create and deliver a notification intelligently
        """
        try:
            # Check user preferences for quiet hours
            pref = NotificationService._get_user_preferences(user)
            
            # Some older DBs/migrations may not include a dedicated "respect_quiet_hours" flag.
            # Treat quiet hours as enabled when start/end are set.
            respect_quiet = bool(
                pref
                and getattr(pref, 'quiet_hours_start', None)
                and getattr(pref, 'quiet_hours_end', None)
            )

            if respect_quiet and (NotificationService._is_quiet_hours(pref) and severity not in ['CRITICAL', 'HIGH']):
                logger.info(f"Skipping notification during quiet hours for user {user.id}")
                return None
            
            # Create notification record.
            # NOTE: the Notification model uses (category/severity/action_type/action_url/metadata)
            # while older call-sites may still send (source/event_type/action_hint/related_app/...)
            # Keep the public API stable and map into the current model fields.

            notif_category = event_type
            valid_categories = {c for c, _ in getattr(Notification, 'EVENT_CATEGORIES', [])}
            if notif_category not in valid_categories:
                notif_category = 'SYSTEM'

            valid_severities = {s for s, _ in getattr(Notification, 'SEVERITY_LEVELS', [])}
            notif_severity = severity if severity in valid_severities else 'INFO'

            extra_meta = {
                'source': source,
                'event_type': event_type,
            }
            if related_app:
                extra_meta['related_app'] = related_app
            if related_model:
                extra_meta['related_model'] = related_model
            if related_id:
                extra_meta['related_id'] = related_id

            merged_meta = {**(metadata or {}), **extra_meta}

            organization = kwargs.pop('organization', None)

            notification = Notification.objects.create(
                user=user,
                organization=organization,
                title=title,
                message=message,
                category=notif_category,
                severity=notif_severity,
                action_required=bool(action_url or action_hint),
                action_type=action_hint or None,
                action_url=action_url,
                requires_acknowledgment=requires_acknowledgment,
                metadata=merged_meta,
                **kwargs,
            )
            
            # Deliver via appropriate channels
            NotificationService._deliver_notification(notification, pref)
            
            # Log for audit
            logger.info(f"Notification created: {notification.id} for user {user.id}")
            
            return notification
            
        except Exception as e:
            logger.error(f"Failed to create notification: {str(e)}", exc_info=True)
            raise
    
    @staticmethod
    def create_from_template(
        template_id: str,
        user,
        context: Dict[str, Any],
        **overrides
    ) -> Notification:
        """
        Create notification from a template
        """
        try:
            template = NotificationTemplate.objects.get(
                template_id=template_id, 
                is_active=True
            )
            
            # Render template with context
            title = template.title_template.format(**context)
            message = template.message_template.format(**context)
            action_hint = template.action_hint_template.format(**context) if template.action_hint_template else None
            
            return NotificationService.create_notification(
                user=user,
                source='notifications.template',
                event_type=overrides.get('event_type', template.default_category),
                severity=overrides.get('severity', template.default_severity),
                title=title,
                message=message,
                action_hint=action_hint,
                requires_acknowledgment=template.requires_acknowledgment,
                metadata={'template_id': template_id, 'context': context},
                **overrides
            )
            
        except NotificationTemplate.DoesNotExist:
            logger.error(f"Template {template_id} not found")
            raise
    
    @staticmethod
    def create_bulk_notifications(
        users: List[User],  # FIXED: Changed from request.User to User
        source: str,
        event_type: str,
        title: str,
        message: str,
        severity: str = 'INFO',
        **kwargs
    ) -> List[Notification]:
        """
        Create notifications for multiple users efficiently
        """
        notifications = []

        for user in users:
            try:
                if notification := NotificationService.create_notification(
                    user=user,
                    source=source,
                    event_type=event_type,
                    title=title,
                    message=message,
                    severity=severity,
                    **kwargs,
                ):
                    notifications.append(notification)
            except Exception as e:
                logger.error(f"Failed to create notification for user {user.id}: {str(e)}")

        return notifications
    
    @staticmethod
    def create_for_event(
        event_source: str,
        event_data: Dict[str, Any],
        severity: str = 'INFO'
    ) -> List[Notification]:
        """
        Create notifications based on system events
        """
        notifications = []

        # Example: Handle payment events
        if event_source == 'analytics_ai.fraud_detected':
            user = User.objects.get(id=event_data.get('user_id'))
            notifications.append(
                NotificationService.create_notification(
                    user=user,
                    source='analytics_ai',
                    event_type='FRAUD',
                    severity='CRITICAL',
                    title='Suspicious Activity Detected',
                    message=f"Unusual transaction detected: {event_data.get('transaction_details')}",
                    action_hint='Review immediately',
                    action_url=reverse('audit:alert_list'),
                    requires_acknowledgment=True,
                    metadata=event_data
                )
            )

        elif event_source == 'audit.security_alert':
            # Get admin users who should receive security alerts
            admin_users = User.objects.filter(
                is_staff=True,
                is_active=True
            )

            notifications.extend(
                NotificationService.create_notification(
                    user=admin_user,
                    source='audit',
                    event_type='SECURITY',
                    severity='HIGH',
                    title='Security Alert',
                    message=f"Security event detected: {event_data.get('alert_type')}",
                    action_hint='Investigate now',
                    action_url=reverse('audit:alert_list'),
                    requires_acknowledgment=True,
                    metadata=event_data,
                )
                for admin_user in admin_users
            )
        elif event_source == 'finance.budget_exceeded':
            user = User.objects.get(id=event_data.get('user_id'))
            notifications.append(
                NotificationService.create_notification(
                    user=user,
                    source='finance',
                    event_type='BUDGET',
                    severity='MEDIUM',
                    title='Budget Limit Exceeded',
                    message=f"You've exceeded your {event_data.get('category')} budget by ₹{event_data.get('excess_amount')}",
                    action_hint='Adjust budget',
                    action_url=reverse('finance:budget_list'),
                    metadata=event_data
                )
            )

        elif event_source == 'finnovaautopilot.rule_triggered':
            user = User.objects.get(id=event_data.get('user_id'))
            notifications.append(
                NotificationService.create_notification(
                    user=user,
                    source='finnovaautopilot',
                    event_type='AUTOPILOT',
                    severity='LOW',
                    title='Autopilot Action Taken',
                    message=f"Your autopilot rule '{event_data.get('rule_name')}' was executed",
                    action_hint='View details',
                    action_url=reverse('autopilot:automation_rules'),
                    metadata=event_data
                )
            )

        elif event_source == 'payments_core.payment_completed':
            user = User.objects.get(id=event_data.get('user_id'))
            notifications.append(
                NotificationService.create_notification(
                    user=user,
                    source='payments_core',
                    event_type='PAYMENT',
                    severity=severity,
                    title='Payment Completed',
                    message=f"Payment of ₹{event_data.get('amount')} was successful",
                    action_hint='View receipt',
                    action_url=reverse('payments:payment_history'),
                    metadata=event_data
                )
            )

        return notifications
    
    @staticmethod
    def _get_user_preferences(user):
        """
        Get or create user notification preferences
        """
        try:
            return NotificationPreference.objects.get(user=user)
        except NotificationPreference.DoesNotExist:
            return NotificationPreference.objects.create(user=user)
    
    @staticmethod
    def _is_quiet_hours(preferences):
        """
        Check if current time is within quiet hours
        """
        if not preferences.quiet_hours_start or not preferences.quiet_hours_end:
            return False
        
        now = timezone.now().time()
        
        # Handle overnight quiet hours
        if preferences.quiet_hours_start <= preferences.quiet_hours_end:
            # Normal case: quiet hours are within the same day
            return preferences.quiet_hours_start <= now <= preferences.quiet_hours_end
        else:
            # Overnight case: quiet hours cross midnight
            return preferences.quiet_hours_start <= now or now <= preferences.quiet_hours_end
    
    @staticmethod
    def _deliver_notification(notification, preferences):
        """
        Deliver notification through appropriate channels
        """
        # This project has had multiple iterations of preference fields.
        # Support the current model (email_notifications/push_notifications/sms_notifications)
        # while remaining backward-compatible with older attribute names.
        severity_order = ['INFO', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL']

        email_on = getattr(preferences, 'email_notifications', getattr(preferences, 'email_enabled', True))
        push_on = getattr(preferences, 'push_notifications', getattr(preferences, 'push_enabled', True))
        sms_on = getattr(preferences, 'sms_notifications', getattr(preferences, 'sms_enabled', False))

        email_min = getattr(preferences, 'email_min_severity', 'INFO')
        push_min = getattr(preferences, 'push_min_severity', 'INFO')

        if email_on and severity_order.index(notification.severity) >= severity_order.index(email_min):
            NotificationService._send_email(notification)

        if push_on and severity_order.index(notification.severity) >= severity_order.index(push_min):
            NotificationService._send_push(notification)

        if sms_on and notification.severity == 'CRITICAL':
            NotificationService._send_sms(notification)
    
    @staticmethod
    def _send_email(notification):
        """
        Send notification via email
        """
        try:
            subject = f"[{notification.severity}] {notification.title}"
            message = f"""
            {notification.message}
            
            Severity: {notification.severity}
            Source: {notification.metadata.get('source', 'system') if hasattr(notification, 'metadata') else 'system'}
            Time: {notification.created_at}
            
            {f'Action Required: {notification.action_type}' if getattr(notification, 'action_type', None) else ''}
            {f'URL: {notification.action_url}' if notification.action_url else ''}
            """
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[notification.user.email],
                fail_silently=True,  # Changed to True to prevent breaking app if email fails
            )
            
            # Persist delivery status in a model-compatible way
            notification.delivery_method = 'EMAIL'
            notification.delivery_status = 'SENT'
            notification.delivery_attempts = (notification.delivery_attempts or 0) + 1
            notification.last_delivery_attempt = timezone.now()
            notification.save(update_fields=['delivery_method', 'delivery_status', 'delivery_attempts', 'last_delivery_attempt'])
            
        except Exception as e:
            logger.error(f"Failed to send email for notification {notification.id}: {str(e)}")
    
    @staticmethod
    def _send_push(notification):
        """
        Send push notification (implement based on your push service)
        """
        try:
            # Integrate with Firebase/APNS/etc. For now, mark as sent.
            notification.delivery_method = 'PUSH'
            notification.delivery_status = 'SENT'
            notification.delivery_attempts = (notification.delivery_attempts or 0) + 1
            notification.last_delivery_attempt = timezone.now()
            notification.save(update_fields=['delivery_method', 'delivery_status', 'delivery_attempts', 'last_delivery_attempt'])
            logger.info(f"Push notification prepared for {notification.id}")
        except Exception as e:
            logger.error(f"Failed to send push for notification {notification.id}: {str(e)}")
    
    @staticmethod
    def _send_sms(notification):
        """
        Send SMS notification (implement based on your SMS service)
        """
        try:
            # Integrate with Twilio/etc. For now, mark as sent.
            notification.delivery_method = 'SMS'
            notification.delivery_status = 'SENT'
            notification.delivery_attempts = (notification.delivery_attempts or 0) + 1
            notification.last_delivery_attempt = timezone.now()
            notification.save(update_fields=['delivery_method', 'delivery_status', 'delivery_attempts', 'last_delivery_attempt'])
            logger.info(f"SMS notification prepared for {notification.id}")
        except Exception as e:
            logger.error(f"Failed to send SMS for notification {notification.id}: {str(e)}")


class NotificationManager:
    """
    Manager for notification operations
    """
    
    @staticmethod
    def get_user_notifications(user, unread_only=False, limit=50):
        """
        Get notifications for a user with filtering
        """
        queryset = Notification.objects.filter(
            user=user,
            is_archived=False
        ).select_related('user')
        
        if unread_only:
            queryset = queryset.filter(is_read=False)
        
        # Filter out expired notifications
        queryset = queryset.filter(
            Q(expires_at__isnull=True) | 
            Q(expires_at__gt=timezone.now())
        )
        
        return queryset.order_by('-created_at')[:limit]
    
    @staticmethod
    def mark_all_as_read(user):
        """
        Mark all user notifications as read
        """
        return Notification.objects.filter(user=user, is_read=False).update(
            is_read=True, read_at=timezone.now()
        )
    
    @staticmethod
    def mark_as_read(notification_id, user):
        """
        Mark a specific notification as read
        """
        try:
            notification = Notification.objects.get(
                id=notification_id,
                user=user
            )
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save()
            return True
        except Notification.DoesNotExist:
            return False
    
    @staticmethod
    def get_stats(user):
        """
        Get notification statistics for user
        """
        today = timezone.now().date()
        
        return Notification.objects.filter(user=user).aggregate(
            total=Count('id'),
            unread=Count('id', filter=Q(is_read=False)),
            critical=Count('id', filter=Q(severity='CRITICAL', is_read=False)),
            high=Count('id', filter=Q(severity='HIGH', is_read=False)),
            today=Count('id', filter=Q(created_at__date=today)),
        )
    
    @staticmethod
    def cleanup_expired(days=30):
        """
        Clean up old notifications
        """
        cutoff = timezone.now() - timedelta(days=days)
        deleted, _ = Notification.objects.filter(
            created_at__lt=cutoff,
            is_archived=True
        ).delete()
        
        return deleted


# Legacy function for backward compatibility
def create_notification_event(user, source, event_type, severity, title, message, action_hint=None):
    """
    Legacy function - use NotificationService instead
    """
    return NotificationService.create_notification(
        user=user,
        source=source,
        event_type=event_type,
        severity=severity,
        title=title,
        message=message,
        action_hint=action_hint
    )


# Helper functions for different apps to send notifications
def send_payment_notification(user, payment_data):
    """Helper for payments_core app"""
    return NotificationService.create_for_event(
        'payments_core.payment_completed',
        {'user_id': user.id, **payment_data}
    )


def send_fraud_notification(user, fraud_data):
    """Helper for analytics_ai app"""
    return NotificationService.create_for_event(
        'analytics_ai.fraud_detected',
        {'user_id': user.id, **fraud_data},
        severity='CRITICAL'
    )


def send_budget_notification(user, budget_data):
    """Helper for finance app"""
    return NotificationService.create_for_event(
        'finance.budget_exceeded',
        {'user_id': user.id, **budget_data},
        severity='MEDIUM'
    )


def send_autopilot_notification(user, autopilot_data):
    """Helper for finnovaautopilot app"""
    return NotificationService.create_for_event(
        'finnovaautopilot.rule_triggered',
        {'user_id': user.id, **autopilot_data},
        severity='LOW'
    )


def send_audit_notification(alert_data):
    """Helper for audit app - sends to all admins"""
    return NotificationService.create_for_event(
        'audit.security_alert',
        alert_data,
        severity='HIGH'
    )


# Standalone function for backward compatibility
def create_notification(user, title, message, notification_type='GENERAL', priority='LOW', **kwargs):
    """
    Create a notification using the NotificationService
    """
    return NotificationService.create_notification(
        user=user,
        source='finance.signal',
        event_type=notification_type,
        severity=priority.upper(),
        title=title,
        message=message,
        **kwargs
    )


def get_unread_count(user):
    """
    Small helper used by dashboard views to fetch the number
    of unread (and not archived) notifications for a user.
    """
    try:
        return Notification.objects.filter(user=user, is_read=False, is_archived=False).count()
    except Exception:
        # Never let notification issues break the main UI
        return 0
