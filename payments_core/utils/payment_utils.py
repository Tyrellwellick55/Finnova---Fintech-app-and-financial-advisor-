# payments_core/services/payment_utils.py
import uuid
from datetime import datetime
from decimal import Decimal
from django.utils import timezone

class PaymentUtils:
    """Utility functions for payment operations"""
    
    @staticmethod
    def generate_transaction_id():
        """Generate unique transaction ID"""
        return f"TXN{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"
    
    @staticmethod
    def format_currency(amount):
        """Format amount with Indian currency"""
        try:
            return f"₹ {float(amount):,.2f}"
        except (ValueError, TypeError):
            return f"₹ {0:,.2f}"
    
    @staticmethod
    def calculate_gst(amount, gst_percent=18):
        """Calculate GST on amount"""
        try:
            amount_decimal = Decimal(str(amount))
            gst = (amount_decimal * Decimal(str(gst_percent))) / Decimal('100')
            return gst.quantize(Decimal('0.01'))
        except Exception:
            return Decimal('0.00')
    
    @staticmethod
    def get_payment_status_color(status):
        """Get Bootstrap color class for status"""
        status_colors = {
            'CREATED': 'info',
            'PENDING': 'warning',
            'PROCESSING': 'warning',
            'SUCCESS': 'success',
            'FAILED': 'danger',
            'CANCELLED': 'secondary',
            'REFUNDED': 'dark',
            'PARTIALLY_REFUNDED': 'warning',
            'SCHEDULED': 'primary',
        }
        return status_colors.get(status, 'secondary')
    
    @staticmethod
    def is_business_hours():
        """Check if current time is within business hours"""
        try:
            now = timezone.localtime()
            # Monday to Friday, 9 AM to 6 PM
            return now.weekday() < 5 and 9 <= now.hour < 18
        except Exception:
            return True  # Default to True if timezone fails
    
    @staticmethod
    def generate_receipt_number():
        """Generate receipt number"""
        return f"RCPT-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    
    @staticmethod
    def mask_card_number(card_number):
        """Mask card number for display"""
        if not card_number:
            return "****"
        card_number = str(card_number).replace(' ', '')
        if len(card_number) >= 4:
            return f"**** **** **** {card_number[-4:]}"
        return "****"
    
    @staticmethod
    def validate_amount(amount, min_amount=1, max_amount=1000000):
        """Validate payment amount"""
        try:
            amount_decimal = Decimal(str(amount))
            if amount_decimal < Decimal(str(min_amount)):
                return False, f"Amount must be at least ₹{min_amount}"
            if amount_decimal > Decimal(str(max_amount)):
                return False, f"Amount cannot exceed ₹{max_amount}"
            return True, "Valid"
        except Exception:
            return False, "Invalid amount format"