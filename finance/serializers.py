from rest_framework import serializers
from .models import (
    Income, Expense, Budget, BudgetCategory,
    FinancialGoal, FinancialReport, TaxRecord,
    Investment, Debt, FinancialMetric
)

class IncomeSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    source_display = serializers.CharField(source='get_source_display', read_only=True)
    
    class Meta:
        model = Income
        fields = [
            'id', 'user', 'source', 'category', 'category_display',
            'amount', 'currency', 'date', 'frequency', 'is_recurring',
            'tax_deducted', 'net_amount', 'description', 'is_verified',
            'created_at', 'updated_at', 'source_display'
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']

class ExpenseSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    
    class Meta:
        model = Expense
        fields = [
            'id', 'user', 'description', 'category', 'category_display',
            'amount', 'currency', 'date', 'time', 'location',
            'payment_method', 'payment_method_display', 'merchant',
            'gst_amount', 'has_receipt', 'receipt_image', 'tags',
            'predicted_category', 'is_verified', 'requires_review',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']

class BudgetSerializer(serializers.ModelSerializer):
    usage_percentage = serializers.FloatField(read_only=True)
    remaining_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_exceeded = serializers.BooleanField(read_only=True)
    is_near_limit = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Budget
        fields = [
            'id', 'user', 'name', 'description', 'amount', 'period',
            'start_date', 'end_date', 'category', 'custom_category',
            'current_spending', 'usage_percentage', 'remaining_amount',
            'alert_threshold', 'notify_on_exceed', 'notify_on_threshold',
            'is_active', 'is_archived', 'is_exceeded', 'is_near_limit',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['user', 'current_spending', 'created_at', 'updated_at']

class FinancialGoalSerializer(serializers.ModelSerializer):
    progress_percentage = serializers.FloatField(read_only=True)
    remaining_amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    months_remaining = serializers.IntegerField(read_only=True)
    required_monthly_saving = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    
    class Meta:
        model = FinancialGoal
        fields = [
            'id', 'user', 'name', 'goal_type', 'description',
            'target_amount', 'current_amount', 'progress_percentage',
            'start_date', 'target_date', 'status', 'priority',
            'remaining_amount', 'months_remaining', 'required_monthly_saving',
            'suggested_monthly_saving', 'auto_track', 'linked_account',
            'milestones', 'created_at', 'updated_at', 'achieved_at'
        ]
        read_only_fields = [
            'user', 'current_amount', 'progress_percentage', 'created_at',
            'updated_at', 'achieved_at'
        ]

class DashboardSerializer(serializers.Serializer):
    summary = serializers.DictField()
    financial_health = serializers.DictField()
    suggestions = serializers.ListField()
    insights = serializers.ListField()
    timestamp = serializers.DateTimeField()

class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialReport
        fields = '__all__'
        read_only_fields = ['user', 'generated_at', 'created_at']

class InvestmentSerializer(serializers.ModelSerializer):
    total_return = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    return_percentage = serializers.FloatField(read_only=True)
    is_performing_well = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Investment
        fields = '__all__'
        read_only_fields = ['user', 'created_at', 'updated_at']

class DebtSerializer(serializers.ModelSerializer):
    interest_paid = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    months_remaining = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = Debt
        fields = '__all__'
        read_only_fields = ['user', 'created_at', 'updated_at']

class FinancialMetricSerializer(serializers.ModelSerializer):
    class Meta:
        model = FinancialMetric
        fields = '__all__'
        read_only_fields = ['user', 'calculated_at']

class BudgetCategorySerializer(serializers.ModelSerializer):
    remaining_budget = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    usage_percentage = serializers.FloatField(read_only=True)
    
    class Meta:
        model = BudgetCategory
        fields = '__all__'
        read_only_fields = ['user', 'last_updated']

class TaxRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxRecord
        fields = '__all__'
        read_only_fields = ['user', 'created_at', 'updated_at']