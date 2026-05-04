from django.contrib import admin
from django.utils.html import format_html
from .models import Notification, NotificationPreference, NotificationTemplate

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user_email', 'title_truncated', 
                    'severity_badge', 'category', 'is_read', 'created_at']
    list_filter = ['severity', 'category', 'is_read', 'created_at']
    search_fields = ['title', 'message', 'user__email', 'user__username']
    readonly_fields = ['id', 'created_at']
    list_per_page = 50
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'id', 'title', 'message')
        }),
        ('Classification', {
            'fields': ('category', 'severity')
        }),
        ('Delivery', {
            'fields': ('delivery_method', 'delivery_status', 'delivery_attempts', 'last_delivery_attempt')
        }),
        ('Status', {
            'fields': ('is_read', 'read_at', 'is_acknowledged', 'acknowledged_at', 'requires_acknowledgment')
        }),
        ('Actions', {
            'fields': ('action_required', 'action_type', 'action_url', 'action_completed', 'action_completed_at')
        }),
        ('Relationships', {
            'fields': ('related_transaction', 'related_payment', 'related_bill', 'related_budget', 'related_goal', 'related_alert', 'related_insight')
        }),
        ('Metadata', {
            'fields': ('metadata', 'expires_at', 'created_at')
        }),
    )
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User Email'
    
    def title_truncated(self, obj):
        return f'{obj.title[:50]}...' if len(obj.title) > 50 else obj.title
    title_truncated.short_description = 'Title'
    
    def severity_badge(self, obj):
        colors = {
            'CRITICAL': 'red',
            'HIGH': 'orange',
            'MEDIUM': 'yellow',
            'LOW': 'green',
            'INFO': 'blue'
        }
        color = colors.get(obj.severity, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 8px; border-radius: 10px;">{}</span>',
            color, obj.severity
        )
    severity_badge.short_description = 'Severity'
    
    actions = ['mark_as_read', 'mark_as_unread', 'archive_selected']
    
    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f"{updated} notifications marked as read.")
    mark_as_read.short_description = "Mark selected as read"
    
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False)
        self.message_user(request, f"{updated} notifications marked as unread.")
    mark_as_unread.short_description = "Mark selected as unread"
    
    def archive_selected(self, request, queryset):
        updated = queryset.update(is_archived=True)
        self.message_user(request, f"{updated} notifications archived.")
    archive_selected.short_description = "Archive selected"


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ['user', 'email_notifications', 'push_notifications', 'sms_notifications', 'updated_at']
    list_filter = ['email_notifications', 'push_notifications', 'sms_notifications']
    search_fields = ['user__email', 'user__username']
    readonly_fields = ['updated_at']
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Channel Preferences', {
            'fields': ('email_notifications', 'push_notifications', 'sms_notifications', 'in_app_notifications')
        }),
        ('Category Preferences', {
            'fields': ('payment_notifications', 'transaction_notifications', 'budget_notifications', 'savings_notifications', 'investment_notifications', 'debt_notifications', 'income_notifications', 'bill_notifications', 'reminder_notifications', 'alert_notifications', 'insight_notifications', 'security_notifications', 'system_notifications', 'promotional_notifications')
        }),
        ('Timing & Delivery', {
            'fields': ('quiet_hours_start', 'quiet_hours_end', 'daily_digest', 'weekly_summary', 'monthly_report', 'immediate_alerts', 'batch_notifications', 'batch_frequency')
        }),
        ('Format Settings', {
            'fields': ('notification_language', 'preferred_format')
        }),
        ('Metadata', {
            'fields': ('updated_at',)
        }),
    )


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ['template_id', 'name', 'default_severity', 'default_category', 'is_active']
    list_filter = ['is_active', 'default_severity', 'default_category']
    search_fields = ['template_id', 'name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Identification', {
            'fields': ('template_id', 'name', 'description')
        }),
        ('Template Content', {
            'fields': ('title_template', 'message_template', 'action_hint_template')
        }),
        ('Default Settings', {
            'fields': ('default_severity', 'default_category', 'requires_acknowledgment')
        }),
        ('Variables', {
            'fields': ('variables',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )