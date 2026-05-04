# notifications/forms.py
from django import forms
from .models import Notification, NotificationPreference
from django.contrib.auth import get_user_model

User = get_user_model()

class NotificationPreferenceForm(forms.ModelForm):
    """Notification preference form"""
    class Meta:
        model = NotificationPreference
        fields = [
            'email_notifications', 'sms_notifications', 'push_notifications', 
            'in_app_notifications', 'payment_notifications', 'transaction_notifications',
            'budget_notifications', 'savings_notifications', 'investment_notifications',
            'debt_notifications', 'income_notifications', 'bill_notifications',
            'reminder_notifications', 'alert_notifications', 'insight_notifications',
            'security_notifications', 'system_notifications', 'promotional_notifications',
            'quiet_hours_start', 'quiet_hours_end', 'daily_digest', 'weekly_summary',
            'monthly_report', 'immediate_alerts', 'batch_notifications', 
            'batch_frequency', 'notification_language', 'preferred_format'
        ]
        widgets = {
            'email_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'sms_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'push_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'in_app_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'payment_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'transaction_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'budget_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'savings_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'investment_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'debt_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'income_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'bill_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'reminder_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'alert_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'insight_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'security_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'system_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'promotional_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'quiet_hours_start': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'quiet_hours_end': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'daily_digest': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'weekly_summary': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'monthly_report': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'immediate_alerts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'batch_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'batch_frequency': forms.Select(attrs={'class': 'form-control'}),
            'notification_language': forms.Select(attrs={'class': 'form-control'}),
            'preferred_format': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        quiet_hours_start = cleaned_data.get('quiet_hours_start')
        quiet_hours_end = cleaned_data.get('quiet_hours_end')
        
        if quiet_hours_start and quiet_hours_end:
            if quiet_hours_start == quiet_hours_end:
                raise forms.ValidationError({
                    'quiet_hours_end': "Quiet hours start and end times cannot be the same"
                })
        
        return cleaned_data

class NotificationFilterForm(forms.Form):
    """Notification filter form"""
    CATEGORIES = [
        ('', 'All Categories'),
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
        ('UPDATE', 'Update'),
    ]
    
    SEVERITIES = [
        ('', 'All Severities'),
        ('INFO', 'Information'),
        ('SUCCESS', 'Success'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]
    
    STATUS_CHOICES = [
        ('', 'All Status'),
        ('read', 'Read'),
        ('unread', 'Unread'),
        ('action_required', 'Action Required'),
        ('action_completed', 'Action Completed'),
    ]
    
    category = forms.ChoiceField(
        choices=CATEGORIES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    severity = forms.ChoiceField(
        choices=SEVERITIES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
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
            'placeholder': 'Search notifications...'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to and date_to < date_from:
            raise forms.ValidationError({
                'date_to': "End date cannot be before start date"
            })
        
        return cleaned_data

class BulkActionForm(forms.Form):
    """Bulk notification action form"""
    ACTIONS = [
        ('mark_read', 'Mark as Read'),
        ('mark_unread', 'Mark as Unread'),
        ('delete', 'Delete'),
        ('archive', 'Archive'),
    ]
    
    action = forms.ChoiceField(
        choices=ACTIONS,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    notification_ids = forms.CharField(
        widget=forms.HiddenInput()
    )
    
    def clean_notification_ids(self):
        ids_str = self.cleaned_data.get('notification_ids')
        try:
            ids = [int(id_str) for id_str in ids_str.split(',') if id_str.strip()]
            return ids
        except ValueError:
            raise forms.ValidationError("Invalid notification IDs")

class SendNotificationForm(forms.Form):
    """Admin notification sending form"""
    RECIPIENT_TYPES = [
        ('SINGLE', 'Single User'),
        ('GROUP', 'User Group'),
        ('ALL', 'All Users'),
        ('ROLE', 'By Role'),
    ]
    
    USER_ROLES = [
        ('REGULAR', 'Regular Users'),
        ('PREMIUM', 'Premium Users'),
        ('INACTIVE', 'Inactive Users'),
        ('NEW', 'New Users (< 30 days)'),
    ]
    
    CATEGORIES = [
        ('SYSTEM', 'System'),
        ('UPDATE', 'Update'),
        ('PROMOTIONAL', 'Promotional'),
        ('SECURITY', 'Security'),
        ('ALERT', 'Alert'),
    ]
    
    SEVERITIES = [
        ('INFO', 'Information'),
        ('SUCCESS', 'Success'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('CRITICAL', 'Critical'),
    ]
    
    recipient_type = forms.ChoiceField(
        choices=RECIPIENT_TYPES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    user_role = forms.ChoiceField(
        choices=USER_ROLES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Notification title'
        })
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Notification message'
        })
    )
    category = forms.ChoiceField(
        choices=CATEGORIES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    severity = forms.ChoiceField(
        choices=SEVERITIES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    action_required = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Requires action'
    )
    action_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'Action URL (optional)'
        })
    )
    delivery_methods = forms.MultipleChoiceField(
        choices=[
            ('EMAIL', 'Email'),
            ('SMS', 'SMS'),
            ('PUSH', 'Push Notification'),
            ('IN_APP', 'In-App'),
        ],
        initial=['IN_APP', 'EMAIL'],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label='Delivery Methods'
    )
    schedule_send = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Schedule for later'
    )
    scheduled_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        recipient_type = cleaned_data.get('recipient_type')
        user = cleaned_data.get('user')
        user_role = cleaned_data.get('user_role')
        
        if recipient_type == 'SINGLE' and not user:
            raise forms.ValidationError({
                'user': "User is required for single recipient"
            })
        
        if recipient_type == 'ROLE' and not user_role:
            raise forms.ValidationError({
                'user_role': "User role is required for role-based recipients"
            })
        
        schedule_send = cleaned_data.get('schedule_send')
        scheduled_time = cleaned_data.get('scheduled_time')
        
        if schedule_send and not scheduled_time:
            raise forms.ValidationError({
                'scheduled_time': "Scheduled time is required when scheduling for later"
            })
        
        return cleaned_data

class NotificationTemplateForm(forms.Form):
    """Notification template form"""
    TEMPLATE_TYPES = [
        ('WELCOME', 'Welcome Notification'),
        ('PAYMENT_SUCCESS', 'Payment Success'),
        ('PAYMENT_FAILED', 'Payment Failed'),
        ('BILL_REMINDER', 'Bill Reminder'),
        ('BUDGET_ALERT', 'Budget Alert'),
        ('SAVINGS_GOAL', 'Savings Goal Update'),
        ('SECURITY_ALERT', 'Security Alert'),
        ('WEEKLY_SUMMARY', 'Weekly Summary'),
        ('MONTHLY_REPORT', 'Monthly Report'),
        ('SYSTEM_UPDATE', 'System Update'),
    ]
    
    template_name = forms.ChoiceField(
        choices=TEMPLATE_TYPES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    subject = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email subject / Notification title'
        })
    )
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 6,
            'placeholder': 'Message body (use {{variable}} for placeholders)'
        })
    )
    variables = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Available variables (one per line)'
        })
    )
    is_active = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Active'
    )
    
    def clean_variables(self):
        variables_str = self.cleaned_data.get('variables')
        if variables_str:
            variables = [v.strip() for v in variables_str.split('\n') if v.strip()]
            return variables
        return []

class QuietHoursForm(forms.Form):
    """Quiet hours settings form"""
    enable_quiet_hours = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Enable quiet hours'
    )
    quiet_hours_start = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={
            'class': 'form-control',
            'type': 'time'
        }),
        label='Start time'
    )
    quiet_hours_end = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={
            'class': 'form-control',
            'type': 'time'
        }),
        label='End time'
    )
    override_critical = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Allow critical notifications during quiet hours'
    )
    days_of_week = forms.MultipleChoiceField(
        choices=[
            ('MON', 'Monday'),
            ('TUE', 'Tuesday'),
            ('WED', 'Wednesday'),
            ('THU', 'Thursday'),
            ('FRI', 'Friday'),
            ('SAT', 'Saturday'),
            ('SUN', 'Sunday'),
        ],
        initial=['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        label='Days of week'
    )
    
    def clean(self):
        cleaned_data = super().clean()
        enable_quiet_hours = cleaned_data.get('enable_quiet_hours')
        quiet_hours_start = cleaned_data.get('quiet_hours_start')
        quiet_hours_end = cleaned_data.get('quiet_hours_end')
        
        if enable_quiet_hours:
            if not quiet_hours_start or not quiet_hours_end:
                raise forms.ValidationError({
                    'quiet_hours_start': "Start and end times are required when quiet hours are enabled"
                })
            
            if quiet_hours_start == quiet_hours_end:
                raise forms.ValidationError({
                    'quiet_hours_end': "Start and end times cannot be the same"
                })
        
        return cleaned_data