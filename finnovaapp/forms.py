import logging
logger = logging.getLogger(__name__)
# finnovaapp/forms.py
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth import get_user_model
from .models import (
    UserProfile,
    LoginHistory,
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationPolicy,
)
import re

User = get_user_model()

class CustomUserCreationForm(UserCreationForm):
    """Custom user registration form"""
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address'
        })
    )
    phone = forms.CharField(
        max_length=15,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your phone number'
        })
    )
    accept_terms = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'phone', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Choose a username'
            }),
        }
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        # Basic phone validation
        if not re.match(r'^\+?1?\d{9,15}$', phone):
            raise forms.ValidationError("Enter a valid phone number")
        return phone
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered")
        return email

class CustomAuthenticationForm(AuthenticationForm):
    """Custom login form"""
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username or Email'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    def clean(self):
        username = self.cleaned_data.get('username')
        
        # Allow login with email or username
        if '@' in username:
            try:
                user = User.objects.get(email=username)
                self.cleaned_data['username'] = user.username
            except User.DoesNotExist:
                pass
        
        return super().clean()

class UserUpdateForm(forms.ModelForm):
    """Update user basic information"""
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'email', 'phone')
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
        }
    
    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone and not re.match(r'^\+?1?\d{9,15}$', phone):
            raise forms.ValidationError("Enter a valid phone number")
        return phone

class ProfileUpdateForm(forms.ModelForm):
    """Update user profile information"""
    class Meta:
        model = UserProfile
        fields = ('date_of_birth', 'gender', 'address', 'city', 'state', 
                  'country', 'pincode', 'occupation', 'annual_income',
                  'profile_image', 'bio', 'investment_experience')
        widgets = {
            'date_of_birth': forms.DateInput(
                attrs={'class': 'form-control', 'type': 'date'}
            ),
            'gender': forms.Select(attrs={'class': 'form-control'}),
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            }),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'pincode': forms.TextInput(attrs={'class': 'form-control'}),
            'occupation': forms.TextInput(attrs={'class': 'form-control'}),
            'annual_income': forms.NumberInput(attrs={'class': 'form-control'}),
            'profile_image': forms.FileInput(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4
            }),
            'investment_experience': forms.Select(attrs={'class': 'form-control'}),
        }

class KYCDocumentForm(forms.Form):
    """KYC document upload form"""
    DOCUMENT_TYPES = [
        ('PAN', 'PAN Card'),
        ('AADHAAR', 'Aadhaar Card'),
        ('PASSPORT', 'Passport'),
        ('DRIVING_LICENSE', 'Driving License'),
        ('VOTER_ID', 'Voter ID')
    ]
    
    document_type = forms.ChoiceField(
        choices=DOCUMENT_TYPES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    document_number = forms.CharField(
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    front_image = forms.ImageField(
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    back_image = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    selfie_image = forms.ImageField(
        widget=forms.FileInput(attrs={'class': 'form-control'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        document_type = cleaned_data.get('document_type')
        document_number = cleaned_data.get('document_number')
        
        # Validate document numbers based on type
        if document_type == 'PAN':
            if not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]{1}$', document_number):
                raise forms.ValidationError({
                    'document_number': 'Invalid PAN number format'
                })
        elif document_type == 'AADHAAR':
            if not re.match(r'^\d{12}$', document_number):
                raise forms.ValidationError({
                    'document_number': 'Invalid Aadhaar number (should be 12 digits)'
                })
        
        return cleaned_data

class PasswordChangeForm(forms.Form):
    """Password change form"""
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Current password'
        })
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New password'
        })
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm new password'
        })
    )
    
    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
    
    def clean_current_password(self):
        current_password = self.cleaned_data.get('current_password')
        if not self.user.check_password(current_password):
            raise forms.ValidationError("Current password is incorrect")
        return current_password
    
    def clean(self):
        cleaned_data = super().clean()
        new_password = cleaned_data.get('new_password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if new_password and confirm_password and new_password != confirm_password:
            raise forms.ValidationError({
                'confirm_password': "Passwords don't match"
            })
        
        # Password strength validation
        if new_password:
            if len(new_password) < 8:
                raise forms.ValidationError({
                    'new_password': "Password must be at least 8 characters long"
                })
            if not re.search(r'[A-Z]', new_password):
                raise forms.ValidationError({
                    'new_password': "Password must contain at least one uppercase letter"
                })
            if not re.search(r'[a-z]', new_password):
                raise forms.ValidationError({
                    'new_password': "Password must contain at least one lowercase letter"
                })
            if not re.search(r'[0-9]', new_password):
                raise forms.ValidationError({
                    'new_password': "Password must contain at least one number"
                })

        return cleaned_data


# =====================
# B2B / ORG FORMS
# =====================


class OrganizationCreateForm(forms.ModelForm):
    """Create a new organization/workspace."""

    class Meta:
        model = Organization
        fields = ('name', 'segment', 'legal_name', 'industry', 'city', 'state', 'gstin', 'pan')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Workspace name'}),
            'segment': forms.Select(attrs={'class': 'form-control'}),
            'legal_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Legal name (optional)'}),
            'industry': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Industry (e.g., Agency)'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'gstin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'GSTIN (optional)'}),
            'pan': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'PAN (optional)'}),
        }

class TwoFactorSetupForm(forms.Form):
    """Two-factor authentication setup form"""
    method = forms.ChoiceField(
        choices=[
            ('SMS', 'SMS (Text Message)'),
            ('EMAIL', 'Email'),
            ('AUTH_APP', 'Authenticator App'),
        ],
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'})
    )
    phone = forms.CharField(
        max_length=15,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        method = cleaned_data.get('method')
        
        if method == 'SMS' and not cleaned_data.get('phone'):
            raise forms.ValidationError({
                'phone': "Phone number is required for SMS 2FA"
            })
        elif method == 'EMAIL' and not cleaned_data.get('email'):
            raise forms.ValidationError({
                'email': "Email is required for Email 2FA"
            })
        
        return cleaned_data


# =====================
# Org Admin Console
# =====================

class OrganizationSettingsForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'legal_name', 'industry', 'segment', 'country', 'state', 'city', 'gstin', 'pan']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'legal_name': forms.TextInput(attrs={'class': 'form-control'}),
            'industry': forms.TextInput(attrs={'class': 'form-control'}),
            'segment': forms.Select(attrs={'class': 'form-select'}),
            'country': forms.TextInput(attrs={'class': 'form-control'}),
            'state': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'gstin': forms.TextInput(attrs={'class': 'form-control'}),
            'pan': forms.TextInput(attrs={'class': 'form-control'}),
        }


class OrganizationPolicyForm(forms.ModelForm):
    class Meta:
        model = OrganizationPolicy
        fields = ['approval_required', 'max_autopay_amount', 'transfer_approval_threshold', 'quiet_hours_start', 'quiet_hours_end']
        widgets = {
            'approval_required': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'max_autopay_amount': forms.NumberInput(attrs={'class': 'form-control'}),
            'transfer_approval_threshold': forms.NumberInput(attrs={'class': 'form-control'}),
            'quiet_hours_start': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'quiet_hours_end': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
        }


class InviteMemberForm(forms.ModelForm):
    class Meta:
        model = OrganizationInvitation
        fields = ['email', 'role']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'teammate@company.com'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
        }


class UpdateMemberRoleForm(forms.Form):
    membership_id = forms.UUIDField(widget=forms.HiddenInput())
    role = forms.ChoiceField(choices=OrganizationMembership.ROLE_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
