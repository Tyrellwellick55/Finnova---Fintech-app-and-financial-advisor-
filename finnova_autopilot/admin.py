from django.contrib import admin
from django.utils.html import format_html
from .models import (
    AutopilotProfile, AutomationRule, SmartBill,
    InvestmentPlan, SavingsGoal, FinancialHealthScore,
    TransactionPattern, Alert, AITrainingData
)

@admin.register(AutopilotProfile)
class AutopilotProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_active', 'risk_tolerance', 'total_money_saved', 'last_run']
    list_filter = ['is_active', 'risk_tolerance', 'created_at']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at', 'last_run']
    fieldsets = (
        ('User', {'fields': ('user',)}),
        ('Settings', {'fields': ('is_active', 'risk_tolerance')}),
        ('Savings Automation', {'fields': ('auto_savings_enabled', 'auto_savings_amount', 'auto_savings_frequency', 'auto_savings_day')}),
        ('Investment Automation', {'fields': ('auto_investment_enabled', 'auto_investment_amount', 'auto_investment_strategy')}),
        ('Budget Settings', {'fields': ('monthly_budget', 'budget_alerts_enabled', 'budget_alert_threshold')}),
        ('Automation Settings', {'fields': ('auto_pay_bills', 'auto_pay_days_before', 'auto_debt_payment', 'debt_payment_strategy')}),
        ('AI Settings', {'fields': ('ai_recommendations_enabled', 'learning_enabled')}),
        ('Performance', {'fields': ('total_money_saved', 'total_investment_gains', 'total_interest_saved')}),
        ('Metadata', {'fields': ('created_at', 'updated_at', 'last_run', 'preferences', 'notification_settings')}),
    )

@admin.register(AutomationRule)
class AutomationRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'rule_type', 'condition_type', 'is_active', 'last_executed']
    list_filter = ['rule_type', 'condition_type', 'is_active', 'created_at']
    search_fields = ['name', 'user__username', 'description']
    readonly_fields = ['created_at', 'updated_at', 'last_executed', 'execution_count']
    fieldsets = (
        ('Basic Info', {'fields': ('user', 'name', 'description')}),
        ('Rule Configuration', {'fields': ('rule_type', 'condition_type', 'condition_value')}),
        ('Action Configuration', {'fields': ('action_type', 'action_value')}),
        ('Execution Settings', {'fields': ('priority', 'is_active', 'run_once', 'schedule_type', 'schedule_value')}),
        ('Performance', {'fields': ('execution_count', 'last_executed', 'success_count', 'failure_count')}),
        ('Linked Entities', {'fields': ('linked_account', 'linked_goal')}),
        ('Metadata', {'fields': ('created_at', 'updated_at', 'metadata')}),
    )

@admin.register(SmartBill)
class SmartBillAdmin(admin.ModelAdmin):
    list_display = ['biller_name', 'user', 'amount', 'due_date', 'status', 'auto_pay', 'is_overdue_display']
    list_filter = ['status', 'biller_category', 'is_recurring', 'auto_pay', 'due_date']
    search_fields = ['biller_name', 'user__username', 'consumer_number']
    readonly_fields = ['created_at', 'updated_at']
    list_editable = ['status', 'auto_pay']
    
    fieldsets = (
        ('Bill Information', {'fields': ('user', 'biller_name', 'biller_category', 'bill_number', 'consumer_number', 'bill_period')}),
        ('Amount & Dates', {'fields': ('amount', 'due_date', 'paid_date', 'paid_amount')}),
        ('Payment Status', {'fields': ('status', 'is_recurring', 'recurrence_pattern', 'recurrence_value')}),
        ('Automation', {'fields': ('auto_pay', 'auto_pay_days_before', 'auto_pay_account')}),
        ('Documents', {'fields': ('bill_image', 'bill_data')}),
        ('Reminders', {'fields': ('reminder_sent', 'last_reminder_sent')}),
        ('Payment Reference', {'fields': ('payment_reference',)}),
        ('Metadata', {'fields': ('created_at', 'updated_at', 'metadata')}),
    )
    
    def is_overdue_display(self, obj):
        if obj.is_overdue:
            return format_html('<span style="color: red; font-weight: bold;">OVERDUE</span>')
        return format_html('<span style="color: green;">On Time</span>')
    is_overdue_display.short_description = 'Overdue Status'

@admin.register(InvestmentPlan)
class InvestmentPlanAdmin(admin.ModelAdmin):
    list_display = ['goal_name', 'user', 'target_amount', 'current_invested', 'progress_display', 'target_date']
    list_filter = ['status', 'risk_profile', 'is_auto_invest']
    search_fields = ['goal_name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Goal Information', {'fields': ('user', 'goal_name', 'status')}),
        ('Target & Timeline', {'fields': ('target_amount', 'target_date', 'start_date')}),
        ('Risk & Strategy', {'fields': ('risk_profile', 'investment_strategy', 'suggested_monthly_investment', 'actual_monthly_investment', 'expected_return_rate')}),
        ('Current Status', {'fields': ('current_invested', 'current_value', 'total_return', 'last_investment_date', 'next_investment_date')}),
        ('Automation', {'fields': ('is_auto_invest', 'investment_day', 'source_account')}),
        ('Allocation', {'fields': ('asset_allocation', 'instruments')}),
        ('Metadata', {'fields': ('created_at', 'updated_at', 'metadata')}),
    )
    
    def progress_display(self, obj):
        percentage = obj.progress_percentage
        color = 'green' if percentage >= 80 else 'orange' if percentage >= 50 else 'red'
        return format_html('<span style="color: {};">{:.1f}%</span>', color, percentage)
    progress_display.short_description = 'Progress'

@admin.register(SavingsGoal)
class SavingsGoalAdmin(admin.ModelAdmin):
    list_display = ['goal_name', 'user', 'target_amount', 'current_saved', 'progress_display', 'target_date']
    list_filter = ['is_auto_save', 'status', 'priority']
    search_fields = ['goal_name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']
    
    def progress_display(self, obj):
        percentage = obj.progress_percentage
        color = 'green' if percentage >= 80 else 'orange' if percentage >= 50 else 'red'
        return format_html('<span style="color: {};">{:.1f}%</span>', color, percentage)
    progress_display.short_description = 'Progress'

@admin.register(FinancialHealthScore)
class FinancialHealthScoreAdmin(admin.ModelAdmin):
    list_display = ['user', 'overall_score_display', 'grade', 'trend', 'calculated_at']
    list_filter = ['grade', 'trend']
    search_fields = ['user__username']
    readonly_fields = ['calculated_at', 'created_at']
    
    fieldsets = (
        ('User', {'fields': ('user',)}),
        ('Scores', {'fields': ('overall_score', 'grade', 'components')}),
        ('SWOT Analysis', {'fields': ('strengths', 'weaknesses', 'opportunities', 'threats')}),
        ('AI Insights', {'fields': ('insights', 'recommendations')}),
        ('Comparison', {'fields': ('trend', 'percentile', 'benchmark')}),
        ('Metadata', {'fields': ('created_at', 'calculated_at', 'metadata')}),
    )
    
    def overall_score_display(self, obj):
        color = 'green' if obj.overall_score >= 80 else 'orange' if obj.overall_score >= 60 else 'red'
        return format_html('<span style="color: {}; font-weight: bold;">{}/100</span>', color, obj.overall_score)
    overall_score_display.short_description = 'Overall Score'

@admin.register(TransactionPattern)
class TransactionPatternAdmin(admin.ModelAdmin):
    list_display = ['user', 'pattern_type', 'confidence_score_display', 'is_active', 'detected_at']
    list_filter = ['pattern_type', 'is_active']
    search_fields = ['user__username', 'description', 'pattern_name']
    readonly_fields = ['detected_at', 'last_observed']
    
    def confidence_score_display(self, obj):
        percentage = obj.confidence_score * 100
        color = 'green' if percentage >= 80 else 'orange' if percentage >= 60 else 'red'
        return format_html('<span style="color: {};">{:.1f}%</span>', color, percentage)
    confidence_score_display.short_description = 'Confidence'

@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'category', 'severity_display', 'is_read', 'action_required', 'alert_time']
    list_filter = ['category', 'severity', 'is_read', 'action_required', 'source']
    search_fields = ['title', 'message', 'user__username']
    readonly_fields = ['alert_time', 'read_at', 'acknowledged_at']
    list_editable = ['is_read', 'action_required']
    
    def severity_display(self, obj):
        colors = {
            'INFO': 'blue',
            'LOW': 'green',
            'MEDIUM': 'orange',
            'HIGH': 'red',
            'CRITICAL': 'darkred'
        }
        color = colors.get(obj.severity, 'black')
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, obj.severity)
    severity_display.short_description = 'Severity'

@admin.register(AITrainingData)
class AITrainingDataAdmin(admin.ModelAdmin):
    list_display = ['user', 'data_type', 'ai_processed', 'created_at']
    list_filter = ['data_type', 'ai_processed']
    search_fields = ['user__username']
    readonly_fields = ['created_at']