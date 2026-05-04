from django.urls import path, include
from . import views

app_name = "finance"

# ── Optional DRF router ────────────────────────────────────────────────────────
try:
    from rest_framework.routers import DefaultRouter
    from .api import (
        IncomeViewSet, ExpenseViewSet, BudgetViewSet,
        FinancialGoalViewSet, DashboardAPIView, AutoProtectAPIView,
        AnalyticsAPIView, SyncAPIView, ReportViewSet,
        InvestmentViewSet, DebtViewSet
    )
    _router = DefaultRouter()
    _router.register(r'api/income',      IncomeViewSet,        basename='income-api')
    _router.register(r'api/expenses',    ExpenseViewSet,       basename='expense-api')
    _router.register(r'api/budgets',     BudgetViewSet,        basename='budget-api')
    _router.register(r'api/goals',       FinancialGoalViewSet, basename='goal-api')
    _router.register(r'api/reports',     ReportViewSet,        basename='report-api')
    _router.register(r'api/investments', InvestmentViewSet,    basename='investment-api')
    _router.register(r'api/debts',       DebtViewSet,          basename='debt-api')
    _drf_urls = [
        path('', include(_router.urls)),
        path('api/dashboard/',    DashboardAPIView.as_view(),   name='api-dashboard'),
        path('api/auto-protect/', AutoProtectAPIView.as_view(), name='api-auto-protect'),
        path('api/analytics/',    AnalyticsAPIView.as_view(),   name='api-analytics'),
        path('api/sync/',         SyncAPIView.as_view(),        name='api-sync'),
    ]
except ImportError:
    _drf_urls = []

urlpatterns = [
    # Dashboard
    path('',          views.finance_dashboard,   name='finance_dashboard'),
    path('overview/', views.financial_overview,  name='financial_overview'),
    path('transactions/', views.transaction_center, name='transaction_center'),

    # Income
    path('income/',                         views.income_list,   name='income_list'),
    path('income/add/',                     views.add_income,    name='add_income'),
    path('income/<uuid:income_id>/edit/',   views.edit_income,   name='edit_income'),
    path('income/<uuid:income_id>/delete/', views.delete_income, name='delete_income'),
    path('income/<uuid:income_id>/verify/', views.verify_income, name='verify_income'),

    # Expense
    path('expenses/',                           views.expense_list,       name='expense_list'),
    path('expenses/add/',                       views.add_expense,        name='add_expense'),
    path('expenses/<uuid:expense_id>/edit/',    views.edit_expense,       name='edit_expense'),
    path('expenses/<uuid:expense_id>/delete/',  views.delete_expense,     name='delete_expense'),
    path('expenses/<uuid:expense_id>/categorize/', views.categorize_expense, name='categorize_expense'),

    # Budget
    path('budgets/',                        views.budget_list,   name='budget_list'),
    path('budgets/add/',                    views.add_budget,    name='add_budget'),
    path('budgets/<uuid:budget_id>/',       views.budget_detail, name='budget_detail'),
    path('budgets/toggle/<uuid:budget_id>/',views.toggle_budget, name='toggle_budget'),

    # Goals
    path('goals/',                          views.financial_goals,      name='financial_goals'),
    path('goals/add/',                      views.add_financial_goal,   name='add_financial_goal'),
    path('goals/update/<uuid:goal_id>/',    views.update_goal_progress, name='update_goal_progress'),
    path('goals/<uuid:goal_id>/',           views.goal_detail,          name='goal_detail'),

    # Reports
    path('reports/',                      views.reports,     name='reports'),
    path('reports/view/<uuid:report_id>/',views.view_report, name='view_report'),

    # Investments & Debts
    path('investments/',                         views.investments,       name='investments'),
    path('investments/<uuid:investment_id>/',    views.investment_detail, name='investment_detail'),
    path('debts/',                              views.debts,             name='debts'),
    path('debts/<uuid:debt_id>/',               views.debt_detail,       name='debt_detail'),
    path('debts/<uuid:debt_id>/pay/',           views.make_debt_payment, name='make_debt_payment'),
    path('taxes/',                              views.taxes,             name='taxes'),
    path('taxes/calculator/',                   views.tax_calculator,    name='tax_calculator'),

    # Data management
    path('sync/',           views.sync_payments,       name='sync_payments'),
    path('sync/autopilot/', views.sync_with_autopilot, name='sync_with_autopilot'),
    path('import/',         views.import_csv,          name='import_csv'),
    path('export/',         views.export_data,         name='export_data'),
    path('settings/',       views.account_settings,    name='account_settings'),

    # Chart data API (no DRF)
    path('api/chart-data/', views.get_chart_data, name='get_chart_data'),

    # DRF REST API (guarded)
    *_drf_urls,
]
