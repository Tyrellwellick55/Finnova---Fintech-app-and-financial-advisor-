from decimal import Decimal

from django.utils import timezone

from finnovaapp.services import get_comprehensive_dashboard
from finance.models import FinancialGoal


def get_financial_summary(user):
    """
    Wrapper around `finnovaapp.services.get_comprehensive_dashboard`
    that enriches the dashboard data with a couple of extra
    fields expected by templates.

    This keeps existing behaviour in one place while exposing a stable
    summary entrypoint for the Finnova shell.
    """
    # Start with the comprehensive dashboard data
    data = get_comprehensive_dashboard(user) or {}

    # Ensure current_date is always available for the welcome header
    today = timezone.now().date()
    data.setdefault("current_date", today)

    # Add a simple savings_goal number based on the highest‑priority
    # active savings goal, falling back to 0 if none exist.
    try:
        goal = (
            FinancialGoal.objects.filter(user=user, goal_type="SAVINGS")
            .order_by("-priority", "target_date")
            .first()
        )
        data.setdefault("savings_goal", goal.target_amount if goal else Decimal("0"))
    except Exception:
        # Fail safe – never break the dashboard due to goal issues
        data.setdefault("savings_goal", Decimal("0"))

    return data

