from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import AuditLog, SecurityAlert, ComplianceRecord, AuditTrail

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class AuditLogSerializer(serializers.ModelSerializer):
    actor_details = UserSerializer(source='actor', read_only=True)
    target_user_details = UserSerializer(source='target_user', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    is_sensitive = serializers.BooleanField(read_only=True)
    duration = serializers.DurationField(read_only=True, allow_null=True)
    
    class Meta:
        model = AuditLog
        fields = [
            'id', 'correlation_id', 'actor', 'actor_details',
            'target_user', 'target_user_details', 'source', 'source_display',
            'action', 'action_display', 'severity', 'severity_display',
            'description', 'ip_address', 'user_agent', 'session_id',
            'metadata', 'parent_event', 'created_at', 'is_sensitive',
            'duration'
        ]
        read_only_fields = fields


class SecurityAlertSerializer(serializers.ModelSerializer):
    user_details = UserSerializer(source='user', read_only=True)
    assigned_to_details = UserSerializer(source='assigned_to', read_only=True)
    resolved_by_details = UserSerializer(source='resolved_by', read_only=True)
    alert_type_display = serializers.CharField(source='get_alert_type_display', read_only=True)
    severity_display = serializers.CharField(source='get_severity_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = SecurityAlert
        fields = [
            'id', 'alert_type', 'alert_type_display', 'title', 'description',
            'user', 'user_details', 'severity', 'severity_display',
            'status', 'status_display', 'ip_address', 'location',
            'device_info', 'evidence_data', 'assigned_to', 'assigned_to_details',
            'resolved_at', 'resolved_by', 'resolved_by_details',
            'resolution_notes', 'created_at', 'updated_at'
        ]
        read_only_fields = fields


class ComplianceRecordSerializer(serializers.ModelSerializer):
    user_details = UserSerializer(source='user', read_only=True)
    verified_by_details = UserSerializer(source='verified_by', read_only=True)
    compliance_type_display = serializers.CharField(source='get_compliance_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    is_overdue = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = ComplianceRecord
        fields = [
            'id', 'compliance_type', 'compliance_type_display',
            'user', 'user_details', 'description', 'status', 'status_display',
            'due_date', 'submitted_date', 'approved_date', 'verified',
            'verified_by', 'verified_by_details', 'verification_notes',
            'documents', 'metadata', 'created_at', 'updated_at', 'is_overdue'
        ]
        read_only_fields = fields


class AuditTrailSerializer(serializers.ModelSerializer):
    user_details = UserSerializer(source='user', read_only=True)
    operation_display = serializers.CharField(source='get_operation_display', read_only=True)
    changes_summary = serializers.CharField(source='get_changes_summary', read_only=True)
    
    class Meta:
        model = AuditTrail
        fields = [
            'id', 'object_type', 'object_id', 'operation', 'operation_display',
            'user', 'user_details', 'old_value', 'new_value', 'changes',
            'changes_summary', 'ip_address', 'reason', 'timestamp'
        ]
        read_only_fields = fields


class AuditStatsSerializer(serializers.Serializer):
    total_logs = serializers.IntegerField()
    by_severity = serializers.DictField(child=serializers.IntegerField())
    by_source = serializers.DictField(child=serializers.IntegerField())
    by_action = serializers.DictField(child=serializers.IntegerField())
    security_alerts = serializers.IntegerField()
    open_alerts = serializers.IntegerField()
    top_actors = serializers.ListField(child=serializers.DictField())
    suspicious_ips = serializers.ListField(child=serializers.DictField())
    period = serializers.CharField(required=False)


class SearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    sources = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    actions = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    severities = serializers.ListField(
        child=serializers.CharField(),
        required=False
    )
    actor_id = serializers.IntegerField(required=False)
    target_id = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(default=100, min_value=1, max_value=1000)


class ExportRequestSerializer(serializers.Serializer):
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)
    format = serializers.ChoiceField(
        choices=['json', 'csv', 'xlsx'],
        default='json'
    )