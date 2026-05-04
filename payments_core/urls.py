from django.urls import path
from . import views, webhooks

app_name = 'payments'

urlpatterns = [
    # Main Dashboard (integrated)
    path('', views.integrated_payment_dashboard, name='payment_dashboard'),

    # ATM Simulation - redirects to dashboard (backward compat)
    # LEGACY (Phase 2): path('atm/', views.atm_simulation, name='atm_simulation'),

    # Payment Processing (POST-only API endpoint)
    # LEGACY (Phase 2): path('process/', views.process_integrated_payment, name='process_payment'),

    # Money Transfer (UPI-style)
    path('transfer/', views.transfer_money, name='transfer_money'),

    # Status
    path('status/<str:reference_id>/', views.payment_status, name='payment_status'),
    path('status/<str:reference_id>/simulate/', views.simulate_payment_action, name='simulate_payment_action'),

    # Finance Integration - sync only (no redirect proxy pages)
    path('finance/sync/', views.sync_payment_expenses, name='sync_payments'),

    # Autopilot execute action only
    path('autopilot/execute/', views.execute_smart_autopilot, name='execute_autopilot'),

    # Payment Methods Management
    path('methods/', views.payment_methods, name='payment_methods'),
    path('methods/card/add/', views.add_card, name='add_card'),
    path('methods/card/<uuid:card_id>/remove/', views.remove_card, name='remove_card'),
    path('methods/card/<uuid:card_id>/default/', views.set_default_card, name='set_default_card'),
    path('methods/upi/add/', views.add_upi, name='add_upi'),
    path('methods/upi/<uuid:upi_id>/remove/', views.remove_upi, name='remove_upi'),
    path('methods/upi/<uuid:upi_id>/default/', views.set_default_upi, name='set_default_upi'),

    # Subscriptions
    path('subscriptions/', views.subscription_list, name='subscription_list'),
    path('subscriptions/create/', views.create_subscription, name='create_subscription'),
    path('subscriptions/<uuid:subscription_id>/cancel/', views.cancel_subscription, name='cancel_subscription'),

    # Payment History
    path('history/', views.payment_history, name='payment_history'),

    # Webhooks
    path('webhook/<str:gateway>/', views.payment_webhook, name='payment_webhook'),
    path('receipt/<str:reference_id>/', views.download_receipt, name='download_receipt'),
    path('webhook/razorpay/', webhooks.razorpay_webhook, name='razorpay_webhook'),
    path('webhook/stripe/', webhooks.stripe_webhook, name='stripe_webhook'),
    path('webhook/upi/', webhooks.upi_webhook, name='upi_webhook'),
]