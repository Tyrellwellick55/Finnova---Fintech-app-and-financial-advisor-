from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import (
    InviteMemberForm,
    OrganizationPolicyForm,
    OrganizationSettingsForm,
    UpdateMemberRoleForm,
)
from .models import OrganizationInvitation, OrganizationMembership, OrganizationPolicy
from .permissions import role_required, ROLE_OWNER
from eventhub.services import emit_event


@login_required
@role_required((ROLE_OWNER,))
def org_settings(request):
    org = getattr(request, 'active_organization', None)
    if not org:
        return redirect('finnovaapp:org_select')

    form = OrganizationSettingsForm(instance=org, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        emit_event(
            event_type='ORG_UPDATED',
            organization=org,
            actor=request.user,
            metadata={'org_id': str(org.id)},
            also_audit=True,
        )
        messages.success(request, 'Organization settings updated.')
        return redirect('finnovaapp:org_settings')

    return render(request, 'finnovaapp/admin/org_settings.html', {
        'organization': org,
        'form': form,
    })


@login_required
@role_required((ROLE_OWNER,))
def org_members(request):
    org = getattr(request, 'active_organization', None)
    if not org:
        return redirect('finnovaapp:org_select')

    invite_form = InviteMemberForm(data=request.POST or None, prefix='invite')
    role_form = UpdateMemberRoleForm(data=request.POST or None, prefix='role')

    if request.method == 'POST':
        if 'invite-submit' in request.POST and invite_form.is_valid():
            inv: OrganizationInvitation = invite_form.save(commit=False)
            inv.organization = org
            inv.status = OrganizationInvitation.STATUS_PENDING
            inv.save()
            emit_event(
                event_type='MEMBER_INVITED',
                organization=org,
                actor=request.user,
                metadata={'email': inv.email, 'role': inv.role, 'token': str(inv.token)},
                also_audit=True,
            )
            messages.success(request, f'Invitation sent to {inv.email}.')
            return redirect('finnovaapp:org_members')

        if 'role-submit' in request.POST and role_form.is_valid():
            membership = get_object_or_404(
                OrganizationMembership,
                id=role_form.cleaned_data['membership_id'],
                organization=org,
            )
            old_role = membership.role
            membership.role = role_form.cleaned_data['role']
            membership.save(update_fields=['role'])
            emit_event(
                event_type='MEMBER_ROLE_CHANGED',
                organization=org,
                actor=request.user,
                metadata={'user': membership.user.username, 'old_role': old_role, 'new_role': membership.role},
                also_audit=True,
            )
            messages.success(request, f"Updated {membership.user.username}'s role.")
            return redirect('finnovaapp:org_members')

    memberships = (
        OrganizationMembership.objects.filter(organization=org, is_active=True)
        .select_related('user')
        .order_by('role', 'user__username')
    )
    invitations = OrganizationInvitation.objects.filter(organization=org).order_by('-created_at')[:50]

    return render(request, 'finnovaapp/admin/org_members.html', {
        'organization': org,
        'memberships': memberships,
        'invitations': invitations,
        'invite_form': invite_form,
        'role_form': role_form,
        'now': timezone.now(),
    })


@login_required
@role_required((ROLE_OWNER,))
def org_policies(request):
    org = getattr(request, 'active_organization', None)
    if not org:
        return redirect('finnovaapp:org_select')

    policy, _ = OrganizationPolicy.objects.get_or_create(organization=org)

    form = OrganizationPolicyForm(instance=policy, data=request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        emit_event(
            event_type='POLICY_UPDATED',
            organization=org,
            actor=request.user,
            metadata={
                'approval_required': policy.approval_required,
                'max_autopay_amount': str(policy.max_autopay_amount),
                'transfer_approval_threshold': str(policy.transfer_approval_threshold),
            },
            also_audit=True,
        )
        messages.success(request, 'Policies updated.')
        return redirect('finnovaapp:org_policies')

    return render(request, 'finnovaapp/admin/org_policies.html', {
        'organization': org,
        'form': form,
    })
