from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
# Add these imports:
from .models import AuditLog, SecurityAlert, ComplianceRecord, AuditTrail, SystemControl, UserRiskFlag
import csv
from django.http import HttpResponse


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Admin interface for Audit Logs"""
    list_display = [
        'id', 'source_badge', 'action', 'severity_badge', 
        'actor_info', 'target_info', 'timestamp', 'quick_actions'
    ]
    list_filter = [
        'source', 'severity', 'created_at', 'actor', 'target_user'
    ]
    search_fields = [
        'action', 'description', 'actor__username', 
        'target_user__username', 'source', 'metadata'
    ]
    readonly_fields = [
        'actor', 'target_user', 'source', 'action', 
        'severity', 'description', 'metadata', 'created_at'
    ]
    fieldsets = (
        ('Event Details', {
            'fields': ('source', 'action', 'severity', 'description')
        }),
        ('User Information', {
            'fields': ('actor', 'target_user')
        }),
        ('Additional Information', {
            'fields': ('metadata', 'created_at'),
            'classes': ('collapse',)
        }),
    )
    actions = ['export_as_csv', 'mark_as_reviewed', 'archive_logs']
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)
    list_per_page = 50

    def source_badge(self, obj):
        colors = {
            'AUTOPILOT': 'primary',
            'AI': 'info',
            'ADMIN': 'success',
            'WALLET': 'warning',
            'SYSTEM': 'secondary',
            'FINANCE': 'danger',
            'PAYMENTS': 'purple',
            'SECURITY': 'dark'
        }
        color = colors.get(obj.source, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color, obj.source
        )
    source_badge.short_description = 'Source'
    source_badge.admin_order_field = 'source'

    def severity_badge(self, obj):
        colors = {
            'LOW': 'success',
            'MEDIUM': 'warning',
            'HIGH': 'danger',
            'CRITICAL': 'dark'
        }
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(obj.severity, 'secondary'),
            obj.get_severity_display()
        )
    severity_badge.short_description = 'Severity'
    severity_badge.admin_order_field = 'severity'

    def actor_info(self, obj):
        if obj.actor:
            return format_html(
                '<strong>{}</strong><br><small class="text-muted">{}</small>',
                obj.actor.username,
                obj.actor.email or 'No email'
            )
        return format_html('<span class="text-muted">System</span>')
    actor_info.short_description = 'Actor'
    actor_info.admin_order_field = 'actor__username'

    def target_info(self, obj):
        if obj.target_user:
            return format_html(
                '<strong>{}</strong><br><small class="text-muted">{}</small>',
                obj.target_user.username,
                obj.target_user.email or 'No email'
            )
        return format_html('<span class="text-muted">N/A</span>')
    target_info.short_description = 'Target User'
    target_info.admin_order_field = 'target_user__username'

    def timestamp(self, obj):
        return obj.created_at.strftime('%Y-%m-%d %H:%M:%S')
    timestamp.short_description = 'Timestamp'
    timestamp.admin_order_field = 'created_at'

    def quick_actions(self, obj):
        return format_html(
            '''
            <div class="btn-group">
                <button class="btn btn-sm btn-outline-primary" 
                        onclick="showLogDetails({})">View</button>
                <button class="btn btn-sm btn-outline-info"
                        onclick="copyLogId({})">Copy ID</button>
            </div>
            ''',
            obj.id, obj.id
        )
    quick_actions.short_description = 'Actions'

    def has_add_permission(self, request):
        """Audit logs should only be created by system, not manually"""
        return False

    def has_change_permission(self, request, obj=None):
        """Audit logs are immutable"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete audit logs"""
        return request.user.is_superuser

    def export_as_csv(self, request, queryset):
        """Export selected audit logs as CSV"""
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename=audit_logs_{timezone.now().date()}.csv'

        writer = csv.writer(response)
        writer.writerow(field_names)
        for obj in queryset:
            row = [getattr(obj, field) for field in field_names]
            writer.writerow(row)

        return response
    export_as_csv.short_description = "Export Selected as CSV"

    def mark_as_reviewed(self, request, queryset):
        """Mark logs as reviewed"""
        updated = queryset.update(metadata={'reviewed': True, 'reviewed_by': request.user.username})
        self.message_user(request, f"{updated} audit logs marked as reviewed.")
    mark_as_reviewed.short_description = "Mark as reviewed"

    def archive_logs(self, request, queryset):
        """Archive old logs"""
        six_months_ago = timezone.now() - timezone.timedelta(days=180)
        old_logs = queryset.filter(created_at__lt=six_months_ago)
        count = old_logs.count()
        # In production, you would move to archival storage
        self.message_user(request, f"{count} logs marked for archival.")
    archive_logs.short_description = "Archive old logs"

    class Media:
        css = {
            'all': ('admin/css/audit_admin.css',)
        }
        js = ('admin/js/audit_admin.js',)


@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    """Admin interface for Security Alerts"""
    list_display = [
        'id', 'alert_type_badge', 'severity_badge', 'user_info',
        'status_badge', 'detected_at', 'resolved_at'
    ]
    list_filter = ['alert_type', 'severity', 'status', 'detected_at']
    search_fields = ['title', 'description', 'user__username', 'ip_address']
    readonly_fields = ['detected_at', 'updated_at', 'resolved_at']
    actions = ['mark_as_resolved', 'escalate_alert', 'export_alerts']
    list_per_page = 30

    def alert_type_badge(self, obj):
        colors = {
            'LOGIN_ATTEMPT': 'info',
            'UNAUTHORIZED_ACCESS': 'danger',
            'DATA_BREACH': 'dark',
            'FRAUD_DETECTED': 'warning',
            'SYSTEM_ANOMALY': 'secondary'
        }
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(obj.alert_type, 'secondary'),
            obj.get_alert_type_display()
        )

    def severity_badge(self, obj):
        colors = {
            'LOW': 'success',
            'MEDIUM': 'warning',
            'HIGH': 'danger',
            'CRITICAL': 'dark'
        }
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(obj.severity, 'secondary'),
            obj.get_severity_display()
        )

    def status_badge(self, obj):
        colors = {
            'OPEN': 'danger',
            'INVESTIGATING': 'warning',
            'RESOLVED': 'success',
            'ESCALATED': 'info'
        }
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(obj.status, 'secondary'),
            obj.get_status_display()
        )

    def user_info(self, obj):
        return f"{obj.user.username} ({obj.user.email})" if obj.user else "System"

    def mark_as_resolved(self, request, queryset):
        updated = queryset.update(
            status='RESOLVED',
            resolved_at=timezone.now(),
            resolved_by=request.user
        )
        self.message_user(request, f"{updated} alerts marked as resolved.")
    mark_as_resolved.short_description = "Mark as resolved"

    def escalate_alert(self, request, queryset):
        updated = queryset.update(status='ESCALATED')
        self.message_user(request, f"{updated} alerts escalated.")
    escalate_alert.short_description = "Escalate alerts"


@admin.register(ComplianceRecord)
class ComplianceRecordAdmin(admin.ModelAdmin):
    """Admin interface for Compliance Records"""
    list_display = [
        'id', 'compliance_type_badge', 'status_badge',
        'user_info', 'due_date', 'completed_date', 'verified'
    ]
    list_filter = ['compliance_type', 'status', 'verified', 'due_date']
    search_fields = ['user__username', 'description', 'compliance_type']
    readonly_fields = ['created_at', 'updated_at']
    actions = ['mark_as_verified', 'generate_compliance_report']
    list_per_page = 30

    def compliance_type_badge(self, obj):
        colors = {
            'GDPR': 'primary',
            'PCI_DSS': 'info',
            'HIPAA': 'success',
            'SOC2': 'warning',
            'ISO27001': 'secondary'
        }
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(obj.compliance_type, 'secondary'),
            obj.get_compliance_type_display()
        )

    def status_badge(self, obj):
        colors = {
            'PENDING': 'warning',
            'SUBMITTED': 'info',
            'APPROVED': 'success',
            'REJECTED': 'danger',
            'OVERDUE': 'dark'
        }
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(obj.status, 'secondary'),
            obj.get_status_display()
        )

    def user_info(self, obj):
        return f"{obj.user.username} ({obj.user.email})" if obj.user else "System"

    def mark_as_verified(self, request, queryset):
        updated = queryset.update(verified=True, verified_by=request.user)
        self.message_user(request, f"{updated} records marked as verified.")
    mark_as_verified.short_description = "Mark as verified"


admin.site.site_header = "Finnova Audit System"
admin.site.site_title = "Audit Administration"
admin.site.index_title = "Audit Dashboard"

@admin.register(UserRiskFlag)
class UserRiskFlagAdmin(admin.ModelAdmin):
    """Admin interface for User Risk Flags"""
    list_display = ['user', 'severity_badge', 'flagged_by', 'created_at', 'quick_actions']
    list_filter = ['created_at', 'flagged_by']
    search_fields = ['user__username', 'user__email', 'reason']
    readonly_fields = ['created_at']
    actions = ['escalate_severity', 'clear_flag']
    
    def severity_badge(self, obj):
        colors = {
            'LOW': 'success',
            'MEDIUM': 'warning',
            'HIGH': 'danger',
            'CRITICAL': 'dark',
            'MINIMAL': 'info'
        }
        level = obj.risk_level
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(level, 'secondary'),
            level
        )
    severity_badge.short_description = 'Severity'
    
    def quick_actions(self, obj):
        return format_html(
            '''
            <div class="btn-group">
                <a href="/admin/audit/userriskflag/{}/change/" class="btn btn-sm btn-outline-primary">Edit</a>
                <button class="btn btn-sm btn-outline-danger" 
                        onclick="confirmFlagRemoval({})">Remove</button>
            </div>
            ''',
            obj.id, obj.id
        )
    quick_actions.short_description = 'Actions'


@admin.register(SystemControl)
class SystemControlAdmin(admin.ModelAdmin):
    """Admin interface for System Controls"""
    list_display = ['autopilot_status', 'ai_status', 'emergency_indicator', 'last_updated']
    
    def autopilot_status(self, obj):
        color = 'success' if obj.autopilot_enabled else 'danger'
        text = 'ACTIVE' if obj.autopilot_enabled else 'DISABLED'
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color, text
        )
    autopilot_status.short_description = 'Autopilot'
    
    def ai_status(self, obj):
        color = 'success' if obj.ai_enabled else 'danger'
        text = 'ACTIVE' if obj.ai_enabled else 'DISABLED'
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color, text
        )
    ai_status.short_description = 'AI System'
    
    def emergency_indicator(self, obj):
        if obj.emergency_message:
            return format_html(
                '<span class="badge bg-danger">⚠️ EMERGENCY</span>'
            )
        return format_html(
            '<span class="badge bg-success">Normal</span>'
        )
    emergency_indicator.short_description = 'Status'
    
    def has_add_permission(self, request):
        # Only one SystemControl record should exist
        return not SystemControl.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Prevent deletion of system controls
        return False