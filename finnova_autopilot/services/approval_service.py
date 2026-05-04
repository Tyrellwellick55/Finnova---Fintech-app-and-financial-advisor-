from __future__ import annotations

import logging
from django.utils import timezone

from payments_core.services.payment_processor import PaymentProcessor
from finance.services.posting import post_expense
from eventhub.dispatcher import emit
from finnova_autopilot.models import AutopilotLog

logger = logging.getLogger(__name__)


class ApprovalExecutionService:
    @staticmethod
    def approve(approval, actor):
        if approval.status != 'PENDING':
            return {'success': False, 'message': 'This approval request is no longer pending.'}

        if approval.bill and (approval.bill.status == 'PAID' or approval.bill.payment_reference_id):
            approval.status = 'EXPIRED'
            approval.decided_at = timezone.now()
            approval.decided_by = actor
            approval.save(update_fields=['status', 'decided_at', 'decided_by'])
            AutopilotLog.objects.create(
                user=actor,
                action='APPROVAL_EXPIRED',
                message=f'Approval expired because bill {approval.bill_id} was already paid.',
                status='SKIPPED',
                bill=approval.bill,
                metadata={'approval_id': str(approval.id)},
            )
            return {'success': False, 'message': 'Bill is already paid; approval marked as expired.'}

        payment_intent = PaymentProcessor.create_payment_intent(
            user=actor,
            organization=approval.organization,
            amount=approval.amount,
            payment_method='BANK_TRANSFER',
            description=approval.title,
            metadata={
                **(approval.metadata or {}),
                'source': 'AUTOPILOT',
                'approval_id': str(approval.id),
            },
        )
        result = PaymentProcessor.process_payment(payment_intent)
        if not result.get('success'):
            payment_intent.mark_failed(result.get('error') or 'Autopilot execution failed')
            AutopilotLog.objects.create(
                user=actor,
                action='APPROVAL_EXECUTE',
                message=f'Autopilot approval execution failed for {approval.title}.',
                status='FAILED',
                bill=approval.bill,
                metadata={'approval_id': str(approval.id), 'error': result.get('error')},
            )
            return {'success': False, 'message': result.get('error', 'Unknown error')}

        payment_intent.mark_success(result.get('gateway_data'))

        if approval.bill:
            approval.bill.status = 'PAID'
            approval.bill.paid_date = timezone.now().date()
            approval.bill.payment_reference = payment_intent
            approval.bill.save(update_fields=['status', 'paid_date', 'payment_reference', 'updated_at'])
            try:
                post_expense(
                    organization=approval.organization,
                    user=actor,
                    amount=payment_intent.amount,
                    merchant=approval.bill.biller_name,
                    category=approval.bill.biller_category or 'OTHER',
                    memo=f"Approved autopay: {approval.bill.biller_name}",
                    payment_reference=payment_intent.reference_id,
                    related_payment=payment_intent,
                )
            except Exception:
                logger.exception('Failed posting autopilot approval expense')

        approval.payment_intent = payment_intent
        approval.status = 'APPROVED'
        approval.decided_at = timezone.now()
        approval.decided_by = actor
        approval.save(update_fields=['payment_intent', 'status', 'decided_at', 'decided_by'])

        emit(
            'AUTOPILOT_EXECUTED',
            actor=actor,
            organization=approval.organization,
            idempotency_key=f"autopilot:approval-executed:{approval.id}",
            metadata={
                'approval_id': str(approval.id),
                'payment_intent_id': str(payment_intent.id),
                'amount': float(approval.amount),
                'label': approval.title,
            },
        )
        AutopilotLog.objects.create(
            user=actor,
            action='APPROVAL_EXECUTE',
            message=f'Approved autopilot action: {approval.title}',
            status='SUCCESS',
            bill=approval.bill,
            metadata={'approval_id': str(approval.id), 'payment_intent_id': str(payment_intent.id)},
        )
        return {'success': True, 'payment_intent': payment_intent}

    @staticmethod
    def reject(approval, actor):
        if approval.status != 'PENDING':
            return {'success': False, 'message': 'This approval request is no longer pending.'}
        approval.status = 'REJECTED'
        approval.decided_at = timezone.now()
        approval.decided_by = actor
        approval.save(update_fields=['status', 'decided_at', 'decided_by'])
        AutopilotLog.objects.create(
            user=actor,
            action='APPROVAL_REJECT',
            message=f'Rejected autopilot action: {approval.title}',
            status='BLOCKED',
            bill=approval.bill,
            metadata={'approval_id': str(approval.id)},
        )
        return {'success': True}


class IncomeSplitExecutor:
    """Executes an approved income split plan — records GST reserve, tax reserve,
    and savings contributions in Finance. No outbound payment is made."""

    @staticmethod
    def execute(approval, actor):
        """Called when user approves an income split from income_split.html."""
        from decimal import Decimal
        from finnova_autopilot.models import SavingsGoal

        if approval.status != 'PENDING':
            return {'success': False, 'message': 'Already processed.'}

        meta = approval.metadata or {}
        org = approval.organization

        try:
            # 1. Post GST reserve as a tagged income note (internal)
            gst_amount = Decimal(str(meta.get('gst_amount', '0')))
            if gst_amount > 0:
                from finance.models import Income
                Income.objects.filter(
                    user=actor,
                    description__icontains=meta.get('source_label', ''),
                    amount=Decimal(str(meta.get('gross_amount', '0'))),
                ).update(
                    metadata={
                        **({} if not Income.objects.filter(user=actor).exists() else {}),
                        'gst_reserved': str(gst_amount),
                        'split_approved': True,
                    }
                )

            # 2. Top up each savings goal
            # Bug 4 fix: Use goal_id stored at plan-build time, fall back to goal_name
            savings_allocs = meta.get('savings_allocations', [])
            for alloc in savings_allocs:
                try:
                    goal = None
                    goal_id = alloc.get('goal_id')
                    if goal_id:
                        goal = SavingsGoal.objects.filter(
                            id=goal_id,
                            user=actor,
                        ).first()
                    if goal is None:
                        # Fallback: match by name (legacy plans without goal_id)
                        goal = SavingsGoal.objects.filter(
                            user=actor,
                            goal_name=alloc.get('name', ''),
                        ).first()
                    if goal:
                        contrib = Decimal(str(alloc.get('amount', '0')))
                        goal.current_saved = (goal.current_saved or Decimal('0')) + contrib
                        goal.save(update_fields=['current_saved', 'updated_at'])
                except Exception:
                    logger.exception('Failed updating savings goal for income split')

            # 3. Mark approval done
            from django.utils import timezone
            approval.status = 'APPROVED'
            approval.decided_at = timezone.now()
            approval.decided_by = actor
            approval.save(update_fields=['status', 'decided_at', 'decided_by'])

            AutopilotLog.objects.create(
                user=actor,
                action='INCOME_SPLIT_APPROVED',
                message=f'Income split approved: ₹{meta.get("gross_amount", 0)} received.',
                status='SUCCESS',
                metadata={'approval_id': str(approval.id), 'allocations': len(savings_allocs)},
            )
            return {'success': True}

        except Exception as exc:
            logger.exception('IncomeSplitExecutor failed for approval %s', approval.id)
            return {'success': False, 'message': str(exc)}
