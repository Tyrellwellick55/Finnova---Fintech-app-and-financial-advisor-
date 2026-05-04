"""
AI advisor helpers for autopilot views.

These methods are intentionally lightweight and deterministic so templates
and views can render consistently even without external ML services.
"""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from finance.models import Expense, Income, Investment


class AIAdvisor:
    """Collection of static helpers used across autopilot pages."""

    @staticmethod
    def _month_start(ref_date=None):
        today = ref_date or timezone.now().date()
        return today.replace(day=1)

    @staticmethod
    def _as_decimal(value):
        return value if isinstance(value, Decimal) else Decimal(str(value or 0))

    @staticmethod
    def _grade_from_score(score_0_to_100):
        if score_0_to_100 >= 90:
            return "A+"
        if score_0_to_100 >= 80:
            return "A"
        if score_0_to_100 >= 70:
            return "B+"
        if score_0_to_100 >= 60:
            return "B"
        if score_0_to_100 >= 50:
            return "C+"
        if score_0_to_100 >= 40:
            return "C"
        if score_0_to_100 >= 30:
            return "D"
        return "F"

    @staticmethod
    def _risk_return_map(risk_profile):
        risk_profile = str(risk_profile or "").upper()
        mapping = {
            "LOW": 7.0,
            "MEDIUM": 10.0,
            "HIGH": 14.0,
            "CONSERVATIVE": 7.0,
            "MODERATE": 10.0,
            "AGGRESSIVE": 14.0,
        }
        return mapping.get(risk_profile, 9.0)

    @staticmethod
    def get_investment_recommendations(user):
        """
        Return structured investment recommendations used by investments page.
        """
        month_start = AIAdvisor._month_start()
        monthly_income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        monthly_expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        free_cash = max(monthly_income - monthly_expense, Decimal("0.00"))
        base_amount = max((free_cash * Decimal("0.25")).quantize(Decimal("0.01")), Decimal("500.00"))

        return [
            {
                "id": "inv-low",
                "title": "Stable Debt Portfolio",
                "name": "Stable Debt Portfolio",
                "description": "Low-volatility allocation focused on capital protection.",
                "risk": "LOW",
                "amount": float(base_amount),
                "expected_return": 7.0,
            },
            {
                "id": "inv-medium",
                "title": "Balanced Index Mix",
                "name": "Balanced Index Mix",
                "description": "Balanced equity-debt allocation for steady long-term growth.",
                "risk": "MEDIUM",
                "amount": float((base_amount * Decimal("1.5")).quantize(Decimal("0.01"))),
                "expected_return": 10.0,
            },
            {
                "id": "inv-high",
                "title": "Growth Equity SIP",
                "name": "Growth Equity SIP",
                "description": "Higher growth potential with higher volatility.",
                "risk": "HIGH",
                "amount": float((base_amount * Decimal("2.0")).quantize(Decimal("0.01"))),
                "expected_return": 14.0,
            },
        ]

    @staticmethod
    def calculate_monthly_investment(target_amount, target_date, risk_profile):
        """Rough monthly investment amount and expected annual return."""
        today = timezone.now().date()
        months = max(1, (target_date.year - today.year) * 12 + (target_date.month - today.month))
        monthly = AIAdvisor._as_decimal(target_amount) / Decimal(months)

        return {
            "amount": monthly.quantize(Decimal("0.01")),
            "expected_return": AIAdvisor._risk_return_map(risk_profile),
        }

    @staticmethod
    def get_savings_recommendations(user):
        """
        Structured savings recommendations used by savings page.
        """
        month_start = AIAdvisor._month_start()
        monthly_income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        monthly_expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        savings = monthly_income - monthly_expense
        savings_rate = float((savings / monthly_income) * 100) if monthly_income > 0 else 0.0

        recommendations = []
        if monthly_income <= 0:
            recommendations.append(
                {
                    "id": "sav-track-income",
                    "type": "OPTIMIZE",
                    "title": "Track Your Income Sources",
                    "description": "Add income records to unlock accurate savings automation.",
                    "potential_savings": 0.0,
                    "suggested_amount": 0.0,
                    "goal_id": "",
                }
            )
            return recommendations

        if savings_rate < 10:
            recommendations.append(
                {
                    "id": "sav-increase-rate",
                    "type": "INCREASE",
                    "title": "Increase Monthly Savings Rate",
                    "description": "Target at least 10% monthly savings by reducing discretionary spending.",
                    "potential_savings": float((monthly_income * Decimal("0.10") - max(savings, Decimal("0.00"))).quantize(Decimal("0.01"))),
                    "suggested_amount": float((monthly_income * Decimal("0.10")).quantize(Decimal("0.01"))),
                    "goal_id": "",
                }
            )

        recommendations.append(
            {
                "id": "sav-auto-transfer",
                "type": "OPTIMIZE",
                "title": "Enable Auto-Save Transfer",
                "description": "Automate a fixed transfer right after salary credit.",
                "potential_savings": float((monthly_income * Decimal("0.05")).quantize(Decimal("0.01"))),
                "suggested_amount": float((monthly_income * Decimal("0.05")).quantize(Decimal("0.01"))),
                "goal_id": "",
            }
        )
        return recommendations[:3]

    @staticmethod
    def calculate_monthly_saving(target_amount, target_date):
        """Simple monthly saving required to hit a goal."""
        today = timezone.now().date()
        months = max(1, (target_date.year - today.year) * 12 + (target_date.month - today.month))
        monthly = AIAdvisor._as_decimal(target_amount) / Decimal(months)
        return {
            "amount": monthly.quantize(Decimal("0.01")),
            "months": months,
        }

    @staticmethod
    def predict_next_month_expenses(user):
        """
        Return prediction cards used in analytics dashboard.
        """
        month_start = AIAdvisor._month_start()
        monthly_expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        monthly_income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        projected = (monthly_expense * Decimal("1.05")).quantize(Decimal("0.01"))
        expected_savings = max((monthly_income - projected), Decimal("0.00")).quantize(Decimal("0.01"))

        return [
            {
                "type": "EXPENSE",
                "title": "Projected Next Month Expenses",
                "description": "Estimated from recent monthly spending patterns.",
                "confidence": 74,
                "amount": float(projected),
            },
            {
                "type": "SAVINGS",
                "title": "Projected Savings Potential",
                "description": "Potential surplus if current trend continues.",
                "confidence": 70,
                "amount": float(expected_savings),
            },
        ]

    @staticmethod
    def get_personalized_recommendations(user):
        """
        Recommendation cards used by AI insights and health pages.
        """
        recs = []
        for idx, rec in enumerate(AIAdvisor.get_savings_recommendations(user), start=1):
            recs.append(
                {
                    "id": rec.get("id", f"rec-s-{idx}"),
                    "priority": "HIGH" if rec.get("type") == "INCREASE" else "MEDIUM",
                    "title": rec.get("title", "Savings Recommendation"),
                    "description": rec.get("description", ""),
                    "timeframe": "This month",
                    "potential_savings": rec.get("potential_savings", 0),
                    "action_url": "/autopilot/savings/",
                }
            )

        for idx, rec in enumerate(AIAdvisor.get_investment_recommendations(user), start=1):
            recs.append(
                {
                    "id": rec.get("id", f"rec-i-{idx}"),
                    "priority": "MEDIUM",
                    "title": rec.get("title", "Investment Suggestion"),
                    "description": rec.get("description", ""),
                    "timeframe": "Next 30 days",
                    "potential_savings": 0,
                    "action_url": "/finance/investments/",
                }
            )

        return recs[:6]

    @staticmethod
    def analyze_spending_patterns(user):
        """Summary structure used by AI insights template."""
        today = timezone.now().date()
        current_month_start = AIAdvisor._month_start(today)
        last_year_same_month_start = current_month_start.replace(year=current_month_start.year - 1)
        last_year_same_month_end = (last_year_same_month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        monthly_total = (
            Expense.objects.filter(user=user, date__gte=current_month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        last_year_total = (
            Expense.objects.filter(
                user=user,
                date__gte=last_year_same_month_start,
                date__lte=last_year_same_month_end,
            ).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        categories = list(
            Expense.objects.filter(user=user, date__gte=current_month_start)
            .values("category")
            .annotate(amount=Sum("amount"))
            .order_by("-amount")
        )
        total_for_pct = sum([c["amount"] or Decimal("0.00") for c in categories], Decimal("0.00"))
        top_categories = []
        for c in categories:
            amount = c["amount"] or Decimal("0.00")
            pct = float((amount / total_for_pct) * 100) if total_for_pct > 0 else 0.0
            top_categories.append(
                {
                    "name": c["category"] or "Other",
                    "category": c["category"] or "Other",   # template alias
                    "amount": float(amount),
                    "percentage": round(pct, 2),
                }
            )

        return {
            "monthly_average": float(monthly_total),
            "top_category": top_categories[0]["name"] if top_categories else "N/A",
            "yoy_change": float(monthly_total - last_year_total),
            "top_categories": top_categories,
        }

    @staticmethod
    def get_investment_suggestions(user):
        """Structure expected by AI insights investment section."""
        return [
            {
                "name": item["name"],
                "risk": item["risk"],
                "description": item["description"],
                "expected_return": item["expected_return"],
            }
            for item in AIAdvisor.get_investment_recommendations(user)
        ]

    @staticmethod
    def identify_savings_opportunities(user):
        """Opportunity cards used in AI insights page."""
        month_start = AIAdvisor._month_start()
        top_expenses = (
            Expense.objects.filter(user=user, date__gte=month_start)
            .values("category")
            .annotate(total=Sum("amount"))
            .order_by("-total")[:3]
        )

        opportunities = []
        for idx, item in enumerate(top_expenses, start=1):
            amount = item["total"] or Decimal("0.00")
            potential = (amount * Decimal("0.10")).quantize(Decimal("0.01"))
            opportunities.append(
                {
                    "id": f"opp-{idx}",
                    "type": "SAVINGS",
                    "title": f"Optimize {item['category']} Spend",
                    "description": "Reduce this category by 10% with a targeted monthly cap.",
                    "potential_savings": float(potential),
                    "period": "month",
                }
            )

        if not opportunities:
            opportunities.append(
                {
                    "id": "opp-auto-save",
                    "type": "SAVINGS",
                    "title": "Start Automatic Savings",
                    "description": "Enable recurring transfer to build savings consistently.",
                    "potential_savings": 500.0,
                    "period": "month",
                }
            )
        return opportunities

    @staticmethod
    def assess_financial_risk(user):
        """Risk block structure used by AI insights template."""
        month_start = AIAdvisor._month_start()
        income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )

        savings_rate = float(((income - expense) / income) * 100) if income > 0 else 0.0
        overspend_ratio = float((expense / income) * 100) if income > 0 else 100.0
        overall_score = max(0, min(100, int((100 - overspend_ratio) + max(0, savings_rate))))

        risks = []
        if overspend_ratio > 90:
            risks.append(
                {
                    "name": "High Spending Ratio",
                    "level": "HIGH",
                    "description": "Monthly spending is very close to monthly income.",
                    "mitigation": "Set stricter category budgets and auto-alerts.",
                }
            )
        if savings_rate < 10:
            risks.append(
                {
                    "name": "Low Savings Buffer",
                    "level": "MEDIUM",
                    "description": "Savings rate is below healthy long-term range.",
                    "mitigation": "Automate monthly savings before discretionary spending.",
                }
            )
        if not risks:
            risks.append(
                {
                    "name": "Balanced Profile",
                    "level": "LOW",
                    "description": "Current risk level appears manageable.",
                    "mitigation": "Continue tracking and maintain current discipline.",
                }
            )

        return {
            "overall_score": overall_score,
            "risks": risks,
        }

    @staticmethod
    def calculate_financial_health(user):
        """
        Core health calculator consumed by FinancialHealthScore.calculate_score().
        """
        month_start = AIAdvisor._month_start()
        income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        invested = (
            Investment.objects.filter(user=user).aggregate(total=Sum("invested_amount"))["total"]
            or Decimal("0.00")
        )

        debt_total = Decimal("0.00")
        try:
            from finance.models import Debt

            debt_total = (
                Debt.objects.filter(user=user, status="ACTIVE").aggregate(total=Sum("remaining_amount"))["total"]
                or Decimal("0.00")
            )
        except Exception:
            debt_total = Decimal("0.00")

        account_balance = Decimal("0.00")
        try:
            from payments_core.models import PaymentAccount

            primary = (
                PaymentAccount.objects.filter(user=user, is_primary=True, is_active=True).first()
                or PaymentAccount.objects.filter(user=user, is_active=True).first()
            )
            account_balance = primary.balance if primary else Decimal("0.00")
        except Exception:
            account_balance = Decimal("0.00")

        savings_rate = float(((income - expense) / income) * 100) if income > 0 else 0.0
        debt_to_income = float((debt_total / income) * 100) if income > 0 else 0.0
        emergency_months = float((account_balance / expense)) if expense > 0 else 0.0
        investment_ratio = float((invested / (income * Decimal("12")) * 100)) if income > 0 else 0.0

        savings_score = max(0, min(100, int(savings_rate * 4)))  # 25% => 100
        debt_score = max(0, min(100, int(100 - debt_to_income)))
        spending_score = max(0, min(100, int(100 - max(0, (float(expense / income) * 100 - 70)) if income > 0 else 30)))
        investment_score = max(0, min(100, int(investment_ratio)))
        insurance_score = 60
        budget_score = spending_score
        emergency_fund_score = max(0, min(100, int((emergency_months / 6) * 100)))

        components = {
            "savings_score": savings_score,
            "insurance_score": insurance_score,
            "debt_score": debt_score,
            "investment_score": investment_score,
            "budget_score": budget_score,
            "emergency_fund_score": emergency_fund_score,
        }
        score_0_to_100 = (
            savings_score * 0.25
            + debt_score * 0.2
            + spending_score * 0.2
            + investment_score * 0.2
            + emergency_fund_score * 0.15
        )
        overall_score = int(round(score_0_to_100 * 10))  # model uses 0..1000
        grade = AIAdvisor._grade_from_score(score_0_to_100)

        strengths = []
        weaknesses = []
        opportunities = []
        threats = []

        if savings_score >= 70:
            strengths.append("Healthy savings habit")
        else:
            weaknesses.append("Savings rate below optimal range")
            opportunities.append("Automate transfers to improve consistency")

        if debt_score < 60:
            threats.append("Debt burden may impact long-term goals")
            opportunities.append("Increase debt repayments to reduce risk")
        else:
            strengths.append("Debt exposure appears manageable")

        if emergency_fund_score < 50:
            weaknesses.append("Emergency fund coverage is limited")
            opportunities.append("Build at least 3-6 months emergency buffer")
        else:
            strengths.append("Emergency buffer provides resilience")

        insights = [
            {
                "title": "Monthly Savings Rate",
                "message": f"Current savings rate is {savings_rate:.1f}%.",
                "timestamp": timezone.now().isoformat(),
            },
            {
                "title": "Debt Exposure",
                "message": f"Debt-to-income ratio is {debt_to_income:.1f}%.",
                "timestamp": timezone.now().isoformat(),
            },
        ]

        recommendations = AIAdvisor.get_financial_health_recommendations(user)
        benchmark = AIAdvisor.get_benchmark_comparison(user)

        return {
            "overall_score": overall_score,
            "grade": grade,
            "components": components,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "opportunities": opportunities,
            "threats": threats,
            "insights": insights,
            "recommendations": recommendations,
            "trend": "STABLE",
            "percentile": 50,
            "benchmark": benchmark,
        }

    @staticmethod
    def get_financial_health_recommendations(user):
        """Recommendations for financial health dashboard."""
        month_start = AIAdvisor._month_start()
        income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        savings_rate = float(((income - expense) / income) * 100) if income > 0 else 0.0

        recs = []
        if savings_rate < 10:
            recs.append(
                {
                    "id": "fh-1",
                    "priority": "HIGH",
                    "title": "Raise Savings Rate",
                    "description": "Move at least 10% of income to savings before discretionary spending.",
                    "timeframe": "Next 30 days",
                    "action_url": "/autopilot/savings/",
                }
            )
        recs.append(
            {
                "id": "fh-2",
                "priority": "MEDIUM",
                "title": "Review Category Budgets",
                "description": "Set strict monthly caps for your top 3 spending categories.",
                "timeframe": "This week",
                "action_url": "/finance/budgets/",
            }
        )
        recs.append(
            {
                "id": "fh-3",
                "priority": "LOW",
                "title": "Diversify Investments",
                "description": "Revisit your investment mix to balance risk and growth.",
                "timeframe": "This quarter",
                "action_url": "/finance/investments/",
            }
        )
        return recs

    @staticmethod
    def get_benchmark_comparison(user):
        """Simple benchmark comparison structure for health template."""
        month_start = AIAdvisor._month_start()
        income = (
            Income.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        expense = (
            Expense.objects.filter(user=user, date__gte=month_start).aggregate(total=Sum("amount"))["total"]
            or Decimal("0.00")
        )
        savings_rate = float(((income - expense) / income) * 100) if income > 0 else 0.0

        invested = (
            Investment.objects.filter(user=user).aggregate(total=Sum("invested_amount"))["total"]
            or Decimal("0.00")
        )
        invest_ratio = float((invested / (income * Decimal("12")) * 100)) if income > 0 else 0.0

        return {
            "savings": {"user": f"{savings_rate:.1f}%", "benchmark": "20.0%"},
            "investments": {"user": f"{invest_ratio:.1f}%", "benchmark": "25.0%"},
            "debt": {"user": "Moderate", "benchmark": "Low"},
            "emergency_fund": {"user": "Building", "benchmark": "6 months"},
        }

    @staticmethod
    def analyze_transaction_patterns(user):
        """Insights shown in transaction pattern analysis page."""
        from ..models import TransactionPattern

        patterns = TransactionPattern.objects.filter(user=user, is_active=True).order_by("-confidence_score")[:5]
        if not patterns:
            return [
                {
                    "type": "INFO",
                    "title": "No strong patterns yet",
                    "message": "Keep using autopilot; more transactions improve pattern confidence.",
                    "impact": "LOW",
                    "action": {"url": "/autopilot/patterns/", "text": "Scan Again"},
                }
            ]

        insights = []
        for pattern in patterns:
            insights.append(
                {
                    "type": "POSITIVE" if float(pattern.confidence_score) >= 70 else "WARNING",
                    "title": pattern.pattern_name,
                    "message": f"{pattern.pattern_type} pattern with {pattern.confidence_score}% confidence.",
                    "impact": "HIGH" if float(pattern.confidence_score) >= 80 else "MEDIUM",
                    "action": {"url": f"/autopilot/patterns/{pattern.id}/", "text": "Review"},
                }
            )
        return insights

    @staticmethod
    def get_pattern_based_recommendations(pattern):
        """Recommendations shown on pattern detail page."""
        return [
            {
                "id": f"pat-{pattern.id}-1",
                "title": "Create Rule from Pattern",
                "impact": "MEDIUM",
                "description": "Automate an action whenever this pattern is detected again.",
                "options": [
                    {"value": "alert", "label": "Create alert", "amount": 0},
                    {"value": "save", "label": "Move to savings", "amount": 500},
                ],
            }
        ]

    @staticmethod
    def get_rebalancing_recommendations(plan):
        """Rebalancing cards used in investment detail page."""
        allocation = plan.asset_allocation or {}
        current = {
            "Equity": float(allocation.get("equity", allocation.get("stocks", 0) or 0)),
            "Debt": float(allocation.get("debt", allocation.get("bonds", 0) or 0)),
            "Gold": float(allocation.get("gold", 0) or 0),
        }

        risk = str(plan.risk_profile or "MEDIUM").upper()
        target_map = {
            "LOW": {"Equity": 25, "Debt": 60, "Gold": 15},
            "MEDIUM": {"Equity": 50, "Debt": 35, "Gold": 15},
            "HIGH": {"Equity": 70, "Debt": 20, "Gold": 10},
        }
        target = target_map.get(risk, target_map["MEDIUM"])

        recs = []
        for asset in ("Equity", "Debt", "Gold"):
            cur = current.get(asset, 0)
            tgt = target.get(asset, 0)
            if abs(cur - tgt) >= 5:
                recs.append(
                    {
                        "asset_class": asset,
                        "current_allocation": round(cur, 1),
                        "target_allocation": round(tgt, 1),
                        "reason": f"Align {asset} allocation with your {risk} risk profile.",
                    }
                )
        return recs

    @staticmethod
    def get_savings_acceleration_strategies(goal):
        """Acceleration cards used in savings detail page."""
        monthly_needed = float(goal.required_monthly_saving or 0)
        current_monthly = float(goal.actual_monthly_saving or 0)
        gap = max(monthly_needed - current_monthly, 0)
        suggested = max(gap, monthly_needed * 0.2, 500)

        return [
            {
                "type": "INCREASE",
                "title": "Increase Monthly Auto-Save",
                "description": "Raise your recurring savings transfer to close the monthly gap.",
                "impact": round(suggested, 2),
                "suggested_amount": round(suggested, 2),
            },
            {
                "type": "CUT",
                "title": "Trim Discretionary Spending",
                "description": "Redirect avoidable spends (subscriptions/dining) into this goal.",
                "impact": round(suggested * 0.6, 2),
                "suggested_amount": round(suggested * 0.6, 2),
            },
        ]
