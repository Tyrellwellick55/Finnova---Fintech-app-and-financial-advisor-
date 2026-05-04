from django.urls import path
from . import views

app_name = 'audit'

urlpatterns = [
    # Main Dashboard
    path('', views.audit_dashboard, name='dashboard'),

    # Audit Logs
    path('logs/', views.AuditLogListView.as_view(), name='log_list'),
    path('logs/<uuid:log_id>/', views.audit_log_detail, name='log_detail'),

    # Security Alerts
    path('alerts/', views.security_alerts, name='alert_list'),
    path('alerts/<uuid:alert_id>/resolve/view/', views.resolve_alert_page, name='resolve_alert'),
    path('alerts/<uuid:alert_id>/resolve/', views.mark_alert_resolved, name='mark_alert_resolved'),

    # System Controls
    path('system-controls/', views.system_controls, name='system_controls'),

    # User Management
    path('users/', views.user_management, name='user_management'),
    path('users/<uuid:user_id>/', views.user_detail, name='user_detail'),
    path('users/<uuid:user_id>/toggle-status/', views.toggle_user_status, name='toggle_user_status'),

    # User Risk Management
    path('risk/', views.user_risk_management, name='user_risk'),
    path('risk/flag/', views.flag_user_risk, name='flag_user_risk'),
    path('risk/<uuid:flag_id>/resolve/', views.resolve_risk_flag, name='resolve_risk_flag'),

    # API Endpoints
    path('api/stats/', views.get_audit_stats_api, name='api_stats'),
    path('api/export/', views.export_audit_data, name='export'),
    path('api/search/', views.search_audit_api, name='search_logs'),

    # Compliance & Reports
    path('compliance/', views.compliance_dashboard, name='compliance'),
    path('compliance/add/', views.add_compliance, name='add_compliance'),
    path('compliance/<uuid:record_id>/verify/', views.verify_compliance, name='verify_compliance'),
    path('reports/', views.generate_reports, name='reports'),

    # Integrated Monitoring
    path('monitoring/', views.integrated_monitoring, name='monitoring'),
    path('gst/', views.gst_dashboard, name='gst_dashboard'),

    path('incidents/', views.incidents, name='incidents'),
]
