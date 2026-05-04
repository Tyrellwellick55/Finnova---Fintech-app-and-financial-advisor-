from datetime import date, timedelta
from decimal import Decimal
import re

from django import forms
from django.db.models import Q

from .models import Account, Budget, Debt, Expense, FinancialGoal, Income, Investment, TaxRecord


def _scoped_accounts(user, organization=None, account_types=None):
    queryset = Account.objects.filter(user=user, is_active=True)
    if organization is None:
        queryset = queryset.filter(organization__isnull=True)
    else:
        queryset = queryset.filter(Q(organization=organization) | Q(organization__isnull=True))
    if account_types:
        queryset = queryset.filter(account_type__in=account_types)
    return queryset.order_by("-is_primary", "name")


class IncomeForm(forms.ModelForm):
    class Meta:
        model = Income
        fields = [
            "account",
            "source",
            "amount",
            "category",
            "date",
            "description",
            "is_recurring",
            "receipt",
        ]
        widgets = {
            "account": forms.Select(attrs={"class": "form-select"}),
            "source": forms.TextInput(attrs={"class": "form-control", "placeholder": "Income source"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_recurring": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "receipt": forms.FileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, user, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = _scoped_accounts(user, organization=organization)
        self.fields["date"].initial = self.instance.date if self.instance.pk else date.today()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")
        return amount


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            "account",
            "description",
            "amount",
            "category",
            "custom_category",
            "date",
            "time",
            "payment_method",
            "merchant",
            "location",
            "budget_category",
            "receipt",
        ]
        widgets = {
            "account": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control", "placeholder": "Description"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "custom_category": forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional custom category"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "time": forms.TimeInput(attrs={"class": "form-control", "type": "time"}),
            "payment_method": forms.Select(attrs={"class": "form-select"}),
            "merchant": forms.TextInput(attrs={"class": "form-control", "placeholder": "Merchant"}),
            "location": forms.TextInput(attrs={"class": "form-control", "placeholder": "Location"}),
            "budget_category": forms.Select(attrs={"class": "form-select"}),
            "receipt": forms.FileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, user, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = _scoped_accounts(user, organization=organization)
        self.fields["budget_category"].queryset = (
            self.fields["budget_category"].queryset.filter(budget__user=user, budget__is_active=True)
            .select_related("budget")
            .order_by("budget__name", "name")
        )
        self.fields["date"].initial = self.instance.date if self.instance.pk else date.today()

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get("category")
        custom_category = cleaned_data.get("custom_category")
        if category == "OTHER" and not custom_category:
            raise forms.ValidationError("Add a custom category or choose a more specific category.")
        return cleaned_data


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = [
            "name",
            "amount",
            "period",
            "start_date",
            "end_date",
            "alert_threshold",
            "is_active",
            "is_recurring",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Budget name"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "period": forms.Select(attrs={"class": "form-select"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "alert_threshold": forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "100", "step": "1"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_recurring": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["start_date"].initial = date.today().replace(day=1)
            self.fields["alert_threshold"].initial = 80

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        period = cleaned_data.get("period")
        if period == "CUSTOM" and not end_date:
            raise forms.ValidationError({"end_date": "Custom budgets need an end date."})
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError({"end_date": "End date must be after start date."})
        return cleaned_data


class FinancialGoalForm(forms.ModelForm):
    class Meta:
        model = FinancialGoal
        fields = ["name", "goal_type", "target_amount", "target_date", "priority", "linked_account", "notes"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Goal name"}),
            "goal_type": forms.Select(attrs={"class": "form-select"}),
            "target_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "target_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
            "linked_account": forms.Select(attrs={"class": "form-select"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, user, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["linked_account"].queryset = _scoped_accounts(
            user,
            organization=organization,
            account_types=["SAVINGS", "INVESTMENT", "CURRENT"],
        )
        if not self.instance.pk:
            self.fields["target_date"].initial = date.today() + timedelta(days=365)

    def clean_target_date(self):
        target_date = self.cleaned_data["target_date"]
        if target_date <= date.today():
            raise forms.ValidationError("Target date must be in the future.")
        return target_date


class InvestmentForm(forms.ModelForm):
    class Meta:
        model = Investment
        fields = [
            "account",
            "instrument",
            "name",
            "invested_amount",
            "purchase_date",
            "expected_return_rate",
            "risk_level",
            "issuer",
            "folio_number",
            "notes",
        ]
        widgets = {
            "account": forms.Select(attrs={"class": "form-select"}),
            "instrument": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "invested_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "purchase_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "expected_return_rate": forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "100", "step": "0.1"}),
            "risk_level": forms.Select(attrs={"class": "form-select"}),
            "issuer": forms.TextInput(attrs={"class": "form-control"}),
            "folio_number": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, user, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = _scoped_accounts(
            user,
            organization=organization,
            account_types=["INVESTMENT", "SAVINGS", "CURRENT"],
        )
        self.fields["purchase_date"].initial = self.instance.purchase_date if self.instance.pk else date.today()
        self.fields["expected_return_rate"].initial = self.fields["expected_return_rate"].initial or 8.0


class DebtForm(forms.ModelForm):
    class Meta:
        model = Debt
        fields = [
            "account",
            "debt_type",
            "lender",
            "principal_amount",
            "interest_rate",
            "interest_type",
            "emi_amount",
            "emi_day",
            "start_date",
            "end_date",
            "auto_pay_enabled",
            "is_secured",
            "collateral",
            "loan_account_number",
        ]
        widgets = {
            "account": forms.Select(attrs={"class": "form-select"}),
            "debt_type": forms.Select(attrs={"class": "form-select"}),
            "lender": forms.TextInput(attrs={"class": "form-control"}),
            "principal_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
            "interest_rate": forms.NumberInput(attrs={"class": "form-control", "min": "0", "max": "50", "step": "0.1"}),
            "interest_type": forms.Select(attrs={"class": "form-select"}),
            "emi_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "emi_day": forms.NumberInput(attrs={"class": "form-control", "min": "1", "max": "31"}),
            "start_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "end_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "auto_pay_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_secured": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "collateral": forms.TextInput(attrs={"class": "form-control"}),
            "loan_account_number": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, user, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["account"].queryset = _scoped_accounts(user, organization=organization)
        self.fields["start_date"].initial = self.instance.start_date if self.instance.pk else date.today()

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        emi_amount = cleaned_data.get("emi_amount")
        emi_day = cleaned_data.get("emi_day")
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError({"end_date": "End date must be after start date."})
        if cleaned_data.get("auto_pay_enabled") and (not emi_amount or not emi_day):
            raise forms.ValidationError("Auto-pay needs both EMI amount and EMI day.")
        return cleaned_data


class TaxRecordForm(forms.ModelForm):
    class Meta:
        model = TaxRecord
        fields = [
            "financial_year",
            "tax_type",
            "taxable_amount",
            "tax_paid",
            "tax_due",
            "due_date",
            "filed_date",
            "acknowledgement_number",
            "notes",
        ]
        widgets = {
            "financial_year": forms.TextInput(attrs={"class": "form-control", "placeholder": "2025-2026"}),
            "tax_type": forms.Select(attrs={"class": "form-select"}),
            "taxable_amount": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "tax_paid": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "tax_due": forms.NumberInput(attrs={"class": "form-control", "min": "0", "step": "0.01"}),
            "due_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "filed_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "acknowledgement_number": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def clean_financial_year(self):
        financial_year = self.cleaned_data["financial_year"]
        if not re.match(r"^\d{4}-\d{4}$", financial_year):
            raise forms.ValidationError("Financial year must use YYYY-YYYY format.")
        start_year, end_year = [int(part) for part in financial_year.split("-")]
        if end_year != start_year + 1:
            raise forms.ValidationError("Financial year end must be the next year.")
        return financial_year


class ReportFilterForm(forms.Form):
    report_type = forms.ChoiceField(
        choices=Budget.REPORT_TYPES if hasattr(Budget, "REPORT_TYPES") else [
            ("MONTHLY", "Monthly Report"),
            ("QUARTERLY", "Quarterly Report"),
            ("YEARLY", "Annual Report"),
            ("CASH_FLOW", "Cash Flow Report"),
            ("NET_WORTH", "Net Worth Report"),
            ("TAX", "Tax Report"),
            ("BUDGET", "Budget Performance"),
            ("INVESTMENT", "Investment Portfolio"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    start_date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    end_date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    category = forms.ChoiceField(
        choices=[("", "All categories")] + list(Expense.EXPENSE_CATEGORIES),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    include_investments = forms.BooleanField(required=False, initial=True, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    include_debts = forms.BooleanField(required=False, initial=True, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].initial = date.today().replace(day=1)
        self.fields["end_date"].initial = date.today()

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and end_date < start_date:
            raise forms.ValidationError("End date must be after start date.")
        return cleaned_data


class ImportCSVForm(forms.Form):
    DATA_TYPES = [
        ("INCOME", "Income"),
        ("EXPENSE", "Expense"),
        ("BOTH", "Mixed (type column required)"),
    ]

    data_type = forms.ChoiceField(choices=DATA_TYPES, widget=forms.Select(attrs={"class": "form-select"}))
    csv_file = forms.FileField(widget=forms.FileInput(attrs={"class": "form-control", "accept": ".csv"}))
    has_headers = forms.BooleanField(required=False, initial=True, widget=forms.CheckboxInput(attrs={"class": "form-check-input"}))
    date_format = forms.CharField(initial="%Y-%m-%d", widget=forms.TextInput(attrs={"class": "form-control"}))

    def clean_csv_file(self):
        csv_file = self.cleaned_data["csv_file"]
        if not csv_file.name.lower().endswith(".csv"):
            raise forms.ValidationError("Only CSV files are supported.")
        if csv_file.size > 5 * 1024 * 1024:
            raise forms.ValidationError("CSV file size cannot exceed 5 MB.")
        return csv_file


class DebtPaymentForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
    )
    payment_date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    payment_method = forms.ChoiceField(choices=Expense.PAYMENT_METHODS, widget=forms.Select(attrs={"class": "form-select"}))
    notes = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}))

    def __init__(self, debt_instance, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.debt = debt_instance
        self.fields["payment_date"].initial = date.today()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount > self.debt.remaining_amount:
            raise forms.ValidationError("Payment amount cannot exceed the remaining balance.")
        return amount


class GoalContributionForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01"),
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "0.01", "step": "0.01"}),
    )
    contribution_date = forms.DateField(widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    source_account = forms.ModelChoiceField(queryset=Account.objects.none(), widget=forms.Select(attrs={"class": "form-select"}))
    notes = forms.CharField(required=False, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Optional note"}))

    def __init__(self, user, goal_instance, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.goal = goal_instance
        self.fields["source_account"].queryset = _scoped_accounts(user, organization=organization)
        self.fields["contribution_date"].initial = date.today()

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        remaining = self.goal.target_amount - self.goal.current_amount
        if amount > remaining:
            raise forms.ValidationError("Contribution exceeds the remaining amount needed for this goal.")
        return amount
