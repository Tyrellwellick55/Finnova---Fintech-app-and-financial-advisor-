import logging
import json
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum, Q
from django.utils import timezone

from finance.models import (
    Income,
    Expense,
    Budget,
    FinancialGoal,
    FinancialMetric,
    Investment,
    Debt,
)

logger = logging.getLogger(__name__)


class FinanceEngine:
    """
    Core financial calculation/analytics engine used across the finance app.

    This implementation focuses on:
    - Keeping method signatures consistent with the rest of the project
    - Returning safe, well‑structured data for templates and APIs
    - Avoiding crashes by failing softly and logging problems
    """

    # ------------------------------------------------------------------
    # Core summaries
    # ------------------------------------------------------------------
    @classmethod
    def calculate_monthly_summary(cls, user, year: int, month: int):
        """
        Calculate income/expense summary for a specific month.

        Used by:
        - `finance.views.finance_dashboard`
        - `finance.api.IncomeViewSet.monthly_summary`
        - Wallet intelligence helpers
        """
        # Determine period bounds
        start_date = date(year, month, 1)
        end_date = date(year, month, monthrange(year, month)[1])

        incomes_qs = Income.objects.filter(
            user=user,
            date__range=(start_date, end_date),
        )
        expenses_qs = Expense.objects.filter(
            user=user,
            date__range=(start_date, end_date),
        )

        total_income = (
            incomes_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        )
        total_expense = (
            expenses_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        )
        savings = total_income - total_expense
        savings_rate = float(
            (savings / total_income * 100) if total_income > 0 else 0.0
        )

        return {
            "period": {
                "year": year,
                "month": month,
                "start_date": start_date,
                "end_date": end_date,
            },
            "totals": {
                "income": total_income,
                "expense": total_expense,
                "savings": savings,
                "savings_rate": round(savings_rate, 2),
            },
            "transaction_counts": {
                "income": incomes_qs.count(),
                "expense": expenses_qs.count(),
            },
        }

    @classmethod
    def calculate_financial_health(cls, user, lookback_days: int = 90):
        """
        Compute a simple financial health breakdown for a user.

        Returns scores between 0 and 100 for:
        - savings_score
        - expense_score
        - emergency_score
        - debt_score
        - overall_score (average)
        """
        today = timezone.now().date()
        start_date = today - timedelta(days=lookback_days)

        incomes_qs = Income.objects.filter(user=user, date__gte=start_date)
        expenses_qs = Expense.objects.filter(user=user, date__gte=start_date)

        total_income = (
            incomes_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        )
        total_expense = (
            expenses_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        )

        # Savings score – higher savings rate => better score
        if total_income > 0:
            raw_savings_rate = float((total_income - total_expense) / total_income * 100)
        else:
            raw_savings_rate = 0.0
        savings_score = max(0.0, min(100.0, raw_savings_rate))

        # Expense score – lower expense/income ratio => better
        if total_income > 0:
            expense_ratio = float(total_expense / total_income)
        else:
            expense_ratio = 1.0
        expense_score = max(
            0.0, min(100.0, (1.0 - min(expense_ratio, 1.5) / 1.5) * 100)
        )

        # Emergency score – do we have at least 3 months of savings?
        monthly_expense = (
            total_expense / (Decimal(lookback_days) / Decimal(30)) if lookback_days > 0 else Decimal('0')
        )
        total_savings = total_income - total_expense
        required_emergency_fund = Decimal(monthly_expense) * 3
        if required_emergency_fund > 0:
            emergency_ratio = float(total_savings / required_emergency_fund)
            emergency_score = max(
                0.0, min(100.0, min(emergency_ratio, 1.0) * 100.0)
            )
        else:
            emergency_score = 50.0  # neutral default

        # Debt score – lower debt / annual income => better
        total_debt = (
            Debt.objects.filter(user=user)
            .aggregate(total=Sum("remaining_amount"))["total"]
            or Decimal("0.00")
        )
        annual_income = total_income * Decimal(str(365.0 / max(lookback_days, 1)))
        if annual_income > 0:
            debt_ratio = float(total_debt / annual_income)
            debt_score = max(
                0.0, min(100.0, (1.0 - min(debt_ratio, 2.0) / 2.0) * 100)
            )
        else:
            debt_score = 50.0

        overall_score = round(
            (savings_score + expense_score + emergency_score + debt_score) / 4.0, 2
        )

        return {
            "overall_score": overall_score,
            "savings_score": round(savings_score, 2),
            "expense_score": round(expense_score, 2),
            "emergency_score": round(emergency_score, 2),
            "debt_score": round(debt_score, 2),
        }

    # ------------------------------------------------------------------
    # Budget & goals helpers
    # ------------------------------------------------------------------
    @classmethod
    def update_budget_spending(cls, user):
        """
        Recalculate `current_spending` for all of a user's active budgets.

        Returns the number of budgets updated.
        """
        budgets = Budget.objects.filter(user=user, is_active=True)
        updated = 0
        for budget in budgets:
            budget.update_spending()
            updated += 1
        return updated

    @classmethod
    def update_financial_goals(cls, user):
        """
        Force a save on all goals so that their calculated fields
        (like `progress_percentage`) stay in sync.

        Returns the number of goals updated.
        """
        goals = FinancialGoal.objects.filter(user=user)
        count = 0
        for goal in goals:
            goal.save()
            count += 1
        return count

    # ------------------------------------------------------------------
    # Analytics & predictions
    # ------------------------------------------------------------------
    @classmethod
    def detect_spending_patterns(cls, user, start_or_lookback=90, end_date=None, **kwargs):
        """
        Lightweight 'pattern detection' used by the analytics page.

        Returns a list of pattern dicts with keys:
        - type
        - description
        - details (optional list of simple objects)
        - suggestion (optional string)
        """
        today = timezone.now().date()

        # Compatibility:
        # - detect_spending_patterns(user, 90)
        # - detect_spending_patterns(user, start_date, end_date)
        # - detect_spending_patterns(user, lookback_days=90)
        if "lookback_days" in kwargs:
            start_or_lookback = kwargs["lookback_days"]

        if hasattr(start_or_lookback, "year") and hasattr(start_or_lookback, "month"):
            start_date = start_or_lookback
            if hasattr(start_date, "date"):
                start_date = start_date.date()
            end_date = end_date or today
            if hasattr(end_date, "date"):
                end_date = end_date.date()
        else:
            lookback_days = int(start_or_lookback or 90)
            start_date = today - timedelta(days=lookback_days)
            end_date = today

        expenses = (
            Expense.objects.filter(user=user, date__gte=start_date, date__lte=end_date)
            .order_by("-date")
            .values("date", "amount", "category")
        )

        if not expenses:
            return []

        total_expense = sum((e["amount"] for e in expenses), Decimal("0.00"))
        days = max(1, (end_date - start_date).days + 1)
        avg_daily = total_expense / days

        patterns = []

        # Pattern 1: High single‑day spikes
        recent_expenses = list(expenses)[:10]
        spike_threshold = avg_daily * Decimal("2.0")
        spikes = [e for e in recent_expenses if e["amount"] > spike_threshold]
        if spikes:
            patterns.append(
                {
                    "type": "spending_spike",
                    "description": "We noticed some unusually high spending days.",
                    "details": [
                        {"date": s["date"], "amount": s["amount"]} for s in spikes
                    ],
                    "suggestion": "Review these transactions and ensure they were expected.",
                }
            )

        # Pattern 2: Top categories
        category_totals = (
            Expense.objects.filter(user=user, date__gte=start_date, date__lte=end_date)
            .values("category")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:5]
        )
        if category_totals:
            patterns.append(
                {
                    "type": "category_focus",
                    "description": "Your top spending categories this period.",
                    "details": [
                        {"category": c["category"], "amount": c["total"]}
                        for c in category_totals
                    ],
                    "suggestion": "Consider setting budgets for your top categories to keep them under control.",
                }
            )

        return patterns

    @classmethod
    def predict_future_expenses(
        cls,
        user,
        lookback_months: int = 3,
        days: int | None = None,
        include_seasonality: bool = False,
        **kwargs,
    ):
        """
        Simple forecast based on the average of the last few months.

        Returns a dict consumed by templates:
        - predicted_daily
        - predicted_weekly
        - predicted_monthly
        - confidence (0..1)
        - message
        """
        today = timezone.now().date()
        if kwargs.get("lookback_months"):
            lookback_months = int(kwargs["lookback_months"])

        monthly_totals = []
        for i in range(lookback_months):
            month_date = (today.replace(day=1) - timedelta(days=30 * i))
            start = month_date.replace(day=1)
            end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

            total = (
                Expense.objects.filter(
                    user=user,
                    date__gte=start,
                    date__lte=end,
                ).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            monthly_totals.append(total)

        if not any(monthly_totals):
            empty = {
                "predicted_daily": Decimal("0.00"),
                "predicted_weekly": Decimal("0.00"),
                "predicted_monthly": Decimal("0.00"),
                "income": Decimal("0.00"),
                "expenses": Decimal("0.00"),
                "savings": Decimal("0.00"),
                "savings_rate": Decimal("0.00"),
                "income_growth": 0.0,
                "expense_growth": 0.0,
                "chart_data": json.dumps(
                    {
                        "labels": ["Week 1", "Week 2", "Week 3", "Week 4"],
                        "historical": [0, 0, 0, 0],
                        "predicted": [0, 0, 0, 0],
                    }
                ),
                "confidence": 0.2,
                "message": "Not enough data yet to make a reliable forecast.",
            }
            return empty

        avg_monthly = sum(monthly_totals) / len(monthly_totals)
        predicted_monthly = avg_monthly
        predicted_daily = predicted_monthly / Decimal("30.0")
        predicted_weekly = predicted_daily * Decimal("7.0")

        # Rough confidence: more months with non‑zero data => more confidence
        non_zero_months = sum(1 for m in monthly_totals if m > 0)
        confidence = min(1.0, non_zero_months / float(lookback_months))

        current_month_income = (
            Income.objects.filter(user=user, date__year=today.year, date__month=today.month)
            .aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        income_growth = 0.0
        if current_month_income > 0:
            income_growth = float(
                ((current_month_income - predicted_monthly) / current_month_income) * 100
            )

        if len(monthly_totals) >= 2 and monthly_totals[-2] > 0:
            expense_growth = float(
                ((monthly_totals[-1] - monthly_totals[-2]) / monthly_totals[-2]) * 100
            )
        else:
            expense_growth = 0.0

        savings_amount = max(current_month_income - predicted_monthly, Decimal("0.00"))
        savings_rate = (
            (savings_amount / current_month_income) * 100 if current_month_income > 0 else Decimal("0.00")
        )

        prediction_payload = {
            "predicted_daily": predicted_daily,
            "predicted_weekly": predicted_weekly,
            "predicted_monthly": predicted_monthly,
            "income": current_month_income,
            "expenses": predicted_monthly,
            "savings": savings_amount,
            "savings_rate": round(savings_rate, 2),
            "income_growth": round(income_growth, 2),
            "expense_growth": round(expense_growth, 2),
            "chart_data": json.dumps(
                {
                    "labels": ["Week 1", "Week 2", "Week 3", "Week 4"],
                    "historical": [float(predicted_monthly / 4)] * 4,
                    "predicted": [float(predicted_monthly / 4)] * 4,
                }
            ),
            "confidence": round(confidence, 2),
            "message": "Based on your recent history, this is an approximate forecast of your upcoming expenses.",
        }
        if include_seasonality:
            prediction_payload["seasonality"] = {
                "enabled": True,
                "signal": "stable",
            }
        if days is not None:
            prediction_payload["horizon_days"] = int(days)
        return prediction_payload

    @classmethod
    def generate_financial_report(
        cls, user, report_type: str, start_date: date, end_date: date
    ):
        """
        Generate a simple report data structure used by `finance.views.reports`.

        The return dict may contain:
        - totals
        - income_breakdown
        - expense_breakdown
        - daily_trends
        - insights
        - recommendations
        """
        incomes = Income.objects.filter(
            user=user, date__range=(start_date, end_date)
        )
        expenses = Expense.objects.filter(
            user=user, date__range=(start_date, end_date)
        )

        total_income = incomes.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        total_expense = (
            expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        )

        daily_trends = []
        current = start_date
        while current <= end_date:
            day_income = (
                incomes.filter(date=current).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            day_expense = (
                expenses.filter(date=current).aggregate(total=Sum("amount"))["total"]
                or Decimal("0.00")
            )
            daily_trends.append(
                {
                    "date": current.isoformat(),
                    "income": float(day_income),
                    "expense": float(day_expense),
                    "savings": float(day_income - day_expense),
                }
            )
            current += timedelta(days=1)

        income_breakdown = list(
            incomes.values("category").annotate(total=Sum("amount")).order_by("-total")
        )
        expense_breakdown = list(
            expenses.values("category").annotate(total=Sum("amount")).order_by("-total")
        )

        insights = []
        recommendations = []

        if total_income > 0:
            savings_rate = float((total_income - total_expense) / total_income * 100)
            if savings_rate < 10:
                insights.append(
                    "Your savings rate is low. Consider reviewing high‑expense categories."
                )
                recommendations.append(
                    "Set strict budgets for your top 2–3 spending categories."
                )
            elif savings_rate > 30:
                insights.append("You maintain a strong savings rate this period.")
                recommendations.append(
                    "Consider directing more savings towards long‑term investments."
                )

        return {
            "totals": {
                "income": total_income,
                "expense": total_expense,
                "savings": total_income - total_expense,
            },
            "income_breakdown": income_breakdown,
            "expense_breakdown": expense_breakdown,
            "daily_trends": daily_trends,
            "insights": insights,
            "recommendations": recommendations,
        }

    @classmethod
    def generate_daily_metrics(cls, user):
        """Record a few lightweight daily financial metrics using the current model schema."""
        today = timezone.now().date()
        if FinancialMetric.objects.filter(user=user, recorded_date=today).exists():
            return False

        month_start = today.replace(day=1)
        incomes_month = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        expenses_month = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        savings_value = incomes_month - expenses_month
        savings_rate = Decimal("0.00")
        if incomes_month > 0:
            savings_rate = (savings_value / incomes_month) * Decimal("100")
        expense_ratio = Decimal("0.00")
        if incomes_month > 0:
            expense_ratio = (expenses_month / incomes_month) * Decimal("100")

        FinancialMetric.record_metric(
            user=user,
            metric_type='CASH_FLOW',
            value=savings_value,
            period_start=month_start,
            period_end=today,
        )
        FinancialMetric.record_metric(
            user=user,
            metric_type='SAVINGS_RATE',
            value=savings_rate,
            period_start=month_start,
            period_end=today,
        )
        FinancialMetric.record_metric(
            user=user,
            metric_type='EXPENSE_RATIO',
            value=expense_ratio,
            period_start=month_start,
            period_end=today,
        )
        return True

    # ------------------------------------------------------------------
    # Payments / integrations
    # ------------------------------------------------------------------
    @classmethod
    def sync_with_payments_core(cls, user, days_back=30):
        """Sync financial data with payments_core using the shared bridge service."""
        try:
            from payments_core.models import PaymentTransaction
            from payments_core.services import PaymentFinanceBridge

            since_date = timezone.now() - timedelta(days=days_back)
            payments = (
                PaymentTransaction.objects.filter(
                    account__user=user,
                    transaction_date__gte=since_date,
                    status="SUCCESS",
                )
                .select_related('payment_intent', 'account')
                .order_by('-transaction_date')
            )

            synced_count = 0
            errors = []
            for payment in payments:
                try:
                    if PaymentFinanceBridge.is_transaction_synced(user, payment):
                        continue
                    synced_obj = PaymentFinanceBridge.sync_transaction(user, payment)
                    if synced_obj is not None:
                        synced_count += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Payment {payment.reference}: {exc}")

            if synced_count > 0:
                logger.info("Synced %s payments for user %s", synced_count, user.username)
                try:
                    from notifications.services import create_notification

                    create_notification(
                        user=user,
                        title="Payments Synced",
                        message=f"Successfully synced {synced_count} recent payments",
                        notification_type="SYNC",
                        priority="LOW",
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("Failed to send sync notification for user %s", user.id)

            return {"synced_count": synced_count, "errors": errors, "success": True}
        except ImportError:
            logger.warning("payments_core module not available for sync")
            return {
                "synced_count": 0,
                "errors": ["Payments module not available"],
                "success": False,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Payment sync error: %s", exc, exc_info=True)
            return {"synced_count": 0, "errors": [str(exc)], "success": False}

    @classmethod
    def identify_tax_savings(cls, user):
        """
        Identify potential tax saving opportunities based on user's financial profile.
        Checks for Section 80C, 80D usage.
        """
        # Calculate current investments eligible for 80C
        # (This is a simplified logic looking at specific investment types)
        investments_80c = Investment.objects.filter(
            user=user,
            instrument__in=['PPF', 'NPS', 'ELSS', 'FD', 'LIC'],  # Assuming these map to 80C instruments
            status='ACTIVE'
        ).aggregate(total=Sum('invested_amount'))['total'] or Decimal('0.00')

        limit_80c = Decimal('150000.00')
        gap_80c = max(Decimal('0.00'), limit_80c - investments_80c)

        opportunities = []
        if gap_80c > 0:
            opportunities.append({
                'section': '80C',
                'description': 'Invest in PPF, ELSS, or Tax-Saver FDs',
                'max_limit': limit_80c,
                'current_investment': investments_80c,
                'potential_saving': gap_80c,
                'action_url': '/finance/investments/new/'
            })

        # Placeholder for 80D (Health Insurance)
        # In a real app, we would check expense categories or a specific insurance model
        opportunities.append({
            'section': '80D',
            'description': 'Health Insurance Premiums',
            'max_limit': Decimal('25000.00'),
            'current_investment': Decimal('0.00'),  # Needs specific tracking
            'potential_saving': Decimal('25000.00'),
            'action_url': '/finance/expenses/add/?category=INSURANCE'
        })

        total_potential = sum((op['potential_saving'] for op in opportunities), Decimal('0.00'))

        return {
            'total_potential': total_potential,
            'opportunities': opportunities
        }

    @classmethod
    def calculate_tax(cls, income, deductions, investments, regime='NEW'):
        """
        Calculate income tax based on simplified Indian tax slabs (FY 2024-25).
        """
        taxable_income = max(Decimal('0.00'), income - deductions)
        tax = Decimal('0.00')

        if regime == 'NEW':
            # New Regime Slabs (FY 2024-25)
            # 0-3L: Nil
            # 3-7L: 5%
            # 7-10L: 10%
            # 10-12L: 15%
            # 12-15L: 20%
            # >15L: 30%
            # Standard Deduction: 75,000 (assumed handled in deductions or applied here if mostly salary)
            
            # Simplified calculation
            slabs = [
                (Decimal('300000'), Decimal('0.00')),
                (Decimal('400000'), Decimal('0.05')),  # 3L to 7L (4L gap)
                (Decimal('300000'), Decimal('0.10')),  # 7L to 10L (3L gap)
                (Decimal('200000'), Decimal('0.15')),  # 10L to 12L (2L gap)
                (Decimal('300000'), Decimal('0.20')),  # 12L to 15L (3L gap)
                (None, Decimal('0.30')),               # > 15L
            ]
            
            remaining_income = taxable_income
            threshold = Decimal('300000') # 0-3L is exempt
            remaining_income -= threshold
            
            if remaining_income > 0:
                for slab_size, rate in slabs[1:]: # Skip first exempt slab
                    if slab_size is None: # Last slab
                        tax += remaining_income * rate
                        break
                    
                    taxable_at_this_slab = min(remaining_income, slab_size)
                    tax += taxable_at_this_slab * rate
                    remaining_income -= taxable_at_this_slab
                    
                    if remaining_income <= 0:
                        break
            
            # Rebate u/s 87A for income up to 7L
            if taxable_income <= Decimal('700000'):
                tax = Decimal('0.00')

        else:
            # Old Regime Slabs (Generic)
            # 0-2.5L: Nil
            # 2.5-5L: 5%
            # 5-10L: 20%
            # >10L: 30%
            
            slabs = [
                (Decimal('250000'), Decimal('0.00')),
                (Decimal('250000'), Decimal('0.05')),
                (Decimal('500000'), Decimal('0.20')),
                (None, Decimal('0.30')),
            ]
            
            remaining_income = taxable_income  - investments # Investments deduction (80C etc) applicable in Old Regime
            remaining_income = max(Decimal('0.00'), remaining_income) # Cannot go negative
            
            if remaining_income > 250000:
                remaining_income -= 250000
                taxable_income_calc = remaining_income
                
                # 2.5L to 5L
                slab_amount = min(taxable_income_calc, Decimal('250000'))
                tax += slab_amount * Decimal('0.05')
                taxable_income_calc -= slab_amount
                
                if taxable_income_calc > 0:
                     # 5L to 10L
                    slab_amount = min(taxable_income_calc, Decimal('500000'))
                    tax += slab_amount * Decimal('0.20')
                    taxable_income_calc -= slab_amount
                    
                    if taxable_income_calc > 0:
                         # > 10L
                        tax += taxable_income_calc * Decimal('0.30')

            # Rebate u/s 87A for income up to 5L
            if (taxable_income - investments) <= Decimal('500000'):
                tax = Decimal('0.00')

        return tax.quantize(Decimal('0.01'))

    @classmethod
    def get_tax_saving_recommendations(cls, income, current_investments):
        """
        Get recommendations for tax saving based on income.
        """
        recommendations = []
        # Basic logical recommendations
        if income > Decimal('700000'): # New regime threshold
             recommendations.append("Consider comparing New vs Old regime benefits.")
        
        limit_80c = Decimal('150000')
        if current_investments < limit_80c:
            gap = limit_80c - current_investments
            recommendations.append(f"Invest ₹{gap} more in 80C instruments (PPF, ELSS) to maximize deductions.")
            
        return recommendations

    @classmethod
    def sync_with_payments(cls, user, days_back=30):
        """
        Backwards‑compatible helper used by `finance.views.sync_payments`,
        which expects a simple integer count.
        """
        result = cls.sync_with_payments_core(user, days_back)
        if isinstance(result, dict):
            return int(result.get("synced_count", 0))
        return 0

    # ------------------------------------------------------------------
    # AI insights wrapper
    # ------------------------------------------------------------------
    @classmethod
    def generate_ai_insights(cls, user, period_days=30):
        """Generate AI‑flavoured financial insights for the API/dashboard."""
        try:
            from analytics_ai.algorithms import (
                detect_budget_overrun,
                category_expense_analysis,
                financial_personality,
                generate_financial_tips,
                detect_income_opportunity,
            )

            insights = []
            today = timezone.now().date()
            start_date = today - timedelta(days=period_days)

            expenses = Expense.objects.filter(user=user, date__gte=start_date)
            incomes = Income.objects.filter(user=user, date__gte=start_date)

            # 1. Budget insights
            budgets = Budget.objects.filter(user=user, is_active=True)
            for budget in budgets:
                budget.update_spending()
                if budget.is_exceeded:
                    insights.append(
                        {
                            "type": "BUDGET_ALERT",
                            "title": f"Budget Exceeded: {budget.name}",
                            "message": f"You have exceeded your {budget.name} budget by ₹{abs(budget.remaining_amount)}",
                            "priority": "HIGH",
                            "action": "REVIEW_BUDGET",
                            "action_data": {"budget_id": budget.id},
                        }
                    )
                elif budget.is_near_limit:
                    insights.append(
                        {
                            "type": "BUDGET_WARNING",
                            "title": f"Budget Near Limit: {budget.name}",
                            "message": f"Your {budget.name} budget is {budget.usage_percentage:.1f}% used",
                            "priority": "MEDIUM",
                            "action": "MONITOR_SPENDING",
                            "action_data": {"budget_id": budget.id},
                        }
                    )

            # 2. Category spending insights
            if expenses.exists():
                try:
                    category_analysis = category_expense_analysis(expenses)
                except Exception:  # noqa: BLE001
                    category_analysis = None

                if category_analysis:
                    top_category = category_analysis[0]
                    insights.append(
                        {
                            "type": "SPENDING_PATTERN",
                            "title": "Top Spending Category",
                            "message": f"You spend the most on {top_category[0]} (₹{top_category[1]})",
                            "priority": "LOW",
                            "action": "VIEW_CATEGORY",
                            "action_data": {"category": top_category[0]},
                        }
                    )

            # 3. Financial personality
            total_income = incomes.aggregate(total=Sum("amount"))["total"] or Decimal(
                "0.00"
            )
            total_expense = (
                expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
            )

            if total_income > 0:
                savings_score = ((total_income - total_expense) / total_income) * 100
                try:
                    personality = financial_personality(savings_score)
                    tips = generate_financial_tips(savings_score)
                except Exception:  # noqa: BLE001
                    personality = "Saver"
                    tips = []

                insights.append(
                    {
                        "type": "FINANCIAL_PERSONALITY",
                        "title": f"You are a {personality}",
                        "message": f"Savings rate: {savings_score:.1f}%. {tips[0] if tips else ''}",
                        "priority": "MEDIUM",
                        "action": "VIEW_DETAILED_ANALYSIS",
                        "action_data": {
                            "personality": personality,
                            "score": float(savings_score),
                        },
                    }
                )

            # 4. Income opportunities
            try:
                opportunities = detect_income_opportunity(list(expenses), {})
                if opportunities:
                    insights.append(
                        {
                            "type": "INCOME_OPPORTUNITY",
                            "title": "Potential Income Boost",
                            "message": f"Found {len(opportunities)} ways to increase your income",
                            "priority": "LOW",
                            "action": "VIEW_OPPORTUNITIES",
                            "action_data": {"opportunities": opportunities[:3]},
                        }
                    )
            except Exception:  # noqa: BLE001
                pass

            return insights
        except Exception as exc:  # noqa: BLE001
            logger.error("AI insights generation failed: %s", exc, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Backward-compatible view helpers
    # ------------------------------------------------------------------
    @classmethod
    def get_financial_overview(cls, user, start_date, end_date, time_range="monthly"):
        """Compatibility helper used by `finance.views.financial_overview`."""
        incomes_qs = Income.objects.filter(user=user, date__range=(start_date, end_date))
        expenses_qs = Expense.objects.filter(user=user, date__range=(start_date, end_date))

        total_income = incomes_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        total_expenses = expenses_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        net_savings = total_income - total_expenses
        savings_rate = (net_savings / total_income * 100) if total_income > 0 else Decimal("0.00")

        period_days = max(1, (end_date - start_date).days + 1)
        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=period_days - 1)

        prev_income = (
            Income.objects.filter(user=user, date__range=(prev_start, prev_end)).aggregate(total=Sum("amount"))[
                "total"
            ]
            or Decimal("0.00")
        )
        prev_expenses = (
            Expense.objects.filter(user=user, date__range=(prev_start, prev_end)).aggregate(total=Sum("amount"))[
                "total"
            ]
            or Decimal("0.00")
        )
        prev_savings = prev_income - prev_expenses
        prev_savings_rate = (prev_savings / prev_income * 100) if prev_income > 0 else Decimal("0.00")

        def _growth(current, previous):
            if previous == 0:
                return 0.0 if current == 0 else 100.0
            return float(((current - previous) / abs(previous)) * 100)

        category_rows = list(
            expenses_qs.values("category").annotate(amount=Sum("amount")).order_by("-amount")
        )
        category_total = sum((row["amount"] for row in category_rows), Decimal("0.00"))
        category_breakdown = []
        for row in category_rows:
            pct = float((row["amount"] / category_total) * 100) if category_total > 0 else 0.0
            category_breakdown.append(
                {
                    "category": row["category"],
                    "amount": row["amount"],
                    "percentage": round(pct, 2),
                }
            )

        income_sources = list(
            incomes_qs.values("source").annotate(amount=Sum("amount")).order_by("-amount")
        )
        expense_categories = category_breakdown

        budgets_data = []
        for budget in Budget.objects.filter(user=user, is_active=True).order_by("-created_at")[:5]:
            budget.update_spending()
            utilization = getattr(
                budget,
                "utilization_percentage",
                getattr(budget, "usage_percentage", 0),
            )
            if callable(utilization):
                utilization = utilization()
            budgets_data.append(
                {
                    "id": budget.id,
                    "name": budget.name,
                    "amount": budget.amount,
                    "spent": budget.current_spending,
                    "remaining": budget.remaining_amount,
                    "progress": float(utilization or 0),
                }
            )

        goals_data = []
        for goal in FinancialGoal.objects.filter(
            user=user,
            status__in=["PLANNING", "IN_PROGRESS", "ACTIVE"],
        ).order_by("target_date")[:4]:
            goals_data.append(
                {
                    "id": goal.id,
                    "name": goal.name,
                    "target_amount": goal.target_amount,
                    "current_amount": goal.current_amount,
                    "progress": float(goal.progress_percentage),
                    "target_date": goal.target_date,
                    "is_on_track": goal.is_on_track,
                }
            )

        active_investments = Investment.objects.filter(user=user, status="ACTIVE")
        total_invested = active_investments.aggregate(total=Sum("invested_amount"))["total"] or Decimal("0.00")
        current_investment_value = active_investments.aggregate(total=Sum("current_value"))["total"] or Decimal("0.00")
        investment_returns = current_investment_value - total_invested
        return_percentage = (
            float((investment_returns / total_invested) * 100) if total_invested > 0 else 0.0
        )

        active_debts = Debt.objects.filter(user=user, status="ACTIVE")
        total_debt = active_debts.aggregate(total=Sum("remaining_amount"))["total"] or Decimal("0.00")
        monthly_emi = active_debts.aggregate(total=Sum("emi_amount"))["total"] or Decimal("0.00")
        debt_to_income = float((monthly_emi / total_income) * 100) if total_income > 0 else 0.0

        # Build chart buckets as 4 periods.
        step = max(1, period_days // 4)
        labels, income_points, expense_points = [], [], []
        cursor = start_date
        while cursor <= end_date and len(labels) < 4:
            bucket_end = min(end_date, cursor + timedelta(days=step - 1))
            label = f"{cursor.strftime('%b %d')} - {bucket_end.strftime('%b %d')}"
            inc = (
                Income.objects.filter(user=user, date__range=(cursor, bucket_end)).aggregate(total=Sum("amount"))[
                    "total"
                ]
                or Decimal("0.00")
            )
            exp = (
                Expense.objects.filter(user=user, date__range=(cursor, bucket_end)).aggregate(total=Sum("amount"))[
                    "total"
                ]
                or Decimal("0.00")
            )
            labels.append(label)
            income_points.append(float(inc))
            expense_points.append(float(exp))
            cursor = bucket_end + timedelta(days=1)

        return {
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_savings": net_savings,
            "savings_rate": round(savings_rate, 2),
            "income_growth": round(_growth(total_income, prev_income), 2),
            "expense_growth": round(_growth(total_expenses, prev_expenses), 2),
            "savings_growth": round(_growth(net_savings, prev_savings), 2),
            "savings_rate_growth": round(_growth(savings_rate, prev_savings_rate), 2),
            "category_breakdown": category_breakdown,
            "income_sources": income_sources,
            "expense_categories": expense_categories,
            "budgets": budgets_data,
            "goals": goals_data,
            "total_invested": total_invested,
            "current_investment_value": current_investment_value,
            "investment_returns": investment_returns,
            "return_percentage": round(return_percentage, 2),
            "total_debt": total_debt,
            "monthly_emi": monthly_emi,
            "debt_to_income": round(debt_to_income, 2),
            "chart_data": json.dumps(
                {
                    "labels": labels,
                    "income": income_points,
                    "expenses": expense_points,
                }
            ),
        }

    @classmethod
    def get_advanced_analytics(cls, user, start_date, end_date):
        """Compatibility helper used by `finance.views.analytics`."""
        incomes_qs = Income.objects.filter(user=user, date__range=(start_date, end_date))
        expenses_qs = Expense.objects.filter(user=user, date__range=(start_date, end_date))

        total_income = incomes_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        total_expense = expenses_qs.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        days = max(1, (end_date - start_date).days + 1)
        approx_months = max(1, days / 30)

        monthly_avg_income = total_income / Decimal(str(approx_months))
        monthly_avg_expense = total_expense / Decimal(str(approx_months))

        prev_end = start_date - timedelta(days=1)
        prev_start = prev_end - timedelta(days=days - 1)
        prev_expense = (
            Expense.objects.filter(user=user, date__range=(prev_start, prev_end)).aggregate(total=Sum("amount"))[
                "total"
            ]
            or Decimal("0.00")
        )
        if prev_expense > 0:
            expense_trend = float(((total_expense - prev_expense) / prev_expense) * 100)
        else:
            expense_trend = 0.0

        # Simple volatility proxy from monthly series in the selected period.
        month_rows = (
            Expense.objects.filter(user=user, date__range=(start_date, end_date))
            .extra(select={"month": "strftime('%%Y-%%m', date)"})
            .values("month")
            .annotate(total=Sum("amount"))
            .order_by("month")
        )
        month_values = [float(row["total"] or 0) for row in month_rows]
        if len(month_values) >= 2:
            mean_v = sum(month_values) / len(month_values)
            variance = sum((v - mean_v) ** 2 for v in month_values) / len(month_values)
            income_volatility = round((variance ** 0.5) / max(mean_v, 1) * 100, 2)
        else:
            income_volatility = 0.0

        transactions_analyzed = incomes_qs.count() + expenses_qs.count()
        confidence_score = min(99, max(60, 60 + int(min(transactions_analyzed, 800) / 20)))

        return {
            "monthly_avg_income": monthly_avg_income,
            "income_volatility": income_volatility,
            "monthly_avg_expense": monthly_avg_expense,
            "expense_trend": round(expense_trend, 2),
            "confidence_score": confidence_score,
            "transactions_analyzed": transactions_analyzed,
        }

    @classmethod
    def detect_anomalies(cls, user, start_date=None, end_date=None):
        """Basic anomaly detection used by finance analytics views."""
        if start_date is None or end_date is None:
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=90)

        expenses = list(
            Expense.objects.filter(user=user, date__range=(start_date, end_date))
            .order_by("-date")
            .values("id", "date", "amount", "description", "category")
        )
        if not expenses:
            return []

        avg = sum((row["amount"] for row in expenses), Decimal("0.00")) / Decimal(len(expenses))
        high_threshold = avg * Decimal("2.0")
        medium_threshold = avg * Decimal("1.5")

        anomalies = []
        for row in expenses:
            severity = None
            confidence = None
            if row["amount"] >= high_threshold and row["amount"] > Decimal("0.00"):
                severity = "HIGH"
                confidence = 90
            elif row["amount"] >= medium_threshold and row["amount"] > Decimal("0.00"):
                severity = "MEDIUM"
                confidence = 75

            if severity:
                anomalies.append(
                    {
                        "id": str(row["id"]),
                        "title": "Unusual spending spike",
                        "description": row["description"] or f"Higher than usual {row['category']} expense",
                        "severity": severity,
                        "date": row["date"],
                        "detected_date": row["date"],
                        "amount": row["amount"],
                        "confidence": confidence,
                    }
                )

        return anomalies[:10]

    @classmethod
    def get_benchmark_comparisons(cls, user):
        """Return simple benchmark comparison cards for analytics template."""
        health = cls.calculate_financial_health(user)
        month_start = timezone.now().date().replace(day=1)
        month_income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        month_expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        savings_rate = (
            float(((month_income - month_expense) / month_income) * 100) if month_income > 0 else 0.0
        )

        return [
            {
                "category": "Savings Rate",
                "your_value": f"{savings_rate:.1f}%",
                "benchmark_value": "25.0%",
                "percentage": max(0, min(100, (savings_rate / 25.0) * 100 if savings_rate > 0 else 0)),
            },
            {
                "category": "Expense Control",
                "your_value": f"{health.get('expense_score', 0):.1f}",
                "benchmark_value": "70.0",
                "percentage": max(0, min(100, float(health.get("expense_score", 0)))),
            },
            {
                "category": "Debt Score",
                "your_value": f"{health.get('debt_score', 0):.1f}",
                "benchmark_value": "65.0",
                "percentage": max(0, min(100, float(health.get("debt_score", 0)))),
            },
        ]

    @classmethod
    def recommend_budget_amount(cls, user, category=None):
        """Recommend a budget amount from recent spending history."""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=90)
        expenses = Expense.objects.filter(user=user, date__range=(start_date, end_date))
        if category:
            expenses = expenses.filter(category=category)

        total = expenses.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        monthly_avg = total / Decimal("3.0")
        return (monthly_avg * Decimal("1.10")).quantize(Decimal("0.01"))

    @classmethod
    def get_goal_recommendations(cls, user, goal):
        """Generate short actionable recommendations for a financial goal."""
        recommendations = []
        monthly_needed = goal.required_monthly_saving
        if not goal.is_on_track:
            recommendations.append(
                f"Increase monthly contribution to at least Rs {monthly_needed:.0f}."
            )
            recommendations.append("Reduce discretionary spending categories by 5-10%.")
        else:
            recommendations.append("Goal is on track. Consider increasing contributions for early completion.")

        if goal.months_remaining <= 6:
            recommendations.append("Prioritize this goal in your auto-savings rules for the next 6 months.")
        else:
            recommendations.append("Enable recurring transfers to keep progress consistent.")
        return recommendations

    @classmethod
    def generate_comprehensive_report(
        cls,
        user,
        report_type,
        start_date,
        end_date,
        category=None,
        include_predictions=False,
    ):
        """Compatibility report generator used by finance report views."""
        data = cls.generate_financial_report(user, report_type, start_date, end_date)
        if category:
            data["expense_breakdown"] = [
                row for row in data.get("expense_breakdown", []) if row.get("category") == category
            ]

        chart_payload = {
            "labels": [row["date"] for row in data.get("daily_trends", [])],
            "income": [row["income"] for row in data.get("daily_trends", [])],
            "expense": [row["expense"] for row in data.get("daily_trends", [])],
            "savings": [row["savings"] for row in data.get("daily_trends", [])],
        }
        data["charts"] = chart_payload

        if include_predictions:
            data["predictions"] = cls.predict_future_expenses(user)
        return data

    @classmethod
    def auto_categorize_expense(cls, description):
        """Keyword based expense categorization fallback for CSV imports."""
        text = (description or "").lower()
        mapping = {
            "FOOD": ["food", "restaurant", "dining", "zomato", "swiggy"],
            "TRANSPORT": ["uber", "ola", "transport", "fuel", "petrol"],
            "BILLS": ["bill", "electricity", "water", "internet", "mobile", "recharge"],
            "SHOPPING": ["amazon", "flipkart", "shopping", "store"],
            "ENTERTAINMENT": ["netflix", "movie", "spotify", "entertainment"],
            "HEALTH": ["hospital", "pharmacy", "doctor", "medicine"],
            "SUBSCRIPTION": ["subscription", "plan", "membership"],
        }
        for category, keywords in mapping.items():
            if any(keyword in text for keyword in keywords):
                return category
        return "OTHER"

    @classmethod
    def update_financial_metrics(cls, user):
        """Refresh key `FinancialMetric` entries for the current month."""
        today = timezone.now().date()
        month_start = today.replace(day=1)

        income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        savings_rate = ((income - expense) / income * 100) if income > 0 else Decimal("0.00")
        debt_total = (
            Debt.objects.filter(user=user, status="ACTIVE").aggregate(total=Sum("remaining_amount"))["total"]
            or Decimal("0.00")
        )
        debt_to_income = (debt_total / (income * Decimal("12")) * 100) if income > 0 else Decimal("0.00")

        FinancialMetric.record_metric(
            user=user,
            metric_type="SAVINGS_RATE",
            value=Decimal(savings_rate),
            period_start=month_start,
            period_end=today,
        )
        FinancialMetric.record_metric(
            user=user,
            metric_type="DEBT_TO_INCOME",
            value=Decimal(debt_to_income),
            period_start=month_start,
            period_end=today,
        )
        FinancialMetric.record_metric(
            user=user,
            metric_type="CASH_FLOW",
            value=Decimal(income - expense),
            period_start=month_start,
            period_end=today,
        )
        return {
            "savings_rate": float(savings_rate),
            "debt_to_income": float(debt_to_income),
            "cash_flow": float(income - expense),
        }

    @classmethod
    def sync_with_autopilot(cls, user):
        """Sync finance state into autopilot hints/alerts (best-effort)."""
        synced_count = 0
        bills_created = 0
        alerts_created = 0

        try:
            from finnova_autopilot.models import Alert
        except Exception:  # noqa: BLE001
            return {"synced_count": 0, "bills_created": 0, "alerts_created": 0}

        budgets = Budget.objects.filter(user=user, is_active=True)
        for budget in budgets:
            budget.update_spending()
            if budget.is_exceeded:
                Alert.objects.create(
                    user=user,
                    title=f"Budget exceeded: {budget.name}",
                    message=f"You exceeded {budget.name} by Rs {abs(budget.remaining_amount):.2f}.",
                    category="BUDGET",
                    severity="HIGH",
                    source="FINANCE",
                    related_budget=budget,
                    metadata={"budget_id": str(budget.id)},
                )
                alerts_created += 1

        synced_count = alerts_created + bills_created
        return {
            "synced_count": synced_count,
            "bills_created": bills_created,
            "alerts_created": alerts_created,
        }

    @classmethod
    def get_chart_data(cls, user, chart_type="monthly", months=6):
        """Chart payload for ajax widgets."""
        months = max(1, int(months or 6))
        today = timezone.now().date()

        if chart_type == "daily":
            labels = []
            income_points = []
            expense_points = []
            for i in range(29, -1, -1):
                day = today - timedelta(days=i)
                labels.append(day.strftime("%d %b"))
                income_points.append(
                    float(
                        Income.objects.filter(user=user, date=day).aggregate(total=Sum("amount"))["total"]
                        or Decimal("0.00")
                    )
                )
                expense_points.append(
                    float(
                        Expense.objects.filter(user=user, date=day).aggregate(total=Sum("amount"))["total"]
                        or Decimal("0.00")
                    )
                )
            return {"labels": labels, "income": income_points, "expense": expense_points}

        labels = []
        income_points = []
        expense_points = []
        for i in range(months - 1, -1, -1):
            pivot = (today.replace(day=1) - timedelta(days=30 * i))
            year, month = pivot.year, pivot.month
            labels.append(pivot.strftime("%b %Y"))
            income_points.append(
                float(
                    Income.objects.filter(user=user, date__year=year, date__month=month).aggregate(total=Sum("amount"))[
                        "total"
                    ]
                    or Decimal("0.00")
                )
            )
            expense_points.append(
                float(
                    Expense.objects.filter(user=user, date__year=year, date__month=month).aggregate(
                        total=Sum("amount")
                    )["total"]
                    or Decimal("0.00")
                )
            )
        return {"labels": labels, "income": income_points, "expense": expense_points}

    @classmethod
    def get_financial_metrics(cls, user):
        """Current high-level metrics for dashboard widgets."""
        today = timezone.now().date()
        month_start = today.replace(day=1)

        month_income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        month_expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        net_savings = month_income - month_expense
        savings_rate = (net_savings / month_income * 100) if month_income > 0 else Decimal("0.00")

        return {
            "month_income": float(month_income),
            "month_expense": float(month_expense),
            "net_savings": float(net_savings),
            "savings_rate": float(round(savings_rate, 2)),
            "active_budgets": Budget.objects.filter(user=user, is_active=True).count(),
            "active_goals": FinancialGoal.objects.filter(user=user, status__in=["PLANNING", "IN_PROGRESS"]).count(),
        }

