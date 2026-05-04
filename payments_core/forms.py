# payments_core/forms.py
from django import forms
from .models import (
    PaymentIntent, ATMCard, VirtualCard, CardToken,
    Subscription, ATMTransaction
)
from django.core.validators import MinValueValidator
from decimal import Decimal
import re

class PaymentForm(forms.ModelForm):
    """Create payment form"""
    PAYMENT_METHODS = [
        ('CARD', 'Credit/Debit Card'),
        ('UPI', 'UPI'),
        ('NETBANKING', 'Net Banking'),
        ('WALLET', 'Wallet'),
        ('BANK_TRANSFER', 'Bank Transfer'),
    ]
    
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Amount in INR',
            'min': '1',
            'step': '0.01'
        })
    )
    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHODS,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    description = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Payment description'
        })
    )
    save_card = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    
    class Meta:
        model = PaymentIntent
        fields = ['amount', 'payment_method', 'description']
    
    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount and amount < Decimal('1.00'):
            raise forms.ValidationError("Minimum payment amount is ₹1.00")
        return amount

class CardPaymentForm(forms.Form):
    """Card payment form"""
    CARD_TYPES = [
        ('VISA', 'Visa'),
        ('MASTERCARD', 'MasterCard'),
        ('RUPAY', 'RuPay'),
        ('AMEX', 'American Express'),
    ]
    
    card_number = forms.CharField(
        max_length=19,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '1234 5678 9012 3456',
            'data-mask': '0000 0000 0000 0000'
        })
    )
    card_holder = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Cardholder Name'
        })
    )
    expiry_month = forms.ChoiceField(
        choices=[(str(i).zfill(2), str(i).zfill(2)) for i in range(1, 13)],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    expiry_year = forms.ChoiceField(
        choices=[(str(i), str(i)) for i in range(2024, 2035)],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    cvv = forms.CharField(
        max_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'CVV',
            'maxlength': '4'
        })
    )
    save_card = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    use_saved_card = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.HiddenInput()
    )
    saved_card_id = forms.CharField(
        required=False,
        widget=forms.HiddenInput()
    )
    
    def clean_card_number(self):
        card_number = self.cleaned_data.get('card_number')
        # Remove spaces
        card_number = card_number.replace(' ', '')
        
        if not re.match(r'^\d{13,19}$', card_number):
            raise forms.ValidationError("Invalid card number")
        
        # Luhn algorithm check
        def luhn_checksum(card_number):
            def digits_of(n):
                return [int(d) for d in str(n)]
            digits = digits_of(card_number)
            odd_digits = digits[-1::-2]
            even_digits = digits[-2::-2]
            checksum = sum(odd_digits)
            for d in even_digits:
                checksum += sum(digits_of(d*2))
            return checksum % 10
        
        if luhn_checksum(card_number) != 0:
            raise forms.ValidationError("Invalid card number")
        
        return card_number
    
    def clean_cvv(self):
        cvv = self.cleaned_data.get('cvv')
        if not re.match(r'^\d{3,4}$', cvv):
            raise forms.ValidationError("Invalid CVV")
        return cvv
    
    def clean(self):
        cleaned_data = super().clean()
        expiry_month = cleaned_data.get('expiry_month')
        expiry_year = cleaned_data.get('expiry_year')
        
        # Check if card is expired
        if expiry_month and expiry_year:
            from datetime import datetime
            current_month = datetime.now().month
            current_year = datetime.now().year
            
            if int(expiry_year) < current_year or (
                int(expiry_year) == current_year and int(expiry_month) < current_month
            ):
                raise forms.ValidationError("Card has expired")
        
        return cleaned_data

class UPIPaymentForm(forms.Form):
    """UPI payment form"""
    upi_id = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'username@upi'
        })
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Amount',
            'min': '1'
        })
    )
    note = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Optional note'
        })
    )
    
    def clean_upi_id(self):
        upi_id = self.cleaned_data.get('upi_id')
        # Basic UPI ID validation
        if not re.match(r'^[\w\.\-]+@[\w]+$', upi_id, re.IGNORECASE):
            raise forms.ValidationError("Invalid UPI ID format")
        return upi_id.lower()

class BankTransferForm(forms.Form):
    """Bank transfer form"""
    bank_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Bank Name'
        })
    )
    account_number = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Account Number'
        })
    )
    ifsc_code = forms.CharField(
        max_length=11,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'IFSC Code'
        })
    )
    account_holder = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Account Holder Name'
        })
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Amount',
            'min': '1'
        })
    )
    description = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Transfer description'
        })
    )
    
    def clean_ifsc_code(self):
        ifsc = self.cleaned_data.get('ifsc_code')
        if not re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', ifsc):
            raise forms.ValidationError("Invalid IFSC Code format")
        return ifsc
    
    def clean_account_number(self):
        acc_no = self.cleaned_data.get('account_number')
        if not re.match(r'^\d{9,18}$', acc_no):
            raise forms.ValidationError("Invalid account number")
        return acc_no

class QuickTransferForm(forms.Form):
    """Quick transfer to saved beneficiaries"""
    beneficiary = forms.ChoiceField(
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('1.00'))],
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Amount',
            'min': '1'
        })
    )
    remarks = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Remarks (optional)'
        })
    )
    
    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate beneficiaries from user's saved beneficiaries
        from .models import Beneficiary
        beneficiaries = Beneficiary.objects.filter(user=user, is_active=True)
        self.fields['beneficiary'].choices = [
            (b.id, f"{b.name} - {b.account_number} ({b.bank_name})")
            for b in beneficiaries
        ]

class ATMCardForm(forms.ModelForm):
    """ATM card application/form"""
    class Meta:
        model = ATMCard
        fields = ['card_type', 'daily_withdrawal_limit', 'daily_transaction_limit']
        widgets = {
            'card_type': forms.Select(attrs={'class': 'form-control'}),
            'daily_withdrawal_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1000',
                'max': '50000'
            }),
            'daily_transaction_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '10000',
                'max': '100000'
            }),
        }
    
    def clean_daily_withdrawal_limit(self):
        limit = self.cleaned_data.get('daily_withdrawal_limit')
        if limit and (limit < 1000 or limit > 50000):
            raise forms.ValidationError("Daily withdrawal limit must be between ₹1,000 and ₹50,000")
        return limit

class ATMPinForm(forms.Form):
    """ATM PIN setup/change form"""
    current_pin = forms.CharField(
        max_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Current PIN',
            'maxlength': '4'
        })
    )
    new_pin = forms.CharField(
        max_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New PIN (4 digits)',
            'maxlength': '4'
        })
    )
    confirm_pin = forms.CharField(
        max_length=4,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm New PIN',
            'maxlength': '4'
        })
    )
    
    def clean_new_pin(self):
        pin = self.cleaned_data.get('new_pin')
        if not pin.isdigit() or len(pin) != 4:
            raise forms.ValidationError("PIN must be 4 digits")
        
        # Check for simple sequences
        if pin in ['1234', '0000', '1111', '2222', '3333', '4444', '5555', 
                   '6666', '7777', '8888', '9999']:
            raise forms.ValidationError("Please choose a stronger PIN")
        
        # Check if it's a repeated digit
        if len(set(pin)) == 1:
            raise forms.ValidationError("PIN cannot be a single repeated digit")
        
        return pin
    
    def clean(self):
        cleaned_data = super().clean()
        new_pin = cleaned_data.get('new_pin')
        confirm_pin = cleaned_data.get('confirm_pin')
        
        if new_pin and confirm_pin and new_pin != confirm_pin:
            raise forms.ValidationError({
                'confirm_pin': "PINs don't match"
            })
        
        return cleaned_data

class VirtualCardForm(forms.ModelForm):
    """Virtual card creation form"""
    class Meta:
        model = VirtualCard
        fields = ['card_type', 'daily_limit', 'per_transaction_limit', 
                  'total_limit', 'allow_international', 'allow_online', 
                  'allow_pos']
        widgets = {
            'card_type': forms.Select(attrs={'class': 'form-control'}),
            'daily_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1000',
                'max': '50000'
            }),
            'per_transaction_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '100',
                'max': '20000'
            }),
            'total_limit': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '5000',
                'max': '100000'
            }),
            'allow_international': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_online': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'allow_pos': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        per_transaction_limit = cleaned_data.get('per_transaction_limit')
        daily_limit = cleaned_data.get('daily_limit')
        total_limit = cleaned_data.get('total_limit')
        
        if per_transaction_limit and daily_limit and per_transaction_limit > daily_limit:
            raise forms.ValidationError({
                'per_transaction_limit': "Per transaction limit cannot exceed daily limit"
            })
        
        if daily_limit and total_limit and daily_limit > total_limit:
            raise forms.ValidationError({
                'daily_limit': "Daily limit cannot exceed total limit"
            })
        
        return cleaned_data

class SubscriptionForm(forms.ModelForm):
    """Subscription creation form"""
    class Meta:
        model = Subscription
        fields = ['name', 'amount', 'frequency', 'payment_method', 
                  'start_date', 'end_date']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Subscription name'
            }),
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'step': '0.01'
            }),
            'frequency': forms.Select(attrs={'class': 'form-control'}),
            'payment_method': forms.Select(attrs={'class': 'form-control'}),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
        }
    
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        
        if start_date and end_date and end_date <= start_date:
            raise forms.ValidationError({
                'end_date': "End date must be after start date"
            })
        
        return cleaned_data

class ATMTransactionForm(forms.ModelForm):
    """ATM transaction form"""
    TRANSACTION_CHOICES = [
        ('WITHDRAWAL', 'Cash Withdrawal'),
        ('DEPOSIT', 'Cash Deposit'),
        ('BALANCE_INQUIRY', 'Balance Inquiry'),
        ('MINI_STATEMENT', 'Mini Statement'),
        ('PIN_CHANGE', 'PIN Change'),
    ]
    
    transaction_type = forms.ChoiceField(
        choices=TRANSACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    amount = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Amount',
            'min': '100',
            'max': '50000'
        })
    )
    pin = forms.CharField(
        max_length=4,
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter PIN',
            'maxlength': '4'
        })
    )
    location = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'ATM Location'
        })
    )
    
    class Meta:
        model = ATMTransaction
        fields = ['transaction_type', 'amount', 'location']
    
    def clean(self):
        cleaned_data = super().clean()
        transaction_type = cleaned_data.get('transaction_type')
        amount = cleaned_data.get('amount')
        pin = cleaned_data.get('pin')
        
        if transaction_type in ['WITHDRAWAL', 'DEPOSIT'] and not amount:
            raise forms.ValidationError({
                'amount': "Amount is required for this transaction"
            })
        
        if transaction_type == 'WITHDRAWAL' and amount:
            if amount % 100 != 0:
                raise forms.ValidationError({
                    'amount': "Withdrawal amount must be in multiples of ₹100"
                })
            if amount < 100 or amount > 50000:
                raise forms.ValidationError({
                    'amount': "Withdrawal amount must be between ₹100 and ₹50,000"
                })
        
        if transaction_type == 'DEPOSIT' and amount:
            if amount < 100:
                raise forms.ValidationError({
                    'amount': "Minimum deposit amount is ₹100"
                })
        
        if transaction_type in ['WITHDRAWAL', 'PIN_CHANGE'] and not pin:
            raise forms.ValidationError({
                'pin': "PIN is required for this transaction"
            })
        
        if pin and (not pin.isdigit() or len(pin) != 4):
            raise forms.ValidationError({
                'pin': "PIN must be 4 digits"
            })
        
        return cleaned_data

class BeneficiaryForm(forms.Form):
    """Add beneficiary form"""
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Beneficiary Name'
        })
    )
    account_number = forms.CharField(
        max_length=20,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Account Number'
        })
    )
    ifsc_code = forms.CharField(
        max_length=11,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'IFSC Code'
        })
    )
    bank_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Bank Name'
        })
    )
    nickname = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nickname (optional)'
        })
    )
    transfer_limit = forms.DecimalField(
        max_digits=12,
        decimal_places=2,
        initial=100000.00,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'min': '1000',
            'max': '1000000'
        })
    )
    
    def clean_ifsc_code(self):
        ifsc = self.cleaned_data.get('ifsc_code')
        if not re.match(r'^[A-Z]{4}0[A-Z0-9]{6}$', ifsc):
            raise forms.ValidationError("Invalid IFSC Code format")
        return ifsc
    
    def clean_account_number(self):
        acc_no = self.cleaned_data.get('account_number')
        if not re.match(r'^\d{9,18}$', acc_no):
            raise forms.ValidationError("Invalid account number")
        return acc_no

class PaymentFilterForm(forms.Form):
    """Filter payments form"""
    STATUS_CHOICES = [
        ('', 'All Status'),
        ('SUCCESS', 'Success'),
        ('PENDING', 'Pending'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    PAYMENT_TYPES = [
        ('', 'All Types'),
        ('CARD', 'Card'),
        ('UPI', 'UPI'),
        ('NETBANKING', 'Net Banking'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('WALLET', 'Wallet'),
    ]
    
    status = forms.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    payment_type = forms.ChoiceField(
        choices=PAYMENT_TYPES,
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    date_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    date_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by reference or description'
        })
    )
    
    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get('date_from')
        date_to = cleaned_data.get('date_to')
        
        if date_from and date_to and date_to < date_from:
            raise forms.ValidationError({
                'date_to': "End date cannot be before start date"
            })
        
        return cleaned_data