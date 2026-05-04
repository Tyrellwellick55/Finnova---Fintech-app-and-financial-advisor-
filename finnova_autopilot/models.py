# finnova_autopilot/models.py
from django.db import models, transaction
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
from decimal import Decimal
from datetime import datetime, date, timedelta
import calendar

User = get_user_model()


def _add_months(base_date, months=1):
    """Add months to a date without requiring python-dateutil."""
    month_index = (base_date.month - 1) + int(months)
    year = base_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return base_date.replace(year=year, month=month, day=day)


def _add_years(base_date, years=1):
    """Add years to a date while handling leap-day safely."""
    try:
        return base_date.replace(year=base_date.year + int(years))
    except ValueError:
        # Handle February 29 -> February 28 in non-leap years.
        return base_date.replace(year=base_date.year + int(years), day=28)


def _months_between(start_date, end_date):
    """Approximate inclusive months between two dates."""
    if not start_date or not end_date or end_date <= start_date:
        return 0

    months = (end_date.year - start_date.year) * 12 + (end_date.month - start_date.month)
    if end_date.day > start_date.day:
        months += 1
    return max(months, 1)

class AutopilotProfile(models.Model):
    """User's autopilot configuration and preferences"""
    RISK_TOLERANCE_CHOICES = [
        ('CONSERVATIVE', 'Conservative'),
        ('MODERATE', 'Moderate'),
        ('AGGRESSIVE', 'Aggressive')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='autopilot_profile')
    organization = models.ForeignKey(
        'finnovaapp.Organization',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='autopilot_profiles',
    )
    
    # Basic settings
    is_active = models.BooleanField(default=True)
    risk_tolerance = models.CharField(max_length=20, choices=RISK_TOLERANCE_CHOICES, default='MODERATE')
    
    # Savings automation
    auto_savings_enabled = models.BooleanField(default=False)
    auto_savings_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    auto_savings_frequency = models.CharField(max_length=20, choices=[
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly')
    ], default='MONTHLY')
    auto_savings_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)])
    
    # Investment automation
    auto_investment_enabled = models.BooleanField(default=False)
    auto_investment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    auto_investment_strategy = models.CharField(max_length=50, choices=[
        ('SAFE', 'Safe - Low Risk'),
        ('BALANCED', 'Balanced - Medium Risk'),
        ('GROWTH', 'Growth - High Risk')
    ], default='BALANCED')
    
    # Budget management
    monthly_budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_alerts_enabled = models.BooleanField(default=True)
    budget_alert_threshold = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=80.00,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    
    # Bill payments
    auto_pay_bills = models.BooleanField(default=False)
    auto_pay_days_before = models.PositiveSmallIntegerField(default=2)

    # B2B-grade safety controls
    approval_required = models.BooleanField(
        default=True,
        help_text="If enabled, Autopilot will recommend payments and require human approval before executing.",
    )
    max_autopay_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('25000.00'),
        help_text="Autopilot will not recommend/execute bill payments above this amount.",
    )
    max_retry_attempts = models.PositiveSmallIntegerField(default=2)
    
    # Debt management
    auto_debt_payment = models.BooleanField(default=False)
    debt_payment_strategy = models.CharField(max_length=20, choices=[
        ('AVALANCHE', 'High Interest First'),
        ('SNOWBALL', 'Smallest Balance First'),
        ('MINIMUM', 'Minimum Payments Only')
    ], default='AVALANCHE')
    
    # Performance tracking
    total_money_saved = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_investment_gains = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_interest_saved = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_bills_auto_paid = models.PositiveIntegerField(default=0)
    
    # AI Settings
    ai_recommendations_enabled = models.BooleanField(default=True)
    learning_enabled = models.BooleanField(default=True)
    fraud_detection_enabled = models.BooleanField(default=True)
    auto_transfer_to_savings = models.BooleanField(default=True)
    
    # Notification preferences
    notification_settings = models.JSONField(default=dict, blank=True)
    
    # Metadata
    preferences = models.JSONField(default=dict, blank=True)
    last_run = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"Autopilot - {self.user.username} - {status}"
    
    def enable(self):
        """Enable autopilot"""
        self.is_active = True
        self.save()
    
    def disable(self):
        """Disable autopilot"""
        self.is_active = False
        self.save()
    
    def run_daily_tasks(self):
        """Execute daily autopilot tasks"""
        from .services.automation_engine import AutomationEngine
        results = AutomationEngine.run_daily_automation(self.user)
        self.last_run = timezone.now()
        self.save()
        return results

    @classmethod
    def _keep_canonical(cls, queryset):
        canonical = queryset.order_by('-updated_at', '-created_at').first()
        if canonical is None:
            return None

        duplicate_ids = list(queryset.exclude(pk=canonical.pk).values_list('pk', flat=True))
        if duplicate_ids:
            try:
                cls.objects.filter(pk__in=duplicate_ids).delete()
            except Exception:
                pass
        return canonical

    @classmethod
    def resolve_for_user(cls, user, organization=None, defaults=None):
        """
        Resolve one usable autopilot profile without assuming there is only one
        row per user.
        """
        defaults = defaults or {}

        with transaction.atomic():
            user_profiles = cls.objects.filter(user=user)

            if organization is not None:
                org_profile = cls._keep_canonical(user_profiles.filter(organization=organization))
                if org_profile is not None:
                    return org_profile, False

            global_profile = cls._keep_canonical(user_profiles.filter(organization__isnull=True))
            if global_profile is not None:
                return global_profile, False

            if organization is None:
                fallback_profile = user_profiles.order_by('-updated_at', '-created_at').first()
                if fallback_profile is not None:
                    return fallback_profile, False

            create_kwargs = dict(defaults)
            create_kwargs.setdefault('organization', organization)
            return cls.objects.create(user=user, **create_kwargs), True

    @property
    def metadata(self):
        """
        Backward-compatible alias for legacy code paths that still use
        `profile.metadata`.
        """
        return self.preferences or {}

    @metadata.setter
    def metadata(self, value):
        self.preferences = value or {}

class AutomationRule(models.Model):
    """Custom automation rules created by users"""
    RULE_TYPES = [
        ('SPENDING', 'Spending Rule'),
        ('SAVINGS', 'Savings Rule'),
        ('INVESTMENT', 'Investment Rule'),
        ('DEBT', 'Debt Payment Rule'),
        ('BUDGET', 'Budget Rule'),
        ('INCOME', 'Income Rule'),
        ('SECURITY', 'Security Rule'),
        ('NOTIFICATION', 'Notification Rule')
    ]
    
    CONDITION_TYPES = [
        ('AMOUNT_GREATER', 'Amount Greater Than'),
        ('AMOUNT_LESS', 'Amount Less Than'),
        ('CATEGORY_MATCH', 'Category Matches'),
        ('DATE_RANGE', 'Within Date Range'),
        ('FREQUENCY', 'Frequency Based'),
        ('BALANCE', 'Account Balance'),
        ('TIME', 'Time Based'),
        ('PATTERN', 'Spending Pattern'),
        ('LOCATION', 'Location Based'),
        ('MERCHANT', 'Merchant Based')
    ]
    
    ACTION_TYPES = [
        ('TRANSFER', 'Transfer Funds'),
        ('INVEST', 'Make Investment'),
        ('SAVE', 'Save Amount'),
        ('ALERT', 'Send Alert'),
        ('BLOCK', 'Block Transaction'),
        ('CATEGORIZE', 'Auto-Categorize'),
        ('REVIEW', 'Flag for Review'),
        ('PAY_BILL', 'Pay Bill'),
        ('CREATE_GOAL', 'Create Savings Goal'),
        ('ADJUST_BUDGET', 'Adjust Budget'),
        ('NOTIFY', 'Send Notification')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='automation_rules')
    
    # Rule details
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    rule_type = models.CharField(max_length=20, choices=RULE_TYPES, default='SPENDING')
    
    # Conditions
    condition_type = models.CharField(max_length=20, choices=CONDITION_TYPES)
    condition_value = models.JSONField(default=dict)
    
    # Actions
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    action_value = models.JSONField(default=dict)
    
    # Execution settings
    priority = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(10)])
    is_active = models.BooleanField(default=True)
    run_once = models.BooleanField(default=False)
    
    # Schedule
    schedule_type = models.CharField(max_length=20, choices=[
        ('IMMEDIATE', 'Run Immediately'),
        ('SCHEDULED', 'Scheduled'),
        ('RECURRING', 'Recurring')
    ], default='IMMEDIATE')
    schedule_value = models.JSONField(default=dict, blank=True)
    
    # Performance tracking
    execution_count = models.PositiveIntegerField(default=0)
    last_executed = models.DateTimeField(null=True, blank=True)
    success_count = models.PositiveIntegerField(default=0)
    failure_count = models.PositiveIntegerField(default=0)
    
    # Linked entities
    linked_account = models.ForeignKey('finance.Account', on_delete=models.SET_NULL, null=True, blank=True)
    linked_goal = models.ForeignKey('finance.FinancialGoal', on_delete=models.SET_NULL, null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['priority', '-created_at']
    
    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.name} - {self.rule_type} - {status}"
    
    def execute(self, trigger_data=None):
        """Execute the automation rule"""
        from .services.automation_engine import AutomationEngine
        
        try:
            result = AutomationEngine.execute_rule(self, trigger_data)
            self.execution_count += 1
            self.success_count += 1
            self.last_executed = timezone.now()
            self.save()
            
            # Deactivate if run_once
            if self.run_once:
                self.is_active = False
                self.save()
            
            return result
        except Exception as e:
            self.execution_count += 1
            self.failure_count += 1
            self.last_executed = timezone.now()
            self.save()
            raise e
    
    def check_condition(self, data):
        """Check if rule conditions are met"""
        from .services.automation_engine import AutomationEngine
        return AutomationEngine.check_condition(self.condition_type, self.condition_value, data)

class SmartBill(models.Model):
    """Smart bill tracking and automation"""
    CATEGORIES = [
        ('ELECTRICITY', 'Electricity'),
        ('WATER', 'Water'),
        ('GAS', 'Gas'),
        ('INTERNET', 'Internet'),
        ('MOBILE', 'Mobile'),
        ('CABLE_TV', 'Cable TV'),
        ('RENT', 'Rent'),
        ('MAINTENANCE', 'Maintenance'),
        ('INSURANCE', 'Insurance'),
        ('LOAN_EMI', 'Loan EMI'),
        ('CREDIT_CARD', 'Credit Card'),
        ('SUBSCRIPTION', 'Subscription'),
        ('SCHOOL_FEES', 'School Fees'),
        ('MEMBERSHIP', 'Membership'),
        ('OTHER', 'Other')
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('OVERDUE', 'Overdue'),
        ('CANCELLED', 'Cancelled'),
        ('FAILED', 'Failed Payment')
    ]
    
    RECURRENCE_PATTERNS = [
        ('NONE', 'No Recurrence'),
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('YEARLY', 'Yearly'),
        ('CUSTOM', 'Custom')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='smart_bills')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='smart_bills')
    
    # Bill details
    biller_name = models.CharField(max_length=200)
    biller_category = models.CharField(max_length=20, choices=CATEGORIES, default='OTHER')
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    due_date = models.DateField()
    
    # Recurrence
    is_recurring = models.BooleanField(default=True)
    recurrence_pattern = models.CharField(max_length=20, choices=RECURRENCE_PATTERNS, default='MONTHLY')
    recurrence_value = models.JSONField(default=dict, blank=True)  # For custom recurrence
    
    # Payment
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    paid_date = models.DateField(null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payment_reference = models.ForeignKey('payments_core.PaymentIntent', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Auto-pay
    auto_pay = models.BooleanField(default=False)
    auto_pay_days_before = models.PositiveSmallIntegerField(default=2)
    auto_pay_account = models.ForeignKey('finance.Account', on_delete=models.SET_NULL, null=True, blank=True, related_name='auto_pay_bills')
    
    # Bill details
    bill_number = models.CharField(max_length=100, blank=True, null=True)
    consumer_number = models.CharField(max_length=100, blank=True, null=True)
    bill_period = models.CharField(max_length=50, blank=True, null=True)  # e.g., "Jan 2024"
    
    # Documents
    bill_image = models.FileField(upload_to='bills/', null=True, blank=True)
    bill_data = models.JSONField(default=dict, blank=True)  # Extracted bill data
    
    # Reminders
    reminder_sent = models.BooleanField(default=False)
    last_reminder_sent = models.DateTimeField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['due_date', 'biller_name']
        indexes = [
            models.Index(fields=['user', 'status', 'due_date']),
            models.Index(fields=['due_date', 'status']),
        ]
    
    def __str__(self):
        return f"{self.biller_name} - ₹{self.amount} - Due: {self.due_date}"
    
    @property
    def is_overdue(self):
        """Check if bill is overdue"""
        return self.status == 'OVERDUE' or (self.status == 'PENDING' and self.due_date < timezone.now().date())

    @property
    def is_due_soon(self):
        """True when bill is due within the next 7 days and not yet paid/overdue."""
        if self.status not in ('PENDING',):
            return False
        days = self.days_until_due
        return 0 <= days <= 7

    @property
    def days_until_due(self):
        """Days until due date (negative if overdue)"""
        from datetime import date
        return (self.due_date - date.today()).days
    
    def mark_as_paid(self, paid_date=None, paid_amount=None, payment_reference=None):
        """Mark bill as paid"""
        self.status = 'PAID'
        self.paid_date = paid_date or timezone.now().date()
        self.paid_amount = paid_amount or self.amount
        if payment_reference:
            self.payment_reference = payment_reference
        self.save()
        
        # Create next bill if recurring
        if self.is_recurring and self.recurrence_pattern != 'NONE':
            self.create_next_bill()
    
    def create_next_bill(self):
        """Create next bill in recurrence series"""
        if self.recurrence_pattern == 'NONE':
            return None
        
        next_due_date = self.due_date
        
        if self.recurrence_pattern == 'DAILY':
            next_due_date += timedelta(days=1)
        elif self.recurrence_pattern == 'WEEKLY':
            next_due_date += timedelta(weeks=1)
        elif self.recurrence_pattern == 'MONTHLY':
            next_due_date = _add_months(next_due_date, 1)
        elif self.recurrence_pattern == 'QUARTERLY':
            next_due_date = _add_months(next_due_date, 3)
        elif self.recurrence_pattern == 'YEARLY':
            next_due_date = _add_years(next_due_date, 1)
        elif self.recurrence_pattern == 'CUSTOM':
            # Use custom recurrence logic from recurrence_value
            custom_days = int((self.recurrence_value or {}).get('days', 30))
            next_due_date += timedelta(days=custom_days)
        
        # Create new bill
        next_bill = SmartBill.objects.create(
            user=self.user,
            biller_name=self.biller_name,
            biller_category=self.biller_category,
            amount=self.amount,
            due_date=next_due_date,
            is_recurring=self.is_recurring,
            recurrence_pattern=self.recurrence_pattern,
            recurrence_value=self.recurrence_value,
            auto_pay=self.auto_pay,
            auto_pay_days_before=self.auto_pay_days_before,
            auto_pay_account=self.auto_pay_account,
            bill_number=self.bill_number,
            consumer_number=self.consumer_number,
            metadata=self.metadata
        )
        
        return next_bill
    
    def process_auto_pay(self):
        """Process automatic bill payment"""
        if not self.auto_pay or self.status != 'PENDING':
            return False
        
        # Check if it's time to pay (within auto_pay_days_before window)
        days_until = self.days_until_due
        if days_until > self.auto_pay_days_before:
            return False
        
        from payments_core.models import PaymentIntent, PaymentAccount
        
        try:
            payment_account = (
                PaymentAccount.objects.filter(user=self.user, is_primary=True, is_active=True).first()
                or PaymentAccount.objects.filter(user=self.user, is_primary=True).first()
                or PaymentAccount.objects.filter(user=self.user, is_active=True).first()
                or PaymentAccount.objects.filter(user=self.user).first()
            )
            if not payment_account:
                return False

            # Create payment intent
            payment_intent = PaymentIntent.objects.create(
                user=self.user,
                account=payment_account,
                reference_id=PaymentIntent.generate_reference_id(),
                amount=self.amount,
                payment_method='BANK_TRANSFER',
                gateway='INTERNAL',
                status='PROCESSING',
                description=f"Auto-pay: {self.biller_name}",
                metadata={'bill_id': str(self.id), 'auto_pay': True}
            )
            
            # Process payment (simplified - would integrate with payment gateway)
            payment_intent.mark_success({'payment_method': 'AUTO'})
            
            # Mark bill as paid
            self.mark_as_paid(
                paid_date=timezone.now().date(),
                paid_amount=self.amount,
                payment_reference=payment_intent
            )
            
            return True
            
        except Exception as e:
            # Log error and mark as failed
            self.status = 'FAILED'
            self.metadata['auto_pay_error'] = str(e)
            self.save()
            return False

class InvestmentPlan(models.Model):
    """Automated investment plans"""
    RISK_PROFILES = [
        ('LOW', 'Low Risk'),
        ('MEDIUM', 'Medium Risk'),
        ('HIGH', 'High Risk')
    ]
    
    STATUS_CHOICES = [
        ('PLANNING', 'Planning'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='investment_plans')
    
    # Plan details
    goal_name = models.CharField(max_length=200)
    target_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    current_invested = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    target_date = models.DateField()
    
    # Investment strategy
    risk_profile = models.CharField(max_length=20, choices=RISK_PROFILES, default='MEDIUM')
    investment_strategy = models.CharField(max_length=100, default='Balanced Portfolio')
    
    # Auto-investment
    suggested_monthly_investment = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_monthly_investment = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    investment_day = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(31)])
    
    # Performance tracking
    current_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_return = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    expected_return_rate = models.DecimalField(max_digits=5, decimal_places=2, default=8.00)  # Percentage
    
    # Allocation
    asset_allocation = models.JSONField(default=dict, blank=True)  # e.g., {"stocks": 60, "bonds": 30, "gold": 10}
    instruments = models.JSONField(default=list, blank=True)  # Specific investment instruments
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PLANNING')
    is_auto_invest = models.BooleanField(default=True)
    
    # Dates
    start_date = models.DateField(default=timezone.now)
    last_investment_date = models.DateField(null=True, blank=True)
    next_investment_date = models.DateField(null=True, blank=True)
    
    # Linked account
    source_account = models.ForeignKey('finance.Account', on_delete=models.SET_NULL, null=True, blank=True, related_name='investment_source')
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['target_date', 'goal_name']
    
    def __str__(self):
        return f"{self.goal_name} - ₹{self.current_invested}/₹{self.target_amount} - {self.user.username}"
    
    @property
    def progress_percentage(self):
        """Calculate investment progress"""
        if self.target_amount == 0:
            return 0
        return (self.current_invested / self.target_amount) * 100
    
    @property
    def months_remaining(self):
        """Months remaining to target date"""
        today = timezone.now().date()
        return _months_between(today, self.target_date)
    
    @property
    def required_monthly_investment(self):
        """Required monthly investment to reach target"""
        months = self.months_remaining
        if months <= 0:
            return Decimal('0.00')
        
        # Future value calculation considering expected returns
        remaining_amount = Decimal(self.target_amount) - Decimal(self.current_value)
        monthly_rate = Decimal(self.expected_return_rate) / 12 / 100
        
        if monthly_rate == 0:
            return remaining_amount / months
        
        # PMT formula for future value
        pmt = remaining_amount * monthly_rate / ((1 + monthly_rate) ** months - 1)
        return pmt
    
    def make_investment(self, amount, date=None):
        """Record an investment"""
        investment_amount = Decimal(amount)
        self.current_invested += investment_amount
        
        # Update current value with expected growth
        growth_factor = 1 + (Decimal(self.expected_return_rate) / 12 / 100)
        self.current_value = (self.current_value + investment_amount) * growth_factor
        self.total_return = self.current_value - self.current_invested
        
        self.last_investment_date = date or timezone.now().date()
        
        # Calculate next investment date
        self.next_investment_date = _add_months(self.last_investment_date, 1)
        
        # Check if target reached
        if self.current_value >= self.target_amount:
            self.status = 'COMPLETED'
        
        self.save()
        
        # Create investment record in finance module
        from finance.models import Investment
        Investment.objects.create(
            user=self.user,
            account=self.source_account,
            instrument='MUTUAL_FUNDS',  # Default, should be configurable
            name=f"Auto-invest: {self.goal_name}",
            invested_amount=investment_amount,
            current_value=investment_amount,  # Initial value same as investment
            purchase_date=self.last_investment_date,
            expected_return_rate=self.expected_return_rate,
            status='ACTIVE',
            risk_level=self.risk_profile,
            metadata={'investment_plan_id': str(self.id)}
        )
        
        return True

    @property
    def return_percentage(self):
        """Compatibility metric used by templates and older views."""
        if not self.current_invested:
            return Decimal('0.00')
        return (self.total_return / self.current_invested) * 100

    @property
    def monthly_investment_needed(self):
        """Alias used by legacy templates."""
        return self.required_monthly_investment

    def update_performance(self):
        """Keep derived performance fields in sync."""
        self.total_return = (self.current_value or Decimal('0.00')) - (self.current_invested or Decimal('0.00'))
        self.save(update_fields=['total_return', 'updated_at'])
        return self.total_return

    def get_value_as_of(self, target_date):
        """
        Lightweight historical value approximation used by charts.
        Falls back to current value because full valuation history is not stored.
        """
        if target_date and self.start_date and target_date < self.start_date:
            return Decimal('0.00')
        return self.current_value or self.current_invested or Decimal('0.00')

class SavingsGoal(models.Model):
    """Automated savings goals"""
    PRIORITY_CHOICES = [
        ('LOW', 'Low Priority'),
        ('MEDIUM', 'Medium Priority'),
        ('HIGH', 'High Priority'),
        ('CRITICAL', 'Critical Priority')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='savings_goals')
    
    # Goal details
    goal_name = models.CharField(max_length=200)
    target_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    current_saved = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    target_date = models.DateField()
    
    # Savings automation
    suggested_monthly_saving = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_monthly_saving = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    savings_day = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(31)])
    
    # Status
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='MEDIUM')
    status = models.CharField(max_length=20, choices=[
        ('PLANNING', 'Planning'),
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('ACHIEVED', 'Achieved'),
        ('CANCELLED', 'Cancelled')
    ], default='ACTIVE')
    
    # Auto-save
    is_auto_save = models.BooleanField(default=True)
    auto_save_account = models.ForeignKey('finance.Account', on_delete=models.SET_NULL, null=True, blank=True, related_name='savings_goals')
    
    # Progress tracking
    last_savings_date = models.DateField(null=True, blank=True)
    next_savings_date = models.DateField(null=True, blank=True)
    
    # Milestones
    milestones = models.JSONField(default=list, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['priority', 'target_date']
    
    def __str__(self):
        return f"{self.goal_name} - ₹{self.current_saved}/₹{self.target_amount} - {self.user.username}"
    
    @property
    def progress_percentage(self):
        """Calculate savings progress"""
        if self.target_amount == 0:
            return 0
        return (self.current_saved / self.target_amount) * 100
    
    @property
    def months_remaining(self):
        """Months remaining to target date"""
        today = timezone.now().date()
        return _months_between(today, self.target_date)
    
    @property
    def required_monthly_saving(self):
        """Required monthly saving to reach goal"""
        months = self.months_remaining
        if months <= 0:
            return Decimal('0.00')
        remaining = self.target_amount - self.current_saved
        return remaining / months
    
    @property
    def is_on_track(self):
        """Check if savings goal is on track"""
        if self.months_remaining <= 0:
            return self.current_saved >= self.target_amount
        
        required_monthly = self.required_monthly_saving
        return self.actual_monthly_saving >= required_monthly if self.actual_monthly_saving else False
    
    def add_savings(self, amount, date=None):
        """Add savings to goal"""
        savings_amount = Decimal(amount)
        self.current_saved += savings_amount
        self.last_savings_date = date or timezone.now().date()
        
        # Update monthly saving average
        if self.last_savings_date:
            # Simple average calculation - could be improved
            months_saving = max(1, self.months_saving)
            self.actual_monthly_saving = self.current_saved / months_saving
        
        # Calculate next savings date if auto-save
        if self.is_auto_save:
            self.next_savings_date = _add_months(self.last_savings_date, 1)
        
        # Check if goal achieved
        if self.current_saved >= self.target_amount:
            self.status = 'ACHIEVED'
        
        self.save()
        
        # Create income record for savings
        from finance.models import Income
        Income.objects.create(
            user=self.user,
            account=self.auto_save_account,
            amount=savings_amount,
            source=f"Savings: {self.goal_name}",
            category='SAVINGS',
            date=self.last_savings_date,
            description=f"Auto-save for {self.goal_name}",
            is_verified=True,
            metadata={'savings_goal_id': str(self.id)}
        )
        
        return True

    @property
    def start_date(self):
        """Legacy alias expected by detail templates."""
        if self.created_at:
            return self.created_at.date()
        return timezone.now().date()

    @property
    def completed_at(self):
        """Persist completion date inside metadata for compatibility."""
        completed = (self.metadata or {}).get('completed_at')
        if completed:
            try:
                return datetime.fromisoformat(completed).date()
            except (ValueError, TypeError):
                return completed
        return None

    @completed_at.setter
    def completed_at(self, value):
        data = self.metadata or {}
        if hasattr(value, 'isoformat'):
            data['completed_at'] = value.isoformat()
        else:
            data['completed_at'] = str(value)
        self.metadata = data

    @property
    def auto_save_enabled(self):
        """Legacy alias for old view code."""
        return self.is_auto_save

    @auto_save_enabled.setter
    def auto_save_enabled(self, value):
        self.is_auto_save = bool(value)

    @property
    def monthly_saving_needed(self):
        """Alias used by legacy templates."""
        return self.required_monthly_saving

    def update_progress(self):
        """Update goal status based on saved amount."""
        if self.current_saved >= self.target_amount:
            self.status = 'ACHIEVED'
        self.save(update_fields=['status', 'updated_at'])
        return self.progress_percentage

    def get_savings_as_of(self, target_date):
        """
        Approximate historical savings value. Full historical snapshots are not
        stored, so this returns current saved amount for charting compatibility.
        """
        if target_date and target_date < self.start_date:
            return Decimal('0.00')
        return self.current_saved or Decimal('0.00')
    
    @property
    def months_saving(self):
        """Calculate months of saving"""
        if not self.last_savings_date or not self.created_at:
            return 1
        return _months_between(self.created_at.date(), self.last_savings_date) + 1

class FinancialHealthScore(models.Model):
    """Financial health score and analysis"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='financial_health_score')
    
    # Overall score
    overall_score = models.IntegerField(validators=[MinValueValidator(0), MaxValueValidator(1000)], default=0)
    grade = models.CharField(max_length=2, choices=[
        ('A+', 'A+ (Excellent)'),
        ('A', 'A (Very Good)'),
        ('B+', 'B+ (Good)'),
        ('B', 'B (Above Average)'),
        ('C+', 'C+ (Average)'),
        ('C', 'C (Below Average)'),
        ('D', 'D (Poor)'),
        ('F', 'F (Critical)')
    ], default='C')
    
    # Component scores
    components = models.JSONField(default=dict, blank=True)  # {savings: 85, debt: 70, ...}
    
    # Analysis
    strengths = models.JSONField(default=list, blank=True)
    weaknesses = models.JSONField(default=list, blank=True)
    opportunities = models.JSONField(default=list, blank=True)
    threats = models.JSONField(default=list, blank=True)
    
    # Insights
    insights = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    
    # Trends
    trend = models.CharField(max_length=20, choices=[
        ('IMPROVING', 'Improving'),
        ('STABLE', 'Stable'),
        ('DECLINING', 'Declining'),
        ('VOLATILE', 'Volatile')
    ], default='STABLE')
    
    # Comparison
    percentile = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)  # vs similar users
    benchmark = models.JSONField(default=dict, blank=True)  # Industry benchmarks
    
    metadata = models.JSONField(default=dict, blank=True)
    calculated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-calculated_at']
    
    def __str__(self):
        return f"Financial Health - {self.user.username} - {self.overall_score}/1000 ({self.grade})"
    
    def calculate_score(self):
        """Calculate financial health score"""
        from .services.ai_advisor import AIAdvisor
        score_data = AIAdvisor.calculate_financial_health(self.user)
        
        self.overall_score = score_data['overall_score']
        self.grade = score_data['grade']
        self.components = score_data['components']
        self.strengths = score_data['strengths']
        self.weaknesses = score_data['weaknesses']
        self.opportunities = score_data['opportunities']
        self.threats = score_data['threats']
        self.insights = score_data['insights']
        self.recommendations = score_data['recommendations']
        self.trend = score_data['trend']
        self.percentile = score_data.get('percentile')
        self.benchmark = score_data.get('benchmark', {})
        
        self.save()
        return self.overall_score
    
    def get_grade_color(self):
        """Get color for grade display"""
        grade_colors = {
            'A+': '#4CAF50',  # Green
            'A': '#8BC34A',   # Light Green
            'B+': '#CDDC39',  # Lime
            'B': '#FFEB3B',   # Yellow
            'C+': '#FFC107',  # Amber
            'C': '#FF9800',   # Orange
            'D': '#FF5722',   # Deep Orange
            'F': '#F44336',   # Red
        }
        return grade_colors.get(self.grade, '#9E9E9E')  # Grey as default

    @property
    def timestamp(self):
        """Alias for calculated_at to match template expectations"""
        return self.calculated_at

class TransactionPattern(models.Model):
    """Learned transaction patterns for AI analysis"""
    PATTERN_TYPES = [
        ('SPENDING', 'Spending Pattern'),
        ('INCOME', 'Income Pattern'),
        ('TIME', 'Time-based Pattern'),
        ('LOCATION', 'Location Pattern'),
        ('CATEGORY', 'Category Pattern'),
        ('MERCHANT', 'Merchant Pattern'),
        ('AMOUNT', 'Amount Pattern'),
        ('FREQUENCY', 'Frequency Pattern')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transaction_patterns')
    
    # Pattern identification
    pattern_type = models.CharField(max_length=20, choices=PATTERN_TYPES)
    pattern_name = models.CharField(max_length=200)
    
    # Pattern data
    pattern_data = models.JSONField(default=dict)
    
    # Confidence and frequency
    confidence_score = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(100)], default=0.00)
    frequency = models.CharField(max_length=20, choices=[
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('YEARLY', 'Yearly'),
        ('IRREGULAR', 'Irregular')
    ], default='MONTHLY')
    
    # Status
    is_active = models.BooleanField(default=True)
    is_anomaly = models.BooleanField(default=False)
    
    # Detection
    detected_at = models.DateTimeField(auto_now_add=True)
    last_observed = models.DateTimeField(null=True, blank=True)
    observation_count = models.PositiveIntegerField(default=1)
    
    # Related entities
    related_category = models.CharField(max_length=50, blank=True, null=True)
    related_merchant = models.CharField(max_length=200, blank=True, null=True)
    related_location = models.CharField(max_length=500, blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-confidence_score', '-last_observed']
        unique_together = ['user', 'pattern_type', 'pattern_name']
    
    def __str__(self):
        return f"{self.pattern_type} - {self.pattern_name} - {self.confidence_score}%"
    
    def update_confidence(self, new_observation=True):
        """Update confidence score based on new observations"""
        if new_observation:
            self.observation_count += 1
            self.last_observed = timezone.now()
        
        # Simple confidence calculation based on observation count
        # More sophisticated algorithms can be implemented
        base_confidence = min(self.observation_count * 10, 100)
        
        # Adjust based on recency (decay over time)
        if self.last_observed:
            days_since = (timezone.now() - self.last_observed).days
            recency_factor = max(0, 100 - (days_since * 5)) / 100
            self.confidence_score = Decimal(str(base_confidence * recency_factor))
        else:
            self.confidence_score = Decimal(str(base_confidence))
        
        self.save()
    
    def check_match(self, transaction_data):
        """Check if transaction matches this pattern"""
        from .services.ai_advisor import AIAdvisor
        return AIAdvisor.match_pattern(self, transaction_data)

class Alert(models.Model):
    """System alerts and notifications"""
    CATEGORIES = [
        ('BUDGET', 'Budget Alert'),
        ('SAVINGS', 'Savings Alert'),
        ('INVESTMENT', 'Investment Alert'),
        ('DEBT', 'Debt Alert'),
        ('INCOME', 'Income Alert'),
        ('PAYMENT', 'Payment Alert'),
        ('SECURITY', 'Security Alert'),
        ('SYSTEM', 'System Alert'),
        ('REMINDER', 'Reminder'),
        ('INSIGHT', 'AI Insight'),
        ('OPPORTUNITY', 'Opportunity'),
        ('RISK', 'Risk Alert')
    ]
    
    SEVERITY_LEVELS = [
        ('INFO', 'Information'),
        ('LOW', 'Low Priority'),
        ('MEDIUM', 'Medium Priority'),
        ('HIGH', 'High Priority'),
        ('CRITICAL', 'Critical')
    ]
    
    SOURCES = [
        ('SYSTEM', 'System Generated'),
        ('AUTOPILOT', 'Autopilot'),
        ('AI_ANALYTICS', 'AI Analytics'),
        ('PAYMENT', 'Payment System'),
        ('FINANCE', 'Finance Module'),
        ('USER', 'User Created'),
        ('EXTERNAL', 'External Source')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alerts')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='autopilot_alerts')
    
    # Alert details
    title = models.CharField(max_length=200)
    message = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORIES, default='INFO')
    severity = models.CharField(max_length=20, choices=SEVERITY_LEVELS, default='INFO')
    source = models.CharField(max_length=20, choices=SOURCES, default='SYSTEM')
    
    # Status
    is_read = models.BooleanField(default=False)
    is_acknowledged = models.BooleanField(default=False)
    requires_acknowledgment = models.BooleanField(default=False)
    
    # Action
    action_required = models.BooleanField(default=False)
    action_type = models.CharField(max_length=50, blank=True, null=True)
    action_data = models.JSONField(default=dict, blank=True)
    action_url = models.URLField(blank=True, null=True)
    
    # Related entities
    related_transaction = models.ForeignKey('payments_core.PaymentTransaction', on_delete=models.SET_NULL, null=True, blank=True)
    related_bill = models.ForeignKey('SmartBill', on_delete=models.SET_NULL, null=True, blank=True)
    related_budget = models.ForeignKey('finance.Budget', on_delete=models.SET_NULL, null=True, blank=True)
    related_goal = models.ForeignKey('finance.FinancialGoal', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Timing
    alert_time = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-alert_time', 'severity']
        indexes = [
            models.Index(fields=['user', 'is_read', 'alert_time']),
            models.Index(fields=['category', 'severity', 'alert_time']),
        ]
    
    def __str__(self):
        status = "Read" if self.is_read else "Unread"
        return f"{self.title} - {self.severity} - {status}"
    
    def mark_as_read(self):
        """Mark alert as read"""
        self.is_read = True
        self.read_at = timezone.now()
        self.save()
    
    def acknowledge(self):
        """Acknowledge alert"""
        self.is_acknowledged = True
        self.acknowledged_at = timezone.now()
        self.save()
    
    def get_severity_color(self):
        """Get color for severity display"""
        severity_colors = {
            'INFO': '#2196F3',      # Blue
            'LOW': '#4CAF50',       # Green
            'MEDIUM': '#FFC107',    # Amber
            'HIGH': '#FF9800',      # Orange
            'CRITICAL': '#F44336',  # Red
        }
        return severity_colors.get(self.severity, '#9E9E9E')
    
    def is_expired(self):
        """Check if alert is expired"""
        if not self.expires_at:
            return False
        return timezone.now() > self.expires_at

class AITrainingData(models.Model):
    """Anonymized data for AI model training"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='training_data')
    data_type = models.CharField(max_length=50, choices=[
        ('TRANSACTION', 'Transaction History'),
        ('BUDGET', 'Budgeting Behavior'),
        ('INVESTMENT', 'Investment Decisions'),
        ('USER_PREFERENCE', 'User Preferences'),
        ('FEEDBACK', 'System Feedback')
    ])
    raw_content = models.JSONField()
    anonymized_content = models.JSONField()
    ai_processed = models.BooleanField(default=False)
    processed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "AI Training Data"
    
    def __str__(self):
        return f"{self.user.username} - {self.data_type} - {self.created_at.date()}"

class FraudEvent(models.Model):
    """Log of detected fraudulent or suspicious activities"""
    RISK_LEVELS = [
        ('LOW', 'Low Risk'),
        ('MEDIUM', 'Medium Risk'),
        ('HIGH', 'High Risk'),
        ('CRITICAL', 'Critical Risk')
    ]
    
    ACTION_CHOICES = [
        ('NONE', 'No Action'),
        ('NOTIFY', 'User Notified'),
        ('PAUSE', 'Autopilot Paused'),
        ('FREEZE', 'Account Frozen'),
        ('INVESTIGATE', 'Under Internal Investigation')
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fraud_events')
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    risk_level = models.CharField(max_length=20, choices=RISK_LEVELS, default='MEDIUM')
    reason = models.TextField()
    auto_action = models.CharField(max_length=20, choices=ACTION_CHOICES, default='NOTIFY')
    
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Fraud Events"
    
    def __str__(self):
        return f"Fraud Alert: {self.user.username} - {self.risk_level} - {self.created_at.date()}"
class AutopilotDecision(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('EXECUTED', 'Executed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
        ('USER_REJECTED', 'User Rejected')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='autopilot_decisions')
    trigger_type = models.CharField(max_length=50)
    action_taken = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    executed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Decision: {self.user.username} - {self.trigger_type} - {self.status}'

class RuleEngine(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='rule_engine_rules')
    name = models.CharField(max_length=150)
    rule_type = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)
    condition_value = models.JSONField(default=dict, blank=True)
    action_type = models.CharField(max_length=50)
    action_value = models.JSONField(default=dict, blank=True)
    execution_count = models.IntegerField(default=0)
    last_triggered = models.DateTimeField(null=True, blank=True)
    last_success = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Rule: {self.name} ({self.user.username})'

class AutopilotLog(models.Model):
    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('SKIPPED', 'Skipped'),
        ('BLOCKED', 'Blocked')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='autopilot_logs')
    action = models.CharField(max_length=50)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    transaction = models.ForeignKey('payments_core.PaymentTransaction', on_delete=models.SET_NULL, null=True, blank=True)
    bill = models.ForeignKey(SmartBill, on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Log: {self.user.username} - {self.action} - {self.status}'


class ApprovalRequest(models.Model):
    """Human approval required before Autopilot executes an action."""

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('EXPIRED', 'Expired'),
    ]

    REQUEST_TYPES = [
        ('BILL_PAYMENT', 'Bill Payment'),
        ('SAVINGS_TRANSFER', 'Savings Transfer'),
        ('OTHER', 'Other'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='approval_requests')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests')

    request_type = models.CharField(max_length=30, choices=REQUEST_TYPES, default='OTHER')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING', db_index=True)

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Optional links
    bill = models.ForeignKey(SmartBill, on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests')
    payment_intent = models.ForeignKey('payments_core.PaymentIntent', on_delete=models.SET_NULL, null=True, blank=True, related_name='approval_requests')

    why = models.TextField(blank=True, help_text="Explainability: why Autopilot is recommending this action")
    rule_fired = models.CharField(max_length=120, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='decided_approvals')

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status', 'created_at']),
        ]
        constraints = [
            # Prevent multiple pending approvals for the same bill
            models.UniqueConstraint(
                fields=['bill'],
                condition=models.Q(status='PENDING') & models.Q(bill__isnull=False),
                name='uniq_pending_approval_per_bill',
            )
        ]

    def __str__(self):
        return f"{self.request_type} {self.status} - {self.title}"
