import logging
logger = logging.getLogger(__name__)
# audit/models.py
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid
import json

User = get_user_model()


class UUIDAwareJSONDecoder(json.JSONDecoder):
    """Decode UUID-like strings back into UUID objects for compatibility tests."""

    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=self._object_hook, *args, **kwargs)

    def _object_hook(self, obj):
        def _looks_like_uuid(s: str) -> bool:
            # Fast, non-throwing heuristic: 36 chars with 4 hyphens.
            return isinstance(s, str) and len(s) == 36 and s.count('-') == 4

        for key, value in list(obj.items()):
            if isinstance(value, str):
                if _looks_like_uuid(value):
                    try:
                        obj[key] = uuid.UUID(value)
                    except (ValueError, TypeError, AttributeError):
                        # Not a valid UUID, keep original string.
                        pass
            elif isinstance(value, list):
                converted = []
                for item in value:
                    if isinstance(item, str):
                        if _looks_like_uuid(item):
                            try:
                                converted.append(uuid.UUID(item))
                                continue
                            except (ValueError, TypeError, AttributeError):
                                pass
                    converted.append(item)
                obj[key] = converted
        return obj

class AuditLog(models.Model):
    """System audit log for tracking all actions"""
    SOURCE_CHOICES = [
        ('SYSTEM', 'System'),
        ('USER', 'User Action'),
        ('API', 'API Call'),
        ('PAYMENT', 'Payment System'),
        ('FINANCE', 'Finance Module'),
        ('AUTOPILOT', 'Autopilot'),
        ('AI', 'AI System'),
        ('SECURITY', 'Security System'),
        ('ADMIN', 'Administrator')
    ]
    
    ACTION_CATEGORIES = [
        ('CREATE', 'Create'),
        ('READ', 'Read'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('LOGIN', 'Login'),
        ('LOGOUT', 'Logout'),
        ('PAYMENT', 'Payment'),
        ('TRANSACTION', 'Transaction'),
        ('SETTING', 'Setting Change'),
        ('SECURITY', 'Security Event'),
        ('ERROR', 'Error'),
        ('SYSTEM', 'System Event')
    ]
    
    SEVERITY_CHOICES = [
        ('INFO', 'Information'),
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # B2B tenant
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='audit_logs')
    
    # Who performed the action
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_actions')
    actor_ip = models.GenericIPAddressField(null=True, blank=True)
    actor_user_agent = models.TextField(null=True, blank=True)
    
    # Target of the action
    target_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='audit_targets')
    target_model = models.CharField(max_length=100, blank=True, null=True)
    target_id = models.CharField(max_length=100, blank=True, null=True)
    
    # Action details
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='SYSTEM')
    action = models.CharField(max_length=50, choices=ACTION_CATEGORIES, default='READ')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='INFO')
    
    # Description
    description = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    
    # Location
    location = models.CharField(max_length=255, blank=True, null=True)
    device_info = models.JSONField(default=dict, blank=True)
    
    # Related entities
    related_transaction = models.ForeignKey('payments_core.PaymentTransaction', on_delete=models.SET_NULL, null=True, blank=True)
    related_payment = models.ForeignKey('payments_core.PaymentIntent', on_delete=models.SET_NULL, null=True, blank=True)
    related_alert = models.ForeignKey('finnova_autopilot.Alert', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Chain of events
    parent_event = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_events')
    correlation_id = models.UUIDField(null=True, blank=True)
    
    # Status
    is_success = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True, decoder=UUIDAwareJSONDecoder)
    created_at = models.DateTimeField(auto_now_add=True)

    def __init__(self, *args, **kwargs):
        ip_address = kwargs.pop('ip_address', None)
        user_agent = kwargs.pop('user_agent', None)
        session_id = kwargs.pop('session_id', None)
        super().__init__(*args, **kwargs)
        if ip_address is not None:
            self.actor_ip = ip_address
        if user_agent is not None:
            self.actor_user_agent = user_agent
        if session_id is not None:
            self.metadata = self.metadata or {}
            self.metadata['session_id'] = session_id

    def save(self, *args, **kwargs):
        if not self.correlation_id:
            self.correlation_id = uuid.uuid4()
        return super().save(*args, **kwargs)

    @property
    def ip_address(self):
        return self.actor_ip

    @ip_address.setter
    def ip_address(self, value):
        self.actor_ip = value

    @property
    def user_agent(self):
        return self.actor_user_agent

    @user_agent.setter
    def user_agent(self, value):
        self.actor_user_agent = value

    @property
    def session_id(self):
        return (self.metadata or {}).get('session_id')

    @session_id.setter
    def session_id(self, value):
        self.metadata = self.metadata or {}
        self.metadata['session_id'] = value

    @property
    def user(self):
        return self.actor

    @user.setter
    def user(self, value):
        self.actor = value

    @property
    def timestamp(self):
        return self.created_at

    @timestamp.setter
    def timestamp(self, value):
        self.created_at = value
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['actor', 'created_at']),
            models.Index(fields=['target_user', 'created_at']),
            models.Index(fields=['action', 'created_at']),
            models.Index(fields=['severity', 'created_at']),
            models.Index(fields=['correlation_id']),
        ]
    
    def __str__(self):
        return f"[{self.source}] {self.action} - {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
    
    @property
    def severity_weight(self):
        """Get numeric weight for severity"""
        weights = {
            'INFO': 1,
            'LOW': 2,
            'MEDIUM': 3,
            'HIGH': 4,
            'CRITICAL': 5
        }
        return weights.get(self.severity, 1)
    
    @classmethod
    def log_event(cls, actor=None, action='READ', severity='INFO', description='', 
                  target_user=None, details=None, metadata=None, **kwargs):
        """Convenience method to log audit event"""
        
        log_entry = cls.objects.create(
            actor=actor,
            actor_ip=kwargs.get('ip_address'),
            actor_user_agent=kwargs.get('user_agent'),
            target_user=target_user,
            target_model=kwargs.get('target_model'),
            target_id=kwargs.get('target_id'),
            source=kwargs.get('source', 'SYSTEM'),
            action=action,
            severity=severity,
            description=description,
            details=details or {},
            location=kwargs.get('location'),
            device_info=kwargs.get('device_info', {}),
            related_transaction=kwargs.get('related_transaction'),
            related_payment=kwargs.get('related_payment'),
            related_alert=kwargs.get('related_alert'),
            parent_event=kwargs.get('parent_event'),
            correlation_id=kwargs.get('correlation_id'),
            is_success=kwargs.get('is_success', True),
            error_message=kwargs.get('error_message'),
            metadata=metadata or {}
        )
        
        return log_entry

class SecurityAlert(models.Model):
    """Security alerts and incidents"""
    ALERT_TYPES = [
        ('LOGIN', 'Login Alert'),
        ('FRAUD', 'Fraud Detection'),
        ('SUSPICIOUS', 'Suspicious Activity'),
        ('UNAUTHORIZED', 'Unauthorized Access'),
        ('DATA_BREACH', 'Data Breach'),
        ('MALWARE', 'Malware Detection'),
        ('PHISHING', 'Phishing Attempt'),
        ('BRUTE_FORCE', 'Brute Force Attack'),
        ('UNUSUAL', 'Unusual Behavior'),
        ('COMPLIANCE', 'Compliance Violation')
    ]
    
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('INVESTIGATING', 'Investigating'),
        ('RESOLVED', 'Resolved'),
        ('FALSE_POSITIVE', 'False Positive'),
        ('ESCALATED', 'Escalated')
    ]
    
    SEVERITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Alert details
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES, default='SUSPICIOUS')
    title = models.CharField(max_length=200)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='MEDIUM')
    
    # User involved
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='security_alerts')
    
    # Incident details
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    device_info = models.JSONField(default=dict, blank=True)
    
    # Evidence and investigation
    evidence = models.JSONField(default=dict, blank=True)
    investigation_data = models.JSONField(default=dict, blank=True)
    related_logs = models.ManyToManyField(AuditLog, blank=True, related_name='security_alerts')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    is_active = models.BooleanField(default=True)
    requires_action = models.BooleanField(default=False)
    
    # Resolution
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_alerts')
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True, null=True)
    resolution_type = models.CharField(max_length=50, blank=True, null=True)
    
    # Timing
    detected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-detected_at', 'severity']
    
    def __str__(self):
        return f"{self.alert_type} - {self.severity} - {self.status} - {self.detected_at.date()}"
    
    def mark_as_resolved(self, resolved_by, notes='', resolution_type=''):
        """Mark alert as resolved"""
        self.status = 'RESOLVED'
        self.is_active = False
        self.resolved_by = resolved_by
        self.resolved_at = timezone.now()
        self.resolution_notes = notes
        self.resolution_type = resolution_type
        self.save()
    
    def escalate(self, escalation_reason=''):
        """Escalate alert"""
        self.status = 'ESCALATED'
        self.requires_action = True
        self.metadata['escalation_reason'] = escalation_reason
        self.metadata['escalated_at'] = timezone.now().isoformat()
        self.save()
    
    def add_evidence(self, evidence_type, evidence_data, description=''):
        """Add evidence to investigation"""
        if 'evidence_log' not in self.evidence:
            self.evidence['evidence_log'] = []
        
        self.evidence['evidence_log'].append({
            'type': evidence_type,
            'data': evidence_data,
            'description': description,
            'added_at': timezone.now().isoformat()
        })
        
        self.save()
    
    def get_severity_color(self):
        """Get color for severity display"""
        severity_colors = {
            'LOW': '#4CAF50',      # Green
            'MEDIUM': '#FFC107',    # Amber
            'HIGH': '#FF9800',      # Orange
            'CRITICAL': '#F44336',  # Red
        }
        return severity_colors.get(self.severity, '#9E9E9E')

class ComplianceRecord(models.Model):
    """Compliance and regulatory records"""
    COMPLIANCE_TYPES = [
        ('KYC', 'Know Your Customer'),
        ('AML', 'Anti-Money Laundering'),
        ('GDPR', 'General Data Protection Regulation'),
        ('PCIDSS', 'PCI Data Security Standard'),
        ('SOX', 'Sarbanes-Oxley'),
        ('HIPAA', 'Health Insurance Portability'),
        ('FATCA', 'Foreign Account Tax Compliance'),
        ('LOCAL', 'Local Regulations'),
        ('INTERNAL', 'Internal Policies')
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('OVERDUE', 'Overdue'),
        ('FAILED', 'Failed'),
        ('EXEMPT', 'Exempt')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Compliance requirement
    compliance_type = models.CharField(max_length=20, choices=COMPLIANCE_TYPES, default='KYC')
    requirement = models.CharField(max_length=500)
    description = models.TextField(blank=True)
    
    # User/Entity
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='compliance_records')
    entity_type = models.CharField(max_length=50, default='USER')  # USER, SYSTEM, ORGANIZATION
    
    # Dates
    due_date = models.DateField()
    completed_date = models.DateField(null=True, blank=True)
    next_review_date = models.DateField(null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    verified = models.BooleanField(default=False)
    verification_date = models.DateField(null=True, blank=True)
    
    # Verification
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_compliance')
    verification_method = models.CharField(max_length=100, blank=True, null=True)
    verification_notes = models.TextField(blank=True, null=True)
    
    # Documents and evidence
    documents = models.JSONField(default=list, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    
    # Audit trail
    audit_trail = models.JSONField(default=list, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['due_date', 'compliance_type']
        indexes = [
            models.Index(fields=['user', 'compliance_type', 'status']),
            models.Index(fields=['due_date', 'status']),
        ]
    
    def __str__(self):
        entity = self.user.username if self.user else self.entity_type
        return f"{self.compliance_type} - {entity} - {self.status}"
    
    def is_overdue(self):
        """Check if compliance is overdue and update status."""
        overdue = self.status not in ['COMPLETED', 'EXEMPT'] and self.due_date < timezone.now().date()
        if overdue and self.status != 'OVERDUE':
            self.status = 'OVERDUE'
            self.save(update_fields=['status'])
        return overdue
    
    @property
    def days_until_due(self):
        """Days until due date (negative if overdue)"""
        from datetime import date
        return (self.due_date - date.today()).days
    
    def mark_completed(self, completed_date=None, verified_by=None, notes=''):
        """Mark compliance as completed"""
        self.status = 'COMPLETED'
        self.completed_date = completed_date or timezone.now().date()
        
        if verified_by:
            self.verified = True
            self.verified_by = verified_by
            self.verification_date = timezone.now().date()
            self.verification_notes = notes
        
        # Calculate next review date (typically 1 year for most compliance)
        from dateutil.relativedelta import relativedelta
        self.next_review_date = self.completed_date + relativedelta(years=1)
        
        # Add to audit trail
        self.audit_trail.append({
            'action': 'COMPLETED',
            'date': timezone.now().isoformat(),
            'by': str(verified_by) if verified_by else 'System',
            'notes': notes
        })
        
        self.save()
    
    def request_extension(self, new_due_date, reason=''):
        """Request extension for compliance"""
        self.due_date = new_due_date
        
        self.audit_trail.append({
            'action': 'EXTENSION_REQUESTED',
            'date': timezone.now().isoformat(),
            'old_due_date': self.due_date.isoformat(),
            'new_due_date': new_due_date.isoformat(),
            'reason': reason
        })
        
        self.save()

class AuditTrail(models.Model):
    """Detailed audit trail for specific entities"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Entity being tracked
    entity_type = models.CharField(max_length=100)
    entity_id = models.CharField(max_length=100)
    entity_name = models.CharField(max_length=200, blank=True, null=True)
    
    # Changes
    old_values = models.JSONField(default=dict, blank=True)
    new_values = models.JSONField(default=dict, blank=True)
    changed_fields = models.JSONField(default=list, blank=True)
    
    # Who changed it
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    changed_by_ip = models.GenericIPAddressField(null=True, blank=True)
    
    # Context
    change_reason = models.TextField(blank=True, null=True)
    change_source = models.CharField(max_length=50, blank=True, null=True)
    
    # Related audit log
    audit_log = models.ForeignKey(AuditLog, on_delete=models.CASCADE, null=True, blank=True, related_name='trail')
    
    changed_at = models.DateTimeField(auto_now_add=True)

    def __init__(self, *args, **kwargs):
        object_type = kwargs.pop('object_type', None)
        object_id = kwargs.pop('object_id', None)
        operation = kwargs.pop('operation', None)
        user = kwargs.pop('user', None)
        old_value = kwargs.pop('old_value', None)
        new_value = kwargs.pop('new_value', None)
        changes = kwargs.pop('changes', None)
        ip_address = kwargs.pop('ip_address', None)
        reason = kwargs.pop('reason', None)
        super().__init__(*args, **kwargs)
        if object_type is not None:
            self.entity_type = object_type
        if object_id is not None:
            self.entity_id = str(object_id)
        if operation is not None:
            self.change_source = operation
        if user is not None:
            self.changed_by = user
        if old_value is not None:
            self.old_values = old_value
        if new_value is not None:
            self.new_values = new_value
        if changes is not None:
            self.changed_fields = changes
        if ip_address is not None:
            self.changed_by_ip = ip_address
        if reason is not None:
            self.change_reason = reason

    @property
    def object_type(self):
        return self.entity_type

    @property
    def object_id(self):
        return self.entity_id

    @property
    def operation(self):
        return self.change_source

    @property
    def user(self):
        return self.changed_by

    @property
    def old_value(self):
        return self.old_values

    @property
    def new_value(self):
        return self.new_values

    @property
    def changes(self):
        return self.changed_fields
    
    class Meta:
        ordering = ['-changed_at']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id', 'changed_at']),
            models.Index(fields=['changed_by', 'changed_at']),
        ]
    
    def __str__(self):
        return f"{self.entity_type}:{self.entity_id} - Changed by {self.changed_by} at {self.changed_at}"
    
    @classmethod
    def track_changes(cls, entity_instance, old_data, new_data, changed_by=None, reason=''):
        """Track changes to an entity"""
        
        # Determine changed fields
        changed_fields = []
        for key, new_value in new_data.items():
            old_value = old_data.get(key)
            if old_value != new_value:
                changed_fields.append(key)
        
        if not changed_fields:
            return None
        
        # Create trail entry
        trail = cls.objects.create(
            entity_type=entity_instance.__class__.__name__,
            entity_id=str(entity_instance.pk),
            entity_name=str(entity_instance),
            old_values=old_data,
            new_values=new_data,
            changed_fields=changed_fields,
            changed_by=changed_by,
            change_reason=reason,
            change_source='SYSTEM'
        )
        
        return trail

class SystemControl(models.Model):
    """System-wide controls and configuration"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Feature toggles
    autopilot_enabled = models.BooleanField(default=True)
    ai_enabled = models.BooleanField(default=True)
    payment_processing_enabled = models.BooleanField(default=True)
    new_registrations_enabled = models.BooleanField(default=True)
    
    # Security settings
    max_login_attempts = models.PositiveIntegerField(default=5)
    session_timeout_minutes = models.PositiveIntegerField(default=30)
    password_min_length = models.PositiveIntegerField(default=8)
    two_factor_required = models.BooleanField(default=False)
    
    # Limits
    max_daily_transactions = models.PositiveIntegerField(default=50)
    max_transaction_amount = models.DecimalField(max_digits=12, decimal_places=2, default=100000.00)
    max_monthly_spending = models.DecimalField(max_digits=12, decimal_places=2, default=500000.00)
    
    # Compliance
    kyc_required = models.BooleanField(default=True)
    aml_enabled = models.BooleanField(default=True)
    data_retention_days = models.PositiveIntegerField(default=365)
    
    # Maintenance
    maintenance_mode = models.BooleanField(default=False)
    maintenance_message = models.TextField(blank=True, null=True)
    maintenance_start = models.DateTimeField(null=True, blank=True)
    maintenance_end = models.DateTimeField(null=True, blank=True)
    
    # Emergency
    emergency_mode = models.BooleanField(default=False)
    emergency_message = models.TextField(blank=True, null=True)
    
    # System info
    current_version = models.CharField(max_length=20, default='1.0.0')
    last_updated = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        verbose_name = 'System Control'
        verbose_name_plural = 'System Controls'
    
    def __str__(self):
        status = "Operational"
        if self.maintenance_mode:
            status = "Maintenance"
        if self.emergency_mode:
            status = "Emergency"
        return f"System Control - {status} - v{self.current_version}"
    
    def save(self, *args, **kwargs):
        """Ensure only one system control exists"""
        if not self.pk and SystemControl.objects.exists():
            # Update the existing instance instead of creating new one
            existing = SystemControl.objects.first()
            existing.autopilot_enabled = self.autopilot_enabled
            existing.ai_enabled = self.ai_enabled
            existing.payment_processing_enabled = self.payment_processing_enabled
            existing.new_registrations_enabled = self.new_registrations_enabled
            existing.max_login_attempts = self.max_login_attempts
            existing.session_timeout_minutes = self.session_timeout_minutes
            existing.password_min_length = self.password_min_length
            existing.two_factor_required = self.two_factor_required
            existing.max_daily_transactions = self.max_daily_transactions
            existing.max_transaction_amount = self.max_transaction_amount
            existing.max_monthly_spending = self.max_monthly_spending
            existing.kyc_required = self.kyc_required
            existing.aml_enabled = self.aml_enabled
            existing.data_retention_days = self.data_retention_days
            existing.maintenance_mode = self.maintenance_mode
            existing.maintenance_message = self.maintenance_message
            existing.maintenance_start = self.maintenance_start
            existing.maintenance_end = self.maintenance_end
            existing.emergency_mode = self.emergency_mode
            existing.emergency_message = self.emergency_message
            existing.current_version = self.current_version
            existing.metadata = self.metadata
            existing.save()
            return existing
        return super().save(*args, **kwargs)
    
    @classmethod
    def get_controls(cls):
        """Get system controls (singleton pattern)"""
        controls, created = cls.objects.get_or_create(id=1)
        return controls

class UserRiskFlag(models.Model):
    """Risk flags for users based on behavior"""
    RISK_TYPES = [
        ('FRAUD', 'Fraud Risk'),
        ('MONEY_LAUNDERING', 'Money Laundering Risk'),
        ('CREDIT', 'Credit Risk'),
        ('OPERATIONAL', 'Operational Risk'),
        ('COMPLIANCE', 'Compliance Risk'),
        ('BEHAVIORAL', 'Behavioral Risk'),
        ('SECURITY', 'Security Risk'),
        ('REPUTATIONAL', 'Reputational Risk')
    ]
    
    RISK_STATUS = [
        ('ACTIVE', 'Active'),
        ('INVESTIGATING', 'Under Investigation'),
        ('RESOLVED', 'Resolved'),
        ('FALSE_POSITIVE', 'False Positive'),
        ('ESCALATED', 'Escalated')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # User
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='risk_flags')
    
    # Risk details
    risk_type = models.CharField(max_length=20, choices=RISK_TYPES, default='BEHAVIORAL')
    description = models.TextField()
    risk_score = models.IntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    
    # Evidence
    evidence = models.JSONField(default=list, blank=True)
    related_transactions = models.ManyToManyField('payments_core.PaymentTransaction', blank=True)
    related_alerts = models.ManyToManyField(SecurityAlert, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=RISK_STATUS, default='ACTIVE')
    is_active = models.BooleanField(default=True)
    requires_review = models.BooleanField(default=True)
    
    # Investigation
    flagged_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='flagged_risks')
    investigated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='investigated_risks')
    investigation_notes = models.TextField(blank=True, null=True)
    
    # Dates
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-risk_score', '-created_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.risk_type} - Score: {self.risk_score}"
    
    @property
    def risk_level(self):
        """Get risk level based on score"""
        if self.risk_score >= 80:
            return 'CRITICAL'
        elif self.risk_score >= 60:
            return 'HIGH'
        elif self.risk_score >= 40:
            return 'MEDIUM'
        elif self.risk_score >= 20:
            return 'LOW'
        else:
            return 'MINIMAL'
    
    def add_evidence(self, evidence_type, evidence_data, description=''):
        """Add evidence to risk flag"""
        self.evidence.append({
            'type': evidence_type,
            'data': evidence_data,
            'description': description,
            'added_at': timezone.now().isoformat()
        })
        
        self.save()
    
    def update_risk_score(self, new_score, reason=''):
        """Update risk score"""
        old_score = self.risk_score
        self.risk_score = new_score
        
        self.metadata.setdefault('score_history', []).append({
            'old_score': old_score,
            'new_score': new_score,
            'reason': reason,
            'changed_at': timezone.now().isoformat()
        })
        
        self.save()
    
    def mark_resolved(self, resolved_by, notes=''):
        """Mark risk flag as resolved"""
        self.status = 'RESOLVED'
        self.is_active = False
        self.requires_review = False
        self.resolved_at = timezone.now()
        self.investigated_by = resolved_by
        self.investigation_notes = notes
        self.save()
    
    def escalate(self, escalation_reason=''):
        """Escalate risk flag"""
        self.status = 'ESCALATED'
        self.requires_review = True
        
        self.metadata['escalation'] = {
            'reason': escalation_reason,
            'escalated_at': timezone.now().isoformat()
        }
        
        self.save()
