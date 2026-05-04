from __future__ import annotations

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone


class Client(models.Model):
    """Agency customer / account."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, related_name='agency_clients')

    name = models.CharField(max_length=160)
    company_name = models.CharField(max_length=220, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=40, blank=True, null=True)

    billing_address = models.TextField(blank=True, null=True)
    gstin = models.CharField(max_length=20, blank=True, null=True)

    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['organization', 'is_active', 'name']),
        ]

    def __str__(self) -> str:
        return self.company_name or self.name

    @property
    def display_name(self) -> str:
        """Company name if set, otherwise contact name."""
        return self.company_name or self.name

    @property
    def invoice_count(self) -> int:
        """Total number of invoices for this client."""
        return self.invoices.count()

    @property
    def open_invoice_count(self) -> int:
        """Number of sent/overdue invoices awaiting payment."""
        return self.invoices.filter(status__in=['SENT', 'OVERDUE']).count()

    @property
    def total_billed(self) -> Decimal:
        """Lifetime total amount invoiced to this client."""
        from django.db.models import Sum
        return self.invoices.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def total_paid(self) -> Decimal:
        """Total amount collected from this client."""
        from django.db.models import Sum
        return self.invoices.filter(status='PAID').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def outstanding_amount(self) -> Decimal:
        """Total unpaid amount across sent/overdue invoices."""
        from django.db.models import Sum
        return self.invoices.filter(status__in=['SENT', 'OVERDUE']).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def active_projects_count(self) -> int:
        """Number of currently active projects for this client."""
        return self.projects.filter(status='ACTIVE').count()


class Project(models.Model):
    """Workstream / retainer project under a client."""

    STATUS_ACTIVE = 'ACTIVE'
    STATUS_PAUSED = 'PAUSED'
    STATUS_CLOSED = 'CLOSED'

    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_PAUSED, 'Paused'),
        (STATUS_CLOSED, 'Closed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, related_name='agency_projects')
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='projects')

    name = models.CharField(max_length=180)
    description = models.TextField(blank=True, null=True)

    monthly_retainer = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    monthly_budget = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)

    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['client', 'status']),
        ]

    def __str__(self) -> str:
        return f"{self.client} — {self.name}"

    @property
    def total_invoiced(self) -> Decimal:
        """Sum of all invoices raised against this project."""
        from django.db.models import Sum
        return self.invoices.aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def total_collected(self) -> Decimal:
        """Sum of paid invoices for this project."""
        from django.db.models import Sum
        return self.invoices.filter(status='PAID').aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def outstanding_amount(self) -> Decimal:
        """Unpaid amount across sent/overdue invoices for this project."""
        from django.db.models import Sum
        return self.invoices.filter(status__in=['SENT', 'OVERDUE']).aggregate(t=Sum('amount'))['t'] or Decimal('0.00')

    @property
    def is_profitable(self) -> bool:
        """True when monthly retainer exceeds monthly budget (simplified margin check)."""
        return self.monthly_retainer > self.monthly_budget


class Invoice(models.Model):
    """Receivable (invoice/retainer) tracking."""

    STATUS_DRAFT = 'DRAFT'
    STATUS_SENT = 'SENT'
    STATUS_PAID = 'PAID'
    STATUS_OVERDUE = 'OVERDUE'
    STATUS_CANCELLED = 'CANCELLED'

    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SENT, 'Sent'),
        (STATUS_PAID, 'Paid'),
        (STATUS_OVERDUE, 'Overdue'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey('finnovaapp.Organization', on_delete=models.CASCADE, related_name='agency_invoices')

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='invoices')
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices')

    invoice_number = models.CharField(max_length=50)
    title = models.CharField(max_length=200, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    issued_date = models.DateField(default=timezone.now)
    due_date = models.DateField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    reminder_count = models.PositiveIntegerField(default=0)
    paid_date = models.DateField(null=True, blank=True)
    payment_reference = models.CharField(max_length=120, blank=True, null=True)

    # Optional link to the payment intent used for this invoice (dummy payment links, receipts)
    payment_intent = models.ForeignKey('payments_core.PaymentIntent', on_delete=models.SET_NULL, null=True, blank=True, related_name='agency_invoices')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_invoices')

    notes = models.TextField(blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-due_date', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'invoice_number'], name='uniq_invoice_number_per_org'),
        ]
        indexes = [
            models.Index(fields=['organization', 'status', 'due_date']),
            models.Index(fields=['client', 'status', 'due_date']),
        ]

    def __str__(self) -> str:
        return f"{self.invoice_number} — {self.client} — ₹{self.amount}"

    @property
    def is_overdue(self) -> bool:
        if self.status in {self.STATUS_PAID, self.STATUS_CANCELLED}:
            return False
        return self.due_date < timezone.now().date()

    @property
    def days_overdue(self) -> int:
        """Number of days this invoice is past due (0 if not overdue)."""
        if not self.is_overdue:
            return 0
        return (timezone.now().date() - self.due_date).days

    @property
    def days_until_due(self) -> int:
        """Days until due date (negative means already past due)."""
        return (self.due_date - timezone.now().date()).days

    @property
    def status_display_class(self) -> str:
        """CSS class name for status badge — used in receivables_dashboard template."""
        return self.status  # Template already handles DRAFT/SENT/PAID/OVERDUE/CANCELLED

    @property
    def client_display_name(self) -> str:
        """Company name if set, otherwise contact name — DRY helper for templates."""
        return self.client.company_name or self.client.name if self.client_id else '—'

    def mark_paid(self, paid_date=None, reference: str | None = None):
        self.status = self.STATUS_PAID
        self.paid_date = paid_date or timezone.now().date()
        if reference:
            self.payment_reference = reference
        self.save(update_fields=['status', 'paid_date', 'payment_reference', 'updated_at'])


def generate_invoice_number(organization_id: uuid.UUID) -> str:
    """Simple, collision-resistant invoice number generator per org."""
    from django.db.models import Max

    prefix = 'INV'
    today = timezone.now().date().strftime('%Y%m')

    latest = Invoice.objects.filter(organization_id=organization_id, invoice_number__startswith=f"{prefix}-{today}-").aggregate(Max('invoice_number'))['invoice_number__max']
    if latest:
        try:
            last_seq = int(latest.split('-')[-1])
        except Exception:
            last_seq = 0
    else:
        last_seq = 0

    seq = last_seq + 1
    return f"{prefix}-{today}-{seq:04d}"
