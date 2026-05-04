from __future__ import annotations

from django import forms
from django.utils import timezone

from .models import Client, Project, Invoice


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'company_name', 'email', 'phone', 'billing_address', 'gstin', 'is_active', 'notes']
        widgets = {
            'billing_address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

    def clean_gstin(self):
        gstin = (self.cleaned_data.get('gstin') or '').strip().upper()
        if gstin and len(gstin) != 15:
            raise forms.ValidationError('GSTIN must be exactly 15 characters.')
        return gstin or None

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip().lower()
        return email or None


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['client', 'name', 'description', 'monthly_retainer', 'monthly_budget', 'start_date', 'end_date', 'status']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and end < start:
            raise forms.ValidationError({'end_date': 'End date must be on or after the start date.'})
        retainer = cleaned.get('monthly_retainer')
        budget = cleaned.get('monthly_budget')
        if retainer and budget and budget > retainer:
            # Warn — cost exceeds revenue
            self.add_error('monthly_budget', 'Monthly budget exceeds the monthly retainer (cost > revenue).')
        return cleaned


class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = [
            'client', 'project', 'invoice_number', 'title',
            'amount', 'issued_date', 'due_date',
            'status', 'payment_reference', 'notes',
        ]
        widgets = {
            'notes': forms.Textarea(attrs={'rows': 3}),
            'issued_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount is not None and amount <= 0:
            raise forms.ValidationError('Invoice amount must be greater than zero.')
        return amount

    def clean_invoice_number(self):
        inv_num = (self.cleaned_data.get('invoice_number') or '').strip()
        return inv_num or None  # Allow blank; view will auto-generate before save

    def clean(self):
        cleaned = super().clean()
        issued = cleaned.get('issued_date') or timezone.now().date()
        due = cleaned.get('due_date')
        if due and due < issued:
            raise forms.ValidationError({'due_date': 'Due date cannot be before the issue date.'})
        # Ensure project belongs to same client
        client = cleaned.get('client')
        project = cleaned.get('project')
        if project and client and project.client_id != client.pk:
            raise forms.ValidationError({'project': 'Selected project does not belong to the chosen client.'})
        return cleaned


class ControlTowerSettingsForm(forms.Form):
    monthly_payroll_estimate = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        min_value=0,
        help_text='Used only for runway / safe-to-spend calculations (demo mode).',
    )
