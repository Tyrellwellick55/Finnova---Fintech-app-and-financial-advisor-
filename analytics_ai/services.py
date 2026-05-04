# services.py - COMPLETE AND FINAL
from datetime import datetime, timedelta
from decimal import Decimal
import json
import uuid
from typing import Dict, List, Optional, Tuple
from django.db import transaction, models
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.db.models import Sum, Avg, Count, Q
from django.urls import reverse

from .models import (
    UserFinancialProfile,
    FinancialInsight,
    PredictiveAlert,
    SmartRule,
    AISession,
    AIFinancialGoal,
)
from finance.models import Expense, Income, BudgetCategory, FinancialGoal, Investment, Debt
from payments_core.models import PaymentTransaction as Transaction, PaymentAccount as Wallet
from finnova_autopilot.models import AutopilotDecision, RuleEngine
from notifications.services import create_notification_event

from .algorithms import (
    detect_budget_overrun, category_expense_analysis, 
    savings_monthly_score, financial_personality,
    predict_cashflow_crisis, smart_savings_automation,
    detect_income_opportunity, financial_risk_level,
    predict_next_month_expenses, recommended_monthly_budget,
    goal_feasibility, calculate_financial_health_score,
    generate_financial_tips, generate_ai_report
)

class FinancialAnalyticsService:
    """Main service for financial analytics - COMPLETE"""
    
    def __init__(self, user):
        self.user = user
        self.profile, _ = UserFinancialProfile.objects.get_or_create(user=user)
        self.session_id = str(uuid.uuid4())

    def _safe_profile_save(self, update_fields: Optional[List[str]] = None) -> None:
        """Best-effort profile persistence so read-only analytics pages still render."""
        try:
            if update_fields:
                self.profile.save(update_fields=update_fields)
            else:
                self.profile.save()
        except Exception:
            pass
        
    def create_ai_session(self, session_type: str, input_data: Dict, 
                         processing_time: float = 0.0) -> AISession:
        """Create AI session log"""
        normalized_type = session_type if session_type in {'CHAT', 'ADVICE', 'ANALYSIS', 'PLANNING', 'EDUCATION', 'SUPPORT'} else 'ANALYSIS'
        return AISession.objects.create(
            user=self.user,
            session_type=normalized_type,
            title=f"AI {normalized_type.title()} Session",
            context_data=input_data or {},
            analysis_data={},
            metadata={
                'session_id': self.session_id,
                'processing_time': processing_time,
                'success': True,
            }
        )
    
    def analyze_monthly_finances(self, month: datetime = None) -> Dict:
        """Complete monthly financial analysis"""
        start_time = timezone.now()
        
        if not month:
            month = timezone.now().replace(day=1, hour=0, minute=0, second=0)
        
        month_end = (month + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        
        # Get financial data
        expenses = Expense.objects.filter(
            user=self.user,
            date__gte=month,
            date__lte=month_end
        ).select_related('budget_category')
        
        incomes = Income.objects.filter(
            user=self.user,
            date__gte=month,
            date__lte=month_end
        )
        
        total_income = float(incomes.aggregate(total=Sum('amount'))['total'] or 0)
        total_expense = float(expenses.aggregate(total=Sum('amount'))['total'] or 0)
        
        # Run all analyses
        analysis = {
            'period': {
                'start': month,
                'end': month_end,
                'month_name': month.strftime('%B %Y')
            },
            'basic_metrics': {
                'total_income': total_income,
                'total_expense': total_expense,
                'net_savings': total_income - total_expense,
                'savings_rate': ((total_income - total_expense) / total_income * 100) if total_income > 0 else 0
            },
            'savings_score': savings_monthly_score(total_income, total_expense),
            'risk_level': financial_risk_level(total_income, total_expense),
            'personality': financial_personality(
                savings_monthly_score(total_income, total_expense)
            ),
            'category_analysis': category_expense_analysis(expenses),
            'budget_status': detect_budget_overrun(
                expenses,
                float(getattr(self.profile, 'monthly_budget', None) or total_income * 0.7)
            ),
            'monthly_trends': self._get_monthly_trends(6),
            'goals_progress': self._analyze_goals_progress(),
            'subscription_analysis': self._analyze_subscriptions(),
        }
        
        # Add predictions
        analysis['predictions'] = {
            'next_month_expense': predict_next_month_expenses(analysis['monthly_trends']),
            'recommended_budget': recommended_monthly_budget(total_income, total_expense)
        }
        
        # Update user profile
        self.profile.financial_personality = analysis['personality'].upper()
        self._safe_profile_save(update_fields=['financial_personality'])
        
        # Generate insights and session logs when persistence is available.
        try:
            self._generate_insights(analysis, expenses, incomes)
        except Exception:
            pass
        
        processing_time = (timezone.now() - start_time).total_seconds()
        try:
            self.create_ai_session(
                'DASHBOARD',
                {'month': month.isoformat()},
                processing_time
            )
        except Exception:
            pass
        
        return analysis
    
    def predict_and_prevent_crisis(self) -> List[PredictiveAlert]:
        """Predict cash flow crises and create alerts"""
        start_time = timezone.now()
        
        # Get upcoming transactions (next 45 days)
        forty_five_days_later = timezone.now() + timedelta(days=45)
        
        upcoming_income = list(Income.objects.filter(
            user=self.user,
            date__gte=timezone.now(),
            date__lte=forty_five_days_later
        ).values('date', 'amount'))
        
        upcoming_expenses = list(Expense.objects.filter(
            user=self.user,
            date__gte=timezone.now(),
            date__lte=forty_five_days_later
        ).values('date', 'amount'))
        
        # Backward-compatible scheduled payment extraction:
        # older integrations store scheduled date in transaction metadata.
        candidate_transactions = Transaction.objects.filter(
            account__user=self.user
        ).values('metadata', 'amount')

        window_start = timezone.now().date()
        window_end = forty_five_days_later.date()

        for tx in candidate_transactions:
            metadata = tx.get('metadata') or {}
            scheduled_raw = metadata.get('scheduled_date')
            if not scheduled_raw:
                continue

            scheduled_date = None

            if isinstance(scheduled_raw, datetime):
                scheduled_date = scheduled_raw.date()
            else:
                parsed_dt = parse_datetime(str(scheduled_raw))
                if parsed_dt is not None:
                    if timezone.is_naive(parsed_dt):
                        parsed_dt = timezone.make_aware(parsed_dt, timezone.get_current_timezone())
                    scheduled_date = timezone.localtime(parsed_dt).date()
                else:
                    parsed_d = parse_date(str(scheduled_raw))
                    if parsed_d is not None:
                        scheduled_date = parsed_d

            if scheduled_date and window_start <= scheduled_date <= window_end:
                upcoming_expenses.append({
                    'date': scheduled_date,
                    'amount': tx['amount']
                })
        
        # Get current balance from the user's primary wallet account
        wallet = (
            Wallet.objects.filter(user=self.user, is_active=True)
            .order_by('-is_primary', '-created_at')
            .first()
        )
        current_balance = float(wallet.balance) if wallet else 0.0
        
        # Predict crisis
        crisis_prediction = predict_cashflow_crisis(
            upcoming_income,
            upcoming_expenses,
            current_balance,
            45
        )
        
        alerts = []
        if crisis_prediction.get('has_crisis', False):
            # Create or update predictive alert
            alert, created = PredictiveAlert.objects.update_or_create(
                user=self.user,
                alert_type='CASHFLOW',
                predicted_date=crisis_prediction['crisis_date'],
                defaults={
                    'title': 'Cash Flow Crisis Predicted',
                    'description': f"AI predicts a cash shortfall of ₹{crisis_prediction['shortfall']:,.2f} in {crisis_prediction['days_until']} days.",
                    'predicted_amount': crisis_prediction['shortfall'],
                    'confidence_score': crisis_prediction['confidence'],
                    'mitigation_suggestion': self._generate_crisis_mitigation(
                        crisis_prediction['shortfall'],
                        crisis_prediction['days_until']
                    ),
                    'action_url': '#',
                    'is_active': True
                }
            )
            alerts.append(alert)
            
            # Create insight if not exists
            if created:
                FinancialInsight.objects.create(
                    user=self.user,
                    insight_type='CRISIS',
                    title='Cash Flow Crisis Detected',
                    description=f"Based on upcoming transactions, you may face a cash shortfall of ₹{crisis_prediction['shortfall']:,.2f} in {crisis_prediction['days_until']} days.",
                    severity='HIGH',
                    action_required=True,
                    related_amount=crisis_prediction['shortfall'],
                    action_url='#',
                    metadata=crisis_prediction
                )
            
            # Send notification
            create_notification_event(
                user=self.user,
                source="ANALYTICS_AI",
                event_type="CRISIS_PREDICTION",
                severity="HIGH",
                title="Cash Flow Alert",
                message=f"Cash shortfall predicted in {crisis_prediction['days_until']} days. Click for mitigation plan.",
                action_hint="Review your upcoming expenses and income"
            )
        
        # Log session
        processing_time = (timezone.now() - start_time).total_seconds()
        self.create_ai_session(
            'CRISIS',
            {'days_ahead': 45},
            processing_time
        )
        
        return alerts
    
    def generate_smart_savings_plan(self) -> Dict:
        """Create personalized savings automation plan"""
        # Get last 90 days data for better analysis
        ninety_days_ago = timezone.now() - timedelta(days=90)
        
        expenses = Expense.objects.filter(
            user=self.user,
            date__gte=ninety_days_ago
        ).select_related('budget_category')
        
        incomes = Income.objects.filter(
            user=self.user,
            date__gte=ninety_days_ago
        )
        
        total_income = float(incomes.aggregate(total=Sum('amount'))['total'] or 0)
        avg_monthly_income = total_income / 3 if total_income > 0 else 0
        
        # Analyze user profile for savings plan
        monthly_savings_goal = float(getattr(self.profile, 'monthly_savings_goal', 0) or 0)
        auto_savings_settings = (self.profile.metadata or {}).get('auto_savings', {})
        auto_savings_enabled = bool(auto_savings_settings.get('enabled', False))
        user_profile = {
            'monthly_savings_goal': monthly_savings_goal,
            'risk_tolerance': getattr(self.profile, 'risk_level', 'MEDIUM'),
            'personality': getattr(self.profile, 'financial_personality', 'BALANCED'),
            'auto_savings_enabled': auto_savings_enabled,
        }
        
        savings_plan = smart_savings_automation(
            user_profile,
            expenses,
            avg_monthly_income
        )
        
        # Check goal feasibility
        if monthly_savings_goal > 0:
            goal_analysis = goal_feasibility(
                monthly_savings_goal,
                savings_plan['recommended_savings']
            )
            savings_plan['goal_feasibility'] = goal_analysis
        
        # Update user profile if auto-transfer is recommended
        if savings_plan['auto_transfer'] and not auto_savings_enabled:
            metadata = self.profile.metadata or {}
            metadata['auto_savings'] = {
                'enabled': True,
                'amount': str(Decimal(str(savings_plan['recommended_savings']))),
                'frequency': str(savings_plan.get('frequency', 'MONTHLY')).upper(),
            }
            self.profile.metadata = metadata
            self.profile.save()
            
            # Create insight about auto-savings
            FinancialInsight.objects.create(
                user=self.user,
                insight_type='SAVINGS',
                title='Auto-Savings Recommended',
                description=f"AI recommends auto-saving ₹{savings_plan['recommended_savings']:,.2f} {savings_plan['frequency']} based on your spending patterns.",
                severity='MEDIUM',
                action_required=True,
                related_amount=savings_plan['recommended_savings'],
                action_url=reverse('autopilot:savings')
            )
        
        return savings_plan
    
    def execute_smart_rules(self, transaction: Transaction = None) -> List[Dict]:
        """Execute user's smart rules in response to events"""
        triggered_rules = []
        active_rules = SmartRule.objects.filter(
            user=self.user, 
            is_active=True
        ).order_by('-priority')
        
        for rule in active_rules:
            try:
                if self._evaluate_rule(rule, transaction):
                    action_result = self._execute_rule_action(rule, transaction)
                    
                    triggered_rules.append({
                        'rule_id': rule.id,
                        'rule_name': rule.name,
                        'action_type': rule.action_type,
                        'result': action_result,
                        'triggered_at': timezone.now()
                    })
                    
                    # Update rule statistics
                    rule.execution_count += 1
                    rule.last_triggered = timezone.now()
                    rule.last_success = action_result.get('success', False)
                    rule.save()
                    
                    # Create autopilot decision record
                    AutopilotDecision.objects.create(
                        user=self.user,
                        trigger_type='SMART_RULE',
                        action_taken=json.dumps({
                            'rule': rule.name,
                            'action': rule.action_type,
                            'result': action_result
                        }),
                        status='COMPLETED' if action_result.get('success', False) else 'FAILED',
                        metadata={
                            'rule_id': rule.id,
                            'transaction_id': transaction.id if transaction else None,
                            'triggered_rules': triggered_rules
                        }
                    )
                    
            except Exception as e:
                # Log error but continue with other rules
                FinancialInsight.objects.create(
                    user=self.user,
                    insight_type='RISK',
                    title='Smart Rule Execution Failed',
                    description=f"Rule '{rule.name}' failed to execute: {str(e)}",
                    severity='MEDIUM',
                    action_required=False,
                    metadata={'rule_id': rule.id, 'error': str(e)}
                )
                continue
        
        return triggered_rules
    
    def calculate_financial_health(self) -> Tuple[int, str, Dict]:
        """Calculate comprehensive financial health score"""
        # Gather all required data
        user_data = {}
        
        # 1. Savings Rate
        analysis = self.analyze_monthly_finances()
        user_data['savings_rate'] = analysis['basic_metrics']['savings_rate']
        
        # 2. Emergency Fund (in months)
        try:
            # Treat any dedicated savings account as emergency fund
            savings_wallet = (
                Wallet.objects.filter(
                    user=self.user,
                    account_type__in=['SAVINGS', 'WALLET'],
                    is_active=True,
                )
                .order_by('-account_type', '-created_at')
                .first()
            )
            emergency_fund = float(savings_wallet.balance) if savings_wallet else 0.0
            monthly_expense = analysis['basic_metrics']['total_expense']
            user_data['emergency_fund_months'] = (
                emergency_fund / monthly_expense if monthly_expense > 0 else 0
            )
        except Exception:
            user_data['emergency_fund_months'] = 0.0
        
        # 3. Debt-to-Income Ratio (placeholder - integrate with loans app)
        user_data['debt_to_income'] = 0.1  # Default
        
        # 4. Credit Utilization (placeholder)
        user_data['credit_utilization'] = 0.3  # Default
        
        # 5. Spending Consistency
        user_data['spending_consistency'] = self._calculate_spending_consistency()
        
        # 6. Investment Ratio
        user_data['investment_ratio'] = self._calculate_investment_ratio()
        
        # Calculate score
        score, grade, breakdown = calculate_financial_health_score(user_data)
        for key, values in breakdown.items():
            if isinstance(values, dict) and 'score' not in values:
                values['score'] = values.get('points', 0)
                values.setdefault('name', key.replace('_', ' ').title())
        
        # Update user profile
        metadata = self.profile.metadata or {}
        metadata['financial_health'] = {
            'score': score,
            'grade': grade,
            'updated_at': timezone.now().isoformat(),
        }
        self.profile.metadata = metadata
        self._safe_profile_save(update_fields=['metadata'])
        
        # Create insight if score is low
        if score < 600:
            try:
                FinancialInsight.objects.create(
                    user=self.user,
                    insight_type='RISK',
                    title='Low Financial Health Score',
                    description=f"Your financial health score is {score}/1000 ({grade}). Consider improving your savings and reducing debt.",
                    severity='MEDIUM',
                    action_required=True,
                    related_amount=score,
                    action_url=reverse('analytics-ai:financial_health_dashboard')
                )
            except Exception:
                pass
        
        return score, grade, breakdown
    
    def detect_income_opportunities(self) -> List[Dict]:
        """Detect income opportunities based on spending patterns"""
        # Get last 60 days of expenses
        sixty_days_ago = timezone.now() - timedelta(days=60)
        
        expenses = Expense.objects.filter(
            user=self.user,
            date__gte=sixty_days_ago
        ).select_related('budget_category')
        
        opportunities = detect_income_opportunity(expenses)
        
        # Store opportunities as insights
        for opp in opportunities:
            FinancialInsight.objects.create(
                user=self.user,
                insight_type='OPPORTUNITY',
                title=f"Income Opportunity: {opp['platform']}",
                description=opp['rationale'],
                severity='LOW',
                action_required=False,
                related_amount=opp['estimated_earning'],
                metadata=opp
            )
        
        return opportunities

    def analyze_spending_patterns(self) -> Dict:
        """Analyze spending behavior for report views."""
        window_start = timezone.now() - timedelta(days=90)
        expenses = Expense.objects.filter(user=self.user, date__gte=window_start)

        total_spending = float(expenses.aggregate(total=Sum('amount'))['total'] or 0)
        tx_count = expenses.count()
        avg_transaction = (total_spending / tx_count) if tx_count else 0

        top_categories = list(
            expenses.values('category').annotate(
                total=Sum('amount'),
                count=Count('id')
            ).order_by('-total')[:5]
        )

        return {
            'period_days': 90,
            'total_spending': round(total_spending, 2),
            'transaction_count': tx_count,
            'avg_transaction': round(avg_transaction, 2),
            'top_categories': top_categories,
        }

    def analyze_investment_portfolio(self) -> Dict:
        """Summarize current investment portfolio and generate recommendations."""
        investments = Investment.objects.filter(user=self.user, status='ACTIVE')
        total_invested = float(investments.aggregate(total=Sum('invested_amount'))['total'] or 0)
        total_current = float(investments.aggregate(total=Sum('current_value'))['total'] or 0)
        total_return = total_current - total_invested
        return_pct = (total_return / total_invested * 100) if total_invested else 0

        recommendations = []
        risk_level = getattr(self.profile, 'risk_level', 'MEDIUM')
        if total_invested == 0:
            recommendations.append({
                'title': 'Start SIP Investing',
                'description': 'Begin with a diversified mutual fund SIP to build long-term discipline.',
                'expected_return': '8-12',
                'timeframe': '3-5 years',
                'icon': 'fa-piggy-bank',
            })
        elif risk_level == 'LOW':
            recommendations.append({
                'title': 'Increase Fixed-Income Allocation',
                'description': 'Add low-volatility debt or fixed-income instruments for stability.',
                'expected_return': '6-8',
                'timeframe': '2-4 years',
                'icon': 'fa-shield-alt',
            })
        elif risk_level == 'HIGH':
            recommendations.append({
                'title': 'Review Equity Concentration',
                'description': 'Rebalance concentrated holdings into diversified index exposure.',
                'expected_return': '10-14',
                'timeframe': '5+ years',
                'icon': 'fa-chart-line',
            })
        else:
            recommendations.append({
                'title': 'Maintain Balanced Portfolio',
                'description': 'Keep a balanced mix across equity and debt aligned to your goals.',
                'expected_return': '8-11',
                'timeframe': '3-5 years',
                'icon': 'fa-balance-scale',
            })

        return {
            'total_invested': round(total_invested, 2),
            'current_value': round(total_current, 2),
            'total_return': round(total_return, 2),
            'return_percentage': round(return_pct, 2),
            'recommendations': recommendations,
        }

    def analyze_debt_situation(self) -> Dict:
        """Analyze debt obligations and repayment burden."""
        debts = Debt.objects.filter(user=self.user, status='ACTIVE')
        total_debt = float(debts.aggregate(total=Sum('remaining_amount'))['total'] or 0)
        avg_interest = float(debts.aggregate(avg=Avg('interest_rate'))['avg'] or 0)
        monthly_emi = float(debts.aggregate(total=Sum('emi_amount'))['total'] or 0)

        monthly_income = float(getattr(self.profile, 'monthly_income', 0) or 0)
        if monthly_income <= 0:
            recent_income = Income.objects.filter(
                user=self.user,
                date__gte=timezone.now().date() - timedelta(days=90)
            ).aggregate(total=Sum('amount'))['total'] or 0
            monthly_income = float(recent_income) / 3 if recent_income else 0

        debt_to_income = (monthly_emi / monthly_income * 100) if monthly_income > 0 else 0
        return {
            'total_debt': round(total_debt, 2),
            'debt_to_income': round(debt_to_income, 2),
            'avg_interest': round(avg_interest, 2),
            'monthly_emi': round(monthly_emi, 2),
        }

    def generate_tax_planning_advice(self) -> Dict:
        """Generate high-level tax planning estimates and actions."""
        year_start = timezone.now().date().replace(month=4, day=1)
        yearly_income = float(
            Income.objects.filter(user=self.user, date__gte=year_start).aggregate(
                total=Sum('amount')
            )['total'] or 0
        )
        potential_savings = round(min(yearly_income * 0.05, 150000), 2) if yearly_income > 0 else 0
        return {
            'potential_savings': potential_savings,
            'recommended_actions': [
                'Review 80C utilization and maximize eligible deductions.',
                'Check 80D health insurance deduction eligibility.',
                'Evaluate NPS additional contribution under 80CCD(1B).',
            ],
        }

    def generate_retirement_plan(self) -> Dict:
        """Return retirement readiness snapshot for report rendering."""
        total_current = float(
            Investment.objects.filter(user=self.user, status='ACTIVE').aggregate(
                total=Sum('current_value')
            )['total'] or 0
        )
        monthly_income = float(getattr(self.profile, 'monthly_income', 0) or 0)
        age = int((self.profile.metadata or {}).get('age', 30))
        years_to_retirement = max(60 - age, 1)

        annual_income = monthly_income * 12
        target_corpus = annual_income * 20 if annual_income > 0 else 0
        readiness_ratio = (total_current / target_corpus * 100) if target_corpus > 0 else 0
        score = max(0, min(100, round(readiness_ratio)))

        monthly_required = 0
        if target_corpus > total_current:
            monthly_required = (target_corpus - total_current) / max(years_to_retirement * 12, 1)

        return {
            'score': score,
            'current_corpus': round(total_current, 2),
            'target_corpus': round(target_corpus, 2),
            'years_to_retirement': years_to_retirement,
            'monthly_required': round(monthly_required, 2),
        }
    
    def generate_weekly_report(self) -> Dict:
        """Generate weekly financial report"""
        week_ago = timezone.now() - timedelta(days=7)
        
        weekly_expenses = Expense.objects.filter(
            user=self.user,
            date__gte=week_ago
        )
        
        weekly_income = Income.objects.filter(
            user=self.user,
            date__gte=week_ago
        )
        
        total_income = float(weekly_income.aggregate(total=Sum('amount'))['total'] or 0)
        total_expense = float(weekly_expenses.aggregate(total=Sum('amount'))['total'] or 0)
        
        # Category breakdown
        category_data = category_expense_analysis(weekly_expenses)
        
        # Compare with previous week
        two_weeks_ago = timezone.now() - timedelta(days=14)
        prev_week_expenses = Expense.objects.filter(
            user=self.user,
            date__gte=two_weeks_ago,
            date__lt=week_ago
        )
        
        prev_total = float(prev_week_expenses.aggregate(total=Sum('amount'))['total'] or 0)
        spending_change = ((total_expense - prev_total) / prev_total * 100) if prev_total > 0 else 0
        
        report = {
            'period': {
                'start': week_ago,
                'end': timezone.now(),
                'week_number': week_ago.isocalendar()[1]
            },
            'income': total_income,
            'expenses': total_expense,
            'net': total_income - total_expense,
            'top_categories': category_data[:3],
            'spending_change_percent': spending_change,
            'daily_average': total_expense / 7,
            'alerts_generated': FinancialInsight.objects.filter(
                user=self.user,
                created_at__gte=week_ago
            ).count(),
            'goals_progress': self._get_weekly_goals_progress()
        }
        
        return report

    # PUBLIC COMPATIBILITY METHODS FOR LEGACY VIEWS

    def generate_investment_recommendations(self) -> List[Dict]:
        """Compatibility wrapper for legacy dashboard cards."""
        return self.analyze_investment_portfolio().get('recommendations', [])

    def assess_financial_risk(self) -> Dict:
        """Return normalized risk summary expected by templates."""
        score, _, breakdown = self.calculate_financial_health()
        risk_score = int(max(0, min(100, 100 - (score / 10))))

        if risk_score < 30:
            level = 'Low'
        elif risk_score < 60:
            level = 'Moderate'
        else:
            level = 'High'

        def _to_severity(status):
            status = (status or '').lower()
            if status in {'poor', 'needs improvement'}:
                return 'High'
            if status in {'fair'}:
                return 'Medium'
            return 'Low'

        factors = []
        for key, value in (breakdown or {}).items():
            if not isinstance(value, dict):
                continue
            severity = _to_severity(value.get('status'))
            factors.append({
                'name': value.get('name', key.replace('_', ' ').title()),
                'severity': severity,
                'impact': severity,
                'status': value.get('status'),
            })

        top_factor = next((f for f in factors if f['severity'] == 'High'), None) or (factors[0] if factors else None)
        liquidity_risk = 'High' if any(f['name'].lower().startswith('emergency') and f['severity'] == 'High' for f in factors) else ('Moderate' if level == 'Moderate' else 'Low')
        market_risk = 'High' if getattr(self.profile, 'risk_level', 'MEDIUM') == 'HIGH' else ('Moderate' if level == 'Moderate' else 'Low')

        return {
            'score': risk_score,
            'level': level,
            'liquidity_risk': liquidity_risk,
            'market_risk': market_risk,
            'factors': factors[:6],
            'top_risk': (top_factor or {}).get('name', 'General spending discipline'),
        }

    def detect_anomalies(self) -> List[Dict]:
        """Detect unusual expenses over last 90 days."""
        window_start = timezone.now().date() - timedelta(days=90)
        expenses = list(
            Expense.objects.filter(user=self.user, date__gte=window_start)
            .values('id', 'date', 'amount', 'category', 'description')
            .order_by('-date')
        )
        if not expenses:
            return []

        amounts = [float(item['amount'] or 0) for item in expenses]
        avg_amount = sum(amounts) / len(amounts)
        high_threshold = avg_amount * 1.9
        medium_threshold = avg_amount * 1.5

        anomalies = []
        for item in expenses:
            amount = float(item['amount'] or 0)
            if amount >= high_threshold and amount > 0:
                severity = 'HIGH'
            elif amount >= medium_threshold and amount > 0:
                severity = 'MEDIUM'
            else:
                continue

            anomalies.append({
                'id': str(item['id']),
                'title': 'Unusual spending detected',
                'description': item.get('description') or f"Unexpected {item.get('category', 'expense')} amount",
                'severity': severity,
                'amount': item['amount'],
                'date': item['date'],
                'type': 'EXPENSE_SPIKE',
            })
        return anomalies[:10]

    def predict_cashflow(self, days: int = 30) -> Dict:
        """Project near-term cashflow for 30/60/90-day cards."""
        days = max(1, int(days or 30))
        today = timezone.now().date()
        lookback_start = today - timedelta(days=90)

        total_income = float(
            Income.objects.filter(user=self.user, date__gte=lookback_start).aggregate(total=Sum('amount'))['total'] or 0
        )
        total_expense = float(
            Expense.objects.filter(user=self.user, date__gte=lookback_start).aggregate(total=Sum('amount'))['total'] or 0
        )

        wallet = (
            Wallet.objects.filter(user=self.user, is_active=True)
            .order_by('-is_primary', '-created_at')
            .first()
        )
        current_balance = float(wallet.balance) if wallet else 0.0

        daily_income = total_income / 90 if total_income else 0.0
        daily_expense = total_expense / 90 if total_expense else 0.0
        daily_net = daily_income - daily_expense

        def _projection(period_days):
            return round(current_balance + (daily_net * period_days), 2)

        projected_30 = _projection(30)
        projected_60 = _projection(60)
        projected_90 = _projection(90)
        low_period_days = 90 if daily_net < 0 else 0
        lowest_point = _projection(low_period_days)
        lowest_date = today + timedelta(days=low_period_days)

        return {
            'current_balance': round(current_balance, 2),
            'daily_net': round(daily_net, 2),
            'next_30_days': projected_30,
            'next_60_days': projected_60,
            'next_90_days': projected_90,
            'lowest_point': lowest_point,
            'lowest_date': lowest_date,
            'confidence': min(95, max(60, int(60 + min(days, 90) / 2))),
        }

    def predict_expense_categories(self) -> Dict:
        """Predict category-wise increase/decrease tendencies."""
        today = timezone.now().date()
        current_start = today - timedelta(days=90)
        previous_start = today - timedelta(days=180)

        current = {
            row['category']: float(row['total'] or 0)
            for row in Expense.objects.filter(user=self.user, date__gte=current_start).values('category').annotate(total=Sum('amount'))
        }
        previous = {
            row['category']: float(row['total'] or 0)
            for row in Expense.objects.filter(user=self.user, date__gte=previous_start, date__lt=current_start).values('category').annotate(total=Sum('amount'))
        }

        increasing = []
        decreasing = []
        all_categories = set(current.keys()) | set(previous.keys())
        for category in all_categories:
            cur = current.get(category, 0.0)
            prev = previous.get(category, 0.0)
            if prev <= 0 and cur > 0:
                change = 100.0
            elif prev <= 0:
                change = 0.0
            else:
                change = ((cur - prev) / prev) * 100

            item = {
                'name': category or 'OTHER',
                'change': round(change, 1),
                'current_amount': round(cur, 2),
            }
            if change >= 0:
                item['increase'] = round(change, 1)
                increasing.append(item)
            else:
                item['decrease'] = round(abs(change), 1)
                decreasing.append(item)

        increasing.sort(key=lambda x: x.get('increase', 0), reverse=True)
        decreasing.sort(key=lambda x: x.get('decrease', 0), reverse=True)
        return {
            'increasing': increasing[:5],
            'decreasing': decreasing[:5],
        }

    def predict_income_trends(self) -> Dict:
        """Predict short-term income trend from rolling monthly totals."""
        today = timezone.now().date()
        month_series = []
        for offset in range(5, -1, -1):
            pivot = (today.replace(day=1) - timedelta(days=30 * offset))
            total = float(
                Income.objects.filter(
                    user=self.user,
                    date__year=pivot.year,
                    date__month=pivot.month,
                ).aggregate(total=Sum('amount'))['total'] or 0
            )
            month_series.append({
                'month': pivot.strftime('%b %Y'),
                'amount': round(total, 2),
            })

        first = month_series[0]['amount'] if month_series else 0
        last = month_series[-1]['amount'] if month_series else 0
        growth = ((last - first) / first * 100) if first > 0 else 0

        return {
            'growth_rate': round(growth, 2),
            'projected_next_month': round(last * (1 + growth / 100), 2) if month_series else 0,
            'history': month_series,
            'confidence': min(95, max(55, 55 + len([m for m in month_series if m['amount'] > 0]) * 6)),
        }

    def analyze_financial_trends(self) -> Dict:
        """Return compact trend KPIs for predictive dashboard."""
        today = timezone.now().date()
        current_start = today - timedelta(days=90)
        previous_start = today - timedelta(days=180)

        current_income = float(
            Income.objects.filter(user=self.user, date__gte=current_start).aggregate(total=Sum('amount'))['total'] or 0
        )
        previous_income = float(
            Income.objects.filter(user=self.user, date__gte=previous_start, date__lt=current_start).aggregate(total=Sum('amount'))['total'] or 0
        )
        current_expense = float(
            Expense.objects.filter(user=self.user, date__gte=current_start).aggregate(total=Sum('amount'))['total'] or 0
        )
        previous_expense = float(
            Expense.objects.filter(user=self.user, date__gte=previous_start, date__lt=current_start).aggregate(total=Sum('amount'))['total'] or 0
        )

        def _growth(current, previous):
            if previous <= 0:
                return 0.0
            return round(((current - previous) / previous) * 100, 2)

        current_savings = current_income - current_expense
        previous_savings = previous_income - previous_expense

        return {
            'income_growth': _growth(current_income, previous_income),
            'expense_growth': _growth(current_expense, previous_expense),
            'savings_growth': _growth(current_savings, previous_savings),
        }

    def analyze_seasonality_patterns(self) -> Dict:
        """Build 4-season spending summary for seasonality cards."""
        month_totals = {
            row['date__month']: float(row['total'] or 0)
            for row in Expense.objects.filter(user=self.user).values('date__month').annotate(total=Sum('amount'))
        }
        global_average = sum(month_totals.values()) / len(month_totals) if month_totals else 1.0

        season_map = [
            ('Spring', [3, 4, 5], 'Mar-May', 'seedling', '#22c55e'),
            ('Summer', [6, 7, 8], 'Jun-Aug', 'sun', '#f59e0b'),
            ('Monsoon', [9, 10, 11], 'Sep-Nov', 'cloud-rain', '#3b82f6'),
            ('Winter', [12, 1, 2], 'Dec-Feb', 'snowflake', '#64748b'),
        ]

        patterns = []
        for name, months, period, icon, color in season_map:
            values = [month_totals.get(m, 0.0) for m in months]
            avg_spending = sum(values) / len(values) if values else 0.0
            variance = ((avg_spending - global_average) / global_average * 100) if global_average > 0 else 0
            patterns.append({
                'name': name,
                'period': period,
                'icon': icon,
                'color': color,
                'avg_spending': round(avg_spending, 2),
                'variance': round(variance, 1),
            })

        return {'patterns': patterns}

    def generate_health_improvement_suggestions(self) -> List[Dict]:
        """Actionable recommendations for health dashboard."""
        _, _, breakdown = self.calculate_financial_health()
        suggestions = []

        mapping = {
            'savings_rate': (
                'Improve savings rate',
                'Automate a fixed monthly transfer to savings right after income credit.',
                'HIGH',
                18,
            ),
            'emergency_fund': (
                'Build emergency fund',
                'Target 3-6 months of expenses in a liquid savings account.',
                'HIGH',
                16,
            ),
            'debt_ratio': (
                'Reduce debt burden',
                'Prioritize highest-interest debt to reduce monthly outflow faster.',
                'MEDIUM',
                14,
            ),
            'credit_utilization': (
                'Lower credit utilization',
                'Keep utilization below 30% to improve financial flexibility.',
                'MEDIUM',
                12,
            ),
            'spending_consistency': (
                'Stabilize monthly spending',
                'Set category-wise weekly limits for discretionary purchases.',
                'LOW',
                10,
            ),
            'investment_ratio': (
                'Increase goal-based investing',
                'Allocate a small SIP amount consistently to long-term goals.',
                'LOW',
                9,
            ),
        }

        for key, data in (breakdown or {}).items():
            status = str((data or {}).get('status', '')).lower()
            if status in {'excellent', 'good'}:
                continue
            title, desc, priority, impact = mapping.get(
                key,
                ('Improve financial discipline', 'Review spending and automate goal-based saving.', 'MEDIUM', 10),
            )
            suggestions.append({
                'title': title,
                'description': desc,
                'priority': priority,
                'impact_score': impact,
            })

        if not suggestions:
            suggestions.append({
                'title': 'Maintain your momentum',
                'description': 'Your financial profile is healthy. Keep your current strategy consistent.',
                'priority': 'LOW',
                'impact_score': 6,
            })
        return suggestions[:8]

    def analyze_health_trends(self) -> Dict:
        """Trend deltas for health score panel."""
        score, _, _ = self.calculate_financial_health()
        history = (self.profile.metadata or {}).get('health_history', [])
        history_scores = [int(item.get('score', 0)) for item in history if isinstance(item, dict)]
        history_scores.append(int(score))

        def _pct_change(window):
            if len(history_scores) < window + 1:
                return 0
            start = history_scores[-(window + 1)]
            end = history_scores[-1]
            if start <= 0:
                return 0
            return round(((end - start) / start) * 100, 1)

        return {
            'three_month': _pct_change(3),
            'six_month': _pct_change(6),
            'one_year': _pct_change(12),
        }

    def get_health_benchmark(self) -> Dict:
        """Return benchmark comparison block for financial health page."""
        score, _, breakdown = self.calculate_financial_health()
        percentile = int(max(1, min(99, (score / 10))))
        categories = {
            key.replace('_', ' ').title(): int((value or {}).get('score', 0))
            for key, value in (breakdown or {}).items()
            if isinstance(value, dict)
        }
        return {
            'peer_average': 680,
            'age_group_avg': 695,
            'income_bracket_avg': 710,
            'percentile': percentile,
            'categories': categories,
        }

    def generate_health_action_plan(self) -> Dict:
        """Generate staged action plan for health improvement."""
        suggestions = self.generate_health_improvement_suggestions()
        today = timezone.now().date()

        immediate = []
        for idx, item in enumerate(suggestions[:3], start=1):
            immediate.append({
                'title': item['title'],
                'description': item['description'],
                'due_date': today + timedelta(days=idx * 10),
                'difficulty': 'warning' if item['priority'] == 'HIGH' else ('info' if item['priority'] == 'MEDIUM' else 'success'),
            })

        short_term = []
        for idx, item in enumerate(suggestions[1:4], start=1):
            short_term.append({
                'title': f"Consolidate: {item['title']}",
                'description': f"Track weekly progress on {item['title'].lower()} and adjust targets.",
                'target_date': today + timedelta(days=30 + idx * 20),
                'priority': item['priority'],
            })

        long_term = [
            {
                'title': 'Build resilient cash buffer',
                'description': 'Grow emergency reserves to cover at least 6 months of expenses.',
                'timeline': '3-6 months',
                'expected_impact': '+20',
            },
            {
                'title': 'Optimize debt and credit mix',
                'description': 'Reduce expensive debt and keep utilization controlled.',
                'timeline': '4-8 months',
                'expected_impact': '+15',
            },
            {
                'title': 'Increase long-term investments',
                'description': 'Gradually raise SIP/allocation for long-term wealth goals.',
                'timeline': '6-12 months',
                'expected_impact': '+18',
            },
        ]

        return {
            'immediate': immediate,
            'short_term': short_term,
            'long_term': long_term,
        }

    def generate_crisis_mitigation_plan(self, alert) -> Dict:
        """Build actionable mitigation plan for a cashflow alert."""
        shortfall = float(getattr(alert, 'predicted_amount', 0) or 0)
        steps = [
            {
                'id': 'cut_discretionary',
                'title': 'Pause discretionary spending',
                'description': 'Temporarily reduce non-essential spends for the next two weeks.',
                'priority': 'HIGH',
                'timeline': 'Immediate',
                'impact': round(shortfall * 0.2, 2),
                'action_required': True,
            },
            {
                'id': 'shift_due_dates',
                'title': 'Reschedule near-term dues',
                'description': 'Move low-priority bill due dates where possible to reduce immediate pressure.',
                'priority': 'MEDIUM',
                'timeline': '2-3 days',
                'impact': round(shortfall * 0.25, 2),
                'action_required': True,
            },
            {
                'id': 'activate_buffer',
                'title': 'Use emergency/liquid buffer',
                'description': 'Use liquid savings or low-cost credit line as temporary buffer.',
                'priority': 'MEDIUM',
                'timeline': '3-5 days',
                'impact': round(shortfall * 0.35, 2),
                'action_required': True,
            },
            {
                'id': 'income_boost',
                'title': 'Add short-term income',
                'description': 'Identify one short-cycle income source to close any remaining gap.',
                'priority': 'LOW',
                'timeline': '1-2 weeks',
                'impact': round(shortfall * 0.2, 2),
                'action_required': False,
            },
        ]
        total_impact = round(sum(step['impact'] for step in steps), 2)
        stress_level = int(max(25, min(95, 35 + (shortfall / 1000))))
        return {
            'steps': steps,
            'total_impact': total_impact,
            'stress_level': stress_level,
        }

    def generate_alternative_solutions(self) -> List[Dict]:
        """Alternative options for crisis card section."""
        return [
            {
                'id': 'alt_savings',
                'title': 'Temporary savings drawdown',
                'description': 'Use a capped amount from liquid savings and replenish over 60 days.',
                'type': 'savings',
                'amount': 15000,
            },
            {
                'id': 'alt_loan',
                'title': 'Low-cost short-term credit',
                'description': 'Use a low-interest line only for unavoidable obligations.',
                'type': 'loan',
                'amount': 30000,
            },
            {
                'id': 'alt_income',
                'title': 'Supplemental income sprint',
                'description': 'Take a short-cycle gig to bridge immediate cashflow gap.',
                'type': 'income',
                'amount': 12000,
            },
        ]

    def optimize_resource_allocation(self) -> Dict:
        """Liquidity map used in mitigation page."""
        today = timezone.now().date()
        month_start = today.replace(day=1)

        wallet = (
            Wallet.objects.filter(user=self.user, is_active=True)
            .order_by('-is_primary', '-created_at')
            .first()
        )
        current_liquidity = float(wallet.balance) if wallet else 0.0
        monthly_expense = float(
            Expense.objects.filter(user=self.user, date__gte=month_start).aggregate(total=Sum('amount'))['total'] or 0
        )
        required_liquidity = max(monthly_expense * 1.2, 10000.0)
        gap = max(required_liquidity - current_liquidity, 0.0)

        investments_total = float(
            Investment.objects.filter(user=self.user, status='ACTIVE').aggregate(total=Sum('current_value'))['total'] or 0
        )
        savings = round(current_liquidity * 0.5, 2)
        fd = round(current_liquidity * 0.3, 2)
        credit_available = round(required_liquidity * 0.35, 2)
        investments = round(investments_total * 0.15, 2)
        total = round(savings + fd + credit_available + investments, 2)

        return {
            'current_liquidity': round(current_liquidity, 2),
            'required_liquidity': round(required_liquidity, 2),
            'gap': round(gap, 2),
            'savings': savings,
            'fd': fd,
            'credit_available': credit_available,
            'investments': investments,
            'total': total,
        }

    def generate_recovery_timeline(self) -> Dict:
        """Recovery milestone timeline for crisis page."""
        today = timezone.now().date()
        crisis_date = today + timedelta(days=7)
        stabilization_date = today + timedelta(days=30)
        recovery_date = today + timedelta(days=60)
        milestones = [
            {
                'description': 'Immediate expense controls active',
                'date': today + timedelta(days=3),
                'achieved': False,
                'progress': 25,
            },
            {
                'description': 'Cashflow stabilized with reduced burn',
                'date': stabilization_date,
                'achieved': False,
                'progress': 55,
            },
            {
                'description': 'Normal buffer restored',
                'date': recovery_date,
                'achieved': False,
                'progress': 85,
            },
        ]
        return {
            'crisis_date': crisis_date,
            'stabilization_date': stabilization_date,
            'recovery_date': recovery_date,
            'milestones': milestones,
        }
     
    # PRIVATE HELPER METHODS
    
    def _evaluate_rule(self, rule: SmartRule, transaction: Transaction = None) -> bool:
        """Evaluate if a rule's condition is met"""
        condition_type = rule.condition_type
        condition_value = rule.condition_value
        
        if condition_type == 'BALANCE':
            # Check primary wallet balance
            wallet = (
                Wallet.objects.filter(user=self.user, is_active=True)
                .order_by('-is_primary', '-created_at')
                .first()
            )
            if not wallet:
                return False

            threshold = Decimal(str(condition_value.get('threshold', 0)))
            condition = condition_value.get('condition', 'below')

            if condition == 'below':
                return wallet.balance <= threshold
            return wallet.balance >= threshold
        
        elif condition_type == 'SPENDING':
            # Check if spending exceeds threshold for period
            period = condition_value.get('period', 'daily')
            threshold = Decimal(str(condition_value.get('threshold', 0)))
            
            if period == 'daily':
                start_time = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
                total_spent = Expense.objects.filter(
                    user=self.user,
                    date__gte=start_time
                ).aggregate(total=Sum('amount'))['total'] or 0
            
            elif period == 'weekly':
                start_time = timezone.now() - timedelta(days=7)
                total_spent = Expense.objects.filter(
                    user=self.user,
                    date__gte=start_time
                ).aggregate(total=Sum('amount'))['total'] or 0
            
            elif period == 'monthly':
                start_time = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                total_spent = Expense.objects.filter(
                    user=self.user,
                    date__gte=start_time
                ).aggregate(total=Sum('amount'))['total'] or 0
            
            return total_spent >= threshold
        
        elif condition_type == 'CATEGORY' and transaction:
            # Check category spending limit
            category_name = condition_value.get('category')
            limit = Decimal(str(condition_value.get('limit', 0)))
            
            if transaction.category and transaction.category == category_name:
                # Check monthly spending in this category
                month_start = timezone.now().replace(day=1, hour=0, minute=0, second=0)
                category_spent = Expense.objects.filter(
                    user=self.user,
                    category=transaction.category,
                    date__gte=month_start
                ).aggregate(total=Sum('amount'))['total'] or 0
                
                # Include current transaction
                category_spent += transaction.amount
                
                return category_spent > limit
        
        elif condition_type == 'TIME':
            # Time-based rules (e.g., every Friday, end of month)
            schedule = condition_value.get('schedule', {})
            schedule_type = schedule.get('type')
            
            if schedule_type == 'DAY_OF_WEEK':
                target_day = schedule.get('day')
                current_day = timezone.now().weekday()  # Monday=0, Sunday=6
                return current_day == target_day
            
            elif schedule_type == 'DAY_OF_MONTH':
                target_day = schedule.get('day')
                current_day = timezone.now().day
                return current_day == target_day
            
            elif schedule_type == 'END_OF_MONTH':
                current_day = timezone.now().day
                days_in_month = 30  # Simplified
                return current_day >= days_in_month - 3  # Last 3 days
        
        return False
    
    def _execute_rule_action(self, rule: SmartRule, transaction: Transaction = None) -> Dict:
        """Execute the action associated with a rule"""
        action_type = rule.action_type
        action_value = rule.action_value
        
        try:
            if action_type == 'SAVE':
                # Auto‑save to a savings‑type wallet
                amount = Decimal(str(action_value.get('amount', 0)))
                from_wallet = (
                    Wallet.objects.filter(self.user, account_type='WALLET', is_active=True)
                    .order_by('-is_primary', '-created_at')
                    .first()
                )
                to_wallet, _ = Wallet.objects.get_or_create(
                    user=self.user,
                    account_type='SAVINGS',
                    defaults={
                        'balance': Decimal('0.00'),
                        'available_balance': Decimal('0.00'),
                        'currency': 'INR',
                        'account_number': Wallet.generate_account_number(),
                        'is_active': True,
                    },
                )

                if not from_wallet or from_wallet.balance < amount:
                    return {
                        'success': False,
                        'message': 'Insufficient balance for auto‑save',
                    }

                # Create transfer-style transaction (debit)
                transfer = Transaction.objects.create(
                    account=from_wallet,
                    amount=amount,
                    transaction_type='DEBIT',
                    description=f'Auto-save: {rule.name}',
                    reference=f'RULE-SAVE-{rule.id}',
                    balance_before=from_wallet.balance,
                    balance_after=from_wallet.balance - amount,
                    metadata={'rule_id': str(rule.id), 'target_account_id': str(to_wallet.id)},
                )

                # Update balances
                from_wallet.update_balance(-amount)
                to_wallet.update_balance(amount)

                return {
                    'success': True,
                    'message': f'Auto-saved ₹{amount}',
                    'transaction_id': transfer.id,
                    'amount_saved': float(amount),
                }
            
            elif action_type == 'ALERT':
                # Send notification
                message = action_value.get('message', f'Rule triggered: {rule.name}')
                create_notification_event(
                    user=self.user,
                    source="SMART_RULE",
                    event_type="RULE_TRIGGERED",
                    title=f"Rule: {rule.name}",
                    message=message,
                    action_hint="Review your finances"
                )
                return {'success': True, 'message': 'Notification sent'}
            
            elif action_type == 'BLOCK' and transaction:
                # Block transaction
                transaction.status = 'BLOCKED'
                transaction.notes = f'Blocked by rule: {rule.name}'
                transaction.save()
                
                create_notification_event(
                    user=self.user,
                    source="SMART_RULE",
                    event_type="TRANSACTION_BLOCKED",
                    severity="HIGH",
                    title="Transaction Blocked",
                    message=f"Transaction of ₹{transaction.amount} blocked by rule '{rule.name}'",
                    action_hint="Review transaction details"
                )
                
                return {
                    'success': True,
                    'message': 'Transaction blocked',
                    'transaction_id': transaction.id
                }
            
            elif action_type == 'TRANSFER':
                # Transfer between wallets (by account_type)
                from_type = action_value.get('from_wallet', 'WALLET')
                to_type = action_value.get('to_wallet', 'SAVINGS')
                amount = Decimal(str(action_value.get('amount', 0)))

                from_wallet = Wallet.objects.filter(
                    user=self.user, account_type=from_type, is_active=True
                ).first()
                to_wallet = Wallet.objects.filter(
                    user=self.user, account_type=to_type, is_active=True
                ).first()

                if not from_wallet or not to_wallet or from_wallet.balance < amount:
                    return {
                        'success': False,
                        'message': 'Unable to complete transfer – check balances and wallet types',
                    }

                transfer = Transaction.objects.create(
                    account=from_wallet,
                    amount=amount,
                    transaction_type='DEBIT',
                    description=f'Rule transfer: {rule.name}',
                    reference=f'RULE-XFER-{rule.id}',
                    balance_before=from_wallet.balance,
                    balance_after=from_wallet.balance - amount,
                    metadata={
                        'rule_id': str(rule.id),
                        'to_account_id': str(to_wallet.id),
                        'from_type': from_type,
                        'to_type': to_type,
                    },
                )

                from_wallet.update_balance(-amount)
                to_wallet.update_balance(amount)

                return {
                    'success': True,
                    'message': f'Transferred ₹{amount} from {from_type} to {to_type}',
                    'transaction_id': transfer.id,
                }
            
            return {'success': False, 'message': 'Action type not implemented'}
            
        except Exception as e:
            return {'success': False, 'message': f'Error: {str(e)}'}
    
    def _get_monthly_trends(self, months: int = 6) -> Dict[str, float]:
        """Get monthly spending trends"""
        trends = {}
        today = timezone.now()
        
        for i in range(months):
            month_date = today - timedelta(days=30*i)
            month_key = month_date.strftime("%Y-%m")
            month_start = month_date.replace(day=1, hour=0, minute=0, second=0)
            
            # Calculate month end
            if i == 0:
                next_month = month_date + timedelta(days=32)
                month_end = next_month.replace(day=1) - timedelta(seconds=1)
            else:
                month_end = month_start + timedelta(days=32)
                month_end = month_end.replace(day=1) - timedelta(seconds=1)
            
            total_spent = Expense.objects.filter(
                user=self.user,
                date__gte=month_start,
                date__lte=month_end
            ).aggregate(total=Sum('amount'))['total'] or 0
            
            trends[month_key] = float(total_spent)
        
        return dict(sorted(trends.items()))
    
    def _generate_insights(self, analysis: Dict, expenses, incomes):
        """Generate and store financial insights"""
        insights = []
        
        # 1. Savings score insight
        savings_score = analysis['savings_score']
        if savings_score < 40:
            insights.append({
                'type': 'SAVINGS',
                'title': 'Low Savings Rate',
                'description': f'Your savings score is {savings_score}/100. Consider reducing discretionary spending.',
                'severity': 'MEDIUM',
                'action_required': True
            })
        elif savings_score >= 80:
            insights.append({
                'type': 'SAVINGS',
                'title': 'Excellent Savings Rate',
                'description': f'Great job! Your savings score is {savings_score}/100. Consider investment options.',
                'severity': 'LOW',
                'action_required': False
            })
        
        # 2. Category spending insight
        category_data = analysis['category_analysis']
        if category_data:
            top_category, amount = category_data[0]
            monthly_income = float(getattr(self.profile, 'monthly_income', 0) or analysis['basic_metrics']['total_income'])
            
            if monthly_income > 0 and (amount / monthly_income) > 0.3:
                insights.append({
                    'type': 'BUDGET',
                    'title': f'High Spending on {top_category}',
                    'description': f'You spent ₹{amount:,.2f} on {top_category} ({amount/monthly_income*100:.1f}% of income).',
                    'severity': 'HIGH',
                    'action_required': True,
                    'related_amount': amount
                })
        
        # 3. Budget status insight
        if analysis['budget_status']['status'] == 'OVERSPENT':
            insights.append({
                'type': 'BUDGET',
                'title': 'Monthly Budget Exceeded',
                'description': f'You exceeded your budget by ₹{analysis["budget_status"]["excess_amount"]:,.2f} ({analysis["budget_status"]["percentage_over"]:.1f}%).',
                'severity': 'HIGH',
                'action_required': True,
                'related_amount': analysis['budget_status']['excess_amount']
            })
        
        # 4. Risk level insight
        if analysis['risk_level'] in ['HIGH RISK', 'CRITICAL RISK']:
            insights.append({
                'type': 'RISK',
                'title': 'High Financial Risk',
                'description': f'Your financial risk level is {analysis["risk_level"]}. Consider reducing expenses.',
                'severity': 'HIGH',
                'action_required': True
            })
        
        # Store insights (avoid duplicates)
        for insight_data in insights:
            # Check if similar insight already exists recently
            existing = FinancialInsight.objects.filter(
                user=self.user,
                title=insight_data['title'],
                created_at__gte=timezone.now() - timedelta(days=3)
            ).exists()
            
            if not existing:
                FinancialInsight.objects.create(
                    user=self.user,
                    insight_type=insight_data['type'],
                    title=insight_data['title'],
                    description=insight_data['description'],
                    severity=insight_data.get('severity', 'MEDIUM'),
                    action_required=insight_data.get('action_required', False),
                    related_amount=Decimal(str(insight_data.get('related_amount', 0))),
                    expires_at=timezone.now() + timedelta(days=7)
                )
    
    def _generate_crisis_mitigation(self, shortfall: float, days_until: int) -> str:
        """Generate actionable crisis mitigation suggestions"""
        safe_days_until = max(int(days_until or 0), 1)
        daily_target = shortfall / safe_days_until if shortfall else 0
        if days_until and days_until > 0:
            timing_message = f"URGENT: You need ₹{shortfall:,.2f} within {days_until} days to avoid cash shortage."
        else:
            timing_message = f"URGENT: You need ₹{shortfall:,.2f} immediately to avoid cash shortage."

        suggestions = [
            timing_message,
            "",
            "Immediate actions:",
            "1. Review and postpone non-essential expenses",
            "2. Contact creditors for payment extensions",
            "3. Use 'Spending Freeze' feature for 7 days",
            "4. Transfer from emergency fund if available",
            "",
            "Quick income options:",
            "5. Take up gig work (delivery, freelancing)",
            "6. Sell unused items online",
            "7. Offer services in your skillset",
            "",
            "Prevention for next month:",
            f"8. Save ₹{daily_target:,.2f} daily starting today",
            "9. Set up income alerts for irregular earnings",
            "10. Build 3-month emergency fund gradually"
        ]
        
        return "\n".join(suggestions)
    
    def _analyze_goals_progress(self) -> List[Dict]:
        """Analyze progress towards financial goals"""
        goals = FinancialGoal.objects.filter(
            user=self.user,
            status='IN_PROGRESS'
        )
        
        progress_data = []
        for goal in goals:
            progress = {
                'id': goal.id,
                'name': goal.name,
                'type': goal.goal_type,
                'target_amount': float(goal.target_amount),
                'current_amount': float(goal.current_amount),
                'progress_percentage': goal.progress_percentage,
                'months_remaining': goal.months_remaining,
                'monthly_needed': float(goal.required_monthly_saving),
                'on_track': goal.is_on_track
            }
            progress_data.append(progress)
        
        return progress_data
    
    def _analyze_subscriptions(self) -> Dict:
        """Analyze subscription expenses"""
        from .subscription_ai import analyze_subscriptions
        
        # Get subscription expenses (assuming category name contains 'subscription')
        subscriptions = Expense.objects.filter(
            user=self.user,
            date__gte=timezone.now() - timedelta(days=30),
        ).filter(
            Q(category__icontains='subscription') |
            Q(custom_category__icontains='subscription') |
            Q(budget_category__name__icontains='subscription')
        )
        
        total_subscription = float(subscriptions.aggregate(total=Sum('amount'))['total'] or 0)
        monthly_income = float(getattr(self.profile, 'monthly_income', 0) or 1)
        
        return analyze_subscriptions(subscriptions, monthly_income)
    
    def _calculate_spending_consistency(self) -> float:
        """Calculate how consistent spending is month-to-month"""
        trends = self._get_monthly_trends(6)
        if len(trends) < 2:
            return 0.7
        
        amounts = list(trends.values())
        avg = sum(amounts) / len(amounts)
        
        # Calculate coefficient of variation (lower is more consistent)
        if avg > 0:
            variance = sum((x - avg) ** 2 for x in amounts) / len(amounts)
            std_dev = variance ** 0.5
            cv = std_dev / avg
            # Convert to consistency score (0-1, higher is better)
            return max(0, 1 - cv)
        
        return 0.5
    
    def _calculate_investment_ratio(self) -> float:
        """Calculate investment-to-income ratio using Finance investments."""
        total_investments = float(
            Investment.objects.filter(user=self.user).aggregate(
                total=Sum('current_value')
            )['total']
            or 0
        )

        monthly_income = float(getattr(self.profile, 'monthly_income', 0) or 0)

        if monthly_income > 0:
            return total_investments / (monthly_income * 12)  # Annualized
        return 0.0
    
    def _get_weekly_goals_progress(self) -> List[Dict]:
        """Get weekly progress towards goals"""
        week_ago = timezone.now() - timedelta(days=7)
        
        goals = FinancialGoal.objects.filter(
            user=self.user,
            status='IN_PROGRESS',
            updated_at__gte=week_ago
        )
        
        return [
            {
                'name': goal.name,
                'progress': goal.progress_percentage,
                'weekly_addition': float(goal.current_amount) - float(goal.metadata.get('last_week_amount', 0))
            }
            for goal in goals
        ]
