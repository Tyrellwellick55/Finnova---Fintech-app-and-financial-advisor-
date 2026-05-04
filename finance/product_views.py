import csv
import io
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from finnovaapp.permissions import ROLE_OWNER_FINANCE, ROLE_OWNER_FINANCE_OPS, role_required

from .forms import (
    BudgetForm,
    DebtForm,
    DebtPaymentForm,
    ExpenseForm,
    FinancialGoalForm,
    GoalContributionForm,
    ImportCSVForm,
    IncomeForm,
    InvestmentForm,
    ReportFilterForm,
    TaxRecordForm,
)
from .models import (
    Account,
    Budget,
    BudgetCategory,
    Debt,
    Expense,
    FinancialGoal,
    FinancialReport,
    Income,
    Investment,
    TaxRecord,
)
from .services.finance_engine import FinanceEngine

logger = logging.getLogger(__name__)

try:
    from payments_core.models import PaymentAccount, PaymentTransaction
    from payments_core.services import PaymentFinanceBridge
except Exception:  # pragma: no cover
    PaymentAccount = PaymentTransaction = None
    PaymentFinanceBridge = None

try:
    from finnova_autopilot.models import Alert, AutopilotProfile, SmartBill, SavingsGoal
except Exception:  # pragma: no cover
    Alert = AutopilotProfile = SmartBill = SavingsGoal = None

try:
    from analytics_ai.models import FinancialInsight
except Exception:  # pragma: no cover
    FinancialInsight = None

try:
    from audit.models import AuditLog
except Exception:  # pragma: no cover
    AuditLog = None

try:
    from notifications.models import Notification
except Exception:  # pragma: no cover
    Notification = None


INCOME_CATEGORY_LABELS = dict(Income.INCOME_CATEGORIES)
EXPENSE_CATEGORY_LABELS = dict(Expense.EXPENSE_CATEGORIES)
REPORT_TYPE_LABELS = dict(FinancialReport.REPORT_TYPES)
RANGE_OPTIONS = {
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
}


from finnovaapp.utils import _active_org, _scoped_queryset, _wants_json, _resolve_finance_account, _resolve_payment_account


def _redirect_back(request, fallback_name, **kwargs):
    fallback_url = reverse(fallback_name, kwargs=kwargs or None)
    return redirect(request.POST.get("next") or request.GET.get("next") or request.META.get("HTTP_REFERER") or fallback_url)


def _account_queryset(user, organization=None):
    return _scoped_queryset(Account.objects.filter(user=user, is_active=True), organization).order_by("-is_primary", "name")


def _notify(user, title, message, category="SYSTEM", severity="INFO", organization=None, **relations):
    if Notification is None:
        return None
    payload = {
        "user": user,
        "organization": organization,
        "title": title,
        "message": message,
        "category": category,
        "severity": severity,
    }
    allowed = {
        "related_budget",
        "related_goal",
        "related_bill",
        "related_alert",
        "related_transaction",
        "related_payment",
        "related_insight",
    }
    payload.update({key: value for key, value in relations.items() if key in allowed and value is not None})
    try:
        return Notification.objects.create(**payload)
    except Exception:
        logger.exception("Unable to create finance notification")
        return None


def _audit(actor, action, description, severity="INFO", metadata=None):
    if AuditLog is None:
        return None
    try:
        return AuditLog.objects.create(
            actor=actor,
            action=action,
            description=description,
            severity=severity,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception("Unable to create finance audit log")
        return None


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _decimal(value, default=Decimal("0.00")):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _json_safe(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return value


def _safe_engine_call(method_name, default, *args, **kwargs):
    method = getattr(FinanceEngine, method_name, None)
    if not callable(method):
        return default
    try:
        return method(*args, **kwargs)
    except Exception:
        logger.exception("FinanceEngine.%s failed", method_name)
        return default


def _safe_update_metrics(user):
    updater = getattr(FinanceEngine, "update_financial_metrics", None)
    if callable(updater):
        try:
            return updater(user)
        except Exception:
            logger.exception("Unable to update finance metrics")
    return _safe_engine_call("generate_daily_metrics", False, user)


def _default_budget_end_date(start_date, period):
    if not start_date:
        return None
    if period == "DAILY":
        return start_date
    if period == "WEEKLY":
        return start_date + timedelta(days=6)
    if period == "MONTHLY":
        return (start_date.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    if period == "QUARTERLY":
        return start_date + timedelta(days=92)
    if period == "YEARLY":
        return start_date + timedelta(days=364)
    return None


def _expense_category_label(code):
    return EXPENSE_CATEGORY_LABELS.get(code, code or "Uncategorized")


def _income_category_label(code):
    return INCOME_CATEGORY_LABELS.get(code, code or "Other")


def _build_monthly_series(user, organization=None, months=6):
    today = timezone.localdate()
    points = []
    for offset in range(months - 1, -1, -1):
        total_months = today.year * 12 + (today.month - 1) - offset
        year = total_months // 12
        month = (total_months % 12) + 1
        month_start = date(year, month, 1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        income_total = _scoped_queryset(
            Income.objects.filter(user=user, date__range=[month_start, month_end]),
            organization,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        expense_total = _scoped_queryset(
            Expense.objects.filter(user=user, date__range=[month_start, month_end]),
            organization,
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        points.append({"label": month_start.strftime("%b"), "income": income_total, "expense": expense_total})
    return points


def _summary_for_period(user, organization=None, *, start_date, end_date):
    incomes = _scoped_queryset(Income.objects.filter(user=user, date__range=[start_date, end_date]), organization)
    expenses = _scoped_queryset(Expense.objects.filter(user=user, date__range=[start_date, end_date]), organization)
    total_income = incomes.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    total_expense = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    current_balance = sum((account.current_balance for account in _account_queryset(user, organization).filter(include_in_total=True)), Decimal("0.00"))
    net_position = total_income - total_expense
    savings_rate = (net_position / total_income * 100) if total_income > 0 else Decimal('0')
    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "current_balance": current_balance,
        "net_position": net_position,
        "savings_rate": savings_rate,
        "income_count": incomes.count(),
        "expense_count": expenses.count(),
    }


def _top_expense_categories(user, organization=None, *, start_date, end_date, limit=6):
    expenses = _scoped_queryset(Expense.objects.filter(user=user, date__range=[start_date, end_date]), organization)
    total_spent = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    rows = []
    for row in expenses.values("category").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")[:limit]:
        percent = Decimal("0.00")
        if total_spent > 0:
            percent = (row["total"] / total_spent) * Decimal("100")
        rows.append(
            {
                "category": row["category"],
                "label": _expense_category_label(row["category"]),
                "total": row["total"],
                "count": row["count"],
                "percent": percent,
            }
        )
    return rows


def _build_budget_cards(user):
    budgets = list(Budget.objects.filter(user=user).prefetch_related("categories").order_by("-is_active", "end_date", "-created_at"))
    for budget in budgets:
        try:
            budget.update_spending()
        except Exception:
            logger.exception("Unable to refresh budget %s", budget.pk)
        primary_category = budget.category
        budget.primary_category_code = primary_category.name if primary_category else ""
        budget.primary_category_label = _expense_category_label(budget.primary_category_code) if budget.primary_category_code else "General"
        budget.progress_display = min(budget.utilization_percentage, Decimal("100.00"))
    return budgets


def _build_goal_cards(user):
    goals = list(FinancialGoal.objects.filter(user=user).order_by("target_date", "priority", "name"))
    for goal in goals:
        goal.progress_display = min(goal.progress_percentage, Decimal("100.00"))
    return goals


def _build_obligations(user, organization=None):
    obligations = []
    today = timezone.localdate()
    if SmartBill is not None:
        bills = _scoped_queryset(
            SmartBill.objects.filter(user=user, status__in=["PENDING", "OVERDUE"], due_date__gte=today - timedelta(days=30)),
            organization,
        ).order_by("due_date")[:6]
        for bill in bills:
            obligations.append(
                {
                    "title": bill.biller_name,
                    "kind": "Bill",
                    "amount": bill.amount,
                    "due_date": bill.due_date,
                    "status": bill.get_status_display(),
                    "detail_url": reverse("autopilot:smart_bills"),
                }
            )
    for debt in Debt.objects.filter(user=user, status="ACTIVE").order_by("next_payment_date", "lender")[:6]:
        if debt.next_payment_date:
            obligations.append(
                {
                    "title": debt.lender,
                    "kind": "Debt payment",
                    "amount": debt.emi_amount or debt.remaining_amount,
                    "due_date": debt.next_payment_date,
                    "status": debt.get_status_display(),
                    "detail_url": reverse("finance:debt_detail", kwargs={"debt_id": debt.id}),
                }
            )
    for record in TaxRecord.objects.filter(user=user, is_paid=False).order_by("due_date")[:6]:
        obligations.append(
            {
                "title": record.get_tax_type_display(),
                "kind": "Tax due",
                "amount": record.tax_due or record.total_tax,
                "due_date": record.due_date,
                "status": "Overdue" if record.is_overdue else "Upcoming",
                "detail_url": reverse("finance:taxes"),
            }
        )
    obligations.sort(key=lambda item: item["due_date"] or today)
    return obligations[:6]


def _sync_budget_category_for_expense(expense, user):
    category_name = expense.custom_category or expense.category
    if not category_name:
        expense.budget_category = None
        expense.save(update_fields=["budget_category", "updated_at"])
        return None
    budget_category = (
        BudgetCategory.objects.filter(budget__user=user, budget__is_active=True)
        .filter(name__iexact=category_name)
        .select_related("budget")
        .order_by("-budget__created_at", "name")
        .first()
    )
    if budget_category != expense.budget_category:
        expense.budget_category = budget_category
        expense.save(update_fields=["budget_category", "updated_at"])
    return budget_category


def _refresh_budget_totals(*categories):
    for category in categories:
        if not category:
            continue
        try:
            category.update_spending()
        except Exception:
            logger.exception("Unable to update budget category %s", category.pk)
        try:
            category.budget.update_spending()
        except Exception:
            logger.exception("Unable to update budget %s", getattr(category.budget, "pk", None))


def _serialize_transaction_item(item_type, item, user):
    currency = getattr(user, "preferred_currency", "INR")
    if item_type == "income":
        return {
            "kind": "Income",
            "kind_code": "income",
            "type": "income",
            "title": item.source,
            "subtitle": item.description or _income_category_label(item.category),
            "category": _income_category_label(item.category),
            "amount": item.amount,
            "signed_amount": item.amount,
            "date": item.date,
            "status": "Verified" if item.is_verified else "Pending",
            "source": "Finance",
            "currency": currency,
            "detail_url": reverse("finance:edit_income", kwargs={"income_id": item.id}),
            "edit_url": reverse("finance:edit_income", kwargs={"income_id": item.id}),
            "delete_url": reverse("finance:delete_income", kwargs={"income_id": item.id}),
            "verify_url": reverse("finance:verify_income", kwargs={"income_id": item.id}) if not item.is_verified else "",
            "sync_state": "Synced from Payments" if item.payment_reference else "Finance entry",
        }
    if item_type == "expense":
        return {
            "kind": "Expense",
            "kind_code": "expense",
            "type": "expense",
            "title": item.description,
            "subtitle": item.merchant or item.get_category_display(),
            "category": item.get_category_display(),
            "amount": item.amount,
            "signed_amount": item.amount * Decimal("-1"),
            "date": item.date,
            "status": "Verified" if item.is_verified else "Review",
            "source": "Finance",
            "currency": currency,
            "detail_url": reverse("finance:edit_expense", kwargs={"expense_id": item.id}),
            "edit_url": reverse("finance:edit_expense", kwargs={"expense_id": item.id}),
            "delete_url": reverse("finance:delete_expense", kwargs={"expense_id": item.id}),
            "categorize_url": reverse("finance:categorize_expense", kwargs={"expense_id": item.id}),
            "sync_state": "Synced from Payments" if item.payment_reference or item.payment_intent_id else "Finance entry",
        }
    return {
        "kind": "Payment",
        "kind_code": "payment",
            "type": "payment",
        "title": item.description or item.reference,
        "subtitle": item.merchant or item.reference,
        "category": item.category or item.transaction_type,
        "amount": item.amount,
        "signed_amount": item.amount if item.transaction_type in {"CREDIT", "REFUND"} else item.amount * Decimal("-1"),
        "date": (timezone.localtime(item.transaction_date).date() if timezone.is_aware(item.transaction_date) else item.transaction_date.date()),
        "status": item.get_status_display() if hasattr(item, "get_status_display") else item.status,
        "source": "Payments",
        "currency": currency,
        "detail_url": reverse("payments:payment_history"),
        "sync_state": (
            "Synced to Finance"
            if PaymentFinanceBridge is not None and PaymentFinanceBridge.is_transaction_synced(user, item)
            else "Pending finance sync"
        ),
    }


def _collect_transactions(user, organization=None, *, search="", type_filter="all", category_filter="", date_from=None, date_to=None, limit=100):
    incomes = _scoped_queryset(Income.objects.filter(user=user), organization)
    expenses = _scoped_queryset(Expense.objects.filter(user=user).select_related("budget_category", "payment_intent"), organization)
    payments = _scoped_queryset(PaymentTransaction.objects.filter(account__user=user), organization) if PaymentTransaction is not None else None
    if date_from:
        incomes = incomes.filter(date__gte=date_from)
        expenses = expenses.filter(date__gte=date_from)
        if payments is not None:
            payments = payments.filter(transaction_date__date__gte=date_from)
    if date_to:
        incomes = incomes.filter(date__lte=date_to)
        expenses = expenses.filter(date__lte=date_to)
        if payments is not None:
            payments = payments.filter(transaction_date__date__lte=date_to)
    if search:
        incomes = incomes.filter(Q(source__icontains=search) | Q(description__icontains=search) | Q(invoice_number__icontains=search))
        expenses = expenses.filter(Q(description__icontains=search) | Q(merchant__icontains=search) | Q(location__icontains=search))
        if payments is not None:
            payments = payments.filter(Q(description__icontains=search) | Q(merchant__icontains=search) | Q(reference__icontains=search))
    if category_filter:
        incomes = incomes.filter(category=category_filter)
        expenses = expenses.filter(Q(category=category_filter) | Q(custom_category__iexact=category_filter))
        if payments is not None:
            payments = payments.filter(category__icontains=category_filter)

    items = []
    if type_filter in {"all", "income"}:
        items.extend(_serialize_transaction_item("income", income, user) for income in incomes.order_by("-date", "-created_at")[:limit])
    if type_filter in {"all", "expense"}:
        items.extend(_serialize_transaction_item("expense", expense, user) for expense in expenses.order_by("-date", "-created_at")[:limit])
    if type_filter in {"all", "payment"} and payments is not None:
        items.extend(_serialize_transaction_item("payment", payment, user) for payment in payments.order_by("-transaction_date")[:limit])
    items.sort(key=lambda item: item["date"], reverse=True)
    items = items[:limit]

    totals = {
        "income": incomes.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "expense": expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "payments": payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00") if payments is not None else Decimal("0.00"),
        "unsynced_payments": 0,
    }
    if payments is not None and PaymentFinanceBridge is not None:
        totals["unsynced_payments"] = sum(
            1 for payment in payments[:limit] if payment.transaction_type == "DEBIT" and not PaymentFinanceBridge.is_transaction_synced(user, payment)
        )
    return items, totals


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def finance_dashboard(request):
    organization = _active_org(request)
    account = _resolve_finance_account(request.user, organization=organization, create_if_missing=True)
    today = timezone.localdate()
    month_start = today.replace(day=1)

    # Build chart data in both formats templates may expect
    chart_points = _build_monthly_series(request.user, organization)
    # Convert list-of-dicts → {labels, income, expense} format for Chart.js datasets
    monthly_series = {
        'labels':  [p['label']   for p in chart_points],
        'income':  [float(p['income'])  for p in chart_points],
        'expense': [float(p['expense']) for p in chart_points],
    } if chart_points else None

    return render(
        request,
        "finance/dashboard.html",
        {
            "account": account,
            "payment_account": _resolve_payment_account(request.user, organization=organization, create_if_missing=False),
            "summary": _summary_for_period(request.user, organization, start_date=month_start, end_date=today),
            "budget_preview": [budget for budget in _build_budget_cards(request.user) if budget.is_active][:4],
            "goal_preview": [goal for goal in _build_goal_cards(request.user) if goal.status in {"PLANNING", "IN_PROGRESS"}][:4],
            "obligations": _build_obligations(request.user, organization),
            "recent_transactions": _collect_transactions(request.user, organization, limit=8)[0],
            "chart_points": json.dumps([{"label": p["label"], "income": float(p["income"]), "expense": float(p["expense"])} for p in chart_points]) if chart_points else "[]",
            "monthly_series": json.dumps(monthly_series) if monthly_series else None,
            "top_categories": _top_expense_categories(request.user, organization, start_date=month_start, end_date=today, limit=4),
            "health_snapshot": _safe_engine_call("calculate_financial_health", {}, request.user),
            "insight_preview": _build_insight_preview(request.user, limit=4),
            "alert_preview": _build_alert_preview(request.user, organization, limit=4),
            "recommended_actions": _build_recommended_actions(request.user, organization),
            "analytics_url": reverse("analytics-ai:ai_dashboard"),
            "autopilot_url": reverse("autopilot:autopilot_dashboard"),
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def financial_overview(request):
    return redirect("finance:finance_dashboard")


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def transaction_center(request):
    organization = _active_org(request)
    search_query = (request.GET.get("search") or "").strip()
    type_filter = (request.GET.get("type") or "all").lower()
    category_filter = (request.GET.get("category") or "").strip()
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    transactions, totals = _collect_transactions(
        request.user,
        organization,
        search=search_query,
        type_filter=type_filter,
        category_filter=category_filter,
        date_from=date_from,
        date_to=date_to,
        limit=150,
    )
    return render(
        request,
        "finance/transaction_center.html",
        {
            "transactions": transactions,
            "totals": totals,
            "search_query": search_query,
            "type_filter": type_filter,
            "category_filter": category_filter,
            "date_from": date_from,
            "date_to": date_to,
            "expense_categories": Expense.EXPENSE_CATEGORIES,
            "income_categories": Income.INCOME_CATEGORIES,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def income_list(request):
    organization = _active_org(request)
    incomes = _scoped_queryset(Income.objects.filter(user=request.user), organization).order_by("-date", "-created_at")
    search_query = (request.GET.get("search") or "").strip()
    category_filter = request.GET.get("category") or ""
    verified_filter = request.GET.get("verified") or ""
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))

    if search_query:
        incomes = incomes.filter(Q(source__icontains=search_query) | Q(description__icontains=search_query) | Q(invoice_number__icontains=search_query))
    if category_filter:
        incomes = incomes.filter(category=category_filter)
    if verified_filter == "verified":
        incomes = incomes.filter(is_verified=True)
    elif verified_filter == "pending":
        incomes = incomes.filter(is_verified=False)
    if date_from:
        incomes = incomes.filter(date__gte=date_from)
    if date_to:
        incomes = incomes.filter(date__lte=date_to)

    stats = {
        "count": incomes.count(),
        "total_amount": incomes.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "average_amount": incomes.aggregate(avg=Avg("amount"))["avg"] or Decimal("0.00"),
        "verified_count": incomes.filter(is_verified=True).count(),
        "recurring_count": incomes.filter(is_recurring=True).count(),
    }
    page_obj = Paginator(incomes, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "finance/income_list.html",
        {
            "page_obj": page_obj,
            "stats": stats,
            "categories": Income.INCOME_CATEGORIES,
            "search_query": search_query,
            "category_filter": category_filter,
            "verified_filter": verified_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE)
def add_income(request):
    organization = _active_org(request)
    _resolve_finance_account(request.user, organization=organization, create_if_missing=True)
    form = IncomeForm(request.user, request.POST or None, request.FILES or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        income = form.save(commit=False)
        income.user = request.user
        income.organization = organization
        if income.is_recurring and not income.next_date:
            income.next_date = income.date + timedelta(days=30)
        income.save()
        _safe_update_metrics(request.user)
        _notify(request.user, "Income recorded", f"{income.source} was added to Finance.", category="INCOME", severity="SUCCESS", organization=organization)
        _audit(request.user, "FINANCE_INCOME_CREATED", f"Created income {income.source}", metadata={"income_id": str(income.id)})
        messages.success(request, "Income recorded.")
        return redirect("finance:income_list")
    return render(request, "finance/income_form.html", {"form": form, "page_title": "Add income"})


@login_required
@role_required(ROLE_OWNER_FINANCE)
def edit_income(request, income_id):
    organization = _active_org(request)
    income = get_object_or_404(_scoped_queryset(Income.objects.filter(user=request.user), organization), id=income_id)
    old_account = income.account
    form = IncomeForm(request.user, request.POST or None, request.FILES or None, instance=income, organization=organization)
    if request.method == "POST" and form.is_valid():
        income = form.save(commit=False)
        income.organization = organization
        income.save()
        for account in {old_account, income.account}:
            if not account:
                continue
            try:
                account.update_balance()
            except Exception:
                logger.exception("Unable to refresh account balance after income update")
        _safe_update_metrics(request.user)
        _audit(request.user, "FINANCE_INCOME_UPDATED", f"Updated income {income.source}", metadata={"income_id": str(income.id)})
        messages.success(request, "Income updated.")
        return redirect("finance:income_list")
    return render(request, "finance/income_form.html", {"form": form, "income": income, "page_title": "Edit income"})


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def delete_income(request, income_id):
    organization = _active_org(request)
    income = get_object_or_404(_scoped_queryset(Income.objects.filter(user=request.user), organization), id=income_id)
    account = income.account
    income.delete()
    if account:
        try:
            account.update_balance()
        except Exception:
            logger.exception("Unable to refresh account balance after income delete")
    _safe_update_metrics(request.user)
    _audit(request.user, "FINANCE_INCOME_DELETED", f"Deleted income {income.source}", severity="WARNING", metadata={"income_id": str(income_id)})
    if _wants_json(request):
        return JsonResponse({"success": True})
    messages.success(request, "Income deleted.")
    return _redirect_back(request, "finance:income_list")


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def verify_income(request, income_id):
    organization = _active_org(request)
    income = get_object_or_404(_scoped_queryset(Income.objects.filter(user=request.user), organization), id=income_id)
    income.is_verified = True
    income.verified_at = timezone.now()
    income.verified_by = request.user
    income.save(update_fields=["is_verified", "verified_at", "verified_by", "updated_at"])
    try:
        income.account.update_balance()
    except Exception:
        logger.exception("Unable to refresh account balance after income verify")
    _audit(request.user, "FINANCE_INCOME_VERIFIED", f"Verified income {income.source}", metadata={"income_id": str(income.id)})
    if _wants_json(request):
        return JsonResponse({"success": True})
    messages.success(request, "Income verified.")
    return _redirect_back(request, "finance:income_list")


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def expense_list(request):
    organization = _active_org(request)
    expenses = _scoped_queryset(Expense.objects.filter(user=request.user).select_related("budget_category", "account"), organization).order_by("-date", "-created_at")
    search_query = (request.GET.get("search") or "").strip()
    category_filter = request.GET.get("category") or ""
    payment_filter = request.GET.get("payment_method") or ""
    state_filter = request.GET.get("state") or ""
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))

    if search_query:
        expenses = expenses.filter(Q(description__icontains=search_query) | Q(merchant__icontains=search_query) | Q(location__icontains=search_query))
    if category_filter:
        expenses = expenses.filter(Q(category=category_filter) | Q(custom_category__iexact=category_filter))
    if payment_filter:
        expenses = expenses.filter(payment_method=payment_filter)
    if state_filter == "needs_review":
        expenses = expenses.filter(Q(requires_review=True) | Q(is_verified=False))
    elif state_filter == "uncategorized":
        expenses = expenses.filter(category="OTHER", custom_category__isnull=True)
    elif state_filter == "linked_budget":
        expenses = expenses.filter(budget_category__isnull=False)
    if date_from:
        expenses = expenses.filter(date__gte=date_from)
    if date_to:
        expenses = expenses.filter(date__lte=date_to)

    today = timezone.localdate()
    month_start = today.replace(day=1)
    stats = {
        "count": expenses.count(),
        "total_amount": expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "month_amount": expenses.filter(date__gte=month_start).aggregate(total=Sum("amount"))["total"] or Decimal("0.00"),
        "review_count": expenses.filter(Q(requires_review=True) | Q(is_verified=False)).count(),
        "budget_linked": expenses.filter(budget_category__isnull=False).count(),
    }
    page_obj = Paginator(expenses, 20).get_page(request.GET.get("page"))
    return render(
        request,
        "finance/expense_list.html",
        {
            "page_obj": page_obj,
            "stats": stats,
            "category_breakdown": _top_expense_categories(request.user, organization, start_date=date_from or month_start, end_date=date_to or today),
            "categories": Expense.EXPENSE_CATEGORIES,
            "payment_methods": Expense.PAYMENT_METHODS,
            "search_query": search_query,
            "category_filter": category_filter,
            "payment_filter": payment_filter,
            "state_filter": state_filter,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE)
def add_expense(request):
    organization = _active_org(request)
    _resolve_finance_account(request.user, organization=organization, create_if_missing=True)
    form = ExpenseForm(request.user, request.POST or None, request.FILES or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.user = request.user
        expense.organization = organization
        previous_category = expense.budget_category
        expense.save()
        linked_category = _sync_budget_category_for_expense(expense, request.user) or previous_category
        _refresh_budget_totals(linked_category, previous_category)
        _safe_update_metrics(request.user)
        _notify(request.user, "Expense recorded", f"{expense.description} was added to Finance.", category="TRANSACTION", severity="INFO", organization=organization)
        _audit(request.user, "FINANCE_EXPENSE_CREATED", f"Created expense {expense.description}", metadata={"expense_id": str(expense.id)})
        messages.success(request, "Expense recorded.")
        return redirect("finance:expense_list")
    return render(request, "finance/expense_form.html", {"form": form, "page_title": "Add expense"})


@login_required
@role_required(ROLE_OWNER_FINANCE)
def edit_expense(request, expense_id):
    organization = _active_org(request)
    expense = get_object_or_404(_scoped_queryset(Expense.objects.filter(user=request.user), organization), id=expense_id)
    old_account = expense.account
    old_budget_category = expense.budget_category
    form = ExpenseForm(request.user, request.POST or None, request.FILES or None, instance=expense, organization=organization)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.organization = organization
        expense.save()
        linked_category = _sync_budget_category_for_expense(expense, request.user)
        _refresh_budget_totals(old_budget_category, linked_category)
        for account in {old_account, expense.account}:
            if not account:
                continue
            try:
                account.update_balance()
            except Exception:
                logger.exception("Unable to refresh account balance after expense update")
        _safe_update_metrics(request.user)
        _audit(request.user, "FINANCE_EXPENSE_UPDATED", f"Updated expense {expense.description}", metadata={"expense_id": str(expense.id)})
        messages.success(request, "Expense updated.")
        return redirect("finance:expense_list")
    return render(request, "finance/expense_form.html", {"form": form, "expense": expense, "page_title": "Edit expense"})


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def delete_expense(request, expense_id):
    organization = _active_org(request)
    expense = get_object_or_404(_scoped_queryset(Expense.objects.filter(user=request.user), organization), id=expense_id)
    account = expense.account
    budget_category = expense.budget_category
    expense.delete()
    if account:
        try:
            account.update_balance()
        except Exception:
            logger.exception("Unable to refresh account balance after expense delete")
    _refresh_budget_totals(budget_category)
    _safe_update_metrics(request.user)
    _audit(request.user, "FINANCE_EXPENSE_DELETED", f"Deleted expense {expense.description}", severity="WARNING", metadata={"expense_id": str(expense_id)})
    if _wants_json(request):
        return JsonResponse({"success": True})
    messages.success(request, "Expense deleted.")
    return _redirect_back(request, "finance:expense_list")


@login_required
@role_required(ROLE_OWNER_FINANCE)
def categorize_expense(request, expense_id):
    organization = _active_org(request)
    expense = get_object_or_404(_scoped_queryset(Expense.objects.filter(user=request.user), organization), id=expense_id)
    suggestion = _safe_engine_call("auto_categorize_expense", expense.category or "OTHER", expense.description)
    if request.method == "POST":
        expense.category = request.POST.get("category") or "OTHER"
        expense.custom_category = (request.POST.get("custom_category") or "").strip() or None
        expense.requires_review = False
        expense.save(update_fields=["category", "custom_category", "requires_review", "updated_at"])
        linked_category = _sync_budget_category_for_expense(expense, request.user)
        _refresh_budget_totals(linked_category)
        messages.success(request, "Expense category updated.")
        return redirect("finance:expense_list")
    return render(
        request,
        "finance/categorize_expense.html",
        {
            "expense": expense,
            "categories": Expense.EXPENSE_CATEGORIES,
            "suggestion": suggestion,
            "page_title": "Categorize expense",
        },
    )


def _build_insight_preview(user, limit=4):
    if FinancialInsight is None:
        return []
    return list(FinancialInsight.objects.filter(user=user, is_active=True).order_by("-created_at")[:limit])


def _build_alert_preview(user, organization=None, limit=4):
    if Alert is None:
        return []
    queryset = _scoped_queryset(Alert.objects.filter(user=user), organization).order_by("is_read", "-alert_time")
    return list(queryset[:limit])


def _unsynced_payment_count(user, organization=None):
    if PaymentTransaction is None or PaymentFinanceBridge is None:
        return 0
    payments = _scoped_queryset(
        PaymentTransaction.objects.filter(account__user=user, status="SUCCESS").select_related("payment_intent", "account"),
        organization,
    ).order_by("-transaction_date")[:50]
    return sum(1 for payment in payments if not PaymentFinanceBridge.is_transaction_synced(user, payment))


def _build_recommended_actions(user, organization=None):
    actions = []
    active_budgets = [budget for budget in _build_budget_cards(user) if budget.is_active]
    active_goals = [goal for goal in _build_goal_cards(user) if goal.status in {"PLANNING", "IN_PROGRESS"}]
    uncategorized = _scoped_queryset(
        Expense.objects.filter(user=user, category="OTHER", custom_category__isnull=True),
        organization,
    ).count()
    review_count = _scoped_queryset(
        Expense.objects.filter(user=user).filter(Q(requires_review=True) | Q(is_verified=False)),
        organization,
    ).count()
    unsynced_count = _unsynced_payment_count(user, organization)

    if not active_budgets:
        actions.append(
            {
                "title": "Create a working budget",
                "description": "Set a spending guardrail so Finance can track budget health.",
                "url": reverse("finance:add_budget"),
                "icon": "fa-chart-pie",
            }
        )
    else:
        exceeded = next((budget for budget in active_budgets if budget.is_exceeded), None)
        near_limit = next((budget for budget in active_budgets if budget.is_near_limit and not budget.is_exceeded), None)
        if exceeded:
            actions.append(
                {
                    "title": f"Review {exceeded.name}",
                    "description": "This budget is over limit and needs a spending decision.",
                    "url": reverse("finance:budget_detail", kwargs={"budget_id": exceeded.id}),
                    "icon": "fa-triangle-exclamation",
                }
            )
        elif near_limit:
            actions.append(
                {
                    "title": f"Protect {near_limit.name}",
                    "description": "This budget is approaching its threshold.",
                    "url": reverse("finance:budget_detail", kwargs={"budget_id": near_limit.id}),
                    "icon": "fa-gauge-high",
                }
            )

    if not active_goals:
        actions.append(
            {
                "title": "Create a financial goal",
                "description": "Turn spare cash flow into a visible target.",
                "url": reverse("finance:add_financial_goal"),
                "icon": "fa-bullseye",
            }
        )
    else:
        urgent_goal = min(active_goals, key=lambda goal: (goal.target_date, goal.priority))
        actions.append(
            {
                "title": f"Fund {urgent_goal.name}",
                "description": "Update goal progress so Autopilot can use the latest target state.",
                "url": reverse("finance:goal_detail", kwargs={"goal_id": urgent_goal.id}),
                "icon": "fa-piggy-bank",
            }
        )

    if uncategorized:
        actions.append(
            {
                "title": "Categorize uncategorized spend",
                "description": f"{uncategorized} expense entries still need a clear category.",
                "url": reverse("finance:expense_list") + "?state=uncategorized",
                "icon": "fa-tags",
            }
        )
    elif review_count:
        actions.append(
            {
                "title": "Review flagged expenses",
                "description": f"{review_count} expense entries need verification or review.",
                "url": reverse("finance:expense_list") + "?state=needs_review",
                "icon": "fa-clipboard-check",
            }
        )

    if unsynced_count:
        actions.append(
            {
                "title": "Sync recent payments",
                "description": f"{unsynced_count} payment records are not reflected in Finance yet.",
                "url": reverse("finance:sync_payments"),
                "icon": "fa-arrows-rotate",
            }
        )

    if FinancialInsight is not None:
        insight = FinancialInsight.objects.filter(user=user, is_active=True, action_required=True).order_by("-created_at").first()
        if insight:
            actions.append(
                {
                    "title": "Review AI insight",
                    "description": insight.title,
                    "url": reverse("analytics-ai:financial_insights"),
                    "icon": "fa-lightbulb",
                }
            )

    if not actions:
        actions = [
            {
                "title": "Open Transaction Center",
                "description": "Use one operational page to review recent money movement.",
                "url": reverse("finance:transaction_center"),
                "icon": "fa-list-check",
            },
            {
                "title": "Generate a report",
                "description": "Create a period summary for deeper review or sharing.",
                "url": reverse("finance:reports"),
                "icon": "fa-file-lines",
            },
        ]
    return actions[:5]


def _normalize_advisory_items(items, default_title="Recommendation", default_description="Recommendation"):
    normalized = []
    for item in items or []:
        if isinstance(item, dict):
            payload = item
        elif hasattr(item, "__dict__"):
            payload = {
                "title": getattr(item, "title", None),
                "description": getattr(item, "description", None),
                "message": getattr(item, "message", None),
                "recommendation": getattr(item, "recommendation", None),
                "type": getattr(item, "type", None),
            }
        else:
            text = str(item).strip()
            if not text:
                continue
            payload = {"title": text}

        title = (
            payload.get("title")
            or payload.get("recommendation")
            or payload.get("message")
            or payload.get("type")
            or default_title
        )
        description = payload.get("description") or payload.get("message") or default_description
        normalized.append(
            {
                "title": title,
                "description": description,
                "type": payload.get("type") or title,
            }
        )
    return normalized


def _sync_goal_to_autopilot(goal):
    if SavingsGoal is None:
        return None
    savings_goal = SavingsGoal.objects.filter(user=goal.user, goal_name=goal.name).order_by("-updated_at", "-created_at").first()
    payload = {
        "target_amount": goal.target_amount,
        "current_saved": goal.current_amount,
        "target_date": goal.target_date,
        "suggested_monthly_saving": goal.suggested_monthly_saving,
        "priority": goal.priority,
        "status": "ACHIEVED" if goal.status == "ACHIEVED" else "ACTIVE",
        "auto_save_account": goal.linked_account,
        "metadata": {"finance_goal_id": str(goal.id)},
    }
    if savings_goal is None:
        return SavingsGoal.objects.create(user=goal.user, goal_name=goal.name, **payload)
    changed_fields = []
    for key, value in payload.items():
        if getattr(savings_goal, key) != value:
            setattr(savings_goal, key, value)
            changed_fields.append(key)
    if changed_fields:
        changed_fields.append("updated_at")
        savings_goal.save(update_fields=changed_fields)
    return savings_goal


def _goal_contributions(goal):
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    contributions = metadata.get("contributions", [])
    rows = []
    for item in contributions:
        created_at = item.get("created_at") or item.get("contribution_date")
        contribution_date = _parse_date(item.get("contribution_date"))
        if contribution_date is None and created_at:
            try:
                contribution_date = datetime.fromisoformat(created_at).date()
            except ValueError:
                contribution_date = None
        rows.append(
            {
                "created_at": created_at,
                "contribution_date": contribution_date,
                "amount": _decimal(item.get("amount")),
                "notes": item.get("notes", ""),
                "source_account": item.get("source_account", ""),
                "source": item.get("source_account") or item.get("notes") or "Contribution",
                "date": _parse_date(item.get("contribution_date")),
                "running_total": _decimal(item.get("running_total"), goal.current_amount),
            }
        )
    rows.sort(key=lambda item: item["contribution_date"] or timezone.localdate(), reverse=True)
    return rows


def _monthly_goal_progress(goal, months=6):
    today = timezone.localdate()
    contributions = _goal_contributions(goal)
    rows = []
    for offset in range(months - 1, -1, -1):
        total_months = today.year * 12 + (today.month - 1) - offset
        year = total_months // 12
        month = (total_months % 12) + 1
        month_start = date(year, month, 1)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        total = sum(
            (item["amount"] for item in contributions if item["contribution_date"] and month_start <= item["contribution_date"] <= month_end),
            Decimal("0.00"),
        )
        rows.append(
            {
                "month": month_start.strftime("%b"),
                "amount": total,
                "target": goal.suggested_monthly_saving or Decimal("0.00"),
            }
        )
    return rows


def _fallback_report_payload(user, organization=None, *, report_type, start_date, end_date, category="", include_investments=True, include_debts=True):
    summary = _summary_for_period(user, organization, start_date=start_date, end_date=end_date)
    incomes = _scoped_queryset(Income.objects.filter(user=user, date__range=[start_date, end_date]), organization)
    expenses = _scoped_queryset(Expense.objects.filter(user=user, date__range=[start_date, end_date]), organization)
    if category:
        expenses = expenses.filter(Q(category=category) | Q(custom_category__iexact=category))

    income_breakdown = [
        {
            "category": row["category"],
            "label": _income_category_label(row["category"]),
            "total": row["total"],
            "count": row["count"],
        }
        for row in incomes.values("category").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")
    ]

    budget_rows = []
    for budget in Budget.objects.filter(user=user).prefetch_related("categories").order_by("-is_active", "end_date", "-created_at"):
        if budget.end_date and budget.end_date < start_date:
            continue
        if budget.start_date > end_date:
            continue
        try:
            budget.update_spending()
        except Exception:
            logger.exception("Unable to update budget %s for report", budget.pk)
        budget_rows.append(
            {
                "id": str(budget.id),
                "name": budget.name,
                "amount": budget.amount,
                "spent": budget.current_spending,
                "remaining": budget.remaining_amount,
                "status": budget.get_status_display(),
                "utilization": budget.utilization_percentage,
            }
        )

    goal_rows = [
        {
            "id": str(goal.id),
            "name": goal.name,
            "target_amount": goal.target_amount,
            "current_amount": goal.current_amount,
            "progress": goal.progress_percentage,
            "target_date": goal.target_date,
            "status": goal.get_status_display(),
        }
        for goal in FinancialGoal.objects.filter(user=user).order_by("target_date", "priority")
    ]

    daily_labels = []
    daily_income = []
    daily_expense = []
    span_days = min((end_date - start_date).days, 30)
    for offset in range(span_days, -1, -1):
        day = end_date - timedelta(days=offset)
        day_income = incomes.filter(date=day).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        day_expense = expenses.filter(date=day).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        daily_labels.append(day.isoformat())
        daily_income.append(float(day_income))
        daily_expense.append(float(day_expense))

    payload = {
        "summary": summary,
        "report_type": report_type,
        "expense_breakdown": _top_expense_categories(user, organization, start_date=start_date, end_date=end_date),
        "income_breakdown": income_breakdown,
        "budget_performance": budget_rows,
        "goals": goal_rows,
        "insights": _normalize_advisory_items(
            [insight.title for insight in _build_insight_preview(user, limit=4)],
            default_title="Insight",
            default_description="Insight",
        ),
        "recommendations": _normalize_advisory_items(
            _build_recommended_actions(user, organization),
            default_title="Recommendation",
            default_description="Recommendation",
        ),
        "charts": {
            "labels": daily_labels,
            "income": daily_income,
            "expense": daily_expense,
            "savings": [income - expense for income, expense in zip(daily_income, daily_expense)],
        },
    }

    if include_investments:
        active_investments = Investment.objects.filter(user=user, status="ACTIVE")
        payload["investments"] = {
            "count": active_investments.count(),
            "invested_amount": active_investments.aggregate(total=Sum("invested_amount"))["total"] or Decimal("0.00"),
            "current_value": active_investments.aggregate(total=Sum("current_value"))["total"] or Decimal("0.00"),
        }
    if include_debts:
        active_debts = Debt.objects.filter(user=user, status="ACTIVE")
        payload["debts"] = {
            "count": active_debts.count(),
            "remaining_amount": active_debts.aggregate(total=Sum("remaining_amount"))["total"] or Decimal("0.00"),
            "monthly_emi": active_debts.aggregate(total=Sum("emi_amount"))["total"] or Decimal("0.00"),
        }
    return payload


def _build_report_payload(user, organization=None, *, report_type, start_date, end_date, category="", include_investments=True, include_debts=True):
    payload = _safe_engine_call(
        "generate_comprehensive_report",
        None,
        user=user,
        report_type=report_type,
        start_date=start_date,
        end_date=end_date,
        category=category or None,
        include_predictions=False,
    )
    if not isinstance(payload, dict) or not payload:
        payload = _fallback_report_payload(
            user,
            organization,
            report_type=report_type,
            start_date=start_date,
            end_date=end_date,
            category=category,
            include_investments=include_investments,
            include_debts=include_debts,
        )
    payload.setdefault("summary", _summary_for_period(user, organization, start_date=start_date, end_date=end_date))
    payload.setdefault("expense_breakdown", _top_expense_categories(user, organization, start_date=start_date, end_date=end_date))
    payload["insights"] = _normalize_advisory_items(
        payload.get("insights") or [insight.title for insight in _build_insight_preview(user, limit=4)],
        default_title="Insight",
        default_description="Insight",
    )
    payload["recommendations"] = _normalize_advisory_items(
        payload.get("recommendations") or _build_recommended_actions(user, organization),
        default_title="Recommendation",
        default_description="Recommendation",
    )
    return payload


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def budget_list(request):
    budgets = _build_budget_cards(request.user)
    status_filter = (request.GET.get("status") or "active").lower()
    if status_filter == "inactive":
        budgets = [budget for budget in budgets if not budget.is_active]
    elif status_filter == "exceeded":
        budgets = [budget for budget in budgets if budget.is_exceeded]
    elif status_filter == "near_limit":
        budgets = [budget for budget in budgets if budget.is_near_limit and not budget.is_exceeded]
    elif status_filter == "all":
        pass
    else:
        status_filter = "active"
        budgets = [budget for budget in budgets if budget.is_active]

    active_budgets = [budget for budget in budgets if budget.is_active]
    total_budgeted = sum((budget.amount for budget in active_budgets), Decimal("0.00"))
    total_spent = sum((budget.current_spending for budget in active_budgets), Decimal("0.00"))
    stats = {
        "total": len(budgets),
        "active": len(active_budgets),
        "total_budgeted": total_budgeted,
        "total_spent": total_spent,
        "overall_utilization": (total_spent / total_budgeted * Decimal("100")) if total_budgeted > 0 else Decimal("0.00"),
        "exceeded": sum(1 for budget in active_budgets if budget.is_exceeded),
        "near_limit": sum(1 for budget in active_budgets if budget.is_near_limit and not budget.is_exceeded),
    }
    return render(
        request,
        "finance/budget_list.html",
        {
            "budgets": budgets,
            "stats": stats,
            "status_filter": status_filter,
            "expense_categories": Expense.EXPENSE_CATEGORIES,
            "recommended_actions": _build_recommended_actions(request.user)[:3],
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE)
def add_budget(request):
    selected_category = (request.POST.get("primary_category") if request.method == "POST" else request.GET.get("category")) or ""
    form = BudgetForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        budget = form.save(commit=False)
        budget.user = request.user
        if not budget.end_date:
            budget.end_date = _default_budget_end_date(budget.start_date, budget.period)
        budget.save()
        category_name = selected_category or budget.name
        BudgetCategory.objects.update_or_create(
            budget=budget,
            name=category_name,
            defaults={
                "allocated_amount": budget.amount,
                "color_code": "#2196F3",
                "priority": 1,
                "description": f"Primary category for {budget.name}",
            },
        )
        _refresh_budget_totals(*budget.categories.all())
        _safe_update_metrics(request.user)
        _notify(request.user, "Budget created", f"{budget.name} is now active in Finance.", category="BUDGET", severity="INFO", related_budget=budget)
        _audit(request.user, "FINANCE_BUDGET_CREATED", f"Created budget {budget.name}", metadata={"budget_id": str(budget.id)})
        messages.success(request, "Budget created.")
        return redirect("finance:budget_list")

    recommendation = _safe_engine_call("recommend_budget_amount", None, request.user, selected_category or None)
    spending_history = []
    if selected_category:
        today = timezone.localdate()
        for offset in range(3, 0, -1):
            total_months = today.year * 12 + (today.month - 1) - offset
            year = total_months // 12
            month = (total_months % 12) + 1
            month_start = date(year, month, 1)
            month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            amount = Expense.objects.filter(user=request.user, date__range=[month_start, month_end], category=selected_category).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            spending_history.append({"month": month_start.strftime("%b"), "amount": amount})
    return render(
        request,
        "finance/budget_form.html",
        {
            "form": form,
            "selected_category": selected_category,
            "expense_categories": Expense.EXPENSE_CATEGORIES,
            "recommended_amount": recommendation,
            "spending_history": spending_history,
            "page_title": "Create budget",
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def toggle_budget(request, budget_id):
    budget = get_object_or_404(Budget.objects.filter(user=request.user), id=budget_id)
    budget.is_active = not budget.is_active
    budget.save(update_fields=["is_active", "last_updated"])
    _audit(request.user, "FINANCE_BUDGET_TOGGLED", f"Toggled budget {budget.name}", metadata={"budget_id": str(budget.id), "is_active": budget.is_active})
    if _wants_json(request):
        return JsonResponse({"success": True, "is_active": budget.is_active})
    messages.success(request, f"{budget.name} is now {'active' if budget.is_active else 'inactive'}.")
    return _redirect_back(request, "finance:budget_list")


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def budget_detail(request, budget_id):
    budget = get_object_or_404(Budget.objects.prefetch_related("categories"), id=budget_id, user=request.user)
    try:
        budget.update_spending()
    except Exception:
        logger.exception("Unable to refresh budget %s", budget.pk)
    budget_categories = list(budget.categories.order_by("priority", "name"))
    category_names = [category.name for category in budget_categories]
    end_date = budget.end_date or timezone.localdate()
    expenses = Expense.objects.filter(user=request.user, date__range=[budget.start_date, end_date])
    if category_names:
        expenses = expenses.filter(Q(budget_category__budget=budget) | Q(category__in=category_names) | Q(custom_category__in=category_names))
    else:
        expenses = expenses.filter(budget_category__budget=budget)
    expenses = expenses.select_related("budget_category", "account").distinct().order_by("-date", "-created_at")

    running_total = Decimal("0.00")
    daily_spending = []
    current_date = budget.start_date
    while current_date <= end_date:
        day_total = expenses.filter(date=current_date).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        running_total += day_total
        daily_spending.append({"date": current_date, "amount": day_total, "cumulative": running_total})
        current_date += timedelta(days=1)

    subcategories = [
        {
            "name": row["budget_category__name"] or row["custom_category"] or row["category"],
            "total": row["total"],
            "count": row["count"],
        }
        for row in expenses.values("budget_category__name", "custom_category", "category").annotate(total=Sum("amount"), count=Count("id")).order_by("-total")
        if row["budget_category__name"] or row["custom_category"] or row["category"]
    ]
    insights = [
        insight for insight in _build_insight_preview(request.user, limit=8) if insight.insight_type in {"BUDGET", "SPENDING", "RECOMMENDATION"}
    ][:4]
    return render(
        request,
        "finance/budget_detail.html",
        {
            "budget": budget,
            "budget_categories": budget_categories,
            "expenses": expenses[:20],
            "daily_spending": daily_spending,
            "subcategories": subcategories,
            "utilization_percentage": budget.utilization_percentage,
            "remaining_days": (end_date - timezone.localdate()).days if budget.end_date else None,
            "ai_insights": insights,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def financial_goals(request):
    _safe_engine_call("update_financial_goals", 0, request.user)
    goals = _build_goal_cards(request.user)
    status_filter = (request.GET.get("status") or "").upper()
    if status_filter == "COMPLETED":
        status_filter = "ACHIEVED"
    if status_filter:
        goals = [goal for goal in goals if goal.status == status_filter]

    total_target = sum((goal.target_amount for goal in goals), Decimal("0.00"))
    total_current = sum((goal.current_amount for goal in goals), Decimal("0.00"))
    stats = {
        "total": len(goals),
        "active": sum(1 for goal in goals if goal.status in {"PLANNING", "IN_PROGRESS"}),
        "completed": sum(1 for goal in goals if goal.status == "ACHIEVED"),
        "total_target": total_target,
        "total_current": total_current,
        "overall_progress": (total_current / total_target * Decimal("100")) if total_target > 0 else Decimal("0.00"),
    }
    recommendations = [
        {
            "title": "Build an emergency fund",
            "description": "Target three to six months of essential expenses in a liquid account.",
        },
        {
            "title": "Tie goals to real cash flow",
            "description": "Use the monthly savings target to shape budgets and Autopilot rules.",
        },
    ]
    return render(
        request,
        "finance/goals.html",
        {
            "goals": goals,
            "stats": stats,
            "status_filter": status_filter,
            "ai_recommendations": recommendations,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE)
def add_financial_goal(request):
    organization = _active_org(request)
    form = FinancialGoalForm(request.user, request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        goal = form.save(commit=False)
        goal.user = request.user
        goal.start_date = timezone.localdate()
        if goal.months_remaining > 0:
            goal.suggested_monthly_saving = goal.required_monthly_saving
        goal.save()
        _sync_goal_to_autopilot(goal)
        _notify(request.user, "Goal created", f"{goal.name} is now being tracked in Finance.", category="SAVINGS", severity="INFO", related_goal=goal)
        _audit(request.user, "FINANCE_GOAL_CREATED", f"Created goal {goal.name}", metadata={"goal_id": str(goal.id)})
        messages.success(request, "Goal created.")
        return redirect("finance:financial_goals")

    templates = [
        {"name": "Emergency Fund", "goal_type": "EMERGENCY_FUND", "target_amount": Decimal("150000.00"), "target_months": 12},
        {"name": "Travel Fund", "goal_type": "VACATION", "target_amount": Decimal("60000.00"), "target_months": 9},
        {"name": "Debt-free milestone", "goal_type": "DEBT_FREE", "target_amount": Decimal("100000.00"), "target_months": 18},
    ]
    return render(
        request,
        "finance/goal_form.html",
        {
            "form": form,
            "templates": templates,
            "page_title": "Create goal",
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def update_goal_progress(request, goal_id):
    organization = _active_org(request)
    goal = get_object_or_404(FinancialGoal.objects.filter(user=request.user), id=goal_id)
    form = GoalContributionForm(request.user, goal, request.POST, organization=organization)
    if not form.is_valid():
        if _wants_json(request):
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
        return redirect("finance:goal_detail", goal_id=goal.id)

    amount = form.cleaned_data["amount"]
    contribution_date = form.cleaned_data["contribution_date"]
    source_account = form.cleaned_data["source_account"]
    notes = form.cleaned_data["notes"]

    goal.current_amount += amount
    if goal.status == "PLANNING":
        goal.status = "IN_PROGRESS"
    if goal.current_amount >= goal.target_amount:
        goal.status = "ACHIEVED"
    goal.last_contribution_date = contribution_date
    goal.last_contribution_amount = amount
    if goal.linked_account is None:
        goal.linked_account = source_account
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    contributions = metadata.get("contributions", [])
    if not isinstance(contributions, list):
        contributions = []
    contributions.append(
        {
            "created_at": timezone.now().isoformat(),
            "contribution_date": contribution_date.isoformat(),
            "amount": str(amount),
            "notes": notes,
            "source_account": source_account.name,
            "source_account_id": str(source_account.id),
            "running_total": str(goal.current_amount),
        }
    )
    metadata["contributions"] = contributions[-100:]
    goal.metadata = metadata
    goal.save()
    _sync_goal_to_autopilot(goal)
    _notify(request.user, "Goal contribution recorded", f"{goal.name} was updated by {amount}.", category="SAVINGS", severity="SUCCESS", related_goal=goal)
    _audit(request.user, "FINANCE_GOAL_PROGRESS_UPDATED", f"Updated goal {goal.name}", metadata={"goal_id": str(goal.id), "amount": str(amount)})

    if _wants_json(request):
        return JsonResponse(
            {
                "success": True,
                "current_amount": float(goal.current_amount),
                "progress": float(goal.progress_percentage),
                "status": goal.get_status_display(),
            }
        )
    messages.success(request, "Goal progress updated.")
    return redirect("finance:goal_detail", goal_id=goal.id)


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def goal_detail(request, goal_id):
    organization = _active_org(request)
    goal = get_object_or_404(FinancialGoal.objects.select_related("linked_account"), id=goal_id, user=request.user)
    contributions = _goal_contributions(goal)
    autopilot_goal = SavingsGoal.objects.filter(user=request.user, goal_name=goal.name).order_by("-updated_at", "-created_at").first() if SavingsGoal is not None else None
    return render(
        request,
        "finance/goal_detail.html",
        {
            "goal": goal,
            "transactions": contributions,
            "monthly_progress": _monthly_goal_progress(goal),
            "ai_recommendations": _normalize_advisory_items(
                _safe_engine_call("get_goal_recommendations", [], request.user, goal),
                default_title="Goal recommendation",
                default_description="Goal recommendation",
            ),
            "months_remaining": goal.months_remaining,
            "monthly_needed": goal.required_monthly_saving,
            "today": timezone.localdate(),
            "contribution_form": GoalContributionForm(request.user, goal, organization=organization),
            "autopilot_goal": autopilot_goal,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def reports(request):
    reports_list = FinancialReport.objects.filter(user=request.user).order_by("-generated_at", "-created_at")
    form = ReportFilterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        report_type = form.cleaned_data["report_type"]
        start_date = form.cleaned_data["start_date"]
        end_date = form.cleaned_data["end_date"]
        category = form.cleaned_data["category"]
        include_investments = form.cleaned_data["include_investments"]
        include_debts = form.cleaned_data["include_debts"]
        payload = _json_safe(
            _build_report_payload(
                request.user,
                _active_org(request),
                report_type=report_type,
                start_date=start_date,
                end_date=end_date,
                category=category,
                include_investments=include_investments,
                include_debts=include_debts,
            )
        )
        report = FinancialReport.objects.create(
            user=request.user,
            report_type=report_type,
            title=f"{REPORT_TYPE_LABELS.get(report_type, report_type.title())} report - {start_date:%d %b %Y} to {end_date:%d %b %Y}",
            start_date=start_date,
            end_date=end_date,
            report_data=payload,
            charts_data=payload.get("charts", {}),
            insights=payload.get("insights", []),
            recommendations=payload.get("recommendations", []),
            is_generated=True,
            generated_at=timezone.now(),
            metadata={"category": category or "", "include_investments": include_investments, "include_debts": include_debts},
        )
        _notify(request.user, "Report generated", report.title, category="SYSTEM", severity="INFO")
        _audit(request.user, "FINANCE_REPORT_CREATED", f"Generated report {report.title}", metadata={"report_id": str(report.id)})
        messages.success(request, "Report generated.")
        return redirect("finance:view_report", report_id=report.id)

    quick_reports = [
        {"report_type": "MONTHLY", "label": "This month", "days": 30},
        {"report_type": "QUARTERLY", "label": "Quarter", "days": 90},
        {"report_type": "YEARLY", "label": "Year", "days": 365},
        {"report_type": "BUDGET", "label": "Budget health", "days": 30},
    ]
    return render(
        request,
        "finance/reports.html",
        {
            "reports": reports_list[:8],
            "form": form,
            "quick_reports": quick_reports,
            "total_reports": reports_list.count(),
            "analytics_url": reverse("analytics-ai:ai_dashboard"),
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def view_report(request, report_id):
    report = get_object_or_404(FinancialReport.objects.filter(user=request.user), id=report_id)
    report_data = report.report_data or {}
    return render(
        request,
        "finance/report_view.html",
        {
            "report": report,
            "report_data": report_data,
            "charts_data": report.charts_data or {},
            "insights": _normalize_advisory_items(report.insights or [], default_title="Insight", default_description="Insight"),
            "recommendations": _normalize_advisory_items(report.recommendations or [], default_title="Recommendation", default_description="Recommendation"),
            "analytics_url": reverse("analytics-ai:ai_dashboard"),
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def analytics(request):
    messages.info(request, "Finance Intelligence is now powered by the Analytics module.")
    return redirect('analytics-ai:ai_dashboard')


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def investments(request):
    organization = _active_org(request)
    investments_qs = Investment.objects.filter(user=request.user).select_related("account").order_by("-purchase_date", "-created_at")
    if organization is not None:
        investments_qs = investments_qs.filter(Q(account__organization=organization) | Q(account__organization__isnull=True))

    form = InvestmentForm(request.user, request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        investment = form.save(commit=False)
        investment.user = request.user
        investment.current_value = investment.current_value or investment.invested_amount
        investment.save()
        _notify(request.user, "Investment added", f"{investment.name} is now tracked in Finance.", category="INVESTMENT", severity="INFO")
        _audit(request.user, "FINANCE_INVESTMENT_CREATED", f"Created investment {investment.name}", metadata={"investment_id": str(investment.id)})
        messages.success(request, "Investment added.")
        return redirect("finance:investments")

    investments_list = list(investments_qs)
    total_invested = sum((item.invested_amount for item in investments_list), Decimal("0.00"))
    total_current = sum((item.current_value for item in investments_list), Decimal("0.00"))
    stats = {
        "total": len(investments_list),
        "active": sum(1 for item in investments_list if item.status == "ACTIVE"),
        "total_invested": total_invested,
        "total_current": total_current,
        "total_return": total_current - total_invested,
        "overall_return_percentage": ((total_current - total_invested) / total_invested * Decimal("100")) if total_invested > 0 else Decimal("0.00"),
    }
    asset_breakdown = [
        {
            "name": row["instrument"],
            "label": dict(Investment.INSTRUMENT_TYPES).get(row["instrument"], row["instrument"]),
            "total_invested": row["invested"],
            "total_current": row["current"],
            "count": row["count"],
        }
        for row in investments_qs.values("instrument").annotate(invested=Sum("invested_amount"), current=Sum("current_value"), count=Count("id")).order_by("-invested")
    ]
    return render(
        request,
        "finance/investments.html",
        {
            "investments": investments_list,
            "form": form,
            "stats": stats,
            "asset_breakdown": asset_breakdown,
            "analytics_url": reverse("analytics-ai:ai_dashboard"),
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def investment_detail(request, investment_id):
    organization = _active_org(request)
    queryset = Investment.objects.filter(user=request.user).select_related("account")
    if organization is not None:
        queryset = queryset.filter(Q(account__organization=organization) | Q(account__organization__isnull=True))
    investment = get_object_or_404(queryset, id=investment_id)

    performance_data = []
    today = timezone.localdate()
    if investment.purchase_date:
        total_days = max((today - investment.purchase_date).days, 1)
        current_date = investment.purchase_date
        while current_date <= today:
            elapsed_days = max((current_date - investment.purchase_date).days, 0)
            ratio = Decimal(elapsed_days) / Decimal(total_days)
            value = investment.invested_amount + ((investment.current_value - investment.invested_amount) * ratio)
            performance_data.append({"date": current_date, "value": value})
            current_date += timedelta(days=30)

    insights = [insight for insight in _build_insight_preview(request.user, limit=8) if insight.insight_type in {"INVESTMENT", "RECOMMENDATION", "RISK"}][:4]
    return render(
        request,
        "finance/investment_detail.html",
        {
            "investment": investment,
            "performance_data": performance_data,
            "ai_insights": insights,
            "holding_period": investment.holding_period if investment.purchase_date else 0,
            "analytics_url": reverse("analytics-ai:ai_dashboard"),
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def debts(request):
    organization = _active_org(request)
    debts_qs = Debt.objects.filter(user=request.user).select_related("account", "auto_pay_account").order_by("-created_at")
    if organization is not None:
        debts_qs = debts_qs.filter(Q(account__organization=organization) | Q(account__organization__isnull=True))

    form = DebtForm(request.user, request.POST or None, organization=organization)
    if request.method == "POST" and form.is_valid():
        debt = form.save(commit=False)
        debt.user = request.user
        debt.remaining_amount = debt.remaining_amount or debt.principal_amount
        if debt.emi_day:
            base_date = max(timezone.localdate(), debt.start_date)
            next_month = base_date.replace(day=1)
            next_date = next_month.replace(day=min(debt.emi_day, 28))
            if next_date < base_date:
                next_date = (next_month + timedelta(days=32)).replace(day=1).replace(day=min(debt.emi_day, 28))
            debt.next_payment_date = next_date
        if not debt.emi_amount and debt.end_date:
            tenure_months = max(1, (debt.end_date.year - debt.start_date.year) * 12 + (debt.end_date.month - debt.start_date.month))
            debt.emi_amount = debt.calculate_emi(tenure_months)
        debt.save()
        _notify(request.user, "Debt added", f"{debt.lender} is now tracked in Finance.", category="DEBT", severity="INFO")
        _audit(request.user, "FINANCE_DEBT_CREATED", f"Created debt {debt.lender}", metadata={"debt_id": str(debt.id)})
        messages.success(request, "Debt added.")
        return redirect("finance:debts")

    debts_list = list(debts_qs)
    stats = {
        "total": len(debts_list),
        "active": sum(1 for item in debts_list if item.status == "ACTIVE"),
        "paid_off": sum(1 for item in debts_list if item.status == "PAID_OFF"),
        "total_principal": sum((item.principal_amount for item in debts_list), Decimal("0.00")),
        "total_remaining": sum((item.remaining_amount for item in debts_list), Decimal("0.00")),
        "total_paid": sum((item.total_paid for item in debts_list), Decimal("0.00")),
        "monthly_emi": sum((item.emi_amount or Decimal("0.00") for item in debts_list if item.status == "ACTIVE"), Decimal("0.00")),
    }
    type_breakdown = debts_qs.values("debt_type").annotate(total_remaining=Sum("remaining_amount"), count=Count("id")).order_by("-total_remaining")
    return render(
        request,
        "finance/debts.html",
        {
            "debts": debts_list,
            "form": form,
            "stats": stats,
            "type_breakdown": type_breakdown,
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def debt_detail(request, debt_id):
    organization = _active_org(request)
    queryset = Debt.objects.filter(user=request.user).select_related("account", "auto_pay_account")
    if organization is not None:
        queryset = queryset.filter(Q(account__organization=organization) | Q(account__organization__isnull=True))
    debt = get_object_or_404(queryset, id=debt_id)

    amortization = []
    if debt.emi_amount and debt.emi_amount > 0:
        remaining = debt.remaining_amount
        for month_index in range(1, min(debt.months_remaining, 12) + 1):
            interest_amount = (remaining * debt.interest_rate / Decimal("1200")).quantize(Decimal("0.01"))
            principal_amount = max(Decimal("0.00"), min(debt.emi_amount - interest_amount, remaining))
            remaining = max(Decimal("0.00"), remaining - principal_amount)
            amortization.append(
                {
                    "month": month_index,
                    "payment_date": timezone.localdate() + timedelta(days=30 * month_index),
                    "payment_amount": debt.emi_amount,
                    "principal_amount": principal_amount,
                    "interest_amount": interest_amount,
                    "remaining_balance": remaining,
                }
            )

    early_payoff_options = []
    for extra_payment in [5000, 10000, 25000]:
        if debt.emi_amount and debt.emi_amount > 0 and debt.remaining_amount > extra_payment:
            months_saved = int(Decimal(extra_payment) / max(debt.emi_amount, Decimal("1.00")))
            interest_saved = (Decimal(extra_payment) * debt.interest_rate / Decimal("1200")).quantize(Decimal("0.01"))
            early_payoff_options.append({"extra_payment": extra_payment, "months_saved": months_saved, "interest_saved": interest_saved})

    insights = [insight for insight in _build_insight_preview(request.user, limit=8) if insight.insight_type in {"DEBT", "RECOMMENDATION", "RISK"}][:4]
    return render(
        request,
        "finance/debt_detail.html",
        {
            "debt": debt,
            "amortization": amortization,
            "early_payoff_options": early_payoff_options,
            "ai_recommendations": insights,
            "payment_form": DebtPaymentForm(debt),
            "today": timezone.localdate(),
        },
    )


@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def make_debt_payment(request, debt_id):
    organization = _active_org(request)
    queryset = Debt.objects.filter(user=request.user).select_related("account", "auto_pay_account")
    if organization is not None:
        queryset = queryset.filter(Q(account__organization=organization) | Q(account__organization__isnull=True))
    debt = get_object_or_404(queryset, id=debt_id)
    form = DebtPaymentForm(debt, request.POST)
    if not form.is_valid():
        if _wants_json(request):
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
        messages.error(request, "Unable to record that payment.")
        return redirect("finance:debt_detail", debt_id=debt.id)

    amount = form.cleaned_data["amount"]
    payment_date = form.cleaned_data["payment_date"]
    payment_method = form.cleaned_data["payment_method"]
    notes = form.cleaned_data["notes"]

    debt.make_payment(amount, date=payment_date)
    expense = Expense.objects.create(
        user=request.user,
        organization=organization,
        account=debt.account,
        amount=amount,
        description=f"Debt payment: {debt.lender}",
        category="EMI",
        date=payment_date,
        payment_method=payment_method,
        merchant=debt.lender,
        is_verified=True,
        metadata={"debt_id": str(debt.id), "notes": notes},
    )
    linked_category = _sync_budget_category_for_expense(expense, request.user)
    _refresh_budget_totals(linked_category)
    _safe_update_metrics(request.user)
    _notify(request.user, "Debt payment recorded", f"{amount} was applied to {debt.lender}.", category="DEBT", severity="INFO")
    _audit(request.user, "FINANCE_DEBT_PAYMENT_CREATED", f"Recorded debt payment for {debt.lender}", metadata={"debt_id": str(debt.id), "expense_id": str(expense.id)})

    if _wants_json(request):
        return JsonResponse(
            {
                "success": True,
                "remaining_amount": float(debt.remaining_amount),
                "status": debt.get_status_display(),
                "next_payment_date": debt.next_payment_date.isoformat() if debt.next_payment_date else None,
            }
        )
    messages.success(request, "Debt payment recorded.")
    return redirect("finance:debt_detail", debt_id=debt.id)


def _financial_year_for_day(day):
    start_year = day.year if day.month >= 4 else day.year - 1
    return f"{start_year}-{start_year + 1}"


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def taxes(request):
    today = timezone.localdate()
    tax_records = TaxRecord.objects.filter(user=request.user).order_by("-financial_year", "-created_at")
    year_filter = request.GET.get("year") or ""
    if year_filter:
        tax_records = tax_records.filter(financial_year=year_filter)

    form = TaxRecordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        tax_record = form.save(commit=False)
        tax_record.user = request.user
        tax_record.is_filed = bool(tax_record.filed_date)
        tax_record.is_paid = tax_record.tax_due <= 0
        tax_record.save()
        _notify(request.user, "Tax record added", f"{tax_record.get_tax_type_display()} for FY {tax_record.financial_year} is now tracked.", category="SYSTEM", severity="INFO")
        _audit(request.user, "FINANCE_TAX_RECORD_CREATED", f"Created tax record {tax_record.financial_year}", metadata={"tax_record_id": str(tax_record.id)})
        messages.success(request, "Tax record added.")
        return redirect("finance:taxes")

    stats = {
        "total": tax_records.count(),
        "total_taxable": tax_records.aggregate(total=Sum("taxable_amount"))["total"] or Decimal("0.00"),
        "total_tax_paid": tax_records.aggregate(total=Sum("tax_paid"))["total"] or Decimal("0.00"),
        "total_tax_due": tax_records.aggregate(total=Sum("tax_due"))["total"] or Decimal("0.00"),
        "filed": tax_records.filter(is_filed=True).count(),
        "overdue": sum(1 for record in tax_records if record.is_overdue),
    }
    yearly_breakdown = [
        {
            "financial_year": row["financial_year"],
            "taxable_amount": row["taxable"],
            "tax_paid": row["paid"],
            "tax_due": row["due"],
            "count": row["count"],
        }
        for row in tax_records.values("financial_year").annotate(taxable=Sum("taxable_amount"), paid=Sum("tax_paid"), due=Sum("tax_due"), count=Count("id")).order_by("-financial_year")
    ]
    upcoming_deadlines = []
    for record in tax_records:
        if record.tax_due > 0 and record.due_date >= today - timedelta(days=30):
            upcoming_deadlines.append({"title": record.get_tax_type_display(), "date": record.due_date, "days_remaining": (record.due_date - today).days})
    return render(
        request,
        "finance/taxes.html",
        {
            "tax_records": tax_records,
            "form": form,
            "stats": stats,
            "yearly_breakdown": yearly_breakdown,
            "tax_savings": _safe_engine_call("identify_tax_savings", {"total_potential": Decimal("0.00"), "opportunities": []}, request.user),
            "upcoming_deadlines": upcoming_deadlines[:5],
            "year_filter": year_filter,
            "financial_years": sorted(set(tax_records.values_list("financial_year", flat=True)), reverse=True),
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def tax_calculator(request):
    today = timezone.localdate()
    current_fy = _financial_year_for_day(today)
    previous_fy = _financial_year_for_day(today.replace(year=today.year - 1))
    previous_year_tax = TaxRecord.objects.filter(user=request.user, financial_year=previous_fy).first()

    if request.method == "POST":
        income = _decimal(request.POST.get("income"))
        deductions = _decimal(request.POST.get("deductions"))
        investments_amount = _decimal(request.POST.get("investments"))
        tax_regime = (request.POST.get("tax_regime") or "NEW").upper()
        tax_amount = _safe_engine_call("calculate_tax", Decimal("0.00"), income, deductions, investments_amount, regime=tax_regime)
        recommendations = _safe_engine_call("get_tax_saving_recommendations", [], income, investments_amount)
        if _wants_json(request):
            return JsonResponse(
                {
                    "success": True,
                    "calculation": {"tax_amount": float(tax_amount), "tax_regime": tax_regime},
                    "recommendations": recommendations,
                }
            )
        return render(
            request,
            "finance/tax_calculator.html",
            {
                "prev_year_tax": previous_year_tax,
                "current_year": current_fy,
                "tax_regimes": [{"value": "OLD", "label": "Old regime"}, {"value": "NEW", "label": "New regime"}],
                "result": {
                    "income": income,
                    "deductions": deductions,
                    "investments": investments_amount,
                    "tax_regime": tax_regime,
                    "tax_amount": tax_amount,
                    "recommendations": recommendations,
                },
            },
        )

    return render(
        request,
        "finance/tax_calculator.html",
        {
            "prev_year_tax": previous_year_tax,
            "current_year": current_fy,
            "tax_regimes": [{"value": "OLD", "label": "Old regime"}, {"value": "NEW", "label": "New regime"}],
        },
    )


@login_required
@role_required(ROLE_OWNER_FINANCE)
def import_csv(request):
    organization = _active_org(request)
    form = ImportCSVForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        csv_file = form.cleaned_data["csv_file"]
        data_type = form.cleaned_data["data_type"]
        has_headers = form.cleaned_data["has_headers"]
        date_format = form.cleaned_data["date_format"]
        content = csv_file.read().decode("utf-8-sig")
        stream = io.StringIO(content)
        if has_headers:
            reader = csv.DictReader(stream)
        else:
            rows = csv.reader(stream)
            if data_type == "BOTH":
                messages.error(request, "Mixed imports require headers with a type column.")
                return redirect("finance:import_csv")
            headers = {
                "INCOME": ["date", "source", "amount", "category", "description", "reference", "verified"],
                "EXPENSE": ["date", "description", "amount", "category", "payment_method", "merchant", "location", "verified"],
            }[data_type]
            reader = (dict(zip(headers, row)) for row in rows)

        finance_account = _resolve_finance_account(request.user, organization=organization, create_if_missing=True)
        imported_count = 0
        errors = []
        for row_number, row in enumerate(reader, start=2 if has_headers else 1):
            normalized = {(key or "").strip().lower(): (value.strip() if isinstance(value, str) else value) for key, value in row.items()}
            row_type = data_type if data_type != "BOTH" else (normalized.get("type") or "").upper()
            try:
                raw_date = normalized.get("date") or timezone.localdate().strftime(date_format)
                parsed_date = datetime.strptime(raw_date, date_format).date()
                amount = _decimal(normalized.get("amount"))
                if amount <= 0:
                    raise ValueError("Amount must be greater than zero.")
                if row_type == "INCOME":
                    Income.objects.create(
                        user=request.user,
                        organization=organization,
                        account=finance_account,
                        source=normalized.get("source") or "Imported income",
                        amount=amount,
                        category=(normalized.get("category") or "OTHER").upper(),
                        date=parsed_date,
                        description=normalized.get("description") or "",
                        invoice_number=normalized.get("reference") or "",
                        is_verified=(normalized.get("verified") or "true").lower() in {"true", "1", "yes"},
                    )
                elif row_type == "EXPENSE":
                    category = (normalized.get("category") or "").upper() or _safe_engine_call("auto_categorize_expense", "OTHER", normalized.get("description") or "")
                    expense = Expense.objects.create(
                        user=request.user,
                        organization=organization,
                        account=finance_account,
                        description=normalized.get("description") or "Imported expense",
                        amount=amount,
                        category=category if category in EXPENSE_CATEGORY_LABELS else "OTHER",
                        custom_category=None if category in EXPENSE_CATEGORY_LABELS else category.title(),
                        date=parsed_date,
                        payment_method=(normalized.get("payment_method") or "CASH").upper(),
                        merchant=normalized.get("merchant") or "",
                        location=normalized.get("location") or "",
                        is_verified=(normalized.get("verified") or "true").lower() in {"true", "1", "yes"},
                    )
                    linked_category = _sync_budget_category_for_expense(expense, request.user)
                    _refresh_budget_totals(linked_category)
                else:
                    raise ValueError("Type must be INCOME or EXPENSE.")
                imported_count += 1
            except Exception as exc:
                errors.append(f"Row {row_number}: {exc}")

        if imported_count:
            _safe_update_metrics(request.user)
            _audit(request.user, "FINANCE_DATA_IMPORTED", f"Imported {imported_count} finance rows", metadata={"count": imported_count, "errors": len(errors)})
            messages.success(request, f"Imported {imported_count} rows into Finance.")
        else:
            messages.warning(request, "No rows were imported.")
        if errors:
            messages.warning(request, "; ".join(errors[:5]))
        return redirect("finance:transaction_center")

    templates = {
        "income": ["date", "source", "amount", "category", "description", "reference", "verified"],
        "expense": ["date", "description", "amount", "category", "payment_method", "merchant", "location", "verified"],
        "mixed": ["type", "date", "description_or_source", "amount", "category", "payment_method", "merchant", "verified"],
    }
    return render(request, "finance/import_data.html", {"form": form, "templates": templates})


@login_required
@role_required(ROLE_OWNER_FINANCE)
def export_data(request):
    export_type = (request.GET.get("type") or "expenses").lower()
    format_type = (request.GET.get("format") or "csv").lower()
    organization = _active_org(request)
    end_date = _parse_date(request.GET.get("date_to")) or timezone.localdate()
    start_date = _parse_date(request.GET.get("date_from")) or (end_date - timedelta(days=30))

    expenses = _scoped_queryset(Expense.objects.filter(user=request.user, date__range=[start_date, end_date]), organization).order_by("date", "created_at")
    incomes = _scoped_queryset(Income.objects.filter(user=request.user, date__range=[start_date, end_date]), organization).order_by("date", "created_at")

    if format_type not in {"csv", "json"}:
        return HttpResponseBadRequest("Unsupported export format.")

    if format_type == "json":
        payload = []
        if export_type in {"expenses", "all"}:
            payload.extend(
                {
                    "type": "expense",
                    "date": expense.date.isoformat(),
                    "description": expense.description,
                    "category": expense.get_category_display(),
                    "amount": float(expense.amount),
                    "payment_method": expense.payment_method,
                    "merchant": expense.merchant,
                }
                for expense in expenses
            )
        if export_type in {"income", "all"}:
            payload.extend(
                {
                    "type": "income",
                    "date": income.date.isoformat(),
                    "source": income.source,
                    "category": _income_category_label(income.category),
                    "amount": float(income.amount),
                    "description": income.description,
                }
                for income in incomes
            )
        response = HttpResponse(json.dumps(payload, indent=2), content_type="application/json")
        response["Content-Disposition"] = f'attachment; filename="finance_{export_type}_{start_date}_{end_date}.json"'
        return response

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="finance_{export_type}_{start_date}_{end_date}.csv"'
    writer = csv.writer(response)
    if export_type == "income":
        writer.writerow(["Date", "Source", "Category", "Amount", "Description", "Verified"])
        for income in incomes:
            writer.writerow([income.date, income.source, _income_category_label(income.category), income.amount, income.description, "Yes" if income.is_verified else "No"])
        return response
    if export_type == "expenses":
        writer.writerow(["Date", "Description", "Category", "Amount", "Payment Method", "Merchant", "Verified"])
        for expense in expenses:
            writer.writerow([expense.date, expense.description, expense.get_category_display(), expense.amount, expense.get_payment_method_display(), expense.merchant or "", "Yes" if expense.is_verified else "No"])
        return response

    writer.writerow(["Type", "Date", "Description", "Category", "Amount", "Details", "Verified"])
    for expense in expenses:
        writer.writerow(["Expense", expense.date, expense.description, expense.get_category_display(), expense.amount, expense.get_payment_method_display(), expense.merchant or "", "Yes" if expense.is_verified else "No"])
    for income in incomes:
        writer.writerow(["Income", income.date, income.source, _income_category_label(income.category), income.amount, income.description or "", "Yes" if income.is_verified else "No"])
    return response


@login_required
@role_required(ROLE_OWNER_FINANCE)
def sync_payments(request):
    result = _safe_engine_call("sync_with_payments_core", {"synced_count": 0, "errors": [], "success": False}, request.user)
    synced_count = result.get("synced_count", 0) if isinstance(result, dict) else int(result or 0)
    errors = result.get("errors", []) if isinstance(result, dict) else []
    if synced_count:
        _notify(request.user, "Payments synced", f"{synced_count} payment records were posted into Finance.", category="TRANSACTION", severity="SUCCESS")
        _audit(request.user, "FINANCE_PAYMENTS_SYNCED", f"Synced {synced_count} payments", metadata={"synced_count": synced_count})
        messages.success(request, f"Synced {synced_count} payment records.")
    elif errors:
        messages.warning(request, errors[0])
    else:
        messages.info(request, "No new payment records were ready to sync.")
    return _redirect_back(request, "finance:finance_dashboard")


@login_required
@role_required(ROLE_OWNER_FINANCE)
def sync_with_autopilot(request):
    organization = _active_org(request)
    result = _safe_engine_call("sync_with_autopilot", {"synced_count": 0, "bills_created": 0, "alerts_created": 0}, request.user)
    synced_goals = 0
    for goal in FinancialGoal.objects.filter(user=request.user, status__in=["PLANNING", "IN_PROGRESS", "ACHIEVED"]):
        if _sync_goal_to_autopilot(goal) is not None:
            synced_goals += 1
    if AutopilotProfile is not None:
        profile, _ = AutopilotProfile.resolve_for_user(request.user, organization=organization)
        monthly_budget = sum((budget.amount for budget in Budget.objects.filter(user=request.user, is_active=True)), Decimal("0.00"))
        profile.monthly_budget = monthly_budget
        profile.save(update_fields=["monthly_budget", "updated_at"])

    synced_count = result.get("synced_count", 0) if isinstance(result, dict) else 0
    alerts_created = result.get("alerts_created", 0) if isinstance(result, dict) else 0
    if synced_count or synced_goals:
        _notify(request.user, "Autopilot synced", "Finance budgets, goals, and alerts were refreshed for Autopilot.", category="SYSTEM", severity="INFO")
        _audit(request.user, "FINANCE_AUTOPILOT_SYNCED", "Synced Finance with Autopilot", metadata={"synced_count": synced_count, "synced_goals": synced_goals, "alerts_created": alerts_created})
        messages.success(request, f"Autopilot sync complete. {synced_goals} goals refreshed and {alerts_created} alerts created.")
    else:
        messages.info(request, "Autopilot already has the latest Finance state.")
    return _redirect_back(request, "finance:finance_dashboard")


@login_required
@require_GET
@role_required(ROLE_OWNER_FINANCE_OPS)
def get_chart_data(request):
    chart_type = request.GET.get("type", "monthly")
    months = int(request.GET.get("months", 6))
    data = _safe_engine_call("get_chart_data", None, request.user, chart_type=chart_type, months=months)
    if data is None:
        points = _build_monthly_series(request.user, _active_org(request), months=months)
        data = {
            "labels": [point["label"] for point in points],
            "income": [float(point["income"]) for point in points],
            "expense": [float(point["expense"]) for point in points],
        }
    return JsonResponse({"success": True, "data": data, "chart_type": chart_type, "months": months})


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def account_settings(request):
    organization = _active_org(request)
    account = _resolve_finance_account(request.user, organization=organization, create_if_missing=True)
    payment_account = _resolve_payment_account(request.user, organization=organization, create_if_missing=False)

    if request.method == "POST":
        account.name = (request.POST.get("name") or account.name).strip()
        account.account_type = request.POST.get("account_type") or account.account_type
        account.currency = request.POST.get("currency") or account.currency
        account.color = request.POST.get("color") or account.color
        account.include_in_total = str(request.POST.get("include_in_total", "")).lower() in {"1", "true", "on", "yes"}
        metadata = account.metadata if isinstance(account.metadata, dict) else {}
        metadata["tax_year"] = request.POST.get("tax_year") or metadata.get("tax_year") or _financial_year_for_day(timezone.localdate())
        metadata["default_budget_period"] = request.POST.get("default_budget_period") or metadata.get("default_budget_period") or "MONTHLY"
        metadata["default_report_type"] = request.POST.get("default_report_type") or metadata.get("default_report_type") or "MONTHLY"
        metadata["notifications"] = {
            "budget_alerts": str(request.POST.get("budget_alerts", "")).lower() in {"1", "true", "on", "yes"},
            "goal_alerts": str(request.POST.get("goal_alerts", "")).lower() in {"1", "true", "on", "yes"},
            "transaction_alerts": str(request.POST.get("transaction_alerts", "")).lower() in {"1", "true", "on", "yes"},
            "report_alerts": str(request.POST.get("report_alerts", "")).lower() in {"1", "true", "on", "yes"},
        }
        account.metadata = metadata
        account.save()
        try:
            account.update_balance()
        except Exception:
            logger.exception("Unable to refresh account balance after settings update")
        _audit(request.user, "FINANCE_ACCOUNT_SETTINGS_UPDATED", f"Updated settings for {account.name}", metadata={"account_id": str(account.id)})
        messages.success(request, "Finance settings updated.")
        return redirect("finance:account_settings")

    currencies = [
        ("INR", "Indian Rupee"),
        ("USD", "US Dollar"),
        ("EUR", "Euro"),
        ("GBP", "British Pound"),
    ]
    return render(
        request,
        "finance/account_settings.html",
        {
            "account": account,
            "payment_account": payment_account,
            "account_types": Account.ACCOUNT_TYPES,
            "currencies": currencies,
            "budget_periods": Budget.PERIOD_CHOICES,
            "report_types": FinancialReport.REPORT_TYPES,
            "notification_settings": (account.metadata or {}).get("notifications", {}),
        },
    )



