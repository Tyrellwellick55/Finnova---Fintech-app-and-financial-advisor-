import logging
logger = logging.getLogger(__name__)
from django.conf import settings

from .models import OrganizationMembership, UserProfile


def user_context(request):
    """Global shell context used by the cross-module app chrome."""
    resolver_match = getattr(request, 'resolver_match', None)
    route_name = resolver_match.url_name if resolver_match else ''
    public_routes = {
        'landing',
        'login',
        'signup',
        'about',
        'contact',
        'privacy_policy',
        'terms_of_service',
        'faq',
        'password_reset',
        'password_reset_done',
        'password_reset_confirm',
        'password_reset_complete',
        'onboarding',
    }
    context = {
        'show_agency_ui': getattr(settings, 'FINNOVA_ENABLE_AGENCY_UI', False),
        'current_organization': getattr(request, 'active_organization', None),
        'org_role': None,
        'user_profile': None,
        'unread_notifications': 0,
        'notification_count': 0,
        'total_unread': 0,
        'security_alerts_count': 0,
        'workspace_count': 0,
        'has_workspace': False,
        'is_personal_mode': True,
        'shell_mode': 'public' if route_name in public_routes else 'app',
        'shell_modules': {
            'finance': False,
            'analytics': False,
            'autopilot': False,
            'notifications': False,
            'payments': False,
            'audit': False,
            'ops': False,
            'agency': False,
            'client_portal': False,
        },
    }

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return context

    context['current_user'] = user

    try:
        context['user_profile'] = getattr(user, 'profile', None)
    except UserProfile.DoesNotExist:
        context['user_profile'] = None

    org = context['current_organization']
    if org is not None:
        try:
            membership = OrganizationMembership.objects.filter(
                organization=org, user=user, is_active=True
            ).only('role').first()
            context['org_role'] = membership.role if membership else None
        except Exception:
            context['org_role'] = None

    try:
        workspace_count = OrganizationMembership.objects.filter(user=user, is_active=True).count()
        context['workspace_count'] = workspace_count
        context['has_workspace'] = workspace_count > 0
    except Exception:
        pass

    agency_enabled = context['show_agency_ui']
    personal_mode = context['current_organization'] is None or context['org_role'] is None
    context['is_personal_mode'] = personal_mode

    if personal_mode:
        context['shell_modules'] = {
            'finance': True,
            'analytics': True,
            'autopilot': True,
            'notifications': True,
            'payments': True,
            'audit': user.is_staff,
            'ops': False,
            'agency': False,      # Agency requires an org workspace
            'client_portal': False,
        }
    else:
        operational_role = context['org_role'] in ('OWNER', 'FINANCE', 'OPERATIONS')
        context['shell_modules'] = {
            'finance': operational_role,
            'analytics': operational_role,
            'autopilot': operational_role,
            'notifications': True,
            'payments': operational_role,
            'audit': context['org_role'] in ('OWNER', 'FINANCE'),
            'ops': context['org_role'] in ('OWNER', 'OPERATIONS'),
            'agency': agency_enabled and context['org_role'] in ('OWNER', 'FINANCE', 'OPERATIONS', 'VIEWER'),
            'client_portal': agency_enabled and context['org_role'] == 'VIEWER',
        }

    try:
        from notifications.models import Notification

        unread = Notification.objects.filter(user=user, is_read=False).count()
        context['unread_notifications'] = unread
        context['notification_count'] = unread
        context['total_unread'] = unread
    except Exception:
        pass

    try:
        from audit.models import SecurityAlert
        alerts = SecurityAlert.objects.filter(is_active=True).exclude(status='RESOLVED')
        # Only filter by user if the model has that field
        if any(f.name == 'user' for f in SecurityAlert._meta.get_fields()):
            alerts = alerts.filter(user=user)
        context['security_alerts_count'] = alerts.count()
    except Exception:
        logger.debug("user_context: could not count security alerts", exc_info=True)

    try:
        from finnova_autopilot.models import ApprovalRequest
        context['pending_approvals_count'] = ApprovalRequest.objects.filter(
            user=user, status='PENDING'
        ).count()
    except Exception:
        context['pending_approvals_count'] = 0

    return context
