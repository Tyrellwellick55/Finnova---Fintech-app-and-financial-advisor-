# payments_core/services/__init__.py
from .payment_processor import PaymentProcessor
from .razorpay_service import create_razorpay_order, verify_payment
from .stripe_service import create_stripe_payment_intent, confirm_stripe_payment, create_stripe_customer
from ..integration.autopilot import AutopilotPaymentIntegration
from ..integration.finance import FinancePaymentIntegration as FinancialIntegrator
from .risk_analyzer import RiskAnalyzer
from .audit_logger import AuditLogger
from .payment_integrator import PaymentIntegrator
from .ai_predictor import AIPredictor
from .automation_engine import AutomationEngine
from .finance_bridge import PaymentFinanceBridge

try:
    from ..utils.encryption import EncryptionService
except Exception:  # optional dependency (cryptography)
    EncryptionService = None

from ..utils.payment_utils import PaymentUtils

try:
    from ..utils.receipt_generator import generate_receipt_pdf
except Exception:
    def generate_receipt_pdf(*args, **kwargs):
        return None

try:
    from ..utils.upi import generate_static_upi_qr, generate_dynamic_upi_qr
except Exception:
    def generate_static_upi_qr(*args, **kwargs):
        return ""
    def generate_dynamic_upi_qr(*args, **kwargs):
        return ""

from ..utils.validators import validate_upi_id, validate_card_number, validate_amount

__all__ = [
    'PaymentProcessor',
    'create_razorpay_order',
    'verify_payment',
    'create_stripe_payment_intent',
    'confirm_stripe_payment',
    'create_stripe_customer',
    'AutopilotPaymentIntegration',
    'FinancialIntegrator',
    'RiskAnalyzer',
    'AuditLogger',
    'PaymentIntegrator',
    'AIPredictor',
    'AutomationEngine',
    'EncryptionService',
    'PaymentUtils',
    'generate_receipt_pdf',
    'generate_static_upi_qr',
    'generate_dynamic_upi_qr',
    'validate_upi_id',
    'validate_card_number',
    'validate_amount',
    'PaymentFinanceBridge',
]
