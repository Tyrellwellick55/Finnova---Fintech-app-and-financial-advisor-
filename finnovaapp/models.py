# finnovaapp/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
import uuid

class CustomUser(AbstractUser):
    """Extended User model with financial attributes"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone = models.CharField(max_length=15, blank=True, null=True)
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    kyc_status = models.CharField(
        max_length=20,
        choices=[
            ('NOT_STARTED', 'Not Started'),
            ('PENDING', 'Pending Verification'),
            ('VERIFIED', 'Verified'),
            ('REJECTED', 'Rejected')
        ],
        default='NOT_STARTED'
    )
    risk_level = models.CharField(
        max_length=20,
        choices=[
            ('LOW', 'Low Risk'),
            ('MEDIUM', 'Medium Risk'),
            ('HIGH', 'High Risk')
        ],
        default='LOW'
    )
    preferred_currency = models.CharField(max_length=3, default='INR')
    language = models.CharField(max_length=10, default='en')
    timezone = models.CharField(max_length=50, default='Asia/Kolkata')
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        db_table = 'auth_user'
        verbose_name = 'User'
        verbose_name_plural = 'Users'
    
    def __str__(self):
        return f"{self.username} ({self.email})"

class UserProfile(models.Model):
    """Extended user profile information"""
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='profile')
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=10,
        choices=[
            ('MALE', 'Male'),
            ('FEMALE', 'Female'),
            ('OTHER', 'Other'),
            ('PREFER_NOT', 'Prefer not to say')
        ],
        null=True,
        blank=True
    )
    address = models.TextField(blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    pincode = models.CharField(max_length=10, blank=True, null=True)
    occupation = models.CharField(max_length=100, blank=True, null=True)
    annual_income = models.DecimalField(
        max_digits=12, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Annual income in preferred currency"
    )
    profile_image = models.ImageField(upload_to='profiles/', null=True, blank=True)
    bio = models.TextField(blank=True, null=True)
    
    # Financial preferences
    investment_experience = models.CharField(
        max_length=20,
        choices=[
            ('BEGINNER', 'Beginner'),
            ('INTERMEDIATE', 'Intermediate'),
            ('ADVANCED', 'Advanced')
        ],
        default='BEGINNER'
    )
    financial_goals = models.JSONField(default=list, blank=True)
    notification_preferences = models.JSONField(default=dict, blank=True)
    onboarding_completed = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def metadata(self):
        """
        Backward-compatible metadata proxy.
        A number of views/templates store onboarding and preference data on the
        related user record, but access it through profile.metadata.
        """
        return (self.user.metadata or {}) if self.user_id else {}

    @metadata.setter
    def metadata(self, value):
        if self.user_id:
            self.user.metadata = value or {}
            self._metadata_dirty = True

    def save(self, *args, **kwargs):
        should_save_user = bool(getattr(self, "_metadata_dirty", False))
        user_update_fields = kwargs.pop("user_update_fields", None)
        super().save(*args, **kwargs)
        if should_save_user and self.user_id and self.user_id == getattr(self.user, "pk", None):
            self._metadata_dirty = False
            self.user.save(update_fields=user_update_fields or ["metadata"])
     
    def __str__(self):
        return f"Profile of {self.user.username}"

class LoginHistory(models.Model):
    """Track user login history for security"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='login_history', null=True, blank=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    location = models.CharField(max_length=255, blank=True, null=True)
    login_time = models.DateTimeField(auto_now_add=True)
    success = models.BooleanField(default=True)
    failure_reason = models.CharField(max_length=255, blank=True, null=True)
    session_id = models.CharField(max_length=100, blank=True, null=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        verbose_name_plural = 'Login Histories'
        ordering = ['-login_time']
    
    def __str__(self):
        status = "Success" if self.success else "Failed"
        username = self.user.username if self.user else "Unknown/Failed"
        return f"{username} - {self.login_time.date()} - {status}"

class UserSession(models.Model):
    """Active user sessions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='sessions')
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-last_activity']
    
    def __str__(self):
        return f"{self.user.username} - Active: {self.is_active}"


# =====================
# B2B / MULTI-TENANCY
# =====================

class Organization(models.Model):
    """A business/workspace (B2B tenant)."""

    SEGMENT_AGENCY = 'AGENCY'
    SEGMENT_CA_FIRM = 'CA_FIRM'
    SEGMENT_CLINIC = 'CLINIC'
    SEGMENT_COACHING = 'COACHING'

    SEGMENT_CHOICES = [
        (SEGMENT_AGENCY, 'Agency / Service SME'),
        (SEGMENT_CA_FIRM, 'CA / Bookkeeping Firm'),
        (SEGMENT_CLINIC, 'Clinic / Healthcare Center'),
        (SEGMENT_COACHING, 'Coaching Institute'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=180)
    legal_name = models.CharField(max_length=220, blank=True, null=True)
    industry = models.CharField(max_length=120, blank=True, null=True)
    segment = models.CharField(max_length=20, choices=SEGMENT_CHOICES, blank=True, null=True)
    country = models.CharField(max_length=80, default='India')
    state = models.CharField(max_length=80, blank=True, null=True)
    city = models.CharField(max_length=80, blank=True, null=True)
    gstin = models.CharField(max_length=20, blank=True, null=True)
    pan = models.CharField(max_length=20, blank=True, null=True)

    is_active = models.BooleanField(default=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


class OrganizationMembership(models.Model):
    ROLE_OWNER = 'OWNER'
    ROLE_FINANCE = 'FINANCE'
    ROLE_OPERATIONS = 'OPERATIONS'
    ROLE_VIEWER = 'VIEWER'

    ROLE_CHOICES = [
        (ROLE_OWNER, 'Owner/Admin'),
        (ROLE_FINANCE, 'Finance'),
        (ROLE_OPERATIONS, 'Operations'),
        (ROLE_VIEWER, 'Viewer'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='org_memberships')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_OWNER)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('organization', 'user')]
        ordering = ['-joined_at']

    def __str__(self) -> str:
        return f"{self.user.username} @ {self.organization.name} ({self.role})"


class OrganizationInvitation(models.Model):
    """Invite a teammate to an organization."""
    STATUS_PENDING = 'PENDING'
    STATUS_ACCEPTED = 'ACCEPTED'
    STATUS_REVOKED = 'REVOKED'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='invitations')
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=OrganizationMembership.ROLE_CHOICES, default=OrganizationMembership.ROLE_VIEWER)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    status = models.CharField(
        max_length=20,
        choices=[
            (STATUS_PENDING, 'Pending'),
            (STATUS_ACCEPTED, 'Accepted'),
            (STATUS_REVOKED, 'Revoked'),
        ],
        default=STATUS_PENDING,
    )
    invited_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_org_invites')
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['email', 'status'])]

    def __str__(self) -> str:
        return f"Invite {self.email} -> {self.organization.name} ({self.status})"

class OrganizationPolicy(models.Model):
    """Organization-level controls and defaults (policy center)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='policy')

    # Approvals / thresholds
    approval_required = models.BooleanField(default=True)
    max_autopay_amount = models.DecimalField(max_digits=12, decimal_places=2, default=25000)
    transfer_approval_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=50000)

    # Notifications defaults
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    metadata = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Policy — {self.organization.name}"
