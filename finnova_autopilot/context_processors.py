from __future__ import annotations

import logging

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)


def autopilot_context(request):
    """Global autopilot context for every authenticated request.
    
    Kept lightweight — only counts, no heavy queries.
    Uses try/except on every DB call so a bad migration never breaks the entire site.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    user = request.user
    current_day = timezone.localdate()
    org = getattr(request, "active_organization", None)

    context = {
        'profile': None,
        'upcoming_bills_count': 0,
        'unread_alerts_count': 0,
        'pending_approvals_count': 0,
        'pending_count': 0,
    }

    try:
        from .models import AutopilotProfile
        profile, _ = AutopilotProfile.resolve_for_user(user, organization=org)
        context['profile'] = profile
    except Exception:
        logger.debug("autopilot_context: could not resolve profile", exc_info=True)

    try:
        from .models import SmartBill
        bills_qs = SmartBill.objects.filter(user=user, status='PENDING', due_date__gte=current_day)
        if org is not None:
            bills_qs = bills_qs.filter(Q(organization=org) | Q(organization__isnull=True))
        context['upcoming_bills_count'] = bills_qs.count()
    except Exception:
        logger.debug("autopilot_context: could not count bills", exc_info=True)

    try:
        from .models import Alert
        alerts_qs = Alert.objects.filter(user=user, is_read=False)
        if org is not None:
            alerts_qs = alerts_qs.filter(Q(organization=org) | Q(organization__isnull=True))
        context['unread_alerts_count'] = alerts_qs.count()
    except Exception:
        logger.debug("autopilot_context: could not count alerts", exc_info=True)

    try:
        from .models import ApprovalRequest
        approvals_qs = ApprovalRequest.objects.filter(user=user, status='PENDING')
        if org is not None:
            approvals_qs = approvals_qs.filter(Q(organization=org) | Q(organization__isnull=True))
        count = approvals_qs.count()
        context['pending_approvals_count'] = count
        context['pending_count'] = count
    except Exception:
        logger.debug("autopilot_context: could not count approvals", exc_info=True)

    return context
