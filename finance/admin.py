from django.contrib import admin
from .models import (
    Account, Income, Expense, Budget, BudgetCategory, 
    FinancialGoal, Investment, Debt, TaxRecord, FinancialMetric
)

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'account_type', 'current_balance', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('name', 'user__username')

@admin.register(Income)
class IncomeAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'source', 'category', 'date')
    list_filter = ('category', 'date')
    search_fields = ('source', 'user__username')

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'category', 'date', 'requires_review')
    list_filter = ('category', 'date', 'requires_review')
    search_fields = ('description', 'user__username')

@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'amount', 'period', 'utilization_percentage', 'is_active')
    list_filter = ('period', 'is_active', 'user')
    search_fields = ('name', 'description', 'user__username')

@admin.register(BudgetCategory)
class BudgetCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'budget', 'allocated_amount', 'utilization_percentage')
    list_filter = ('budget__user',)
    search_fields = ('name', 'budget__user__username')

@admin.register(FinancialGoal)
class FinancialGoalAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'target_amount', 'current_amount', 'target_date', 'progress_percentage')
    list_filter = ('status', 'priority')
    search_fields = ('name', 'user__username')

@admin.register(TaxRecord)
class TaxRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'tax_type', 'financial_year', 'tax_paid', 'filing_status')
    list_filter = ('tax_type', 'filing_status', 'financial_year')
    search_fields = ('user__username', 'financial_year')

@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'instrument', 'invested_amount', 'current_value', 'status')
    list_filter = ('instrument', 'status')
    search_fields = ('name', 'user__username')

@admin.register(Debt)
class DebtAdmin(admin.ModelAdmin):
    list_display = ('user', 'lender', 'debt_type', 'remaining_amount', 'status')
    list_filter = ('debt_type', 'status')
    search_fields = ('lender', 'user__username')

@admin.register(FinancialMetric)
class FinancialMetricAdmin(admin.ModelAdmin):
    list_display = ('user', 'recorded_date', 'metric_type', 'value', 'unit')
    list_filter = ('recorded_date', 'metric_type')
    search_fields = ('user__username',)
    date_hierarchy = 'recorded_date'