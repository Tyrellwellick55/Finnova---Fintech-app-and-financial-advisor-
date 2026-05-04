# payments_core/subscription_engine.py
from django.utils import timezone
from datetime import timedelta
import logging

from .models import Subscription, PaymentIntent, PaymentAccount
from .services.payment_processor import PaymentProcessor

logger = logging.getLogger(__name__)

def process_due_subscriptions():
    """
    Process all due subscriptions
    """
    try:
        today = timezone.now().date()
        processed_count = 0
        failed_count = 0
        
        # Get active subscriptions that are due
        due_subscriptions = Subscription.objects.filter(
            status='ACTIVE',
            next_billing_date__lte=today
        ).select_related('user', 'account', 'card_token')
        
        for subscription in due_subscriptions:
            try:
                # Check if payment method is available
                if subscription.payment_method == 'CARD' and not subscription.card_token:
                    logger.warning(f"Subscription {subscription.id} has no card token")
                    subscription.status = 'FAILED'
                    subscription.save()
                    failed_count += 1
                    continue
                
                # Create payment intent
                payment_intent = PaymentIntent.objects.create(
                    user=subscription.user,
                    account=subscription.account,
                    reference_id=PaymentIntent.generate_reference_id(),
                    amount=subscription.amount,
                    currency=subscription.currency,
                    payment_method=subscription.payment_method,
                    description=f"Subscription: {subscription.name}",
                    status='PROCESSING',
                    card_token=subscription.card_token if subscription.payment_method == 'CARD' else None,
                    metadata={
                        'subscription_id': str(subscription.id),
                        'frequency': subscription.frequency,
                        'name': subscription.name
                    }
                )
                
                # Process payment
                result = PaymentProcessor.process_payment(payment_intent)
                
                if result['success']:
                    # Mark payment as success
                    payment_intent.mark_success(result.get('gateway_data', {}))
                    
                    # Update subscription
                    subscription.next_billing_date = subscription.calculate_next_billing_date()
                    subscription.retry_count = 0
                    subscription.save()
                    
                    processed_count += 1
                    logger.info(f"Processed subscription {subscription.id} for user {subscription.user.username}")
                else:
                    # Handle payment failure
                    payment_intent.mark_failed(result.get('error', 'Payment failed'))
                    
                    # Increment retry count
                    subscription.retry_count += 1
                    subscription.last_retry_at = timezone.now()
                    
                    # Check if max retries reached
                    if subscription.retry_count >= subscription.max_retries:
                        subscription.status = 'FAILED'
                        logger.warning(f"Subscription {subscription.id} failed after max retries")
                    
                    subscription.save()
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing subscription {subscription.id}: {str(e)}")
                failed_count += 1
                # Update subscription retry count
                subscription.retry_count += 1
                subscription.last_retry_at = timezone.now()
                subscription.save()
        
        return {
            'processed': processed_count,
            'failed': failed_count,
            'total': due_subscriptions.count()
        }
        
    except Exception as e:
        logger.error(f"Error in process_due_subscriptions: {str(e)}")
        return {'processed': 0, 'failed': 0, 'total': 0}

def pause_subscription(subscription_id):
    """Pause a subscription"""
    try:
        subscription = Subscription.objects.get(id=subscription_id)
        subscription.status = 'PAUSED'
        subscription.save()
        return True
    except Subscription.DoesNotExist:
        logger.error(f"Subscription {subscription_id} not found")
        return False
    except Exception as e:
        logger.error(f"Error pausing subscription {subscription_id}: {str(e)}")
        return False

def resume_subscription(subscription_id):
    """Resume a paused subscription"""
    try:
        subscription = Subscription.objects.get(id=subscription_id, status='PAUSED')
        subscription.status = 'ACTIVE'
        subscription.save()
        return True
    except Subscription.DoesNotExist:
        logger.error(f"Subscription {subscription_id} not found or not paused")
        return False
    except Exception as e:
        logger.error(f"Error resuming subscription {subscription_id}: {str(e)}")
        return False