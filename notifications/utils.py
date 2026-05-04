from typing import List, Dict, Any
from django.contrib.auth import get_user_model
from .services import NotificationService

User = get_user_model()


def notify_admins(
    title: str,
    message: str,
    severity: str = 'HIGH',
    source: str = 'system.admin',
    **kwargs
):
    """
    Send notification to all admin users
    """
    admins = User.objects.filter(is_staff=True, is_active=True)
    
    return NotificationService.create_bulk_notifications(
        users=list(admins),
        source=source,
        event_type='SYSTEM',
        severity=severity,
        title=title,
        message=message,
        **kwargs
    )


def notify_department(
    department: str,
    title: str,
    message: str,
    severity: str = 'MEDIUM',
    source: str = 'system.department',
    **kwargs
):
    """
    Send notification to users in a specific department
    """
    # This assumes User model has a department field
    # Adjust based on your actual User model
    users = User.objects.filter(
        profile__department=department,
        is_active=True
    )
    
    return NotificationService.create_bulk_notifications(
        users=list(users),
        source=source,
        event_type='SYSTEM',
        severity=severity,
        title=title,
        message=message,
        **kwargs
    )


def create_audit_trail_notification(
    user,
    action: str,
    resource: str,
    resource_id: str,
    changes: Dict[str, Any] = None,
    ip_address: str = None,
    user_agent: str = None
):
    """
    Create standardized audit trail notification
    """
    from .services import NotificationService
    
    return NotificationService.create_notification(
        user=user,
        source='audit.trail',
        event_type='AUDIT',
        severity='INFO',
        title=f'Audit: {action} on {resource}',
        message=f'User performed {action} on {resource} {resource_id}',
        related_app='audit',
        related_model=resource,
        related_id=resource_id,
        metadata={
            'action': action,
            'resource': resource,
            'resource_id': resource_id,
            'changes': changes or {},
            'ip_address': ip_address,
            'user_agent': user_agent
        }
    )