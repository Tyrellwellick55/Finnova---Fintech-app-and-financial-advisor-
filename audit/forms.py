# audit/forms.py
from django import forms
from .models import (
    AuditLog, SecurityAlert, ComplianceRecord, 
    UserRiskFlag, SystemControl
)
from django.contrib.auth import get_user_model

User = get_user_model()

class AuditLogFilterForm(forms.Form):
    """Audit log filter form"""
    SOURCE_CHOICES = [
        ('', 'All Sources'),
        ('SYSTEM', 'System'),
        ('USER', 'User Action'),
        ('API', 'API Call'),
        ('PAYMENT', 'Payment System'),
        ('FINANCE', 'Finance Module'),
        ('AUTOPILOT', 'Autopilot'),
        ('AI', 'AI System'),
        ('SECURITY', 'Security System'),
        ('ADMIN', 'Administrator'),
    ]
    
    ACTION_CHOICES = [
        ('', 'All Actions'),
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
        ('SYSTEM', 'System Event'),
    ]
    
    SEVERITY_CHOICES = [
        ('', 'All Severities'),
        ('INFO', 'Information'),
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    ]
    
    source = forms.ChoiceField(
        choices=SOURCE_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    severity = forms.ChoiceField(
        choices=SEVERITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    actor = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    target = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search in description...'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit actor/target choices to recent users
        recent_users = User.objects.order_by('-date_joined')[:100]
        self.fields['actor'].queryset = recent_users
        self.fields['target'].queryset = recent_users
    
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to and date_to < date_from:
            raise forms.ValidationError({
                'date_to': "End date cannot be before start date"
            })
        
        return cleaned_data

class SecurityAlertFilterForm(forms.Form):
    """Security alert filter form"""
    ALERT_TYPES = [
        ('', 'All Types'),
        ('LOGIN', 'Login Alert'),
        ('FRAUD', 'Fraud Detection'),
        ('SUSPICIOUS', 'Suspicious Activity'),
        ('UNAUTHORIZED', 'Unauthorized Access'),
        ('DATA_BREACH', 'Data Breach'),
        ('MALWARE', 'Malware Detection'),
        ('PHISHING', 'Phishing Attempt'),
        ('BRUTE_FORCE', 'Brute Force Attack'),
        ('UNUSUAL', 'Unusual Behavior'),
        ('COMPLIANCE', 'Compliance Violation'),
    ]
    
    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('OPEN', 'Open'),
        ('INVESTIGATING', 'Investigating'),
        ('RESOLVED', 'Resolved'),
        ('FALSE_POSITIVE', 'False Positive'),
        ('ESCALATED', 'Escalated'),
    ]
    
    SEVERITY_CHOICES = [
        ('', 'All Severities'),
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    ]
    
    alert_type = forms.ChoiceField(
        choices=ALERT_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    severity = forms.ChoiceField(
        choices=SEVERITY_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search alerts...'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit user choices to recent users with alerts
        from .models import SecurityAlert
        users_with_alerts = User.objects.filter(
            security_alerts__isnull=False
        ).distinct()[:50]
        self.fields['user'].queryset = users_with_alerts

class ComplianceRecordForm(forms.ModelForm):
    """Compliance record form"""
    class Meta:
        model = ComplianceRecord
        fields = [
            'compliance_type', 'requirement', 'description',
            'due_date', 'user', 'entity_type'
        ]
        widgets = {
            'compliance_type': forms.Select(attrs={'class': 'form-control'}),
            'requirement': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Compliance requirement'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Detailed description'
            }),
            'due_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'user': forms.Select(attrs={'class': 'form-control'}),
            'entity_type': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit user choices to active users
        self.fields['user'].queryset = User.objects.filter(is_active=True)
        from datetime import date, timedelta
        # Set default due date to 30 days from now
        self.fields['due_date'].initial = date.today() + timedelta(days=30)

class ComplianceFilterForm(forms.Form):
    """Compliance filter form"""
    COMPLIANCE_TYPES = [
        ('', 'All Types'),
        ('KYC', 'Know Your Customer'),
        ('AML', 'Anti-Money Laundering'),
        ('GDPR', 'General Data Protection Regulation'),
        ('PCIDSS', 'PCI Data Security Standard'),
        ('SOX', 'Sarbanes-Oxley'),
        ('HIPAA', 'Health Insurance Portability'),
        ('FATCA', 'Foreign Account Tax Compliance'),
        ('LOCAL', 'Local Regulations'),
        ('INTERNAL', 'Internal Policies'),
    ]
    
    STATUS_CHOICES = [
        ('', 'All Statuses'),
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('COMPLETED', 'Completed'),
        ('OVERDUE', 'Overdue'),
        ('FAILED', 'Failed'),
        ('EXEMPT', 'Exempt'),
    ]
    
    compliance_type = forms.ChoiceField(
        choices=COMPLIANCE_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    due_date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    due_date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    verified_only = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Show only verified'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit user choices to active users
        self.fields['user'].queryset = User.objects.filter(is_active=True)
    
    def clean(self):
        cleaned_data = super().clean()
        due_date_from = cleaned_data.get('due_date_from')
        due_date_to = cleaned_data.get('due_date_to')
        
        if due_date_from and due_date_to and due_date_to < due_date_from:
            raise forms.ValidationError({
                'due_date_to': "End date cannot be before start date"
            })
        
        return cleaned_data

class UserRiskFlagForm(forms.ModelForm):
    """User risk flag form"""
    class Meta:
        model = UserRiskFlag
        fields = [
            'user', 'risk_type', 'description', 'risk_score',
            'requires_review', 'investigation_notes'
        ]
        widgets = {
            'user': forms.Select(attrs={'class': 'form-control'}),
            'risk_type': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Risk description'
            }),
            'risk_score': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0',
                'max': '100'
            }),
            'requires_review': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'investigation_notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Investigation notes'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit user choices to active users
        self.fields['user'].queryset = User.objects.filter(is_active=True)
        # Set default risk score
        self.fields['risk_score'].initial = 50

class RiskFlagFilterForm(forms.Form):
    """Risk flag filter form"""
    RISK_TYPES = [
        ('', 'All Types'),
        ('FRAUD', 'Fraud Risk'),
        ('MONEY_LAUNDERING', 'Money Laundering Risk'),
        ('CREDIT', 'Credit Risk'),
        ('OPERATIONAL', 'Operational Risk'),
        ('COMPLIANCE', 'Compliance Risk'),
        ('BEHAVIORAL', 'Behavioral Risk'),
        ('SECURITY', 'Security Risk'),
        ('REPUTATIONAL', 'Reputational Risk'),
    ]
    
    RISK_STATUS = [
        ('', 'All Statuses'),
        ('ACTIVE', 'Active'),
        ('INVESTIGATING', 'Under Investigation'),
        ('RESOLVED', 'Resolved'),
        ('FALSE_POSITIVE', 'False Positive'),
        ('ESCALATED', 'Escalated'),
    ]
    
    risk_type = forms.ChoiceField(
        choices=RISK_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=RISK_STATUS,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    min_risk_score = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=100,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min score'
        })
    )
    max_risk_score = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=100,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Max score'
        })
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Limit user choices to users with risk flags
        from .models import UserRiskFlag
        users_with_risks = User.objects.filter(
            risk_flags__isnull=False
        ).distinct()[:50]
        self.fields['user'].queryset = users_with_risks
    
    def clean(self):
        cleaned_data = super().clean()
        min_score = cleaned_data.get('min_risk_score')
        max_score = cleaned_data.get('max_risk_score')
        
        if min_score and max_score and max_score < min_score:
            raise forms.ValidationError({
                'max_risk_score': "Maximum score cannot be less than minimum score"
            })
        
        return cleaned_data

class SystemControlForm(forms.ModelForm):
    """System control settings form"""
    class Meta:
        model = SystemControl
        fields = [
            'autopilot_enabled', 'ai_enabled', 'payment_processing_enabled',
            'new_registrations_enabled', 'max_login_attempts', 'session_timeout_minutes',
            'password_min_length', 'two_factor_required', 'max_daily_transactions',
            'max_transaction_amount', 'max_monthly_spending', 'kyc_required',
            'aml_enabled', 'data_retention_days', 'maintenance_mode',
            'maintenance_message', 'maintenance_start', 'maintenance_end',
            'emergency_mode', 'emergency_message', 'current_version'
        ]
        widgets = {
            'autopilot_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'ai_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'payment_processing_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'new_registrations_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'max_login_attempts': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '20'
            }),
            'session_timeout_minutes': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '1440'  # 24 hours
            }),
            'password_min_length': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '6',
                'max': '32'
            }),
            'two_factor_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'max_daily_transactions': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '1000'
            }),
            'max_transaction_amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '100',
                'step': '0.01'
            }),
            'max_monthly_spending': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1000',
                'step': '0.01'
            }),
            'kyc_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'aml_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'data_retention_days': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '30',
                'max': '3650'  # 10 years
            }),
            'maintenance_mode': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'maintenance_message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Maintenance message for users'
            }),
            'maintenance_start': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'maintenance_end': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local'
            }),
            'emergency_mode': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'emergency_message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Emergency message for users'
            }),
            'current_version': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 1.0.0'
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        maintenance_mode = cleaned_data.get('maintenance_mode')
        maintenance_start = cleaned_data.get('maintenance_start')
        maintenance_end = cleaned_data.get('maintenance_end')
        
        if maintenance_mode:
            if not maintenance_start or not maintenance_end:
                raise forms.ValidationError({
                    'maintenance_start': "Maintenance start and end times are required when maintenance mode is enabled"
                })
            
            if maintenance_end <= maintenance_start:
                raise forms.ValidationError({
                    'maintenance_end': "Maintenance end time must be after start time"
                })
        
        emergency_mode = cleaned_data.get('emergency_mode')
        emergency_message = cleaned_data.get('emergency_message')
        
        if emergency_mode and not emergency_message:
            raise forms.ValidationError({
                'emergency_message': "Emergency message is required when emergency mode is enabled"
            })
        
        return cleaned_data

class AlertResolutionForm(forms.Form):
    """Security alert resolution form"""
    RESOLUTION_TYPES = [
        ('RESOLVED', 'Resolved'),
        ('FALSE_POSITIVE', 'False Positive'),
        ('ESCALATED', 'Escalated to Security Team'),
        ('USER_ERROR', 'User Error'),
        ('SYSTEM_ERROR', 'System Error'),
        ('OTHER', 'Other'),
    ]
    
    resolution_type = forms.ChoiceField(
        choices=RESOLUTION_TYPES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    resolution_notes = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Detailed resolution notes...'
        })
    )
    add_to_knowledge_base = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Add to knowledge base for future reference'
    )
    prevent_recurrence = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Take measures to prevent recurrence'
    )

class ComplianceVerificationForm(forms.Form):
    """Compliance verification form"""
    verification_method = forms.ChoiceField(
        choices=[
            ('DOCUMENT_REVIEW', 'Document Review'),
            ('USER_INTERVIEW', 'User Interview'),
            ('SYSTEM_CHECK', 'System Check'),
            ('THIRD_PARTY_VERIFICATION', 'Third Party Verification'),
            ('AUDIT', 'Audit'),
            ('OTHER', 'Other'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    verification_notes = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Verification details...'
        })
    )
    documents_uploaded = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Supporting documents uploaded'
    )
    next_review_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    
    def clean_next_review_date(self):
        next_review_date = self.cleaned_data.get('next_review_date')
        if next_review_date:
            from datetime import date
            if next_review_date <= date.today():
                raise forms.ValidationError("Next review date must be in the future")
        return next_review_date

class ExportAuditLogForm(forms.Form):
    """Audit log export form"""
    FORMAT_CHOICES = [
        ('CSV', 'CSV'),
        ('JSON', 'JSON'),
        ('PDF', 'PDF'),
        ('EXCEL', 'Excel'),
    ]
    
    format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_from = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    date_to = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    include_sensitive = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Include sensitive data'
    )
    password_protect = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Password protect export'
    )
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Export password'
        })
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from datetime import date, timedelta
        # Set default dates (last 30 days)
        self.fields['date_from'].initial = date.today() - timedelta(days=30)
        self.fields['date_to'].initial = date.today()
    
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_to < date_from:
            raise forms.ValidationError({
                'date_to': "End date cannot be before start date"
            })
        
        if (date_to - date_from).days > 365:
            raise forms.ValidationError({
                'date_to': "Export period cannot exceed 1 year"
            })
        
        password_protect = cleaned_data.get('password_protect')
        password = cleaned_data.get('password')
        
        if password_protect and not password:
            raise forms.ValidationError({
                'password': "Password is required when password protection is enabled"
            })
        
        return cleaned_data