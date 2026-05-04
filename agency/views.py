from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_POST

from eventhub.dispatcher import emit

from finnovaapp.models import Organization
from finnovaapp.permissions import role_required, ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS, ROLE_VIEWER, ROLE_OWNER_FINANCE, ROLE_OWNER_FINANCE_OPS
from payments_core.models import PaymentAccount, PaymentIntent
from payments_core.services.payment_processor import PaymentProcessor
from finance.services.posting import post_expense
from finnova_autopilot.models import SmartBill, ApprovalRequest

from .forms import ClientForm, ProjectForm, InvoiceForm, ControlTowerSettingsForm
from .models import Client, Project, Invoice, generate_invoice_number

logger = logging.getLogger(__name__)


def _get_org(request) -> Organization:
    org = getattr(request, 'active_organization', None)
    if org is None:
        raise Organization.DoesNotExist('No active organization selected')
    return org


def _get_primary_payment_account(user, org: Organization) -> PaymentAccount:
    account = PaymentAccount.objects.filter(user=user, organization=org, is_primary=True).first()
    if account:
        return account
    return PaymentAccount.objects.create(
        user=user,
        organization=org,
        is_primary=True,
        balance=Decimal('0.00'),
        available_balance=Decimal('0.00'),
        account_type='WALLET',
        currency='INR',
        account_number=PaymentAccount.generate_account_number(),
        is_active=True,
    )


# ── Gap fix: send invoice notification helper ─────────────────────────────────
def _notify_invoice(user, title, message, invoice=None):
    """Send notification about an invoice action."""
    try:
        from notifications.models import Notification
        Notification.objects.create(
            user=user,
            title=title,
            message=message,
            category='PAYMENT',
            severity='INFO',
            action_url=reverse('agency:receivables_dashboard'),
        )
    except Exception:
        logger.debug('Notification send failed', exc_info=True)


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def control_tower(request):
    org = _get_org(request)

    current_payroll = Decimal(str(org.metadata.get('monthly_payroll_estimate', '0') or '0'))
    if request.method == 'POST':
        form = ControlTowerSettingsForm(request.POST)
        if form.is_valid():
            payroll = form.cleaned_data.get('monthly_payroll_estimate') or Decimal('0')
            org.metadata['monthly_payroll_estimate'] = str(payroll)
            org.save(update_fields=['metadata', 'updated_at'])
            messages.success(request, 'Control Tower settings updated.')
            return redirect('agency:control_tower')
    else:
        form = ControlTowerSettingsForm(initial={'monthly_payroll_estimate': current_payroll})

    today = timezone.now().date()
    horizon_14 = today + timedelta(days=14)
    horizon_30 = today + timedelta(days=30)

    # ── Wallet balance ────────────────────────────────────────────────────────
    total_balance = PaymentAccount.objects.filter(
        organization=org, is_active=True
    ).aggregate(total=Sum('available_balance'))['total'] or Decimal('0')

    # ── Payables: org-scoped SmartBills ──────────────────────────────────────
    # Include both user-personal and org-scoped bills so Control Tower is complete
    bills_qs = SmartBill.objects.filter(
        Q(organization=org) | Q(user=request.user, organization__isnull=True),
        status__in=['PENDING', 'OVERDUE', 'FAILED'],
    )
    upcoming_bills = bills_qs.filter(due_date__lte=horizon_14).order_by('due_date')
    overdue_bills  = bills_qs.filter(due_date__lt=today).order_by('due_date')

    upcoming_payables_14 = upcoming_bills.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    overdue_payables      = overdue_bills.aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # ── Receivables: mark overdue, then query ─────────────────────────────────
    Invoice.objects.filter(
        organization=org,
        status__in=[Invoice.STATUS_DRAFT, Invoice.STATUS_SENT],
        due_date__lt=today,
    ).update(status=Invoice.STATUS_OVERDUE)

    open_invoices_qs = Invoice.objects.filter(
        organization=org,
        status__in=[Invoice.STATUS_SENT, Invoice.STATUS_OVERDUE],
    ).select_related('client', 'project').order_by('due_date')

    # ── Aggregates ────────────────────────────────────────────────────────────
    overdue_receivables = open_invoices_qs.filter(
        status=Invoice.STATUS_OVERDUE
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    due_next_14 = open_invoices_qs.filter(
        due_date__gte=today, due_date__lte=horizon_14
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    due_next_30 = open_invoices_qs.filter(
        due_date__gte=today, due_date__lte=horizon_30
    ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

    # ── Pending approvals ─────────────────────────────────────────────────────
    pending_approvals = ApprovalRequest.objects.filter(
        organization=org, status='PENDING'
    ).count()

    # ── Safe-to-spend + runway ────────────────────────────────────────────────
    safe_to_spend_14 = (total_balance + due_next_14) - upcoming_payables_14
    safe_to_spend_30 = (total_balance + due_next_30) - (upcoming_payables_14 + current_payroll)

    monthly_burn = upcoming_payables_14 + current_payroll
    runway_months = None
    if monthly_burn > 0:
        runway_months = (total_balance / monthly_burn).quantize(Decimal('0.1'))

    # ── Active projects count ─────────────────────────────────────────────────
    active_projects = Project.objects.filter(organization=org, status='ACTIVE').count()
    total_clients   = Client.objects.filter(organization=org, is_active=True).count()

    context = {
        'org': org,
        'form': form,
        'total_balance': total_balance,
        'upcoming_payables_14': upcoming_payables_14,
        'overdue_payables': overdue_payables,
        'overdue_receivables': overdue_receivables,
        'due_next_14': due_next_14,
        'due_next_30': due_next_30,
        'safe_to_spend_14': safe_to_spend_14,
        'safe_to_spend_30': safe_to_spend_30,
        'runway_months': runway_months,
        'pending_approvals': pending_approvals,
        # ── GAP 1 FIX: pass actual invoice rows ──────────────────────────────
        'open_invoices': open_invoices_qs[:6],
        'upcoming_bills': upcoming_bills[:6],
        'overdue_bills_list': overdue_bills[:3],
        'active_projects': active_projects,
        'total_clients': total_clients,
        'today': today,
    }
    return render(request, 'agency/control_tower.html', context)


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def clients_list(request):
    org = _get_org(request)
    q = (request.GET.get('q') or '').strip()
    qs = Client.objects.filter(organization=org).order_by('name')
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(company_name__icontains=q) |
            Q(email__icontains=q) | Q(phone__icontains=q)
        )
    stats = {
        'total': qs.count(),
        'active': qs.filter(is_active=True).count(),
    }
    return render(request, 'agency/clients_list.html', {'org': org, 'clients': qs, 'q': q, 'stats': stats})


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def client_create(request):
    org = _get_org(request)
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            client.organization = org
            client.save()
            try:
                emit('AGENCY_CLIENT_CREATED', actor=request.user, organization=org, metadata={
                    'client_id': str(client.id),
                    'client_name': client.company_name or client.name,
                    'description': f"Client created: {client.company_name or client.name}",
                    'action_url': reverse('agency:clients_list'),
                }, idempotency_key=f"agency:client_created:{client.id}")
            except Exception:
                logger.debug('EventHub emit failed', exc_info=True)
            messages.success(request, 'Client created.')
            return redirect('agency:clients_list')
    else:
        form = ClientForm()
    return render(request, 'agency/client_form.html', {'org': org, 'form': form, 'mode': 'create'})


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def client_edit(request, client_id):
    org = _get_org(request)
    client = get_object_or_404(Client, id=client_id, organization=org)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, 'Client updated.')
            return redirect('agency:clients_list')
    else:
        form = ClientForm(instance=client)
    return render(request, 'agency/client_form.html', {'org': org, 'form': form, 'mode': 'edit', 'client': client})


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def projects_list(request):
    org = _get_org(request)
    client_id = request.GET.get('client')
    qs = Project.objects.filter(organization=org).select_related('client').order_by('-created_at')
    if client_id:
        qs = qs.filter(client_id=client_id)
    clients = Client.objects.filter(organization=org, is_active=True).order_by('name')
    return render(request, 'agency/projects_list.html', {
        'org': org, 'projects': qs, 'clients': clients, 'client_id': client_id,
    })


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def project_create(request):
    org = _get_org(request)
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
        if form.is_valid():
            project = form.save(commit=False)
            project.organization = org
            if project.client.organization_id != org.id:
                messages.error(request, 'Invalid client selection.')
                return redirect('agency:project_create')
            project.save()
            try:
                emit('AGENCY_PROJECT_CREATED', actor=request.user, organization=org, metadata={
                    'project_id': str(project.id), 'project_name': project.name,
                    'client_name': project.client.company_name or project.client.name,
                    'description': f"Project created: {project.name}",
                    'action_url': reverse('agency:projects_list'),
                }, idempotency_key=f"agency:project_created:{project.id}")
            except Exception:
                logger.debug('EventHub emit failed', exc_info=True)
            messages.success(request, 'Project created.')
            return redirect('agency:projects_list')
    else:
        form = ProjectForm()
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
    return render(request, 'agency/project_form.html', {'org': org, 'form': form, 'mode': 'create'})


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def project_edit(request, project_id):
    org = _get_org(request)
    project = get_object_or_404(Project, id=project_id, organization=org)
    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
        if form.is_valid():
            proj = form.save(commit=False)
            if proj.client.organization_id != org.id:
                messages.error(request, 'Invalid client selection.')
                return redirect('agency:projects_list')
            proj.save()
            messages.success(request, 'Project updated.')
            return redirect('agency:projects_list')
    else:
        form = ProjectForm(instance=project)
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
    return render(request, 'agency/project_form.html', {'org': org, 'form': form, 'mode': 'edit', 'project': project})


# ── GAP 2: Auto-generate retainer invoices ────────────────────────────────────
@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def generate_retainer_invoices(request):
    """
    Loop through all ACTIVE projects with a monthly_retainer > 0
    and create an Invoice for the current month if one doesn't exist yet.
    Idempotent — checks for existing invoice with same project + month.
    """
    org = _get_org(request)
    today = timezone.now().date()
    month_prefix = today.strftime('%Y%m')
    created_count = 0
    skipped_count = 0

    active_projects = Project.objects.filter(
        organization=org,
        status='ACTIVE',
        monthly_retainer__gt=Decimal('0'),
    ).select_related('client')

    for project in active_projects:
        # Check if a retainer invoice already exists for this project this month
        existing = Invoice.objects.filter(
            organization=org,
            project=project,
            invoice_number__contains=f"-{month_prefix}-",
            title__icontains='retainer',
        ).first()

        if existing:
            skipped_count += 1
            continue

        # Create the invoice
        due_date = today.replace(day=1) + timedelta(days=32)
        due_date = due_date.replace(day=1) - timedelta(days=1)  # last day of month

        inv_number = generate_invoice_number(org.id)
        invoice = Invoice.objects.create(
            organization=org,
            client=project.client,
            project=project,
            invoice_number=inv_number,
            title=f"Monthly retainer — {project.name} ({today.strftime('%B %Y')})",
            amount=project.monthly_retainer,
            issued_date=today,
            due_date=due_date,
            status=Invoice.STATUS_DRAFT,
            created_by=request.user,
        )
        created_count += 1

        try:
            emit('AGENCY_INVOICE_CREATED', actor=request.user, organization=org, metadata={
                'invoice_id': str(invoice.id),
                'invoice_number': invoice.invoice_number,
                'client_name': project.client.company_name or project.client.name,
                'amount': str(invoice.amount),
                'due_date': str(invoice.due_date),
                'description': f"Retainer invoice generated: {invoice.invoice_number}",
                'action_url': reverse('agency:receivables_dashboard'),
            }, idempotency_key=f"agency:retainer:{project.id}:{month_prefix}")
        except Exception:
            logger.debug('EventHub emit failed', exc_info=True)

    if created_count:
        messages.success(request, f"Generated {created_count} retainer invoice{'' if created_count == 1 else 's'}.")
    else:
        messages.info(request, f"All {skipped_count} retainer invoice{'' if skipped_count == 1 else 's'} already exist for this month.")

    return redirect('agency:receivables_dashboard')


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def receivables_dashboard(request):
    org = _get_org(request)
    today = timezone.now().date()
    horizon_14 = today + timedelta(days=14)

    Invoice.objects.filter(
        organization=org,
        status__in=[Invoice.STATUS_DRAFT, Invoice.STATUS_SENT],
        due_date__lt=today,
    ).update(status=Invoice.STATUS_OVERDUE)

    status = request.GET.get('status')
    q = (request.GET.get('q') or '').strip()

    qs = Invoice.objects.filter(organization=org).select_related('client', 'project')
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(
            Q(invoice_number__icontains=q) | Q(client__name__icontains=q) |
            Q(client__company_name__icontains=q) | Q(project__name__icontains=q)
        )
    qs = qs.order_by('-due_date', '-created_at')

    open_qs = Invoice.objects.filter(organization=org, status__in=[Invoice.STATUS_SENT, Invoice.STATUS_OVERDUE])
    total_open    = open_qs.aggregate(t=Sum('amount'))['t'] or Decimal('0')
    total_overdue = open_qs.filter(status=Invoice.STATUS_OVERDUE).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    due_next_14   = open_qs.filter(due_date__gte=today, due_date__lte=horizon_14).aggregate(t=Sum('amount'))['t'] or Decimal('0')
    draft_count   = Invoice.objects.filter(organization=org, status=Invoice.STATUS_DRAFT).count()

    # Active projects with retainer for the "Generate" button
    retainer_projects = Project.objects.filter(
        organization=org, status='ACTIVE', monthly_retainer__gt=Decimal('0')
    ).count()

    return render(request, 'agency/receivables_dashboard.html', {
        'org': org, 'invoices': qs, 'status': status, 'q': q,
        'total_open': total_open, 'total_overdue': total_overdue,
        'due_next_14': due_next_14, 'draft_count': draft_count,
        'retainer_projects': retainer_projects,
        'STATUS_CHOICES': Invoice.STATUS_CHOICES,
    })


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def invoice_create(request):
    org = _get_org(request)
    if request.method == 'POST':
        form = InvoiceForm(request.POST)
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
        form.fields['project'].queryset = Project.objects.filter(organization=org).select_related('client').order_by('-created_at')
        if form.is_valid():
            inv = form.save(commit=False)
            inv.organization = org
            inv.created_by = request.user
            if inv.client.organization_id != org.id:
                messages.error(request, 'Invalid client selection.')
                return redirect('agency:invoice_create')
            if inv.project and inv.project.organization_id != org.id:
                messages.error(request, 'Invalid project selection.')
                return redirect('agency:invoice_create')
            if not inv.invoice_number:
                inv.invoice_number = generate_invoice_number(org.id)
            inv.save()
            try:
                emit('AGENCY_INVOICE_CREATED', actor=request.user, organization=org, metadata={
                    'invoice_id': str(inv.id), 'invoice_number': inv.invoice_number,
                    'client_name': inv.client.company_name or inv.client.name,
                    'amount': str(inv.amount), 'due_date': str(inv.due_date),
                    'description': f"Invoice created: {inv.invoice_number}",
                    'action_url': reverse('agency:receivables_dashboard'),
                }, idempotency_key=f"agency:invoice_created:{inv.id}")
            except Exception:
                logger.debug('EventHub emit failed', exc_info=True)
            messages.success(request, 'Invoice created.')
            return redirect('agency:receivables_dashboard')
    else:
        # Pre-fill from project if passed
        project_id = request.GET.get('project')
        initial = {'invoice_number': generate_invoice_number(org.id)}
        if project_id:
            try:
                proj = Project.objects.get(id=project_id, organization=org)
                initial['project'] = proj
                initial['client'] = proj.client
                initial['amount'] = proj.monthly_retainer
                initial['title'] = f"Monthly retainer — {proj.name}"
            except Project.DoesNotExist:
                pass
        form = InvoiceForm(initial=initial)
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
        form.fields['project'].queryset = Project.objects.filter(organization=org).select_related('client').order_by('-created_at')
    return render(request, 'agency/invoice_form.html', {'org': org, 'form': form, 'mode': 'create'})


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def invoice_edit(request, invoice_id):
    org = _get_org(request)
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)
    if request.method == 'POST':
        form = InvoiceForm(request.POST, instance=invoice)
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
        form.fields['project'].queryset = Project.objects.filter(organization=org).select_related('client').order_by('-created_at')
        if form.is_valid():
            inv = form.save(commit=False)
            if inv.client.organization_id != org.id:
                messages.error(request, 'Invalid client selection.')
                return redirect('agency:receivables_dashboard')
            if inv.project and inv.project.organization_id != org.id:
                messages.error(request, 'Invalid project selection.')
                return redirect('agency:receivables_dashboard')
            inv.save()
            messages.success(request, 'Invoice updated.')
            return redirect('agency:receivables_dashboard')
    else:
        form = InvoiceForm(instance=invoice)
        form.fields['client'].queryset = Client.objects.filter(organization=org).order_by('name')
        form.fields['project'].queryset = Project.objects.filter(organization=org).select_related('client').order_by('-created_at')
    return render(request, 'agency/invoice_form.html', {'org': org, 'form': form, 'mode': 'edit', 'invoice': invoice})


@login_required
@role_required(ROLE_OWNER_FINANCE)
def invoice_mark_paid(request, invoice_id):
    org = _get_org(request)
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    if request.method == 'POST':
        reference = (request.POST.get('reference') or '').strip() or None
        invoice.mark_paid(reference=reference)

        # ── Post to Finance income ledger ──────────────────────────────────────
        try:
            from finance.services.posting import post_income
            post_income(
                organization=org,
                user=request.user,
                amount=invoice.amount,
                source=f"{invoice.client.company_name or invoice.client.name}",
                category='BUSINESS',
                memo=f"Invoice paid: {invoice.invoice_number}",
                payment_reference=reference or invoice.payment_reference or invoice.invoice_number,
            )
        except Exception:
            logger.debug('Finance posting failed for invoice_mark_paid', exc_info=True)

        # ── Notify org owner ───────────────────────────────────────────────────
        _notify_invoice(
            request.user,
            f"Invoice {invoice.invoice_number} marked paid",
            f"₹{invoice.amount:,.2f} from {invoice.client.company_name or invoice.client.name} recorded in Finance.",
            invoice=invoice,
        )

        try:
            emit('AGENCY_INVOICE_PAID', actor=request.user, organization=org, metadata={
                'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number,
                'client_name': invoice.client.company_name or invoice.client.name,
                'amount': str(invoice.amount),
                'description': f"Invoice paid: {invoice.invoice_number}",
                'action_url': reverse('agency:receivables_dashboard'),
            }, idempotency_key=f"agency:invoice_paid:{invoice.id}:{invoice.updated_at.timestamp() if invoice.updated_at else ''}")
        except Exception:
            logger.debug('EventHub emit failed', exc_info=True)

        # ── AJAX support ───────────────────────────────────────────────────────
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({'success': True, 'invoice_number': invoice.invoice_number})

        messages.success(request, f"Invoice {invoice.invoice_number} marked as PAID. Income posted to Finance.")

    return redirect('agency:receivables_dashboard')


# ── GAP 3: Invoice send + reminder flow ──────────────────────────────────────
@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def invoice_send(request, invoice_id):
    """Mark invoice as SENT and record the send timestamp."""
    org = _get_org(request)
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    if invoice.status not in (Invoice.STATUS_DRAFT, Invoice.STATUS_SENT):
        messages.warning(request, f"Invoice {invoice.invoice_number} cannot be sent from status {invoice.status}.")
        return redirect('agency:receivables_dashboard')

    invoice.status = Invoice.STATUS_SENT
    invoice.sent_at = timezone.now()
    if not invoice.reminder_count:
        invoice.reminder_count = 0
    invoice.save(update_fields=['status', 'sent_at', 'updated_at'])

    # Notify the acting user
    _notify_invoice(
        request.user,
        f"Invoice {invoice.invoice_number} marked as sent",
        f"₹{invoice.amount:,.2f} due {invoice.due_date.strftime('%d %b %Y')} from {invoice.client.company_name or invoice.client.name}.",
        invoice=invoice,
    )

    try:
        emit('AGENCY_INVOICE_SENT', actor=request.user, organization=org, metadata={
            'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number,
            'client_name': invoice.client.company_name or invoice.client.name,
            'amount': str(invoice.amount), 'due_date': str(invoice.due_date),
            'description': f"Invoice sent: {invoice.invoice_number}",
            'action_url': reverse('agency:receivables_dashboard'),
        }, idempotency_key=f"agency:invoice_sent:{invoice.id}")
    except Exception:
        logger.debug('EventHub emit failed', exc_info=True)

    messages.success(request, f"Invoice {invoice.invoice_number} marked as sent.")
    return redirect('agency:receivables_dashboard')


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def invoice_remind(request, invoice_id):
    """Record a reminder sent to client and update reminder metadata."""
    org = _get_org(request)
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    if invoice.status not in (Invoice.STATUS_SENT, Invoice.STATUS_OVERDUE):
        messages.warning(request, "Can only send reminders for sent or overdue invoices.")
        return redirect('agency:receivables_dashboard')

    invoice.last_reminder_at = timezone.now()
    invoice.reminder_count = (invoice.reminder_count or 0) + 1
    invoice.save(update_fields=['last_reminder_at', 'reminder_count', 'updated_at'])

    _notify_invoice(
        request.user,
        f"Reminder #{invoice.reminder_count} sent for {invoice.invoice_number}",
        f"Payment reminder recorded for {invoice.client.company_name or invoice.client.name} — ₹{invoice.amount:,.2f}.",
        invoice=invoice,
    )

    try:
        emit('AGENCY_INVOICE_REMINDER', actor=request.user, organization=org, metadata={
            'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number,
            'client_name': invoice.client.company_name or invoice.client.name,
            'reminder_count': invoice.reminder_count,
            'description': f"Reminder #{invoice.reminder_count} for {invoice.invoice_number}",
        }, idempotency_key=f"agency:invoice_remind:{invoice.id}:{invoice.reminder_count}")
    except Exception:
        logger.debug('EventHub emit failed', exc_info=True)

    messages.success(request, f"Reminder #{invoice.reminder_count} recorded for {invoice.invoice_number}.")
    return redirect('agency:receivables_dashboard')


@login_required
@role_required((ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS, ROLE_VIEWER))
def invoice_pdf(request, invoice_id):
    org = _get_org(request)
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    width, height = A4

    # Header
    y = height - 50
    c.setFont('Helvetica-Bold', 20)
    c.setFillColorRGB(0, 0.784, 0.588)  # brand green
    c.drawString(50, y, org.legal_name or org.name)
    c.setFillColorRGB(0, 0, 0)
    y -= 18
    c.setFont('Helvetica', 10)
    if org.gstin:
        c.drawString(50, y, f"GSTIN: {org.gstin}")
        y -= 14
    if org.city:
        c.drawString(50, y, f"{org.city}")
        y -= 14

    # Invoice meta
    y -= 20
    c.setFont('Helvetica-Bold', 15)
    c.drawString(50, y, f"INVOICE")
    c.setFont('Helvetica', 11)
    c.drawRightString(width - 50, y, invoice.invoice_number)
    y -= 16
    c.setFont('Helvetica', 10)
    c.drawString(50, y, f"Issued: {invoice.issued_date.strftime('%d %b %Y')}   Due: {invoice.due_date.strftime('%d %b %Y')}")
    c.drawRightString(width - 50, y, f"Status: {invoice.get_status_display()}")

    # Horizontal rule
    y -= 10
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(50, y, width - 50, y)
    y -= 20

    # Bill to
    c.setFont('Helvetica-Bold', 11)
    c.drawString(50, y, 'Bill To')
    y -= 14
    c.setFont('Helvetica', 11)
    c.drawString(50, y, invoice.client.company_name or invoice.client.name)
    y -= 12
    if invoice.client.email:
        c.setFont('Helvetica', 9)
        c.drawString(50, y, invoice.client.email)
        y -= 12
    if invoice.client.phone:
        c.drawString(50, y, invoice.client.phone)
        y -= 12
    if invoice.client.gstin:
        c.drawString(50, y, f"GSTIN: {invoice.client.gstin}")
        y -= 12

    # Description
    y -= 16
    c.setFont('Helvetica-Bold', 11)
    c.drawString(50, y, 'Description')
    y -= 14
    c.setFont('Helvetica', 11)
    desc = invoice.title or (invoice.project.name if invoice.project else 'Professional Services')
    c.drawString(50, y, desc)

    # Amount block
    y -= 28
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.line(50, y, width - 50, y)
    y -= 18
    c.setFont('Helvetica-Bold', 13)
    c.drawString(50, y, 'Total Amount Due')
    c.setFillColorRGB(0, 0.784, 0.588)
    c.drawRightString(width - 50, y, f"INR {invoice.amount:,.2f}")
    c.setFillColorRGB(0, 0, 0)

    if invoice.payment_reference:
        y -= 18
        c.setFont('Helvetica', 9)
        c.drawString(50, y, f"Payment Reference: {invoice.payment_reference}")

    if invoice.notes:
        y -= 22
        c.setFont('Helvetica-Bold', 10)
        c.drawString(50, y, 'Notes')
        y -= 12
        c.setFont('Helvetica', 9)
        c.drawString(50, y, invoice.notes[:120])

    # Footer
    c.setFont('Helvetica', 8)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawString(50, 40, 'Generated by Finnova · Thank you for your business')

    c.showPage()
    c.save()
    pdf = buf.getvalue()
    buf.close()

    from django.http import HttpResponse
    resp = HttpResponse(content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="{invoice.invoice_number}.pdf"'
    resp.write(pdf)
    return resp


@login_required
@role_required((ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS, ROLE_VIEWER))
def invoice_pay(request, invoice_id):
    org = _get_org(request)
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    if invoice.status == Invoice.STATUS_PAID:
        messages.info(request, 'This invoice is already marked as PAID.')
        return redirect('agency:receivables_dashboard')

    account = _get_primary_payment_account(request.user, org)
    idempotency_key = f"invoice:{invoice.id}:pay"
    intent = PaymentIntent.objects.filter(organization=org, idempotency_key=idempotency_key).first()

    if not intent:
        intent = PaymentIntent.objects.create(
            user=request.user,
            organization=org,
            account=account,
            reference_id=PaymentIntent.generate_reference_id(),
            idempotency_key=idempotency_key,
            amount=invoice.amount,
            currency='INR',
            payment_method='DEPOSIT',
            gateway='DUMMY',
            status='CREATED',
            description=f"Invoice payment: {invoice.invoice_number}",
            metadata={
                'invoice_id': str(invoice.id),
                'invoice_number': invoice.invoice_number,
                'client_id': str(invoice.client_id),
                'project_id': str(invoice.project_id) if invoice.project_id else None,
                'source': 'agency.invoice_pay_link',
            },
        )
        invoice.payment_intent = intent
        invoice.save(update_fields=['payment_intent', 'updated_at'])

    if request.method == 'POST':
        intent.mark_success(gateway_data={'mode': 'dummy', 'source': 'invoice_pay'})
        invoice.mark_paid(reference=intent.reference_id)

        # ── Post to Finance income ─────────────────────────────────────────────
        try:
            from finance.services.posting import post_income
            post_income(
                organization=org, user=request.user, amount=invoice.amount,
                source=invoice.client.company_name or invoice.client.name,
                category='BUSINESS',
                memo=f"Invoice paid via payment link: {invoice.invoice_number}",
                payment_reference=intent.reference_id,
                related_payment=intent,
            )
        except Exception:
            logger.debug('Finance posting failed for invoice_pay', exc_info=True)

        try:
            emit('AGENCY_INVOICE_PAID', actor=request.user, organization=org, metadata={
                'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number,
                'client_name': invoice.client.company_name or invoice.client.name,
                'amount': str(invoice.amount), 'payment_reference': intent.reference_id,
                'description': f"Invoice paid: {invoice.invoice_number}",
                'action_url': reverse('agency:receivables_dashboard'),
            }, idempotency_key=f"agency:invoice_paid:{invoice.id}:{intent.reference_id}")
        except Exception:
            logger.debug('EventHub emit failed for AGENCY_INVOICE_PAID', exc_info=True)
        messages.success(request, f"Payment received for {invoice.invoice_number}.")
        return redirect('agency:receivables_dashboard')

    return render(request, 'agency/invoice_pay.html', {'org': org, 'invoice': invoice, 'intent': intent})


# ── Client portal (VIEWER role) ───────────────────────────────────────────────

@login_required
@role_required((ROLE_VIEWER,))
def client_invoice_list(request):
    org = _get_org(request)
    invoices = Invoice.objects.filter(
        organization=org
    ).select_related('client', 'project').order_by('-created_at')
    return render(request, 'agency/portal/invoices_list.html', {'org': org, 'invoices': invoices})


@login_required
@role_required((ROLE_VIEWER,))
def client_invoice_detail(request, invoice_id):
    org = _get_org(request)
    invoice = get_object_or_404(
        Invoice.objects.select_related('client', 'project'), id=invoice_id, organization=org
    )
    return render(request, 'agency/portal/invoice_detail.html', {'org': org, 'invoice': invoice})


@login_required
def client_invoice_pay(request, invoice_id):
    org = _get_org(request)
    invoice = get_object_or_404(Invoice, id=invoice_id, organization=org)

    if invoice.status == Invoice.STATUS_PAID:
        messages.info(request, 'This invoice is already PAID.')
        return redirect('agency:client_invoice_detail', invoice_id=invoice.id)

    account = _get_primary_payment_account(request.user, org)
    idempotency_key = f"invoice:{invoice.id}:client_pay"
    intent = PaymentIntent.objects.filter(organization=org, idempotency_key=idempotency_key).first()

    if not intent:
        intent = PaymentIntent.objects.create(
            user=request.user, organization=org, account=account,
            reference_id=PaymentIntent.generate_reference_id(),
            idempotency_key=idempotency_key,
            amount=invoice.amount, currency='INR',
            payment_method='DEPOSIT', gateway='DUMMY', status='CREATED',
            description=f"Invoice payment (portal): {invoice.invoice_number}",
            metadata={'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number, 'source': 'agency.client_portal'},
        )
        invoice.payment_intent = intent
        invoice.save(update_fields=['payment_intent', 'updated_at'])

    if request.method == 'POST':
        intent.mark_success(gateway_data={'mode': 'dummy', 'source': 'client_portal'})
        invoice.mark_paid(reference=intent.reference_id)

        # ── Post to Finance income ─────────────────────────────────────────────
        try:
            from finance.services.posting import post_income
            post_income(
                organization=org, user=request.user, amount=invoice.amount,
                source=invoice.client.company_name or invoice.client.name,
                category='BUSINESS',
                memo=f"Portal payment: {invoice.invoice_number}",
                payment_reference=intent.reference_id,
                related_payment=intent,
            )
        except Exception:
            logger.debug('Finance posting failed for client_invoice_pay', exc_info=True)

        try:
            emit('AGENCY_INVOICE_PAID', actor=request.user, organization=org, metadata={
                'invoice_id': str(invoice.id), 'invoice_number': invoice.invoice_number,
                'amount': str(invoice.amount), 'payment_reference': intent.reference_id,
                'description': f"Invoice paid (portal): {invoice.invoice_number}",
                'action_url': reverse('agency:client_invoice_detail', kwargs={'invoice_id': invoice.id}),
            }, idempotency_key=f"agency:portal_invoice_paid:{invoice.id}:{intent.reference_id}")
        except Exception:
            logger.debug('EventHub emit failed for portal invoice pay', exc_info=True)
        messages.success(request, 'Payment successful! Thank you.')
        return redirect('agency:client_invoice_detail', invoice_id=invoice.id)

    return render(request, 'agency/portal/invoice_pay.html', {'org': org, 'invoice': invoice, 'intent': intent})
