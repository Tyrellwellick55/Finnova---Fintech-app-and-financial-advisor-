# urls.py
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from .views import (
    LoginView, SignupView, logout_view,
    ProfileView, DashboardView, LandingView,
    AboutView, ContactView, settings_view,
    get_user_stats, update_user_preferences,
    onboarding, kyc_upload, change_password,
    handler404, handler500, handler403,
    org_select, set_org, clear_org, org_create, privacy_policy, terms_of_service, faq,
    activity_feed, redirect_to_dashboard, ops_console
)

from .admin_console import (
    org_settings as admin_org_settings,
    org_members as admin_org_members,
    org_policies as admin_org_policies,
)

urlpatterns = [
    path('', LandingView.as_view(), name='landing'),
    path('home/', redirect_to_dashboard, name='home'),
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('activity/', activity_feed, name='activity_feed'),
    path('ops/', ops_console, name='ops_console'),
    path('login/', LoginView.as_view(), name='login'),
    path('signup/', SignupView.as_view(), name='signup'),
    path('logout/', logout_view, name='logout'),
    path('onboarding/', onboarding, name='onboarding'),
    path('kyc/', kyc_upload, name='kyc_upload'),
    path('change-password/', change_password, name='change_password'),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('about/', AboutView.as_view(), name='about'),
    path('contact/', ContactView.as_view(), name='contact'),
    path('settings/', settings_view, name='settings'),

    # B2B workspace
    path('org/select/', org_select, name='org_select'),
    path('org/select/personal/', clear_org, name='clear_org'),
    path('org/select/<uuid:org_id>/', set_org, name='set_org'),
    path('org/create/', org_create, name='org_create'),
    path('org/settings/', admin_org_settings, name='org_settings'),
    path('org/members/', admin_org_members, name='org_members'),
    path('org/policies/', admin_org_policies, name='org_policies'),
    path(
        'password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='finnovaapp/registration/password_reset_form.html',
            success_url=reverse_lazy('finnovaapp:password_reset_done'),
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
        ),
        name='password_reset',
    ),
    path(
        'password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='finnovaapp/registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='finnovaapp/registration/password_reset_confirm.html',
            success_url=reverse_lazy('finnovaapp:password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='finnovaapp/registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
    
    # API endpoints
    path('api/user-stats/', get_user_stats, name='user_stats'),
    path('api/update-preferences/', update_user_preferences, name='update_preferences'),
    path('legal/privacy/', privacy_policy, name='privacy_policy'),
    path('legal/terms/', terms_of_service, name='terms_of_service'),
    path('faq/', faq, name='faq'),
]

# Error handlers
handler404 = 'finnovaapp.views.handler404'
handler500 = 'finnovaapp.views.handler500'
handler403 = 'finnovaapp.views.handler403'
