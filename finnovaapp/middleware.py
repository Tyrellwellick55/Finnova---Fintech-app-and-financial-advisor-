from __future__ import annotations

from .models import Organization, OrganizationMembership


class OrganizationMiddleware:
    """Attach the currently selected organization to request.

    We no longer force workspace selection for every authenticated request.
    That keeps the personal-finance experience usable. Org-only views still
    enforce workspace requirements via decorators.
    """

    SESSION_KEY = 'active_org_id'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.active_organization = None
        request.available_organizations_count = 0

        if request.user.is_authenticated:
            memberships = OrganizationMembership.objects.filter(
                user=request.user,
                is_active=True,
                organization__is_active=True,
            ).select_related('organization')
            request.available_organizations_count = memberships.count()

            org_id = request.session.get(self.SESSION_KEY)
            if org_id:
                request.active_organization = Organization.objects.filter(
                    id=org_id,
                    is_active=True,
                    memberships__user=request.user,
                    memberships__is_active=True,
                ).distinct().first()
                if request.active_organization is None:
                    request.session.pop(self.SESSION_KEY, None)

            if request.active_organization is None and request.available_organizations_count == 1:
                request.active_organization = memberships[0].organization
                request.session[self.SESSION_KEY] = str(request.active_organization.id)

        return self.get_response(request)
