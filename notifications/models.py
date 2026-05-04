# notifications/models.py
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()

class Notification(models.Model):
    """System notifications for users"""
    EVENT_CATEGORIES = [
        ('PAYMENT', 'Payment'),
        ('TRANSACTION', 'Transaction'),
        ('BUDGET', 'Budget'),
        ('SAVINGS', 'Savings'),
        ('INVESTMENT', 'Investment'),
        ('DEBT', 'Debt'),
        ('INCOME', 'Income'),
        ('BILL', 'Bill'),
        ('REMINDER', 'Reminder'),
        ('ALERT', 'Alert'),
        ('INSIGHT', 'Insight'),
        ('SECURITY', 'Security'),
        ('SYSTEM', 'System'),
        ('PROMOTIONAL', 'Promotional'),
        ('UPDATE', 'Update')
    ]
    
    SEVERITY_LEVELS = [
        ('INFO', 'Information'),
        ('SUCCESS', 'Success'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical')
    ]
    
    DELIVERY_STATUS = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('DELIVERED', 'Delivered'),
        ('READ', 'Read'),
        ('FAILED', 'Failed')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')
    
    # Content
    title = models.CharField(max_length=200)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=EVENT_CATEGORIES, default='SYSTEM')
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='INFO')
    
    # Delivery
    delivery_method = models.CharField(max_length=20, choices=[
        ('IN_APP', 'In-App'),
        ('EMAIL', 'Email'),
        ('SMS', 'SMS'),
        ('PUSH', 'Push Notification'),
        ('ALL', 'All Channels')
    ], default='IN_APP')
    
    delivery_status = models.CharField(max_length=20, choices=DELIVERY_STATUS, default='PENDING')
    delivery_attempts = models.PositiveIntegerField(default=0)
    last_delivery_attempt = models.DateTimeField(null=True, blank=True)
    
    # Read/Interaction
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    
    requires_acknowledgment = models.BooleanField(default=False)
    is_acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    
    # Action
    action_required = models.BooleanField(default=False)
    action_type = models.CharField(max_length=50, blank=True, null=True)
    action_data = models.JSONField(default=dict, blank=True)
    action_url = models.URLField(blank=True, null=True)
    action_completed = models.BooleanField(default=False)
    action_completed_at = models.DateTimeField(null=True, blank=True)
    
    # Related entities
    related_transaction = models.ForeignKey('payments_core.PaymentTransaction', on_delete=models.SET_NULL, null=True, blank=True)
    related_payment = models.ForeignKey('payments_core.PaymentIntent', on_delete=models.SET_NULL, null=True, blank=True)
    related_bill = models.ForeignKey('finnova_autopilot.SmartBill', on_delete=models.SET_NULL, null=True, blank=True)
    related_budget = models.ForeignKey('finance.Budget', on_delete=models.SET_NULL, null=True, blank=True)
    related_goal = models.ForeignKey('finance.FinancialGoal', on_delete=models.SET_NULL, null=True, blank=True)
    related_alert = models.ForeignKey('finnova_autopilot.Alert', on_delete=models.SET_NULL, null=True, blank=True)
    related_insight = models.ForeignKey('analytics_ai.FinancialInsight', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', 'created_at']),
            models.Index(fields=['category', 'severity', 'created_at']),
            models.Index(fields=['delivery_status', 'created_at']),
        ]
    
    def __str__(self):
        status = "Read" if self.is_read else "Unread"
        return f"{self.title} - {self.category} - {self.severity} - {status}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        self.is_read = True
        self.read_at = timezone.now()
        self.save()
    
    def acknowledge(self):
        """Acknowledge notification"""
        self.is_acknowledged = True
        self.acknowledged_at = timezone.now()
        self.save()
    
    def complete_action(self):
        """Mark action as completed"""
        self.action_completed = True
        self.action_completed_at = timezone.now()
        self.save()
    
    def get_severity_color(self):
        """Get color for severity display"""
        severity_colors = {
            'INFO': '#2196F3',      # Blue
            'SUCCESS': '#4CAF50',    # Green
            'WARNING': '#FFC107',    # Amber
            'ERROR': '#FF9800',      # Orange
            'CRITICAL': '#F44336',   # Red
        }
        return severity_colors.get(self.severity, '#9E9E9E')
    
    def is_expired(self):
        """Check if notification is expired"""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at
    
    @classmethod
    def send_notification(cls, user, title, message, category='SYSTEM', severity='INFO', 
                         delivery_method='IN_APP', related_entity=None, action_data=None):
        """Convenience method to send notification"""
        
        # Determine related entity
        related_transaction = None
        related_payment = None
        related_bill = None
        related_budget = None
        related_goal = None
        related_alert = None
        related_insight = None
        
        if related_entity:
            entity_class = related_entity.__class__.__name__
            if entity_class == 'PaymentTransaction':
                related_transaction = related_entity
            elif entity_class == 'PaymentIntent':
                related_payment = related_entity
            elif entity_class == 'SmartBill':
                related_bill = related_entity
            elif entity_class == 'Budget':
                related_budget = related_entity
            elif entity_class == 'FinancialGoal':
                related_goal = related_entity
            elif entity_class == 'Alert':
                related_alert = related_entity
            elif entity_class == 'FinancialInsight':
                related_insight = related_entity
        
        # Create notification
        notification = cls.objects.create(
            user=user,
            title=title,
            message=message,
            category=category,
            severity=severity,
            delivery_method=delivery_method,
            action_data=action_data or {},
            related_transaction=related_transaction,
            related_payment=related_payment,
            related_bill=related_bill,
            related_budget=related_budget,
            related_goal=related_goal,
            related_alert=related_alert,
            related_insight=related_insight,
            metadata={'source': 'system'}
        )
        
        return notification

class NotificationPreference(models.Model):
    """User notification preferences"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notification_preferences')
    
    # Channel preferences
    email_notifications = models.BooleanField(default=True)
    sms_notifications = models.BooleanField(default=False)
    push_notifications = models.BooleanField(default=True)
    in_app_notifications = models.BooleanField(default=True)
    
    # Category preferences
    payment_notifications = models.BooleanField(default=True)
    transaction_notifications = models.BooleanField(default=True)
    budget_notifications = models.BooleanField(default=True)
    savings_notifications = models.BooleanField(default=True)
    investment_notifications = models.BooleanField(default=True)
    debt_notifications = models.BooleanField(default=True)
    income_notifications = models.BooleanField(default=True)
    bill_notifications = models.BooleanField(default=True)
    reminder_notifications = models.BooleanField(default=True)
    alert_notifications = models.BooleanField(default=True)
    insight_notifications = models.BooleanField(default=True)
    security_notifications = models.BooleanField(default=True)
    system_notifications = models.BooleanField(default=True)
    promotional_notifications = models.BooleanField(default=False)
    
    # Timing preferences
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    daily_digest = models.BooleanField(default=True)
    weekly_summary = models.BooleanField(default=True)
    monthly_report = models.BooleanField(default=True)
    
    # Delivery preferences
    immediate_alerts = models.BooleanField(default=True)
    batch_notifications = models.BooleanField(default=True)
    batch_frequency = models.CharField(max_length=20, choices=[
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('BIWEEKLY', 'Bi-weekly'),
        ('MONTHLY', 'Monthly')
    ], default='DAILY')
    
    # Language and format
    notification_language = models.CharField(max_length=10, default='en')
    preferred_format = models.CharField(max_length=20, choices=[
        ('TEXT', 'Text Only'),
        ('HTML', 'HTML Format'),
        ('RICH', 'Rich Format')
    ], default='RICH')
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'
    
    def __str__(self):
        return f"Notification Preferences - {self.user.username}"
    
    def can_send_notification(self, category, severity='INFO'):
        """Check if notification can be sent based on preferences"""
        
        # Check category preference
        category_field = f"{category.lower()}_notifications"
        if hasattr(self, category_field):
            if not getattr(self, category_field, True):
                return False
        
        # Check quiet hours
        if self.quiet_hours_start and self.quiet_hours_end:
            now = timezone.now().time()
            if self.quiet_hours_start < self.quiet_hours_end:
                if self.quiet_hours_start <= now <= self.quiet_hours_end:
                    # In quiet hours, only send critical notifications
                    if severity not in ['CRITICAL', 'ERROR']:
                        return False
            else:
                # Quiet hours span midnight
                if now >= self.quiet_hours_start or now <= self.quiet_hours_end:
                    if severity not in ['CRITICAL', 'ERROR']:
                        return False
        
        # Check delivery method preferences
        if not self.in_app_notifications:
            return False
        
        return True
    
    def get_preferred_channels(self, category, severity='INFO'):
        """Get preferred delivery channels for notification"""
        channels = []
        
        # Always include in-app if enabled
        if self.in_app_notifications:
            channels.append('IN_APP')
        
        # Email for important notifications
        if self.email_notifications and severity in ['CRITICAL', 'ERROR', 'WARNING', 'SUCCESS']:
            channels.append('EMAIL')
        
        # SMS for critical alerts
        if self.sms_notifications and severity in ['CRITICAL', 'ERROR']:
            channels.append('SMS')
        
        # Push notifications
        if self.push_notifications:
            channels.append('PUSH')
        
        return channels

class NotificationTemplate(models.Model):
    """Template for system notifications"""
    template_id = models.CharField(max_length=100, unique=True, db_index=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    
    # Template content (supports string formatting)
    title_template = models.CharField(max_length=255)
    message_template = models.TextField()
    action_hint_template = models.CharField(max_length=255, blank=True, null=True)
    
    # Default settings
    default_severity = models.CharField(
        max_length=20, 
        choices=Notification.SEVERITY_LEVELS, 
        default='INFO'
    )
    default_category = models.CharField(
        max_length=20, 
        choices=Notification.EVENT_CATEGORIES, 
        default='SYSTEM'
    )
    requires_acknowledgment = models.BooleanField(default=False)
    
    # Validation/Variables
    variables = models.JSONField(default=list, blank=True)  # List of required context variables
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['template_id']
    
    def __str__(self):
        return f"{self.template_id} - {self.name}"
