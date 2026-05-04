# payments_core/services/upi.py
import qrcode
import base64
import io

def generate_static_upi_qr(vpa, merchant_name):
    """Generate static UPI QR code"""
    try:
        upi_string = f"upi://pay?pa={vpa}&pn={merchant_name}&cu=INR"
        qr = qrcode.make(upi_string)
        
        # Convert to base64
        buffer = io.BytesIO()
        qr.save(buffer, format='PNG')
        buffer.seek(0)
        
        return base64.b64encode(buffer.read()).decode()
    except Exception:
        # Return empty string if QR generation fails
        return ""

def generate_dynamic_upi_qr(vpa, merchant_name, amount, txn_id):
    """Generate dynamic UPI QR code with amount"""
    try:
        upi_string = (
            f"upi://pay?"
            f"pa={vpa}"
            f"&pn={merchant_name}"
            f"&am={amount}"
            f"&cu=INR"
            f"&tn=TXN-{txn_id}"
        )
        qr = qrcode.make(upi_string)
        
        # Convert to base64
        buffer = io.BytesIO()
        qr.save(buffer, format='PNG')
        buffer.seek(0)
        
        return base64.b64encode(buffer.read()).decode()
    except Exception:
        # Return empty string if QR generation fails
        return ""