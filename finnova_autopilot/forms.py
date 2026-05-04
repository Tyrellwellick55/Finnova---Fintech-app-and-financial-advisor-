from datetime import date, timedelta

from django import forms

from finance.models import Account

from .models import SavingsGoal, SmartBill


class SmartBillForm(forms.ModelForm):
    class Meta:
        model = SmartBill
        fields = [
            "biller_name",
            "biller_category",
            "amount",
            "due_date",
            "is_recurring",
            "recurrence_pattern",
            "auto_pay",
            "auto_pay_days_before",
            "bill_number",
            "consumer_number",
            "bill_period",
            "auto_pay_account",
        ]
        widgets = {
            "biller_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Biller name"}),
            "biller_category": forms.Select(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "is_recurring": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "recurrence_pattern": forms.Select(attrs={"class": "form-control"}),
            "auto_pay": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "auto_pay_days_before": forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "30"}),
            "bill_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Bill number"}),
            "consumer_number": forms.TextInput(attrs={"class": "form-control", "placeholder": "Consumer number"}),
            "bill_period": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., Jan 2026"}),
            "auto_pay_account": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["auto_pay_account"].queryset = Account.objects.filter(user=user, is_active=True)
        self.fields["auto_pay_days_before"].initial = 2
        self.fields["due_date"].initial = date.today()

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("auto_pay") and not cleaned_data.get("auto_pay_account"):
            raise forms.ValidationError({"auto_pay_account": "Auto-pay account is required when auto-pay is enabled."})
        return cleaned_data


class SavingsGoalForm(forms.ModelForm):
    class Meta:
        model = SavingsGoal
        fields = [
            "goal_name",
            "target_amount",
            "target_date",
            "priority",
            "suggested_monthly_saving",
            "savings_day",
            "is_auto_save",
            "auto_save_account",
        ]
        widgets = {
            "goal_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Savings goal"}),
            "target_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "target_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "priority": forms.Select(attrs={"class": "form-control"}),
            "suggested_monthly_saving": forms.NumberInput(
                attrs={"class": "form-control", "min": "0", "step": "0.01"}
            ),
            "savings_day": forms.NumberInput(attrs={"class": "form-control", "min": "1", "max": "31"}),
            "is_auto_save": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "auto_save_account": forms.Select(attrs={"class": "form-control"}),
        }

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["auto_save_account"].queryset = Account.objects.filter(user=user, is_active=True)
        self.fields["savings_day"].initial = 1
        self.fields["target_date"].initial = date.today() + timedelta(days=365)

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get("is_auto_save") and not cleaned_data.get("auto_save_account"):
            raise forms.ValidationError({"auto_save_account": "Auto-save account is required when auto-save is enabled."})
        return cleaned_data
