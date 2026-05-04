# finance/services/insights_engine.py
"""
Smart financial insights engine.

Generates actionable, AI-style spending suggestions grounded in actual
finance data. No LLM needed — it's pure rule-based pattern recognition
on real transaction history.

Used by:
  - Personal dashboard (smart insight cards)
  - Notification triggers (budget alerts)
  - Analytics module (spending patterns)
"""

import logging
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, Sum, Q
from django.utils import timezone

logger = logging.getLogger(__name__)


class InsightsEngine:
    """Generates smart financial insights from transaction data."""

    # ── Public API ──────────────────────────────────────────────

    @classmethod
    def get_dashboard_insights(cls, user, limit=5):
        """Return top insights for the personal dashboard."""
        all_insights = []
        try:
            all_insights.extend(cls._check_budget_warnings(user))
            all_insights.extend(cls._check_spending_trends(user))
            all_insights.extend(cls._check_savings_rate(user))
            all_insights.extend(cls._check_goal_progress(user))
            all_insights.extend(cls._check_recurring_patterns(user))
            all_insights.extend(cls._check_large_expenses(user))
        except Exception:
            logger.exception("InsightsEngine: error generating insights")

        # Sort by priority: critical > warning > tip > info
        priority_order = {'critical': 0, 'warning': 1, 'tip': 2, 'info': 3, 'success': 4}
        all_insights.sort(key=lambda x: priority_order.get(x.get('type', 'info'), 5))
        return all_insights[:limit]

    @classmethod
    def get_savings_metrics(cls, user, months=6):
        """Return month-by-month savings data for the savings tracker."""
        from finance.models import Income, Expense
        now = timezone.now().date()
        months_data = []

        for i in range(months - 1, -1, -1):
            # Calculate month boundaries
            ref = now - timedelta(days=30 * i)
            month_start = ref.replace(day=1)
            # Next month start
            if month_start.month == 12:
                next_month = month_start.replace(year=month_start.year + 1, month=1)
            else:
                next_month = month_start.replace(month=month_start.month + 1)
            month_end = next_month - timedelta(days=1)

            income = Income.objects.filter(
                user=user,
                date__gte=month_start,
                date__lte=month_end,
                is_verified=True,
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

            expense = Expense.objects.filter(
                user=user,
                date__gte=month_start,
                date__lte=month_end,
                is_verified=True,
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

            saved = income - expense
            rate = (saved / income * 100) if income > 0 else Decimal('0')

            months_data.append({
                'month': month_start.strftime('%b %Y'),
                'month_short': month_start.strftime('%b'),
                'income': float(income),
                'expense': float(expense),
                'saved': float(saved),
                'rate': float(rate),
            })

        return months_data

    @classmethod
    def get_budget_forecast(cls, budget):
        """Predict whether a budget will be exceeded based on spending velocity."""
        now = timezone.now().date()
        days_elapsed = (now - budget.start_date).days

        if days_elapsed <= 0:
            return {
                'status': 'just_started',
                'daily_rate': Decimal('0'),
                'projected_total': Decimal('0'),
                'will_exceed': False,
                'projected_overshoot': Decimal('0'),
                'safe_daily_limit': budget.amount,
            }

        daily_rate = budget.current_spending / max(days_elapsed, 1)

        if budget.end_date:
            days_remaining = max((budget.end_date - now).days, 0)
        else:
            # Monthly budget default
            import calendar
            _, last_day = calendar.monthrange(now.year, now.month)
            days_remaining = max(last_day - now.day, 0)

        projected_total = budget.current_spending + (daily_rate * days_remaining)
        overshoot = max(projected_total - budget.amount, Decimal('0'))

        return {
            'status': 'on_track' if projected_total <= budget.amount else 'will_exceed',
            'daily_rate': daily_rate,
            'projected_total': projected_total,
            'will_exceed': projected_total > budget.amount,
            'projected_overshoot': overshoot,
            'safe_daily_limit': budget.remaining_amount / max(days_remaining, 1),
            'days_remaining': days_remaining,
        }

    @classmethod
    def get_category_comparison(cls, user):
        """Compare this month's category spending vs last month."""
        from finance.models import Expense
        now = timezone.now().date()
        this_month_start = now.replace(day=1)
        last_month_end = this_month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        this_month = Expense.objects.filter(
            user=user, date__gte=this_month_start, is_verified=True,
        ).values('category').annotate(
            total=Sum('amount'), count=Count('id')
        ).order_by('-total')

        last_month = {
            row['category']: row['total']
            for row in Expense.objects.filter(
                user=user, date__gte=last_month_start, date__lte=last_month_end,
                is_verified=True,
            ).values('category').annotate(total=Sum('amount'))
        }

        result = []
        for cat in this_month:
            prev = last_month.get(cat['category'], Decimal('0'))
            change = Decimal('0')
            if prev > 0:
                change = ((cat['total'] - prev) / prev) * 100

            result.append({
                'category': cat['category'],
                'category_display': dict(Expense.EXPENSE_CATEGORIES).get(
                    cat['category'], cat['category']
                ),
                'this_month': float(cat['total']),
                'last_month': float(prev),
                'change_pct': float(change),
                'count': cat['count'],
                'trend': 'up' if change > 5 else ('down' if change < -5 else 'flat'),
            })

        return result

    # ── Private insight generators ──────────────────────────────

    @classmethod
    def _check_budget_warnings(cls, user):
        """Insights about budgets that are near/over limit."""
        from finance.models import Budget
        insights = []
        budgets = Budget.objects.filter(user=user, is_active=True)

        for budget in budgets:
            utilization = float(budget.utilization_percentage)

            if budget.is_exceeded:
                overshoot = float(budget.current_spending - budget.amount)
                insights.append({
                    'type': 'critical',
                    'icon': 'fa-triangle-exclamation',
                    'title': f'{budget.name} exceeded',
                    'body': (
                        f'You\'ve spent ₹{budget.current_spending:,.0f} against a '
                        f'₹{budget.amount:,.0f} budget (over by ₹{overshoot:,.0f}).'
                    ),
                    'action': 'Review budget',
                    'action_url': f'/finance/budgets/{budget.id}/',
                })
            elif utilization >= 80:
                remaining = float(budget.remaining_amount)
                insights.append({
                    'type': 'warning',
                    'icon': 'fa-gauge-high',
                    'title': f'{budget.name} at {utilization:.0f}%',
                    'body': f'Only ₹{remaining:,.0f} remaining in this budget.',
                    'action': 'View budget',
                    'action_url': f'/finance/budgets/{budget.id}/',
                })

        return insights

    @classmethod
    def _check_spending_trends(cls, user):
        """Detect spending categories that increased significantly."""
        from finance.models import Expense
        insights = []
        now = timezone.now().date()
        this_month_start = now.replace(day=1)
        last_month_end = this_month_start - timedelta(days=1)
        last_month_start = last_month_end.replace(day=1)

        for category_code, category_name in Expense.EXPENSE_CATEGORIES:
            this_total = Expense.objects.filter(
                user=user, category=category_code,
                date__gte=this_month_start, is_verified=True,
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

            last_total = Expense.objects.filter(
                user=user, category=category_code,
                date__gte=last_month_start, date__lte=last_month_end,
                is_verified=True,
            ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

            if last_total > 0 and this_total > last_total * Decimal('1.20'):
                pct = ((this_total - last_total) / last_total * 100)
                insights.append({
                    'type': 'warning',
                    'icon': 'fa-arrow-trend-up',
                    'title': f'{category_name} spending up {pct:.0f}%',
                    'body': (
                        f'₹{this_total:,.0f} this month vs ₹{last_total:,.0f} last month.'
                    ),
                    'action': 'Review expenses',
                    'action_url': f'/finance/expenses/?category={category_code}',
                })

        return insights[:3]  # Cap at 3 trend insights

    @classmethod
    def _check_savings_rate(cls, user):
        """Insight about this month's savings rate."""
        from finance.models import Income, Expense
        insights = []
        now = timezone.now().date()
        this_month_start = now.replace(day=1)

        income = Income.objects.filter(
            user=user, date__gte=this_month_start, is_verified=True,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        expense = Expense.objects.filter(
            user=user, date__gte=this_month_start, is_verified=True,
        ).aggregate(t=Sum('amount'))['t'] or Decimal('0')

        if income > 0:
            rate = float((income - expense) / income * 100)

            if rate >= 30:
                insights.append({
                    'type': 'success',
                    'icon': 'fa-piggy-bank',
                    'title': f'Great savings rate: {rate:.1f}%',
                    'body': (
                        f'You\'re saving ₹{float(income - expense):,.0f} this month. '
                        f'Keep it up!'
                    ),
                    'action': 'View savings',
                    'action_url': '/finance/',
                })
            elif rate < 10:
                insights.append({
                    'type': 'tip',
                    'icon': 'fa-lightbulb',
                    'title': f'Savings rate is low: {rate:.1f}%',
                    'body': (
                        'Try to save at least 20% of your income. Review your '
                        'top spending categories for potential cuts.'
                    ),
                    'action': 'Check expenses',
                    'action_url': '/finance/expenses/',
                })

        return insights

    @classmethod
    def _check_goal_progress(cls, user):
        """Insights about financial goal milestones."""
        from finance.models import FinancialGoal
        insights = []
        goals = FinancialGoal.objects.filter(
            user=user, status='IN_PROGRESS',
        )

        for goal in goals:
            pct = float(goal.progress_percentage)

            if pct >= 75 and pct < 100:
                insights.append({
                    'type': 'success',
                    'icon': 'fa-trophy',
                    'title': f'{goal.name} is {pct:.0f}% complete!',
                    'body': (
                        f'Just ₹{float(goal.target_amount - goal.current_amount):,.0f} '
                        f'more to reach your goal.'
                    ),
                    'action': 'View goal',
                    'action_url': f'/finance/goals/{goal.id}/',
                })
            elif pct >= 50 and pct < 75:
                insights.append({
                    'type': 'info',
                    'icon': 'fa-flag-checkered',
                    'title': f'{goal.name}: halfway there!',
                    'body': f'₹{float(goal.current_amount):,.0f} saved of ₹{float(goal.target_amount):,.0f}.',
                    'action': 'View goal',
                    'action_url': f'/finance/goals/{goal.id}/',
                })

        return insights[:2]

    @classmethod
    def _check_recurring_patterns(cls, user):
        """Detect merchants where user spends repeatedly (subscription detection)."""
        from finance.models import Expense
        insights = []
        now = timezone.now().date()
        three_months_ago = now - timedelta(days=90)

        recurring = Expense.objects.filter(
            user=user, date__gte=three_months_ago,
            merchant__isnull=False, is_verified=True,
        ).exclude(
            merchant=''
        ).values('merchant').annotate(
            count=Count('id'),
            avg_amount=Avg('amount'),
            total=Sum('amount'),
        ).filter(count__gte=3).order_by('-total')[:5]

        if recurring:
            total_recurring = sum(float(r['total']) for r in recurring)
            top_merchant = recurring[0]['merchant']
            insights.append({
                'type': 'tip',
                'icon': 'fa-repeat',
                'title': f'Recurring spending: ₹{total_recurring:,.0f} in 3 months',
                'body': (
                    f'You have {len(recurring)} regular merchants. '
                    f'Top: {top_merchant} (₹{float(recurring[0]["total"]):,.0f}). '
                    f'Review for potential savings.'
                ),
                'action': 'View expenses',
                'action_url': '/finance/expenses/',
            })

        return insights

    @classmethod
    def _check_large_expenses(cls, user):
        """Flag unusually large recent expenses."""
        from finance.models import Expense
        insights = []
        now = timezone.now().date()
        week_ago = now - timedelta(days=7)
        three_months_ago = now - timedelta(days=90)

        # Get user's average expense amount
        avg_result = Expense.objects.filter(
            user=user, date__gte=three_months_ago, is_verified=True,
        ).aggregate(avg=Avg('amount'))
        avg_amount = avg_result['avg']

        if avg_amount and avg_amount > 0:
            threshold = avg_amount * 3  # 3x average is "large"
            large_recent = Expense.objects.filter(
                user=user, date__gte=week_ago,
                amount__gte=threshold, is_verified=True,
            ).order_by('-amount')[:3]

            for expense in large_recent:
                insights.append({
                    'type': 'info',
                    'icon': 'fa-circle-exclamation',
                    'title': f'Large expense: ₹{float(expense.amount):,.0f}',
                    'body': (
                        f'{expense.description[:60]} on {expense.date.strftime("%d %b")}. '
                        f'This is {float(expense.amount / avg_amount):.1f}x your average.'
                    ),
                    'action': 'Review',
                    'action_url': '/finance/expenses/',
                })

        return insights[:1]
