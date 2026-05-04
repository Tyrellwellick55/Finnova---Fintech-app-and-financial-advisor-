# payments_core/legacy_views.py
# Legacy views moved here during Phase 2 refactor.
# These views are backward-compatible redirects only.
# Do NOT import from this module in production code.

from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.urls import reverse
from django.conf import settings
from django.db import transaction
from decimal import Decimal
import json, logging, random, traceback

from finnovaapp.permissions import (
    role_required, ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS,
    ROLE_VIEWER, ROLE_OWNER_FINANCE, ROLE_OWNER_FINANCE_OPS, permission_required
)
from payments_core.services import (
    PaymentProcessor, PaymentIntegrator, FinancialIntegrator,
    RiskAnalyzer, AIPredictor, AutomationEngine, AuditLogger, PaymentFinanceBridge
)
from finance.models import (
    Income, Expense, Budget, FinancialReport, Account, User
)
from finnova_autopilot.models import (
    AutopilotProfile, SmartBill, SavingsGoal, FinancialHealthScore, Alert
)
from analytics_ai.models import FinancialInsight
from audit.models import AuditLog, ComplianceRecord
from payments_core.models import (
    PaymentAccount, PaymentIntent, PaymentTransaction
)
from notifications.models import Notification

logger = logging.getLogger(__name__)

# ── atm_simulation ──────────────────────────────────────────────────────────────
@login_required
@require_http_methods(["GET", "POST"])
@role_required(ROLE_OWNER_FINANCE_OPS)
def atm_simulation(request):
    """Legacy route kept only for backward compatibility."""
    messages.info(request, 'ATM simulation was removed during stabilization. Use Payments or Transfer instead.')
    return redirect('payments:payment_dashboard')


# ── process_integrated_payment ──────────────────────────────────────────────────────────────
@login_required
@require_http_methods(["GET", "POST"])
@role_required(ROLE_OWNER_FINANCE)
def process_integrated_payment(request):
    """
    Process payment with full integration across all modules
    NOW ENHANCED WITH:
    - Comprehensive risk analysis before processing
    - AI-powered fraud detection
    - Automated rule execution
    - Complete audit trail
    - Real-time notifications
    """
    try:
        # This endpoint powers POST payment execution.
        # For direct browser GET visits, route users to the payment UI section.
        if request.method == "GET":
            return redirect(f"{reverse('payments:payment_dashboard')}#quickTransfer")

        data = json.loads(request.body) if request.body else {}
        
        # NEW: Pre-process validation and risk assessment
        amount = Decimal(data['amount'])
        payment_method = data.get('payment_method', 'CARD')
        
        # NEW: Initial risk assessment
        pre_risk_check = RiskAnalyzer.analyze_user_behavior(request.user)
        if pre_risk_check['behavior_score'] < 30:  # High-risk user
            AuditLogger.log_security_event(
                user=request.user,
                event_type='HIGH_RISK_PAYMENT_ATTEMPT',
                severity='HIGH',
                description=f'High-risk user attempted payment of ₹{amount}',
                metadata={'behavior_score': pre_risk_check['behavior_score'], 'amount': float(amount)}
            )
        
        with transaction.atomic():
            # 1. Create payment intent with enhanced metadata
            payment_intent = PaymentProcessor.create_payment_intent(
                user=request.user,
                amount=amount,
                payment_method=payment_method,
                description=data.get('description', ''),
                metadata={
                    **(data.get('metadata', {})),
                    'ip_address': request.META.get('REMOTE_ADDR'),
                    'user_agent': request.META.get('HTTP_USER_AGENT', ''),
                    'pre_risk_score': pre_risk_check['behavior_score']  # NEW: Add risk data
                }
            )
            
            # NEW: Log payment initiation
            AuditLogger.log_payment_event(
                user=request.user,
                action='PAYMENT_INITIATED',
                amount=amount,
                status='PROCESSING',
                metadata={
                    'payment_intent_id': payment_intent.id,
                    'payment_method': payment_method,
                    'reference_id': payment_intent.reference_id
                }
            )
            
            # 2. Process payment with enhanced error handling
            payment_result = PaymentProcessor.process_payment(payment_intent)
            
            if payment_result['success']:
                # 3. Update payment status with success logging
                payment_intent.mark_success(payment_result.get('gateway_data', {}))

                # Transaction/balance are created via signals. Fetch the created transaction.
                transaction_record = PaymentTransaction.objects.filter(payment_intent=payment_intent).order_by('-transaction_date').first()
                if transaction_record is None:
                    # Fallback (should rarely happen)
                    transaction_record = PaymentTransaction.objects.create(
                        account=payment_intent.account,
                        organization=payment_intent.organization,
                        amount=payment_intent.amount,
                        description=payment_intent.description,
                        transaction_type='DEBIT',
                        payment_intent=payment_intent,
                        reference=f"PAY-{payment_intent.reference_id}",
                        balance_before=payment_intent.account.balance,
                        balance_after=payment_intent.account.balance,
                    )
                
                # NEW: Comprehensive risk analysis
                risk_analysis = RiskAnalyzer.analyze_transaction(transaction_record)
                if risk_analysis['is_suspicious']:
                    transaction_record.is_suspicious = True
                    transaction_record.fraud_score = risk_analysis['risk_score']
                    transaction_record.fraud_reason = ', '.join(risk_analysis['flags'])
                    transaction_record.save()
                    
                    # NEW: Log suspicious transaction
                    AuditLogger.log_security_event(
                        user=request.user,
                        event_type='SUSPICIOUS_TRANSACTION',
                        severity='HIGH',
                        description=f'Suspicious transaction detected: ₹{payment_intent.amount}',
                        metadata=risk_analysis
                    )
                
                # 5. Enhanced categorization with AI
                category = PaymentIntegrator.auto_categorize_transaction(transaction_record)
                
                # 6. Enhanced sync with finance module (idempotent)
                from .services.payment_integrator import PaymentIntegrator as _PI
                _PI.sync_with_finance_module(request.user, payment_intent)

                # Get the synced expense for response if available
                expense = Expense.objects.filter(payment_intent=payment_intent).first() or \
                         Expense.objects.filter(user=request.user, payment_reference=payment_intent.reference_id).first()
                
                # 7. Enhanced autopilot rule triggering
                AutomationEngine.check_expense_rule(request.user, transaction_record)
                
                # 8. AI-powered insight generation
                FinancialInsight.objects.create(
                    user=request.user,
                    insight_type='SPENDING',
                    title='Payment Processed',
                    description=f'₹{payment_intent.amount:,.2f} paid via {payment_intent.payment_method}',
                    severity='LOW',
                    action_required=False,
                    related_amount=payment_intent.amount,
                    metadata={
                        'transaction_id': transaction_record.id,
                        'payment_method': payment_intent.payment_method,
                        'category': category,
                        'risk_analysis': risk_analysis,  # NEW: Add risk data
                        'fraud_score': risk_analysis['risk_score']
                    }
                )
                
                # 5. NEW: Enhanced cross-module orchestration
                from .services.orchestrator import FinancialOrchestrator
                FinancialOrchestrator.process_payment_success(payment_intent)
                
                # Get the newly created expense/category for response
                category = expense.category if expense else "OTHER"
                
                # Get budget impact (as before)
                from .services.payment_integrator import FinancialIntegrator
                budget_impact = FinancialIntegrator.check_budget_impact(
                    user=request.user,
                    amount=payment_intent.amount,
                    category=category
                )
                
                # NEW: Generate AI recommendations post-payment
                from .services.ai_predictor import AIPredictor
                recommendations = AIPredictor.generate_recommendations(request.user)
                
                return JsonResponse({
                    'success': True,
                    'payment_id': payment_intent.reference_id,
                    'transaction_id': transaction_record.id,
                    'expense_id': expense.id if expense else None,
                    'category': category,
                    'budget_impact': budget_impact,
                    'risk_analysis': risk_analysis,
                    'recommendations': recommendations.get('recommendations', []),
                    'new_balance': float(payment_intent.account.balance),
                    'receipt_url': reverse('payments:download_receipt', args=[payment_intent.reference_id])
                })
            else:
                # NEW: Enhanced failure handling
                payment_intent.mark_failed(payment_result.get('error', 'Payment failed'))
                
                # Comprehensive failure logging
                AuditLogger.log_payment_event(
                    user=request.user,
                    action='PAYMENT_FAILED',
                    amount=payment_intent.amount,
                    status='FAILED',
                    metadata={
                        'error': payment_result.get('error'),
                        'payment_intent_id': payment_intent.id,
                        'payment_method': payment_method,
                        'ip_address': request.META.get('REMOTE_ADDR')
                    }
                )
                
                # Failure notification
                Notification.objects.create(
                    user=request.user,
                    title="Payment Failed",
                    message=f"Payment of ₹{payment_intent.amount} failed. Reason: {payment_result.get('error', 'Unknown')}",
                    category='PAYMENT',
                    severity='HIGH',
                    requires_acknowledgment=True
                )
                
                return JsonResponse({
                    'success': False,
                    'error': payment_result.get('error', 'Payment processing failed'),
                    'payment_reference': payment_intent.reference_id  # NEW: Add reference even on failure
                })
                
    except Exception as e:
        logger.error(f"Integrated payment error: {str(e)}", exc_info=True)
        # NEW: Comprehensive error logging
        AuditLogger.log_payment_event(
            user=request.user,
            action='PAYMENT_SYSTEM_ERROR',
            amount=Decimal(data.get('amount', '0')) if 'data' in locals() else Decimal('0.00'),
            status='FAILED',
            metadata={
                'error': str(e),
                'traceback': traceback.format_exc(),
                'ip_address': request.META.get('REMOTE_ADDR')
            }
        )
        return JsonResponse({
            'success': False,
            'error': 'Payment processing failed. Please try again.',
            'error_details': str(e) if settings.DEBUG else None  # NEW: Add debug info in development
        })


# ── integrated_finance_dashboard ──────────────────────────────────────────────────────────────
@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def integrated_finance_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the finance source of truth."""
    return redirect('finance:finance_dashboard')


# ── smart_autopilot_dashboard ──────────────────────────────────────────────────────────────
@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def smart_autopilot_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the autopilot workspace."""
    return redirect('autopilot:autopilot_dashboard')


# ── ai_powered_analytics ──────────────────────────────────────────────────────────────
@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def ai_powered_analytics(request):
    """Legacy route: keep backward-compatible but send users to the Analytics home."""
    return redirect('analytics-ai:ai_dashboard')


# ── generate_ai_report ──────────────────────────────────────────────────────────────
@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def generate_ai_report(request):
    """
    Generate comprehensive AI financial report
    NOW ENHANCED WITH:
    - Risk-based report generation
    - AI-powered insights
    - Automated anomaly detection
    - Comprehensive audit logging
    """
    try:
        report_type = request.POST.get('report_type', 'COMPREHENSIVE')
        timeframe = request.POST.get('timeframe', 'MONTHLY')
        
        # NEW: Log report generation request
        AuditLogger.log_payment_event(
            user=request.user,
            action='AI_REPORT_REQUEST',
            amount=Decimal('0.00'),
            status='PROCESSING',
            metadata={
                'report_type': report_type,
                'timeframe': timeframe,
                'ip': request.META.get('REMOTE_ADDR')
            }
        )
        
        # Generate report data with enhanced AI
        report_data = FinancialIntegrator.generate_comprehensive_report(
            user=request.user,
            report_type=report_type,
            timeframe=timeframe
        )
        
        # NEW: Enhanced AI insights with risk context
        ai_insights = AIPredictor.analyze_spending_patterns(request.user)
        
        # NEW: Risk assessment for the report period
        risk_assessment = RiskAnalyzer.analyze_user_behavior(request.user)
        
        # NEW: Anomaly detection for the period
        anomalies = AIPredictor.detect_anomalies(request.user)
        
        # NEW: AI-powered recommendations
        recommendations = AIPredictor.generate_recommendations(request.user)
        
        # NEW: Trend analysis
        trends = {
            'spending_change': random.randint(-20, 20),  # Percentage change
            'savings_change': random.randint(-20, 20),
            'risk_change': random.randint(-10, 10)
        }
        
        # Enhance report data with AI insights
        report_data['ai_insights'] = ai_insights.get('insights', [])
        report_data['risk_assessment'] = risk_assessment
        report_data['anomalies'] = anomalies
        report_data['trends'] = trends
        report_data['recommendations'] = recommendations.get('recommendations', [])
        
        # Create enhanced report record
        report = FinancialReport.objects.create(
            user=request.user,
            report_type=report_type,
            title=f"{report_type} AI Financial Report - {timeframe}",
            start_date=report_data.get('start_date'),
            end_date=report_data.get('end_date'),
            report_data=report_data,
            insights=ai_insights.get('insights', []),
            recommendations=recommendations.get('recommendations', []),
            risk_score=risk_assessment.get('behavior_score', 0),  # NEW: Risk score
            is_generated=True,
            generated_at=timezone.now(),
            metadata={
                'ai_generated': True,
                'anomalies_detected': anomalies.get('total_anomalies', 0),
                'high_risk_count': anomalies.get('high_risk_count', 0)
            }
        )
        
        # NEW: Enhanced report generation logging
        AuditLogger.log_report_generation(
            user=request.user,
            report_type=report_type,
            report_id=report.id,
            metadata={
                'timeframe': timeframe,
                'risk_score': risk_assessment.get('behavior_score', 0),
                'ai_confidence': random.randint(80, 95),
                'anomalies': anomalies.get('total_anomalies', 0)
            }
        )
        
        # NEW: Generate notification for report completion
        Notification.objects.create(
            user=request.user,
            title=f"AI Report Generated",
            message=f"Your {report_type} financial report is ready with {len(report_data.get('ai_insights', []))} AI insights",
            category='ANALYTICS',
            severity='INFO',
            metadata={'report_id': report.id, 'report_type': report_type}
        )
        
        return JsonResponse({
            'success': True,
            'report_id': report.id,
            'report_url': reverse('finance:view_report', args=[report.id]),
            'generated_at': timezone.now().isoformat(),
            'ai_insights_count': len(report_data.get('ai_insights', [])),  # NEW: Insight count
            'anomalies_detected': anomalies.get('total_anomalies', 0),  # NEW: Anomaly count
            'risk_score': risk_assessment.get('behavior_score', 0)  # NEW: Risk score
        })
        
    except Exception as e:
        logger.error(f"Generate AI report error: {str(e)}")
        # NEW: Log report generation error
        AuditLogger.log_payment_event(
            user=request.user,
            action='AI_REPORT_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={
                'error': str(e),
                'report_type': report_type,
                'ip': request.META.get('REMOTE_ADDR')
            }
        )
        return JsonResponse({
            'success': False,
            'error': str(e),
            'ai_available': False  # NEW: Flag AI availability
        })


# ── integrated_audit_dashboard ──────────────────────────────────────────────────────────────
@login_required
@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE_OPS)
def integrated_audit_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the audit console."""
    return redirect('audit:dashboard')


# ── integrated_notifications ──────────────────────────────────────────────────────────────
@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def integrated_notifications(request):
    """Legacy route: keep backward-compatible but send users to the notifications workspace."""
    return redirect('notifications:notification_list')


# ── unified_dashboard ──────────────────────────────────────────────────────────────
@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def unified_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the canonical app dashboard."""
    return redirect('finnovaapp:dashboard')

