import logging
logger = logging.getLogger(__name__)
# audit/views.py - COMPLETE AUDIT MODULE VIEWS
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from finnovaapp.permissions import role_required, ROLE_OWNER, ROLE_OWNER_FINANCE, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.generic import ListView, DetailView, TemplateView
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Q, Count, Avg, Max, Min,F
from django.utils.decorators import method_decorator
from datetime import datetime, timedelta
import json
import csv

from .models import AuditLog, SecurityAlert, ComplianceRecord, AuditTrail, SystemControl, UserRiskFlag
from .services import AuditService
from payments_core.models import PaymentTransaction, PaymentIntent
from finance.models import Expense, Income
from finnova_autopilot.models import Alert
from analytics_ai.models import FinancialInsight
from django.contrib.auth import get_user_model

User = get_user_model()

# ========== DASHBOARD VIEWS ==========

@login_required
@role_required(ROLE_OWNER_FINANCE)
def audit_dashboard(request):
    """Main audit dashboard with integrated analytics"""
    try:
        can_view_full = (
            request.user.is_staff
            or request.user.is_superuser
            or request.user.has_perm('audit.view_auditlog')
        )
        
        # Get statistics
        if can_view_full:
            stats = AuditService.get_audit_stats('today')
        else:
            user_logs = AuditLog.objects.filter(
                Q(actor=request.user) | Q(target_user=request.user)
            )
            user_alerts = SecurityAlert.objects.filter(user=request.user)
            stats = {
                'total_logs': user_logs.count(),
                'critical_alerts': user_alerts.filter(severity='CRITICAL').count(),
                'high_risk_users': UserRiskFlag.objects.filter(user=request.user, is_active=True).count(),
                'compliance_score': 100 - min(
                    ComplianceRecord.objects.filter(user=request.user, status='PENDING').count() * 10,
                    100
                ),
                'logs_increase': 0,
            }
        
        stats.setdefault('logs_increase', 0)
        stats.setdefault('critical_alerts', 0)
        stats.setdefault('high_risk_users', 0)
        stats.setdefault('compliance_score', 100)
        
        if can_view_full:
            log_queryset = AuditLog.objects.all()
            alert_queryset = SecurityAlert.objects.all()
            compliance_queryset = ComplianceRecord.objects.all()
            expense_queryset = Expense.objects.all()
            txn_queryset = PaymentTransaction.objects.all()
            risk_queryset = UserRiskFlag.objects.all()
        else:
            log_queryset = AuditLog.objects.filter(
                Q(actor=request.user) | Q(target_user=request.user)
            )
            alert_queryset = SecurityAlert.objects.filter(user=request.user)
            compliance_queryset = ComplianceRecord.objects.filter(user=request.user)
            expense_queryset = Expense.objects.filter(user=request.user)
            txn_queryset = PaymentTransaction.objects.filter(account__user=request.user)
            risk_queryset = UserRiskFlag.objects.filter(user=request.user)
        
        # Recent logs with severity analysis
        recent_logs = log_queryset.select_related(
            'actor', 'target_user'
        ).order_by('-created_at')[:10]
        
        # Open security alerts
        open_alerts = alert_queryset.filter(
            status__in=['OPEN', 'INVESTIGATING']
        ).select_related('user').order_by('-detected_at')[:5]
        
        # Pending compliance
        pending_compliance = compliance_queryset.filter(
            status='PENDING'
        ).order_by('due_date')[:5]
        
        # High-risk transactions (from payments_core)
        suspicious_transactions = txn_queryset.filter(
            is_suspicious=True
        ).select_related('account__user').order_by('-transaction_date')[:5]
        
        # Financial anomalies (from finance module)
        large_expenses = expense_queryset.filter(
            amount__gte=50000
        ).select_related('user').order_by('-date')[:5]
        
        # System controls
        system_controls = SystemControl.objects.first()
        
        # User risk flags
        risk_flags = risk_queryset.filter(
            is_active=True
        ).select_related('user', 'flagged_by').order_by('-risk_score')[:5]
        
        # Daily activity chart data
        today = timezone.now().date()
        daily_activity = []
        for i in range(7, -1, -1):
            date = today - timedelta(days=i)
            count = log_queryset.filter(
                created_at__date=date
            ).count()
            daily_activity.append({
                'date': date.strftime('%b %d'),
                'count': count
            })
        
        context = {
            'stats': stats,
            'recent_logs': recent_logs,
            'open_alerts': open_alerts,
            'pending_compliance': pending_compliance,
            'suspicious_transactions': suspicious_transactions,
            'large_expenses': large_expenses,
            'system_controls': system_controls,
            'risk_flags': risk_flags,
            'daily_activity': daily_activity,
            'today': today,
        }
        
        return render(request, 'audit/dashboard.html', context)
        
    except Exception as e:
        messages.error(request, f"Error loading dashboard: {str(e)}")
        return render(request, 'finnovaapp/error.html', {'error': str(e)})

# ========== AUDIT LOG MANAGEMENT ==========

@method_decorator(login_required, name='dispatch')
@method_decorator(permission_required('audit.view_auditlog', raise_exception=True), name='dispatch')
class AuditLogListView(ListView):
    """List view for audit logs with advanced filtering"""
    model = AuditLog
    template_name = 'audit/log_list.html'
    context_object_name = 'logs'
    paginate_by = 50
    
    def get_queryset(self):
        queryset = AuditLog.objects.all().select_related(
            'actor', 'target_user', 'parent_event'
        ).order_by('-created_at')
        
        # Filters
        if source := self.request.GET.get('source'):
            queryset = queryset.filter(source=source)
        
        if action := self.request.GET.get('action'):
            queryset = queryset.filter(action=action)
        
        if severity := self.request.GET.get('severity'):
            queryset = queryset.filter(severity=severity)
        
        if actor_id := self.request.GET.get('actor'):
            queryset = queryset.filter(actor_id=actor_id)
        
        if target_id := self.request.GET.get('target'):
            queryset = queryset.filter(target_user_id=target_id)
        
        if search := self.request.GET.get('search'):
            queryset = queryset.filter(
                Q(description__icontains=search) |
                Q(metadata__icontains=search) |
                Q(actor__username__icontains=search) |
                Q(target_user__username__icontains=search)
            )
        
        if date_from := self.request.GET.get('date_from'):
            queryset = queryset.filter(created_at__date__gte=date_from)
        
        if date_to := self.request.GET.get('date_to'):
            queryset = queryset.filter(created_at__date__lte=date_to)
        
        return queryset
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Filter options
        context['sources'] = AuditLog.objects.values_list(
            'source', flat=True
        ).distinct().order_by('source')
        
        context['actions'] = AuditLog.objects.values_list(
            'action', flat=True
        ).distinct().order_by('action')
        
        context['severities'] = AuditLog.SEVERITY_CHOICES
        
        # Active filters
        context['active_filters'] = {
            'source': self.request.GET.get('source', ''),
            'action': self.request.GET.get('action', ''),
            'severity': self.request.GET.get('severity', ''),
            'search': self.request.GET.get('search', ''),
            'date_from': self.request.GET.get('date_from', ''),
            'date_to': self.request.GET.get('date_to', ''),
        }
        
        return context

@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def audit_log_detail(request, log_id):
    """Detailed view for audit log"""
    log = get_object_or_404(AuditLog, id=log_id)
    
    # Get related logs
    related_logs = AuditLog.objects.filter(
        Q(actor=log.actor) | Q(target_user=log.target_user),
        created_at__date=log.created_at.date()
    ).exclude(id=log.id).order_by('-created_at')[:10]
    
    # Get related transaction if applicable
    related_transaction = None
    if log.metadata and 'transaction_id' in log.metadata:
        try:
            related_transaction = PaymentTransaction.objects.get(
                id=log.metadata['transaction_id']
            )
        except PaymentTransaction.DoesNotExist:
            pass
    
    context = {
        'log': log,
        'related_logs': related_logs,
        'related_transaction': related_transaction,
    }
    
    return render(request, 'audit/log_detail.html', context)

# ========== SECURITY ALERTS ==========

@login_required
@permission_required('audit.view_securityalert', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def security_alerts(request):
    """Security alerts management"""
    alerts = SecurityAlert.objects.all().select_related(
        'user', 'resolved_by'
    ).order_by('-detected_at')
    
    # Filters
    status = request.GET.get('status')
    if status:
        alerts = alerts.filter(status=status)
    
    severity = request.GET.get('severity')
    if severity:
        alerts = alerts.filter(severity=severity)
    
    search = request.GET.get('search')
    if search:
        alerts = alerts.filter(
            Q(title__icontains=search) |
            Q(description__icontains=search) |
            Q(user__username__icontains=search)
        )
    
    # Statistics
    stats = {
        'total': alerts.count(),
        'open': alerts.filter(status='OPEN').count(),
        'investigating': alerts.filter(status='INVESTIGATING').count(),
        'resolved': alerts.filter(status='RESOLVED').count(),
        'critical': alerts.filter(severity='CRITICAL').count(),
        'high': alerts.filter(severity='HIGH').count(),
    }
    
    paginator = Paginator(alerts, 20)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)
    
    context = {
        'alerts': page_obj,
        'stats': stats,
        'status_choices': SecurityAlert.STATUS_CHOICES,
        'severity_choices': SecurityAlert.SEVERITY_CHOICES,
    }
    
    return render(request, 'audit/security_alerts.html', context)

@login_required
@permission_required('audit.change_securityalert', raise_exception=True)
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def mark_alert_resolved(request, alert_id):
    """Mark security alert as resolved"""
    alert = get_object_or_404(SecurityAlert, id=alert_id)
    
    try:
        notes = request.POST.get('notes', '')
        resolution_type = request.POST.get('resolution_type', '')
        alert.mark_as_resolved(request.user, notes, resolution_type)
        
        # Log the resolution
        AuditLog.objects.create(
            actor=request.user,
            action='SECURITY_ALERT_RESOLVED',
            description=f'Resolved security alert: {alert.title}',
            severity='INFO',
            metadata={
                'alert_id': alert.id,
                'resolved_by': request.user.username,
                'resolution_notes': notes,
                'resolution_type': resolution_type,
            }
        )
        
        messages.success(request, 'Alert marked as resolved successfully.')
        return redirect('audit:alert_list')
        
    except Exception as e:
        messages.error(request, f'Error resolving alert: {str(e)}')
        return redirect('audit:alert_list')

@login_required
@permission_required('audit.change_securityalert', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def resolve_alert_page(request, alert_id):
    """Detailed resolution page for a single security alert."""
    alert = get_object_or_404(SecurityAlert, id=alert_id)
    return render(request, 'audit/resolve_alert.html', {'alert': alert})

# ========== COMPLIANCE MANAGEMENT ==========

@login_required
@permission_required('audit.view_compliancerecord', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def compliance_dashboard(request):
    """Compliance tracking dashboard"""
    # Get compliance by type
    compliance_by_type = {}
    for compliance_type, display_name in ComplianceRecord.COMPLIANCE_TYPES:
        records = ComplianceRecord.objects.filter(
            compliance_type=compliance_type
        ).select_related('user', 'verified_by')
        
        compliance_by_type[display_name] = {
            'total': records.count(),
            'pending': records.filter(status='PENDING').count(),
            'approved': records.filter(status='COMPLETED').count(),
            'overdue': records.filter(status='OVERDUE').count(),
            'verified': records.filter(verified=True).count(),
        }
    
    # Upcoming deadlines (next 30 days)
    upcoming_deadlines = ComplianceRecord.objects.filter(
        due_date__gte=timezone.now().date(),
        due_date__lte=timezone.now().date() + timedelta(days=30),
        status__in=['PENDING', 'OVERDUE']
    ).select_related('user').order_by('due_date')[:10]
    
    # Overdue items
    overdue_items = ComplianceRecord.objects.filter(
        status='OVERDUE'
    ).select_related('user').order_by('due_date')[:10]
    
    # Recent verifications
    recent_verifications = ComplianceRecord.objects.filter(
        verified=True
    ).select_related('user', 'verified_by').order_by('-verification_date')[:10]
    
    context = {
        'compliance_by_type': compliance_by_type,
        'upcoming_deadlines': upcoming_deadlines,
        'overdue_items': overdue_items,
        'recent_verifications': recent_verifications,
        'users': User.objects.filter(is_active=True).order_by('username')[:500],
        'today': timezone.now().date(),
    }
    
    return render(request, 'audit/compliance_dashboard.html', context)

@login_required
@permission_required('audit.view_compliancerecord', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def add_compliance(request):
    """Create compliance records from dashboard modal and dedicated add page."""
    if request.method == 'GET':
        context = {
            'users': User.objects.filter(is_active=True).order_by('username')[:500],
        }
        return render(request, 'audit/add_compliance.html', context)

    try:
        compliance_type = request.POST.get('compliance_type', 'KYC')
        requirement = (request.POST.get('requirement') or '').strip()
        description = (request.POST.get('description') or '').strip()
        due_date_raw = request.POST.get('due_date')
        entity_type = (request.POST.get('entity_type') or '').strip()
        user_id = request.POST.get('user')

        if not requirement:
            messages.error(request, 'Requirement is required.')
            return redirect('audit:add_compliance')
        if not due_date_raw:
            messages.error(request, 'Due date is required.')
            return redirect('audit:add_compliance')

        assigned_user = None
        if user_id:
            assigned_user = get_object_or_404(User, id=user_id)

        due_date = datetime.strptime(due_date_raw, '%Y-%m-%d').date()

        metadata = {
            'priority': request.POST.get('priority', 'MEDIUM'),
            'send_notification': request.POST.get('send_notification') == 'true',
            'requires_verification': request.POST.get('requires_verification') == 'true',
            'created_by': request.user.username,
        }

        record = ComplianceRecord.objects.create(
            compliance_type=compliance_type,
            requirement=requirement,
            description=description,
            user=assigned_user,
            entity_type='USER' if assigned_user else (entity_type or 'SYSTEM'),
            due_date=due_date,
            status='PENDING',
            metadata=metadata,
        )

        AuditLog.objects.create(
            actor=request.user,
            target_user=assigned_user,
            action='COMPLIANCE_CREATED',
            description=f'Created compliance requirement: {record.requirement}',
            severity='INFO',
            metadata={
                'record_id': str(record.id),
                'compliance_type': record.compliance_type,
                'due_date': record.due_date.isoformat(),
            },
        )

        messages.success(request, 'Compliance record created successfully.')
        return redirect('audit:compliance')
    except ValueError:
        messages.error(request, 'Invalid due date format.')
        return redirect('audit:add_compliance')
    except Exception as e:
        messages.error(request, f'Error creating compliance record: {str(e)}')
        return redirect('audit:add_compliance')

@login_required
@permission_required('audit.verify_compliancerecord', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def verify_compliance(request, record_id):
    """Verify compliance record"""
    record = get_object_or_404(ComplianceRecord, id=record_id)

    if request.method == 'GET':
        return render(request, 'audit/verify_compliance.html', {'record': record})

    try:
        document_url = request.POST.get('document_url', '')
        notes = request.POST.get('notes', '')
        verification_method = request.POST.get('verification_method', '').strip()
        next_review_date = request.POST.get('next_review_date')

        record.mark_completed(verified_by=request.user, notes=notes)
        record.verification_method = verification_method or record.verification_method
        if document_url:
            record.evidence = {
                **(record.evidence or {}),
                'document_url': document_url,
            }
        if next_review_date:
            try:
                record.next_review_date = datetime.strptime(next_review_date, '%Y-%m-%d').date()
            except ValueError:
                pass
        record.save()

        # Log the verification
        AuditLog.objects.create(
            actor=request.user,
            target_user=record.user,
            action='COMPLIANCE_VERIFIED',
            description=f'Verified compliance: {record.requirement}',
            severity='INFO',
            metadata={
                'record_id': str(record.id),
                'compliance_type': record.compliance_type,
                'verified_by': request.user.username,
                'verification_method': verification_method,
            }
        )
        
        messages.success(request, 'Compliance record verified successfully.')
        return redirect('audit:compliance')
        
    except Exception as e:
        messages.error(request, f'Error verifying compliance: {str(e)}')
        return redirect('audit:compliance')

# ========== USER RISK MANAGEMENT ==========

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser, login_url='finnovaapp:dashboard')
@permission_required('audit.view_userriskflag', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def user_risk_management(request):
    """User risk flag management"""
    risk_flags = UserRiskFlag.objects.all().select_related(
        'user', 'flagged_by'
    ).order_by('-created_at')
    
    # Filters
    risk_type = request.GET.get('risk_type')
    if risk_type:
        risk_flags = risk_flags.filter(risk_type=risk_type)
    
    is_active = request.GET.get('is_active')
    if is_active:
        risk_flags = risk_flags.filter(is_active=(is_active == 'true'))
    
    search = request.GET.get('search')
    if search:
        risk_flags = risk_flags.filter(
            Q(user__username__icontains=search) |
            Q(description__icontains=search)
        )
    
    # Risk score distribution
    risk_distribution = {
        'high': risk_flags.filter(risk_score__gte=70).count(),
        'medium': risk_flags.filter(risk_score__gte=40, risk_score__lt=70).count(),
        'low': risk_flags.filter(risk_score__lt=40).count(),
    }
    
    paginator = Paginator(risk_flags, 20)
    page = request.GET.get('page')
    page_obj = paginator.get_page(page)
    
    context = {
        'risk_flags': page_obj,
        'risk_distribution': risk_distribution,
        'risk_types': UserRiskFlag.RISK_TYPES,
    }
    
    return render(request, 'audit/user_risk_management.html', context)

@login_required
@permission_required('audit.add_userriskflag', raise_exception=True)
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def flag_user_risk(request):
    """Flag user as risky"""
    try:
        data = json.loads(request.body) if request.body else {}
        
        user_id = data.get('user_id')
        risk_type = data.get('risk_type')
        description = data.get('description')
        risk_score = data.get('risk_score', 50)
        evidence = data.get('evidence', {})
        
        if not user_id or not risk_type or not description:
            return JsonResponse({
                'success': False,
                'error': 'Missing required fields'
            }, status=400)
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = get_object_or_404(User, id=user_id)
        
        # Create risk flag
        risk_flag = UserRiskFlag.objects.create(
            user=user,
            flagged_by=request.user,
            risk_type=risk_type,
            description=description,
            risk_score=risk_score,
            evidence=evidence,
            is_active=True
        )
        
        # Log the action
        AuditLog.objects.create(
            actor=request.user,
            target_user=user,
            action='USER_RISK_FLAGGED',
            description=f'Flagged user {user.username} as risky: {description}',
            severity='HIGH',
            metadata={
                'risk_flag_id': risk_flag.id,
                'risk_type': risk_type,
                'risk_score': risk_score
            }
        )
        
        # Create security alert
        SecurityAlert.objects.create(
            user=user,
            alert_type='USER_RISK',
            title=f'User Flagged as Risky: {risk_type}',
            description=description,
            severity='HIGH' if risk_score >= 70 else 'MEDIUM',
            status='OPEN',
            investigation_data={
                'flagged_by': request.user.username,
                'risk_score': risk_score,
                'evidence': evidence
            }
        )
        
        return JsonResponse({
            'success': True,
            'risk_flag_id': risk_flag.id,
            'message': 'User flagged successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@permission_required('audit.change_userriskflag', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def resolve_risk_flag(request, flag_id):
    """Resolve risk flag"""
    risk_flag = get_object_or_404(UserRiskFlag, id=flag_id)

    if request.method == 'GET':
        return render(request, 'audit/resolve_risk_flag.html', {'flag': risk_flag})

    try:
        resolution_notes = request.POST.get('resolution_notes', '')
        new_risk_score_raw = request.POST.get('new_risk_score')

        if new_risk_score_raw not in (None, ''):
            try:
                risk_flag.update_risk_score(
                    int(new_risk_score_raw),
                    reason='Updated during risk resolution',
                )
            except ValueError:
                pass

        risk_flag.mark_resolved(request.user, resolution_notes)
        
        # Log the resolution
        AuditLog.objects.create(
            actor=request.user,
            target_user=risk_flag.user,
            action='USER_RISK_RESOLVED',
            description=f'Resolved risk flag for {risk_flag.user.username}',
            severity='INFO',
            metadata={
                'risk_flag_id': str(risk_flag.id),
                'resolution_notes': resolution_notes,
                'resolved_by': request.user.username
            }
        )
        
        messages.success(request, 'Risk flag resolved successfully.')
        return redirect('audit:user_management')
        
    except Exception as e:
        messages.error(request, f'Error resolving risk flag: {str(e)}')
        return redirect('audit:user_management')

# ========== SYSTEM CONTROLS ==========

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser, login_url='finnovaapp:dashboard')
@permission_required('audit.view_systemcontrol', raise_exception=True)
@role_required((ROLE_OWNER,))
def system_controls(request):
    """System controls management"""
    controls = SystemControl.objects.first() or SystemControl.objects.create()
    existing_metadata = controls.metadata or {}
    config_data = existing_metadata.get('configuration', {})
    
    if request.method == 'POST':
        try:
            def _is_enabled(field_name):
                return str(request.POST.get(field_name, '')).lower() in {'1', 'true', 'on', 'yes'}

            controls.autopilot_enabled = _is_enabled('autopilot_enabled')
            controls.ai_enabled = _is_enabled('ai_enabled')
            controls.emergency_message = request.POST.get('emergency_message', '').strip() or None
            
            # Parse configuration JSON
            config_json = request.POST.get('configuration', '{}')
            try:
                config_data = json.loads(config_json)
            except json.JSONDecodeError:
                config_data = {}

            metadata = controls.metadata or {}
            metadata['configuration'] = config_data
            controls.metadata = metadata
            
            controls.save()
            
            # Log the update
            AuditLog.objects.create(
                actor=request.user,
                action='SYSTEM_CONTROLS_UPDATED',
                description='Updated system controls configuration',
                severity='INFO',
                metadata={
                    'autopilot_enabled': controls.autopilot_enabled,
                    'ai_enabled': controls.ai_enabled,
                    'updated_by': request.user.username
                }
            )
            
            messages.success(request, 'System controls updated successfully.')
            return redirect('audit:system_controls')
            
        except Exception as e:
            messages.error(request, f'Error updating system controls: {str(e)}')
    
    context = {
        'controls': controls,
        'config_json': json.dumps(config_data, indent=2),
    }
    
    return render(request, 'audit/system_controls.html', context)


@login_required
@permission_required('audit.export_audit_logs', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def export_audit_data(request):
    """Export audit data (API endpoint only - export.html removed)."""
    if 'format' not in request.GET:
        # Previously rendered export.html; redirect to reports instead.
        return redirect('audit:reports')

    format_type = request.GET.get('format', 'csv')
    date_from = request.GET.get('date_from', (timezone.now() - timedelta(days=30)).date())
    date_to = request.GET.get('date_to', timezone.now().date())
    
    try:
        data_type = request.GET.get('type', 'logs')
        
        if data_type == 'logs':
            queryset = AuditLog.objects.filter(
                created_at__date__range=[date_from, date_to]
            )
            filename = f'audit_logs_{date_from}_to_{date_to}.{format_type}'
        elif data_type == 'alerts':
            queryset = SecurityAlert.objects.filter(
                detected_at__date__range=[date_from, date_to]
            )
            filename = f'security_alerts_{date_from}_to_{date_to}.{format_type}'
        elif data_type == 'compliance':
            queryset = ComplianceRecord.objects.filter(
                created_at__date__range=[date_from, date_to]
            )
            filename = f'compliance_records_{date_from}_to_{date_to}.{format_type}'
        elif data_type == 'risk':
            queryset = UserRiskFlag.objects.filter(
                created_at__date__range=[date_from, date_to]
            )
            filename = f'risk_flags_{date_from}_to_{date_to}.{format_type}'
        else:
            return JsonResponse({'error': 'Invalid data type'}, status=400)
        
        if format_type == 'json':
            data = list(queryset.values())
            response = HttpResponse(
                json.dumps(data, default=str, indent=2),
                content_type='application/json'
            )
        elif format_type == 'csv':
            response = HttpResponse(content_type='text/csv')
            writer = csv.writer(response)
            
            # Write headers based on data type
            if data_type == 'logs':
                writer.writerow(['ID', 'Timestamp', 'Actor', 'Action', 'Severity', 'Description', 'Source'])
                for item in queryset:
                    writer.writerow([
                        item.id,
                        item.created_at,
                        item.actor.username if item.actor else 'System',
                        item.action,
                        item.severity,
                        item.description[:100],
                        item.source
                    ])
            elif data_type == 'alerts':
                writer.writerow(['ID', 'Created', 'User', 'Type', 'Severity', 'Status', 'Title', 'Description'])
                for item in queryset:
                    writer.writerow([
                        item.id,
                        item.detected_at,
                        item.user.username if item.user else 'System',
                        item.alert_type,
                        item.severity,
                        item.status,
                        item.title,
                        item.description[:100]
                    ])
            elif data_type == 'compliance':
                writer.writerow(['ID', 'Created', 'Type', 'Entity', 'Requirement', 'Status', 'Due Date', 'Verified'])
                for item in queryset:
                    writer.writerow([
                        item.id,
                        item.created_at,
                        item.compliance_type,
                        item.user.username if item.user else item.entity_type,
                        item.requirement[:120],
                        item.status,
                        item.due_date,
                        item.verified,
                    ])
            elif data_type == 'risk':
                writer.writerow(['ID', 'Created', 'User', 'Risk Type', 'Risk Score', 'Status', 'Description'])
                for item in queryset:
                    writer.writerow([
                        item.id,
                        item.created_at,
                        item.user.username if item.user else 'Unknown',
                        item.risk_type,
                        item.risk_score,
                        item.status,
                        item.description[:120],
                    ])
            
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
        elif format_type in {'pdf', 'pack'} and data_type == 'logs':
            # Diligence-grade export for audit logs
            from datetime import datetime, time

            start_dt = timezone.make_aware(datetime.combine(date_from, time.min))
            end_dt = timezone.make_aware(datetime.combine(date_to, time.max))
            export_bytes = AuditService.export_audit_logs(start_dt, end_dt, format=format_type)

            if format_type == 'pdf':
                response = HttpResponse(export_bytes, content_type='application/pdf')
                filename = f'audit_logs_{date_from}_to_{date_to}.pdf'
            else:
                response = HttpResponse(export_bytes, content_type='application/zip')
                filename = f'audit_pack_{date_from}_to_{date_to}.zip'

            response['Content-Disposition'] = f'attachment; filename="{filename}"'
        else:
            return JsonResponse({'error': 'Unsupported format'}, status=400)
        
        return response
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# ========== API ENDPOINTS ==========

@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@require_GET
@role_required(ROLE_OWNER_FINANCE)
def get_audit_stats_api(request):
    """API endpoint for audit statistics"""
    period = request.GET.get('period', 'today')
    
    try:
        stats = AuditService.get_audit_stats(period)
        
        # Add module-specific stats
        stats.update({
            'suspicious_transactions': PaymentTransaction.objects.filter(
                is_suspicious=True
            ).count(),
            'large_expenses': Expense.objects.filter(
                amount__gte=50000
            ).count(),
            'ai_insights': FinancialInsight.objects.filter(
                severity__in=['HIGH', 'CRITICAL']
            ).count(),
            'autopilot_alerts': Alert.objects.filter(
                severity__in=['HIGH', 'CRITICAL']
            ).count(),
        })
        
        return JsonResponse({
            'success': True,
            'stats': stats,
            'period': period,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@require_GET
@role_required(ROLE_OWNER_FINANCE)
def search_audit_api(request):
    """Search API for audit logs"""
    try:
        query = request.GET.get('q', '')
        limit = int(request.GET.get('limit', 20))
        
        # Search across multiple models
        results = []
        
        # Search audit logs
        logs = AuditLog.objects.filter(
            Q(description__icontains=query) |
            Q(action__icontains=query) |
            Q(actor__username__icontains=query) |
            Q(target_user__username__icontains=query)
        ).order_by('-created_at')[:limit]
        
        for log in logs:
            results.append({
                'type': 'audit_log',
                'id': str(log.id),
                'title': f'Audit: {log.action}',
                'description': log.description[:100],
                'timestamp': log.created_at.isoformat(),
                'severity': log.severity,
                'url': f'/audit/logs/{log.id}/'
            })
        
        # Search security alerts
        alerts = SecurityAlert.objects.filter(
            Q(title__icontains=query) |
            Q(description__icontains=query) |
            Q(user__username__icontains=query)
        ).order_by('-detected_at')[:limit]
        
        for alert in alerts:
            results.append({
                'type': 'security_alert',
                'id': str(alert.id),
                'title': f'Alert: {alert.title}',
                'description': alert.description[:100],
                'timestamp': alert.detected_at.isoformat(),
                'severity': alert.severity,
                'url': f'/audit/alerts/{alert.id}/'
            })
        
        return JsonResponse({
            'success': True,
            'results': results,
            'count': len(results),
            'query': query
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# ========== INTEGRATED MONITORING ==========

@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def integrated_monitoring(request):
    """Integrated monitoring across all modules"""
    # Use a datetime here because the template formats time (H:i).
    today = timezone.now()
    
    # Get data from all modules
    context = {
        # Audit module
        'recent_logs': AuditLog.objects.all().order_by('-created_at')[:10],
        'open_alerts': SecurityAlert.objects.filter(status='OPEN').count(),
        
        # Payments module
        'suspicious_transactions': PaymentTransaction.objects.filter(
            is_suspicious=True
        ).order_by('-transaction_date')[:10],
        'failed_payments': PaymentIntent.objects.filter(
            status='FAILED'
        ).count(),
        
        # Finance module
        'large_expenses': Expense.objects.filter(
            amount__gte=50000
        ).select_related('user').order_by('-date')[:10],
        'unverified_incomes': Income.objects.filter(
            is_verified=False
        ).count(),
        
        # Autopilot module
        'critical_alerts': Alert.objects.filter(
            severity='CRITICAL'
        ).select_related('user').order_by('-alert_time')[:10],
        'failed_automations': 0,  # You'll need to track this
        
        # Analytics AI module
        'ai_insights': FinancialInsight.objects.filter(
            severity__in=['HIGH', 'CRITICAL']
        ).select_related('user').order_by('-created_at')[:10],
        
        # User risks
        'high_risk_users': UserRiskFlag.objects.filter(
            is_active=True,
            risk_score__gte=70
        ).select_related('user').order_by('-risk_score')[:10],
        
        # System status
        'system_controls': SystemControl.objects.first(),
        'today': today,
    }
    
    return render(request, 'audit/integrated_monitoring.html', context)

# ========== USER MANAGEMENT ==========

@login_required
@user_passes_test(lambda u: u.is_staff or u.is_superuser, login_url='finnovaapp:dashboard')
@permission_required('auth.view_user', raise_exception=True)
@role_required((ROLE_OWNER,))
def user_management(request):
    """User management dashboard with risk integration"""
    users = User.objects.all().annotate(
        risk_count=Count('risk_flags', filter=Q(risk_flags__is_active=True))
    ).order_by('-risk_count')
    
    context = {
        'users': users,
        'risk_levels': ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
    }
    return render(request, 'audit/user_management.html', context)

@login_required
@permission_required('auth.view_user', raise_exception=True)
@role_required((ROLE_OWNER,))
def user_detail(request, user_id):
    """Detailed user profile with audit trail"""
    user_obj = get_object_or_404(User, id=user_id)
    logs = AuditLog.objects.filter(Q(actor=user_obj) | Q(target_user=user_obj)).order_by('-created_at')[:50]
    risk_flags = UserRiskFlag.objects.filter(user=user_obj).order_by('-created_at')
    
    context = {
        'managed_user': user_obj,
        'logs': logs,
        'risk_flags': risk_flags,
    }
    return render(request, 'audit/user_detail.html', context)

@login_required
@permission_required('auth.change_user', raise_exception=True)
@require_POST
@role_required((ROLE_OWNER,))
def toggle_user_status(request, user_id):
    """Enable or disable a user account"""
    user_obj = get_object_or_404(User, id=user_id)
    user_obj.is_active = not user_obj.is_active
    user_obj.save()
    
    action = 'ENABLED' if user_obj.is_active else 'DISABLED'
    AuditLog.objects.create(
        actor=request.user,
        target_user=user_obj,
        action=f'USER_{action}',
        description=f'User {user_obj.username} has been {action.lower()}',
        severity='HIGH',
    )
    
    messages.success(request, f'User {user_obj.username} has been {action.lower()}.')
    return redirect('audit:user_detail', user_id=user_id)

# ========== REPORTS ==========

@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE)
def generate_reports(request):
    """Report generation and management hub"""
    return render(request, 'audit/reports.html', {
        'report_types': ['Security', 'Compliance', 'Activity', 'Risk']
    })


# =====================
# Incident Center (computed)
# =====================

@login_required
@role_required(ROLE_OWNER_FINANCE)
def incidents(request):
    """Incident Center.

    Groups AuditLog entries by correlation_id and shows a drill-down starting point.
    This is intentionally computed (no extra model) to keep the demo project simple.
    """

    org = getattr(request, 'active_organization', None)
    correlation = request.GET.get('correlation')
    severity = request.GET.get('severity')

    logs = AuditLog.objects.all()
    if org:
        logs = logs.filter(organization=org)

    cutoff = timezone.now() - timedelta(days=30)
    logs = logs.filter(created_at__gte=cutoff).exclude(correlation_id__isnull=True)

    if correlation:
        logs = logs.filter(correlation_id=correlation)
    if severity:
        logs = logs.filter(severity=severity)

    grouped = (
        logs.values('correlation_id')
        .annotate(
            first_seen=Min('created_at'),
            last_seen=Max('created_at'),
            count=Count('id'),
            max_sev=Max('severity'),
        )
        .order_by('-last_seen')
    )

    action_map = {}
    try:
        from eventhub.models import DomainEvent
        evts = DomainEvent.objects.filter(correlation_id__in=[g['correlation_id'] for g in grouped])
        if org:
            evts = evts.filter(organization=org)
        for evt in evts.order_by('-created_at')[:800]:
            action_map.setdefault(str(evt.correlation_id), {
                'event_type': evt.event_type,
                'module': evt.module,
                'action_url': evt.action_url,
                'severity': evt.severity,
            })
    except Exception:
        pass

    incidents_list = []
    for g in grouped:
        cid = str(g['correlation_id'])
        extra = action_map.get(cid, {})
        incidents_list.append({
            'correlation_id': cid,
            'first_seen': g['first_seen'],
            'last_seen': g['last_seen'],
            'count': g['count'],
            'max_severity': g['max_sev'],
            'event_type': extra.get('event_type'),
            'module': extra.get('module'),
            'action_url': extra.get('action_url'),
        })

    return render(request, 'audit/incidents.html', {
        'incidents': incidents_list,
        'selected_correlation': correlation,
        'selected_severity': severity,
        'severities': [c[0] for c in AuditLog.SEVERITY_CHOICES],
    })


# ── GST Dashboard view ────────────────────────────────────────────────────────
@login_required
@role_required(ROLE_OWNER_FINANCE)
def gst_dashboard(request):
    """GST summary — collected, paid, net payable, filing deadlines."""
    from decimal import Decimal
    from datetime import date
    import calendar as _cal
    
    user = request.user
    today = date.today()

    # Bug 2 fix: Check if GST is configured
    try:
        gst_registered = (user.profile.metadata or {}).get('gst_registered', 'no')
    except Exception:
        gst_registered = 'no'
    gst_not_configured = (gst_registered != 'yes')
    
    # Determine selected quarter
    quarter_param = request.GET.get('quarter')
    current_q = (today.month - 1) // 3 + 1
    current_y = today.year
    
    if quarter_param:
        try:
            qy, qq = map(int, quarter_param.split('Q'))
        except Exception:
            qy, qq = current_y, current_q
    else:
        qy, qq = current_y, current_q
    
    def quarter_dates(y, q):
        start_month = (q - 1) * 3 + 1
        end_month = start_month + 2
        start = date(y, start_month, 1)
        end = date(y, end_month, _cal.monthrange(y, end_month)[1])
        return start, end
    
    q_start, q_end = quarter_dates(qy, qq)
    
    # Build list of quarters for dropdown
    quarters = []
    for offset in range(8):
        total_q = current_y * 4 + current_q - 1 - offset
        qyr = total_q // 4; qqr = (total_q % 4) + 1
        month_names = ['Jan-Mar', 'Apr-Jun', 'Jul-Sep', 'Oct-Dec']
        quarters.append({
            'key': f'{qyr}Q{qqr}',
            'label': f"Q{qqr} {qyr} ({month_names[qqr-1]})",
        })
    
    selected_quarter = f'{qy}Q{qq}'
    current_quarter_label = f"Q{qq} {qy}"
    
    # GST filing deadline (20th of month following quarter end)
    end_m = qq * 3
    fd_m = end_m + 1 if end_m < 12 else 1
    fd_y = qy if end_m < 12 else qy + 1
    filing_deadline = date(fd_y, fd_m, 20)
    days_to_filing = (filing_deadline - today).days
    
    if days_to_filing < 0:
        filing_status = 'overdue'
    elif days_to_filing <= 10:
        filing_status = 'soon'
    else:
        filing_status = 'ok'
    
    # Calculate GST collected from Income
    gst_collected = Decimal('0')
    invoice_count = 0
    gst_transactions = []
    
    try:
        from finance.models import Income, Expense
        from django.db.models import Sum
        
        # Blueprint: filter by BUSINESS_CATEGORIES as spec requires
        BUSINESS_CATEGORIES = (
            'FREELANCE', 'CLIENT_PAYMENT', 'BUSINESS', 'CONSULTING',
            'CONTRACT', 'RETAINER', 'PROJECT',
        )
        incomes = Income.objects.filter(
            user=user,
            date__range=[q_start, q_end],
            category__in=BUSINESS_CATEGORIES,
        )
        
        invoice_count = incomes.count()
        for inc in incomes:
            gst_rate = getattr(inc, 'gst_rate', 18) or 18
            base = inc.amount / (1 + Decimal(str(gst_rate)) / 100)
            gst_amt = inc.amount - base
            gst_collected += gst_amt
            gst_transactions.append({
                'date': inc.date,
                'description': inc.description or inc.source or 'Income',
                'party': getattr(inc, 'source', ''),
                'type': 'income',
                'base_amount': base,
                'gst_rate': gst_rate,
                'gst_amount': gst_amt,
            })
        
        # GST paid on expenses (ITC)
        gst_paid = Decimal('0')
        expenses = Expense.objects.filter(
            user=user,
            date__range=[q_start, q_end],
        ).exclude(gst_rate=0).exclude(gst_rate__isnull=True)
        
        for exp in expenses:
            gst_rate = getattr(exp, 'gst_rate', 18) or 18
            gst_amt = exp.amount * Decimal(str(gst_rate)) / (100 + Decimal(str(gst_rate)))
            gst_paid += gst_amt
            gst_transactions.append({
                'date': exp.date,
                'description': exp.description or exp.merchant or 'Expense',
                'party': getattr(exp, 'merchant', ''),
                'type': 'expense',
                'base_amount': exp.amount - gst_amt,
                'gst_rate': gst_rate,
                'gst_amount': gst_amt,
            })
    except Exception as e:
        logger.exception("GST dashboard finance query failed")
        gst_collected = gst_paid = Decimal('0')
    
    net_payable = max(gst_collected - gst_paid, Decimal('0'))
    
    # Sort by date
    gst_transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Build quarterly summary
    quarter_summary = []
    for offset in range(4):
        total_q = current_y * 4 + current_q - 1 - offset
        qyr2 = total_q // 4; qqr2 = (total_q % 4) + 1
        qs, qe = quarter_dates(qyr2, qqr2)
        month_names = ['Jan-Mar', 'Apr-Jun', 'Jul-Sep', 'Oct-Dec']
        
        try:
            q_inc = Income.objects.filter(user=user, date__range=[qs, qe]).exclude(gst_rate=0).exclude(gst_rate__isnull=True)
            q_collected = sum(
                i.amount - i.amount / (1 + Decimal(str(getattr(i, 'gst_rate', 18) or 18)) / 100)
                for i in q_inc
            )
            q_exp = Expense.objects.filter(user=user, date__range=[qs, qe]).exclude(gst_rate=0).exclude(gst_rate__isnull=True)
            q_itc = sum(
                e.amount * Decimal(str(getattr(e, 'gst_rate', 18) or 18)) / (100 + Decimal(str(getattr(e, 'gst_rate', 18) or 18)))
                for e in q_exp
            )
        except Exception:
            q_collected = q_itc = Decimal('0')
        
        q_net = max(q_collected - q_itc, Decimal('0'))
        is_current = (qyr2 == current_y and qqr2 == current_q)
        
        # Check if filing exists
        try:
            from audit.models import ComplianceRecord
            filed = ComplianceRecord.objects.filter(
                user=user,
                compliance_type='GST_FILING',
                period_start=qs,
                status='COMPLIANT'
            ).exists()
            status = 'filed' if filed else ('due' if is_current else 'pending')
        except Exception:
            status = 'due' if is_current else 'pending'
        
        quarter_summary.append({
            'label': f"Q{qqr2} {qyr2} ({month_names[qqr2-1]})",
            'collected': q_collected,
            'itc': q_itc,
            'net': q_net,
            'status': status,
        })
    
    return render(request, 'audit/gst_dashboard.html', {
        'gst_collected': gst_collected,
        'gst_paid': gst_paid,
        'net_payable': net_payable,
        'invoice_count': invoice_count,
        'gst_transactions': gst_transactions[:30],
        'quarter_summary': quarter_summary,
        'quarters': quarters,
        'selected_quarter': selected_quarter,
        'current_quarter_label': current_quarter_label,
        'filing_deadline': filing_deadline,
        'days_to_filing': days_to_filing,
        'filing_status': filing_status,
        'gst_not_configured': gst_not_configured,
    })
