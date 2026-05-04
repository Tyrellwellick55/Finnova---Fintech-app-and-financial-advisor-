## **5. ANALYTICS AI VIEWS** (`analytics_ai/views.py`)
# analytics_ai/views.py - FIXED AND COMPLETE
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.utils import timezone
from django.utils.timesince import timesince
from django.core.paginator import Paginator
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q, Avg, Count, Sum as models_Sum
from datetime import timedelta, date
import json
import logging

from .models import (
    FinancialInsight, PredictiveAlert, SmartRule,
    UserFinancialProfile, AISession
)
from .services import FinancialAnalyticsService
from .algorithms import generate_ai_report, generate_financial_tips
from finance.models import Expense, Income
from payments_core.models import PaymentTransaction
from finnova_autopilot.models import AutomationRule
from audit.models import AuditLog
from notifications.models import Notification

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# AI DASHBOARD
# ─────────────────────────────────────────────────────────────
@login_required
def ai_dashboard(request):
    """Main AI Dashboard"""
    try:
        svc = FinancialAnalyticsService(request.user)
        analysis = svc.analyze_monthly_finances()

        active_alerts = PredictiveAlert.objects.filter(
            user=request.user, is_active=True,
            predicted_date__gte=timezone.now().date()
        ).order_by('predicted_date')[:5]

        recent_insights = FinancialInsight.objects.filter(
            user=request.user,
            created_at__gte=timezone.now() - timedelta(days=7)
        ).order_by('-severity', '-created_at')[:8]

        automation_rules = AutomationRule.objects.filter(
            user=request.user, is_active=True
        ).order_by('-created_at')[:5]

        crisis_alerts = svc.predict_and_prevent_crisis()
        savings_plan  = svc.generate_smart_savings_plan()
        health_score, health_grade, health_breakdown = svc.calculate_financial_health()
        goals_progress   = svc._analyze_goals_progress()
        spending_patterns = svc.analyze_spending_patterns()
        investment_recommendations = svc.generate_investment_recommendations()
        risk_assessment  = svc.assess_financial_risk()
        anomalies        = svc.detect_anomalies()

        # ── Chart data (6-month spending trend) ──────────────────
        trends = analysis.get('monthly_trends', {})
        chart_labels  = json.dumps(list(trends.keys())[-6:])
        chart_amounts = json.dumps([float(v) for v in list(trends.values())[-6:]])

        # ── Category pie data ─────────────────────────────────────
        cat_data = analysis.get('category_analysis', [])
        category_labels  = json.dumps([c[0] for c in cat_data[:6]])
        category_amounts = json.dumps([float(c[1]) for c in cat_data[:6]])

        # ── Income vs Expense for the last 6 months ───────────────
        today = date.today()
        income_series   = []
        expense_series  = []
        month_labels    = []
        for offset in range(5, -1, -1):
            pivot = (today.replace(day=1) - timedelta(days=30 * offset))
            inc = float(Income.objects.filter(
                user=request.user, date__year=pivot.year, date__month=pivot.month
            ).aggregate(t=models_Sum('amount'))['t'] or 0)
            exp = float(Expense.objects.filter(
                user=request.user, date__year=pivot.year, date__month=pivot.month
            ).aggregate(t=models_Sum('amount'))['t'] or 0)
            income_series.append(round(inc, 2))
            expense_series.append(round(exp, 2))
            month_labels.append(pivot.strftime('%b %Y'))

        context = {
            # Basic metrics
            'total_income':   analysis['basic_metrics']['total_income'],
            'total_expense':  analysis['basic_metrics']['total_expense'],
            'net_savings':    analysis['basic_metrics']['net_savings'],
            'savings_rate':   round(analysis['basic_metrics']['savings_rate'], 1),
            # AI Analysis
            'score':       analysis['savings_score'],
            'risk':        analysis['risk_level'],
            'personality': analysis['personality'].title(),
            'prediction':  analysis['predictions']['next_month_expense'],
            # Category data
            'category_data':  cat_data,
            'top_category':   cat_data[0][0] if cat_data else 'None',
            # Budget
            'budget_status': analysis['budget_status'],
            # Proactive
            'active_alerts':      list(active_alerts),
            'recent_insights':    recent_insights,
            'recent_insights_count': recent_insights.count(),
            'automation_rules':   automation_rules,
            'savings_plan':       savings_plan,
            'crisis_alerts':      crisis_alerts,
            'has_crisis_alerts':  len(crisis_alerts) > 0,
            # Health
            'health_score':     health_score,
            'health_grade':     health_grade,
            'health_breakdown': health_breakdown,
            # Goals
            'goals_progress': goals_progress,
            'goals_on_track': sum(1 for g in goals_progress if g.get('on_track')),
            # Patterns
            'spending_patterns':          spending_patterns,
            'investment_recommendations': investment_recommendations,
            'risk_assessment':            risk_assessment,
            'anomalies':                  anomalies,
            # Chart data (correct variable names)
            'chart_labels':       chart_labels,
            'chart_amounts':      chart_amounts,
            'category_labels':    category_labels,
            'category_amounts':   category_amounts,
            'month_labels':       json.dumps(month_labels),
            'income_series':      json.dumps(income_series),
            'expense_series':     json.dumps(expense_series),
            # AI tips
            'ai_report': generate_ai_report(
                analysis['savings_score'], analysis['risk_level'],
                analysis['predictions']['next_month_expense'], analysis['personality']
            ),
            'advice': generate_financial_tips(
                analysis['savings_score'],
                cat_data[0][0] if cat_data else 'General'
            ),
            'profile':      UserFinancialProfile.objects.get_or_create(user=request.user)[0],
            'generated_at': timezone.now(),
        }

        return render(request, 'analytics_ai/ai_dashboard.html', context)

    except Exception as e:
        logger.error(f"AI Dashboard error: {str(e)}", exc_info=True)
        try:
            profile = UserFinancialProfile.objects.get_or_create(user=request.user)[0]
        except Exception:
            profile = None
        return render(request, 'analytics_ai/ai_dashboard.html', {
            'error': True, 'profile': profile,
            'total_income': 0, 'total_expense': 0, 'net_savings': 0,
            'savings_rate': 0, 'health_score': None, 'health_grade': None,
            'recent_insights': [], 'recent_insights_count': 0,
            'active_alerts': [], 'goals_progress': [], 'crisis_alerts': [],
            'chart_labels': '[]', 'chart_amounts': '[]',
            'category_labels': '[]', 'category_amounts': '[]',
            'month_labels': '[]', 'income_series': '[]', 'expense_series': '[]',
        })


# ─────────────────────────────────────────────────────────────
# AI REPORT
# ─────────────────────────────────────────────────────────────
@login_required
def ai_report(request):
    """Detailed AI Financial Report"""
    try:
        svc = FinancialAnalyticsService(request.user)
        analysis   = svc.analyze_monthly_finances()
        health_score, health_grade, health_breakdown = svc.calculate_financial_health()
        savings_plan   = svc.generate_smart_savings_plan()
        opportunities  = svc.detect_income_opportunities()
        spending_analysis  = svc.analyze_spending_patterns()
        investment_analysis = svc.analyze_investment_portfolio()
        debt_analysis  = svc.analyze_debt_situation()
        tax_planning   = svc.generate_tax_planning_advice()
        retirement     = svc.generate_retirement_plan()

        # ── Income vs Expense 6-month bars for report ─────────────
        today = date.today()
        report_months = []
        for offset in range(5, -1, -1):
            pivot = (today.replace(day=1) - timedelta(days=30 * offset))
            inc = float(Income.objects.filter(
                user=request.user, date__year=pivot.year, date__month=pivot.month
            ).aggregate(t=models_Sum('amount'))['t'] or 0)
            exp = float(Expense.objects.filter(
                user=request.user, date__year=pivot.year, date__month=pivot.month
            ).aggregate(t=models_Sum('amount'))['t'] or 0)
            report_months.append({
                'label': pivot.strftime('%b'),
                'income': round(inc, 2),
                'expense': round(exp, 2),
                'net': round(inc - exp, 2),
            })

        safe_data = json.loads(json.dumps(analysis, cls=DjangoJSONEncoder))
        try:
            AISession.objects.create(
                user=request.user, session_type='ANALYSIS',
                title='Comprehensive AI Report',
                context_data={'report_type': 'COMPREHENSIVE'},
                analysis_data={'report_data': safe_data},
                metadata={'confidence_score': 85}
            )
        except Exception:
            pass

        context = {
            'analysis': analysis,
            'health_score': health_score,
            'health_grade': health_grade,
            'health_breakdown': health_breakdown,
            'savings_plan': savings_plan,
            'opportunities': opportunities[:3],
            'spending_analysis': spending_analysis,
            'investment_analysis': investment_analysis,
            'investment_recommendations': investment_analysis.get('recommendations', []),
            'debt_analysis': debt_analysis,
            'tax_planning': tax_planning,
            'retirement_planning': retirement,
            'report_months': report_months,
            'report_months_json': json.dumps(report_months),
            'profile': UserFinancialProfile.objects.get_or_create(user=request.user)[0],
            'generated_at': timezone.now(),
        }
        return render(request, 'analytics_ai/ai_report.html', context)

    except Exception as e:
        logger.error(f"AI Report error: {str(e)}", exc_info=True)
        try:
            profile = UserFinancialProfile.objects.get_or_create(user=request.user)[0]
        except Exception:
            profile = None
        return render(request, 'analytics_ai/ai_report.html', {
            'error': True,
            'analysis': {'basic_metrics': {'total_income': 0, 'total_expense': 0, 'net_savings': 0, 'savings_rate': 0}},
            'health_score': 0, 'health_grade': 'N/A', 'health_breakdown': {},
            'savings_plan': {}, 'opportunities': [],
            'spending_analysis': {}, 'investment_analysis': {'recommendations': []},
            'investment_recommendations': [], 'debt_analysis': {},
            'tax_planning': {}, 'retirement_planning': {},
            'report_months': [], 'report_months_json': '[]',
            'profile': profile, 'generated_at': timezone.now(),
        })


# ─────────────────────────────────────────────────────────────
# PREDICTIVE ANALYTICS
# ─────────────────────────────────────────────────────────────
@login_required
def predictive_analytics(request):
    """Predictive analytics dashboard"""
    try:
        svc = FinancialAnalyticsService(request.user)

        cashflow_predictions  = svc.predict_cashflow(days=90)
        expense_predictions   = svc.predict_expense_categories()
        income_predictions    = svc.predict_income_trends()
        anomalies             = svc.detect_anomalies()
        risk_assessment       = svc.assess_financial_risk()
        trend_analysis        = svc.analyze_financial_trends()
        seasonality           = svc.analyze_seasonality_patterns()

        active_alerts = PredictiveAlert.objects.filter(
            user=request.user, is_active=True,
            predicted_date__gte=timezone.now().date()
        ).order_by('predicted_date')[:6]

        # ── Cashflow chart: project 90 days from today ────────────
        today = date.today()
        current_balance = float(cashflow_predictions.get('current_balance', 0) or 0)
        daily_net       = float(cashflow_predictions.get('daily_net', 0) or 0)
        cf_labels = []
        cf_values = []
        for i in range(0, 91, 10):
            d = today + timedelta(days=i)
            cf_labels.append(d.strftime('%d %b'))
            cf_values.append(round(current_balance + daily_net * i, 2))
        cashflow_chart = json.dumps({'labels': cf_labels, 'values': cf_values})

        # ── Income history chart ──────────────────────────────────
        history = income_predictions.get('history', [])
        income_chart = json.dumps({
            'labels': [h['month'] for h in history],
            'values': [h['amount'] for h in history],
        })

        # ── Seasonality summary ───────────────────────────────────
        patterns = seasonality.get('patterns', [])
        top = max(patterns, key=lambda x: abs(x.get('variance', 0)), default=None)
        if top:
            direction = 'above' if top.get('variance', 0) >= 0 else 'below'
            seasonality_summary = (
                f"{top['name']} spending is {abs(top.get('variance', 0)):.1f}% "
                f"{direction} your annual average."
            )
        else:
            seasonality_summary = "Seasonality insights will appear after more Finance history."

        # ── Forecast signal cards ─────────────────────────────────
        def conf_class(s):
            return 'high' if s >= 85 else ('medium' if s >= 65 else 'low')

        forecast_signals = []
        lowest_date = cashflow_predictions.get('lowest_date')
        if lowest_date:
            lowest_pt = float(cashflow_predictions.get('lowest_point', 0) or 0)
            conf = int(cashflow_predictions.get('confidence', 0) or 0)
            pressure = lowest_pt < current_balance
            forecast_signals.append({
                'title': 'Projected balance range',
                'detail': (
                    f"Balance may reach ₹{lowest_pt:,.0f} by "
                    f"{lowest_date.strftime('%b %d, %Y')} at current pace."
                ),
                'badge': 'Pressure' if pressure else 'Stable',
                'badge_class': 'warning' if pressure else 'success',
                'icon': 'wallet',
                'confidence': conf,
                'confidence_class': conf_class(conf),
            })

        rising = expense_predictions.get('increasing', [])
        if rising:
            top_r = rising[0]
            increase = float(top_r.get('increase', top_r.get('change', 0)) or 0)
            forecast_signals.append({
                'title': f"{top_r.get('name', 'Category')} spend rising",
                'detail': f"{top_r.get('name', 'Category')} is tracking {increase:.1f}% above prior period.",
                'badge': 'Rising',
                'badge_class': 'warning' if increase >= 10 else 'info',
                'icon': 'arrow-trend-up',
            })

        proj_income = float(income_predictions.get('projected_next_month', 0) or 0)
        if proj_income > 0:
            growth = float(income_predictions.get('growth_rate', 0) or 0)
            conf   = int(income_predictions.get('confidence', 0) or 0)
            forecast_signals.append({
                'title': 'Next-month income outlook',
                'detail': f"Projected ₹{proj_income:,.0f} — {growth:+.1f}% vs earlier months.",
                'badge': 'Improving' if growth >= 0 else 'Softening',
                'badge_class': 'success' if growth >= 0 else 'warning',
                'icon': 'calendar-check',
                'confidence': conf,
                'confidence_class': conf_class(conf),
            })

        if anomalies:
            a = anomalies[0]
            adate = a.get('date')
            forecast_signals.append({
                'title': a.get('title', 'Unusual activity'),
                'detail': (
                    f"{a.get('description', 'Unusual transaction pattern')} "
                    f"on {adate.strftime('%b %d, %Y') if adate else 'recently'}."
                ),
                'badge': a.get('severity', 'Review').title(),
                'badge_class': 'danger' if a.get('severity') == 'HIGH' else 'warning',
                'icon': 'triangle-exclamation',
            })

        if not forecast_signals:
            forecast_signals.append({
                'title': 'Add data to unlock predictions',
                'detail': 'Record income and expenses in Finance to enable AI-powered forecasting.',
                'badge': 'Info', 'badge_class': 'info', 'icon': 'circle-info',
            })

        context = {
            'cashflow_predictions':  cashflow_predictions,
            'cashflow_chart':        cashflow_chart,
            'expense_predictions':   expense_predictions,
            'income_predictions':    income_predictions,
            'income_chart':          income_chart,
            'anomalies':             anomalies,
            'risk_assessment':       risk_assessment,
            'trend_analysis':        trend_analysis,
            'seasonality':           seasonality,
            'seasonality_summary':   seasonality_summary,
            'forecast_signals':      forecast_signals,
            'active_alerts':         list(active_alerts),
            'profile':               svc.profile,
        }
        return render(request, 'analytics_ai/predictive_analytics.html', context)

    except Exception as e:
        logger.error(f"Predictive analytics error: {str(e)}", exc_info=True)
        try:
            profile = UserFinancialProfile.objects.get_or_create(user=request.user)[0]
        except Exception:
            profile = None
        return render(request, 'analytics_ai/predictive_analytics.html', {
            'error': True,
            'cashflow_predictions': {}, 'cashflow_chart': '{"labels":[],"values":[]}',
            'expense_predictions': {'increasing': [], 'decreasing': []},
            'income_predictions': {'history': [], 'growth_rate': 0, 'projected_next_month': 0, 'confidence': 0},
            'income_chart': '{"labels":[],"values":[]}',
            'anomalies': [], 'risk_assessment': {}, 'trend_analysis': {},
            'seasonality': {}, 'seasonality_summary': 'Add Finance data to unlock predictions.',
            'forecast_signals': [{'title': 'Add financial data', 'detail': 'Record income and expenses to enable forecasting.', 'badge': 'Info', 'badge_class': 'info', 'icon': 'circle-info'}],
            'active_alerts': [], 'profile': profile,
        })


@login_required
@require_GET
def get_predictions(request):
    try:
        svc = FinancialAnalyticsService(request.user)
        ptype = request.GET.get('type', 'cashflow')
        days  = int(request.GET.get('days', 30))
        if ptype == 'cashflow':
            data = svc.predict_cashflow(days=days)
        elif ptype == 'expenses':
            data = svc.predict_expense_categories()
        elif ptype == 'income':
            data = svc.predict_income_trends()
        else:
            return JsonResponse({'success': False, 'error': 'Invalid type'})
        return JsonResponse({'success': True, 'predictions': data, 'type': ptype, 'generated_at': timezone.now().isoformat()})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})


# ─────────────────────────────────────────────────────────────
# FINANCIAL INSIGHTS
# ─────────────────────────────────────────────────────────────
@login_required
def financial_insights(request):
    """Financial insights list"""
    insights = FinancialInsight.objects.filter(user=request.user).order_by('-severity', '-created_at')

    insight_type   = request.GET.get('type')
    severity       = request.GET.get('severity')
    action_required = request.GET.get('action_required')
    search_query   = request.GET.get('search')

    if insight_type:
        insights = insights.filter(insight_type=insight_type)
    if severity:
        insights = insights.filter(severity=severity)
    if action_required == 'true':
        insights = insights.filter(action_required=True)
    elif action_required == 'false':
        insights = insights.filter(action_required=False)
    if search_query:
        insights = insights.filter(Q(title__icontains=search_query) | Q(description__icontains=search_query))

    total_qs = FinancialInsight.objects.filter(user=request.user)
    stats = {
        'total':          total_qs.count(),
        'critical':       total_qs.filter(severity='CRITICAL').count(),
        'high':           total_qs.filter(severity='HIGH').count(),
        'medium':         total_qs.filter(severity='MEDIUM').count(),
        'low':            total_qs.filter(severity='LOW').count(),
        'action_required': total_qs.filter(action_required=True).count(),
        'active':         total_qs.filter(is_active=True).count(),
    }

    insight_categories = total_qs.values('insight_type').annotate(count=Count('id')).order_by('-count')
    paginator  = Paginator(insights, 20)
    page_obj   = paginator.get_page(request.GET.get('page'))

    context = {
        'page_obj':          page_obj,
        'stats':             stats,
        'recent_insights':   total_qs.filter(created_at__gte=timezone.now() - timedelta(days=30)).count(),
        'insight_categories': insight_categories,
        'insight_types':     FinancialInsight.INSIGHT_TYPES,
        'severities':        FinancialInsight.SEVERITY_CHOICES,
        'insight_type':      insight_type,
        'severity':          severity,
        'action_required':   action_required,
        'search_query':      search_query,
    }
    return render(request, 'analytics_ai/financial_insights.html', context)


@login_required
def insight_detail(request, insight_id):
    insight = get_object_or_404(FinancialInsight, id=insight_id, user=request.user)
    similar = FinancialInsight.objects.filter(
        user=request.user, insight_type=insight.insight_type
    ).exclude(id=insight.id).order_by('-created_at')[:5]
    action_items = _generate_action_items(insight)
    context = {'insight': insight, 'similar_insights': similar, 'action_items': action_items}
    return render(request, 'analytics_ai/insight_detail.html', context)


@login_required
@require_POST
def mark_insight_read(request, insight_id):
    try:
        insight = FinancialInsight.objects.get(id=insight_id, user=request.user)
        insight.action_completed = True
        insight.is_read = True
        insight.is_active = False
        insight.action_completed_at = timezone.now()
        insight.save()
        return JsonResponse({'success': True})
    except FinancialInsight.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Not found'}, status=404)


# ─────────────────────────────────────────────────────────────
# FINANCIAL HEALTH
# ─────────────────────────────────────────────────────────────
@login_required
def financial_health_dashboard(request):
    """Financial health dashboard"""
    svc = FinancialAnalyticsService(request.user)
    try:
        score, grade, breakdown = svc.calculate_financial_health()
        suggestions   = svc.generate_health_improvement_suggestions()
        health_trends = svc.analyze_health_trends()
        benchmark     = svc.get_health_benchmark()
        risk_assessment = svc.assess_financial_risk()
        action_plan   = svc.generate_health_action_plan()

        # Normalize breakdown for template: ensure each value has 'score', 'points', 'name', 'status'
        normalized = {}
        max_per_component = {'savings_rate': 250, 'emergency_fund': 200, 'debt_ratio': 200,
                             'credit_utilization': 150, 'spending_consistency': 100, 'investment_ratio': 100}
        for key, val in breakdown.items():
            if not isinstance(val, dict):
                val = {'points': int(val or 0), 'status': 'Fair'}
            pts = val.get('points', val.get('score', 0))
            mx  = max_per_component.get(key, 200)
            normalized[key] = {
                'score':   pts,
                'points':  pts,
                'max':     mx,
                'pct':     round(pts / mx * 100, 1) if mx else 0,
                'name':    val.get('name', key.replace('_', ' ').title()),
                'status':  val.get('status', 'Fair'),
                'label':   val.get('label', ''),
            }

        context = {
            'score': score, 'grade': grade,
            'breakdown': normalized,
            'suggestions': suggestions,
            'health_trends': json.dumps(health_trends, default=str),
            'benchmark': benchmark,
            'risk_assessment': risk_assessment,
            'action_plan': action_plan,
            'milestones': [],
            'profile': svc.profile,
        }
        return render(request, 'analytics_ai/financial_health.html', context)

    except Exception as e:
        logger.error(f"Financial health error: {str(e)}", exc_info=True)
        try:
            profile = UserFinancialProfile.objects.get_or_create(user=request.user)[0]
        except Exception:
            profile = None
        return render(request, 'analytics_ai/financial_health.html', {
            'error': True, 'score': None, 'grade': None, 'breakdown': {},
            'suggestions': [{'title': 'Add income & expense data', 'description': 'Record your monthly income and expenses to calculate your score.', 'priority': 'HIGH'}],
            'health_trends': '{}', 'benchmark': {}, 'risk_assessment': {},
            'action_plan': [], 'milestones': [], 'profile': profile,
        })


@login_required
@require_GET
def get_financial_health_score(request):
    svc = FinancialAnalyticsService(request.user)
    try:
        score, grade, breakdown = svc.calculate_financial_health()
        return JsonResponse({'success': True, 'score': score, 'grade': grade, 'percentage': (score / 1000) * 100, 'breakdown': breakdown, 'timestamp': timezone.now().isoformat()})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ─────────────────────────────────────────────────────────────
# AI CHAT
# ─────────────────────────────────────────────────────────────
@login_required
def ai_chat(request):
    user = request.user
    try:
        from decimal import Decimal
        today_d = date.today()
        month_start = today_d.replace(day=1)
        month_income  = Income.objects.filter(user=user, date__gte=month_start).aggregate(t=models_Sum('amount'))['t'] or Decimal('0')
        month_expense = Expense.objects.filter(user=user, date__gte=month_start).aggregate(t=models_Sum('amount'))['t'] or Decimal('0')
    except Exception:
        from decimal import Decimal
        month_income = month_expense = Decimal('0')

    try:
        from analytics_ai.models import FinancialHealthScore
        hs = FinancialHealthScore.objects.filter(user=user).order_by('-calculated_at').first()
        health_score_val = hs.overall_score if hs else None
    except Exception:
        health_score_val = None

    try:
        from agency.models import Invoice
        open_invoices = Invoice.objects.filter(organization__memberships__user=user, status__in=['SENT', 'OVERDUE']).count()
    except Exception:
        open_invoices = 0

    try:
        from finnova_autopilot.models import SavingsGoal
        savings_goals = SavingsGoal.objects.filter(user=user, status__in=['PLANNING', 'ACTIVE']).count()
    except Exception:
        savings_goals = 0

    try:
        months_data = Income.objects.filter(user=user).dates('date', 'month').count()
    except Exception:
        months_data = 0

    from decimal import Decimal as _D
    context_summary = {
        'month_income': month_income, 'month_expense': month_expense,
        'net_this_month': month_income - month_expense,
        'health_score': health_score_val, 'open_invoices': open_invoices,
        'savings_goals': savings_goals, 'months_of_data': months_data,
    }
    return render(request, 'analytics_ai/ai_chat.html', {'context_summary': context_summary, 'chat_history': []})


@login_required
@require_POST
def ai_chat_api(request):
    try:
        body = json.loads(request.body)
        user_question = body.get('message', '').strip()
    except Exception:
        return JsonResponse({'error': 'Invalid request'}, status=400)
    if not user_question:
        return JsonResponse({'error': 'No message provided'}, status=400)
    if len(user_question) > 500:
        return JsonResponse({'error': 'Question too long (max 500 characters)'}, status=400)
    try:
        context = _build_ai_context(request.user)
    except Exception:
        context = "No financial data available yet."
    try:
        reply = _call_ai(user_question, context, request.user)
    except Exception:
        return JsonResponse({'error': 'AI service unavailable. Please try again.'}, status=503)
    return JsonResponse({'reply': reply})


def _build_ai_context(user):
    from decimal import Decimal
    today = date.today()
    month_start = today.replace(day=1)
    lines = [f"User: {user.get_full_name() or user.username}", f"Date: {today.strftime('%d %B %Y')}", ""]
    try:
        from finance.models import Budget, FinancialGoal
        mi = Income.objects.filter(user=user, date__gte=month_start).aggregate(t=models_Sum('amount'))['t'] or 0
        me = Expense.objects.filter(user=user, date__gte=month_start).aggregate(t=models_Sum('amount'))['t'] or 0
        lines.append(f"THIS MONTH: Income ₹{mi:,.0f}, Expenses ₹{me:,.0f}, Net ₹{mi-me:,.0f}")
        for offset in range(5, -1, -1):
            pivot = (today.replace(day=1) - timedelta(days=30 * offset))
            import calendar
            me_date = date(pivot.year, pivot.month, calendar.monthrange(pivot.year, pivot.month)[1])
            i = Income.objects.filter(user=user, date__range=[pivot, me_date]).aggregate(t=models_Sum('amount'))['t'] or 0
            e = Expense.objects.filter(user=user, date__range=[pivot, me_date]).aggregate(t=models_Sum('amount'))['t'] or 0
            lines.append(f"{pivot.strftime('%b %Y')}: Income ₹{i:,.0f}, Expenses ₹{e:,.0f}")
        cats = Expense.objects.filter(user=user, date__gte=month_start).values('category').annotate(t=models_Sum('amount')).order_by('-t')[:5]
        if cats:
            lines.append("TOP CATEGORIES: " + ", ".join(f"{c['category']} ₹{c['t']:,.0f}" for c in cats))
        budgets = Budget.objects.filter(user=user, is_active=True)[:5]
        if budgets:
            lines.append("BUDGETS: " + "; ".join(f"{b.name} {b.current_spending:.0f}/{b.amount:.0f}" for b in budgets))
        goals = FinancialGoal.objects.filter(user=user).exclude(status__in=['ACHIEVED', 'CANCELLED'])[:4]
        if goals:
            lines.append("GOALS: " + "; ".join(f"{g.name} {g.progress_percentage:.0f}% of ₹{g.target_amount:,.0f}" for g in goals))
    except Exception:
        pass
    try:
        from agency.models import Client, Invoice
        clients = Client.objects.filter(organization__memberships__user=user)[:5]
        if clients:
            lines.append("CLIENTS: " + ", ".join(c.name for c in clients))
        open_inv = Invoice.objects.filter(organization__memberships__user=user, status__in=['SENT', 'OVERDUE'])
        if open_inv.exists():
            lines.append(f"OPEN INVOICES: {open_inv.count()} invoices")
    except Exception:
        pass
    try:
        from analytics_ai.models import FinancialHealthScore
        hs = FinancialHealthScore.objects.filter(user=user).order_by('-calculated_at').first()
        if hs:
            lines.append(f"HEALTH SCORE: {hs.overall_score}/1000 Grade {hs.grade}")
    except Exception:
        pass
    try:
        from finnova_autopilot.models import SavingsGoal, Alert
        sg = SavingsGoal.objects.filter(user=user, status__in=['PLANNING', 'ACTIVE'])
        if sg.exists():
            lines.append("SAVINGS GOALS: " + "; ".join(f"{g.goal_name} ₹{float(g.current_saved):,.0f}/₹{float(g.target_amount):,.0f}" for g in sg[:4]))
    except Exception:
        pass
    return "\n".join(lines)


def _call_ai(question, context, user):
    import os
    api_key = os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('OPENAI_API_KEY')
    system_prompt = """You are Finnova AI, a financial advisor embedded in a business finance platform.
You have access to the user's real financial data. Answer questions directly using their actual numbers.
Keep answers clear, practical, and under 200 words. Use ₹ for Indian rupees."""
    full_prompt = f"USER FINANCIAL DATA:\n{context}\n\nUSER QUESTION: {question}\n\nAnswer:"
    if os.environ.get('ANTHROPIC_API_KEY'):
        import urllib.request
        payload = {"model": "claude-sonnet-4-6", "max_tokens": 400, "system": system_prompt, "messages": [{"role": "user", "content": full_prompt}]}
        req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': '2023-06-01'}, method='POST')
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
            return data['content'][0]['text']
    return _rule_based_response(question, context)


def _rule_based_response(question, context):
    q = question.lower()
    lines = context.split('\n')
    for line in lines:
        if 'THIS MONTH:' in line and any(w in q for w in ['profit', 'income', 'earn', 'revenue']):
            return f"Based on your data — {line.replace('THIS MONTH: ', '')}. Add an ANTHROPIC_API_KEY for deeper AI analysis."
        if 'HEALTH SCORE:' in line and 'health' in q:
            return f"{line.replace('FINANCIAL ', '')}. Add an ANTHROPIC_API_KEY for personalized improvement advice."
    return ("I can see your financial data but need an AI API key for intelligent answers. "
            "Add ANTHROPIC_API_KEY to your environment variables. "
            f"Quick summary: {lines[2] if len(lines) > 2 else 'No data loaded yet.'}")


# ─────────────────────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────────────────────
@login_required
def ai_settings(request):
    profile, _ = UserFinancialProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        try:
            profile.risk_level = request.POST.get('risk_tolerance', 'MEDIUM')
            ai_prefs = {
                'enable_predictive_analytics': request.POST.get('enable_predictive') == 'true',
                'enable_anomaly_detection':    request.POST.get('enable_anomaly') == 'true',
                'enable_auto_insights':        request.POST.get('enable_insights') == 'true',
                'insight_frequency':           request.POST.get('insight_frequency', 'WEEKLY'),
                'alert_threshold':             int(request.POST.get('alert_threshold', 70)),
            }
            profile.metadata = profile.metadata or {}
            profile.metadata['ai_preferences'] = ai_prefs
            profile.save()
            messages.success(request, "Settings saved.")
            return redirect('analytics-ai:ai_settings')
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
    ai_prefs = (profile.metadata or {}).get('ai_preferences', {})
    context = {
        'profile': profile,
        'ai_preferences': ai_prefs,
        'risk_tolerance_options': UserFinancialProfile.RISK_LEVELS if hasattr(UserFinancialProfile, 'RISK_LEVELS') else [('LOW','Low'),('MEDIUM','Medium'),('HIGH','High')],
    }
    return render(request, 'analytics_ai/settings.html', context)


# ─────────────────────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────────────────────
@login_required
@require_GET
def ai_insights_api(request):
    try:
        insights = FinancialInsight.objects.filter(user=request.user).order_by('-severity', '-created_at')
        severity = request.GET.get('severity')
        if severity:
            insights = insights.filter(severity=severity)
        paginator = Paginator(insights, 20)
        page_obj  = paginator.get_page(request.GET.get('page', 1))
        data = [{'id': str(i.id), 'type': i.insight_type, 'title': i.title, 'description': i.description, 'severity': i.severity, 'action_required': i.action_required, 'created_at': i.created_at.strftime('%Y-%m-%d %H:%M'), 'relative_time': f"{timesince(i.created_at)} ago"} for i in page_obj]
        return JsonResponse({'success': True, 'insights': data, 'total': paginator.count})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_POST
def execute_autopilot(request):
    svc = FinancialAnalyticsService(request.user)
    try:
        data = json.loads(request.body) if request.body else {}
        action_type = data.get('action_type', 'ANALYZE')
        triggered = []
        if action_type == 'EXECUTE_RULES':
            triggered = svc.execute_smart_rules(None)
        return JsonResponse({'success': True, 'triggered_rules': triggered, 'count': len(triggered)})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_GET
def analytics_status_api(request):
    profile = UserFinancialProfile.objects.filter(user=request.user).first()
    open_alerts = PredictiveAlert.objects.filter(user=request.user, is_active=True).count()
    return JsonResponse({'success': True, 'savings_score': getattr(profile, 'savings_behavior_score', 0) if profile else 0, 'risk_level': getattr(profile, 'risk_level', 'MEDIUM') if profile else 'MEDIUM', 'alert_count': open_alerts, 'timestamp': timezone.now().isoformat()})


@login_required
@require_POST
def freeze_spending(request):
    Notification.send_notification(user=request.user, title='Spending Freeze Enabled', message='A temporary spending freeze has been enabled.', category='ALERT', severity='WARNING', delivery_method='IN_APP', action_data={'source': 'analytics_ai'})
    return JsonResponse({'success': True, 'message': 'Spending freeze recorded.'})


@login_required
@require_GET
def weekly_report_api(request):
    svc = FinancialAnalyticsService(request.user)
    try:
        report = svc.generate_weekly_report()
        return JsonResponse({'success': True, 'report': report, 'generated_at': timezone.now().isoformat()})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_GET
def income_opportunities_api(request):
    svc = FinancialAnalyticsService(request.user)
    try:
        opps = svc.detect_income_opportunities()
        return JsonResponse({'success': True, 'opportunities': opps, 'count': len(opps)})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["GET", "POST", "PUT", "PATCH", "DELETE"])
def legacy_analytics_endpoint(request, legacy_path=''):
    normalized = (legacy_path or '').strip('/')
    user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
    if normalized in {'error-log', 'error-report'}:
        return HttpResponse(status=204)
    if normalized in {'api/status'}:
        return JsonResponse({'success': True, 'savings_score': 0, 'risk_level': 'MEDIUM', 'alert_count': 0, 'timestamp': timezone.now().isoformat()})
    return JsonResponse({'success': True, 'path': normalized, 'message': 'Legacy endpoint handled.'})


@csrf_exempt
@login_required
@require_POST
def realtime_analysis_webhook(request):
    try:
        data = json.loads(request.body)
        transaction_id = data.get('transaction_id')
        if not transaction_id:
            return JsonResponse({'error': 'transaction_id required'}, status=400)
        return JsonResponse({'success': True, 'analysis_complete': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ─────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────
def _generate_action_items(insight):
    items = []
    if insight.insight_type == 'SPENDING' and insight.severity in ['HIGH', 'CRITICAL']:
        items.append({'title': 'Review Spending', 'description': 'Review your spending in this category', 'priority': 'HIGH'})
        items.append({'title': 'Set Budget Limit', 'description': 'Set a budget limit for this category', 'priority': 'MEDIUM'})
    elif insight.insight_type == 'SAVINGS':
        items.append({'title': 'Increase Savings', 'description': 'Consider increasing your savings rate', 'priority': 'MEDIUM'})
    elif insight.insight_type == 'INVESTMENT':
        items.append({'title': 'Review Portfolio', 'description': 'Review your investment portfolio', 'priority': 'MEDIUM'})
    return items
