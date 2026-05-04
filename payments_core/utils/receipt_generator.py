# payments_core/services/receipt_generator.py
import io
import logging
from django.conf import settings
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.lib.units import inch

logger = logging.getLogger(__name__)

def generate_receipt_pdf(payment_intent):
    """Generate PDF receipt for payment"""
    try:
        buffer = io.BytesIO()
        
        # Create PDF
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=18
        )
        
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            alignment=TA_CENTER,
            spaceAfter=30,
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            alignment=TA_LEFT,
            spaceAfter=12,
        )
        
        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontSize=11,
            alignment=TA_LEFT,
        )
        
        # Content
        story = []
        
        # Title
        story.append(Paragraph("PAYMENT RECEIPT", title_style))
        story.append(Spacer(1, 20))
        
        # Company Info (with fallbacks)
        company_name = getattr(settings, 'COMPANY_NAME', 'FINNOVA TECHNOLOGIES PVT LTD')
        company_gstin = getattr(settings, 'COMPANY_GSTIN', 'GSTINXXXXXXX')
        company_email = getattr(settings, 'COMPANY_EMAIL', 'info@finnova.com')
        company_phone = getattr(settings, 'COMPANY_PHONE', '+91 XXXXXXXXXX')
        
        company_info = [
            f"<b>{company_name}</b>",
            "Bangalore, Karnataka",
            f"GSTIN: {company_gstin}",
            f"Email: {company_email}",
            f"Phone: {company_phone}",
        ]
        
        for line in company_info:
            story.append(Paragraph(line, normal_style))
        
        story.append(Spacer(1, 30))
        
        # Receipt Details
        receipt_data = [
            ["<b>Receipt Number:</b>", f"RCPT-{payment_intent.reference_id}"],
            ["<b>Date:</b>", payment_intent.created_at.strftime("%d %B, %Y %I:%M %p")],
            ["<b>Transaction ID:</b>", payment_intent.reference_id],
            ["<b>Payment Method:</b>", payment_intent.get_payment_method_display()],
            ["<b>Status:</b>", payment_intent.get_status_display()],
        ]
        
        story.append(Paragraph("<b>Receipt Details</b>", heading_style))
        
        table = Table(receipt_data, colWidths=[2*inch, 3*inch])
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Customer Info
        customer_name = payment_intent.user.get_full_name() or payment_intent.user.username
        customer_info = [
            ["<b>Customer Name:</b>", customer_name],
            ["<b>Email:</b>", payment_intent.user.email],
            ["<b>Account Number:</b>", payment_intent.account.account_number],
        ]
        
        story.append(Paragraph("<b>Customer Information</b>", heading_style))
        
        table = Table(customer_info, colWidths=[2*inch, 3*inch])
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 20))
        
        # Payment Details
        amount = float(payment_intent.amount)
        gst = amount * 0.18
        total = amount + gst
        
        payment_details = [
            ["<b>Description</b>", "<b>Amount (INR)</b>"],
            ["Payment Amount", f"₹ {amount:,.2f}"],
            ["Tax (GST 18%)", f"₹ {gst:,.2f}"],
            ["<b>Total Amount</b>", f"<b>₹ {total:,.2f}</b>"],
        ]
        
        story.append(Paragraph("<b>Payment Details</b>", heading_style))
        
        table = Table(payment_details, colWidths=[3.5*inch, 1.5*inch])
        table.setStyle(TableStyle([
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 1, colors.grey),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightblue),
        ]))
        
        story.append(table)
        story.append(Spacer(1, 30))
        
        # Footer
        support_email = getattr(settings, 'SUPPORT_EMAIL', 'support@finnova.com')
        footer_text = f"""
        <i>This is a computer generated receipt. No signature required.</i><br/>
        <i>For any queries, contact {support_email}</i><br/>
        <i>Thank you for your payment!</i>
        """
        
        story.append(Paragraph(footer_text, normal_style))
        
        # Build PDF
        doc.build(story)
        
        # Get PDF value
        pdf = buffer.getvalue()
        buffer.close()
        
        return pdf
        
    except Exception as e:
        logger.error(f"Error generating receipt PDF: {str(e)}")
        # Return empty bytes if PDF generation fails
        return b''