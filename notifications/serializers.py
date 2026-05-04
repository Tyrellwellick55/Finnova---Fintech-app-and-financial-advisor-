from rest_framework import serializers
from .models import Notification, NotificationPreference, NotificationTemplate
from django.contrib.auth import get_user_model

User = get_user_model()


class NotificationSerializer(serializers.ModelSerializer):
    """
    Serializer for Notification model
    """
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.CharField(source='user.get_full_name', read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_urgent = serializers.BooleanField(read_only=True)
    time_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id',
            'notification_id',
            'user',
            'user_email',
            'user_name',
            'source',
            'event_type',
            'severity',
            'title',
            'message',
            'action_hint',
            'action_url',
            'is_read',
            'is_archived',
            'requires_acknowledgment',
            'acknowledged_at',
            'related_app',
            'related_model',
            'related_id',
            'metadata',
            'priority',
            'created_at',
            'updated_at',
            'expires_at',
            'is_expired',
            'is_urgent',
            'time_ago',
            'sent_via_email',
            'sent_via_push',
            'sent_via_sms',
        ]
        read_only_fields = [
            'id', 'notification_id', 'created_at', 'updated_at',
            'sent_via_email', 'sent_via_push', 'sent_via_sms'
        ]
    
    def get_time_ago(self, obj):
        from django.utils.timesince import timesince
        return timesince(obj.created_at)


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    """
    Serializer for Notification Preference model
    """
    class Meta:
        model = NotificationPreference
        fields = [
            'id',
            'user',
            'email_enabled',
            'push_enabled',
            'sms_enabled',
            'email_min_severity',
            'push_min_severity',
            'sms_min_severity',
            'quiet_hours_start',
            'quiet_hours_end',
            'respect_quiet_hours',
            'enabled_categories',
            'muted_sources',
            'max_daily_emails',
            'max_daily_pushes',
            'updated_at',
        ]
        read_only_fields = ['id', 'user', 'updated_at']


class NotificationTemplateSerializer(serializers.ModelSerializer):
    """
    Serializer for Notification Template model
    """
    class Meta:
        model = NotificationTemplate
        fields = [
            'id',
            'template_id',
            'name',
            'description',
            'title_template',
            'message_template',
            'action_hint_template',
            'default_severity',
            'default_category',
            'requires_acknowledgment',
            'variables',
            'is_active',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class MarkAsReadSerializer(serializers.Serializer):
    """
    Serializer for marking notifications as read
    """
    notification_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False
    )
    all = serializers.BooleanField(default=False)


class BulkActionSerializer(serializers.Serializer):
    """
    Serializer for bulk notification actions
    """
    ACTION_CHOICES = [
        ('mark_read', 'Mark as Read'),
        ('archive', 'Archive'),
        ('delete', 'Delete'),
    ]
    
    action = serializers.ChoiceField(choices=ACTION_CHOICES)
    notification_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=True
    )