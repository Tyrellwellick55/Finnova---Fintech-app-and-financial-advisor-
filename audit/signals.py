from django.db.models.signals import post_save, pre_delete, pre_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.core.signals import request_started, request_finished

from audit.notify import notify_suspicious_activity

from .services import AuditService
from .models import AuditLog, SecurityAlert
from notifications.services import NotificationService

User = get_user_model()


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """Log user login events"""
    AuditService.log_audit_event(
        actor=user,
        source='SECURITY',
        action='LOGIN',
        severity='LOW',
        description=f'User {user.username} logged in',
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT'),
        request=request
    )


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """Log user logout events"""
    AuditService.log_audit_event(
        actor=user,
        source='SECURITY',
        action='LOGOUT',
        severity='LOW',
        description=f'User {user.username} logged out',
        ip_address=request.META.get('REMOTE_ADDR'),
        request=request
    )


@receiver(user_login_failed)
def log_login_failed(sender, credentials, request, **kwargs):
    """Log failed login attempts"""
    username = credentials.get('username')
    
    AuditService.log_audit_event(
        source='SECURITY',
        action='LOGIN',
        severity='HIGH',
        description=f'Failed login attempt for username: {username}',
        ip_address=request.META.get('REMOTE_ADDR'),
        user_agent=request.META.get('HTTP_USER_AGENT'),
        request=request
    )


@receiver(pre_save, sender=User)
def log_user_changes_pre(sender, instance, **kwargs):
    """Log user changes before they happen"""
    if instance.pk:
        try:
            old_instance = User.objects.get(pk=instance.pk)
            # Store old values for comparison
            request = getattr(instance, '_request', None)
            instance._old_values = {
                'email': old_instance.email,
                'is_active': old_instance.is_active,
                'is_staff': old_instance.is_staff,
                'is_superuser': old_instance.is_superuser,
            }
        except User.DoesNotExist:
            instance._old_values = {}


@receiver(post_save, sender=User)
def log_user_changes_post(sender, instance, created, **kwargs):
    """Log user changes after they happen"""
    request = getattr(instance, '_request', None)
    
    if created and request:
        # New user created
        AuditService.log_audit_event(
            actor=request.user if request and hasattr(request, 'user') else None,
            target_user=instance,
            source='ADMIN',
            action='CREATE',
            severity='MEDIUM',
            description=f'New user created: {instance.username}',
            ip_address=request.META.get('REMOTE_ADDR') if request else None,
            request=request
        )
    elif not created:
        # User updated - check for changes
        old_values = getattr(instance, '_old_values', {})
        changes = {}
        
        for field in ['email', 'is_active', 'is_staff', 'is_superuser']:
            old_val = old_values.get(field)
            new_val = getattr(instance, field)
            
            if old_val != new_val:
                changes[field] = {'old': old_val, 'new': new_val}
        
        if changes:
            # Log data change
            AuditService.log_data_change(
                object_type='User',
                object_id=str(instance.id),
                operation='UPDATE',
                user=request.user if request and hasattr(request, 'user') else None,
                old_value=old_values,
                new_value={
                    'email': instance.email,
                    'is_active': instance.is_active,
                    'is_staff': instance.is_staff,
                    'is_superuser': instance.is_superuser,
                },
                changes=changes,
                ip_address=request.META.get('REMOTE_ADDR') if request else None,
                reason='User profile update'
            )


@receiver(pre_delete, sender=User)
def log_user_deletion(sender, instance, **kwargs):
    """Log user deletion"""
    request = getattr(instance, '_request', None)
    
    AuditService.log_audit_event(
        actor=request.user if request and hasattr(request, 'user') else None,
        target_user=instance,
        source='ADMIN',
        action='DELETE',
        severity='HIGH',
        description=f'User deleted: {instance.username}',
        ip_address=request.META.get('REMOTE_ADDR') if request else None,
        request=request
    )


# Signal for important system events
def log_system_event(event_type, description, severity='MEDIUM', metadata=None):
    """Convenience function to log system events"""
    AuditService.log_audit_event(
        source='SYSTEM',
        action='SYSTEM_EVENT',
        severity=severity,
        description=f'{event_type}: {description}',
        metadata=metadata or {}
    )


# Connect to other important signals
@receiver(request_started)
def log_request_start(sender, environ, **kwargs):
    """Log request start for performance monitoring"""
    # Store start time in thread local storage
    import threading
    thread_local = threading.local()
    thread_local.request_start_time = timezone.now()


@receiver(request_finished)
def log_request_finish(sender, **kwargs):
    """Log request completion for performance monitoring"""
    import threading
    thread_local = threading.local()
    
    if hasattr(thread_local, 'request_start_time'):
        duration = timezone.now() - thread_local.request_start_time
        
        # Log slow requests
        if duration.total_seconds() > 5.0:  # 5 seconds threshold
            AuditService.log_audit_event(
                source='SYSTEM',
                action='PERFORMANCE_ISSUE',
                severity='MEDIUM',
                description=f'Slow request detected: {duration.total_seconds():.2f}s',
                metadata={'duration': duration.total_seconds()}
            )

@receiver(post_save, sender=AuditLog)
def handle_audit_notification(sender, instance, created, **kwargs):
    """
    Unified notification handler for audit logs
    """
    if not created:
        return
        
    # Check if suspicious (from original notify_suspicious_activity call)
    if hasattr(instance, 'is_suspicious') and instance.is_suspicious:
        notify_suspicious_activity(instance)
        
    # Standard security notifications
    if instance.action in ['FAILED_LOGIN', 'UNAUTHORIZED_ACCESS', 'SUSPICIOUS_ACTIVITY']:
        NotificationService.create_notification(
            user=instance.actor if instance.actor else None,
            source='audit.security',
            event_type='SECURITY',
            severity='HIGH' if instance.action == 'UNAUTHORIZED_ACCESS' else 'MEDIUM',
            title=f'Security Alert: {instance.action.replace("_", " ").title()}',
            message=f'{instance.action.replace("_", " ").title()} detected from IP {instance.ip_address}',
            related_app='audit',
            related_model='AuditLog',
            related_id=str(instance.id),
            requires_acknowledgment=True,
            metadata={
                'ip_address': instance.actor_ip,
                'user_agent': instance.actor_user_agent,
                'timestamp': str(instance.created_at)
            }
        )
