from django.urls import path
from . import views

app_name = 'agency'

urlpatterns = [
    # Control Tower
    path('', views.control_tower, name='control_tower'),
    path('control-tower/', views.control_tower, name='control_tower'),

    # Clients
    path('clients/', views.clients_list, name='clients_list'),
    path('clients/new/', views.client_create, name='client_create'),
    path('clients/<uuid:client_id>/edit/', views.client_edit, name='client_edit'),

    # Projects
    path('projects/', views.projects_list, name='projects_list'),
    path('projects/new/', views.project_create, name='project_create'),
    path('projects/<uuid:project_id>/edit/', views.project_edit, name='project_edit'),

    # Receivables / Invoices
    path('receivables/', views.receivables_dashboard, name='receivables_dashboard'),
    path('receivables/new/', views.invoice_create, name='invoice_create'),
    path('receivables/generate-retainers/', views.generate_retainer_invoices, name='generate_retainer_invoices'),
    path('receivables/<uuid:invoice_id>/edit/', views.invoice_edit, name='invoice_edit'),
    path('receivables/<uuid:invoice_id>/paid/', views.invoice_mark_paid, name='invoice_mark_paid'),
    path('receivables/<uuid:invoice_id>/send/', views.invoice_send, name='invoice_send'),
    path('receivables/<uuid:invoice_id>/remind/', views.invoice_remind, name='invoice_remind'),
    path('receivables/<uuid:invoice_id>/pdf/', views.invoice_pdf, name='invoice_pdf'),
    path('receivables/<uuid:invoice_id>/pay/', views.invoice_pay, name='invoice_pay'),

    # Client portal (VIEWER)
    path('portal/invoices/', views.client_invoice_list, name='client_invoice_list'),
    path('portal/invoices/<uuid:invoice_id>/', views.client_invoice_detail, name='client_invoice_detail'),
    path('portal/invoices/<uuid:invoice_id>/pay/', views.client_invoice_pay, name='client_invoice_pay'),
]
