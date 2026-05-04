# payments_core/models.py
from django.db import models
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
import hashlib
from decimal import Decimal

User = get_user_model()

class PaymentAccount(models.Model):
    """User's primary payment account"""
    ACCOUNT_TYPES = [
        ('SAVINGS', 'Savings Account'),
        ('CURRENT', 'Current Account'),
        ('WALLET', 'Digital Wallet'),
        ('CREDIT', 'Credit Account')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_accounts')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='payment_accounts')
    account_number = models.CharField(max_length=20, unique=True, db_index=True)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES, default='SAVINGS')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    available_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    currency = models.CharField(max_length=3, default='INR')
    is_active = models.BooleanField(default=True)
    is_primary = models.BooleanField(default=False)
    min_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    overdraft_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    # Linked bank details (for real banking integration)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_branch = models.CharField(max_length=100, blank=True, null=True)
    ifsc_code = models.CharField(max_length=11, blank=True, null=True)
    upi_id = models.CharField(max_length=100, blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_transaction_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Allow ONE primary account per (user, organization) when organization is set.
            models.UniqueConstraint(
                fields=['user', 'organization'],
                condition=Q(is_primary=True, organization__isnull=False),
                name='uniq_primary_payment_account_per_org',
            ),
            # Allow ONE primary personal account per user when organization is NULL.
            models.UniqueConstraint(
                fields=['user'],
                condition=Q(is_primary=True, organization__isnull=True),
                name='uniq_primary_payment_account_personal',
            ),
        ]
    
    def __str__(self):
        return f"{self.account_number} - {self.user.username}"
    
    def update_balance(self, amount):
        """Update account balance atomically.

        Important: this method must update *this instance* too.
        Many parts of the code compute `balance_after` immediately after calling
        `update_balance()`. If we only update a separate ORM instance, callers
        will read a stale balance and write incorrect audit trails.
        """
        from django.db import transaction

        with transaction.atomic():
            account = PaymentAccount.objects.select_for_update().get(id=self.id)

            new_balance = account.balance + Decimal(amount)
            account.balance = max(new_balance, Decimal('0.00'))
            account.available_balance = max(account.balance - account.min_balance, Decimal('0.00'))
            account.last_transaction_at = timezone.now()
            account.save(update_fields=['balance', 'available_balance', 'last_transaction_at', 'updated_at'])

            # Keep the caller instance in-sync
            self.balance = account.balance
            self.available_balance = account.available_balance
            self.last_transaction_at = account.last_transaction_at

        return self.balance
    
    def can_withdraw(self, amount):
        """Check if withdrawal is possible"""
        return self.available_balance >= Decimal(amount)
    
    @property
    def wallet_status(self) -> str:
        """
        Backwards‑compatible wallet status indicator.

        Older parts of the system expected a separate `Wallet` model with
        a `wallet_status` field. We treat this `PaymentAccount` as that
        wallet and derive the status from `is_active`.
        """
        return 'ACTIVE' if self.is_active else 'FROZEN'
    
    @classmethod
    def generate_account_number(cls):
        """Generate unique account number"""
        import random
        while True:
            account_number = f"FN{random.randint(10000000, 99999999)}"
            if not cls.objects.filter(account_number=account_number).exists():
                return account_number

class ATMCard(models.Model):
    """ATM Card model for physical/digital cards"""
    CARD_TYPES = [
        ('DEBIT', 'Debit Card'),
        ('CREDIT', 'Credit Card'),
        ('PREPAID', 'Prepaid Card')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='atm_cards')
    account = models.ForeignKey(PaymentAccount, on_delete=models.CASCADE, related_name='cards')
    card_number = models.CharField(max_length=19, unique=True)  # Format: XXXX-XXXX-XXXX-XXXX
    card_holder_name = models.CharField(max_length=100)
    expiry_month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    expiry_year = models.PositiveSmallIntegerField(validators=[MinValueValidator(2024), MaxValueValidator(2030)])
    cvv_hash = models.CharField(max_length=64)  # SHA-256 hash
    pin_hash = models.CharField(max_length=64)  # SHA-256 hash
    card_type = models.CharField(max_length=20, choices=CARD_TYPES, default='DEBIT')
    daily_withdrawal_limit = models.DecimalField(max_digits=12, decimal_places=2, default=50000.00)
    daily_transaction_limit = models.DecimalField(max_digits=12, decimal_places=2, default=100000.00)
    is_active = models.BooleanField(default=True)
    is_blocked = models.BooleanField(default=False)
    is_lost = models.BooleanField(default=False)
    issued_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-issued_at']
    
    def __str__(self):
        return f"{self.card_number[-4:]} - {self.user.username}"
    
    def set_pin(self, pin):
        """Set PIN with hashing"""
        if len(pin) != 4 or not pin.isdigit():
            raise ValueError("PIN must be 4 digits")
        self.pin_hash = hashlib.sha256(pin.encode()).hexdigest()
    
    def verify_pin(self, pin):
        """Verify PIN"""
        return self.pin_hash == hashlib.sha256(pin.encode()).hexdigest()
    
    def mask_card_number(self):
        """Return masked card number"""
        return f"****-****-****-{self.card_number[-4:]}"

class PaymentIntent(models.Model):
    """Payment intent/order before processing"""
    PAYMENT_METHODS = [
        ('CARD', 'Credit/Debit Card'),
        ('UPI', 'UPI'),
        ('NETBANKING', 'Net Banking'),
        ('WALLET', 'Wallet'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('CASH', 'Cash'),
        ('AUTO', 'Auto Payment'),
        # System-generated credits
        ('REFUND', 'Refund'),
        ('TOPUP', 'Top-up'),
        ('DEPOSIT', 'Deposit'),
    ]
    
    STATUS_CHOICES = [
        ('CREATED', 'Created'),
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
        ('REFUNDED', 'Refunded'),
        ('PARTIALLY_REFUNDED', 'Partially Refunded'),
        ('DISPUTED', 'Disputed'),
        ('CHARGEBACK', 'Chargeback')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='payment_intents')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='payment_intents')
    account = models.ForeignKey(PaymentAccount, on_delete=models.CASCADE, related_name='payment_intents')
    reference_id = models.CharField(max_length=50, unique=True, db_index=True)
    idempotency_key = models.CharField(max_length=64, blank=True, null=True, db_index=True, help_text='Idempotency key for safe retries')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    gateway = models.CharField(max_length=50, default='RAZORPAY')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='CREATED')
    description = models.TextField(blank=True)
    
    # Gateway references
    gateway_order_id = models.CharField(max_length=100, blank=True, null=True)
    gateway_payment_id = models.CharField(max_length=100, blank=True, null=True)
    
    # For UPI payments
    upi_vpa = models.CharField(max_length=100, blank=True, null=True)
    qr_code = models.TextField(blank=True, null=True)  # Base64 QR code
    
    # For card payments
    card_token = models.ForeignKey('CardToken', on_delete=models.SET_NULL, null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reference_id']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['organization', 'idempotency_key']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['organization', 'idempotency_key'],
                condition=Q(idempotency_key__isnull=False),
                name='uniq_payment_intent_idempotency_per_org',
            ),
        ]
    def mark_success(self, gateway_data=None, **kwargs):
        """Mark payment as successful.

        NOTE: Balance updates and PaymentTransaction creation are handled via signals
        to ensure idempotency and avoid double-debits.
        """
        gateway_data = gateway_data or {}
        # Allow legacy callers that pass gateway_payment_id/metadata kwargs
        gateway_payment_id = kwargs.get('gateway_payment_id') or gateway_data.get('payment_id')
        extra_metadata = kwargs.get('metadata') or {}

        self.status = 'SUCCESS'
        self.gateway_payment_id = gateway_payment_id
        self.completed_at = timezone.now()
        self.metadata.update({
            'gateway_response': gateway_data,
            'completed_at': self.completed_at.isoformat(),
        })
        if isinstance(extra_metadata, dict) and extra_metadata:
            self.metadata.update(extra_metadata)

        self.save(update_fields=['status', 'gateway_payment_id', 'completed_at', 'metadata', 'updated_at'])
    
    def mark_failed(self, error_message):
        """Mark payment as failed"""
        self.status = 'FAILED'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()
    
    @classmethod
    def generate_reference_id(cls):
        """Generate unique reference ID"""
        import random
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_str = str(random.randint(1000, 9999))
        return f"FN{timestamp}{random_str}"

class PaymentTransaction(models.Model):
    """Record of completed payment transactions"""
    TRANSACTION_TYPES = [
        ('DEBIT', 'Debit'),
        ('CREDIT', 'Credit'),
        ('TRANSFER', 'Transfer'),
        ('REFUND', 'Refund')
    ]

    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('PENDING', 'Pending'),
        ('REFUNDED', 'Refunded'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(PaymentAccount, on_delete=models.CASCADE, related_name='transactions')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='payment_transactions')
    payment_intent = models.ForeignKey(PaymentIntent, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUCCESS')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField()
    reference = models.CharField(max_length=100, unique=True, db_index=True)
    
    # Balance tracking
    balance_before = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Categorization
    category = models.CharField(max_length=50, blank=True, null=True)
    merchant = models.CharField(max_length=200, blank=True, null=True)
    location = models.CharField(max_length=200, blank=True, null=True)
    
    # Fraud detection
    is_suspicious = models.BooleanField(default=False)
    fraud_score = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    fraud_reason = models.TextField(blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    transaction_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-transaction_date']
        indexes = [
            models.Index(fields=['reference']),
            models.Index(fields=['account', 'transaction_date']),
            models.Index(fields=['category', 'transaction_date']),
        ]
    
    def __str__(self):
        return f"{self.reference} - {self.transaction_type} ₹{self.amount}"
    
    @classmethod
    def create_from_payment_intent(cls, payment_intent):
        """Create transaction from successful payment intent"""
        transaction = cls.objects.create(
            account=payment_intent.account,
            payment_intent=payment_intent,
            transaction_type='DEBIT',
            amount=payment_intent.amount,
            description=payment_intent.description or 'Payment',
            reference=payment_intent.reference_id,
            balance_before=payment_intent.account.balance + payment_intent.amount,
            balance_after=payment_intent.account.balance,
            category=payment_intent.metadata.get('category'),
            merchant=payment_intent.metadata.get('merchant'),
            metadata=payment_intent.metadata
        )
        return transaction

class ATMTransaction(models.Model):
    """ATM-specific transactions"""
    TRANSACTION_TYPES = [
        ('WITHDRAWAL', 'Cash Withdrawal'),
        ('DEPOSIT', 'Cash Deposit'),
        ('BALANCE_INQUIRY', 'Balance Inquiry'),
        ('MINI_STATEMENT', 'Mini Statement'),
        ('PIN_CHANGE', 'PIN Change'),
        ('FUND_TRANSFER', 'Fund Transfer')
    ]
    
    STATUS_CHOICES = [
        ('INITIATED', 'Initiated'),
        ('PROCESSING', 'Processing'),
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='atm_transactions')
    atm_card = models.ForeignKey(ATMCard, on_delete=models.SET_NULL, null=True, blank=True)
    account = models.ForeignKey(PaymentAccount, on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='INITIATED')
    
    # ATM Details
    atm_id = models.CharField(max_length=50)
    atm_location = models.CharField(max_length=255)
    terminal_id = models.CharField(max_length=50, blank=True, null=True)
    
    # Receipt Information
    receipt_number = models.CharField(max_length=50, unique=True)
    available_balance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    # Security
    is_fraudulent = models.BooleanField(default=False)
    verification_method = models.CharField(max_length=50, blank=True, null=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"ATM {self.transaction_type} - {self.receipt_number}"
    
    def mark_success(self, available_balance=None):
        """Mark ATM transaction as successful"""
        self.status = 'SUCCESS'
        if available_balance:
            self.available_balance = available_balance
        self.save()
    
    def mark_failed(self, reason=None):
        """Mark ATM transaction as failed"""
        self.status = 'FAILED'
        if reason:
            self.metadata['failure_reason'] = reason
        self.save()
    
    @classmethod
    def generate_receipt_number(cls):
        """Generate unique receipt number"""
        import random
        timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
        random_str = str(random.randint(100, 999))
        return f"ATM{timestamp}{random_str}"

class VirtualCard(models.Model):
    """Virtual card for online payments"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='virtual_cards')
    account = models.ForeignKey(PaymentAccount, on_delete=models.CASCADE, related_name='virtual_cards')
    card_number = models.CharField(max_length=19, unique=True)
    card_holder_name = models.CharField(max_length=100)
    expiry_month = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(12)])
    expiry_year = models.PositiveSmallIntegerField(validators=[MinValueValidator(2024), MaxValueValidator(2030)])
    cvv_hash = models.CharField(max_length=64)
    card_type = models.CharField(max_length=20, choices=ATMCard.CARD_TYPES, default='DEBIT')
    
    # Limits
    daily_limit = models.DecimalField(max_digits=12, decimal_places=2, default=50000.00)
    per_transaction_limit = models.DecimalField(max_digits=12, decimal_places=2, default=20000.00)
    total_limit = models.DecimalField(max_digits=12, decimal_places=2, default=100000.00)
    
    # Security
    is_active = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False)
    allow_international = models.BooleanField(default=False)
    allow_online = models.BooleanField(default=True)
    allow_pos = models.BooleanField(default=False)
    
    # Usage tracking
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    total_spent = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Virtual Card {self.card_number[-4:]} - {self.user.username}"
    
    def can_use(self, amount, transaction_type='ONLINE'):
        """Check if virtual card can be used for transaction"""
        if not self.is_active or self.is_locked:
            return False
        
        # Check transaction type permissions
        if transaction_type == 'ONLINE' and not self.allow_online:
            return False
        if transaction_type == 'INTERNATIONAL' and not self.allow_international:
            return False
        
        # Check limits
        today = timezone.now().date()
        today_spent = sum(
            (
                transaction.amount or Decimal('0.00')
                for transaction in PaymentTransaction.objects.filter(
                    account__user=self.user,
                    transaction_date__date=today,
                )
                if str(((transaction.metadata or {}) if isinstance(transaction.metadata, dict) else {}).get('virtual_card_id', '')) == str(self.id)
            ),
            Decimal('0.00'),
        )
        
        if abs(today_spent) + Decimal(amount) > self.daily_limit:
            return False
        
        if Decimal(amount) > self.per_transaction_limit:
            return False
        
        if self.total_spent + Decimal(amount) > self.total_limit:
            return False
        
        return True

class CardToken(models.Model):
    """Tokenized card information for recurring payments"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='card_tokens')
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='card_tokens')
    gateway = models.CharField(max_length=50)
    token = models.CharField(max_length=200, unique=True)
    card_type = models.CharField(max_length=20, choices=ATMCard.CARD_TYPES)
    
    # Masked card info
    last4 = models.CharField(max_length=4)
    brand = models.CharField(max_length=20)  # VISA, MASTERCARD, etc.
    expiry_month = models.PositiveSmallIntegerField()
    expiry_year = models.PositiveSmallIntegerField()
    issuer = models.CharField(max_length=100, blank=True, null=True)
    
    # Status
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # Security
    encrypted_data = models.TextField(blank=True, null=True)  # Encrypted card details
    fingerprint = models.CharField(max_length=64, blank=True, null=True)  # Device fingerprint
    
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'token']
    
    def __str__(self):
        return f"{self.brand} ****{self.last4} - {self.user.username}"
    
    def mask(self):
        """Return masked card info"""
        return {
            'last4': self.last4,
            'brand': self.brand,
            'expiry': f"{self.expiry_month:02d}/{self.expiry_year}",
            'issuer': self.issuer
        }


class UPIID(models.Model):
    """UPI ID for payments (dummy-ready)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='upi_ids')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='upi_ids')
    upi_id = models.CharField(max_length=120)

    provider = models.CharField(max_length=50, blank=True, null=True)  # e.g., okhdfcbank, okaxis
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_verified = models.BooleanField(default=True)  # dummy verification

    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['user', 'upi_id', 'organization']

    def __str__(self):
        return f"{self.upi_id} - {self.user.username}"

class Subscription(models.Model):
    """Recurring subscription model"""
    FREQUENCY_CHOICES = [
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('YEARLY', 'Yearly')
    ]
    
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('PAUSED', 'Paused'),
        ('CANCELLED', 'Cancelled'),
        ('EXPIRED', 'Expired'),
        ('FAILED', 'Failed')
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='subscriptions')
    account = models.ForeignKey(PaymentAccount, on_delete=models.CASCADE, related_name='subscriptions')
    
    # Subscription details
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='MONTHLY')
    
    # Billing details
    start_date = models.DateField()
    next_billing_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Payment method
    payment_method = models.CharField(max_length=20, choices=PaymentIntent.PAYMENT_METHODS, default='CARD')
    card_token = models.ForeignKey(CardToken, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Retry logic
    max_retries = models.PositiveIntegerField(default=3)
    retry_count = models.PositiveIntegerField(default=0)
    last_retry_at = models.DateTimeField(null=True, blank=True)
    
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - ₹{self.amount}/{self.frequency} - {self.user.username}"
    
    def calculate_next_billing_date(self):
        """Calculate next billing date based on frequency"""
        from dateutil.relativedelta import relativedelta
        
        if self.frequency == 'DAILY':
            return self.next_billing_date + relativedelta(days=1)
        elif self.frequency == 'WEEKLY':
            return self.next_billing_date + relativedelta(weeks=1)
        elif self.frequency == 'MONTHLY':
            return self.next_billing_date + relativedelta(months=1)
        elif self.frequency == 'QUARTERLY':
            return self.next_billing_date + relativedelta(months=3)
        elif self.frequency == 'YEARLY':
            return self.next_billing_date + relativedelta(years=1)
        return self.next_billing_date
    
    def cancel(self):
        """Cancel subscription"""
        self.status = 'CANCELLED'
        self.save()
    
    def process_payment(self):
        """Process subscription payment"""
        try:
            # Create payment intent
            payment_intent = PaymentIntent.objects.create(
                user=self.user,
                account=self.account,
                amount=self.amount,
                payment_method=self.payment_method,
                description=f"Subscription: {self.name}",
                metadata={
                    'subscription_id': str(self.id),
                    'frequency': self.frequency
                }
            )
            
            # Process payment based on payment method
            if self.payment_method == 'CARD' and self.card_token:
                # Process card payment via gateway
                # This would integrate with Razorpay/Stripe
                pass
            
            # Update next billing date on success
            if payment_intent.status == 'SUCCESS':
                self.next_billing_date = self.calculate_next_billing_date()
                self.retry_count = 0
                self.save()
                return True
            else:
                self.retry_count += 1
                self.last_retry_at = timezone.now()
                self.save()
                return False
                
        except Exception as e:
            self.retry_count += 1
            self.last_retry_at = timezone.now()
            self.save()
            return False
