# analytics_ai/forms.py
from django import forms
from .models import (
    FinancialInsight, PredictiveAlert, SmartRule, 
    AISession, AIFinancialGoal
)
import json

class InsightFilterForm(forms.Form):
    """Filter insights form"""
    INSIGHT_TYPES = [
        ('', 'All Types'),
        ('SPENDING', 'Spending Insight'),
        ('SAVINGS', 'Savings Insight'),
        ('INVESTMENT', 'Investment Insight'),
        ('DEBT', 'Debt Insight'),
        ('INCOME', 'Income Insight'),
        ('BUDGET', 'Budget Insight'),
        ('TREND', 'Trend Analysis'),
        ('ANOMALY', 'Anomaly Detection'),
        ('OPPORTUNITY', 'Opportunity'),
        ('RISK', 'Risk Alert'),
    ]
    
    SEVERITY_CHOICES = [
        ('', 'All Severities'),
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('CRITICAL', 'Critical'),
    ]
    
    insight_type = forms.ChoiceField(
        choices=INSIGHT_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    severity = forms.ChoiceField(
        choices=SEVERITY_CHOICES,
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
    action_required = forms.ChoiceField(
        choices=[
            ('', 'All'),
            ('yes', 'Action Required'),
            ('no', 'No Action Required'),
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search insights...'
        })
    )

class AIReportRequestForm(forms.Form):
    """AI report generation form"""
    REPORT_TYPES = [
        ('COMPREHENSIVE', 'Comprehensive Financial Report'),
        ('SPENDING_ANALYSIS', 'Spending Analysis'),
        ('SAVINGS_OPTIMIZATION', 'Savings Optimization'),
        ('INVESTMENT_REVIEW', 'Investment Portfolio Review'),
        ('DEBT_MANAGEMENT', 'Debt Management Plan'),
        ('RETIREMENT_PLANNING', 'Retirement Planning'),
        ('TAX_OPTIMIZATION', 'Tax Optimization'),
        ('CASHFLOW_FORECAST', 'Cash Flow Forecast'),
    ]
    
    TIMEFRAME_CHOICES = [
        ('MONTHLY', 'Monthly Analysis'),
        ('QUARTERLY', 'Quarterly Analysis'),
        ('YEARLY', 'Yearly Analysis'),
        ('CUSTOM', 'Custom Date Range'),
    ]
    
    report_type = forms.ChoiceField(
        choices=REPORT_TYPES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    timeframe = forms.ChoiceField(
        choices=TIMEFRAME_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    include_comparisons = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Include peer comparisons'
    )
    include_predictions = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Include future predictions'
    )
    detailed_analysis = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Detailed analysis (may take longer)'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from datetime import date, timedelta
        # Set default dates (last 30 days)
        self.fields['start_date'].initial = date.today() - timedelta(days=30)
        self.fields['end_date'].initial = date.today()
    
    def clean(self):
        cleaned_data = super().clean()
        timeframe = cleaned_data.get('timeframe')
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if timeframe == 'CUSTOM':
            if not start_date or not end_date:
                raise forms.ValidationError({
                    'start_date': "Start date and end date are required for custom timeframe"
                })
            
            if end_date < start_date:
                raise forms.ValidationError({
                    'end_date': "End date cannot be before start date"
                })
            
            if (end_date - start_date).days > 365:
                raise forms.ValidationError({
                    'end_date': "Custom timeframe cannot exceed 1 year"
                })
        
        return cleaned_data

class ChatbotForm(forms.Form):
    """AI chatbot form"""
    message = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Ask me anything about your finances...',
            'style': 'resize: none;'
        })
    )
    context = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    
    def clean_message(self):
        message = self.cleaned_data.get('message')
        if not message or len(message.strip()) == 0:
            raise forms.ValidationError("Please enter a message")
        if len(message) > 1000:
            raise forms.ValidationError("Message is too long (max 1000 characters)")
        return message.strip()

class SmartRuleForm(forms.ModelForm):
    """Smart rule creation form"""
    class Meta:
        model = SmartRule
        fields = [
            'name', 'condition_type', 'condition_value',
            'action_type', 'action_value', 'priority', 'is_active'
        ]
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Rule name'
            }),
            'condition_type': forms.Select(attrs={'class': 'form-control'}),
            'action_type': forms.Select(attrs={'class': 'form-control'}),
            'priority': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '10'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add custom JSON fields for condition and action values
        self.fields['condition_value_json'] = forms.CharField(
            required=False,
            widget=forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter JSON for condition value'
            })
        )
        self.fields['action_value_json'] = forms.CharField(
            required=False,
            widget=forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Enter JSON for action value'
            })
        )
        
        # Populate JSON fields from existing data
        if self.instance and self.instance.pk:
            if self.instance.condition_value:
                self.fields['condition_value_json'].initial = json.dumps(
                    self.instance.condition_value, indent=2
                )
            if self.instance.action_value:
                self.fields['action_value_json'].initial = json.dumps(
                    self.instance.action_value, indent=2
                )
    
    def clean_condition_value_json(self):
        json_str = self.cleaned_data.get('condition_value_json')
        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                raise forms.ValidationError(f"Invalid JSON: {str(e)}")
        return {}
    
    def clean_action_value_json(self):
        json_str = self.cleaned_data.get('action_value_json')
        if json_str:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                raise forms.ValidationError(f"Invalid JSON: {str(e)}")
        return {}
    
    def save(self, commit=True):
        instance = super().save(commit=False)
        
        # Set condition and action values from JSON
        condition_json = self.cleaned_data.get('condition_value_json')
        action_json = self.cleaned_data.get('action_value_json')
        
        if condition_json is not None:
            instance.condition_value = condition_json
        if action_json is not None:
            instance.action_value = action_json
        
        if commit:
            instance.save()
        
        return instance

class PredictiveAlertSettingsForm(forms.Form):
    """Predictive alert settings form"""
    # Cash flow alerts
    cashflow_crisis_days = forms.IntegerField(
        initial=7,
        min_value=1,
        max_value=30,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Days to predict cash flow crisis',
        help_text='How many days in advance to predict cash flow issues'
    )
    enable_cashflow_alerts = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Enable cash flow alerts'
    )
    
    # Spending alerts
    unusual_spending_threshold = forms.IntegerField(
        initial=150,
        min_value=100,
        max_value=500,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Unusual spending threshold (%)',
        help_text='Percentage above average to consider spending unusual'
    )
    enable_spending_alerts = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Enable unusual spending alerts'
    )
    
    # Savings alerts
    savings_rate_warning = forms.IntegerField(
        initial=10,
        min_value=0,
        max_value=50,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Minimum savings rate warning (%)',
        help_text='Warn if savings rate falls below this percentage'
    )
    enable_savings_alerts = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Enable savings alerts'
    )
    
    # Debt alerts
    debt_to_income_warning = forms.IntegerField(
        initial=40,
        min_value=0,
        max_value=100,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Debt-to-income warning threshold (%)',
        help_text='Warn if debt-to-income ratio exceeds this percentage'
    )
    enable_debt_alerts = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Enable debt alerts'
    )
    
    # Investment alerts
    market_drop_threshold = forms.IntegerField(
        initial=10,
        min_value=1,
        max_value=50,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Market drop alert threshold (%)',
        help_text='Alert if investments drop by this percentage'
    )
    enable_investment_alerts = forms.BooleanField(
        initial=True,
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Enable investment alerts'
    )
    
    # Confidence thresholds
    high_confidence_threshold = forms.IntegerField(
        initial=80,
        min_value=50,
        max_value=100,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='High confidence threshold (%)',
        help_text='Minimum confidence to trigger high priority alerts'
    )
    medium_confidence_threshold = forms.IntegerField(
        initial=60,
        min_value=30,
        max_value=90,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Medium confidence threshold (%)',
        help_text='Minimum confidence to trigger medium priority alerts'
    )

class AIGoalForm(forms.ModelForm):
    """AI financial goal form"""
    class Meta:
        model = AIFinancialGoal
        fields = [
            'goal_type', 'name', 'description', 'target_value',
            'target_date', 'complexity'
        ]
        widgets = {
            'goal_type': forms.Select(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Goal name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe your goal...'
            }),
            'target_value': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '0.01',
                'step': '0.01'
            }),
            'target_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'complexity': forms.Select(attrs={'class': 'form-control'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from datetime import date, timedelta
        # Set default target date to 1 year from now
        self.fields['target_date'].initial = date.today() + timedelta(days=365)
    
    def clean_target_date(self):
        target_date = self.cleaned_data.get('target_date')
        if target_date and target_date <= date.today():
            raise forms.ValidationError("Target date must be in the future")
        return target_date

class FinancialHealthAssessmentForm(forms.Form):
    """Financial health assessment form"""
    # Income questions
    income_stability = forms.ChoiceField(
        choices=[
            ('STABLE', 'Stable (Regular salary/business income)'),
            ('MODERATE', 'Moderately stable (Mostly regular with some variability)'),
            ('VOLATILE', 'Volatile (Irregular or seasonal income)'),
            ('UNCERTAIN', 'Uncertain (No regular income source)'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='How stable is your income?'
    )
    
    income_growth = forms.ChoiceField(
        choices=[
            ('GROWING', 'Growing (Consistently increasing)'),
            ('STABLE', 'Stable (Remains about the same)'),
            ('DECLINING', 'Declining (Decreasing over time)'),
            ('VARIABLE', 'Variable (Goes up and down)'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='How is your income trending?'
    )
    
    # Expense questions
    expense_control = forms.ChoiceField(
        choices=[
            ('FULL', 'Full control (Track and stick to budget)'),
            ('MOST', 'Most control (Usually stick to budget)'),
            ('SOME', 'Some control (Sometimes overspend)'),
            ('LITTLE', 'Little control (Frequently overspend)'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='How much control do you have over your expenses?'
    )
    
    emergency_fund = forms.ChoiceField(
        choices=[
            ('6_MONTHS', '6+ months of expenses'),
            ('3_6_MONTHS', '3-6 months of expenses'),
            ('1_3_MONTHS', '1-3 months of expenses'),
            ('LESS_1_MONTH', 'Less than 1 month of expenses'),
            ('NONE', 'No emergency fund'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='How much emergency fund do you have?'
    )
    
    # Debt questions
    debt_burden = forms.ChoiceField(
        choices=[
            ('NONE', 'No debt'),
            ('MANAGEABLE', 'Manageable (Easy to make payments)'),
            ('MODERATE', 'Moderate (Payments are noticeable but manageable)'),
            ('HIGH', 'High (Payments are difficult)'),
            ('OVERWHELMING', 'Overwhelming (Can\'t make payments)'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='How would you describe your debt burden?'
    )
    
    # Savings questions
    savings_rate = forms.ChoiceField(
        choices=[
            ('HIGH', 'High (20%+ of income)'),
            ('GOOD', 'Good (10-20% of income)'),
            ('MODERATE', 'Moderate (5-10% of income)'),
            ('LOW', 'Low (Less than 5% of income)'),
            ('NONE', 'None (Not saving)'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='What is your savings rate?'
    )
    
    # Investment questions
    investment_knowledge = forms.ChoiceField(
        choices=[
            ('EXPERT', 'Expert (Professional level knowledge)'),
            ('ADVANCED', 'Advanced (Good understanding)'),
            ('INTERMEDIATE', 'Intermediate (Basic understanding)'),
            ('BEGINNER', 'Beginner (Little knowledge)'),
            ('NONE', 'None (No knowledge)'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='What is your investment knowledge level?'
    )
    
    # Goals
    financial_goals = forms.ChoiceField(
        choices=[
            ('CLEAR_PLAN', 'Clear goals with detailed plan'),
            ('GOALS_PLAN', 'Have goals with some plan'),
            ('GOALS_NO_PLAN', 'Have goals but no plan'),
            ('VAGUE', 'Vague ideas about goals'),
            ('NONE', 'No financial goals'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='How clear are your financial goals?'
    )
    
    # Risk tolerance
    risk_tolerance = forms.ChoiceField(
        choices=[
            ('AGGRESSIVE', 'Aggressive (High risk for high returns)'),
            ('MODERATE', 'Moderate (Balanced risk and return)'),
            ('CONSERVATIVE', 'Conservative (Low risk, stable returns)'),
            ('VERY_CONSERVATIVE', 'Very conservative (Avoid risk)'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        label='What is your risk tolerance?'
    )
    
    # Additional info
    age_group = forms.ChoiceField(
        choices=[
            ('UNDER_25', 'Under 25'),
            ('25_35', '25-35'),
            ('35_45', '35-45'),
            ('45_55', '45-55'),
            ('55_PLUS', '55+'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Age group'
    )
    
    dependents = forms.IntegerField(
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
        label='Number of dependents'
    )
    
    additional_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Any additional information about your financial situation...'
        })
    )

class ExportDataForm(forms.Form):
    """Data export form"""
    DATA_TYPES = [
        ('ALL', 'All Financial Data'),
        ('TRANSACTIONS', 'Transactions Only'),
        ('INCOME', 'Income Only'),
        ('EXPENSES', 'Expenses Only'),
        ('INVESTMENTS', 'Investments Only'),
        ('DEBTS', 'Debts Only'),
        ('BUDGETS', 'Budgets Only'),
        ('GOALS', 'Goals Only'),
        ('INSIGHTS', 'AI Insights Only'),
    ]
    
    FORMAT_CHOICES = [
        ('CSV', 'CSV (Excel compatible)'),
        ('JSON', 'JSON (Machine readable)'),
        ('PDF', 'PDF (Printable report)'),
        ('EXCEL', 'Excel (Advanced formatting)'),
    ]
    
    data_type = forms.ChoiceField(
        choices=DATA_TYPES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    format = forms.ChoiceField(
        choices=FORMAT_CHOICES,
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
    include_metadata = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Include metadata'
    )
    password_protect = forms.BooleanField(
        required=False,
        initial=False,
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
    
    def clean(self):
        cleaned_data = super().clean()
        password_protect = cleaned_data.get('password_protect')
        password = cleaned_data.get('password')
        
        if password_protect and not password:
            raise forms.ValidationError({
                'password': "Password is required when password protection is enabled"
            })
        
        return cleaned_data