from __future__ import annotations
import json

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from analytics_ai.models import FinancialInsight
from audit.models import AuditLog
from finance.models import Account as FinanceAccount
from finance.models import Budget, Expense, FinancialGoal, Income
from finance.services.posting import post_expense
from finnovaapp.permissions import ROLE_OWNER_FINANCE, ROLE_OWNER_FINANCE_OPS, role_required
from payments_core.models import PaymentAccount
from payments_core.services.payment_processor import PaymentProcessor

from .forms import SavingsGoalForm, SmartBillForm
from .models import (
    Alert,
    ApprovalRequest,
    AutomationRule,
    AutopilotProfile,
    FinancialHealthScore,
    SavingsGoal,
    SmartBill,
    TransactionPattern,
    _add_months,
    _add_years,
)
from .services.ai_advisor import AIAdvisor
from .services.approval_service import ApprovalExecutionService
from .services.automation_engine import AutomationEngine


RULE_CONDITION_OPTIONS = [
    ("AMOUNT_GREATER", "Amount is greater than"),
    ("CATEGORY_MATCH", "Category matches"),
    ("BALANCE", "Balance falls below"),
    ("TIME", "Due date or schedule"),
    ("PATTERN", "Pattern is detected"),
]

RULE_ACTION_OPTIONS = [
    ("ALERT", "Send alert"),
    ("SAVE", "Recommend savings move"),
    ("PAY_BILL", "Prepare bill payment"),
    ("REVIEW", "Send to review queue"),
    ("NOTIFY", "Notify team"),
]


def _current_day() -> date:
    return timezone.localdate()


from finnovaapp.utils import _active_org, _scoped_queryset as _filter_for_org


def _autopilot_qs(model, user, organization):
    return _filter_for_org(model.objects.filter(user=user), organization)


def _finance_qs(model, user, organization):
    return _filter_for_org(model.objects.filter(user=user), organization)


def _safe_decimal(value, default="0.00") -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(str(default))


def _safe_date(value, default=None):
    if not value:
        return default
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return default


def _redirect_target(request, fallback_name, **kwargs):
    target = request.POST.get("next") or request.GET.get("next")
    if target:
        return target
    return reverse(fallback_name, kwargs=kwargs or None)


def _resolve_autopilot_profile(request):
    return AutopilotProfile.resolve_for_user(request.user, organization=_active_org(request))


def _resolve_payment_account(user, organization=None, create_if_missing=False):
    accounts = PaymentAccount.objects.filter(user=user)
    if organization is not None:
        accounts = accounts.filter(Q(organization=organization) | Q(organization__isnull=True))

    account = (
        accounts.filter(is_primary=True, is_active=True).first()
        or accounts.filter(is_primary=True).first()
        or accounts.filter(is_active=True).first()
        or accounts.first()
    )
    if account:
        return account

    if not create_if_missing:
        raise PaymentAccount.DoesNotExist(f"No payment account for user {user.id}")

    return PaymentAccount.objects.create(
        user=user,
        organization=organization,
        account_number=PaymentAccount.generate_account_number(),
        account_type="SAVINGS",
        balance=Decimal("0.00"),
        available_balance=Decimal("0.00"),
        is_active=True,
        is_primary=True,
    )


def _finance_accounts(user, organization):
    accounts = FinanceAccount.objects.filter(user=user, is_active=True)
    return _filter_for_org(accounts, organization)


def _refresh_bill_statuses(user, organization):
    return _autopilot_qs(SmartBill, user, organization).filter(
        status="PENDING",
        due_date__lt=_current_day(),
    ).update(status="OVERDUE")


def _next_bill_due_date(bill):
    due_date = bill.due_date
    pattern = bill.recurrence_pattern
    if pattern == "DAILY":
        return due_date + timedelta(days=1)
    if pattern == "WEEKLY":
        return due_date + timedelta(weeks=1)
    if pattern == "MONTHLY":
        return _add_months(due_date, 1)
    if pattern == "QUARTERLY":
        return _add_months(due_date, 3)
    if pattern == "YEARLY":
        return _add_years(due_date, 1)
    if pattern == "CUSTOM":
        return due_date + timedelta(days=int((bill.recurrence_value or {}).get("days", 30)))
    return due_date + timedelta(days=30)


def _next_savings_date(goal, from_date=None):
    base_date = from_date or _current_day()
    day = min(max(int(goal.savings_day or 1), 1), 28)
    next_month = _add_months(base_date.replace(day=1), 1)
    return next_month.replace(day=day)


def _refresh_active_budgets(user, organization):
    budgets = list(Budget.objects.filter(user=user, is_active=True))
    for budget in budgets:
        try:
            budget.update_spending()
        except Exception:
            continue
    budgets.sort(
        key=lambda budget: (
            1 if budget.is_exceeded else 0,
            1 if budget.is_near_limit else 0,
            float(budget.utilization_percentage or 0),
        ),
        reverse=True,
    )
    return budgets


def _rule_success_rate(rule):
    if not rule.execution_count:
        return 0
    return round((rule.success_count / rule.execution_count) * 100)


def _describe_rule(rule):
    condition_value = rule.condition_value or {}
    action_value = rule.action_value or {}

    condition = rule.get_condition_type_display()
    if condition_value.get("threshold"):
        condition = f"{condition} Rs. {condition_value['threshold']}"
    elif condition_value.get("category"):
        condition = f"{condition} {condition_value['category']}"
    elif condition_value.get("pattern_name"):
        condition = f"{condition} {condition_value['pattern_name']}"

    action = rule.get_action_type_display()
    if action_value.get("amount"):
        action = f"{action} Rs. {action_value['amount']}"
    elif action_value.get("message"):
        action = f"{action}: {action_value['message']}"

    return condition, action


def _sanitize_action_url(url):
    if not url:
        return ""
    if "/autopilot/analytics" in url:
        return reverse("analytics-ai:ai_dashboard")
    if "/autopilot/investments" in url:
        return reverse("finance:investments")
    return url


def _sanitized_health_actions(user):
    actions = []
    for action in AIAdvisor.get_financial_health_recommendations(user):
        actions.append({**action, "action_url": _sanitize_action_url(action.get("action_url"))})
    return actions


def _goal_activity_entries(goal):
    entries = []
    for raw_entry in (goal.metadata or {}).get("activity", []):
        amount = _safe_decimal(raw_entry.get("amount", "0.00"))
        activity_date = _safe_date(raw_entry.get("date"), goal.created_at.date())
        entries.append(
            {
                "kind": raw_entry.get("kind", "ADD"),
                "amount": amount,
                "date": activity_date,
                "source": raw_entry.get("source", "MANUAL"),
                "note": raw_entry.get("note", ""),
            }
        )
    return entries


def _record_goal_activity(goal, *, kind, amount, entry_date, note="", source="MANUAL"):
    metadata = goal.metadata or {}
    entries = list(metadata.get("activity", []))
    entries.insert(
        0,
        {
            "kind": kind,
            "amount": str(amount),
            "date": entry_date.isoformat(),
            "source": source,
            "note": note,
        },
    )
    metadata["activity"] = entries[:50]
    goal.metadata = metadata


def _record_audit(actor, organization, description, *, action="SYSTEM", severity="INFO", metadata=None):
    AuditLog.objects.create(
        organization=organization,
        actor=actor,
        source="AUTOPILOT",
        action=action,
        severity=severity,
        description=description,
        metadata=metadata or {},
    )


def _maybe_create_alert(
    *,
    user,
    organization,
    title,
    message,
    category,
    severity,
    source="AUTOPILOT",
    action_required=False,
    action_url="",
    related_budget=None,
    related_bill=None,
):
    alerts = _autopilot_qs(Alert, user, organization).filter(title=title, alert_time__date=_current_day())
    if related_budget is not None:
        alerts = alerts.filter(related_budget=related_budget)
    if related_bill is not None:
        alerts = alerts.filter(related_bill=related_bill)
    if alerts.exists():
        return False

    Alert.objects.create(
        user=user,
        organization=organization,
        title=title,
        message=message,
        category=category,
        severity=severity,
        source=source,
        action_required=action_required,
        action_url=action_url,
        related_budget=related_budget,
        related_bill=related_bill,
    )
    return True


def _build_recommended_actions(
    *,
    approvals_count,
    overdue_bills,
    budget_warnings,
    unread_critical_alerts,
    monthly_surplus,
    savings_count,
    anomaly_count,
    analytics_signals,
):
    actions = []
    if approvals_count:
        actions.append(
            {
                "title": "Review pending approvals",
                "detail": "Autopilot is waiting for explicit confirmation before moving money.",
                "tone": "danger",
                "url": reverse("autopilot:approvals"),
            }
        )
    if overdue_bills:
        actions.append(
            {
                "title": "Resolve overdue bills",
                "detail": f"{overdue_bills} bill(s) are past due and should be reviewed first.",
                "tone": "danger",
                "url": f"{reverse('autopilot:smart_bills')}?status=overdue",
            }
        )
    if budget_warnings:
        actions.append(
            {
                "title": "Tighten active budgets",
                "detail": f"{len(budget_warnings)} Finance budget(s) are near or over limit.",
                "tone": "warning",
                "url": reverse("finance:budget_list"),
            }
        )
    if unread_critical_alerts:
        actions.append(
            {
                "title": "Acknowledge high-severity alerts",
                "detail": "Critical warnings should be reviewed before Autopilot expands coverage.",
                "tone": "warning",
                "url": f"{reverse('autopilot:alerts')}?severity=CRITICAL",
            }
        )
    if monthly_surplus > 0 and not savings_count:
        actions.append(
            {
                "title": "Start an auto-save goal",
                "detail": "This month's surplus can be routed into a controlled savings plan.",
                "tone": "success",
                "url": reverse("autopilot:savings"),
            }
        )
    if anomaly_count:
        actions.append(
            {
                "title": "Review anomaly patterns",
                "detail": "Unusual spending patterns were detected and should be confirmed manually.",
                "tone": "info",
                "url": reverse("autopilot:transaction_patterns"),
            }
        )
    if analytics_signals:
        actions.append(
            {
                "title": "Open Analytics for explanation",
                "detail": "Analytics has fresh signals that can explain recent money movement.",
                "tone": "info",
                "url": reverse("analytics-ai:ai_dashboard"),
            }
        )
    return actions[:6]


def _run_guidance_check(user, organization, profile):
    current_day = _current_day()
    counts = {"alerts": 0, "approvals": 0, "patterns": 0, "overdue": 0}
    counts["overdue"] = _refresh_bill_statuses(user, organization)

    try:
        AutomationEngine.update_financial_health(user)
    except Exception:
        pass

    try:
        counts["patterns"] = AutomationEngine.detect_patterns(user) or 0
    except Exception:
        counts["patterns"] = 0

    budgets = _refresh_active_budgets(user, organization)
    for budget in budgets:
        if budget.is_exceeded:
            created = _maybe_create_alert(
                user=user,
                organization=organization,
                title=f"Budget exceeded: {budget.name}",
                message=f"Finance shows spending above the current limit for {budget.name}.",
                category="BUDGET",
                severity="HIGH",
                action_required=True,
                action_url=reverse("finance:budget_detail", kwargs={"budget_id": budget.id}),
                related_budget=budget,
            )
            counts["alerts"] += 1 if created else 0
        elif budget.is_near_limit:
            created = _maybe_create_alert(
                user=user,
                organization=organization,
                title=f"Budget nearing limit: {budget.name}",
                message=f"{budget.name} has reached {budget.utilization_percentage:.0f}% of its limit.",
                category="BUDGET",
                severity="MEDIUM",
                action_required=True,
                action_url=reverse("finance:budget_detail", kwargs={"budget_id": budget.id}),
                related_budget=budget,
            )
            counts["alerts"] += 1 if created else 0

    payment_account = _resolve_payment_account(user, organization, create_if_missing=True)
    due_soon = _autopilot_qs(SmartBill, user, organization).filter(
        status="PENDING",
        auto_pay=True,
        payment_reference__isnull=True,
        due_date__lte=current_day + timedelta(days=profile.auto_pay_days_before),
    )
    for bill in due_soon:
        if payment_account.available_balance < bill.amount:
            created = _maybe_create_alert(
                user=user,
                organization=organization,
                title=f"Insufficient balance for {bill.biller_name}",
                message="Autopilot cannot prepare this bill because the available balance is too low.",
                category="PAYMENT",
                severity="HIGH",
                action_required=True,
                action_url=reverse("autopilot:smart_bills"),
                related_bill=bill,
            )
            counts["alerts"] += 1 if created else 0
            continue

        _, created = ApprovalRequest.objects.get_or_create(
            user=user,
            organization=organization,
            bill=bill,
            status="PENDING",
            defaults={
                "request_type": "BILL_PAYMENT",
                "title": f"Review bill: {bill.biller_name}",
                "description": f"Due on {bill.due_date.isoformat()}",
                "amount": bill.amount,
                "why": (
                    "Bill is due soon, auto-pay is enabled, and Autopilot requires explicit review "
                    "before money moves."
                ),
                "metadata": {"bill_id": str(bill.id), "due_date": bill.due_date.isoformat()},
            },
        )
        if created:
            counts["approvals"] += 1

    overdue_bills = _autopilot_qs(SmartBill, user, organization).filter(status="OVERDUE")
    for bill in overdue_bills[:5]:
        created = _maybe_create_alert(
            user=user,
            organization=organization,
            title=f"Overdue bill: {bill.biller_name}",
            message=f"{bill.biller_name} is overdue and should be reviewed immediately.",
            category="PAYMENT",
            severity="CRITICAL",
            action_required=True,
            action_url=reverse("autopilot:smart_bills"),
            related_bill=bill,
        )
        counts["alerts"] += 1 if created else 0

    profile.last_run = timezone.now()
    profile.save(update_fields=["last_run", "updated_at"])
    return counts


def _dashboard_payload(request):
    organization = _active_org(request)
    profile, _ = _resolve_autopilot_profile(request)
    current_day = _current_day()
    month_start = current_day.replace(day=1)

    _refresh_bill_statuses(request.user, organization)

    payment_account = _resolve_payment_account(request.user, organization, create_if_missing=True)
    monthly_income = _finance_qs(Income, request.user, organization).filter(date__gte=month_start).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    monthly_expense = _finance_qs(Expense, request.user, organization).filter(date__gte=month_start).aggregate(
        total=Sum("amount")
    )["total"] or Decimal("0.00")
    monthly_surplus = monthly_income - monthly_expense

    budgets = _refresh_active_budgets(request.user, organization)
    budget_warnings = [budget for budget in budgets if budget.is_near_limit or budget.is_exceeded][:4]

    bills = _autopilot_qs(SmartBill, request.user, organization).order_by("due_date", "biller_name")
    upcoming_bills = list(bills.filter(status="PENDING", due_date__gte=current_day)[:5])
    overdue_bills = bills.filter(status="OVERDUE")

    alerts = _autopilot_qs(Alert, request.user, organization).order_by("-alert_time")
    unread_alerts = alerts.filter(is_read=False)
    approvals = _autopilot_qs(ApprovalRequest, request.user, organization).filter(status="PENDING")
    rules = AutomationRule.objects.filter(user=request.user)
    savings_goals = SavingsGoal.objects.filter(user=request.user).exclude(status="CANCELLED")
    patterns = TransactionPattern.objects.filter(user=request.user, is_active=True)
    analytics_signals = list(FinancialInsight.objects.filter(user=request.user).order_by("-created_at")[:3])

    health_score = FinancialHealthScore.objects.filter(user=request.user).first()
    if health_score is None:
        health_score = AutomationEngine.update_financial_health(request.user)

    recommended_actions = _build_recommended_actions(
        approvals_count=approvals.count(),
        overdue_bills=overdue_bills.count(),
        budget_warnings=budget_warnings,
        unread_critical_alerts=unread_alerts.filter(severity__in=["HIGH", "CRITICAL"]).count(),
        monthly_surplus=monthly_surplus,
        savings_count=savings_goals.count(),
        anomaly_count=patterns.filter(is_anomaly=True).count(),
        analytics_signals=analytics_signals,
    )

    return {
        "organization": organization,
        "profile": profile,
        "current_day": current_day,
        "payment_account": payment_account,
        "monthly_income": monthly_income,
        "monthly_expense": monthly_expense,
        "monthly_surplus": monthly_surplus,
        "budget_warnings": budget_warnings,
        "budgets": budgets[:5],
        "upcoming_bills": upcoming_bills,
        "overdue_bills_count": overdue_bills.count(),
        "top_alerts": list(alerts[:5]),
        "unread_alerts_count": unread_alerts.count(),
        "pending_approvals": list(approvals.order_by("-created_at")[:5]),
        "pending_approvals_count": approvals.count(),
        "active_rules_count": rules.filter(is_active=True).count(),
        "rules_count": rules.count(),
        "savings_goals": list(savings_goals.order_by("target_date")[:4]),
        "analytics_signals": analytics_signals,
        "health_score": health_score,
        "recommended_actions": recommended_actions,
    }


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def autopilot_dashboard(request):
    try:
        return render(request, "finnova_autopilot/dashboard.html", _dashboard_payload(request))
    except Exception as exc:
        return render(
            request,
            "finnovaapp/error.html",
            {"error_code": 500, "message": str(exc)},
            status=500,
        )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def toggle_autopilot(request):
    profile, _ = _resolve_autopilot_profile(request)
    profile.is_active = not profile.is_active
    profile.save(update_fields=["is_active", "updated_at"])
    _record_audit(
        request.user,
        _active_org(request),
        f"Autopilot {'enabled' if profile.is_active else 'paused'} from dashboard.",
        action="SETTING",
    )
    messages.success(request, f"Autopilot {'enabled' if profile.is_active else 'paused'}.")
    return redirect(_redirect_target(request, "autopilot:autopilot_dashboard"))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def run_automation_now(request):
    profile, _ = _resolve_autopilot_profile(request)
    counts = _run_guidance_check(request.user, _active_org(request), profile)
    messages.success(
        request,
        (
            "Automation check complete. "
            f"{counts['alerts']} alert(s) refreshed, "
            f"{counts['approvals']} approval request(s) queued, "
            f"{counts['patterns']} pattern update(s) processed."
        ),
    )
    return redirect(_redirect_target(request, "autopilot:autopilot_dashboard"))


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def alerts(request):
    organization = _active_org(request)
    alerts_qs = _autopilot_qs(Alert, request.user, organization).order_by("-alert_time")
    stats_qs = alerts_qs

    status_filter = request.GET.get("status", "").strip()
    severity_filter = request.GET.get("severity", "").strip()
    category_filter = request.GET.get("category", "").strip()
    source_filter = request.GET.get("source", "").strip()
    search_query = request.GET.get("search", "").strip()

    if status_filter == "unread":
        alerts_qs = alerts_qs.filter(is_read=False)
    elif status_filter == "read":
        alerts_qs = alerts_qs.filter(is_read=True)
    if severity_filter:
        alerts_qs = alerts_qs.filter(severity=severity_filter)
    if category_filter:
        alerts_qs = alerts_qs.filter(category=category_filter)
    if source_filter:
        alerts_qs = alerts_qs.filter(source=source_filter)
    if search_query:
        alerts_qs = alerts_qs.filter(
            Q(title__icontains=search_query)
            | Q(message__icontains=search_query)
            | Q(source__icontains=search_query)
        )

    page_obj = Paginator(alerts_qs, 15).get_page(request.GET.get("page"))
    return render(
        request,
        "finnova_autopilot/alerts.html",
        {
            "page_obj": page_obj,
            "stats": {
                "total": stats_qs.count(),
                "unread": stats_qs.filter(is_read=False).count(),
                "critical": stats_qs.filter(severity="CRITICAL").count(),
                "high": stats_qs.filter(severity="HIGH").count(),
            },
            "status_filter": status_filter,
            "severity_filter": severity_filter,
            "category_filter": category_filter,
            "source_filter": source_filter,
            "search_query": search_query,
            "alert_categories": Alert.CATEGORIES,
            "alert_sources": Alert.SOURCES,
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def mark_all_alerts_read(request):
    updated = _autopilot_qs(Alert, request.user, _active_org(request)).filter(is_read=False).update(
        is_read=True,
        read_at=timezone.now(),
    )
    messages.success(request, f"{updated} alert(s) marked as read.")
    return redirect(_redirect_target(request, "autopilot:alerts"))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def acknowledge_alert(request, alert_id):
    alert = get_object_or_404(_autopilot_qs(Alert, request.user, _active_org(request)), id=alert_id)
    alert.is_read = True
    alert.is_acknowledged = True
    alert.read_at = timezone.now()
    alert.acknowledged_at = timezone.now()
    alert.save(update_fields=["is_read", "is_acknowledged", "read_at", "acknowledged_at"])
    messages.success(request, "Alert acknowledged.")
    return redirect(_redirect_target(request, "autopilot:alerts"))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def delete_alert(request, alert_id):
    alert = get_object_or_404(_autopilot_qs(Alert, request.user, _active_org(request)), id=alert_id)
    title = alert.title
    alert.delete()
    messages.success(request, f"Removed alert: {title}.")
    return redirect(_redirect_target(request, "autopilot:alerts"))


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def smart_bills(request):
    organization = _active_org(request)
    profile, _ = _resolve_autopilot_profile(request)
    _refresh_bill_statuses(request.user, organization)

    bills_qs = _autopilot_qs(SmartBill, request.user, organization).order_by("due_date", "biller_name")
    status_filter = request.GET.get("status", "").strip()
    category_filter = request.GET.get("category", "").strip()
    search_query = request.GET.get("search", "").strip()

    if status_filter:
        bills_qs = bills_qs.filter(status=status_filter.upper())
    if category_filter:
        bills_qs = bills_qs.filter(biller_category=category_filter)
    if search_query:
        bills_qs = bills_qs.filter(
            Q(biller_name__icontains=search_query)
            | Q(bill_number__icontains=search_query)
            | Q(consumer_number__icontains=search_query)
        )

    if request.method == "POST":
        form = SmartBillForm(request.user, request.POST)
        if form.is_valid():
            bill = form.save(commit=False)
            bill.user = request.user
            bill.organization = organization
            bill.save()
            messages.success(request, f"Added bill: {bill.biller_name}.")
            return redirect("autopilot:smart_bills")
    else:
        form = SmartBillForm(request.user)

    all_bills = _autopilot_qs(SmartBill, request.user, organization)
    current_day = _current_day()
    return render(
        request,
        "finnova_autopilot/smart_bills.html",
        {
            "form": form,
            "bills": bills_qs,
            "profile": profile,
            "status_filter": status_filter,
            "category_filter": category_filter,
            "search_query": search_query,
            "stats": {
                "total_due": all_bills.filter(status="PENDING").aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00"),
                "overdue_count": all_bills.filter(status="OVERDUE").count(),
                "due_soon_count": all_bills.filter(
                    status="PENDING",
                    due_date__lte=current_day + timedelta(days=7),
                    due_date__gte=current_day,
                ).count(),
                "active_autopays": all_bills.filter(auto_pay=True, status="PENDING").count(),
                "recurring_amount": all_bills.filter(is_recurring=True, status="PENDING").aggregate(total=Sum("amount"))[
                    "total"
                ]
                or Decimal("0.00"),
            },
            "history": all_bills.filter(status="PAID").order_by("-paid_date", "-updated_at")[:8],
            "bill_categories": SmartBill.CATEGORIES,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def edit_smart_bill(request, bill_id):
    bill = get_object_or_404(_autopilot_qs(SmartBill, request.user, _active_org(request)), id=bill_id)
    if request.method == "POST":
        form = SmartBillForm(request.user, request.POST, instance=bill)
        if form.is_valid():
            bill = form.save(commit=False)
            bill.user = request.user
            bill.organization = _active_org(request)
            bill.save()
            messages.success(request, f"Updated bill: {bill.biller_name}.")
            return redirect("autopilot:smart_bills")
    else:
        form = SmartBillForm(request.user, instance=bill)

    return render(request, "finnova_autopilot/smart_bill_edit.html", {"bill": bill, "form": form})


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def smart_bill_history(request, bill_id):
    bill = get_object_or_404(_autopilot_qs(SmartBill, request.user, _active_org(request)), id=bill_id)
    history_qs = _autopilot_qs(SmartBill, request.user, _active_org(request))
    if bill.consumer_number:
        history_qs = history_qs.filter(consumer_number=bill.consumer_number)
    elif bill.bill_number:
        history_qs = history_qs.filter(bill_number=bill.bill_number)
    else:
        history_qs = history_qs.filter(biller_name=bill.biller_name)

    return render(
        request,
        "finnova_autopilot/smart_bill_history.html",
        {"bill": bill, "history": history_qs.order_by("-due_date")[:50]},
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def toggle_autopay(request, bill_id):
    bill = get_object_or_404(_autopilot_qs(SmartBill, request.user, _active_org(request)), id=bill_id)
    bill.auto_pay = not bill.auto_pay
    bill.save(update_fields=["auto_pay", "updated_at"])
    messages.success(request, f"Auto-pay {'enabled' if bill.auto_pay else 'paused'} for {bill.biller_name}.")
    return redirect(_redirect_target(request, "autopilot:smart_bills"))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def pay_bill_now(request, bill_id):
    bill = get_object_or_404(_autopilot_qs(SmartBill, request.user, _active_org(request)), id=bill_id)
    if bill.status == "PAID":
        messages.info(request, f"{bill.biller_name} is already paid.")
        return redirect(_redirect_target(request, "autopilot:smart_bills"))

    try:
        payment_intent = PaymentProcessor.create_payment_intent(
            user=request.user,
            organization=_active_org(request),
            amount=bill.amount,
            payment_method="BANK_TRANSFER",
            description=f"Manual bill payment: {bill.biller_name}",
            metadata={"source": "AUTOPILOT_MANUAL_PAY", "bill_id": str(bill.id)},
        )
        result = PaymentProcessor.process_payment(payment_intent)
        if not result.get("success"):
            payment_intent.mark_failed(result.get("error") or "Payment failed")
            messages.error(request, result.get("error") or "Payment failed.")
            return redirect(_redirect_target(request, "autopilot:smart_bills"))

        payment_intent.mark_success(result.get("gateway_data") or {})
        bill.mark_as_paid(paid_date=_current_day(), paid_amount=bill.amount, payment_reference=payment_intent)
        try:
            post_expense(
                organization=_active_org(request),
                user=request.user,
                amount=bill.amount,
                merchant=bill.biller_name,
                category=bill.biller_category or "OTHER",
                memo=f"Bill payment: {bill.biller_name}",
                payment_reference=payment_intent.reference_id,
                related_payment=payment_intent,
            )
        except Exception:
            pass

        _record_audit(
            request.user,
            _active_org(request),
            f"Paid bill manually from Autopilot: {bill.biller_name}.",
            action="PAYMENT",
            metadata={"bill_id": str(bill.id), "reference_id": payment_intent.reference_id},
        )
        messages.success(request, f"Paid {bill.biller_name}. Reference: {payment_intent.reference_id}.")
    except Exception as exc:
        messages.error(request, f"Unable to pay bill: {exc}")

    return redirect(_redirect_target(request, "autopilot:smart_bills"))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def skip_bill(request, bill_id):
    bill = get_object_or_404(_autopilot_qs(SmartBill, request.user, _active_org(request)), id=bill_id)
    if not bill.is_recurring:
        messages.error(request, "Only recurring bills can be skipped.")
        return redirect(_redirect_target(request, "autopilot:smart_bills"))

    old_due_date = bill.due_date
    bill.due_date = _next_bill_due_date(bill)
    bill.status = "PENDING"
    bill.save(update_fields=["due_date", "status", "updated_at"])
    messages.info(
        request,
        f"Skipped {bill.biller_name}. Next due date is {bill.due_date.isoformat()} (was {old_due_date.isoformat()}).",
    )
    return redirect(_redirect_target(request, "autopilot:smart_bills"))


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def automation_rules(request):
    organization = _active_org(request)
    rules_qs = AutomationRule.objects.filter(user=request.user).select_related("linked_account").order_by(
        "-is_active",
        "priority",
        "-created_at",
    )
    status_filter = request.GET.get("status", "").strip()
    type_filter = request.GET.get("type", "").strip()
    search_query = request.GET.get("search", "").strip()

    if status_filter == "active":
        rules_qs = rules_qs.filter(is_active=True)
    elif status_filter == "inactive":
        rules_qs = rules_qs.filter(is_active=False)
    if type_filter:
        rules_qs = rules_qs.filter(rule_type=type_filter)
    if search_query:
        rules_qs = rules_qs.filter(Q(name__icontains=search_query) | Q(description__icontains=search_query))

    finance_accounts = _finance_accounts(request.user, organization)
    pattern_seed = None
    pattern_id = request.GET.get("pattern")
    if pattern_id:
        pattern_seed = TransactionPattern.objects.filter(user=request.user, id=pattern_id).first()

    form_values = {
        "name": request.POST.get("name") or (f"Pattern guard: {pattern_seed.pattern_name}" if pattern_seed else ""),
        "description": request.POST.get("description")
        or (
            f"Create a guided review whenever {pattern_seed.pattern_name} appears again."
            if pattern_seed
            else ""
        ),
        "rule_type": request.POST.get("rule_type") or ("SPENDING" if not pattern_seed else "SECURITY"),
        "condition_type": request.POST.get("condition_type") or ("PATTERN" if pattern_seed else "AMOUNT_GREATER"),
        "threshold_amount": request.POST.get("threshold_amount", ""),
        "condition_category": request.POST.get("condition_category", ""),
        "action_type": request.POST.get("action_type") or "REVIEW",
        "action_amount": request.POST.get("action_amount", ""),
        "linked_account": request.POST.get("linked_account", ""),
        "priority": request.POST.get("priority", "5"),
        "run_once": request.POST.get("run_once"),
        "is_active": request.POST.get("is_active", "on"),
    }
    form_errors = []

    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if not name:
            form_errors.append("Rule name is required.")

        priority = int(request.POST.get("priority") or "5")
        condition_type = request.POST.get("condition_type") or "AMOUNT_GREATER"
        action_type = request.POST.get("action_type") or "REVIEW"
        threshold = _safe_decimal(request.POST.get("threshold_amount") or "0.00")
        action_amount = _safe_decimal(request.POST.get("action_amount") or "0.00")

        linked_account = None
        linked_account_id = request.POST.get("linked_account")
        if linked_account_id:
            linked_account = finance_accounts.filter(id=linked_account_id).first()

        if not form_errors:
            condition_value = {}
            category_value = (request.POST.get("condition_category") or "").strip()
            if condition_type in {"AMOUNT_GREATER", "BALANCE"} and threshold > 0:
                condition_value["threshold"] = str(threshold)
            if category_value:
                condition_value["category"] = category_value
            if pattern_seed:
                condition_value["pattern_id"] = str(pattern_seed.id)
                condition_value["pattern_name"] = pattern_seed.pattern_name

            action_value = {}
            if action_type in {"SAVE", "PAY_BILL"} and action_amount > 0:
                action_value["amount"] = str(action_amount)
            if action_type in {"ALERT", "NOTIFY", "REVIEW"}:
                action_value["message"] = (request.POST.get("description") or name)[:160]

            rule = AutomationRule.objects.create(
                user=request.user,
                name=name,
                description=(request.POST.get("description") or "").strip(),
                rule_type=request.POST.get("rule_type") or "SPENDING",
                condition_type=condition_type,
                condition_value=condition_value,
                action_type=action_type,
                action_value=action_value,
                priority=max(1, min(priority, 10)),
                is_active=bool(request.POST.get("is_active")),
                run_once=bool(request.POST.get("run_once")),
                schedule_type="RECURRING" if condition_type == "TIME" else "IMMEDIATE",
                linked_account=linked_account,
            )
            _record_audit(
                request.user,
                organization,
                f"Created Autopilot rule: {rule.name}.",
                action="CREATE",
                metadata={"rule_id": str(rule.id)},
            )
            messages.success(request, f"Created rule: {rule.name}.")
            return redirect("autopilot:automation_rules")

    rules = list(rules_qs)
    for rule in rules:
        rule.condition_summary, rule.action_summary = _describe_rule(rule)
        rule.success_rate = _rule_success_rate(rule)

    return render(
        request,
        "finnova_autopilot/automation_rules.html",
        {
            "rules": rules,
            "status_filter": status_filter,
            "type_filter": type_filter,
            "search_query": search_query,
            "stats": {
                "total": AutomationRule.objects.filter(user=request.user).count(),
                "active": AutomationRule.objects.filter(user=request.user, is_active=True).count(),
                "review": AutomationRule.objects.filter(user=request.user, action_type="REVIEW").count(),
                "bill": AutomationRule.objects.filter(user=request.user, action_type="PAY_BILL").count(),
            },
            "rule_type_options": AutomationRule.RULE_TYPES,
            "condition_options": RULE_CONDITION_OPTIONS,
            "action_options": RULE_ACTION_OPTIONS,
            "finance_accounts": finance_accounts,
            "pattern_seed": pattern_seed,
            "form_values": form_values,
            "form_errors": form_errors,
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def toggle_rule(request, rule_id):
    rule = get_object_or_404(AutomationRule.objects.filter(user=request.user), id=rule_id)
    rule.is_active = not rule.is_active
    rule.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"Rule {'enabled' if rule.is_active else 'paused'}: {rule.name}.")
    return redirect(_redirect_target(request, "autopilot:automation_rules"))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def delete_rule(request, rule_id):
    rule = get_object_or_404(AutomationRule.objects.filter(user=request.user), id=rule_id)
    name = rule.name
    rule.delete()
    messages.success(request, f"Removed rule: {name}.")
    return redirect(_redirect_target(request, "autopilot:automation_rules"))


@login_required
@role_required(ROLE_OWNER_FINANCE)
def approvals(request):
    approvals_qs = _autopilot_qs(ApprovalRequest, request.user, _active_org(request)).filter(status="PENDING")
    page_obj = Paginator(approvals_qs.order_by("-created_at"), 20).get_page(request.GET.get("page"))
    return render(
        request,
        "finnova_autopilot/approvals.html",
        {
            "page_obj": page_obj,
            "pending_count": approvals_qs.count(),
            "profile": _resolve_autopilot_profile(request)[0],
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def approve_request(request, approval_id):
    org = _active_org(request)
    approval = get_object_or_404(_autopilot_qs(ApprovalRequest, request.user, org), id=approval_id)

    # Route by approval type
    if approval.request_type == 'INCOME_SPLIT':
        from finnova_autopilot.services.approval_service import IncomeSplitExecutor
        result = IncomeSplitExecutor.execute(approval, request.user)
        # After approving income split, redirect back to income split page or approvals
        if result.get('success'):
            messages.success(request, 'Income plan approved. Allocations applied.')
        else:
            messages.warning(request, result.get('message') or 'Could not apply income plan.')
        return redirect(_redirect_target(request, 'autopilot:approvals'))

    result = ApprovalExecutionService.approve(approval, request.user)
    if result.get('success'):
        messages.success(request, 'Approval executed successfully.')
    else:
        messages.warning(request, result.get('message') or 'Approval could not be executed.')
    return redirect(_redirect_target(request, 'autopilot:approvals'))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def reject_request(request, approval_id):
    approval = get_object_or_404(_autopilot_qs(ApprovalRequest, request.user, _active_org(request)), id=approval_id)
    result = ApprovalExecutionService.reject(approval, request.user)
    if result.get("success"):
        messages.success(request, "Approval rejected.")
    else:
        messages.warning(request, result.get("message") or "Approval is no longer pending.")
    return redirect(_redirect_target(request, "autopilot:approvals"))


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def autopilot_settings(request):
    organization = _active_org(request)
    profile, _ = _resolve_autopilot_profile(request)

    if request.method == "POST":
        profile.risk_tolerance = request.POST.get("risk_tolerance") or profile.risk_tolerance
        profile.monthly_budget = _safe_decimal(request.POST.get("monthly_budget"), profile.monthly_budget or "0.00")
        profile.budget_alerts_enabled = bool(request.POST.get("budget_alerts_enabled"))
        profile.budget_alert_threshold = _safe_decimal(
            request.POST.get("budget_alert_threshold"),
            profile.budget_alert_threshold or "80.00",
        )
        profile.auto_pay_bills = bool(request.POST.get("auto_pay_bills"))
        profile.auto_pay_days_before = max(0, min(int(request.POST.get("auto_pay_days_before") or 2), 30))
        profile.approval_required = bool(request.POST.get("approval_required"))
        profile.max_autopay_amount = _safe_decimal(
            request.POST.get("max_autopay_amount"),
            profile.max_autopay_amount or "25000.00",
        )
        profile.auto_savings_enabled = bool(request.POST.get("auto_savings_enabled"))
        profile.auto_savings_amount = _safe_decimal(
            request.POST.get("auto_savings_amount"),
            profile.auto_savings_amount or "0.00",
        )
        profile.auto_savings_frequency = request.POST.get("auto_savings_frequency") or profile.auto_savings_frequency
        profile.auto_savings_day = max(1, min(int(request.POST.get("auto_savings_day") or 1), 31))
        profile.ai_recommendations_enabled = bool(request.POST.get("ai_recommendations_enabled"))
        profile.learning_enabled = bool(request.POST.get("learning_enabled"))
        profile.notification_settings = {
            "bill_reminders": bool(request.POST.get("notify_bill_reminders")),
            "approval_updates": bool(request.POST.get("notify_approval_updates")),
            "budget_warnings": bool(request.POST.get("notify_budget_warnings")),
            "health_updates": bool(request.POST.get("notify_health_updates")),
            "pattern_warnings": bool(request.POST.get("notify_pattern_warnings")),
        }
        profile.save()
        _record_audit(
            request.user,
            organization,
            "Updated Autopilot settings.",
            action="SETTING",
            metadata={"profile_id": str(profile.id)},
        )
        messages.success(request, "Autopilot settings updated.")
        return redirect("autopilot:autopilot_settings")

    payment_account = _resolve_payment_account(request.user, organization, create_if_missing=True)
    active_rules = AutomationRule.objects.filter(user=request.user, is_active=True).count()
    return render(
        request,
        "finnova_autopilot/autopilot_settings.html",
        {
            "profile": profile,
            "payment_account": payment_account,
            "active_rules_count": active_rules,
            "risk_choices": AutopilotProfile.RISK_TOLERANCE_CHOICES,
            "frequency_choices": AutopilotProfile._meta.get_field("auto_savings_frequency").choices,
            "notification_settings": profile.notification_settings or {},
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def financial_health(request):
    """Financial health — delegates to analytics_ai service for consistent context."""
    from analytics_ai.services import FinancialAnalyticsService

    try:
        svc = FinancialAnalyticsService(request.user)
        score, grade, breakdown = svc.calculate_financial_health()
        suggestions   = svc.generate_health_improvement_suggestions()
        health_trends = svc.analyze_health_trends()
        benchmark     = svc.get_health_benchmark()
        risk_assessment = svc.assess_financial_risk()
        action_plan   = svc.generate_health_action_plan()

        # Normalise breakdown so template gets score/points/max/pct/name/status on each entry
        max_per_component = {
            'savings_rate': 250, 'emergency_fund': 200, 'debt_ratio': 200,
            'credit_utilization': 150, 'spending_consistency': 100, 'investment_ratio': 100,
        }
        normalized = {}
        for key, val in breakdown.items():
            if not isinstance(val, dict):
                val = {'points': int(val or 0), 'status': 'Fair'}
            pts = val.get('points', val.get('score', 0))
            mx  = max_per_component.get(key, 200)
            normalized[key] = {
                'score': pts, 'points': pts, 'max': mx,
                'pct': round(pts / mx * 100, 1) if mx else 0,
                'name': val.get('name', key.replace('_', ' ').title()),
                'status': val.get('status', 'Fair'),
                'label': val.get('label', ''),
            }

        return render(request, 'analytics_ai/financial_health.html', {
            'score': score,
            'grade': grade,
            'breakdown': normalized,
            'suggestions': suggestions,
            'health_trends': json.dumps(health_trends, default=str),
            'benchmark': benchmark,
            'risk_assessment': risk_assessment,
            'action_plan': action_plan,
            'milestones': [],
            'profile': svc.profile,
        })
    except Exception as e:
        logger.error(f"Autopilot financial_health error: {e}", exc_info=True)
        from analytics_ai.models import UserFinancialProfile
        profile = UserFinancialProfile.objects.filter(user=request.user).first()
        return render(request, 'analytics_ai/financial_health.html', {
            'error': True, 'score': None, 'grade': None, 'breakdown': {},
            'suggestions': [{'title': 'Add income & expense data',
                             'description': 'Record monthly income and expenses to calculate your score.',
                             'priority': 'HIGH'}],
            'health_trends': '{}', 'benchmark': {}, 'risk_assessment': {},
            'action_plan': [], 'milestones': [], 'profile': profile,
        })


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def refresh_financial_health(request):
    AutomationEngine.update_financial_health(request.user)
    messages.success(request, "Financial health recalculated from current Finance data.")
    return redirect(_redirect_target(request, "autopilot:financial_health"))


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def transaction_patterns(request):
    patterns_qs = TransactionPattern.objects.filter(user=request.user).order_by("-is_anomaly", "-confidence_score", "-last_observed")
    type_filter = request.GET.get("type", "").strip()
    confidence_filter = request.GET.get("confidence", "").strip()
    search_query = request.GET.get("search", "").strip()

    if type_filter:
        patterns_qs = patterns_qs.filter(pattern_type=type_filter)
    if confidence_filter == "high":
        patterns_qs = patterns_qs.filter(confidence_score__gte=80)
    elif confidence_filter == "medium":
        patterns_qs = patterns_qs.filter(confidence_score__gte=60, confidence_score__lt=80)
    elif confidence_filter == "low":
        patterns_qs = patterns_qs.filter(confidence_score__lt=60)
    if search_query:
        patterns_qs = patterns_qs.filter(
            Q(pattern_name__icontains=search_query)
            | Q(related_category__icontains=search_query)
            | Q(related_merchant__icontains=search_query)
        )

    page_obj = Paginator(patterns_qs, 16).get_page(request.GET.get("page"))
    return render(
        request,
        "finnova_autopilot/transaction_patterns.html",
        {
            "page_obj": page_obj,
            "stats": {
                "total": TransactionPattern.objects.filter(user=request.user, is_active=True).count(),
                "high_confidence": TransactionPattern.objects.filter(user=request.user, confidence_score__gte=80).count(),
                "anomalies": TransactionPattern.objects.filter(user=request.user, is_anomaly=True).count(),
                "spending": TransactionPattern.objects.filter(user=request.user, pattern_type="SPENDING").count(),
            },
            "pattern_types": TransactionPattern.PATTERN_TYPES,
            "type_filter": type_filter,
            "confidence_filter": confidence_filter,
            "search_query": search_query,
            "pattern_insights": AIAdvisor.analyze_transaction_patterns(request.user),
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def scan_transaction_patterns(request):
    patterns_found = AutomationEngine.detect_patterns(request.user) or 0
    messages.success(request, f"Pattern scan complete. {patterns_found} update(s) processed.")
    return redirect(_redirect_target(request, "autopilot:transaction_patterns"))


def _matching_transactions_for_pattern(pattern, user):
    current_day = _current_day()
    if pattern.pattern_type in {"SPENDING", "CATEGORY", "MERCHANT", "AMOUNT", "FREQUENCY"}:
        expenses = Expense.objects.filter(user=user, date__gte=current_day - timedelta(days=90)).order_by("-date")
        if pattern.related_category:
            expenses = expenses.filter(category=pattern.related_category)
        if pattern.related_merchant:
            expenses = expenses.filter(description__icontains=pattern.related_merchant)
        return list(expenses[:20])

    if pattern.pattern_type == "INCOME":
        incomes = Income.objects.filter(user=user, date__gte=current_day - timedelta(days=90)).order_by("-date")
        if pattern.related_merchant:
            incomes = incomes.filter(source__icontains=pattern.related_merchant)
        return list(incomes[:20])

    return []


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def pattern_detail(request, pattern_id):
    pattern = get_object_or_404(TransactionPattern.objects.filter(user=request.user), id=pattern_id)
    matching_transactions = _matching_transactions_for_pattern(pattern, request.user)
    recommendations = AIAdvisor.get_pattern_based_recommendations(pattern)
    return render(
        request,
        "finnova_autopilot/pattern_detail.html",
        {
            "pattern": pattern,
            "matching_transactions": matching_transactions,
            "recommendations": recommendations,
            "create_rule_url": f"{reverse('autopilot:automation_rules')}?pattern={pattern.id}",
            "finance_transactions_url": reverse("finance:transaction_center"),
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def confirm_pattern(request, pattern_id):
    pattern = get_object_or_404(TransactionPattern.objects.filter(user=request.user), id=pattern_id)
    pattern.update_confidence(new_observation=True)
    messages.success(request, f"Pattern confirmed: {pattern.pattern_name}.")
    return redirect(_redirect_target(request, "autopilot:pattern_detail", pattern_id=pattern.id))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def mark_pattern_anomaly(request, pattern_id):
    pattern = get_object_or_404(TransactionPattern.objects.filter(user=request.user), id=pattern_id)
    state = request.POST.get("state")
    pattern.is_anomaly = state == "true" if state is not None else not pattern.is_anomaly
    pattern.save(update_fields=["is_anomaly"])
    messages.success(
        request,
        f"Pattern {'flagged as anomaly' if pattern.is_anomaly else 'returned to normal review'}: {pattern.pattern_name}.",
    )
    return redirect(_redirect_target(request, "autopilot:pattern_detail", pattern_id=pattern.id))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def toggle_pattern(request, pattern_id):
    pattern = get_object_or_404(TransactionPattern.objects.filter(user=request.user), id=pattern_id)
    pattern.is_active = not pattern.is_active
    pattern.save(update_fields=["is_active"])
    messages.success(request, f"Pattern {'activated' if pattern.is_active else 'paused'}: {pattern.pattern_name}.")
    return redirect(_redirect_target(request, "autopilot:pattern_detail", pattern_id=pattern.id))


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def savings(request):
    goals_qs = SavingsGoal.objects.filter(user=request.user).order_by("priority", "target_date")
    status_filter = request.GET.get("status", "").strip()
    priority_filter = request.GET.get("priority", "").strip()
    search_query = request.GET.get("search", "").strip()

    if status_filter:
        goals_qs = goals_qs.filter(status=status_filter.upper())
    if priority_filter:
        goals_qs = goals_qs.filter(priority=priority_filter.upper())
    if search_query:
        goals_qs = goals_qs.filter(goal_name__icontains=search_query)

    if request.method == "POST":
        form = SavingsGoalForm(request.user, request.POST)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            if not goal.suggested_monthly_saving:
                goal.suggested_monthly_saving = AIAdvisor.calculate_monthly_saving(goal.target_amount, goal.target_date)[
                    "amount"
                ]
            if goal.is_auto_save and not goal.next_savings_date:
                goal.next_savings_date = _next_savings_date(goal)
            goal.save()
            messages.success(request, f"Created savings goal: {goal.goal_name}.")
            return redirect("autopilot:savings")
    else:
        form = SavingsGoalForm(request.user)

    all_goals = SavingsGoal.objects.filter(user=request.user)
    return render(
        request,
        "finnova_autopilot/savings.html",
        {
            "form": form,
            "goals": goals_qs,
            "status_filter": status_filter,
            "priority_filter": priority_filter,
            "search_query": search_query,
            "stats": {
                "active": all_goals.filter(status="ACTIVE").count(),
                "total_saved": all_goals.aggregate(total=Sum("current_saved"))["total"] or Decimal("0.00"),
                "total_target": all_goals.aggregate(total=Sum("target_amount"))["total"] or Decimal("0.00"),
                "on_track": sum(1 for goal in all_goals if goal.is_on_track),
            },
            "recommendations": AIAdvisor.get_savings_recommendations(request.user),
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def savings_detail(request, goal_id):
    goal = get_object_or_404(SavingsGoal.objects.filter(user=request.user), id=goal_id)
    activity_entries = _goal_activity_entries(goal)
    return render(
        request,
        "finnova_autopilot/savings_detail.html",
        {
            "goal": goal,
            "activity_entries": activity_entries,
            "next_savings_date": goal.next_savings_date or _next_savings_date(goal),
            "strategies": AIAdvisor.get_savings_acceleration_strategies(goal),
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def add_to_savings(request, goal_id):
    goal = get_object_or_404(SavingsGoal.objects.filter(user=request.user), id=goal_id)
    amount = _safe_decimal(request.POST.get("amount"))
    entry_date = _safe_date(request.POST.get("entry_date"), _current_day())
    source = request.POST.get("source") or "MANUAL"
    note = (request.POST.get("note") or "").strip()

    if amount <= 0:
        messages.error(request, "Contribution amount must be greater than zero.")
        return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))

    organization = _active_org(request)

    # ── Deduct from PaymentAccount balance ──────────────────────────────────
    try:
        payment_account = _resolve_payment_account(request.user, organization=organization, create_if_missing=False)
        if payment_account.available_balance < amount:
            messages.error(request, f"Insufficient balance. Available: ₹{payment_account.available_balance:,.2f}")
            return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))
        payment_account.balance = max(payment_account.balance - amount, Decimal("0.00"))
        payment_account.available_balance = max(payment_account.available_balance - amount, Decimal("0.00"))
        payment_account.save(update_fields=["balance", "available_balance"])
    except PaymentAccount.DoesNotExist:
        pass  # No payment account yet — allow manual tracking without deduction

    # ── Record as Finance Expense (uses post_expense which handles account creation) ──
    try:
        post_expense(
            organization=organization,
            user=request.user,
            amount=amount,
            merchant=f"Savings: {goal.goal_name}",
            category="SAVINGS",
            memo=note or f"Transfer to savings goal: {goal.goal_name}",
            payment_reference=f"savings:{goal.id}:{entry_date.isoformat()}:{source}",
        )
    except Exception:
        logger.debug("post_expense failed for savings contribution", exc_info=True)
        # Non-fatal — goal update still proceeds

    # ── Update goal ──────────────────────────────────────────────────────────
    goal.current_saved = _safe_decimal(goal.current_saved) + amount
    goal.last_savings_date = entry_date
    if goal.is_auto_save:
        goal.next_savings_date = _next_savings_date(goal, from_date=entry_date)
    current_month = entry_date.strftime("%Y-%m")
    month_total = amount
    for item in _goal_activity_entries(goal):
        if item["kind"] != "ADD":
            continue
        if item["date"].strftime("%Y-%m") == current_month:
            month_total += item["amount"]
    goal.actual_monthly_saving = month_total
    if goal.current_saved >= goal.target_amount:
        goal.status = "ACHIEVED"
    elif goal.status == "PAUSED":
        goal.status = "ACTIVE"
    _record_goal_activity(goal, kind="ADD", amount=amount, entry_date=entry_date, note=note, source=source)
    goal.save()
    messages.success(request, f"Added ₹{amount:.2f} to {goal.goal_name}. Amount deducted from your account.")
    return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def withdraw_from_savings(request, goal_id):
    goal = get_object_or_404(SavingsGoal.objects.filter(user=request.user), id=goal_id)
    amount = _safe_decimal(request.POST.get("amount"))
    entry_date = _safe_date(request.POST.get("entry_date"), _current_day())
    note = (request.POST.get("note") or "").strip()

    if amount <= 0:
        messages.error(request, "Withdrawal amount must be greater than zero.")
        return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))
    if amount > goal.current_saved:
        messages.error(request, "Withdrawal amount cannot exceed current saved balance.")
        return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))

    goal.current_saved = _safe_decimal(goal.current_saved) - amount
    if goal.status == "ACHIEVED" and goal.current_saved < goal.target_amount:
        goal.status = "ACTIVE"
    _record_goal_activity(goal, kind="WITHDRAW", amount=amount, entry_date=entry_date, note=note, source="MANUAL")
    goal.save()
    messages.success(request, f"Withdrew Rs. {amount:.2f} from {goal.goal_name}.")
    return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def pause_savings_goal(request, goal_id):
    goal = get_object_or_404(SavingsGoal.objects.filter(user=request.user), id=goal_id)
    goal.status = "PAUSED"
    goal.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Paused goal: {goal.goal_name}.")
    return redirect(_redirect_target(request, "autopilot:savings_detail", goal_id=goal.id))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def resume_savings_goal(request, goal_id):
    goal = get_object_or_404(SavingsGoal.objects.filter(user=request.user), id=goal_id)
    goal.status = "ACTIVE"
    goal.save(update_fields=["status", "updated_at"])
    messages.success(request, f"Resumed goal: {goal.goal_name}.")
    return redirect(_redirect_target(request, "autopilot:savings_detail", goal_id=goal.id))


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def apply_savings_strategy(request, goal_id):
    goal = get_object_or_404(SavingsGoal.objects.filter(user=request.user), id=goal_id)
    amount = _safe_decimal(request.POST.get("amount"))
    if amount <= 0:
        messages.error(request, "Suggested monthly contribution must be greater than zero.")
        return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))

    goal.suggested_monthly_saving = amount
    goal.save(update_fields=["suggested_monthly_saving", "updated_at"])
    messages.success(request, f"Updated suggested monthly contribution to Rs. {amount:.2f}.")
    return redirect(reverse("autopilot:savings_detail", kwargs={"goal_id": goal.id}))


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def ai_insights(request):
    health_score = FinancialHealthScore.objects.filter(user=request.user).first()
    if health_score is None:
        health_score = AutomationEngine.update_financial_health(request.user)

    recommendations = []
    for recommendation in AIAdvisor.get_personalized_recommendations(request.user):
        recommendations.append(
            {
                **recommendation,
                "action_url": _sanitize_action_url(recommendation.get("action_url")),
            }
        )

    analytics_signals = list(FinancialInsight.objects.filter(user=request.user).order_by("-created_at")[:5])
    spending_patterns = AIAdvisor.analyze_spending_patterns(request.user)
    raw_risk = AIAdvisor.assess_financial_risk(request.user)

    # Normalise risk dict to match ai_insights.html template expectations
    risk_score = raw_risk.get("overall_score", raw_risk.get("risk_score", 0))
    risk_factors = raw_risk.get("risks", raw_risk.get("risk_factors", []))
    if risk_score < 30:
        risk_level = "Low"
    elif risk_score < 60:
        risk_level = "Moderate"
    else:
        risk_level = "High"
    risk = {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "risk_factors": risk_factors,
        "overall_score": risk_score,
        "risks": risk_factors,
    }

    unread_alerts = _autopilot_qs(Alert, request.user, _active_org(request)).filter(is_read=False).order_by("-alert_time")[:5]
    pending_approvals = _autopilot_qs(ApprovalRequest, request.user, _active_org(request)).filter(status="PENDING").count()

    return render(
        request,
        "finnova_autopilot/ai_insights.html",
        {
            "health_score": health_score,
            "analytics_signals": analytics_signals,
            "recommendations": recommendations,
            "savings_opportunities": AIAdvisor.identify_savings_opportunities(request.user),
            "spending_patterns": spending_patterns,
            "risk": risk,
            "unread_alerts": list(unread_alerts),
            "pending_approvals_count": pending_approvals,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def legacy_analytics_redirect(request):
    messages.info(request, "Autopilot analytics now live in the Analytics module.")
    return redirect("analytics-ai:ai_dashboard")


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def legacy_investments_redirect(request, plan_id=None):
    messages.info(request, "Investment planning now lives in Finance.")
    return redirect("finance:investments")


# ── Income Split Plan view ────────────────────────────────────────────────────
@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def income_split_plan(request, approval_id):
    """Show the income money plan for user to review and approve."""
    from decimal import Decimal
    org = _active_org(request)
    
    approval = get_object_or_404(
        ApprovalRequest,
        id=approval_id,
        user=request.user,
        request_type='INCOME_SPLIT',
    )
    
    metadata = approval.metadata or {}
    gross = Decimal(str(metadata.get('gross_amount', '0')))
    gst_amount = Decimal(str(metadata.get('gst_amount', '0')))
    tax_amount = Decimal(str(metadata.get('tax_amount', '0')))
    bills_reserved = Decimal(str(metadata.get('bills_reserved', '0')))
    spendable = Decimal(str(metadata.get('spendable', '0')))
    
    savings_allocations = metadata.get('savings_allocations', [])
    upcoming_bills = metadata.get('upcoming_bills', [])
    
    gst_pct = (gst_amount / gross * 100) if gross > 0 else Decimal('0')
    net = gross - gst_amount
    tax_pct = (tax_amount / net * 100) if net > 0 else Decimal('0')
    spendable_pct = (spendable / gross * 100) if gross > 0 else Decimal('0')
    
    from datetime import date
    today = date.today()
    # GST filing: last day of next month after quarter end
    qm = ((today.month - 1) // 3 + 1) * 3 + 1
    qy = today.year if qm <= 12 else today.year + 1
    qm = qm if qm <= 12 else qm - 12
    import calendar
    filing_date = date(qy, qm, calendar.monthrange(qy, qm)[1])
    
    plan = {
        'approval_id': approval.id,
        'gross_amount': gross,
        'gst_amount': gst_amount,
        'gst_pct': gst_pct,
        'tax_amount': tax_amount,
        'tax_pct': tax_pct,
        'savings_allocations': savings_allocations,
        'bills_reserved': bills_reserved,
        'bills_count': len(upcoming_bills),
        'upcoming_bills': upcoming_bills,
        'spendable': spendable,
        'spendable_pct': spendable_pct,
        'source_label': metadata.get('source_label', ''),
        'received_at': approval.created_at,
        'gst_filing_date': filing_date,
    }
    
    return render(request, 'finnova_autopilot/income_split.html', {
        'plan': plan,
        'approval': approval,
        'organization': org,
    })


def _build_income_split_plan(income, user, org):
    """Calculate the money split plan for a new income record.
    
    Uses actual SavingsGoal field names: goal_name, current_saved, is_auto_save.
    Income model has no gst_rate field — we infer GST from user metadata and category.
    """
    from decimal import Decimal
    from datetime import date, timedelta
    from .models import SavingsGoal, SmartBill
    from finnovaapp.models import UserProfile

    gross = Decimal(str(income.amount))
    gst_amount = Decimal('0')
    tax_amount = Decimal('0')
    savings_allocs = []

    # ── GST reserve ──────────────────────────────────────────────────────────
    # Infer from user profile metadata or income category
    try:
        profile = user.profile
        gst_registered = (profile.metadata or {}).get('gst_registered', 'no')
    except Exception:
        gst_registered = 'no'

    business_categories = ('FREELANCE', 'CLIENT_PAYMENT', 'BUSINESS', 'CONSULTING',
                            'CONTRACT', 'RETAINER', 'PROJECT')
    if gst_registered == 'yes' and income.category in business_categories:
        # GST is 18% already included in gross (reverse-calculate)
        gst_amount = (gross * Decimal('18') / Decimal('118')).quantize(Decimal('0.01'))

    net = gross - gst_amount

    # ── Advance tax provision (rough estimate: 8% of net for quarterly provision) ──
    if net > Decimal('25000'):
        tax_amount = (net * Decimal('0.08')).quantize(Decimal('0.01'))

    after_obligations = net - tax_amount
    remaining = after_obligations

    # ── Savings goal contributions ────────────────────────────────────────────
    # SavingsGoal uses: goal_name, target_amount, current_saved, is_auto_save, status
    goals = SavingsGoal.objects.filter(
        user=user,
        is_auto_save=True,
        status__in=['PLANNING', 'ACTIVE'],
    ).order_by('priority', 'goal_name')[:3]

    for goal in goals:
        if remaining <= 0:
            break
        # Default auto-save: 20% of after-obligation amount, capped at remaining gap
        savings_target_pct = Decimal(str(
            (goal.metadata or {}).get('auto_contribute_pct', 20)
            if hasattr(goal, 'metadata') and goal.metadata else 20
        ))
        gap = goal.target_amount - goal.current_saved
        if gap <= 0:
            continue
        contrib = min(
            remaining * savings_target_pct / 100,
            gap,
            remaining,
        ).quantize(Decimal('0.01'))
        if contrib > 0:
            progress_pct = float(
                goal.current_saved / goal.target_amount * 100
            ) if goal.target_amount > 0 else 0
            savings_allocs.append({
                'goal_id': str(goal.id),  # Bug 4 fix: store id for reliable lookup
                'name': goal.goal_name,
                'pct': float(savings_target_pct),
                'amount': str(contrib),
                'target': str(goal.target_amount),
                'progress_pct': round(progress_pct, 1),
            })
            remaining -= contrib

    # ── Bills due in next 30 days ─────────────────────────────────────────────
    today = date.today()
    bill_qs = SmartBill.objects.filter(
        user=user, status='PENDING',
        due_date__range=(today, today + timedelta(days=30)),
    ).order_by('due_date')[:5]
    bills_reserved = sum(b.amount for b in bill_qs)
    bills_list = [{'biller_name': b.biller_name, 'amount': float(b.amount)} for b in bill_qs]

    # ── Spendable ─────────────────────────────────────────────────────────────
    spendable = max(remaining - bills_reserved, Decimal('0')).quantize(Decimal('0.01'))

    return {
        'gross_amount': str(gross),
        'gst_amount': str(gst_amount),
        'gst_pct': '18' if gst_amount > 0 else '0',
        'tax_amount': str(tax_amount),
        'tax_pct': '8',
        'savings_allocations': savings_allocs,
        'bills_reserved': str(bills_reserved),
        'bills_count': len(bills_list),
        'upcoming_bills': bills_list,
        'spendable': str(spendable),
        'spendable_pct': str(
            round(float(spendable / gross * 100), 1) if gross > 0 else 0
        ),
        'source_label': getattr(income, 'source', '') or income.description or '',
    }
