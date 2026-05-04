import logging
logger = logging.getLogger(__name__)
# finnovaapp/views.py - MAIN APPLICATION VIEWS
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views import View
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView
from django.urls import reverse, reverse_lazy
from django.conf import settings
from django.utils import timezone
import json
from datetime import timedelta
from django.db.models import Q, Sum
from django.views.decorators.http import require_GET, require_POST

# Org + role permissions (active organization is set by middleware)
from .permissions import (
    org_required,
    role_required,
    ROLE_OWNER,
    ROLE_FINANCE,
    ROLE_OPERATIONS,
    ROLE_VIEWER,
    ROLE_OWNER_FINANCE,
    ROLE_OWNER_FINANCE_OPS,
)

# Import your original forms and models
from .forms import (
    CustomUserCreationForm as UserRegistrationForm,  # Use your original form
    CustomAuthenticationForm as UserLoginForm,      # Use your original form
    UserUpdateForm,                                # Already exists
    ProfileUpdateForm,                             # Already exists
    OrganizationCreateForm
)
from .models import (
    CustomUser,
    UserProfile,
    LoginHistory,
    UserSession,
    Organization,
    OrganizationMembership,
)

# Import other module models (with fallbacks)
try:
    from finance.models import Account, Income, Expense, Budget, FinancialGoal
except ImportError:
    Account = Income = Expense = Budget = FinancialGoal = None

try:
    from payments_core.models import PaymentAccount, PaymentTransaction
except ImportError:
    PaymentAccount = PaymentTransaction = None

try:
    from finnova_autopilot.models import (
        AutopilotProfile,
        Alert,
        SmartBill,
        AutomationRule,
        FinancialHealthScore,
    )
except ImportError:
    AutopilotProfile = Alert = SmartBill = AutomationRule = FinancialHealthScore = None

try:
    from analytics_ai.models import FinancialInsight
except ImportError:
    FinancialInsight = None

try:
    from audit.models import AuditLog
except ImportError:
    AuditLog = None


SEVERITY_RANK = {
    'CRITICAL': 4,
    'HIGH': 3,
    'MEDIUM': 2,
    'LOW': 1,
    'INFO': 0,
}


def _personal_org_filter(queryset, organization):
    """Apply organization filtering when a model supports personal/org records."""
    if not hasattr(queryset.model, 'organization'):
        return queryset
    if organization is None:
        return queryset.filter(organization__isnull=True)
    return queryset.filter(organization=organization)


def ensure_user_foundations(user):
    """Provision the minimum records the shell expects for a personal workspace."""
    UserProfile.objects.get_or_create(user=user)

    if Account:
        primary_finance = Account.objects.filter(
            user=user,
            organization__isnull=True,
            is_primary=True,
        ).order_by('-updated_at').first()
        if primary_finance is None:
            Account.objects.create(
                user=user,
                organization=None,
                is_primary=True,
                name='Primary Financial Account',
                account_type='SAVINGS',
                opening_balance=Decimal('0.00'),
                current_balance=Decimal('0.00'),
                currency=getattr(user, 'preferred_currency', 'INR'),
                is_active=True,
            )

    if PaymentAccount:
        primary_payment = PaymentAccount.objects.filter(
            user=user,
            organization__isnull=True,
            is_primary=True,
        ).order_by('-updated_at').first()
        if primary_payment is None:
            PaymentAccount.objects.create(
                user=user,
                organization=None,
                is_primary=True,
                account_number=PaymentAccount.generate_account_number(),
                account_type='SAVINGS',
                balance=Decimal('0.00'),
                available_balance=Decimal('0.00'),
                currency=getattr(user, 'preferred_currency', 'INR'),
                is_active=True,
            )

    if AutopilotProfile:
        try:
            AutopilotProfile.resolve_for_user(user, organization=None)
        except Exception:
            logger.debug("Unable to provision autopilot profile", exc_info=True)


def _get_membership_for_request(request):
    organization = getattr(request, 'active_organization', None)
    membership = None
    role = None
    if organization is not None:
        membership = OrganizationMembership.objects.filter(
            organization=organization,
            user=request.user,
            is_active=True,
        ).select_related('organization').first()
        role = membership.role if membership else None
    return organization, membership, role


def _get_module_access(role, organization=None):
    agency_enabled = getattr(settings, 'FINNOVA_ENABLE_AGENCY_UI', False)
    personal_mode = organization is None or role is None
    if personal_mode:
        modules = {
            'finance': True,
            'payments': True,
            'analytics': True,
            'autopilot': True,
            'notifications': True,
            'audit': False,
            'ops': False,
            'agency': False,
            'client_portal': False,
        }
    else:
        operational_role = role in ('OWNER', 'FINANCE', 'OPERATIONS')
        modules = {
            'finance': operational_role,
            'payments': operational_role,
            'analytics': operational_role,
            'autopilot': operational_role,
            'notifications': True,
            'audit': role in ('OWNER', 'FINANCE'),
            'ops': role in ('OWNER', 'OPERATIONS'),
            'agency': agency_enabled and role in ('OWNER', 'FINANCE', 'OPERATIONS', 'VIEWER'),
            'client_portal': agency_enabled and role == 'VIEWER',
        }
    return modules, personal_mode, agency_enabled


def _top_severity_first(items, time_attr):
    return sorted(
        items,
        key=lambda item: (
            SEVERITY_RANK.get(getattr(item, 'severity', 'INFO'), 0),
            getattr(item, time_attr, timezone.now()),
        ),
        reverse=True,
    )


def build_dashboard_snapshot(user, organization=None):
    """Collect the command-center data used by the canonical shell dashboard."""
    today = timezone.now().date()
    month_start = today.replace(day=1)

    snapshot = {
        'today': today,
        'month_income': Decimal('0.00'),
        'month_expense': Decimal('0.00'),
        'net_savings': Decimal('0.00'),
        'savings_rate': Decimal('0.00'),
        'available_balance': Decimal('0.00'),
        'finance_account': None,
        'payment_account': None,
        'recent_transactions': [],
        'budgets': [],
        'budget_summary': {
            'active_count': 0,
            'healthy_count': 0,
            'near_limit_count': 0,
            'exceeded_count': 0,
            'top_budget': None,
        },
        'goals': [],
        'goal_summary': {
            'active_count': 0,
            'on_track_count': 0,
            'off_track_count': 0,
            'top_goal': None,
        },
        'insights': [],
        'alerts': [],
        'upcoming_bills': [],
        'health_score': None,
        'autopilot_profile': None,
        'active_rules_count': 0,
    }

    if Account:
        try:
            finance_account = _personal_org_filter(
                Account.objects.filter(user=user),
                organization,
            ).order_by('-is_primary', '-updated_at').first()
            snapshot['finance_account'] = finance_account
            if finance_account:
                snapshot['available_balance'] = finance_account.current_balance or Decimal('0.00')
        except Exception:
            logger.debug("Unable to load finance account for dashboard", exc_info=True)

    if Income:
        try:
            snapshot['month_income'] = _personal_org_filter(
                Income.objects.filter(user=user, date__gte=month_start, date__lte=today),
                organization,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        except Exception:
            logger.debug("Unable to load income for dashboard", exc_info=True)

    # Phase 5: Check if user has ANY income records (not just this month)
    if Income:
        try:
            snapshot['has_any_income'] = _personal_org_filter(
                Income.objects.filter(user=user),
                organization,
            ).exists()
        except Exception:
            snapshot['has_any_income'] = False
    else:
        snapshot['has_any_income'] = False

    if Expense:
        try:
            snapshot['month_expense'] = _personal_org_filter(
                Expense.objects.filter(user=user, date__gte=month_start, date__lte=today),
                organization,
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
        except Exception:
            logger.debug("Unable to load expenses for dashboard", exc_info=True)

    snapshot['net_savings'] = snapshot['month_income'] - snapshot['month_expense']
    if snapshot['month_income'] > 0:
        snapshot['savings_rate'] = (snapshot['net_savings'] / snapshot['month_income']) * Decimal('100')

    if PaymentAccount:
        try:
            payment_account = _personal_org_filter(
                PaymentAccount.objects.filter(user=user),
                organization,
            ).order_by('-is_primary', '-updated_at').first()
            snapshot['payment_account'] = payment_account
            if payment_account:
                snapshot['available_balance'] = payment_account.available_balance or payment_account.balance or snapshot['available_balance']
                if PaymentTransaction:
                    snapshot['recent_transactions'] = list(
                        PaymentTransaction.objects.filter(account=payment_account)
                        .order_by('-transaction_date')[:5]
                    )
        except Exception:
            logger.debug("Unable to load payments for dashboard", exc_info=True)

    if Budget:
        try:
            budgets = list(Budget.objects.filter(user=user, is_active=True).order_by('-created_at')[:3])
            snapshot['budgets'] = budgets
            snapshot['budget_summary'] = {
                'active_count': len(budgets),
                'healthy_count': sum(1 for budget in budgets if not budget.is_near_limit and not budget.is_exceeded),
                'near_limit_count': sum(1 for budget in budgets if budget.is_near_limit and not budget.is_exceeded),
                'exceeded_count': sum(1 for budget in budgets if budget.is_exceeded),
                'top_budget': max(budgets, key=lambda budget: budget.utilization_percentage, default=None),
            }
        except Exception:
            logger.debug("Unable to load budgets for dashboard", exc_info=True)

    if FinancialGoal:
        try:
            goals = list(
                FinancialGoal.objects.filter(user=user)
                .exclude(status__in=['ACHIEVED', 'CANCELLED'])
                .order_by('target_date')[:3]
            )
            snapshot['goals'] = goals
            snapshot['goal_summary'] = {
                'active_count': len(goals),
                'on_track_count': sum(1 for goal in goals if goal.is_on_track),
                'off_track_count': sum(1 for goal in goals if not goal.is_on_track),
                'top_goal': max(goals, key=lambda goal: goal.progress_percentage, default=None),
            }
        except Exception:
            logger.debug("Unable to load goals for dashboard", exc_info=True)

    if AutopilotProfile:
        try:
            snapshot['autopilot_profile'], _ = AutopilotProfile.resolve_for_user(user, organization=organization)
        except Exception:
            logger.debug("Unable to resolve autopilot profile for dashboard", exc_info=True)

    if AutomationRule:
        try:
            snapshot['active_rules_count'] = AutomationRule.objects.filter(user=user, is_active=True).count()
        except Exception:
            logger.debug("Unable to count automation rules for dashboard", exc_info=True)

    if SmartBill:
        try:
            snapshot['upcoming_bills'] = list(
                _personal_org_filter(
                    SmartBill.objects.filter(
                        user=user,
                        status='PENDING',
                        due_date__gte=today,
                    ),
                    organization,
                ).order_by('due_date')[:3]
            )
        except Exception:
            logger.debug("Unable to load smart bills for dashboard", exc_info=True)

    if FinancialHealthScore:
        try:
            snapshot['health_score'] = FinancialHealthScore.objects.filter(user=user).order_by('-calculated_at').first()
        except Exception:
            logger.debug("Unable to load financial health score for dashboard", exc_info=True)

    if FinancialInsight:
        try:
            insights = list(
                FinancialInsight.objects.filter(user=user, is_active=True).order_by('-created_at')[:6]
            )
            snapshot['insights'] = _top_severity_first(insights, 'created_at')[:3]
        except Exception:
            logger.debug("Unable to load financial insights for dashboard", exc_info=True)

    if Alert:
        try:
            alerts = list(
                _personal_org_filter(
                    Alert.objects.filter(user=user, is_read=False),
                    organization,
                ).order_by('-alert_time')[:6]
            )
            snapshot['alerts'] = _top_severity_first(alerts, 'alert_time')[:3]
        except Exception:
            logger.debug("Unable to load autopilot alerts for dashboard", exc_info=True)

    # Pending approvals count (approval-first autopilot)
    try:
        from finnova_autopilot.models import ApprovalRequest
        snapshot['pending_approvals_count'] = ApprovalRequest.objects.filter(
            user=user, status='PENDING'
        ).count()
    except Exception:
        snapshot['pending_approvals_count'] = 0

    snapshot['recommended_actions'] = build_recommended_actions(snapshot)
    return snapshot


def build_recommended_actions(snapshot):
    """Surface the highest-signal next steps from Finance, Analytics, and Autopilot."""
    actions = []
    budget_summary = snapshot.get('budget_summary', {})
    goal_summary = snapshot.get('goal_summary', {})
    insights = snapshot.get('insights', [])
    alerts = snapshot.get('alerts', [])
    autopilot_profile = snapshot.get('autopilot_profile')

    if Budget and budget_summary.get('active_count', 0) == 0:
        actions.append({
            'title': 'Create your first budget',
            'summary': 'Start the Finance pillar with a spending guardrail you can monitor from the dashboard.',
            'url': reverse('finance:add_budget'),
            'cta': 'Add budget',
            'tone': 'primary',
        })
    elif budget_summary.get('exceeded_count', 0) > 0:
        actions.append({
            'title': 'Rebalance budget pressure',
            'summary': f"{budget_summary['exceeded_count']} active budget needs attention before spending drifts further.",
            'url': reverse('finance:budget_list'),
            'cta': 'Review budgets',
            'tone': 'danger',
        })
    elif budget_summary.get('near_limit_count', 0) > 0:
        actions.append({
            'title': 'Adjust upcoming budget limits',
            'summary': f"{budget_summary['near_limit_count']} budget is nearing its threshold this period.",
            'url': reverse('finance:budget_list'),
            'cta': 'Open budgets',
            'tone': 'warning',
        })

    if FinancialGoal and goal_summary.get('active_count', 0) == 0:
        actions.append({
            'title': 'Set a financial goal',
            'summary': 'Goals make the dashboard more useful by tying daily tracking to a concrete target.',
            'url': reverse('finance:add_financial_goal'),
            'cta': 'Create goal',
            'tone': 'success',
        })
    elif goal_summary.get('off_track_count', 0) > 0:
        actions.append({
            'title': 'Bring goals back on track',
            'summary': f"{goal_summary['off_track_count']} goal needs a contribution or deadline review.",
            'url': reverse('finance:financial_goals'),
            'cta': 'Review goals',
            'tone': 'warning',
        })

    if alerts:
        actions.append({
            'title': 'Resolve priority alerts',
            'summary': alerts[0].message[:120],
            'url': reverse('autopilot:alerts'),
            'cta': 'Open alerts',
            'tone': 'danger' if SEVERITY_RANK.get(alerts[0].severity, 0) >= 3 else 'warning',
        })

    actionable_insight = next((insight for insight in insights if insight.action_required), insights[0] if insights else None)
    if actionable_insight:
        actions.append({
            'title': 'Review latest AI insight',
            'summary': actionable_insight.description[:120],
            'url': reverse('analytics-ai:financial_insights'),
            'cta': 'See insights',
            'tone': 'primary',
        })

    if autopilot_profile and not autopilot_profile.is_active:
        actions.append({
            'title': 'Activate Autopilot guidance',
            'summary': 'Turn on guided automation so the system can flag safer financial actions sooner.',
            'url': reverse('autopilot:autopilot_settings'),
            'cta': 'Open Autopilot',
            'tone': 'success',
        })

    if not actions:
        actions.append({
            'title': 'Keep your money picture current',
            'summary': 'Add today\'s income or expenses so Finance, Analytics, and Autopilot stay accurate.',
            'url': reverse('finance:transaction_center'),
            'cta': 'Open Finance',
            'tone': 'primary',
        })

    return actions[:4]

# ========== AUTHENTICATION VIEWS ==========

class LoginView(View):
    """User login using your original CustomAuthenticationForm"""
    def get(self, request):
        if request.user.is_authenticated:
            if hasattr(request.user, 'profile') and not request.user.profile.onboarding_completed:
                return redirect('finnovaapp:onboarding')
            return redirect('finnovaapp:dashboard')
        form = UserLoginForm()
        return render(request, 'finnovaapp/login.html', {'form': form})
    
    def post(self, request):
        form = UserLoginForm(request, data=request.POST)
        
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            remember_me = form.cleaned_data.get('remember_me', False)
            
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                
                # Set session expiry
                if not remember_me:
                    request.session.set_expiry(0)
                
                # Create login history
                from .services import create_login_history
                create_login_history(user, request, success=True)
                
                # Create user session
                from .services import create_user_session
                create_user_session(user, request, request.session.session_key)
                
                # Log login event
                if AuditLog:
                    AuditLog.objects.create(
                        actor=user,
                        action='USER_LOGIN',
                        description=f'User logged in: {username}',
                        severity='INFO',
                        metadata={
                            'ip_address': request.META.get('REMOTE_ADDR'),
                            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                            'remember_me': remember_me
                        }
                    )
                
                messages.success(request, f'Welcome back, {user.username}!')
                
                # Redirect based on user type
                if user.is_staff or user.is_superuser:
                    return redirect('audit:dashboard')
                if hasattr(user, 'profile') and not user.profile.onboarding_completed:
                    return redirect('finnovaapp:onboarding')
                return redirect('finnovaapp:dashboard')
            else:
                messages.error(request, 'Invalid username or password.')
        else:
            # Log failed login attempt
            from .services import create_login_history
            create_login_history(None, request, success=False, failure_reason="Invalid credentials")
        
        return render(request, 'finnovaapp/login.html', {'form': form})

class SignupView(View):
    """User registration using your original CustomUserCreationForm"""
    def get(self, request):
        if request.user.is_authenticated:
            if hasattr(request.user, 'profile') and not request.user.profile.onboarding_completed:
                return redirect('finnovaapp:onboarding')
            return redirect('finnovaapp:dashboard')
        form = UserRegistrationForm()
        return render(request, 'finnovaapp/signup.html', {'form': form})
    
    def post(self, request):
        form = UserRegistrationForm(request.POST)
        
        if form.is_valid():
            user = form.save()
            
            # Set additional fields from your form
            if hasattr(form, 'cleaned_data'):
                if 'phone' in form.cleaned_data:
                    user.phone = form.cleaned_data['phone']
                user.save()
            
            login(request, user)
            ensure_user_foundations(user)
            
            # Log signup event
            if AuditLog:
                AuditLog.objects.create(
                    actor=user,
                    action='USER_SIGNUP',
                    description=f'New user registered: {user.username}',
                    severity='INFO',
                    metadata={
                        'email': user.email,
                        'phone': user.phone,
                        'signup_ip': request.META.get('REMOTE_ADDR')
                    }
                )
            
            messages.success(request, 'Account created successfully! Welcome to Finnova.')
            
            needs_onboarding = not hasattr(user, 'profile') or not user.profile.onboarding_completed
            return redirect('finnovaapp:onboarding' if needs_onboarding else 'finnovaapp:dashboard')
        
        return render(request, 'finnovaapp/signup.html', {'form': form})

@login_required
def logout_view(request):
    """User logout"""
    # Log logout event
    if AuditLog:
        AuditLog.objects.create(
            actor=request.user,
            action='USER_LOGOUT',
            description=f'User logged out: {request.user.username}',
            severity='INFO',
            metadata={'logout_time': timezone.now().isoformat()}
        )
    
    # Deactivate session
    try:
        session = UserSession.objects.get(session_key=request.session.session_key, user=request.user)
        session.is_active = False
        session.save()
    except UserSession.DoesNotExist:
        pass
    
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('finnovaapp:login')

# ========== MAIN DASHBOARD VIEWS ==========

class DashboardView(LoginRequiredMixin, View):
    """Single canonical dashboard for the Finnova shell."""

    def get(self, request, *args, **kwargs):
        if request.user.is_staff or request.user.is_superuser:
            return redirect('audit:dashboard')

        ensure_user_foundations(request.user)

        if hasattr(request.user, 'profile') and not request.user.profile.onboarding_completed:
            return redirect('finnovaapp:onboarding')

        organization, membership, role = _get_membership_for_request(request)
        modules, personal_mode, agency_enabled = _get_module_access(role, organization=organization)

        if agency_enabled and role == 'VIEWER':
            return redirect('agency:client_invoice_list')

        snapshot = build_dashboard_snapshot(request.user, organization=organization)

        return render(request, 'finnovaapp/dashboard.html', {
            'snapshot': snapshot,
            'today': snapshot['today'],
            'organization': organization,
            'membership': membership,
            'org_role': role,
            'modules': modules,
            'shell_modules': modules,      # Template alias — dashboard uses shell_modules
            'show_agency_ui': agency_enabled,
            'is_personal_mode': personal_mode,
            'workspace_count': OrganizationMembership.objects.filter(user=request.user, is_active=True).count(),
        })



def redirect_to_dashboard(request):
    """Redirect legacy/duplicate dashboard routes to the single dashboard."""
    return redirect('finnovaapp:dashboard')


@login_required
def activity_feed(request):
    """Unified activity feed backed by DomainEvent."""
    organization = getattr(request, 'active_organization', None)
    if not organization:
        messages.info(request, 'Activity feed is available when an organization workspace is active.')
        return redirect('finnovaapp:dashboard')

    from eventhub.models import DomainEvent

    qs = DomainEvent.objects.filter(organization=organization).select_related('actor')
    event_type = request.GET.get('type')
    actor = request.GET.get('actor')

    if event_type:
        qs = qs.filter(event_type=event_type)
    if actor:
        qs = qs.filter(actor__username__icontains=actor)

    events = qs.order_by('-created_at')[:200]
    event_types = (
        DomainEvent.objects.filter(organization=organization)
        .values_list('event_type', flat=True)
        .distinct()
        .order_by('event_type')
    )

    return render(request, 'finnovaapp/activity_feed.html', {
        'organization': organization,
        'events': events,
        'event_types': list(event_types),
        'selected_type': event_type or '',
        'actor_q': actor or '',
    })


@login_required
@role_required((ROLE_OWNER, ROLE_OPERATIONS))
def ops_console(request):
    """Hidden operations view for org users handling approvals and follow-ups."""
    organization = getattr(request, 'active_organization', None)
    if not organization:
        return redirect('finnovaapp:org_select')

    from finnova_autopilot.models import ApprovalRequest, Alert
    from agency.models import Invoice
    from eventhub.models import DomainEvent
    from notifications.models import Notification

    today = timezone.now().date()
    pending_approvals = (
        ApprovalRequest.objects.filter(organization=organization, status='PENDING')
        .select_related('user', 'bill')
        .order_by('-created_at')[:12]
    )
    overdue_invoices = (
        Invoice.objects.filter(organization=organization)
        .exclude(status__in=[Invoice.STATUS_PAID, Invoice.STATUS_CANCELLED])
        .filter(due_date__lt=today)
        .select_related('client', 'project')
        .order_by('due_date')[:12]
    )
    alerts = Alert.objects.filter(organization=organization, is_acknowledged=False).order_by('-alert_time')[:12]
    recent_events = (
        DomainEvent.objects.filter(organization=organization)
        .select_related('actor')
        .order_by('-created_at')[:20]
    )
    # Unread notifications for sidebar
    notifications = Notification.objects.filter(
        user=request.user, is_read=False
    ).order_by('-created_at')[:10]

    member_count = OrganizationMembership.objects.filter(
        organization=organization, is_active=True
    ).count()

    return render(request, 'finnovaapp/ops_console.html', {
        'organization': organization,
        'pending_approvals': pending_approvals,
        'overdue_invoices': overdue_invoices,
        'alerts': alerts,
        'recent_events': recent_events,
        'notifications': notifications,
        'member_count': member_count,
        'today': today,
    })

# ========== USER PROFILE ==========

class ProfileView(LoginRequiredMixin, View):
    """User profile management using your original forms"""
    template_name = 'finnovaapp/profile.html'
    
    def get(self, request):
        user = request.user
        
        # Use your original forms
        user_form = UserUpdateForm(instance=user)
        
        # Get or create profile
        try:
            profile = user.profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=user)
        
        profile_form = ProfileUpdateForm(instance=profile)
        
        # Get user's financial profile from all modules
        context = self.get_user_profile_context(user, organization=getattr(request, 'active_organization', None))
        context.update({
            'user_form': user_form,
            'profile_form': profile_form,
        })
        
        return render(request, self.template_name, context)
    
    def post(self, request):
        user = request.user
        
        # Get or create profile
        try:
            profile = user.profile
        except UserProfile.DoesNotExist:
            profile = UserProfile.objects.create(user=user)
        
        # Use your original forms
        user_form = UserUpdateForm(request.POST, instance=user)
        profile_form = ProfileUpdateForm(request.POST, request.FILES, instance=profile)
        
        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            if 'financial_goals' in request.POST:
                profile.financial_goals = request.POST.getlist('financial_goals')
                profile.save(update_fields=['financial_goals', 'updated_at'])
            
            # Update user's phone if changed in profile
            if 'phone' in user_form.cleaned_data:
                user.phone = user_form.cleaned_data['phone']
                user.save()
            
            # Log profile update
            if AuditLog:
                AuditLog.objects.create(
                    actor=request.user,
                    action='PROFILE_UPDATED',
                    description='User updated their profile',
                    severity='INFO',
                    metadata={'updated_fields': list(request.POST.keys())}
                )
            
            messages.success(request, 'Profile updated successfully!')
            return redirect('finnovaapp:profile')
        
        context = self.get_user_profile_context(user, organization=getattr(request, 'active_organization', None))
        context.update({
            'user_form': user_form,
            'profile_form': profile_form,
        })
        
        return render(request, self.template_name, context)
    
    def get_user_profile_context(self, user, organization=None):
        """Get integrated user profile data"""
        context = {
            'user': user,
            'login_history': LoginHistory.objects.filter(user=user).order_by('-login_time')[:10],
            'active_sessions': UserSession.objects.filter(user=user, is_active=True).order_by('-last_activity'),
        }
        
        # Add data from other modules with error handling
        try:
            if Account:
                context['finance_account'] = _personal_org_filter(
                    Account.objects.filter(user=user),
                    organization,
                ).order_by('-is_primary', '-updated_at').first()
        except Exception:
            logger.debug("Error loading finance account for profile", exc_info=True)
        
        try:
            if PaymentAccount:
                context['payment_account'] = _personal_org_filter(
                    PaymentAccount.objects.filter(user=user),
                    organization,
                ).order_by('-is_primary', '-updated_at').first()
        except Exception:
            logger.debug("Error loading payment account for profile", exc_info=True)
        
        try:
            if AutopilotProfile:
                context['autopilot_profile'], _ = AutopilotProfile.resolve_for_user(user, organization=organization)
        except Exception:
            logger.debug("Error loading autopilot profile for profile view", exc_info=True)
        
        try:
            if AuditLog:
                context['recent_logs'] = AuditLog.objects.filter(
                    Q(actor=user) | Q(target_user=user)
                ).order_by('-created_at')[:10]
        except Exception:
            logger.debug("Error loading audit logs for profile", exc_info=True)
        
        return context

# ========== ONBOARDING ==========

BUSINESS_TYPES = [
    {"value": "freelancer",  "icon": "💻", "label": "Freelancer",       "desc": "Developer, designer, writer, consultant"},
    {"value": "agency",      "icon": "🏢", "label": "Agency / Studio",   "desc": "Small team, multiple clients, project work"},
    {"value": "consultant",  "icon": "📊", "label": "Consultant / CA",   "desc": "Advisory services, retainer or per-session"},
    {"value": "creator",     "icon": "🎬", "label": "Creator / Coach",   "desc": "Content, courses, coaching, digital products"},
    {"value": "retail",      "icon": "🛍️", "label": "Retail / Trade",    "desc": "Product sales, inventory, physical or online"},
    {"value": "clinic",      "icon": "🏥", "label": "Clinic / Practice", "desc": "Healthcare, therapy, wellness services"},
    {"value": "other",       "icon": "⚡", "label": "Other business",    "desc": "Something that does not fit above"},
]


@login_required
def onboarding(request):
    """Business-focused onboarding wizard."""
    valid_steps = {"1", "2", "3", "4", "5"}
    if not hasattr(request.user, "profile"):
        UserProfile.objects.get_or_create(user=request.user)
    if getattr(request.user.profile, "onboarding_completed", False):
        return redirect("finnovaapp:dashboard")
    step = request.GET.get("step", "1")
    if step not in valid_steps:
        step = "1"
    current_step = int(step)
    if request.method == "POST":
        return process_onboarding_step(request, step)
    context = {
        "step": step,
        "current_step": current_step,
        "total_steps": 5,
        "previous_step": current_step - 1 if current_step > 1 else None,
        "next_step": current_step + 1 if current_step < 5 else None,
        "remaining_steps": 5 - current_step,
        "business_types": BUSINESS_TYPES,
    }
    return render(request, f"finnovaapp/onboarding/step_{step}.html", context)


@login_required
def process_onboarding_step(request, step):
    """Save each onboarding step and advance."""
    user = request.user
    try:
        profile = user.profile
    except Exception:
        profile, _ = UserProfile.objects.get_or_create(user=user)
    try:
        if step == "1":
            meta = profile.metadata or {}
            meta.update({
                "business_type": request.POST.get("business_type", "freelancer"),
                "business_name": request.POST.get("business_name", "").strip(),
                "business_age": request.POST.get("business_age", "new"),
            })
            profile.metadata = meta
            bname = meta.get("business_name", "")
            if bname:
                profile.occupation = bname
            profile.save()
            messages.success(request, "Business type saved.")
        elif step == "2":
            gst_reg = request.POST.get("gst_registered", "no")
            gstin = request.POST.get("gstin", "").strip().upper()
            meta = profile.metadata or {}
            meta.update({"gst_registered": gst_reg, "gstin": gstin})
            profile.metadata = meta
            profile.save()
            if gstin and len(gstin) == 15:
                umeta = user.metadata or {}
                umeta["gstin"] = gstin
                user.metadata = umeta
                user.save(update_fields=["metadata"])
            messages.success(request, "Tax setup saved.")
        elif step == "3":
            savings_pct = int(request.POST.get("savings_target_pct", "20"))
            meta = profile.metadata or {}
            meta.update({
                "income_pattern": request.POST.get("income_pattern", "mixed"),
                "monthly_revenue": request.POST.get("monthly_revenue", "50-150k"),
                "savings_target_pct": savings_pct,
            })
            profile.metadata = meta
            profile.save()
            ensure_user_foundations(user)
            if FinancialGoal:
                    # Blueprint: FinancialGoal uses name/current_amount/status
                    FinancialGoal.objects.get_or_create(
                        user=user,
                        name="Emergency Fund",
                        defaults={
                            "target_amount": Decimal("100000"),
                            "current_amount": Decimal("0"),
                            "target_date": timezone.now().date() + timedelta(days=365),
                            "status": "IN_PROGRESS",
                            "priority": "HIGH",
                            "metadata": {"auto_contribute_pct": savings_pct, "is_auto_save": True},
                        },
                    )
            messages.success(request, "Income pattern saved.")
        elif step == "4":
            client_name = request.POST.get("client_name", "").strip()
            client_email = request.POST.get("client_email", "").strip()
            goal_type = request.POST.get("goal_type", "")
            goal_amount_raw = request.POST.get("goal_amount", "")
            if client_name:
                org = getattr(request, "active_organization", None)
                if org is None:
                    bname = (profile.metadata or {}).get("business_name") or user.username + "'s Business"
                    org, _ = Organization.objects.get_or_create(
                        name=bname, defaults={"is_active": True}
                    )
                    OrganizationMembership.objects.get_or_create(
                        user=user, organization=org,
                        defaults={"role": OrganizationMembership.ROLE_OWNER, "is_active": True},
                    )
                    request.session["active_org_id"] = str(org.id)
                try:
                    from agency.models import Client as AgencyClient
                    AgencyClient.objects.get_or_create(
                        organization=org, name=client_name,
                        defaults={"email": client_email or None, "is_active": True},
                    )
                    messages.success(request, f"Client added.")
                except Exception:
                    pass
            if goal_type and goal_amount_raw:
                try:
                    amt = Decimal(str(goal_amount_raw))
                    goal_labels = {
                        "emergency": "Emergency Fund", "equipment": "New Equipment",
                        "office": "Office Setup", "tax": "Advance Tax Reserve",
                        "growth": "Business Growth", "custom": "My Goal",
                    }
                    if FinancialGoal:
                        # Blueprint: correct FinancialGoal field names
                        FinancialGoal.objects.get_or_create(
                            user=user,
                            name=goal_labels.get(goal_type, "My Goal"),
                            defaults={
                                "target_amount": amt,
                                "current_amount": Decimal("0"),
                                "target_date": timezone.now().date() + timedelta(days=365),
                                "status": "IN_PROGRESS",
                                "priority": "MEDIUM",
                                "metadata": {"is_auto_save": True},
                            },
                        )
                except Exception:
                    pass
        elif step == "5":
            profile.onboarding_completed = True
            profile.save()
            ensure_user_foundations(user)
            if AuditLog:
                try:
                    AuditLog.objects.create(
                        actor=user, action="ONBOARDING_COMPLETED",
                        description="User completed business onboarding", severity="INFO",
                        metadata={"business_type": (profile.metadata or {}).get("business_type", "unknown")},
                    )
                except Exception:
                    pass
            messages.success(request, "Welcome to Finnova! Your financial brain is ready.")
            return redirect("finnovaapp:dashboard")

        next_step = int(step) + 1
        return redirect(f'{reverse_lazy("finnovaapp:onboarding")}?step={next_step}')
    except Exception as exc:
        logger.exception("Onboarding step %s failed", step)
        messages.error(request, f"Could not save step {step}: {exc}")
        return redirect(f'{reverse_lazy("finnovaapp:onboarding")}?step={step}')


@login_required
def kyc_upload(request):
    """Handle KYC document upload and verification submission"""
    from .forms import KYCDocumentForm
    
    if request.user.kyc_status == 'VERIFIED':
        messages.info(request, "Your KYC is already verified.")
        return redirect('finnovaapp:profile')
        
    if request.user.kyc_status == 'PENDING':
        messages.info(request, "Your KYC verification is already in progress.")
        return redirect('finnovaapp:profile')

    if request.method == 'POST':
        form = KYCDocumentForm(request.POST, request.FILES)
        if form.is_valid():
            # In a real app, we would save the documents to a model or secure storage
            # For this simulation, we'll update the user status
            user = request.user
            user.kyc_status = 'PENDING'
            user.save()
            
            # Log the KYC submission
            if AuditLog:
                AuditLog.objects.create(
                    actor=user,
                    action='KYC_SUBMITTED',
                    description=f'User submitted {form.cleaned_data.get("document_type")} for verification',
                    severity='INFO',
                    metadata={
                        'document_type': form.cleaned_data.get('document_type'),
                        'submission_time': timezone.now().isoformat()
                    }
                )
            
            messages.success(request, "Documents uploaded successfully! Your verification is now pending.")
            return redirect('finnovaapp:profile')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field.title()}: {error}")
    else:
        form = KYCDocumentForm()
        
    return render(request, 'finnovaapp/kyc_upload.html', {'form': form})

# ========== LANDING & PUBLIC PAGES ==========

class LandingView(View):
    """Public landing page"""
    def get(self, request):
        if request.user.is_authenticated:
            if request.user.is_staff or request.user.is_superuser:
                return redirect('audit:dashboard')
            if hasattr(request.user, 'profile') and not request.user.profile.onboarding_completed:
                return redirect('finnovaapp:onboarding')
            return redirect('finnovaapp:dashboard')
        
        # Get some public stats with error handling
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        stats = {
            'total_users': User.objects.count() if hasattr(User.objects, 'count') else 0,
        }
        
        try:
            if PaymentTransaction:
                stats['total_transactions'] = PaymentTransaction.objects.count()
        except:
            stats['total_transactions'] = 0
        
        try:
            if AutopilotProfile:
                money_saved = AutopilotProfile.objects.aggregate(
                    total=Sum('total_money_saved')
                )['total'] or 0.00
                stats['money_saved'] = money_saved
        except:
            stats['money_saved'] = 0.00
        
        return render(request, 'finnovaapp/landing.html', {
            'stats': stats,
            'features': self.get_features()
        })
    
    def get_features(self):
        """Get feature list for landing page"""
        return [
            {
                'title': 'Finance',
                'description': 'Track accounts, income, expenses, budgets, and goals in one operating layer.',
                'icon': 'wallet'
            },
            {
                'title': 'Analytics',
                'description': 'Turn raw money movement into explainable insights, patterns, and financial health signals.',
                'icon': 'chart-line'
            },
            {
                'title': 'Autopilot',
                'description': 'Review guided actions, alerts, and safer recommendations before money decisions escalate.',
                'icon': 'robot'
            },
            {
                'title': 'Notifications',
                'description': 'Stay on top of priority changes, reminders, and system follow-ups without dashboard clutter.',
                'icon': 'bell'
            },
            {
                'title': 'Shared Control',
                'description': 'Business workspaces, approvals, and audit-friendly flows stay available when teams need them.',
                'icon': 'security'
            },
            {
                'title': 'Clear Product Shell',
                'description': 'One navigation system and one dashboard keep the platform demo-ready and easier to explain.',
                'icon': 'layout'
            },
        ]

class AboutView(TemplateView):
    """About page"""
    template_name = 'finnovaapp/about.html'

class ContactView(View):
    """Contact page"""
    def get(self, request):
        return render(request, 'finnovaapp/contact.html')
    
    def post(self, request):
        # Handle contact form submission
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')
        
        # Here you would typically send an email
        # For now, just log it
        if AuditLog:
            AuditLog.objects.create(
                action='CONTACT_FORM_SUBMITTED',
                description=f'Contact form from {name} ({email})',
                severity='INFO',
                metadata={'message': message[:200]}
            )
        
        messages.success(request, 'Thank you for your message! We\'ll get back to you soon.')
        return redirect('finnovaapp:contact')

# ========== SETTINGS ==========

@login_required
def settings_view(request):
    """User settings"""
    user = request.user
    
    # Get or create profile
    try:
        profile = user.profile
    except UserProfile.DoesNotExist:
        profile = UserProfile.objects.create(user=user)
    
    # Handle POST request for updating settings
    if request.method == 'POST':
        return update_settings(request, profile)
    
    # Get settings from all modules
    context = {
        'account_settings': get_account_settings(user, organization=getattr(request, 'active_organization', None)),
        'notification_settings': get_notification_settings(profile),
        'privacy_settings': get_privacy_settings(profile),
        'integration_settings': get_integration_settings(profile),
        'user': user,
        'profile': profile,
    }
    
    return render(request, 'finnovaapp/settings.html', context)

def get_account_settings(user, organization=None):
    """Get account settings from all modules"""
    settings = {}

    # Pull gstin/gst_registered from user metadata for direct template access
    user_meta = getattr(user, 'metadata', None) or {}
    settings['gstin'] = user_meta.get('gstin', '')
    settings['gst_registered'] = user_meta.get('gst_registered', 'no')

    # User settings from your model
    settings['user'] = {
        'email': user.email,
        'phone': getattr(user, 'phone', '') or '',
        'kyc_status': getattr(user, 'kyc_status', '') or '',
        'preferred_currency': getattr(user, 'preferred_currency', 'INR') or 'INR',
        'language': getattr(user, 'language', 'en') or 'en',
        'timezone': getattr(user, 'timezone', 'Asia/Kolkata') or 'Asia/Kolkata',
    }
    
    # Profile settings
    try:
        profile = user.profile
        settings['profile'] = {
            'investment_experience': profile.investment_experience,
            'annual_income': profile.annual_income,
            'occupation': profile.occupation,
        }
    except UserProfile.DoesNotExist:
        settings['profile'] = {}
    
    # Module settings with error handling
    try:
        if Account:
            acct_qs = Account.objects.filter(user=user)
            if organization is not None:
                acct_qs = acct_qs.filter(organization=organization)
            finance_account = acct_qs.order_by('-is_primary', '-updated_at').first()
            if not finance_account:
                raise Account.DoesNotExist
            settings['finance'] = {
                'currency': getattr(finance_account, 'currency', 'INR'),
            }
    except Exception as e:
        settings['finance_error'] = str(e)
    
    try:
        if AutopilotProfile:
            autopilot_profile, _ = AutopilotProfile.resolve_for_user(user, organization=organization)
            settings['autopilot'] = {
                'is_active': autopilot_profile.is_active,
                'auto_savings_enabled': getattr(autopilot_profile, 'auto_savings_enabled', False),
                'monthly_budget': getattr(autopilot_profile, 'monthly_budget', 0),
            }
    except Exception as e:
        settings['autopilot_error'] = str(e)
    
    return settings

def get_notification_settings(profile):
    """Get notification settings from profile"""
    defaults = {
        'email_notifications': True,
        'sms_notifications': False,
        'push_notifications': True,
        'autopilot_enabled': True,
        'weekly_digest': False,
    }
    if hasattr(profile, 'notification_preferences') and isinstance(profile.notification_preferences, dict):
        return {**defaults, **profile.notification_preferences}
    return defaults

def get_privacy_settings(profile):
    """Get privacy settings"""
    return (profile.user.metadata or {}).get('privacy_settings', {
        'show_profile': True,
        'share_analytics': True,
        'personalization': True,
        'data_retention': '6 months',
    })

def get_integration_settings(profile):
    """Get integration settings"""
    return (profile.user.metadata or {}).get('integration_settings', {
        'bank_sync': False,
        'email_sync': False,
        'calendar_sync': False,
    })

def update_settings(request, profile):
    """Update user settings"""
    try:
        user = request.user
        metadata = user.metadata or {}

        if 'notification_settings' in request.POST:
            profile.notification_preferences = {
                'email_notifications': request.POST.get('email_notifications') == 'on',
                'sms_notifications': request.POST.get('sms_notifications') == 'on',
                'push_notifications': request.POST.get('push_notifications') == 'on',
                'autopilot_enabled': request.POST.get('autopilot_enabled') == 'on',
                'weekly_digest': request.POST.get('weekly_digest') == 'on',
            }

        if 'privacy_settings' in request.POST:
            metadata['privacy_settings'] = {
                'show_profile': request.POST.get('show_profile') == 'on',
                'share_analytics': request.POST.get('share_analytics') == 'on',
                'personalization': request.POST.get('personalization') == 'on',
                'data_retention': request.POST.get('data_retention', '6 months'),
            }

        if 'integration_settings' in request.POST:
            metadata['integration_settings'] = {
                'bank_sync': request.POST.get('bank_sync') == 'on',
                'email_sync': request.POST.get('email_sync') == 'on',
                'calendar_sync': request.POST.get('calendar_sync') == 'on',
            }

        if 'email' in request.POST:
            user.email = request.POST.get('email')
        if 'phone' in request.POST:
            user.phone = request.POST.get('phone')
        if 'preferred_currency' in request.POST:
            user.preferred_currency = request.POST.get('preferred_currency')
        if 'language' in request.POST:
            user.language = request.POST.get('language')
        if 'timezone' in request.POST:
            user.timezone = request.POST.get('timezone')

        user.metadata = metadata
        user.save()
        profile.save()
        
        # Log settings update
        if AuditLog:
            AuditLog.objects.create(
                actor=user,
                action='SETTINGS_UPDATED',
                description='User updated their settings',
                severity='INFO',
            )
        
        messages.success(request, 'Settings updated successfully!')
        
    except Exception as e:
        messages.error(request, f'Error updating settings: {str(e)}')
    
    return redirect('finnovaapp:settings')

# ========== ERROR HANDLERS ==========

def handler404(request, exception):
    """Custom 404 handler"""
    is_auth = getattr(request, 'user', None) and request.user.is_authenticated
    home_url = reverse_lazy('finnovaapp:dashboard') if is_auth else reverse_lazy('finnovaapp:landing')
    return render(request, 'finnovaapp/error.html', {
        'error_code': 404,
        'message': 'Page not found',
        'home_url': home_url,
        'home_label': 'Open dashboard' if is_auth else 'Back to Finnova',
    }, status=404)

def handler500(request):
    """Custom 500 handler — wraps render() so a broken template doesn't mask the 500."""
    import logging
    _log = logging.getLogger('finnovaapp')
    _log.error('Unhandled 500 error on %s', request.path, exc_info=True)
    is_auth = getattr(request, 'user', None) and request.user.is_authenticated
    home_url = reverse_lazy('finnovaapp:dashboard') if is_auth else reverse_lazy('finnovaapp:landing')
    try:
        return render(request, 'finnovaapp/error.html', {
            'error_code': 500,
            'message': 'Internal server error',
            'home_url': home_url,
            'home_label': 'Open dashboard' if is_auth else 'Back to Finnova',
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@finnova.com'),
        }, status=500)
    except Exception:
        from django.http import HttpResponse
        return HttpResponse(
            "<h1>500 Server Error</h1><p>Something went wrong. Please try again later.</p>",
            status=500, content_type='text/html'
        )

def handler403(request, exception):
    """Custom 403 handler"""
    is_auth = getattr(request, 'user', None) and request.user.is_authenticated
    home_url = reverse_lazy('finnovaapp:dashboard') if is_auth else reverse_lazy('finnovaapp:landing')
    return render(request, 'finnovaapp/error.html', {
        'error_code': 403,
        'message': 'Access denied',
        'home_url': home_url,
        'home_label': 'Open dashboard' if is_auth else 'Back to Finnova',
    }, status=403)

# ========== API ENDPOINTS ==========

@login_required
@require_GET
def get_user_stats(request):
    """Get user statistics for dashboard"""
    user = request.user
    today = timezone.now().date()
    organization = getattr(request, 'active_organization', None)
    
    try:
        stats = {
            'finance': {
                'month_income': 0.00,
                'month_expense': 0.00,
            },
            'payments': {
                'balance': 0.00,
                'recent_transactions': 0,
            },
            'autopilot': {
                'active_rules': 0,
                'upcoming_bills': 0,
            },
            'analytics': {
                'health_score': 0,
                'insights_count': 0,
            }
        }
        
        # Finance stats
        if Income and Expense:
            month_start = today.replace(day=1)
            stats['finance']['month_income'] = _personal_org_filter(
                Income.objects.filter(user=user, date__gte=month_start, date__lte=today),
                organization,
            ).aggregate(total=Sum('amount'))['total'] or 0.00

            stats['finance']['month_expense'] = _personal_org_filter(
                Expense.objects.filter(user=user, date__gte=month_start, date__lte=today),
                organization,
            ).aggregate(total=Sum('amount'))['total'] or 0.00
        
        # Payment stats
        if PaymentAccount and PaymentTransaction:
            try:
                pa_qs = _personal_org_filter(PaymentAccount.objects.filter(user=user), organization)
                payment_account = pa_qs.order_by('-is_primary', '-updated_at').first()
                if not payment_account:
                    raise PaymentAccount.DoesNotExist
                stats['payments']['balance'] = payment_account.balance
                stats['payments']['recent_transactions'] = PaymentTransaction.objects.filter(
                    account=payment_account
                ).count()
            except PaymentAccount.DoesNotExist:
                pass
        
        # Autopilot stats
        if AutomationRule and SmartBill:
            stats['autopilot']['active_rules'] = AutomationRule.objects.filter(
                user=user,
                is_active=True
            ).count()
            
            stats['autopilot']['upcoming_bills'] = SmartBill.objects.filter(
                user=user,
                status='PENDING',
                due_date__gte=today
            ).count()
        
        # Analytics stats
        if FinancialHealthScore and FinancialInsight:
            health_score = FinancialHealthScore.objects.filter(user=user).first()
            stats['analytics']['health_score'] = health_score.overall_score if health_score else 0
            
            stats['analytics']['insights_count'] = FinancialInsight.objects.filter(
                user=user,
                is_active=True
            ).count()
        
        # User profile stats
        if hasattr(user, 'profile'):
            profile = user.profile
            stats['user'] = {
                'investment_experience': profile.investment_experience,
                'kyc_status': user.kyc_status,
                'risk_level': user.risk_level,
            }
        
        return JsonResponse({
            'success': True,
            'stats': stats,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def change_password(request):
    """Handle password change submission"""
    from .forms import PasswordChangeForm
    form = PasswordChangeForm(user=request.user, data=request.POST)
    
    if form.is_valid():
        user = request.user
        user.set_password(form.cleaned_data['new_password'])
        user.save()
        
        # Log password change
        if AuditLog:
            AuditLog.objects.create(
                actor=user,
                action='PASSWORD_CHANGED',
                description='User changed their password',
                severity='WARNING',
                metadata={'ip_address': request.META.get('REMOTE_ADDR')}
            )
            
        messages.success(request, "Password updated successfully!")
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{error}")
                
    return redirect('finnovaapp:profile')

@login_required
@require_POST
def update_user_preferences(request):
    """Update user preferences"""
    try:
        data = json.loads(request.body) if request.body else {}
        
        user = request.user
        
        # Update user preferences from your model
        if 'preferred_currency' in data:
            user.preferred_currency = data['preferred_currency']
        if 'language' in data:
            user.language = data['language']
        if 'timezone' in data:
            user.timezone = data['timezone']
        
        # Update profile preferences
        if hasattr(user, 'profile'):
            profile = user.profile
            
            if 'investment_experience' in data:
                profile.investment_experience = data['investment_experience']
            
            if 'notification_preferences' in data:
                profile.notification_preferences = data['notification_preferences']
            
            profile.save()
        
        user.save()
        
        # Update module preferences with error handling
        if 'autopilot' in data and AutopilotProfile:
            try:
                profile, _ = AutopilotProfile.resolve_for_user(
                    user,
                    organization=getattr(request, 'active_organization', None),
                )
                profile.auto_savings_enabled = data['autopilot'].get('auto_savings_enabled', profile.auto_savings_enabled)
                profile.monthly_budget = data['autopilot'].get('monthly_budget', profile.monthly_budget)
                profile.save()
            except Exception as e:
                print(f"Error updating autopilot preferences: {e}")
        
        # Log preference update
        if AuditLog:
            AuditLog.objects.create(
                actor=user,
                action='PREFERENCES_UPDATED',
                description='User updated their preferences',
                severity='INFO',
                metadata={'updated_modules': list(data.keys())}
            )
        
        return JsonResponse({
            'success': True,
            'message': 'Preferences updated successfully'
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# =====================
# B2B / ORG SELECTION
# =====================


@login_required
def org_select(request):
    """Select the active organization for the session."""
    memberships = OrganizationMembership.objects.filter(user=request.user, is_active=True).select_related('organization')
    orgs = [m.organization for m in memberships]

    if request.method == 'POST':
        org_id = request.POST.get('organization_id')
        if org_id and any(str(o.id) == str(org_id) for o in orgs):
            request.session['active_org_id'] = str(org_id)
            messages.success(request, 'Workspace selected.')
            return redirect('finnovaapp:dashboard')
        messages.error(request, 'Invalid workspace selection.')

    context = {
        'organizations': orgs,
        'active_org_id': request.session.get('active_org_id'),
        'workspace_memberships': memberships,
    }
    return render(request, 'finnovaapp/org_select.html', context)


@login_required
def set_org(request, org_id):
    """Activate a workspace for the current session."""
    membership = (
        OrganizationMembership.objects
        .filter(user=request.user, organization_id=org_id, is_active=True)
        .select_related('organization')
        .first()
    )
    if not membership:
        messages.error(request, 'Invalid workspace selection.')
        return redirect('finnovaapp:org_select')

    request.session['active_org_id'] = str(membership.organization_id)
    messages.success(request, 'Workspace selected.')
    return redirect('finnovaapp:dashboard')


@login_required
def clear_org(request):
    """Return to personal mode for the current session."""
    request.session.pop('active_org_id', None)
    messages.success(request, 'Switched to personal mode.')
    return redirect('finnovaapp:dashboard')


@login_required
def org_create(request):
    """Create a new organization and make current user the OWNER."""
    if request.method == 'POST':
        form = OrganizationCreateForm(request.POST)
        if form.is_valid():
            org = form.save()
            OrganizationMembership.objects.create(
                organization=org,
                user=request.user,
                role=OrganizationMembership.ROLE_OWNER,
                is_active=True,
            )

            # Create default accounts (demo-friendly)
            from finance.models import Account as FinanceAccount
            from payments_core.models import PaymentAccount
            from decimal import Decimal

            FinanceAccount.objects.get_or_create(
                user=request.user,
                organization=org,
                is_primary=True,
                defaults={
                    'name': 'Primary Financial Account',
                    'account_type': 'SAVINGS',
                    'opening_balance': Decimal('0.00'),
                    'current_balance': Decimal('0.00'),
                    'is_active': True,
                },
            )

            primary_payment_account, _ = PaymentAccount.objects.get_or_create(
                user=request.user,
                is_primary=True,
                defaults={
                    'organization': org,
                    'account_number': PaymentAccount.generate_account_number(),
                    'account_type': 'SAVINGS',
                    'balance': Decimal('0.00'),
                    'available_balance': Decimal('0.00'),
                    'is_active': True,
                },
            )
            if primary_payment_account.organization_id is None:
                primary_payment_account.organization = org
                primary_payment_account.save(update_fields=['organization', 'updated_at'])

            request.session['active_org_id'] = str(org.id)
            messages.success(request, 'Workspace created successfully.')
            return redirect('finnovaapp:dashboard')
    else:
        form = OrganizationCreateForm()

    return render(request, 'finnovaapp/org_create.html', {'form': form})

# ========== LEGAL / STATIC PAGES ==========

def privacy_policy(request):
    return render(request, 'finnovaapp/legal_privacy.html')

def terms_of_service(request):
    return render(request, 'finnovaapp/legal_terms.html')

def faq(request):
    return render(request, 'finnovaapp/faq.html')
