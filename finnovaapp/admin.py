# admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, UserProfile, LoginHistory, UserSession
from .forms import CustomUserCreationForm

@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    add_form = CustomUserCreationForm
    model = CustomUser
    list_display = ['username', 'email', 'phone', 'kyc_status', 'is_staff', 'is_active']
    list_filter = ['kyc_status', 'is_staff', 'is_active', 'date_joined']
    fieldsets = UserAdmin.fieldsets + (
        ('Additional Information', {
            'fields': ('phone', 'email_verified', 'phone_verified', 'kyc_status', 
                      'risk_level', 'preferred_currency', 'language', 'timezone', 'metadata')
        }),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Additional Information', {
            'fields': ('phone', 'email', 'accept_terms')
        }),
    )

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'occupation', 'annual_income', 'investment_experience']
    search_fields = ['user__username', 'user__email', 'occupation']
    list_filter = ['investment_experience', 'gender']

@admin.register(LoginHistory)
class LoginHistoryAdmin(admin.ModelAdmin):
    list_display = ['user', 'ip_address', 'login_time', 'success']
    list_filter = ['success', 'login_time']
    search_fields = ['user__username', 'ip_address']
    readonly_fields = ['login_time']

@admin.register(UserSession)
class UserSessionAdmin(admin.ModelAdmin):
    list_display = ['user', 'ip_address', 'login_time', 'last_activity', 'is_active']
    list_filter = ['is_active', 'login_time']
    search_fields = ['user__username', 'ip_address', 'session_key']
    readonly_fields = ['login_time', 'last_activity']

# End of file
