from django.contrib import admin
from django.utils.html import format_html
from .models import (
    UserFinancialProfile, FinancialInsight, 
    PredictiveAlert, AISession, SmartRule
)

@admin.register(UserFinancialProfile)
class UserFinancialProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'financial_personality', 'risk_level', 'income_stability', 'analyzed_at')
    list_filter = ('financial_personality', 'risk_level', 'income_stability')
    search_fields = ('user__username', 'user__email')

@admin.register(FinancialInsight)
class FinancialInsightAdmin(admin.ModelAdmin):
    list_display = ('user', 'insight_type', 'title', 'severity', 'action_required', 'created_at')
    list_filter = ('insight_type', 'severity', 'action_required', 'created_at')
    search_fields = ('user__username', 'title', 'description')
    readonly_fields = ('created_at',)
    
    def colored_severity(self, obj):
        colors = {
            'LOW': 'green',
            'MEDIUM': 'orange',
            'HIGH': 'red',
            'CRITICAL': 'darkred'
        }
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colors.get(obj.severity, 'black'),
            obj.severity
        )
    colored_severity.short_description = 'Severity'

@admin.register(PredictiveAlert)
class PredictiveAlertAdmin(admin.ModelAdmin):
    list_display = ('user', 'alert_type', 'predicted_date', 'predicted_amount', 
                   'confidence_score', 'is_active', 'has_occurred')
    list_filter = ('alert_type', 'is_active', 'has_occurred', 'predicted_date')
    search_fields = ('user__username', 'description')

@admin.register(AISession)
class AISessionAdmin(admin.ModelAdmin):
    list_display = ('user', 'session_type', 'ai_response_time_avg', 'is_completed', 'started_at')
    list_filter = ('session_type', 'is_completed', 'started_at')
    search_fields = ('user__username',)
    readonly_fields = ('started_at',)

@admin.register(SmartRule)
class SmartRuleAdmin(admin.ModelAdmin):
    list_display = ('user', 'name', 'condition_type', 'action_type', 'is_active', 'last_executed')
    list_filter = ('condition_type', 'action_type', 'is_active')
    search_fields = ('user__username', 'name')