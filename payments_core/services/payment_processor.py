# payments_core/services/payment_processor.py
import logging
from decimal import Decimal
from django.conf import settings

from ..models import PaymentIntent, PaymentAccount
from .payment_method_resolver import resolve_for_intent

logger = logging.getLogger(__name__)

class PaymentProcessor:
    """Main payment processor for handling payments"""
    
    @classmethod
    def create_payment_intent(cls, user, amount, payment_method, description="", metadata=None, organization=None):
        """
        Create a new payment intent
        """
        try:
            # Get user's primary payment account
            account_qs = PaymentAccount.objects.filter(user=user)
            if organization is not None:
                account_qs = account_qs.filter(organization=organization)

            account = account_qs.filter(is_primary=True).first()
            if not account:
                # Create default account if none exists
                account = PaymentAccount.objects.create(
                    user=user,
                    organization=organization,
                    account_number=PaymentAccount.generate_account_number(),
                    account_type='SAVINGS',
                    balance=0.00,
                    available_balance=0.00,
                    is_primary=True
                )
            
            # Create payment intent
            payment_intent = PaymentIntent.objects.create(
                user=user,
                organization=organization,
                account=account,
                reference_id=PaymentIntent.generate_reference_id(),
                amount=Decimal(amount),
                payment_method=payment_method,
                description=description,
                status='CREATED',
                metadata=metadata or {}
            )
            
            logger.info(f"Created payment intent {payment_intent.reference_id} for user {user.username}")
            return payment_intent
            
        except Exception as e:
            logger.error(f"Error creating payment intent: {str(e)}")
            raise
    
    @classmethod
    def process_payment(cls, payment_intent):
        """
        Process a payment intent
        """
        try:
            # Normalize + validate method requirements
            resolved = resolve_for_intent(payment_intent)
            if payment_intent.payment_method != resolved.method:
                payment_intent.payment_method = resolved.method

            # Update status to processing
            payment_intent.status = 'PROCESSING'
            payment_intent.save()
            
            # Process based on payment method
            if resolved.method == 'CARD':
                return cls._process_card_payment(payment_intent)
            elif resolved.method == 'UPI':
                return cls._process_upi_payment(payment_intent)
            elif resolved.method == 'BANK_TRANSFER':
                return cls._process_bank_transfer(payment_intent)
            elif resolved.method == 'NETBANKING':
                return cls._process_netbanking(payment_intent)
            elif resolved.method == 'WALLET':
                return cls._process_wallet_payment(payment_intent)
            else:
                payment_intent.mark_failed(f"Unsupported payment method: {payment_intent.payment_method}")
                return {'success': False, 'error': 'Unsupported payment method'}
                
        except Exception as e:
            logger.error(f"Error processing payment {payment_intent.reference_id}: {str(e)}")
            payment_intent.mark_failed(str(e))
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def _process_card_payment(cls, payment_intent):
        """Process card payment"""
        try:
            # Check if card token exists for saved cards
            if payment_intent.card_token:
                # Process with saved card
                return cls._process_saved_card_payment(payment_intent)
            else:
                # Process with new card (simulate for now)
                # In production, integrate with Razorpay/Stripe
                payment_intent.gateway = 'RAZORPAY'
                payment_intent.save()
                
                # Simulate success for demo
                return {
                    'success': True,
                    'message': 'Card payment initiated',
                    'gateway_data': {
                        'payment_id': f"card_{payment_intent.reference_id}",
                        'method': 'card'
                    }
                }
                
        except Exception as e:
            logger.error(f"Card payment error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def _process_saved_card_payment(cls, payment_intent):
        """Process payment with saved card token"""
        try:
            card_token = payment_intent.card_token
            
            # Check if card is active
            if not card_token.is_active:
                return {'success': False, 'error': 'Card is not active'}
            
            # Check if card is not expired
            from datetime import datetime
            current_year = datetime.now().year
            current_month = datetime.now().month
            
            if (card_token.expiry_year < current_year or 
                (card_token.expiry_year == current_year and card_token.expiry_month < current_month)):
                return {'success': False, 'error': 'Card has expired'}
            
            # Simulate payment processing
            payment_intent.gateway = card_token.gateway
            payment_intent.save()
            
            # Update card token last used
            card_token.last_used = datetime.now()
            card_token.save()
            
            return {
                'success': True,
                'message': 'Payment with saved card initiated',
                'gateway_data': {
                    'payment_id': f"{card_token.gateway}_{payment_intent.reference_id}",
                    'method': 'card',
                    'card_last4': card_token.last4,
                    'card_brand': card_token.brand
                }
            }
            
        except Exception as e:
            logger.error(f"Saved card payment error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def _process_upi_payment(cls, payment_intent):
        """Process UPI payment"""
        try:
            # Simulate UPI payment initiation
            payment_intent.gateway = 'UPI'
            payment_intent.save()
            
            return {
                'success': True,
                'message': 'UPI payment initiated',
                'gateway_data': {
                    'payment_id': f"upi_{payment_intent.reference_id}",
                    'method': 'upi',
                    'vpa': payment_intent.upi_vpa
                }
            }
            
        except Exception as e:
            logger.error(f"UPI payment error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def _process_bank_transfer(cls, payment_intent):
        """Process bank transfer"""
        try:
            payment_intent.gateway = 'BANK_TRANSFER'
            payment_intent.save()
            
            return {
                'success': True,
                'message': 'Bank transfer initiated',
                'gateway_data': {
                    'payment_id': f"bank_{payment_intent.reference_id}",
                    'method': 'bank_transfer'
                }
            }
            
        except Exception as e:
            logger.error(f"Bank transfer error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def _process_netbanking(cls, payment_intent):
        """Process net banking"""
        try:
            payment_intent.gateway = 'NETBANKING'
            payment_intent.save()
            
            return {
                'success': True,
                'message': 'Net banking initiated',
                'gateway_data': {
                    'payment_id': f"netbank_{payment_intent.reference_id}",
                    'method': 'netbanking'
                }
            }
            
        except Exception as e:
            logger.error(f"Net banking error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def _process_wallet_payment(cls, payment_intent):
        """Process wallet payment"""
        try:
            payment_intent.gateway = 'WALLET'
            payment_intent.save()
            
            return {
                'success': True,
                'message': 'Wallet payment initiated',
                'gateway_data': {
                    'payment_id': f"wallet_{payment_intent.reference_id}",
                    'method': 'wallet'
                }
            }
            
        except Exception as e:
            logger.error(f"Wallet payment error: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @classmethod
    def verify_webhook_signature(cls, gateway, request):
        """
        Verify webhook signature.

        This supports:
        - Razorpay: HMAC SHA256 over raw body
        - Stripe: stripe.Webhook (if stripe package is installed)

        In *dummy mode* (no secret configured), it will accept the webhook
        but log a warning so you can spot misconfiguration.
        """
        try:
            gw = (gateway or '').lower()

            if gw == 'razorpay':
                import hmac
                import hashlib

                secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', None)
                signature = request.META.get('HTTP_X_RAZORPAY_SIGNATURE')

                if not secret or not signature:
                    logger.warning('Razorpay webhook accepted without signature verification (missing secret or header)')
                    return True

                expected = hmac.new(
                    key=str(secret).encode('utf-8'),
                    msg=request.body,
                    digestmod=hashlib.sha256,
                ).hexdigest()
                return hmac.compare_digest(expected, signature)

            if gw == 'stripe':
                secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)
                sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')

                if not secret or not sig_header:
                    logger.warning('Stripe webhook accepted without signature verification (missing secret or header)')
                    return True

                try:
                    import stripe
                    stripe.Webhook.construct_event(payload=request.body, sig_header=sig_header, secret=secret)
                    return True
                except ImportError:
                    logger.warning('stripe package not installed; accepting webhook without verification')
                    return True

            logger.warning(f'Unknown gateway {gateway}; accepting webhook without verification')
            return True

        except Exception as e:
            logger.error(f'Webhook signature verification error: {e}')
            return False
    
    @classmethod
    def refund_payment(cls, payment_intent_id, amount=None, reason=None):
        """
        Initiate refund for a payment
        """
        try:
            payment_intent = PaymentIntent.objects.get(id=payment_intent_id)
            
            # Check if payment can be refunded
            if payment_intent.status != 'SUCCESS':
                return {'success': False, 'error': 'Only successful payments can be refunded'}
            
            refund_amount = Decimal(amount) if amount else payment_intent.amount
            
            if refund_amount > payment_intent.amount:
                return {'success': False, 'error': 'Refund amount exceeds payment amount'}
            
            # Create refund payment intent
            refund_intent = PaymentIntent.objects.create(
                user=payment_intent.user,
                account=payment_intent.account,
                reference_id=PaymentIntent.generate_reference_id(),
                amount=refund_amount,
                payment_method='REFUND',
                description=f"Refund: {payment_intent.description}",
                status='SUCCESS',  # Auto-success for demo
                metadata={
                    'original_payment_id': str(payment_intent.id),
                    'original_reference_id': payment_intent.reference_id,
                    'reason': reason or 'Customer request'
                }
            )
            
            # Update original payment status
            if refund_amount == payment_intent.amount:
                payment_intent.status = 'REFUNDED'
            else:
                payment_intent.status = 'PARTIALLY_REFUNDED'
            payment_intent.save()

            # IMPORTANT: Do NOT update balances directly here.
            # The refund intent is created with status=SUCCESS and payment_method=REFUND.
            # payments_core signals will perform the idempotent balance update and
            # create the corresponding PaymentTransaction.
            
            logger.info(f"Refund processed for payment {payment_intent.reference_id}")
            
            return {
                'success': True,
                'refund_intent': refund_intent,
                'message': 'Refund processed successfully'
            }
            
        except PaymentIntent.DoesNotExist:
            return {'success': False, 'error': 'Payment not found'}
        except Exception as e:
            logger.error(f"Refund error: {str(e)}")
            return {'success': False, 'error': str(e)}

    @classmethod
    def chargeback_payment(cls, payment_intent_id, amount=None, reason=None):
        """Simulate a chargeback (dummy mode).

        - Creates a REFUND credit intent (signals update balances)
        - Marks original intent as CHARGEBACK
        """
        try:
            payment_intent = PaymentIntent.objects.get(id=payment_intent_id)

            if payment_intent.status not in ['SUCCESS', 'REFUNDED', 'PARTIALLY_REFUNDED']:
                return {'success': False, 'error': 'Chargeback only allowed for completed payments'}

            chargeback_amount = Decimal(amount) if amount else payment_intent.amount
            if chargeback_amount > payment_intent.amount:
                return {'success': False, 'error': 'Chargeback amount exceeds payment amount'}

            cb_intent = PaymentIntent.objects.create(
                user=payment_intent.user,
                account=payment_intent.account,
                reference_id=PaymentIntent.generate_reference_id(),
                amount=chargeback_amount,
                payment_method='REFUND',
                description=f"Chargeback: {payment_intent.description}",
                status='SUCCESS',
                metadata={
                    'original_payment_id': str(payment_intent.id),
                    'original_reference_id': payment_intent.reference_id,
                    'reason': reason or 'Chargeback',
                    'type': 'CHARGEBACK',
                }
            )

            payment_intent.status = 'CHARGEBACK'
            payment_intent.save(update_fields=['status', 'updated_at'])

            logger.info(f"Chargeback processed for payment {payment_intent.reference_id}")

            return {'success': True, 'chargeback_intent': cb_intent, 'message': 'Chargeback processed successfully'}

        except PaymentIntent.DoesNotExist:
            return {'success': False, 'error': 'Payment not found'}
        except Exception as e:
            logger.error(f"Chargeback error: {str(e)}")
            return {'success': False, 'error': str(e)}