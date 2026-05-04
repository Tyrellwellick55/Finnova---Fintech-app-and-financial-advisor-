# urls.py - COMPLETE AND FINAL
from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = "analytics_ai"

urlpatterns = [
    # Main Dashboard
    path('', views.ai_dashboard, name='ai_dashboard'),
    path('home/', RedirectView.as_view(pattern_name='analytics-ai:ai_dashboard', permanent=False), name='home'),
    path('report/', views.ai_report, name='ai_report'),
    
    # Predictive Analytics
    path('predictions/', views.predictive_analytics, name='predictive_analytics'),
    
    # Financial Insights
    path('insights/', views.financial_insights, name='financial_insights'),
    path('recommendations/', RedirectView.as_view(pattern_name='analytics-ai:financial_insights', permanent=False), name='recommendations'),
    path('insights/<uuid:insight_id>/', views.insight_detail, name='insight_detail'),
    
    # Settings & guided handoff to Autopilot
    path('rules/', RedirectView.as_view(pattern_name='autopilot:automation_rules', permanent=False), name='smart_rules'),
    path('autopilot/rules/', RedirectView.as_view(pattern_name='autopilot:automation_rules', permanent=False), name='autopilot_rules'),
    path('preferences/', views.ai_settings, name='ai_settings'),
    path('autopilot/settings/', RedirectView.as_view(pattern_name='analytics-ai:ai_settings', permanent=False), name='autopilot_settings'),
    path('autopilot-settings/', RedirectView.as_view(pattern_name='analytics-ai:ai_settings', permanent=False)),
    
    # Financial Health
    path('health/', views.financial_health_dashboard, name='financial_health_dashboard'),
    
    # API Endpoints
    path('api/insights/', views.ai_insights_api, name='ai_insights_api'),
    path('api/health-score/', views.get_financial_health_score, name='financial_health_score'),
    path('api/weekly-report/', views.weekly_report_api, name='weekly_report'),
    path('api/income-opportunities/', views.income_opportunities_api, name='income_opportunities'),
    path('api/execute-autopilot/', views.execute_autopilot, name='execute_autopilot'),
    path('api/realtime-analysis/', views.realtime_analysis_webhook, name='realtime_analysis'),
    path('api/predictions/', views.get_predictions, name='get_predictions'),
    path('api/status/', views.analytics_status_api, name='analytics_status'),
    path('api/freeze-spending/', views.freeze_spending, name='freeze_spending'),
    
    path('api/insights/<uuid:insight_id>/mark-read/', views.mark_insight_read, name='mark_insight_read'),
    path('chat/', views.ai_chat, name='ai_chat'),
    path('api/chat/', views.ai_chat_api, name='ai_chat_api'),

]
