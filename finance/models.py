# finance/models.py
import calendar
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_CEILING

from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

User = get_user_model()


def _add_months(base_date, months):
    month_index = (base_date.month - 1) + months
    year = base_date.year + (month_index // 12)
    month = (month_index % 12) + 1
    day = min(base_date.day, calendar.monthrange(year, month)[1])
    return base_date.replace(year=year, month=month, day=day)


def _add_years(base_date, years):
    year = base_date.year + years
    day = min(base_date.day, calendar.monthrange(year, base_date.month)[1])
    return base_date.replace(year=year, day=day)

class Account(models.Model):
    """Financial account for tracking purposes"""
    ACCOUNT_TYPES = [
        ('SAVINGS', 'Savings Account'),
        ('CURRENT', 'Current Account'),
        ('INVESTMENT', 'Investment Account'),
        ('LOAN', 'Loan Account'),
        ('CREDIT_CARD', 'Credit Card'),
        ('WALLET', 'Digital Wallet')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='finance_accounts')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='finance_accounts')
    name = models.CharField(max_length=100)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES)
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default='INR')
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, null=False)
    
    # Linked payment account
    payment_account = models.ForeignKey('payments_core.PaymentAccount', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Account details
    institution = models.CharField(max_length=100, blank=True, null=True)
    account_number = models.CharField(max_length=50, blank=True, null=True)
    
    # Status
    is_primary = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    include_in_total = models.BooleanField(default=True)
    
    # Metadata
    color = models.CharField(max_length=7, default='#4CAF50')  # Hex color
    notes = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_reconciled = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-is_primary', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'organization'],
                condition=Q(is_primary=True, organization__isnull=False),
                name='uniq_primary_finance_account_per_org',
            ),
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(is_primary=True, organization__isnull=True),
                name='uniq_primary_finance_account_personal',
            ),
        ]
    
    def __str__(self):
        return f"{self.name} - {self.user.username}"
    
    def update_balance(self):
        """Update balance from transactions"""
        total_income = Income.objects.filter(
            account=self, 
            is_verified=True
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        
        total_expenses = Expense.objects.filter(
            account=self,
            is_verified=True
        ).aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')
        
        self.current_balance = self.opening_balance + total_income - total_expenses
        self.save()
    
    @classmethod
    def _generate_candidate(cls):
        """Generate unique account number"""
        import random
        return f"FIN{random.randint(10000000, 99999999)}"

class Income(models.Model):
    """Income tracking model"""
    INCOME_CATEGORIES = [
        ('SALARY', 'Salary'),
        ('FREELANCE', 'Freelance'),
        ('BUSINESS', 'Business Income'),
        ('INVESTMENT', 'Investment Returns'),
        ('RENTAL', 'Rental Income'),
        ('GIFT', 'Gift'),
        ('REFUND', 'Refund'),
        ('INTEREST', 'Interest'),
        ('DIVIDEND', 'Dividend'),
        ('OTHER', 'Other Income')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='incomes')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='incomes')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='incomes')
    
    # Income details
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    source = models.CharField(max_length=200)
    category = models.CharField(max_length=20, choices=INCOME_CATEGORIES, default='SALARY')
    date = models.DateField(default=timezone.now)
    description = models.TextField(blank=True)
    
    # Payment reference
    payment_reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    # Recurring income
    is_recurring = models.BooleanField(default=False)
    recurrence_pattern = models.CharField(max_length=50, blank=True, null=True)
    next_date = models.DateField(null=True, blank=True)
    
    # Verification
    is_verified = models.BooleanField(default=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_incomes')
    verified_at = models.DateTimeField(null=True, blank=True)
    
    # Documents
    receipt = models.FileField(upload_to='income_receipts/', null=True, blank=True)
    invoice_number = models.CharField(max_length=100, blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['category', 'date']),
            models.Index(fields=['is_recurring', 'next_date']),
        ]
    
    def __str__(self):
        return f"{self.source} - ₹{self.amount} - {self.date}"
    
    @property
    def reference_number(self):
        """Backward-compatible alias used by older templates/import-export flows."""
        return self.invoice_number

    @reference_number.setter
    def reference_number(self, value):
        self.invoice_number = value

    def save(self, *args, **kwargs):
        """Override save to update account balance"""
        super().save(*args, **kwargs)
        if self.is_verified:
            self.account.update_balance()

class Expense(models.Model):
    """Expense tracking model"""
    EXPENSE_CATEGORIES = [
        ('FOOD', 'Food & Dining'),
        ('TRANSPORT', 'Transportation'),
        ('SHOPPING', 'Shopping'),
        ('ENTERTAINMENT', 'Entertainment'),
        ('BILLS', 'Bills & Utilities'),
        ('HEALTH', 'Healthcare'),
        ('EDUCATION', 'Education'),
        ('GROCERIES', 'Groceries'),
        ('FUEL', 'Fuel'),
        ('SUBSCRIPTION', 'Subscriptions'),
        ('TRAVEL', 'Travel'),
        ('PERSONAL_CARE', 'Personal Care'),
        ('GIFTS', 'Gifts & Donations'),
        ('INSURANCE', 'Insurance'),
        ('TAX', 'Taxes'),
        ('RENT', 'Rent'),
        ('EMI', 'Loan EMI'),
        ('OTHER', 'Other Expenses')
    ]
    
    PAYMENT_METHODS = [
        ('CASH', 'Cash'),
        ('CARD', 'Credit/Debit Card'),
        ('UPI', 'UPI'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('WALLET', 'Digital Wallet'),
        ('CHEQUE', 'Cheque'),
        ('OTHER', 'Other')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expenses')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='expenses')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='expenses')
    budget_category = models.ForeignKey('BudgetCategory', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    
    # Expense details
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    description = models.CharField(max_length=500)
    category = models.CharField(max_length=20, choices=EXPENSE_CATEGORIES, default='OTHER')
    custom_category = models.CharField(max_length=100, blank=True, null=True)
    date = models.DateField(default=timezone.now)
    time = models.TimeField(null=True, blank=True)
    
    # Payment details
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='CASH')
    merchant = models.CharField(max_length=200, blank=True, null=True)
    location = models.CharField(max_length=500, blank=True, null=True)
    
    # Payment integration
    payment_reference = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    payment_intent = models.ForeignKey('payments_core.PaymentIntent', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Budget tracking
    is_budgeted = models.BooleanField(default=True)
    
    # Verification
    is_verified = models.BooleanField(default=True)
    requires_review = models.BooleanField(default=False)
    
    # Receipt/document
    receipt = models.FileField(upload_to='expense_receipts/', null=True, blank=True)
    receipt_text = models.TextField(blank=True, null=True)  # OCR text
    
    # Tags for categorization
    tags = models.JSONField(default=list, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date', '-created_at']
        indexes = [
            models.Index(fields=['user', 'date']),
            models.Index(fields=['category', 'date']),
            models.Index(fields=['payment_method', 'date']),
            models.Index(fields=['merchant', 'date']),
        ]
        constraints = [
            # Hard idempotency guard: one successful payment intent must map to at most one Expense.
            models.UniqueConstraint(fields=['payment_intent'], name='uniq_expense_payment_intent'),
        ]
    
    def __str__(self):
        return f"{self.description[:50]} - ₹{self.amount} - {self.date}"
    
    def save(self, *args, **kwargs):
        """Override save to update account balance and budget"""
        super().save(*args, **kwargs)
        if self.is_verified:
            self.account.update_balance()
            if self.budget_category:
                self.budget_category.update_spending()
    
    def get_category_display(self):
        """Get category display name"""
        if self.custom_category:
            return self.custom_category
        return dict(self.EXPENSE_CATEGORIES).get(self.category, self.category)

class Budget(models.Model):
    """Budget planning model"""
    PERIOD_CHOICES = [
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('YEARLY', 'Yearly'),
        ('CUSTOM', 'Custom Date Range')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budgets')
    name = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    period = models.CharField(max_length=20, choices=PERIOD_CHOICES, default='MONTHLY')
    
    # Date range
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    
    # Status
    is_active = models.BooleanField(default=True)
    is_recurring = models.BooleanField(default=True)
    
    # Spending tracking
    current_spending = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    last_updated = models.DateTimeField(auto_now=True)
    
    # Alerts
    alert_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=80.00, 
                                         validators=[MinValueValidator(Decimal('0.00')), 
                                                     MaxValueValidator(Decimal('100.00'))])
    notifications_enabled = models.BooleanField(default=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-is_active', '-created_at']
    
    def __str__(self):
        return f"{self.name} - ₹{self.amount}/{self.period} - {self.user.username}"
    
    @property
    def category(self):
        """Return the primary budget category for legacy views/templates."""
        return self.categories.order_by('priority', 'name').first()

    @property
    def color(self):
        """Expose a display color derived from the primary category."""
        primary_category = self.category
        return primary_category.color_code if primary_category and primary_category.color_code else None

    def get_category_display(self):
        """Return a human-readable category label for legacy templates."""
        primary_category = self.category
        return primary_category.name if primary_category else 'General'

    @property
    def status(self):
        """Compatibility status flag for templates and list views."""
        if not self.is_active:
            return 'INACTIVE'
        if self.is_exceeded:
            return 'EXCEEDED'
        if self.is_near_limit:
            return 'NEAR_LIMIT'
        return 'HEALTHY'

    def get_status_display(self):
        """Return a human-readable budget health label."""
        return {
            'HEALTHY': 'Healthy',
            'NEAR_LIMIT': 'Near Limit',
            'EXCEEDED': 'Exceeded',
            'INACTIVE': 'Inactive',
        }.get(self.status, 'Healthy')

    @property
    def is_exceeded(self):
        """Check if budget is exceeded"""
        return self.current_spending > self.amount
    
    @property
    def is_near_limit(self):
        """Check if budget is near limit"""
        if self.amount == 0:
            return False
        utilization = (self.current_spending / self.amount) * 100
        return utilization >= self.alert_threshold
    
    @property
    def utilization_percentage(self):
        """Calculate budget utilization percentage"""
        if self.amount == 0:
            return 0
        return (self.current_spending / self.amount) * 100
    
    @property
    def remaining_amount(self):
        """Calculate remaining budget"""
        return max(self.amount - self.current_spending, Decimal('0.00'))

    @property
    def progress_display(self):
        """Alias for utilization_percentage — used in budget list/detail templates."""
        if hasattr(self, '_progress_display'):
            return self._progress_display
        return self.utilization_percentage

    @progress_display.setter
    def progress_display(self, value):
        self._progress_display = value

    @property
    def primary_category_label(self):
        """Human-readable label for the primary budget category — used in templates."""
        if hasattr(self, '_primary_category_label'):
            return self._primary_category_label
        primary = self.category  # uses the existing @property that returns first BudgetCategory
        if primary:
            return primary.name
        return self.get_category_display()

    @primary_category_label.setter
    def primary_category_label(self, value):
        self._primary_category_label = value

    def update_spending(self):
        """Update current spending from expenses"""
        from django.db.models import Sum

        if self.end_date and self.end_date < timezone.now().date():
            self.is_active = False
            self.save()
            return

        # Build date range for this budget period
        expenses = Expense.objects.filter(
            user=self.user,
            date__gte=self.start_date,
            is_verified=True,
        )
        if self.end_date:
            expenses = expenses.filter(date__lte=self.end_date)

        # PRIMARY: expenses explicitly linked to a BudgetCategory belonging to this budget
        direct = expenses.filter(budget_category__budget=self)

        # FALLBACK: expenses whose category/custom_category matches any category name in this budget
        budget_category_names = list(self.categories.values_list('name', flat=True))
        if budget_category_names:
            indirect = expenses.filter(
                models.Q(category__in=budget_category_names) |
                models.Q(custom_category__in=budget_category_names)
            ).exclude(budget_category__budget=self)
            all_expenses = direct | indirect
        else:
            all_expenses = direct

        self.current_spending = all_expenses.distinct().aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

        self.save(update_fields=['current_spending', 'last_updated'])

    
    def reset(self, carry_over=False):
        """Reset budget for new period"""
        if carry_over and self.is_recurring:
            # Carry over unused amount
            carry_amount = self.remaining_amount
        else:
            carry_amount = Decimal('0.00')
        
        # Calculate new period
        new_start = self.end_date + timedelta(days=1) if self.end_date else timezone.now().date()
        
        if self.period == 'MONTHLY':
            new_end = _add_months(new_start, 1) - timedelta(days=1)
        elif self.period == 'WEEKLY':
            new_end = new_start + timedelta(weeks=1, days=-1)
        elif self.period == 'YEARLY':
            new_end = _add_years(new_start, 1) - timedelta(days=1)
        else:
            new_end = None
        
        # Create new budget entry
        new_budget = Budget.objects.create(
            user=self.user,
            name=self.name,
            amount=self.amount + carry_amount,
            period=self.period,
            start_date=new_start,
            end_date=new_end,
            is_active=True,
            is_recurring=self.is_recurring,
            alert_threshold=self.alert_threshold,
            notifications_enabled=self.notifications_enabled
        )
        
        # Copy categories
        for category in self.categories.all():
            BudgetCategory.objects.create(
                budget=new_budget,
                name=category.name,
                allocated_amount=category.allocated_amount,
                color_code=category.color_code,
                priority=category.priority
            )
        
        return new_budget

class BudgetCategory(models.Model):
    """Categories within a budget"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name='categories')
    name = models.CharField(max_length=100)
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    spent_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    color_code = models.CharField(max_length=7, default='#2196F3')  # Hex color
    icon = models.CharField(max_length=50, blank=True, null=True)
    priority = models.PositiveIntegerField(default=1)
    description = models.TextField(blank=True, null=True)
    
    class Meta:
        ordering = ['priority', 'name']
        verbose_name_plural = 'Budget Categories'
        unique_together = ['budget', 'name']
    
    def __str__(self):
        return f"{self.name} - ₹{self.allocated_amount} - {self.budget.name}"
    
    @property
    def utilization_percentage(self):
        """Calculate category utilization percentage"""
        if self.allocated_amount == 0:
            return 0
        return (self.spent_amount / self.allocated_amount) * 100
    
    @property
    def remaining_amount(self):
        """Calculate remaining amount in category"""
        return max(self.allocated_amount - self.spent_amount, Decimal('0.00'))
    
    def update_spending(self):
        """Update spent amount from expenses"""
        from django.db.models import Sum
        
        # Get expenses for this category in budget period
        expenses = Expense.objects.filter(
            user=self.budget.user,
            budget_category=self,
            date__gte=self.budget.start_date,
            is_verified=True
        )
        
        if self.budget.end_date:
            expenses = expenses.filter(date__lte=self.budget.end_date)
        
        self.spent_amount = expenses.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        self.save()

class FinancialGoal(models.Model):
    """Financial goals and targets"""
    GOAL_TYPES = [
        ('SAVINGS', 'Savings Goal'),
        ('DEBT_FREE', 'Debt Free Goal'),
        ('INVESTMENT', 'Investment Goal'),
        ('PURCHASE', 'Major Purchase'),
        ('EMERGENCY_FUND', 'Emergency Fund'),
        ('RETIREMENT', 'Retirement Planning'),
        ('EDUCATION', 'Education Fund'),
        ('VACATION', 'Vacation/Travel'),
        ('HOME', 'Home Purchase'),
        ('CAR', 'Car Purchase'),
        ('WEDDING', 'Wedding'),
        ('OTHER', 'Other Goal')
    ]
    
    STATUS_CHOICES = [
        ('PLANNING', 'Planning'),
        ('IN_PROGRESS', 'In Progress'),
        ('ACHIEVED', 'Achieved'),
        ('ON_HOLD', 'On Hold'),
        ('CANCELLED', 'Cancelled')
    ]
    
    PRIORITY_CHOICES = [
        ('LOW', 'Low Priority'),
        ('MEDIUM', 'Medium Priority'),
        ('HIGH', 'High Priority'),
        ('CRITICAL', 'Critical Priority')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='financial_goals')
    name = models.CharField(max_length=200)
    goal_type = models.CharField(max_length=20, choices=GOAL_TYPES, default='SAVINGS')
    target_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    current_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Timeline
    start_date = models.DateField(default=timezone.now)
    target_date = models.DateField()
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PLANNING')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='MEDIUM')
    
    # Progress tracking
    suggested_monthly_saving = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    last_contribution_date = models.DateField(null=True, blank=True)
    last_contribution_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Linked account for tracking
    linked_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name='goals')
    
    # Milestones
    milestones = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['priority', 'target_date']
    
    def __str__(self):
        return f"{self.name} - ₹{self.current_amount}/{self.target_amount} - {self.user.username}"
    
    @property
    def months_remaining(self):
        """Calculate months remaining to target date"""
        today = timezone.now().date()
        if self.target_date <= today:
            return 0

        month_delta = (self.target_date.year - today.year) * 12 + (self.target_date.month - today.month)

        # Count a partial month as one month to preserve previous behaviour.
        if self.target_date.day > today.day:
            month_delta += 1

        return max(month_delta, 1)
    
    @property
    def progress_percentage(self):
        """Calculate progress percentage safely with Decimal-compatible inputs."""
        target = Decimal(str(self.target_amount or '0'))
        current = Decimal(str(self.current_amount or '0'))
        if target == 0:
            return Decimal('0.00')
        return (current / target) * Decimal('100')

    @property
    def progress_display(self):
        """Alias for progress_percentage — used in goal card templates."""
        if hasattr(self, '_progress_display'):
            return self._progress_display
        return self.progress_percentage

    @progress_display.setter
    def progress_display(self, value):
        self._progress_display = value

    @property
    def required_monthly_saving(self):
        """Calculate required monthly saving to reach goal"""
        months = self.months_remaining
        if months <= 0:
            return Decimal('0.00')
        target = Decimal(str(self.target_amount or '0'))
        current = Decimal(str(self.current_amount or '0'))
        remaining = max(target - current, Decimal('0.00'))
        return remaining / Decimal(months)
    
    @property
    def is_on_track(self):
        """Check if goal is on track"""
        if self.months_remaining <= 0:
            return self.current_amount >= self.target_amount
        
        required_monthly = self.required_monthly_saving
        suggested = Decimal(str(self.suggested_monthly_saving or '0'))
        return suggested >= required_monthly if suggested else False
    
    def update_progress(self, amount):
        """Update goal progress with contribution"""
        self.current_amount = Decimal(str(self.current_amount or '0')) + Decimal(str(amount))
        self.last_contribution_date = timezone.now().date()
        self.last_contribution_amount = Decimal(str(amount))
        
        # Check if goal achieved
        if self.current_amount >= self.target_amount:
            self.status = 'ACHIEVED'
        
        self.save()

class Investment(models.Model):
    """Investment tracking model"""
    INSTRUMENT_TYPES = [
        ('STOCKS', 'Stocks'),
        ('MUTUAL_FUNDS', 'Mutual Funds'),
        ('FD', 'Fixed Deposit'),
        ('RD', 'Recurring Deposit'),
        ('PPF', 'Public Provident Fund'),
        ('NPS', 'National Pension System'),
        ('GOLD', 'Gold'),
        ('REAL_ESTATE', 'Real Estate'),
        ('CRYPTO', 'Cryptocurrency'),
        ('BONDS', 'Bonds'),
        ('ETF', 'Exchange Traded Fund'),
        ('OTHER', 'Other Investment')
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('MATURED', 'Matured'),
        ('SOLD', 'Sold'),
        ('CLOSED', 'Closed'),
        ('DEFAULTED', 'Defaulted')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='investments')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='investments')
    
    # Investment details
    instrument = models.CharField(max_length=50, choices=INSTRUMENT_TYPES, default='MUTUAL_FUNDS')
    name = models.CharField(max_length=200)
    invested_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    current_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Dates
    purchase_date = models.DateField(default=timezone.now)
    maturity_date = models.DateField(null=True, blank=True)
    
    # Returns
    expected_return_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)  # Percentage
    actual_return_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    is_liquid = models.BooleanField(default=False)
    risk_level = models.CharField(max_length=20, choices=[
        ('LOW', 'Low Risk'),
        ('MEDIUM', 'Medium Risk'),
        ('HIGH', 'High Risk')
    ], default='MEDIUM')
    
    # Additional details
    issuer = models.CharField(max_length=200, blank=True, null=True)
    folio_number = models.CharField(max_length=100, blank=True, null=True)
    certificate_number = models.CharField(max_length=100, blank=True, null=True)
    
    # Documents
    documents = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_valuation_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-purchase_date']
    
    def __str__(self):
        return f"{self.name} - ₹{self.invested_amount} - {self.user.username}"
    
    @property
    def total_return(self):
        """Calculate total return"""
        return self.current_value - self.invested_amount
    
    @property
    def return_percentage(self):
        """Calculate return percentage"""
        if self.invested_amount == 0:
            return Decimal('0.00')
        return ((self.current_value - self.invested_amount) / self.invested_amount) * 100
    
    @property
    def holding_period(self):
        """Calculate holding period in years"""
        today = timezone.now().date()
        total_days = max((today - self.purchase_date).days, 0)
        return total_days / 365.25
    
    def update_valuation(self, new_value):
        """Update current valuation"""
        self.current_value = Decimal(new_value)
        self.last_valuation_date = timezone.now()
        
        # Calculate actual return rate if holding period > 0
        if self.holding_period > 0:
            cagr = ((self.current_value / self.invested_amount) ** (1 / self.holding_period) - 1) * 100
            self.actual_return_rate = cagr
        
        self.save()

class Debt(models.Model):
    """Debt/loan tracking model"""
    DEBT_TYPES = [
        ('PERSONAL_LOAN', 'Personal Loan'),
        ('HOME_LOAN', 'Home Loan'),
        ('CAR_LOAN', 'Car Loan'),
        ('EDUCATION_LOAN', 'Education Loan'),
        ('CREDIT_CARD', 'Credit Card Debt'),
        ('BUSINESS_LOAN', 'Business Loan'),
        ('FRIEND_FAMILY', 'Friend/Family Loan'),
        ('OTHER', 'Other Debt')
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('PAID_OFF', 'Paid Off'),
        ('DEFAULTED', 'Defaulted'),
        ('RESTRUCTURED', 'Restructured'),
        ('SETTLED', 'Settled')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='debts')
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='debts')
    
    # Debt details
    debt_type = models.CharField(max_length=20, choices=DEBT_TYPES, default='PERSONAL_LOAN')
    lender = models.CharField(max_length=200)
    principal_amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    remaining_amount = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Interest
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2)  # Annual percentage
    interest_type = models.CharField(max_length=20, choices=[
        ('FIXED', 'Fixed Rate'),
        ('FLOATING', 'Floating Rate')
    ], default='FIXED')
    
    # EMI details
    emi_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    emi_day = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(31)])
    
    # Dates
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    
    # Payment tracking
    total_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    last_payment_date = models.DateField(null=True, blank=True)
    next_payment_date = models.DateField(null=True, blank=True)
    
    # Auto-pay
    auto_pay_enabled = models.BooleanField(default=False)
    auto_pay_account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, related_name='auto_pay_debts')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    is_secured = models.BooleanField(default=False)
    collateral = models.CharField(max_length=500, blank=True, null=True)
    
    # Additional info
    loan_account_number = models.CharField(max_length=100, blank=True, null=True)
    agreement_number = models.CharField(max_length=100, blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.lender} - ₹{self.remaining_amount} - {self.user.username}"
    
    @property
    def progress_percentage(self):
        """Calculate payoff progress"""
        if self.principal_amount == 0:
            return 100
        return ((self.principal_amount - self.remaining_amount) / self.principal_amount) * 100

    @property
    def paid_percentage(self):
        """Alias for progress_percentage — used in debts.html template."""
        return self.progress_percentage


        """Estimate months remaining based on EMI"""
        if not self.emi_amount or self.emi_amount <= 0:
            return 0
        remaining = Decimal(str(self.remaining_amount or '0'))
        emi_amount = Decimal(str(self.emi_amount or '0'))
        if emi_amount <= 0:
            return 0
        return int((remaining / emi_amount).to_integral_value(rounding=ROUND_CEILING))
    
    @property
    def interest_paid(self):
        """Calculate total interest paid"""
        return self.total_paid - (self.principal_amount - self.remaining_amount)
    
    def make_payment(self, amount, date=None):
        """Record a payment towards debt"""
        payment_amount = Decimal(amount)
        self.remaining_amount = max(self.remaining_amount - payment_amount, Decimal('0.00'))
        self.total_paid += payment_amount
        self.last_payment_date = date or timezone.now().date()
        
        # Update next payment date for EMI
        if self.emi_day and self.emi_amount:
            self.next_payment_date = _add_months(self.last_payment_date, 1)
            due_day = min(self.emi_day, calendar.monthrange(self.next_payment_date.year, self.next_payment_date.month)[1])
            self.next_payment_date = self.next_payment_date.replace(day=due_day)
        
        # Check if paid off
        if self.remaining_amount <= 0:
            self.status = 'PAID_OFF'
            self.end_date = self.last_payment_date
        
        self.save()
    
    def calculate_emi(self, tenure_months):
        """Calculate EMI using standard formula"""
        monthly_rate = self.interest_rate / 12 / 100
        emi = (self.principal_amount * monthly_rate * (1 + monthly_rate) ** tenure_months) / \
              ((1 + monthly_rate) ** tenure_months - 1)
        return emi

class TaxRecord(models.Model):
    """Tax filing and payment records"""
    TAX_TYPES = [
        ('INCOME_TAX', 'Income Tax'),
        ('GST', 'Goods and Services Tax'),
        ('TDS', 'Tax Deducted at Source'),
        ('PROPERTY_TAX', 'Property Tax'),
        ('SALES_TAX', 'Sales Tax'),
        ('OTHER', 'Other Tax')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tax_records')
    financial_year = models.CharField(max_length=9)  # Format: 2023-2024
    
    # Tax details
    tax_type = models.CharField(max_length=20, choices=TAX_TYPES, default='INCOME_TAX')
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2)
    tax_paid = models.DecimalField(max_digits=12, decimal_places=2)
    tax_due = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Filing dates
    due_date = models.DateField()
    filed_date = models.DateField(null=True, blank=True)
    
    # Status
    is_filed = models.BooleanField(default=False)
    is_paid = models.BooleanField(default=False)
    filing_status = models.CharField(max_length=20, choices=[
        ('NOT_FILED', 'Not Filed'),
        ('FILED', 'Filed'),
        ('ASSESSED', 'Assessed'),
        ('APPEALED', 'Appealed'),
        ('SETTLED', 'Settled')
    ], default='NOT_FILED')
    
    # Documents
    acknowledgement_number = models.CharField(max_length=100, blank=True, null=True)
    assessment_number = models.CharField(max_length=100, blank=True, null=True)
    documents = models.JSONField(default=list, blank=True)
    
    # Verification
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_taxes')
    verified_at = models.DateTimeField(null=True, blank=True)
    
    notes = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-financial_year', 'tax_type']
        unique_together = ['user', 'financial_year', 'tax_type']
    
    def __str__(self):
        return f"{self.get_tax_type_display()} - FY {self.financial_year} - ₹{self.tax_paid}"
    
    @property
    def total_tax(self):
        """Total tax liability"""
        return self.tax_paid + self.tax_due
    
    @property
    def is_overdue(self):
        """Check if tax payment is overdue"""
        if self.is_paid:
            return False
        return self.due_date < timezone.now().date()
    
    def mark_as_filed(self, filed_date=None, acknowledgement_number=None):
        """Mark tax as filed"""
        self.is_filed = True
        self.filed_date = filed_date or timezone.now().date()
        self.filing_status = 'FILED'
        if acknowledgement_number:
            self.acknowledgement_number = acknowledgement_number
        self.save()
    
    def record_payment(self, amount, payment_date=None):
        """Record tax payment"""
        payment_amount = Decimal(amount)
        self.tax_paid += payment_amount
        self.tax_due = max(self.tax_due - payment_amount, Decimal('0.00'))
        
        if self.tax_due <= 0:
            self.is_paid = True
        
        self.save()

class FinancialReport(models.Model):
    """Generated financial reports"""
    REPORT_TYPES = [
        ('MONTHLY', 'Monthly Report'),
        ('QUARTERLY', 'Quarterly Report'),
        ('YEARLY', 'Annual Report'),
        ('CASH_FLOW', 'Cash Flow Report'),
        ('NET_WORTH', 'Net Worth Report'),
        ('TAX', 'Tax Report'),
        ('BUDGET', 'Budget Performance'),
        ('INVESTMENT', 'Investment Portfolio'),
        ('CUSTOM', 'Custom Report')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='financial_reports')
    report_type = models.CharField(max_length=20, choices=REPORT_TYPES, default='MONTHLY')
    title = models.CharField(max_length=500)
    
    # Date range
    start_date = models.DateField()
    end_date = models.DateField()
    
    # Report data
    report_data = models.JSONField(default=dict)
    charts_data = models.JSONField(default=dict, blank=True)
    
    # Insights and recommendations
    insights = models.JSONField(default=list, blank=True)
    recommendations = models.JSONField(default=list, blank=True)
    
    # Status
    is_generated = models.BooleanField(default=False)
    is_shared = models.BooleanField(default=False)
    
    # Export
    pdf_file = models.FileField(upload_to='reports/pdf/', null=True, blank=True)
    excel_file = models.FileField(upload_to='reports/excel/', null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-generated_at', '-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"
    
    def generate(self):
        """Generate report data"""
        from .services.finance_engine import FinanceEngine
        self.report_data = FinanceEngine.generate_report(
            user=self.user,
            report_type=self.report_type,
            start_date=self.start_date,
            end_date=self.end_date
        )
        self.is_generated = True
        self.generated_at = timezone.now()
        self.save()
        return self.report_data

class FinancialMetric(models.Model):
    """Key financial metrics for trend analysis"""
    METRIC_TYPES = [
        ('SAVINGS_RATE', 'Savings Rate'),
        ('DEBT_TO_INCOME', 'Debt to Income Ratio'),
        ('EXPENSE_RATIO', 'Expense Ratio'),
        ('NET_WORTH', 'Net Worth'),
        ('CASH_FLOW', 'Monthly Cash Flow'),
        ('EMERGENCY_FUND', 'Emergency Fund Coverage'),
        ('RETIREMENT_SAVINGS', 'Retirement Savings Progress'),
        ('INVESTMENT_RETURN', 'Investment Return'),
        ('BUDGET_ADHERENCE', 'Budget Adherence'),
        ('CREDIT_UTILIZATION', 'Credit Utilization')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='financial_metrics')
    metric_type = models.CharField(max_length=50, choices=METRIC_TYPES)
    value = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=20, default='percentage')
    
    # Trend data
    previous_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    change_percentage = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Time period
    period_start = models.DateField()
    period_end = models.DateField()
    recorded_date = models.DateField(default=timezone.now)
    
    # Target
    target_value = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    is_on_target = models.BooleanField(default=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-recorded_date', 'metric_type']
        unique_together = ['user', 'metric_type', 'recorded_date']
    
    def __str__(self):
        return f"{self.get_metric_type_display()} - {self.value} - {self.recorded_date}"
    
    def calculate_change(self):
        """Calculate change from previous value"""
        if self.previous_value is None:
            return None
        
        if self.previous_value == 0:
            return Decimal('100.00') if self.value > 0 else Decimal('-100.00')
        
        change = ((self.value - self.previous_value) / abs(self.previous_value)) * 100
        return change
    
    @classmethod
    def record_metric(cls, user, metric_type, value, period_start=None, period_end=None):
        """Record a new metric with trend calculation"""
        recorded_date = timezone.now().date()
        normalized_value = Decimal(str(value or '0'))
        
        # Get previous value
        previous = cls.objects.filter(
            user=user,
            metric_type=metric_type,
            recorded_date__lt=recorded_date,
        ).order_by('-recorded_date').first()
        
        previous_value = previous.value if previous else None
        
        # Calculate change
        change_percentage = None
        if previous_value is not None:
            if previous_value == 0:
                change_percentage = Decimal('100.00') if normalized_value > 0 else Decimal('-100.00')
            else:
                change_percentage = ((normalized_value - previous_value) / abs(previous_value)) * 100
        
        metric, _ = cls.objects.update_or_create(
            user=user,
            metric_type=metric_type,
            recorded_date=recorded_date,
            defaults={
                "value": normalized_value,
                "previous_value": previous_value,
                "change_percentage": change_percentage,
                "period_start": period_start or recorded_date.replace(day=1),
                "period_end": period_end or recorded_date,
            },
        )
        
        return metric
