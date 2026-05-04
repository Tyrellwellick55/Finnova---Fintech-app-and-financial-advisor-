# payments_core/services/validators.py
import re
from decimal import Decimal
from django.core.exceptions import ValidationError

def validate_upi_id(upi_id):
    """Validate UPI ID format"""
    if not upi_id:
        return False
    pattern = r'^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$'
    return bool(re.match(pattern, upi_id, re.IGNORECASE))

def validate_card_number(card_number):
    """Validate card number using Luhn algorithm"""
    if not card_number:
        return False
    
    # Remove spaces and non-digits
    card_number = re.sub(r'[^\d]', '', card_number)
    
    if not card_number.isdigit() or len(card_number) < 13:
        return False
    
    # Luhn algorithm
    total = 0
    reverse_digits = card_number[::-1]
    
    for i, digit in enumerate(reverse_digits):
        n = int(digit)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    
    return total % 10 == 0

def validate_amount(amount, min_amount=1, max_amount=1000000):
    """Validate payment amount"""
    try:
        if not isinstance(amount, (int, float, Decimal)):
            amount = Decimal(str(amount))
        else:
            amount = Decimal(amount)
        
        if amount < Decimal(min_amount):
            raise ValidationError(f"Amount must be at least ₹{min_amount}")
        
        if amount > Decimal(max_amount):
            raise ValidationError(f"Amount cannot exceed ₹{max_amount}")
        
        return True
    except (ValueError, TypeError):
        raise ValidationError("Amount must be a valid number")

def validate_expiry_date(month, year):
    """Validate card expiry date"""
    from datetime import datetime
    
    try:
        month = int(month)
        year = int(year)
        
        current_year = datetime.now().year
        current_month = datetime.now().month
        
        if not (1 <= month <= 12):
            return False, "Invalid month"
        
        if year < current_year or (year == current_year and month < current_month):
            return False, "Card has expired"
        
        return True, "Valid"
    except (ValueError, TypeError):
        return False, "Invalid date format"

def validate_cvv(cvv):
    """Validate CVV"""
    if not cvv:
        return False
    cvv = str(cvv)
    return cvv.isdigit() and len(cvv) in [3, 4]

def validate_ifsc_code(ifsc):
    """Validate IFSC code format"""
    if not ifsc:
        return False
    pattern = r'^[A-Z]{4}0[A-Z0-9]{6}$'
    return bool(re.match(pattern, ifsc))

def validate_account_number(account_number):
    """Validate bank account number"""
    if not account_number:
        return False
    account_number = str(account_number)
    return account_number.isdigit() and 9 <= len(account_number) <= 18