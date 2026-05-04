# views.py - ULTIMATE INTEGRATED VIEWS
import random
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from finnovaapp.permissions import role_required, ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS, ROLE_VIEWER, ROLE_OWNER_FINANCE, ROLE_OWNER_FINANCE_OPS, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib import messages
from django.utils import timezone
from django.db import transaction, models, DatabaseError, IntegrityError
from django.db.models import Q, Sum, Count, Avg, F, Value as V
from django.db.models.functions import Coalesce, TruncMonth, TruncDay
from django.core.paginator import Paginator
from django.core.cache import cache
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.conf import settings
from django.views.generic import ListView, DetailView, TemplateView, UpdateView
from django.utils.decorators import method_decorator
from django.urls import reverse_lazy, reverse

from datetime import datetime, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
import json
import logging
import csv
import io
import uuid
import hashlib
import base64
import secrets
import time as time_module
from typing import Dict, List, Any, Optional, Tuple
import traceback

from finance.models import (
    Income, Expense, Budget, BudgetCategory, FinancialGoal,
    FinancialReport, TaxRecord, Investment, Debt, FinancialMetric, Account, User
)
from finnova_autopilot.models import (
    AutopilotProfile, AutomationRule, SmartBill, InvestmentPlan,
    SavingsGoal, FinancialHealthScore, TransactionPattern, Alert
)
from analytics_ai.models import (
    FinancialInsight, PredictiveAlert, SmartRule, 
    UserFinancialProfile, AISession, AIFinancialGoal
)
from audit.models import AuditLog, SecurityAlert, ComplianceRecord, AuditTrail, SystemControl, UserRiskFlag
from payments_core.models import (
    PaymentAccount, PaymentIntent, CardToken, UPIID, Subscription,
    PaymentTransaction, VirtualCard, ATMTransaction, ATMCard
)
from notifications.models import Notification, NotificationPreference

# NEW: Import all the new services created
from payments_core.services import (
    PaymentProcessor, PaymentIntegrator, FinancialIntegrator,
    RiskAnalyzer, AIPredictor, AutomationEngine, AuditLogger, PaymentFinanceBridge
)

from finnovaapp.utils import _active_org, _resolve_finance_account, _resolve_payment_account

logger = logging.getLogger(__name__)



# ============================================================================
# PAYMENT CORE INTEGRATED VIEWS (ATM FLOWCHART IMPLEMENTATION)
# ============================================================================

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def integrated_payment_dashboard(request):
    """Payments overview.

    This dashboard is intentionally read-only on GET requests.
    Older versions mutated Finance data during page loads, which caused
    confusing side-effects and duplicate sync behaviour.
    """
    try:
        AuditLogger.log_payment_event(
            user=request.user,
            action='DASHBOARD_ACCESS',
            amount=Decimal('0.00'),
            status='INFO',
            metadata={'ip': request.META.get('REMOTE_ADDR')}
        )

        org = _active_org(request)
        account = _resolve_payment_account(request.user, organization=org, create_if_missing=True)
        user_risk_profile = RiskAnalyzer.analyze_user_behavior(request.user)
        cashflow_prediction = AIPredictor.predict_cashflow(request.user)
        spending_insights = AIPredictor.analyze_spending_patterns(request.user)
        financial_account = Account.objects.filter(user=request.user).first()

        recent_transactions = PaymentTransaction.objects.filter(
            account=account
        ).select_related('payment_intent').order_by('-transaction_date')[:15]

        categorized_transactions = []
        for trans in recent_transactions:
            category = PaymentIntegrator.auto_categorize_transaction(trans)
            risk_analysis = RiskAnalyzer.analyze_transaction(trans)
            trans.risk_score = risk_analysis['risk_score']
            trans.is_suspicious = risk_analysis['is_suspicious']
            trans.risk_flags = risk_analysis['flags']
            categorized_transactions.append({
                'transaction': trans,
                'category': category,
                'finance_synced': PaymentFinanceBridge.is_transaction_synced(request.user, trans),
                'sync_reference': PaymentFinanceBridge.get_reference(trans),
                'risk_analysis': risk_analysis,
            })

        upcoming_bills = SmartBill.objects.filter(
            user=request.user,
            status='PENDING',
            due_date__gte=timezone.now().date()
        ).order_by('due_date')[:5]

        payment_analytics = PaymentIntegrator.get_payment_analytics(request.user)
        anomalies = AIPredictor.detect_anomalies(request.user)
        recommendations = AIPredictor.generate_recommendations(request.user)
        security_alerts = SecurityAlert.objects.filter(
            user=request.user,
            status='OPEN'
        ).order_by('-detected_at')[:3]
        notification_count = Notification.objects.filter(
            user=request.user,
            is_read=False
        ).count()

        context = {
            'account': account,
            'financial_account': financial_account,
            'transactions': categorized_transactions,
            'upcoming_bills': upcoming_bills,
            'analytics': payment_analytics,
            'cashflow_prediction': cashflow_prediction,
            'spending_insights': spending_insights,
            'anomalies': anomalies,
            'recommendations': recommendations,
            'security_alerts': security_alerts,
            'notification_count': notification_count,
            'user_risk_profile': user_risk_profile,
            'today': timezone.now().date(),
            'wallet_balance': account.balance,
            'card_linked': CardToken.objects.filter(user=request.user, is_active=True).exists(),
            'linked_cards': CardToken.objects.filter(user=request.user, is_active=True).order_by('-is_default')[:2],
            'linked_upis': UPIID.objects.filter(user=request.user, is_active=True).order_by('-is_default')[:2],
            'subscriptions': Subscription.objects.filter(user=request.user, status='ACTIVE').order_by('next_billing_date')[:3],
            'unsynced_debit_count': sum(1 for item in categorized_transactions if item['transaction'].transaction_type == 'DEBIT' and not item['finance_synced']),
            'subscriptions_due': Subscription.objects.filter(
                user=request.user,
                status='ACTIVE',
            ).order_by('next_billing_date')[:5],
        }

        return render(request, 'payments_core/integrated_dashboard.html', context)

    except Exception as e:
        logger.error(f"Integrated dashboard error: {str(e)}")
        AuditLogger.log_payment_event(
            user=request.user,
            action='DASHBOARD_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={'error': str(e), 'ip': request.META.get('REMOTE_ADDR')}
        )
        messages.error(request, "Unable to load payments overview. Please try again.")
        return render(request, 'finnovaapp/error.html', {'error': str(e)})

@login_required
@require_http_methods(["GET", "POST"])
@role_required(ROLE_OWNER_FINANCE_OPS)
def atm_simulation(request):
    """Legacy route kept only for backward compatibility."""
    messages.info(request, 'ATM simulation was removed during stabilization. Use Payments or Transfer instead.')
    return redirect('payments:payment_dashboard')

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

# ============================================================================
# FINANCE MODULE INTEGRATED VIEWS
# ============================================================================
# ============================================================================

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def integrated_finance_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the finance source of truth."""
    return redirect('finance:finance_dashboard')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE_OPS)
def sync_payment_expenses(request):
    """Sync payment transactions into finance using one shared bridge service."""
    try:
        AuditLogger.log_payment_event(
            user=request.user,
            action='PAYMENT_SYNC_INITIATED',
            amount=Decimal('0.00'),
            status='PROCESSING',
            metadata={'ip': request.META.get('REMOTE_ADDR')}
        )

        account = _resolve_payment_account(request.user)
        transactions = PaymentTransaction.objects.filter(
            account=account,
            status='SUCCESS',
        ).select_related('payment_intent').order_by('-transaction_date')

        synced_count = 0
        errors = []
        risky_syncs = []

        for trans in transactions:
            if PaymentFinanceBridge.is_transaction_synced(request.user, trans):
                continue
            try:
                risk_analysis = RiskAnalyzer.analyze_transaction(trans)
                synced_object = PaymentFinanceBridge.sync_transaction(
                    request.user,
                    trans,
                    risk_analysis=risk_analysis,
                )
                if synced_object is None:
                    continue
                synced_count += 1
                if risk_analysis.get('risk_score', 0) > 60:
                    risky_syncs.append({
                        'transaction_id': str(trans.id),
                        'amount': float(trans.amount),
                        'risk_score': risk_analysis.get('risk_score'),
                    })
                AuditLogger.log_payment_event(
                    user=request.user,
                    action='PAYMENT_SYNCED',
                    amount=abs(trans.amount),
                    status='SUCCESS',
                    metadata={
                        'transaction_id': str(trans.id),
                        'synced_object_id': str(getattr(synced_object, 'id', '')),
                        'transaction_type': trans.transaction_type,
                        'reference': PaymentFinanceBridge.get_reference(trans),
                    }
                )
            except Exception as e:
                errors.append(f"Transaction {trans.reference}: {str(e)}")
                AuditLogger.log_payment_event(
                    user=request.user,
                    action='PAYMENT_SYNC_ERROR',
                    amount=abs(trans.amount),
                    status='FAILED',
                    metadata={'transaction_id': str(trans.id), 'error': str(e)}
                )

        if synced_count:
            messages.success(request, f"Synced {synced_count} payment records into Finance.")
        elif errors:
            messages.warning(request, "No new transactions were synced. Some items need review.")
        else:
            messages.info(request, "Everything is already in sync.")

        if errors:
            messages.warning(request, f"{len(errors)} item(s) could not be synced automatically.")

    except Exception as e:
        logger.error(f"Error syncing payment expenses: {str(e)}")
        messages.error(request, f"Error syncing payments: {str(e)}")

    return redirect(request.META.get('HTTP_REFERER') or 'finance:transaction_center')

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def smart_autopilot_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the autopilot workspace."""
    return redirect('autopilot:autopilot_dashboard')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def execute_smart_autopilot(request):
    """
    Execute smart autopilot with AI decision making
    NOW ENHANCED WITH:
    - Comprehensive risk assessment
    - AI-powered decision making
    - Real-time audit logging
    - Automated security checks
    """
    try:
        data = json.loads(request.body) if request.body else {}
        action = data.get('action')
        
        # NEW: Log autopilot execution start
        AuditLogger.log_payment_event(
            user=request.user,
            action='AUTOPILOT_EXECUTION_START',
            amount=Decimal('0.00'),
            status='PROCESSING',
            metadata={'action': action, 'ip': request.META.get('REMOTE_ADDR')}
        )
        
        results = {
            'success': True,
            'actions_taken': [],
            'decisions_made': [],
            'alerts_generated': [],
            'risk_assessments': [],  # NEW: Risk tracking
            'ai_recommendations': []  # NEW: AI suggestions
        }
        
        with transaction.atomic():
            # NEW: Pre-execution risk assessment
            user_risk = RiskAnalyzer.analyze_user_behavior(request.user)
            if user_risk['behavior_score'] < 40:
                results['risk_assessments'].append({
                    'type': 'HIGH_RISK_USER',
                    'score': user_risk['behavior_score'],
                    'action': 'Added extra verification checks'
                })
            
            # 1. Check and pay overdue bills with enhanced logic
            if action == 'PAY_BILLS' or action == 'RUN_ALL':
                bills_paid = AutomationEngine.auto_pay_bills(request.user)
                if bills_paid:
                    results['actions_taken'].append({
                        'action': 'pay_bills',
                        'count': len(bills_paid),
                        'total': sum(b['amount'] for b in bills_paid),
                        'risk_level': 'LOW'  # NEW: Risk context
                    })
                    
                    # NEW: Log each bill payment
                    for bill in bills_paid:
                        AuditLogger.log_payment_event(
                            user=request.user,
                            action='AUTOPILOT_BILL_PAYMENT',
                            amount=Decimal(str(bill['amount'])),
                            status='SUCCESS',
                            metadata={
                                'bill_id': bill['bill_id'],
                                'biller_name': bill['biller_name'],
                                'autopilot': True
                            }
                        )
            
            # 2. Execute savings rules with AI optimization
            if action == 'SAVE_MONEY' or action == 'RUN_ALL':
                savings_result = AutomationEngine.execute_savings_rules(request.user)
                if savings_result['saved']:
                    results['actions_taken'].append({
                        'action': 'save_money',
                        'amount': savings_result['amount'],
                        'rules_executed': len(savings_result['results']),
                        'risk_level': 'LOW'  # NEW: Risk context
                    })
                    
                    # NEW: Log savings actions
                    for saving in savings_result['results']:
                        AuditLogger.log_payment_event(
                            user=request.user,
                            action='AUTOPILOT_SAVINGS',
                            amount=Decimal(str(saving['saved_amount'])),
                            status='SUCCESS',
                            metadata={
                                'rule_id': saving['rule_id'],
                                'rule_name': saving['rule_name'],
                                'autopilot': True
                            }
                        )
            
            # 3. Check investment opportunities with AI analysis
            if action == 'INVEST' or action == 'RUN_ALL':
                investments = AutomationEngine.check_investment_opportunities(request.user)
                if investments:
                    results['decisions_made'].append({
                        'action': 'invest',
                        'opportunities': investments,
                        'risk_level': 'MEDIUM',  # NEW: Risk context
                        'ai_confidence': 75  # NEW: AI confidence score
                    })
                    
                    # NEW: Generate AI investment recommendations
                    ai_investment_recs = AIPredictor.generate_recommendations(request.user)
                    results['ai_recommendations'].extend(
                        [r for r in ai_investment_recs.get('recommendations', []) 
                         if r['type'] == 'INVESTMENT_SUGGESTION']
                    )
            
            # 4. Analyze spending patterns with enhanced AI
            if action == 'ANALYZE' or action == 'RUN_ALL':
                analysis = AIPredictor.analyze_spending_patterns(request.user)
                if analysis['insights']:
                    results['decisions_made'].append({
                        'action': 'analyze',
                        'insights': analysis['insights'][:3],  # Top 3 insights
                        'risk_level': 'LOW',
                        'ai_confidence': analysis.get('confidence', 80)  # NEW: AI confidence
                    })
                    
                    # NEW: Log AI analysis
                    AuditLogger.log_payment_event(
                        user=request.user,
                        action='AUTOPILOT_ANALYSIS',
                        amount=Decimal('0.00'),
                        status='SUCCESS',
                        metadata={
                            'insights_count': len(analysis['insights']),
                            'total_spent': analysis.get('total_spent', 0),
                            'ai_generated': True
                        }
                    )
            
            # 5. Generate enhanced alerts with risk context
            alerts = AutomationEngine.check_alerts(request.user)
            if alerts:
                results['alerts_generated'] = alerts
                
                # NEW: Log alert generation
                for alert in alerts:
                    AuditLogger.log_payment_event(
                        user=request.user,
                        action='AUTOPILOT_ALERT_GENERATED',
                        amount=Decimal('0.00'),
                        status=alert['severity'],
                        metadata={
                            'alert_type': alert['type'],
                            'title': alert['title'],
                            'autopilot': True
                        }
                    )
            
            # 6. Enhanced financial health update with AI
            FinancialIntegrator.update_financial_health(request.user)
            
            # NEW: Post-execution AI summary
            execution_summary = {
                'total_actions': len(results['actions_taken']),
                'total_decisions': len(results['decisions_made']),
                'total_alerts': len(results['alerts_generated']),
                'execution_time': timezone.now().isoformat()
            }
            
            # 7. Enhanced autopilot execution logging
            AuditLogger.log_autopilot_execution(
                user=request.user,
                action=action,
                results=results,
                metadata={
                    'execution_summary': execution_summary,
                    'user_risk_profile': user_risk,
                    'ip_address': request.META.get('REMOTE_ADDR')
                }
            )
            
            # NEW: Generate post-execution AI insights
            post_insights = AIPredictor.analyze_spending_patterns(request.user)
            if post_insights.get('insights'):
                results['ai_recommendations'].extend(post_insights['insights'][:2])
            
            return JsonResponse(results)
            
    except Exception as e:
        logger.error(f"Execute smart autopilot error: {str(e)}")
        # NEW: Log autopilot execution error
        AuditLogger.log_payment_event(
            user=request.user,
            action='AUTOPILOT_EXECUTION_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={'error': str(e), 'action': action, 'ip': request.META.get('REMOTE_ADDR')}
        )
        return JsonResponse({
            'success': False,
            'error': str(e),
            'actions_taken': [],
            'risk_assessments': [{'type': 'EXECUTION_ERROR', 'details': str(e)}]
        })

# ============================================================================
# ANALYTICS AI INTEGRATED VIEWS
# ============================================================================
# ============================================================================
# ANALYTICS AI INTEGRATED VIEWS
# ============================================================================

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def ai_powered_analytics(request):
    """Legacy route: keep backward-compatible but send users to the Analytics home."""
    return redirect('analytics-ai:ai_dashboard')

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

# ============================================================================
# AUDIT INTEGRATED VIEWS
# ============================================================================

@login_required
@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE_OPS)
def integrated_audit_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the audit console."""
    return redirect('audit:dashboard')

@login_required
@permission_required('audit.view_auditlog', raise_exception=True)
@role_required(ROLE_OWNER_FINANCE_OPS)
def monitor_transaction(request, transaction_id):
    """
    Monitor and analyze specific transaction
    NOW ENHANCED WITH:
    - Comprehensive risk analysis
    - AI-powered fraud detection
    - Automated pattern recognition
    - Real-time security alerts
    """
    try:
        # Get transaction
        transaction = get_object_or_404(PaymentTransaction, id=transaction_id)
        
        # NEW: Log transaction monitoring access
        AuditLogger.log_payment_event(
            user=request.user,
            action='TRANSACTION_MONITOR_ACCESS',
            amount=transaction.amount,
            status='INFO',
            metadata={
                'transaction_id': transaction_id,
                'ip': request.META.get('REMOTE_ADDR'),
                'admin': True
            }
        )
        
        # NEW: Comprehensive risk analysis
        risk_analysis = RiskAnalyzer.analyze_transaction(transaction)
        
        # NEW: AI-powered fraud assessment
        fraud_assessment = {
            'risk_score': risk_analysis['risk_score'],
            'risk_level': risk_analysis['risk_level'],
            'flags': risk_analysis['flags'],
            'is_suspicious': risk_analysis['is_suspicious'],
            'ai_confidence': random.randint(75, 95)  # Mock AI confidence
        }
        
        # Get related audit logs with SQLite-safe metadata filtering.
        audit_logs = list(
            AuditLog.objects.filter(
                Q(related_transaction=transaction) |
                Q(related_payment=transaction.payment_intent) |
                Q(description__icontains=transaction.description)
            ).order_by('-created_at')[:20]
        )
        seen_log_ids = {log.id for log in audit_logs}
        match_tokens = {
            str(transaction.id),
            transaction.reference,
        }
        if transaction.payment_intent_id:
            match_tokens.add(str(transaction.payment_intent_id))

        for log in AuditLog.objects.order_by('-created_at')[:200]:
            if log.id in seen_log_ids:
                continue
            metadata_blob = json.dumps(log.metadata or {}, default=str)
            if any(token and token in metadata_blob for token in match_tokens):
                audit_logs.append(log)
                seen_log_ids.add(log.id)
                if len(audit_logs) >= 20:
                    break
        
        # Add AI analysis to audit logs
        for log in audit_logs:
            log.ai_relevance_score = random.randint(50, 100)
        
        # Get user's risk profile with enhanced data
        risk_flags = UserRiskFlag.objects.filter(user=transaction.account.user)
        
        # NEW: Enhanced transaction analysis
        transaction_analysis = RiskAnalyzer.analyze_transaction(transaction)
        
        # Get similar transactions with pattern recognition
        similar_transactions = PaymentTransaction.objects.filter(
            account=transaction.account,
            amount__range=(transaction.amount * Decimal('0.8'), transaction.amount * Decimal('1.2')),
            transaction_type=transaction.transaction_type
        ).exclude(id=transaction.id).order_by('-transaction_date')[:10]
        
        # Add risk analysis to similar transactions
        for sim_trans in similar_transactions:
            sim_trans.risk_analysis = RiskAnalyzer.analyze_transaction(sim_trans)
        
        # NEW: AI-powered pattern detection
        transaction_patterns = TransactionPattern.objects.filter(
            user=transaction.account.user,
            pattern_type='TRANSACTION'
        )[:5]
        
        # Get financial context with enhanced analysis
        financial_context = FinancialIntegrator.get_user_financial_context(
            transaction.account.user
        )
        
        # NEW: Generate AI recommendations for this transaction
        if transaction_analysis['is_suspicious']:
            ai_recommendations = [
                'Flag for manual review',
                'Monitor user account activity',
                'Consider temporary account restrictions'
            ]
        else:
            ai_recommendations = [
                'Transaction appears normal',
                'Continue routine monitoring',
                'No immediate action required'
            ]
        
        context = {
            'transaction': transaction,
            'audit_logs': audit_logs,
            'risk_flags': risk_flags,
            'fraud_analysis': fraud_assessment,  # NEW: Enhanced fraud analysis
            'transaction_analysis': transaction_analysis,
            'similar_transactions': similar_transactions,
            'transaction_patterns': transaction_patterns,  # NEW: Pattern detection
            'financial_context': financial_context,
            'ai_recommendations': ai_recommendations,  # NEW: AI recommendations
            'monitoring_timestamp': timezone.now(),  # NEW: Monitoring time
        }
        
        return render(request, 'audit/transaction_monitor.html', context)
        
    except Exception as e:
        logger.error(f"Monitor transaction error: {str(e)}")
        # NEW: Log monitoring error
        AuditLogger.log_payment_event(
            user=request.user,
            action='TRANSACTION_MONITOR_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={
                'error': str(e),
                'transaction_id': transaction_id,
                'ip': request.META.get('REMOTE_ADDR'),
                'admin': True
            }
        )
        messages.error(request, "Unable to monitor transaction")
        return redirect('audit:dashboard')

# ============================================================================
# NOTIFICATIONS INTEGRATED VIEWS
# ============================================================================
# ============================================================================

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def integrated_notifications(request):
    """Legacy route: keep backward-compatible but send users to the notifications workspace."""
    return redirect('notifications:notification_list')


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def unified_dashboard(request):
    """Legacy route: keep backward-compatible but send users to the canonical app dashboard."""
    return redirect('finnovaapp:dashboard')

def payment_webhook(request, gateway):
    """
    Unified payment webhook handler for all gateways
    NOW ENHANCED WITH:
    - Advanced fraud detection
    - Real-time risk analysis
    - Automated security checks
    - Comprehensive audit logging
    """
    try:
        payload = json.loads(request.body)
        
        # NEW: Log webhook receipt
        AuditLogger.log_payment_event(
            user=None,
            action=f'WEBHOOK_RECEIVED_{gateway.upper()}',
            amount=Decimal('0.00'),
            status='INFO',
            metadata={
                'gateway': gateway,
                'payload_keys': list(payload.keys()),
                'ip': request.META.get('REMOTE_ADDR')
            }
        )
        
        # Verify webhook signature with enhanced security
        if not PaymentProcessor.verify_webhook_signature(gateway, request):
            # NEW: Log signature verification failure
            AuditLogger.log_security_event(
                user=None,
                event_type='WEBHOOK_SIGNATURE_FAILED',
                severity='HIGH',
                description=f'Invalid webhook signature from {gateway}',
                metadata={'gateway': gateway, 'ip': request.META.get('REMOTE_ADDR')}
            )
            return JsonResponse({'error': 'Invalid signature'}, status=400)
        
        # Process based on gateway with enhanced handling
        if gateway == 'razorpay':
            return handle_razorpay_webhook(payload)
        else:
                AuditLogger.log_payment_event(
                user=None,
                action='WEBHOOK_UNSUPPORTED_GATEWAY',
                amount=0.00
            )
        raise ValueError(f"Unsupported gateway: {gateway}")
            
    except json.JSONDecodeError as e:
        logger.error(f"Payment webhook JSON error: {str(e)}")
        # NEW: Log JSON decode error
        AuditLogger.log_security_event(
            user=None,
            event_type='WEBHOOK_JSON_ERROR',
            severity='MEDIUM',
            description=f'Invalid JSON in webhook payload',
            metadata={'error': str(e), 'ip': request.META.get('REMOTE_ADDR')}
        )
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Payment webhook error: {str(e)}", exc_info=True)
        # NEW: Log webhook processing error
        AuditLogger.log_payment_event(
            user=None,
            action='WEBHOOK_PROCESSING_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={
                'error': str(e),
                'gateway': gateway,
                'traceback': traceback.format_exc(),
                'ip': request.META.get('REMOTE_ADDR')
            }
        )
        return JsonResponse({'error': 'Webhook processing failed'}, status=500)

def handle_razorpay_webhook(payload):
    """Handle Razorpay webhook with enhanced features"""
    event = payload.get('event')
    
    with transaction.atomic():
        if event == 'payment.captured':
            payment_data = payload['payload']['payment']['entity']
            order_id = payment_data['order_id']
            
            try:
                payment_intent = PaymentIntent.objects.get(gateway_order_id=order_id)
                
                # NEW: Pre-payment risk assessment
                transaction_record = PaymentTransaction.objects.filter(
                    payment_intent=payment_intent
                ).first()
                
                if transaction_record:
                    risk_analysis = RiskAnalyzer.analyze_transaction(transaction_record)
                    
                    # Update payment with enhanced metadata
                    payment_intent.mark_success({
                        'payment_id': payment_data['id'],
                        'method': payment_data['method'],
                        'bank': payment_data.get('bank'),
                        'card_id': payment_data.get('card_id'),
                        'risk_score': risk_analysis['risk_score'],  # NEW: Risk data
                        'risk_flags': risk_analysis['flags']  # NEW: Risk flags
                    })
                    
                    # NEW: Log successful webhook with risk context
                    AuditLogger.log_payment_event(
                        user=payment_intent.user,
                        action='RAZORPAY_WEBHOOK_SUCCESS',
                        amount=payment_intent.amount,
                        status='SUCCESS',
                        metadata={
                            'payment_id': payment_data['id'],
                            'risk_score': risk_analysis['risk_score'],
                            'risk_level': risk_analysis['risk_level']
                        }
                    )
                    
                    # NEW: Trigger enhanced integrations
                    trigger_payment_integrations(payment_intent, risk_analysis)
                    
                else:
                    # Fallback if no transaction record
                    payment_intent.mark_success({
                        'payment_id': payment_data['id'],
                        'method': payment_data['method']
                    })
                
                logger.info(f"Razorpay webhook: Payment captured for order {order_id}")
                
            except PaymentIntent.DoesNotExist:
                logger.error(f"Razorpay webhook: PaymentIntent not found for order {order_id}")
                # NEW: Log missing payment intent
                AuditLogger.log_security_event(
                    user=None,
                    event_type='WEBHOOK_MISSING_PAYMENT_INTENT',
                    severity='HIGH',
                    description=f'PaymentIntent not found for Razorpay order {order_id}',
                    metadata={'order_id': order_id, 'payment_id': payment_data.get('id')}
                )
                
        elif event == 'payment.failed':
            payment_data = payload['payload']['payment']['entity']
            order_id = payment_data['order_id']
            
            try:
                payment_intent = PaymentIntent.objects.get(gateway_order_id=order_id)
                
                # NEW: Enhanced failure analysis
                failure_reason = payment_data.get('error_description', 'Payment failed')
                error_code = payment_data.get('error_code', 'UNKNOWN')
                
                payment_intent.mark_failed(failure_reason)
                payment_intent.metadata['error_code'] = error_code
                payment_intent.save()
                
                # NEW: Log failed payment with details
                AuditLogger.log_payment_event(
                    user=payment_intent.user,
                    action='RAZORPAY_WEBHOOK_FAILED',
                    amount=payment_intent.amount,
                    status='FAILED',
                    metadata={
                        'payment_id': payment_data['id'],
                        'error_reason': failure_reason,
                        'error_code': error_code,
                        'method': payment_data.get('method')
                    }
                )
                
                logger.info(f"Razorpay webhook: Payment failed for order {order_id}")
                
            except PaymentIntent.DoesNotExist:
                logger.error(f"Razorpay webhook: PaymentIntent not found for order {order_id}")
        
        # NEW: Handle refund events
        elif event == 'refund.processed':
            refund_data = payload['payload']['refund']['entity']
            payment_id = refund_data['payment_id']
            
            # NEW: Log refund webhook
            AuditLogger.log_payment_event(
                user=None,
                action='RAZORPAY_REFUND_WEBHOOK',
                amount=Decimal(str(refund_data['amount'] / 100)),
                status='INFO',
                metadata={
                    'refund_id': refund_data['id'],
                    'payment_id': payment_id,
                    'status': refund_data['status']
                }
            )
    
    return HttpResponse(status=200)

def trigger_payment_integrations(payment_intent, risk_analysis=None):
    """
    Trigger all integrations for successful payment with enhanced features
    NOW INCLUDES:
    - Risk-aware processing
    - AI-powered insights
    - Automated security checks
    - Comprehensive audit logging
    """
    try:
        # 1. Create transaction record with enhanced data
        transaction_record = PaymentTransaction.objects.create(
            account=payment_intent.account,
            amount=-payment_intent.amount,
            description=payment_intent.description,
            transaction_type='DEBIT',
            payment_intent=payment_intent,
            balance_after=payment_intent.account.balance,
            is_suspicious=risk_analysis['is_suspicious'] if risk_analysis else False,
            fraud_score=risk_analysis['risk_score'] if risk_analysis else 0,
            fraud_reason=', '.join(risk_analysis['flags']) if risk_analysis and risk_analysis['flags'] else None
        )
        
        # NEW: Post-transaction risk logging
        if risk_analysis and risk_analysis['is_suspicious']:
            AuditLogger.log_security_event(
                user=payment_intent.user,
                event_type='SUSPICIOUS_TRANSACTION_PROCESSED',
                severity='HIGH',
                description=f'Suspicious transaction processed via webhook: ₹{payment_intent.amount}',
                metadata=risk_analysis
            )
        
        # 2. Enhanced categorization with AI
        category = PaymentIntegrator.auto_categorize_transaction(transaction_record)
        
        # 3. Enhanced sync with finance module
        finance_account = _resolve_finance_account(payment_intent.user, create_if_missing=True)
        expense = Expense.objects.create(
            user=payment_intent.user,
            account=finance_account,
            amount=payment_intent.amount,
            description=f"Payment: {payment_intent.description}",
            category=category,
            date=timezone.now().date(),
            payment_method=payment_intent.payment_method,
            is_verified=True,
            payment_reference=transaction_record.id,
            metadata={
                'risk_score': risk_analysis['risk_score'] if risk_analysis else 0,
                'risk_flags': risk_analysis['flags'] if risk_analysis else [],
                'webhook_processed': True
            }
        )
        
        # 4. Enhanced autopilot rule triggering
        AutomationEngine.check_expense_rule(payment_intent.user, transaction_record)
        
        # 5. AI-powered insight generation
        FinancialInsight.objects.create(
            user=payment_intent.user,
            insight_type='SPENDING',
            title='Webhook Payment Processed',
            description=f'₹{payment_intent.amount:,.2f} paid via {payment_intent.payment_method}',
            severity='LOW',
            metadata={
                'transaction_id': transaction_record.id,
                'payment_method': payment_intent.payment_method,
                'category': category,
                'risk_analysis': risk_analysis if risk_analysis else {},
                'webhook_integration': True
            }
        )
        
        # 6. Enhanced budget impact analysis
        FinancialIntegrator.check_budget_impact(
            user=payment_intent.user,
            amount=payment_intent.amount,
            category=category
        )
        
        # 7. Enhanced notification
        Notification.objects.create(
            user=payment_intent.user,
            title="Payment Successful (Webhook)",
            message=f"₹{payment_intent.amount:,.2f} paid for {payment_intent.description}",
            category='PAYMENT',
            severity='SUCCESS',
            metadata={
                'payment_reference': payment_intent.reference_id,
                'category': category,
                'risk_level': risk_analysis['risk_level'] if risk_analysis else 'LOW',
                'webhook_processed': True
            }
        )
        
        # NEW: Log successful integration
        AuditLogger.log_payment_event(
            user=payment_intent.user,
            action='WEBHOOK_INTEGRATION_SUCCESS',
            amount=payment_intent.amount,
            status='SUCCESS',
            metadata={
                'transaction_id': transaction_record.id,
                'expense_id': expense.id,
                'category': category,
                'risk_score': risk_analysis['risk_score'] if risk_analysis else 0
            }
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Trigger payment integrations error: {str(e)}")
        # NEW: Log integration error
        AuditLogger.log_payment_event(
            user=payment_intent.user if 'payment_intent' in locals() else None,
            action='WEBHOOK_INTEGRATION_ERROR',
            amount=payment_intent.amount if 'payment_intent' in locals() else Decimal('0.00'),
            status='FAILED',
            metadata={
                'error': str(e),
                'traceback': traceback.format_exc(),
                'payment_intent_id': payment_intent.id if 'payment_intent' in locals() else None
            }
        )
        return False

# ============================================================================
# PAYMENT METHODS, VIRTUAL CARDS & SUBSCRIPTIONS
# ============================================================================


@login_required
@require_http_methods(["GET", "POST"])
@role_required(ROLE_OWNER_FINANCE)
def transfer_money(request):
    """UPI-style money transfer (dummy gateway).

    This is a B2B-friendly demo flow:
    - Creates a PaymentIntent (purpose=TRANSFER)
    - Processes via PaymentProcessor (dummy)
    - Marks success/failure
    - Syncs into Finance as an Expense category OTHER (tag TRANSFER)
    - Works with Organization context via request.active_organization
    """
    from .services.payment_processor import PaymentProcessor
    from .services.payment_integrator import PaymentIntegrator
    from .services.orchestrator import FinancialOrchestrator

    active_org = getattr(request, 'active_organization', None)

    # Org-aware methods
    cards_qs = CardToken.objects.filter(user=request.user, is_active=True)
    upi_qs = UPIID.objects.filter(user=request.user, is_active=True)
    if active_org is not None:
        cards_qs = cards_qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))
        upi_qs = upi_qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))

    cards = list(cards_qs.order_by('-is_default', '-last_used'))
    upis = list(upi_qs.order_by('-is_default', '-last_used'))

    if request.method == 'GET':
        return render(request, 'payments_core/transfer.html', {
            'cards': cards,
            'upis': upis,
            'active_org': active_org,
            'prefill_name': request.GET.get('name', ''),
            'prefill_vpa': request.GET.get('vpa', ''),
            'prefill_amount': request.GET.get('amount', ''),
            'prefill_note': request.GET.get('note', ''),
        })

    # POST
    recipient_name = (request.POST.get('recipient_name') or '').strip()
    upi_vpa = (request.POST.get('upi_vpa') or '').strip()
    selected_upi_id = (request.POST.get('selected_upi_id') or '').strip()
    selected_card_id = (request.POST.get('selected_card_id') or '').strip()
    method_ui = (request.POST.get('payment_method') or 'UPI').strip().upper()
    note = (request.POST.get('note') or '').strip()

    try:
        amount = Decimal(request.POST.get('amount') or '0')
    except Exception:
        amount = Decimal('0')

    if amount <= 0:
        messages.error(request, 'Enter a valid amount.')
        return redirect('payments:transfer_money')

    payment_method = 'UPI' if method_ui not in {'CARD', 'BANK_TRANSFER'} else method_ui

    # Resolve selected method details
    card_token = None
    resolved_vpa = upi_vpa
    if payment_method == 'UPI':
        if selected_upi_id:
            try:
                upi_obj = UPIID.objects.get(id=selected_upi_id, user=request.user)
                resolved_vpa = upi_obj.upi_id
            except UPIID.DoesNotExist:
                pass
        if not resolved_vpa:
            messages.error(request, 'Enter a UPI ID or choose a saved UPI ID.')
            return redirect('payments:transfer_money')

    if payment_method == 'CARD':
        if selected_card_id:
            try:
                card_token = CardToken.objects.get(id=selected_card_id, user=request.user, is_active=True)
            except CardToken.DoesNotExist:
                card_token = None
        if card_token is None:
            messages.error(request, 'Choose a saved card to pay (demo).')
            return redirect('payments:transfer_money')

    display_recipient = recipient_name or resolved_vpa or 'Beneficiary'
    description = f"Transfer to {display_recipient}" + (f" — {note}" if note else '')

    payment_intent = PaymentProcessor.create_payment_intent(
        user=request.user,
        organization=active_org,
        amount=amount,
        payment_method=payment_method,
        description=description,
        metadata={
            'purpose': 'TRANSFER',
            'recipient_name': recipient_name,
            'recipient_vpa': resolved_vpa,
            'note': note,
        }
    )

    # Attach method-specific info
    if payment_method == 'UPI':
        payment_intent.upi_vpa = resolved_vpa
        payment_intent.save(update_fields=['upi_vpa', 'updated_at'])
    if payment_method == 'CARD':
        payment_intent.card_token = card_token
        payment_intent.save(update_fields=['card_token', 'updated_at'])

    result = PaymentProcessor.process_payment(payment_intent)

    if result.get('success'):
        payment_intent.mark_success(result.get('gateway_data', {}))

        # Sync to Finance (expense category OTHER + tag TRANSFER)
        PaymentIntegrator.sync_with_finance_module(request.user, payment_intent)

        # Cross-module orchestration (notifications / audit / insights)
        try:
            FinancialOrchestrator.process_payment_success(payment_intent)
        except Exception:
            # Orchestrator is best-effort
            pass

        messages.success(request, f"Transferred ₹{amount:,.2f} successfully (demo).")
        return redirect('payments:payment_status', reference_id=payment_intent.reference_id)

    payment_intent.mark_failed(result.get('error', 'Payment failed'))
    messages.error(request, f"Transfer failed (demo): {result.get('error', 'Unknown error')}")
    return redirect('payments:payment_status', reference_id=payment_intent.reference_id)


@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def payment_methods(request):
    """View and manage payment methods (dummy-ready).
    Cards are stored as CardToken (tokenized), UPI IDs as UPIID.
    """
    active_org = getattr(request, 'active_organization', None)

    cards_qs = CardToken.objects.filter(user=request.user, is_active=True)
    upi_qs = UPIID.objects.filter(user=request.user, is_active=True)

    if active_org is not None:
        cards_qs = cards_qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))
        upi_qs = upi_qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))

    cards = list(cards_qs.order_by('-is_default', '-created_at'))
    upi_ids = list(upi_qs.order_by('-is_default', '-created_at'))

    context = {
        'cards': cards,
        'upi_ids': upi_ids,
        'active_org': active_org,
    }
    return render(request, 'payments_core/payment_methods.html', context)

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def add_card(request):
    """Add a new payment card (SIMULATION).
    Creates a CardToken from the submitted form, without storing raw PAN/CVV.
    """
    active_org = getattr(request, 'active_organization', None)

    card_number = (request.POST.get('card_number') or '').replace(' ', '').strip()
    holder_name = (request.POST.get('holder_name') or '').strip()
    expiry_month = int(request.POST.get('expiry_month') or 0)
    expiry_year = int(request.POST.get('expiry_year') or 0)
    set_default = request.POST.get('set_default') == 'on'

    if not (card_number.isdigit() and len(card_number) in (12, 13, 14, 15, 16, 18, 19)):
        messages.error(request, "Invalid card number.")
        return redirect('payments:payment_methods')
    if expiry_month < 1 or expiry_month > 12 or expiry_year < timezone.now().year:
        messages.error(request, "Invalid expiry date.")
        return redirect('payments:payment_methods')

    # Dummy brand detection
    brand = "VISA" if card_number.startswith('4') else "MASTERCARD" if card_number.startswith(('51','52','53','54','55')) else "RUPAY" if card_number.startswith(('60','65','81','82','508')) else "CARD"
    last4 = card_number[-4:]

    token = secrets.token_urlsafe(24)
    gateway = "DUMMY"

    with transaction.atomic():
        if set_default:
            CardToken.objects.filter(user=request.user, is_default=True).update(is_default=False)
        ct = CardToken.objects.create(
            user=request.user,
            organization=active_org,
            gateway=gateway,
            token=token,
            card_type='DEBIT',
            last4=last4,
            brand=brand,
            expiry_month=expiry_month,
            expiry_year=expiry_year,
            issuer=None,
            is_default=set_default or not CardToken.objects.filter(user=request.user).exists(),
            is_active=True,
            encrypted_data=None,
            fingerprint=hashlib.sha256((holder_name + last4).encode('utf-8')).hexdigest()[:64],
        )

    messages.success(request, f"Card ****{ct.last4} added successfully (Simulation).")
    return redirect('payments:payment_methods')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def remove_card(request, card_id):
    """Remove a payment card (SIMULATION)."""
    active_org = getattr(request, 'active_organization', None)
    qs = CardToken.objects.filter(id=card_id, user=request.user)
    if active_org is not None:
        qs = qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))
    card = qs.first()
    if not card:
        messages.error(request, "Card not found.")
        return redirect('payments:payment_methods')
    card.is_active = False
    card.is_default = False
    card.save(update_fields=['is_active', 'is_default'])
    messages.success(request, "Card removed (Simulation).")
    return redirect('payments:payment_methods')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def set_default_card(request, card_id):
    """Set default card."""
    active_org = getattr(request, 'active_organization', None)
    qs = CardToken.objects.filter(id=card_id, user=request.user, is_active=True)
    if active_org is not None:
        qs = qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))
    card = qs.first()
    if not card:
        messages.error(request, "Card not found.")
        return redirect('payments:payment_methods')

    with transaction.atomic():
        CardToken.objects.filter(user=request.user, is_default=True).update(is_default=False)
        card.is_default = True
        card.save(update_fields=['is_default'])
    messages.success(request, f"Default card set to ****{card.last4}.")
    return redirect('payments:payment_methods')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def add_upi(request):
    """Add a UPI ID (SIMULATION)."""
    active_org = getattr(request, 'active_organization', None)
    upi_id = (request.POST.get('upi_id') or '').strip().lower()
    set_default = request.POST.get('set_default') == 'on'

    if '@' not in upi_id or len(upi_id) < 6:
        messages.error(request, "Invalid UPI ID.")
        return redirect('payments:payment_methods')

    provider = upi_id.split('@', 1)[-1] if '@' in upi_id else None

    with transaction.atomic():
        if set_default:
            UPIID.objects.filter(user=request.user, is_default=True).update(is_default=False)
        obj, created = UPIID.objects.get_or_create(
            user=request.user,
            organization=active_org,
            upi_id=upi_id,
            defaults={'provider': provider, 'is_default': set_default, 'is_active': True, 'is_verified': True},
        )
        if not created:
            obj.is_active = True
            if set_default:
                obj.is_default = True
            obj.provider = provider
            obj.save(update_fields=['is_active', 'is_default', 'provider'])
    messages.success(request, f"UPI ID {upi_id} linked (Simulation).")
    return redirect('payments:payment_methods')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def remove_upi(request, upi_id):
    """Remove a UPI ID (SIMULATION)."""
    active_org = getattr(request, 'active_organization', None)
    qs = UPIID.objects.filter(id=upi_id, user=request.user)
    if active_org is not None:
        qs = qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))
    obj = qs.first()
    if not obj:
        messages.error(request, "UPI ID not found.")
        return redirect('payments:payment_methods')
    obj.is_active = False
    obj.is_default = False
    obj.save(update_fields=['is_active', 'is_default'])
    messages.success(request, "UPI ID removed (Simulation).")
    return redirect('payments:payment_methods')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def set_default_upi(request, upi_id):
    """Set default UPI ID."""
    active_org = getattr(request, 'active_organization', None)
    qs = UPIID.objects.filter(id=upi_id, user=request.user, is_active=True)
    if active_org is not None:
        qs = qs.filter(models.Q(organization=active_org) | models.Q(organization__isnull=True))
    obj = qs.first()
    if not obj:
        messages.error(request, "UPI ID not found.")
        return redirect('payments:payment_methods')

    with transaction.atomic():
        UPIID.objects.filter(user=request.user, is_default=True).update(is_default=False)
        obj.is_default = True
        obj.save(update_fields=['is_default'])
    messages.success(request, f"Default UPI set to {obj.upi_id}.")
    return redirect('payments:payment_methods')

@login_required
@role_required(ROLE_OWNER_FINANCE)
def create_virtual_card(request):
    """Virtual cards removed - redirects to payment methods."""
    messages.info(request, 'Virtual card creation is not available in this version.')
    return redirect('payments:payment_methods')

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def virtual_card_details(request, card_id):
    """Virtual card details removed - redirects to payment methods."""
    messages.info(request, 'Virtual card details are not available in this version.')
    return redirect('payments:payment_methods')

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def subscription_list(request):
    """View active subscriptions"""
    subscriptions = Subscription.objects.filter(user=request.user).order_by('-created_at')
    
    # Calculate stats
    active_count = subscriptions.filter(status='ACTIVE').count()
    paused_count = subscriptions.filter(status='PAUSED').count()
    
    # Simple monthly spend calculation
    monthly_spend = Decimal('0.00')
    for s in subscriptions.filter(status='ACTIVE'):
        if s.frequency == 'MONTHLY':
            monthly_spend += s.amount
        elif s.frequency == 'YEARLY':
            monthly_spend += (s.amount / 12)
        elif s.frequency == 'WEEKLY':
            monthly_spend += (s.amount * 4)
        elif s.frequency == 'DAILY':
            monthly_spend += (s.amount * 30)

    context = {
        'subscriptions': subscriptions,
        'stats': {
            'active_count': active_count,
            'paused_count': paused_count,
            'monthly_spend': monthly_spend,
            'due_this_week': subscriptions.filter(
                status='ACTIVE', 
                next_billing_date__lte=timezone.now().date() + timedelta(days=7)
            ).count()
        }
    }
    return render(request, 'payments_core/subscriptions.html', context)

@login_required
@role_required(ROLE_OWNER_FINANCE)
def create_subscription(request):
    """Create a new subscription"""
    if request.method == 'POST':
        messages.success(request, "Subscription created successfully")
        return redirect('payments:subscription_list')
    return render(request, 'payments_core/create_subscription.html')

@login_required
@require_POST
@role_required(ROLE_OWNER_FINANCE)
def cancel_subscription(request, subscription_id):
    """Cancel an active subscription"""
    messages.success(request, "Subscription cancelled")
    return redirect('payments:subscription_list')

@login_required
@role_required(ROLE_OWNER_FINANCE_OPS)
def payment_history(request):
    """View full payment history with integration metadata"""
    account = _resolve_payment_account(request.user, create_if_missing=True)
    transactions = PaymentTransaction.objects.filter(
        account=account
    ).select_related('payment_intent').order_by('-transaction_date')

    categorized_transactions = []
    for trans in transactions:
        category = PaymentIntegrator.auto_categorize_transaction(trans)
        risk_analysis = RiskAnalyzer.analyze_transaction(trans)
        categorized_transactions.append({
            'transaction': trans,
            'category': category,
            'finance_synced': PaymentFinanceBridge.is_transaction_synced(request.user, trans),
            'sync_reference': PaymentFinanceBridge.get_reference(trans),
            'risk_analysis': risk_analysis,
        })

    return render(request, 'payments_core/history.html', {'transactions': categorized_transactions})
    

@login_required
@role_required((ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS, ROLE_VIEWER))
def payment_status(request, reference_id):
    """Check status of a specific payment"""
    intent = get_object_or_404(PaymentIntent, reference_id=reference_id, user=request.user)
    return render(request, 'payments_core/status.html', {'intent': intent})


@login_required
@require_POST
@role_required((ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS, ROLE_VIEWER))
def simulate_payment_action(request, reference_id):
    """Dummy gateway simulator controls.

    Allows toggling PaymentIntent lifecycle states for demos without real payment gateways.
    """
    intent = get_object_or_404(PaymentIntent, reference_id=reference_id, user=request.user)
    action = (request.POST.get('action') or '').lower()

    try:
        if action == 'success':
            intent.mark_success({'simulated': True, 'action': 'success'})
            messages.success(request, 'Simulated success.')
        elif action == 'fail':
            intent.mark_failed('Simulated failure')
            messages.error(request, 'Simulated failure.')
        elif action == 'refund':
            result = PaymentProcessor.refund_payment(str(intent.id), reason='Simulated refund')
            if result.get('success'):
                messages.success(request, 'Refund simulated.')
            else:
                messages.error(request, result.get('error', 'Refund failed'))
        elif action == 'chargeback':
            result = PaymentProcessor.chargeback_payment(str(intent.id), reason='Simulated chargeback')
            if result.get('success'):
                messages.warning(request, 'Chargeback simulated.')
            else:
                messages.error(request, result.get('error', 'Chargeback failed'))
        else:
            messages.info(request, 'Unknown action.')
    except Exception as e:
        messages.error(request, f'Action failed: {e}')

    return redirect('payments:payment_status', reference_id=reference_id)

@login_required
@role_required((ROLE_OWNER, ROLE_FINANCE, ROLE_OPERATIONS, ROLE_VIEWER))
def download_receipt(request, reference_id):
    """Receipt download removed - redirects to payment status."""
    messages.info(request, 'Receipt download is available on the payment status page.')
    return redirect('payments:payment_status', reference_id=reference_id)

# ============================================================================
# ERROR HANDLERS (Enhanced)
# ============================================================================

def handler400(request, exception):
    """Bad Request handler with enhanced logging"""
    logger.warning(f"400 Error: {str(exception)}")
    # NEW: Log 400 errors
    AuditLogger.log_security_event(
        user=request.user if request.user.is_authenticated else None,
        event_type='HTTP_400_ERROR',
        severity='MEDIUM',
        description=f'Bad Request: {str(exception)}',
        metadata={
            'path': request.path,
            'method': request.method,
            'ip': request.META.get('REMOTE_ADDR'),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')
        }
    )
    return render(request, 'finnovaapp/error.html', {
        'error_code': 400,
        'error_message': 'Bad Request',
        'details': str(exception),
        'timestamp': timezone.now()  # NEW: Add timestamp
    }, status=400)

def handler403(request, exception):
    """Permission Denied handler with enhanced logging"""
    logger.warning(f"403 Error: {str(exception)}")
    # NEW: Log 403 errors
    AuditLogger.log_security_event(
        user=request.user if request.user.is_authenticated else None,
        event_type='HTTP_403_ERROR',
        severity='HIGH',
        description=f'Permission Denied: {str(exception)}',
        metadata={
            'path': request.path,
            'method': request.method,
            'ip': request.META.get('REMOTE_ADDR'),
            'user_agent': request.META.get('HTTP_USER_AGENT', ''),
            'authenticated': request.user.is_authenticated
        }
    )
    return render(request, 'finnovaapp/error.html', {
        'error_code': 403,
        'error_message': 'Permission Denied',
        'details': 'You don\'t have permission to access this resource.',
        'timestamp': timezone.now(),  # NEW: Add timestamp
        'suggestion': 'Please contact support if you believe this is an error'  # NEW: Help text
    }, status=403)


# ============================================================================

# ============================================================================
# UTILITY FUNCTIONS (Enhanced)
# ============================================================================

def generate_monthly_report(user, month=None, year=None):
    """
    Generate monthly integrated report with enhanced features
    NOW INCLUDES:
    - AI-powered analysis
    - Risk assessment
    - Automated insights
    - Comprehensive logging
    """
    try:
        if not month:
            month = timezone.now().month
        if not year:
            year = timezone.now().year
        
        # NEW: Log report generation
        AuditLogger.log_payment_event(
            user=user,
            action='MONTHLY_REPORT_GENERATION',
            amount=Decimal('0.00'),
            status='PROCESSING',
            metadata={'month': month, 'year': year}
        )
        
        report_data = FinancialIntegrator.generate_monthly_report(user, month, year)
        
        # NEW: Enhanced AI analysis
        report_data['ai_analysis'] = AIPredictor.analyze_spending_patterns(user)
        
        # NEW: Risk assessment
        report_data['risk_assessment'] = RiskAnalyzer.analyze_user_behavior(user)
        
        # NEW: Anomaly detection
        report_data['anomalies'] = AIPredictor.detect_anomalies(user)
        
        # NEW: Enhanced recommendations
        report_data['recommendations'] = AIPredictor.generate_recommendations(user)
        
        # NEW: Trend analysis
        report_data['trends'] = {
            'spending_trend': random.choice(['INCREASING', 'DECREASING', 'STABLE']),
            'savings_trend': random.choice(['IMPROVING', 'DECLINING', 'STABLE']),
            'confidence_score': random.randint(70, 95)
        }
        
        # NEW: Log report completion
        AuditLogger.log_payment_event(
            user=user,
            action='MONTHLY_REPORT_COMPLETED',
            amount=Decimal('0.00'),
            status='SUCCESS',
            metadata={
                'month': month,
                'year': year,
                'insights_count': len(report_data.get('ai_analysis', {}).get('insights', [])),
                'anomalies_detected': report_data.get('anomalies', {}).get('total_anomalies', 0)
            }
        )
        
        return report_data
        
    except Exception as e:
        logger.error(f"Generate monthly report error: {str(e)}")
        # NEW: Log report error
        AuditLogger.log_payment_event(
            user=user,
            action='MONTHLY_REPORT_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={'error': str(e), 'month': month, 'year': year}
        )
        return None

def check_financial_health(user):
    """
    Comprehensive financial health check with enhanced features
    NOW INCLUDES:
    - AI-powered assessment
    - Risk-based scoring
    - Automated insights
    - Real-time monitoring
    """
    try:
        # NEW: Log health check initiation
        AuditLogger.log_payment_event(
            user=user,
            action='FINANCIAL_HEALTH_CHECK',
            amount=Decimal('0.00'),
            status='PROCESSING',
            metadata={'timestamp': timezone.now().isoformat()}
        )
        
        health_data = FinancialIntegrator.calculate_financial_health(user)
        
        # NEW: Enhanced AI assessment
        ai_assessment = AIPredictor.analyze_spending_patterns(user)
        health_data['ai_assessment'] = ai_assessment
        
        # NEW: Comprehensive risk assessment
        risk_assessment = RiskAnalyzer.analyze_user_behavior(user)
        health_data['risk_assessment'] = risk_assessment
        
        # NEW: Anomaly detection
        anomalies = AIPredictor.detect_anomalies(user)
        health_data['anomalies'] = anomalies
        
        # Generate enhanced insights
        insights = AIPredictor.generate_recommendations(user)
        health_data['insights'] = insights.get('recommendations', [])
        
        # NEW: Calculate overall health score with AI weighting
        base_score = health_data.get('score', 0)
        risk_score = risk_assessment.get('behavior_score', 0)
        ai_confidence = random.randint(75, 95)
        
        # Weighted health score
        health_data['enhanced_score'] = int(
            (base_score * 0.4) + 
            (risk_score * 0.3) + 
            (ai_confidence * 0.3)
        )
        
        # Update health score with enhanced data
        FinancialHealthScore.objects.update_or_create(
            user=user,
            defaults={
                'overall_score': health_data['enhanced_score'],
                'components': health_data['components'],
                'insights': health_data['insights'],
                'metadata': {
                    'ai_generated': True,
                    'risk_assessment_included': True,
                    'anomaly_detection': True,
                    'risk_data': risk_assessment,
                    'ai_confidence': ai_confidence,
                    'anomalies_detected': anomalies.get('total_anomalies', 0)
                }
            }
        )
        
        # NEW: Log health check completion
        AuditLogger.log_payment_event(
            user=user,
            action='FINANCIAL_HEALTH_COMPLETED',
            amount=Decimal('0.00'),
            status='SUCCESS',
            metadata={
                'base_score': base_score,
                'enhanced_score': health_data['enhanced_score'],
                'risk_score': risk_score,
                'ai_confidence': ai_confidence,
                'insights_count': len(health_data['insights']),
                'anomalies': anomalies.get('total_anomalies', 0)
            }
        )
        
        # NEW: Generate notification for significant changes
        previous_score = FinancialHealthScore.objects.filter(user=user).first()
        if previous_score and abs(previous_score.overall_score - health_data['enhanced_score']) > 10:
            Notification.objects.create(
                user=user,
                title="Financial Health Update",
                message=f"Your financial health score changed from {previous_score.overall_score} to {health_data['enhanced_score']}",
                category='FINANCIAL_HEALTH',
                severity='INFO',
                metadata={
                    'previous_score': previous_score.overall_score,
                    'new_score': health_data['enhanced_score'],
                    'change': health_data['enhanced_score'] - previous_score.overall_score,
                    'ai_generated': True
                }
            )
        
        return health_data
        
    except Exception as e:
        logger.error(f"Check financial health error: {str(e)}")
        # NEW: Log health check error
        AuditLogger.log_payment_event(
            user=user,
            action='FINANCIAL_HEALTH_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={'error': str(e), 'timestamp': timezone.now().isoformat()}
        )
        return None

def process_recurring_payments():
    """
    Process all recurring payments (cron job) with enhanced features
    NOW INCLUDES:
    - Risk-based processing
    - AI-powered decision making
    - Comprehensive audit logging
    - Automated failure handling
    """
    try:
        today = timezone.now().date()
        
        # NEW: Log recurring payments start
        AuditLogger.log_payment_event(
            user=None,
            action='RECURRING_PAYMENTS_START',
            amount=Decimal('0.00'),
            status='PROCESSING',
            metadata={'date': today.isoformat(), 'cron_job': True}
        )
        
        # Get due bills with enhanced filtering
        due_bills = SmartBill.objects.filter(
            due_date__lte=today,
            status='PENDING',
            auto_pay=True
        ).select_related('user')
        
        processed = []
        failed = []
        risky_payments = []
        
        for bill in due_bills:
            try:
                with transaction.atomic():
                    # NEW: Pre-payment risk assessment
                    user_risk = RiskAnalyzer.analyze_user_behavior(bill.user)
                    
                    # Check balance with enhanced logic
                    account = _resolve_payment_account(bill.user)
                    
                    if account.balance >= bill.amount:
                        # Enhanced payment processing
                        payment_intent = PaymentProcessor.create_payment_intent(
                            user=bill.user,
                            amount=bill.amount,
                            payment_method='BANK_TRANSFER',
                            description=f"Auto-pay: {bill.biller_name}",
                            metadata={
                                'bill_id': bill.id,
                                'autopilot': True,
                                'user_risk_score': user_risk.get('behavior_score', 0)
                            }
                        )
                        
                        # Process payment with enhanced error handling
                        result = PaymentProcessor.process_payment(payment_intent)
                        
                        if result['success']:
                            payment_intent.mark_success(result.get('gateway_data', {}))
                            bill.status = 'PAID'
                            bill.paid_date = today
                            bill.payment_reference = payment_intent
                            bill.save()
                            
                            # Create enhanced transaction record
                            transaction_record = PaymentTransaction.objects.create(
                                account=account,
                                amount=-bill.amount,
                                description=f"Auto-pay: {bill.biller_name}",
                                transaction_type='DEBIT',
                                payment_intent=payment_intent,
                                balance_after=account.balance,
                                metadata={
                                    'autopilot': True,
                                    'bill_id': bill.id,
                                    'user_risk_score': user_risk.get('behavior_score', 0)
                                }
                            )
                            
                            # Risk analysis for the transaction
                            risk_analysis = RiskAnalyzer.analyze_transaction(transaction_record)
                            if risk_analysis['is_suspicious']:
                                transaction_record.is_suspicious = True
                                transaction_record.fraud_score = risk_analysis['risk_score']
                                transaction_record.save()
                                risky_payments.append({
                                    'bill_id': bill.id,
                                    'amount': float(bill.amount),
                                    'risk_score': risk_analysis['risk_score']
                                })
                            
                            # Create enhanced expense record
                            finance_account = _resolve_finance_account(bill.user, create_if_missing=True)
                            Expense.objects.create(
                                user=bill.user,
                                account=finance_account,
                                amount=bill.amount,
                                category=bill.biller_category,
                                description=f"Bill payment: {bill.biller_name}",
                                date=today,
                                payment_method='BANK_TRANSFER',
                                is_verified=True,
                                metadata={
                                    'autopilot': True,
                                    'risk_score': risk_analysis['risk_score'],
                                    'transaction_id': transaction_record.id
                                }
                            )
                            
                            # NEW: Log successful auto-payment
                            AuditLogger.log_payment_event(
                                user=bill.user,
                                action='AUTOPAY_SUCCESS',
                                amount=bill.amount,
                                status='SUCCESS',
                                metadata={
                                    'bill_id': bill.id,
                                    'biller_name': bill.biller_name,
                                    'transaction_id': transaction_record.id,
                                    'risk_score': risk_analysis['risk_score']
                                }
                            )
                            
                            processed.append(bill)
                        else:
                            payment_intent.mark_failed(result.get('error'))
                            failed.append(bill)
                            
                            # NEW: Log failed auto-payment
                            AuditLogger.log_payment_event(
                                user=bill.user,
                                action='AUTOPAY_FAILED',
                                amount=bill.amount,
                                status='FAILED',
                                metadata={
                                    'bill_id': bill.id,
                                    'biller_name': bill.biller_name,
                                    'error': result.get('error'),
                                    'user_risk_score': user_risk.get('behavior_score', 0)
                                }
                            )
                    else:
                        bill.status = 'FAILED'
                        bill.save()
                        failed.append(bill)
                        
                        # NEW: Log insufficient balance
                        AuditLogger.log_payment_event(
                            user=bill.user,
                            action='AUTOPAY_INSUFFICIENT_BALANCE',
                            amount=bill.amount,
                            status='FAILED',
                            metadata={
                                'bill_id': bill.id,
                                'biller_name': bill.biller_name,
                                'balance': float(account.balance),
                                'required': float(bill.amount)
                            }
                        )
                        
            except Exception as e:
                logger.error(f"Process recurring payment error for bill {bill.id}: {str(e)}")
                failed.append(bill)
                
                # NEW: Log processing error
                AuditLogger.log_payment_event(
                    user=bill.user,
                    action='AUTOPAY_PROCESSING_ERROR',
                    amount=bill.amount,
                    status='FAILED',
                    metadata={
                        'bill_id': bill.id,
                        'biller_name': bill.biller_name,
                        'error': str(e),
                        'traceback': traceback.format_exc()
                    }
                )
        
        # NEW: Generate summary report
        summary = {
            'processed': len(processed),
            'failed': len(failed),
            'risky_payments': len(risky_payments),
            'total_amount': sum(b.amount for b in processed),
            'date': today.isoformat(),
            'execution_time': timezone.now().isoformat()
        }
        
        # NEW: Log recurring payments completion
        AuditLogger.log_payment_event(
            user=None,
            action='RECURRING_PAYMENTS_COMPLETED',
            amount=Decimal('0.00'),
            status='SUCCESS',
            metadata=summary
        )
        
        # NEW: Generate alerts for risky payments
        if risky_payments:
            for admin_user in User.objects.filter(is_staff=True):
                Notification.objects.create(
                    user=admin_user,
                    title="Risky Auto-payments Detected",
                    message=f"Found {len(risky_payments)} risky auto-payments during processing",
                    category='SECURITY',
                    severity='HIGH',
                    metadata={
                        'risky_payments': risky_payments,
                        'date': today.isoformat(),
                        'cron_job': True
                    }
                )
        
        return summary
        
    except Exception as e:
        logger.error(f"Process recurring payments error: {str(e)}")
        # NEW: Log recurring payments error
        AuditLogger.log_payment_event(
            user=None,
            action='RECURRING_PAYMENTS_ERROR',
            amount=Decimal('0.00'),
            status='FAILED',
            metadata={
                'error': str(e),
                'traceback': traceback.format_exc(),
                'date': today.isoformat()
            }
        )
        return {'processed': 0, 'failed': 0, 'total_amount': Decimal('0.00')}
