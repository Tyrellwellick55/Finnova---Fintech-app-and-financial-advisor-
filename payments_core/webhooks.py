# payments_core/webhooks.py
import json
import logging
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from decimal import Decimal

from .models import PaymentIntent
from .services.payment_processor import PaymentProcessor

logger = logging.getLogger(__name__)

@csrf_exempt
@require_POST
def razorpay_webhook(request):
    """
    Handle Razorpay webhook
    """
    try:
        # Verify webhook signature (implement based on Razorpay docs)
        # payload = json.loads(request.body)
        
        # For now, accept all webhooks
        payload = json.loads(request.body)
        
        event = payload.get('event')
        
        if event == 'payment.captured':
            payment_data = payload['payload']['payment']['entity']
            order_id = payment_data['order_id']
            
            try:
                payment_intent = PaymentIntent.objects.get(gateway_order_id=order_id)
                payment_intent.mark_success({
                    'payment_id': payment_data['id'],
                    'method': payment_data['method'],
                    'bank': payment_data.get('bank'),
                    'card_id': payment_data.get('card_id'),
                })
                
                logger.info(f"Razorpay webhook: Payment captured for order {order_id}")
                
            except PaymentIntent.DoesNotExist:
                logger.error(f"Razorpay webhook: PaymentIntent not found for order {order_id}")
                
        elif event == 'payment.failed':
            payment_data = payload['payload']['payment']['entity']
            order_id = payment_data['order_id']
            
            try:
                payment_intent = PaymentIntent.objects.get(gateway_order_id=order_id)
                payment_intent.mark_failed(
                    payment_data.get('error_description', 'Payment failed')
                )
                
                logger.info(f"Razorpay webhook: Payment failed for order {order_id}")
                
            except PaymentIntent.DoesNotExist:
                logger.error(f"Razorpay webhook: PaymentIntent not found for order {order_id}")
        
        return HttpResponse(status=200)
        
    except json.JSONDecodeError:
        logger.error("Razorpay webhook: Invalid JSON")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Razorpay webhook error: {str(e)}")
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)

@csrf_exempt
@require_POST
def upi_webhook(request):
    """
    Handle UPI payment webhook
    """
    try:
        payload = json.loads(request.body)
        
        txn_ref = payload.get('txn_ref')
        status = payload.get('status')
        amount = Decimal(payload.get('amount', '0'))
        
        if not txn_ref:
            return JsonResponse({'error': 'Missing transaction reference'}, status=400)
        
        try:
            payment_intent = PaymentIntent.objects.get(reference_id=txn_ref)
            
            if status == 'SUCCESS':
                payment_intent.mark_success({
                    'payment_id': payload.get('transaction_id'),
                    'method': 'UPI',
                    'vpa': payload.get('vpa'),
                })
            else:
                payment_intent.mark_failed(payload.get('error_message', 'UPI payment failed'))
            
            logger.info(f"UPI webhook: Payment {txn_ref} status updated to {status}")
            
        except PaymentIntent.DoesNotExist:
            logger.error(f"UPI webhook: PaymentIntent not found for reference {txn_ref}")
            return JsonResponse({'error': 'Payment not found'}, status=404)
        
        return HttpResponse(status=200)
        
    except json.JSONDecodeError:
        logger.error("UPI webhook: Invalid JSON")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"UPI webhook error: {str(e)}")
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)

@csrf_exempt
@require_POST
def stripe_webhook(request):
    """
    Handle Stripe webhook
    """
    try:
        payload = json.loads(request.body)
        event_type = payload.get('type')
        
        if event_type == 'payment_intent.succeeded':
            payment_data = payload['data']['object']
            payment_intent_id = payment_data['id']
            
            try:
                payment_intent = PaymentIntent.objects.get(gateway_order_id=payment_intent_id)
                payment_intent.mark_success({
                    'payment_id': payment_data['id'],
                    'method': 'card',
                    'card_brand': payment_data.get('charges', {}).get('data', [{}])[0].get('payment_method_details', {}).get('card', {}).get('brand'),
                })
                
                logger.info(f"Stripe webhook: Payment succeeded for {payment_intent_id}")
                
            except PaymentIntent.DoesNotExist:
                logger.error(f"Stripe webhook: PaymentIntent not found for {payment_intent_id}")
                
        elif event_type == 'payment_intent.payment_failed':
            payment_data = payload['data']['object']
            payment_intent_id = payment_data['id']
            
            try:
                payment_intent = PaymentIntent.objects.get(gateway_order_id=payment_intent_id)
                payment_intent.mark_failed(
                    payment_data.get('last_payment_error', {}).get('message', 'Payment failed')
                )
                
                logger.info(f"Stripe webhook: Payment failed for {payment_intent_id}")
                
            except PaymentIntent.DoesNotExist:
                logger.error(f"Stripe webhook: PaymentIntent not found for {payment_intent_id}")
        
        return HttpResponse(status=200)
        
    except json.JSONDecodeError:
        logger.error("Stripe webhook: Invalid JSON")
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Stripe webhook error: {str(e)}")
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)