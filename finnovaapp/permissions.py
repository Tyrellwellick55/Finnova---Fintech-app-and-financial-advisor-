"""Shared organization + role permissions for FINNOVA.

This project is multi-tenant (Organization) and role-based (OrganizationMembership).
Most modules assume an "active organization" has been selected by middleware and stored
on the request as `request.active_organization`.

Use these helpers/decorators to consistently enforce access control across apps.
"""

from __future__ import annotations

from functools import wraps
from typing import Iterable, Optional

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from .models import Organization, OrganizationMembership


_PERSONAL_MODE_ALLOWED_MODULE_PREFIXES = (
    'finance.',
    'payments_core.',
    'finnova_autopilot.',
    'analytics_ai.',
)

_PERSONAL_MODE_DENYLIST = {
    'finnovaapp.views.ops_console',
}


def _user_has_any_active_membership(user) -> bool:
    if not user or not getattr(user, 'is_authenticated', False):
        return False
    return OrganizationMembership.objects.filter(user=user, is_active=True).exists()


def _allow_personal_mode_access(view_func) -> bool:
    qualified_name = f"{view_func.__module__}.{getattr(view_func, '__name__', '')}"
    if qualified_name in _PERSONAL_MODE_DENYLIST:
        return False
    return view_func.__module__.startswith(_PERSONAL_MODE_ALLOWED_MODULE_PREFIXES)



def get_active_org(request: HttpRequest) -> Optional[Organization]:
    return getattr(request, 'active_organization', None)


def get_membership(user, org: Organization) -> Optional[OrganizationMembership]:
    if not user or not getattr(user, 'is_authenticated', False) or not org:
        return None
    return (
        OrganizationMembership.objects
        .filter(user=user, organization=org, is_active=True)
        .select_related('organization', 'user')
        .first()
    )


def has_role(user, org: Organization, allowed_roles: Iterable[str]) -> bool:
    membership = get_membership(user, org)
    if not membership:
        return False
    return membership.role in set(allowed_roles)


def org_required(view_func):
    """Require an authenticated user and an active organization."""

    @login_required
    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
        org = get_active_org(request)
        if not org:
            messages.warning(request, 'Please select a workspace to continue.')
            return redirect('finnovaapp:org_select')
        return view_func(request, *args, **kwargs)

    return _wrapped


def role_required(allowed_roles: Iterable[str]):
    """Require the user to have one of the allowed org roles.

    Personal-finance mode is allowed for selected product modules when the user has
    no active organization memberships at all. This keeps Finance/Payments/Autopilot/
    Analytics usable without forcing a business-workspace selection, while leaving
    org-only areas like Audit, Agency, and Ops Console protected.
    """

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            org = get_active_org(request)
            if org is None:
                if not _user_has_any_active_membership(request.user) and _allow_personal_mode_access(view_func):
                    return view_func(request, *args, **kwargs)
                messages.warning(request, 'Please select a workspace to continue.')
                return redirect('finnovaapp:org_select')

            if not has_role(request.user, org, allowed_roles):
                messages.error(request, 'You do not have permission to access this page.')
                return redirect('finnovaapp:dashboard')
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


def permission_required(perm: str, raise_exception: bool = False):
    """Org-aware variant of Django's permission_required.

    Many apps in this project use Django model permissions (e.g. audit.view_auditlog)
    alongside org roles. This decorator ensures the user is authenticated, has an
    active organization, and then checks `user.has_perm(perm)`.
    """

    def decorator(view_func):
        @org_required
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            if request.user.has_perm(perm):
                return view_func(request, *args, **kwargs)
            if raise_exception:
                raise PermissionDenied
            messages.error(request, 'You do not have permission to perform this action.')
            return redirect('finnovaapp:dashboard')

        return _wrapped

    return decorator


# Convenience constants
ROLE_OWNER = OrganizationMembership.ROLE_OWNER
ROLE_FINANCE = OrganizationMembership.ROLE_FINANCE
ROLE_OPERATIONS = OrganizationMembership.ROLE_OPERATIONS
ROLE_VIEWER = OrganizationMembership.ROLE_VIEWER

ROLE_OWNER_FINANCE = (ROLE_OWNER, ROLE_FINANCE)
ROLE_OWNER_FINANCE_OPS = (ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS)
