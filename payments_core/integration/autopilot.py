# payments_core/services/autopilot.py
import logging
from django.utils import timezone
from datetime import datetime

from ..models import PaymentIntent, Subscription, PaymentAccount
from ..services.payment_processor import PaymentProcessor

logger = logging.getLogger(__name__)

class AutopilotPaymentIntegration:
    """Integration between payments and autopilot features"""
    
    @staticmethod
    def process_autopilot_payments(user):
        """
        Process all automated payments for autopilot
        """
        try:
            # Get user's active subscriptions
            subscriptions = Subscription.objects.filter(
                user=user,
                status='ACTIVE'
            )
            
            processed = []
            for subscription in subscriptions:
                if subscription.next_billing_date <= timezone.now().date():
                    try:
                        # Create payment intent
                        payment_intent = PaymentIntent.objects.create(
                            user=user,
                            account=subscription.account,
                            reference_id=PaymentIntent.generate_reference_id(),
                            amount=subscription.amount,
                            payment_method=subscription.payment_method,
                            description=f"Auto-payment: {subscription.name}",
                            status='PROCESSING',
                            card_token=subscription.card_token if subscription.payment_method == 'CARD' else None,
                            metadata={
                                'subscription_id': str(subscription.id),
                                'autopilot': True
                            }
                        )
                        
                        # Process payment
                        result = PaymentProcessor.process_payment(payment_intent)
                        
                        if result['success']:
                            payment_intent.mark_success(result.get('gateway_data', {}))
                            
                            # Update subscription
                            subscription.next_billing_date = subscription.calculate_next_billing_date()
                            subscription.save()
                            
                            processed.append({
                                'subscription': subscription.name,
                                'amount': subscription.amount,
                                'status': 'success'
                            })
                            logger.info(f"Auto-payment processed for subscription {subscription.id}")
                            
                    except Exception as e:
                        logger.error(f"Error processing autopayment for subscription {subscription.id}: {str(e)}")
                        processed.append({
                            'subscription': subscription.name,
                            'amount': subscription.amount,
                            'status': 'failed',
                            'error': str(e)
                        })
            
            return {
                'success': True,
                'processed': processed,
                'total': len(processed)
            }
            
        except Exception as e:
            logger.error(f"Error in process_autopilot_payments: {str(e)}")
            return {'success': False, 'error': str(e), 'processed': []}
    
    @staticmethod
    def schedule_payment(user, amount, payee, schedule_date, description=""):
        """
        Schedule a future payment
        """
        try:
            # Create scheduled payment record
            # In a real implementation, this would be stored in a ScheduledPayment model
            # and processed by a background job
            
            from ..models import PaymentIntent
            
            # Create payment intent with future date
            payment_intent = PaymentIntent.objects.create(
                user=user,
                account=PaymentAccount.objects.filter(user=user, is_primary=True).first(),
                reference_id=PaymentIntent.generate_reference_id(),
                amount=amount,
                payment_method='SCHEDULED',
                description=f"Scheduled: {description or f'Payment to {payee}'}",
                status='SCHEDULED',  # New status for scheduled payments
                metadata={
                    'payee': payee,
                    'scheduled_date': schedule_date.isoformat(),
                    'scheduled': True
                }
            )
            
            logger.info(f"Scheduled payment created: {payment_intent.reference_id} for {schedule_date}")
            
            return {
                'success': True,
                'payment_intent': payment_intent,
                'message': f'Payment scheduled for {schedule_date}'
            }
            
        except Exception as e:
            logger.error(f"Error scheduling payment: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    @staticmethod
    def execute_scheduled_payments():
        """
        Execute all due scheduled payments
        """
        try:
            today = timezone.now().date()
            
            # Get scheduled payments due today
            scheduled_payments = PaymentIntent.objects.filter(
                status='SCHEDULED',
                metadata__scheduled_date__lte=today.isoformat()
            )
            
            executed = []
            for payment in scheduled_payments:
                try:
                    # Update status to processing
                    payment.status = 'PROCESSING'
                    payment.save()
                    
                    # Process payment
                    result = PaymentProcessor.process_payment(payment)
                    
                    if result['success']:
                        payment.mark_success(result.get('gateway_data', {}))
                        executed.append({
                            'payment_id': payment.reference_id,
                            'amount': payment.amount,
                            'status': 'success'
                        })
                    else:
                        payment.mark_failed(result.get('error', 'Scheduled payment failed'))
                        executed.append({
                            'payment_id': payment.reference_id,
                            'amount': payment.amount,
                            'status': 'failed'
                        })
                        
                except Exception as e:
                    logger.error(f"Error executing scheduled payment {payment.reference_id}: {str(e)}")
                    executed.append({
                        'payment_id': payment.reference_id,
                        'amount': payment.amount,
                        'status': 'error',
                        'error': str(e)
                    })
            
            return {
                'success': True,
                'executed': executed,
                'total': len(executed)
            }
            
        except Exception as e:
            logger.error(f"Error executing scheduled payments: {str(e)}")
            return {'success': False, 'error': str(e), 'executed': []}