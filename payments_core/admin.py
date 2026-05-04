# payments_core/admin.py
from django.contrib import admin
from .models import (
    PaymentAccount, ATMCard, PaymentIntent, 
    PaymentTransaction, ATMTransaction, VirtualCard, 
    CardToken, Subscription
)

@admin.register(PaymentAccount)
class PaymentAccountAdmin(admin.ModelAdmin):
    list_display = ['user', 'account_number', 'account_type', 'balance', 'is_active', 'created_at']
    list_filter = ['account_type', 'is_active', 'is_primary']
    search_fields = ['user__username', 'account_number', 'user__email']
    readonly_fields = ['created_at', 'updated_at', 'last_transaction_at']
    fieldsets = [
        ('Account Information', {
            'fields': ['user', 'account_number', 'account_type', 'balance', 'available_balance']
        }),
        ('Bank Details', {
            'fields': ['bank_name', 'bank_branch', 'ifsc_code', 'upi_id'],
            'classes': ['collapse']
        }),
        ('Limits', {
            'fields': ['min_balance', 'overdraft_limit'],
            'classes': ['collapse']
        }),
        ('Status', {
            'fields': ['is_active', 'is_primary']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at', 'last_transaction_at'],
            'classes': ['collapse']
        }),
    ]

@admin.register(ATMCard)
class ATMCardAdmin(admin.ModelAdmin):
    list_display = ['user', 'card_number_display', 'card_type', 'is_active', 'is_blocked', 'issued_at']
    list_filter = ['card_type', 'is_active', 'is_blocked']
    search_fields = ['user__username', 'card_number', 'card_holder_name']
    readonly_fields = ['issued_at', 'last_used']
    
    def card_number_display(self, obj):
        return f"**** **** **** {obj.card_number[-4:]}"
    card_number_display.short_description = 'Card Number'

@admin.register(PaymentIntent)
class PaymentIntentAdmin(admin.ModelAdmin):
    list_display = ['reference_id', 'user', 'amount', 'payment_method', 'status', 'created_at']
    list_filter = ['status', 'payment_method', 'gateway']
    search_fields = ['user__username', 'reference_id', 'gateway_order_id', 'description']
    readonly_fields = ['created_at', 'updated_at', 'completed_at']
    fieldsets = [
        ('Payment Information', {
            'fields': ['user', 'account', 'reference_id', 'amount', 'currency', 'payment_method']
        }),
        ('Gateway Details', {
            'fields': ['gateway', 'gateway_order_id', 'gateway_payment_id'],
            'classes': ['collapse']
        }),
        ('Status', {
            'fields': ['status', 'error_message']
        }),
        ('Additional Info', {
            'fields': ['description', 'card_token', 'upi_vpa', 'qr_code', 'metadata'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['created_at', 'updated_at', 'completed_at'],
            'classes': ['collapse']
        }),
    ]

@admin.register(PaymentTransaction)
class PaymentTransactionAdmin(admin.ModelAdmin):
    list_display = ['reference', 'account', 'transaction_type', 'amount', 'transaction_date']
    list_filter = ['transaction_type', 'is_suspicious']
    search_fields = ['reference', 'description', 'account__account_number']
    readonly_fields = ['transaction_date']
    fieldsets = [
        ('Transaction Details', {
            'fields': ['account', 'payment_intent', 'reference', 'transaction_type', 'amount']
        }),
        ('Descriptions', {
            'fields': ['description', 'category', 'merchant', 'location']
        }),
        ('Balance Tracking', {
            'fields': ['balance_before', 'balance_after']
        }),
        ('Fraud Detection', {
            'fields': ['is_suspicious', 'fraud_score', 'fraud_reason'],
            'classes': ['collapse']
        }),
        ('Metadata', {
            'fields': ['metadata'],
            'classes': ['collapse']
        }),
        ('Timestamp', {
            'fields': ['transaction_date']
        }),
    ]

@admin.register(ATMTransaction)
class ATMTransactionAdmin(admin.ModelAdmin):
    list_display = ['receipt_number', 'user', 'transaction_type', 'amount', 'status', 'timestamp']
    list_filter = ['transaction_type', 'status', 'is_fraudulent']
    search_fields = ['receipt_number', 'user__username', 'atm_location']
    readonly_fields = ['timestamp']

@admin.register(VirtualCard)
class VirtualCardAdmin(admin.ModelAdmin):
    list_display = ['user', 'card_number_display', 'card_type', 'is_active', 'created_at']
    list_filter = ['card_type', 'is_active', 'allow_international', 'allow_online']
    search_fields = ['user__username', 'card_number', 'card_holder_name']
    
    def card_number_display(self, obj):
        return f"**** **** **** {obj.card_number[-4:]}"
    card_number_display.short_description = 'Card Number'

@admin.register(CardToken)
class CardTokenAdmin(admin.ModelAdmin):
    list_display = ['user', 'brand', 'last4', 'expiry_month', 'expiry_year', 'is_active', 'is_default']
    list_filter = ['brand', 'is_active', 'is_default', 'gateway']
    search_fields = ['user__username', 'last4', 'token']
    readonly_fields = ['created_at', 'last_used']

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'amount', 'frequency', 'status', 'next_billing_date']
    list_filter = ['status', 'frequency', 'payment_method']
    search_fields = ['name', 'user__username', 'description']
    readonly_fields = ['created_at', 'updated_at', 'last_retry_at']
    
    def next_charge(self, obj):
        return obj.next_billing_date
    next_charge.short_description = "Next Charge"