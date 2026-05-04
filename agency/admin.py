from django.contrib import admin

from .models import Client, Project, Invoice


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('name', 'company_name', 'organization', 'email', 'phone', 'is_active', 'updated_at')
    list_filter = ('is_active', 'organization')
    search_fields = ('name', 'company_name', 'email', 'phone')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'client', 'organization', 'status', 'monthly_retainer', 'monthly_budget', 'updated_at')
    list_filter = ('status', 'organization')
    search_fields = ('name', 'client__name', 'client__company_name')


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('invoice_number', 'client', 'project', 'organization', 'status', 'amount', 'due_date')
    list_filter = ('status', 'organization')
    search_fields = ('invoice_number', 'client__name', 'client__company_name', 'project__name')
