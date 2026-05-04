from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "autopilot"

urlpatterns = [
    path("", views.autopilot_dashboard, name="autopilot_dashboard"),
    path("toggle/", views.toggle_autopilot, name="toggle_autopilot"),
    path("run/", views.run_automation_now, name="run_automation_now"),

    path("alerts/", views.alerts, name="alerts"),
    path("alerts/mark-all-read/", views.mark_all_alerts_read, name="mark_all_alerts_read"),
    path("alerts/<uuid:alert_id>/acknowledge/", views.acknowledge_alert, name="acknowledge_alert"),
    path("alerts/<uuid:alert_id>/delete/", views.delete_alert, name="delete_alert"),

    path("bills/", views.smart_bills, name="smart_bills"),
    path("bills/<uuid:bill_id>/edit/", views.edit_smart_bill, name="edit_smart_bill"),
    path("bills/<uuid:bill_id>/history/", views.smart_bill_history, name="smart_bill_history"),
    path("bills/<uuid:bill_id>/toggle-auto-pay/", views.toggle_autopay, name="toggle_auto_pay"),
    path("bills/<uuid:bill_id>/pay/", views.pay_bill_now, name="mark_bill_paid"),
    path("bills/<uuid:bill_id>/skip/", views.skip_bill, name="skip_bill"),

    path("rules/", views.automation_rules, name="automation_rules"),
    path("rules/<uuid:rule_id>/toggle/", views.toggle_rule, name="toggle_rule"),
    path("rules/<uuid:rule_id>/delete/", views.delete_rule, name="delete_rule"),

    path("approvals/", views.approvals, name="approvals"),
    path("approvals/<uuid:approval_id>/approve/", views.approve_request, name="approve_request"),
    path("approvals/<uuid:approval_id>/reject/", views.reject_request, name="reject_request"),

    path("settings/", views.autopilot_settings, name="autopilot_settings"),

    path("health/", views.financial_health, name="financial_health"),
    path("health/refresh/", views.refresh_financial_health, name="refresh_financial_health"),
    path(
        "health/score/",
        RedirectView.as_view(pattern_name="autopilot:financial_health", permanent=False),
        name="health_score",
    ),
    path("insights/", views.ai_insights, name="ai_insights"),

    path("patterns/", views.transaction_patterns, name="transaction_patterns"),
    path("patterns/scan/", views.scan_transaction_patterns, name="scan_transaction_patterns"),
    path("patterns/<uuid:pattern_id>/", views.pattern_detail, name="pattern_detail"),
    path("patterns/<uuid:pattern_id>/confirm/", views.confirm_pattern, name="confirm_pattern"),
    path("patterns/<uuid:pattern_id>/anomaly/", views.mark_pattern_anomaly, name="mark_pattern_anomaly"),
    path("patterns/<uuid:pattern_id>/toggle/", views.toggle_pattern, name="toggle_pattern"),

    path("income/<uuid:approval_id>/split/", views.income_split_plan, name="income_split_plan"),

    path("savings/", views.savings, name="savings"),
    path("savings/<uuid:goal_id>/", views.savings_detail, name="savings_detail"),
    path("savings/<uuid:goal_id>/add/", views.add_to_savings, name="add_to_savings"),
    path("savings/<uuid:goal_id>/withdraw/", views.withdraw_from_savings, name="withdraw_from_savings"),
    path("savings/<uuid:goal_id>/pause/", views.pause_savings_goal, name="pause_savings_goal"),
    path("savings/<uuid:goal_id>/resume/", views.resume_savings_goal, name="resume_savings_goal"),
    path("savings/<uuid:goal_id>/strategy/", views.apply_savings_strategy, name="apply_savings_strategy"),
]
