import logging
logger = logging.getLogger(__name__)
# algorithms.py - COMPLETE AND FINAL
from collections import defaultdict
from datetime import datetime, timedelta
import statistics
from typing import Dict, List, Tuple, Optional
from decimal import Decimal

#####################################################################
# Algorithm 1: Budget overrun detection
def detect_budget_overrun(expenses, monthly_budget: float) -> Dict:
    """Check if user has exceeded monthly budget"""
    total_spent = sum(float(exp.amount) for exp in expenses)
    
    if total_spent > monthly_budget:
        return {
            "status": "OVERSPENT",
            "total_spent": total_spent,
            "excess_amount": total_spent - monthly_budget,
            "percentage_over": ((total_spent - monthly_budget) / monthly_budget * 100) if monthly_budget > 0 else 0
        }
    
    return {
        "status": "WITHIN_BUDGET",
        "total_spent": total_spent,
        "remaining_budget": monthly_budget - total_spent,
        "percentage_used": (total_spent / monthly_budget * 100) if monthly_budget > 0 else 0
    }

#####################################################################
# Algorithm 2: Category spending analysis
def category_expense_analysis(expenses) -> List[Tuple[str, float]]:
    """Identify categories where user spends most money"""
    category_totals = defaultdict(float)
    
    for exp in expenses:
        if exp.category:
            # Compatible with both FK-like category objects and string choices.
            category_name = (
                exp.category.name
                if hasattr(exp.category, "name")
                else str(exp.category)
            )
            category_totals[category_name] += float(exp.amount)
        else:
            category_totals["Uncategorized"] += float(exp.amount)
    
    return sorted(category_totals.items(), key=lambda x: x[1], reverse=True)

#####################################################################
# Algorithm 3: Savings score calculation
def savings_monthly_score(total_income: float, total_expenses: float) -> int:
    """Calculate savings score (0-100)"""
    if total_income <= 0:
        return 0
    
    savings_ratio = (total_income - total_expenses) / total_income
    score = int(savings_ratio * 100)
    return max(0, min(100, score))

#####################################################################
# Algorithm 4: Financial tips generation
def generate_financial_tips(score: int, top_category: str = None) -> List[str]:
    """Generate personalized financial tips"""
    tips = []
    
    if score < 40:
        tips.append("Consider cutting non-essential expenses to improve your savings.")
        if top_category:
            tips.append(f"Try to limit spending in the '{top_category}' category.")
        tips.append("Set up a strict budget and track daily expenses.")
    elif 40 <= score < 70:
        tips.append("Setting a monthly budget can help you manage your finances better.")
        tips.append("Consider automating your savings to ensure consistency.")
    else:
        tips.append("Great job! Consider investing your surplus funds for better returns.")
        tips.append("You could explore mutual funds or fixed deposits for your savings.")
    
    return tips

#####################################################################
# Algorithm 5: Monthly spending trend
def monthly_spending_trend(expenses) -> Dict[str, float]:
    """Analyze monthly spending patterns"""
    monthly_data = defaultdict(float)
    
    for exp in expenses:
        month_key = exp.date.strftime("%Y-%m")
        monthly_data[month_key] += float(exp.amount)
    
    return dict(sorted(monthly_data.items()))

#####################################################################
# Algorithm 6: Financial personality classification
def financial_personality(score: int) -> str:
    """Classify user's financial personality"""
    if score >= 80:
        return 'saver'
    elif 50 <= score < 80:
        return 'balanced'
    elif 30 <= score < 50:
        return 'spender'
    else:
        return 'overspender'

#####################################################################
# Algorithm 7: Unusual spending detection
def detect_unusual_spending(expenses, threshold: float = 2.0) -> List:
    """Detect expenses that are unusually high"""
    if not expenses:
        return []
    
    avg = sum(float(exp.amount) for exp in expenses) / len(expenses)
    return [exp for exp in expenses if float(exp.amount) > threshold * avg]

#####################################################################
# Algorithm 8: Next month expense prediction
def predict_next_month_expenses(monthly_trends: Dict[str, float], seasonality: bool = True) -> float:
    """Predict next month's expenses using trend analysis"""
    if not monthly_trends:
        return 0.0
    
    if len(monthly_trends) < 3:
        # Simple average for insufficient data
        total = sum(monthly_trends.values())
        return round(total / len(monthly_trends), 2)
    
    # Extract months and amounts
    months = list(range(len(monthly_trends)))
    amounts = list(monthly_trends.values())
    
    # Calculate linear regression for trend
    n = len(months)
    sum_x = sum(months)
    sum_y = sum(amounts)
    sum_xy = sum(x * y for x, y in zip(months, amounts))
    sum_x2 = sum(x * x for x in months)
    
    # Avoid division by zero
    if n * sum_x2 - sum_x * sum_x == 0:
        return round(amounts[-1], 2)
    
    slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
    
    # Next month prediction = last value + trend
    last_amount = amounts[-1]
    next_prediction = last_amount + slope
    
    # Apply seasonality if enough data
    if len(monthly_trends) >= 12 and seasonality:
        monthly_averages = defaultdict(list)
        for month_str, amount in monthly_trends.items():
            year, month = map(int, month_str.split('-'))
            monthly_averages[month].append(amount)
        
        # Get next month
        next_month = datetime.now().month + 1
        if next_month > 12:
            next_month = 1
        
        if next_month in monthly_averages:
            seasonal_avg = statistics.mean(monthly_averages[next_month])
            # Weighted average of trend and seasonality
            next_prediction = (next_prediction * 0.7) + (seasonal_avg * 0.3)
    
    return round(max(0, next_prediction), 2)

#####################################################################
# Algorithm 9: Smart budget recommendation
def recommended_monthly_budget(income: float, expense: float) -> float:
    """Recommend monthly budget based on income-to-expense ratio"""
    if income <= 0:
        return 0
    
    recommended_budget = income * 0.8  # 80% rule
    
    # If expenses are already under control, use current expenses
    if expense < recommended_budget:
        return round(expense, 2)
    
    return round(recommended_budget, 2)

#####################################################################
# Algorithm 10: Goal feasibility check
def goal_feasibility(goal_amount: float, monthly_saving: float) -> Dict:
    """Check if financial goal is achievable"""
    if monthly_saving <= 0:
        return {
            'status': 'UNACHIEVABLE',
            'message': 'With zero monthly savings, achieving the goal is not feasible.'
        }
    
    months_required = goal_amount / monthly_saving
    
    return {
        'status': 'ACHIEVABLE',
        'months_required': int(months_required) if months_required < 120 else 120,  # Cap at 10 years
        'years_required': round(months_required / 12, 1)
    }

#####################################################################
# Algorithm 11: Financial risk assessment
def financial_risk_level(income: float, expense: float) -> str:
    """Assess financial risk based on expense ratio"""
    if income <= 0:
        return "HIGH RISK"
    
    expense_ratio = expense / income
    
    if expense_ratio > 0.9:
        return "CRITICAL RISK"
    elif expense_ratio > 0.7:
        return "HIGH RISK"
    elif expense_ratio > 0.5:
        return "MODERATE RISK"
    else:
        return "LOW RISK"

#####################################################################
# Algorithm 12: AI report generation
def generate_ai_report(score: int, risk: str, prediction: float, personality: str) -> str:
    """Generate natural language AI report"""
    report_parts = [
        f"Your financial health score is {score}/100, which indicates a {personality} personality.",
        f"Risk assessment: {risk}. This is based on your current spending patterns.",
        f"Based on historical data, your next month's expenses are predicted to be ₹{prediction:,.2f}.",
    ]
    
    # Add personalized advice
    if score < 50:
        report_parts.append("Consider reviewing your discretionary spending to improve your savings rate.")
    elif score >= 80:
        report_parts.append("Excellent financial discipline! You're ready for investment opportunities.")
    
    return " ".join(report_parts)

#####################################################################
# Algorithm 13: Financial data validation
def validate_financial_data(income: float, expense: float) -> bool:
    """Validate financial data for anomalies"""
    if income < 0 or expense < 0:
        return False
    
    # Expense should not exceed 5x income (unrealistic scenario)
    if expense > income * 5:
        return False
    
    return True

#####################################################################
# Algorithm 14: Cash flow crisis prediction
def predict_cashflow_crisis(income_schedule: List[Dict], expense_schedule: List[Dict],
                           current_balance: float, days_ahead: int = 30) -> Dict:
    """Predict cash flow crisis in next X days"""
    daily_balance = float(current_balance or 0)
    crisis_points = []
    today = datetime.now().date()

    def _to_date(value):
        """Normalize incoming schedule date values to date objects."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date()
        if hasattr(value, "date") and callable(value.date):
            try:
                return value.date()
            except TypeError:
                pass
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).date()
            except ValueError:
                return None
        return value
    
    for day in range(days_ahead):
        target_date = today + timedelta(days=day)
        
        # Calculate daily income
        day_income = sum(
            float(item.get('amount') or 0)
            for item in income_schedule
            if _to_date(item.get('date')) == target_date
        )
        
        # Calculate daily expenses
        day_expenses = sum(
            float(item.get('amount') or 0)
            for item in expense_schedule
            if _to_date(item.get('date')) == target_date
        )
        
        daily_balance += day_income - day_expenses
        
        if daily_balance < 0:
            crisis_points.append({
                'date': target_date,
                'shortfall': abs(daily_balance),
                'day_number': day
            })
    
    if crisis_points:
        earliest = min(crisis_points, key=lambda x: x['day_number'])
        return {
            'has_crisis': True,
            'crisis_date': earliest['date'],
            'shortfall': earliest['shortfall'],
            'days_until': earliest['day_number'],
            'confidence': 0.85
        }
    
    return {'has_crisis': False, 'confidence': 0.9}

#####################################################################
# Algorithm 15: Smart savings automation
def smart_savings_automation(user_profile: Dict, expenses: List, income: float) -> Dict:
    """Recommend automatic savings based on spending patterns"""
    if income <= 0:
        return {
            'recommended_savings': 0,
            'frequency': 'monthly',
            'auto_transfer': False,
            'priority': 'LOW',
            'estimated_goal_achievement': float('inf')
        }
    
    # Analyze discretionary spending (assuming category has is_essential field)
    discretionary_spending = 0
    for exp in expenses:
        if hasattr(exp.category, 'is_essential'):
            if not exp.category.is_essential:
                discretionary_spending += float(exp.amount)
        else:
            # Default: assume 30% is discretionary
            discretionary_spending += float(exp.amount) * 0.3
    
    # Calculate safe-to-save amount
    safe_savings = min(income * 0.2, discretionary_spending * 0.5)
    
    monthly_goal = user_profile.get('monthly_savings_goal', 0)
    
    return {
        'recommended_savings': round(safe_savings, 2),
        'frequency': 'weekly' if income >= 50000 else 'monthly',
        'auto_transfer': safe_savings > 1000,
        'priority': 'HIGH' if monthly_goal > safe_savings else 'MEDIUM',
        'estimated_goal_achievement': monthly_goal / safe_savings if safe_savings > 0 else float('inf')
    }

#####################################################################
# Algorithm 16: Spending pattern analysis
def spending_pattern_analysis(user_id: int) -> Dict:
    """Analyze user's spending patterns and provide insights"""
    # This would typically query the database for user's spending data
    # For now, return a basic analysis structure
    return {
        'top_category': 'Food & Dining',
        'average_daily_spending': 150.0,
        'weekend_vs_weekday_ratio': 1.3,
        'seasonal_trends': 'Higher spending in December',
        'recommendations': [
            'Consider meal planning to reduce food expenses',
            'Weekend spending is 30% higher than weekdays'
        ]
    }

#####################################################################
# Algorithm 17: Investment recommendations
def investment_recommendations(balance: float, income: float, risk_level: str) -> str:
    """Provide investment recommendations based on user profile"""
    if balance < 10000:
        return "Build an emergency fund before investing"

    if risk_level == "LOW RISK":
        if income > 50000:
            return "Consider balanced mutual funds or PPF for stable returns"
        else:
            return "Start with fixed deposits or recurring deposits"
    elif risk_level == "MODERATE RISK":
        return "Consider equity savings funds or balanced advantage funds"
    elif risk_level == "HIGH RISK":
        return "Focus on debt funds and conservative hybrid funds"
    else:
        return "Consult a financial advisor before investing"

#####################################################################
# Algorithm 18: Income opportunity detection
def detect_income_opportunity(spending_patterns: List, market_data: Dict = None) -> List[Dict]:
    """Suggest income opportunities based on spending"""
    opportunities = []
    
    # Analyze spending categories
    top_categories = category_expense_analysis(spending_patterns)
    
    # Gig economy opportunities by category
    gig_platforms = {
        'Food': ['Swiggy Instamart', 'Zomato Delivery', 'Food Delivery'],
        'Entertainment': ['Freelance Content', 'Online Tutoring', 'Game Testing'],
        'Shopping': ['Reselling', 'Dropshipping', 'Affiliate Marketing'],
        'Transport': ['Uber/Ola', 'Delivery Services', 'Car Rental'],
        'Bills': ['Budget Consulting', 'Utility Comparison Services']
    }
    
    # Map categories to gig platforms
    category_mapping = {
        'Food & Dining': 'Food',
        'Entertainment': 'Entertainment',
        'Shopping': 'Shopping',
        'Transportation': 'Transport',
        'Utilities': 'Bills',
        'Groceries': 'Food'
    }
    
    for category, amount in top_categories[:3]:
        mapped_category = category_mapping.get(category, 'Other')
        
        if mapped_category in gig_platforms and amount > 3000:
            for platform in gig_platforms[mapped_category]:
                # Estimate earning potential (10-30% of spending)
                estimated_earning = amount * 0.2
                
                opportunities.append({
                    'category': category,
                    'platform': platform,
                    'estimated_earning': round(estimated_earning, 2),
                    'effort': 'PART_TIME',
                    'rationale': f'You spend ₹{amount:,.0f} on {category}. Consider earning through {platform}.',
                    'action_link': f'/opportunities/{platform.lower().replace(" ", "-")}'
                })
    
    return opportunities[:3]


#####################################################################
# Compatibility helpers for autopilot/automation engine
#####################################################################
def predict_expense_categories(expenses) -> Dict[str, float]:
    """
    Backwards‑compatible helper used by the autopilot automation engine.

    Returns a dict of {category_name: total_amount}.
    """
    analysis = category_expense_analysis(expenses)
    return {name: total for name, total in analysis}


def detect_anomalies(expenses, threshold: float = 2.0):
    """
    Thin wrapper around `detect_unusual_spending` for older code paths.
    """
    return detect_unusual_spending(expenses, threshold=threshold)


def calculate_risk_score(income: float, expense: float) -> int:
    """
    Convert `financial_risk_level` into a simple numeric score (0-100).
    Lower risk => higher score.
    """
    level = financial_risk_level(income, expense)
    mapping = {
        "LOW RISK": 90,
        "MODERATE RISK": 70,
        "HIGH RISK": 40,
        "CRITICAL RISK": 20,
    }
    return mapping.get(level, 50)

#####################################################################
# NEW Algorithm 17: Financial Health Score (Comprehensive)
def calculate_financial_health_score(user_data: Dict) -> Tuple[int, str, Dict]:
    """
    Calculate comprehensive financial health score (0-1000)
    Returns: (score, grade, breakdown)
    """
    score = 0
    breakdown = {}
    
    # 1. Savings Rate (250 points)
    savings_rate = user_data.get('savings_rate', 0)
    if savings_rate >= 20:
        score += 250
        breakdown['savings_rate'] = {'points': 250, 'status': 'Excellent'}
    elif savings_rate >= 15:
        score += 200
        breakdown['savings_rate'] = {'points': 200, 'status': 'Good'}
    elif savings_rate >= 10:
        score += 150
        breakdown['savings_rate'] = {'points': 150, 'status': 'Fair'}
    elif savings_rate >= 5:
        score += 100
        breakdown['savings_rate'] = {'points': 100, 'status': 'Needs Improvement'}
    else:
        score += 50
        breakdown['savings_rate'] = {'points': 50, 'status': 'Poor'}
    
    # 2. Emergency Fund (200 points)
    emergency_months = user_data.get('emergency_fund_months', 0)
    if emergency_months >= 6:
        score += 200
        breakdown['emergency_fund'] = {'points': 200, 'status': 'Excellent'}
    elif emergency_months >= 3:
        score += 150
        breakdown['emergency_fund'] = {'points': 150, 'status': 'Good'}
    elif emergency_months >= 1:
        score += 100
        breakdown['emergency_fund'] = {'points': 100, 'status': 'Fair'}
    else:
        score += 30
        breakdown['emergency_fund'] = {'points': 30, 'status': 'Poor'}
    
    # 3. Debt-to-Income Ratio (200 points)
    debt_ratio = user_data.get('debt_to_income', 0)
    if debt_ratio <= 0.2:
        score += 200
        breakdown['debt_ratio'] = {'points': 200, 'status': 'Excellent'}
    elif debt_ratio <= 0.35:
        score += 150
        breakdown['debt_ratio'] = {'points': 150, 'status': 'Good'}
    elif debt_ratio <= 0.5:
        score += 100
        breakdown['debt_ratio'] = {'points': 100, 'status': 'Fair'}
    else:
        score += 50
        breakdown['debt_ratio'] = {'points': 50, 'status': 'Poor'}
    
    # 4. Credit Utilization (150 points)
    credit_util = user_data.get('credit_utilization', 0)
    if credit_util <= 0.3:
        score += 150
        breakdown['credit_utilization'] = {'points': 150, 'status': 'Excellent'}
    elif credit_util <= 0.5:
        score += 120
        breakdown['credit_utilization'] = {'points': 120, 'status': 'Good'}
    elif credit_util <= 0.7:
        score += 80
        breakdown['credit_utilization'] = {'points': 80, 'status': 'Fair'}
    else:
        score += 30
        breakdown['credit_utilization'] = {'points': 30, 'status': 'Poor'}
    
    # 5. Spending Consistency (100 points)
    spending_consistency = user_data.get('spending_consistency', 0.7)
    if spending_consistency >= 0.9:
        score += 100
        breakdown['spending_consistency'] = {'points': 100, 'status': 'Excellent'}
    elif spending_consistency >= 0.7:
        score += 70
        breakdown['spending_consistency'] = {'points': 70, 'status': 'Good'}
    elif spending_consistency >= 0.5:
        score += 40
        breakdown['spending_consistency'] = {'points': 40, 'status': 'Fair'}
    else:
        score += 20
        breakdown['spending_consistency'] = {'points': 20, 'status': 'Poor'}
    
    # 6. Investment Ratio (100 points)
    investment_ratio = user_data.get('investment_ratio', 0)
    if investment_ratio >= 0.2:
        score += 100
        breakdown['investment_ratio'] = {'points': 100, 'status': 'Excellent'}
    elif investment_ratio >= 0.1:
        score += 70
        breakdown['investment_ratio'] = {'points': 70, 'status': 'Good'}
    elif investment_ratio >= 0.05:
        score += 40
        breakdown['investment_ratio'] = {'points': 40, 'status': 'Fair'}
    else:
        score += 10
        breakdown['investment_ratio'] = {'points': 10, 'status': 'Poor'}
    
    # Calculate grade
    percentage = (score / 1000) * 100
    
    if percentage >= 85:
        grade = 'A'
    elif percentage >= 75:
        grade = 'B'
    elif percentage >= 65:
        grade = 'C'
    elif percentage >= 50:
        grade = 'D'
    else:
        grade = 'F'
    
    return score, grade, breakdown
