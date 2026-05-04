# payments_core/services/audit_logger.py
import logging
from django.utils import timezone
from datetime import datetime
from decimal import Decimal
from uuid import UUID

logger = logging.getLogger(__name__)

class AuditLogger:
    """Centralized logging for audit trails"""
    
    @staticmethod
    def _make_json_safe(value):
        if isinstance(value, dict):
            return {str(key): AuditLogger._make_json_safe(val) for key, val in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [AuditLogger._make_json_safe(item) for item in value]
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return str(value)
        return value
    
    @staticmethod
    def log_payment_event(user, action, amount, status, metadata=None):
        """Log payment-related events"""
        try:
            from audit.models import AuditLog
            metadata = AuditLogger._make_json_safe(metadata or {})
            
            severity = AuditLogger._get_severity_for_status(status)
            
            AuditLog.objects.create(
                actor=user,
                action=action,
                description=f"{action}: ₹{amount} - {status}",
                severity=severity,
                ip_address=metadata.get('ip_address') if metadata else None,
                user_agent=metadata.get('user_agent') if metadata else None,
                metadata=metadata
            )
            
            logger.info(f"Audit log: {action} by {user.username} - {status}")
            
        except ImportError:
            # Fallback if audit app is not available
            logger.info(f"Payment Audit: {user.username} - {action} - ₹{amount} - {status}")
        except Exception as e:
            logger.error(f"Error logging payment event: {str(e)}")
    
    @staticmethod
    def log_atm_transaction(user, action, amount, status, metadata=None):
        """Log ATM transaction events"""
        try:
            from audit.models import AuditLog
            
            severity = 'MEDIUM' if action == 'BALANCE_INQUIRY' else 'HIGH'
            metadata = AuditLogger._make_json_safe(metadata or {})
            
            AuditLog.objects.create(
                actor=user,
                action=f"ATM_{action}",
                description=f"ATM {action}: ₹{amount} - {status}",
                severity=severity,
                ip_address='ATM_TERMINAL',
                user_agent='ATM_DEVICE',
                metadata=metadata
            )
            
        except ImportError:
            logger.info(f"ATM Audit: {user.username} - {action} - ₹{amount} - {status}")
        except Exception as e:
            logger.error(f"Error logging ATM transaction: {str(e)}")
    
    @staticmethod
    def log_security_event(user, event_type, severity, description, metadata=None):
        """Log security-related events"""
        try:
            from audit.models import AuditLog
            metadata = AuditLogger._make_json_safe(metadata or {})
            
            AuditLog.objects.create(
                actor=user,
                action=f"SECURITY_{event_type}",
                description=description,
                severity=severity,
                ip_address=metadata.get('ip_address') if metadata else None,
                user_agent=metadata.get('user_agent') if metadata else None,
                metadata=metadata
            )
            
            # Also log to security alerts if available
            try:
                from audit.models import SecurityAlert
                SecurityAlert.objects.create(
                    user=user,
                    alert_type=event_type,
                    severity=severity,
                    description=description,
                    metadata=metadata
                )
            except ImportError:
                logger.debug('audit app not installed; skipping audit log')
                
        except ImportError:
            logger.warning(f"Security Event: {user.username} - {event_type} - {severity} - {description}")
        except Exception as e:
            logger.error(f"Error logging security event: {str(e)}")
    
    @staticmethod
    def log_subscription_event(subscription, action, status, metadata=None):
        """Log subscription events"""
        try:
            from audit.models import AuditLog
            metadata = AuditLogger._make_json_safe(metadata or {})
            
            AuditLog.objects.create(
                actor=subscription.user,
                action=f"SUBSCRIPTION_{action}",
                description=f"Subscription {subscription.name}: {action} - {status}",
                severity='MEDIUM',
                metadata={
                    'subscription_id': str(subscription.id),
                    'subscription_name': subscription.name,
                    'amount': float(subscription.amount),
                    **metadata
                }
            )
            
        except ImportError:
            logger.info(f"Subscription Audit: {subscription.user.username} - {subscription.name} - {action} - {status}")
        except Exception as e:
            logger.error(f"Error logging subscription event: {str(e)}")
    
    @staticmethod
    def log_card_event(card, action, status, metadata=None):
        """Log card-related events"""
        try:
            from audit.models import AuditLog
            
            severity = 'HIGH' if action in ['BLOCK', 'REPORT_LOST', 'PIN_CHANGE'] else 'MEDIUM'
            metadata = AuditLogger._make_json_safe(metadata or {})
            
            AuditLog.objects.create(
                actor=card.user,
                action=f"CARD_{action}",
                description=f"Card {card.mask_card_number()}: {action} - {status}",
                severity=severity,
                metadata={
                    'card_last4': card.card_number[-4:],
                    'card_type': card.card_type,
                    **metadata
                }
            )
            
        except ImportError:
            logger.info(f"Card Audit: {card.user.username} - {card.card_number[-4:]} - {action} - {status}")
        except Exception as e:
            logger.error(f"Error logging card event: {str(e)}")
    
    @staticmethod
    def _get_severity_for_status(status):
        """Map status to severity level"""
        status_severity = {
            'SUCCESS': 'LOW',
            'PROCESSING': 'INFO',
            'PENDING': 'INFO',
            'FAILED': 'HIGH',
            'CANCELLED': 'MEDIUM',
            'REFUNDED': 'INFO',
            'FRAUD': 'CRITICAL'
        }
        return status_severity.get(status, 'INFO')
    
    @staticmethod
    def log_user_login(user, ip_address, user_agent, success=True):
        """Log user login attempts"""
        try:
            from audit.models import AuditLog
            
            action = 'LOGIN_SUCCESS' if success else 'LOGIN_FAILED'
            severity = 'MEDIUM' if not success else 'LOW'
            
            AuditLog.objects.create(
                actor=user if success else None,
                action=action,
                description=f"User login attempt: {'Success' if success else 'Failed'}",
                severity=severity,
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={
                    'success': success,
                    'timestamp': timezone.now().isoformat()
                }
            )
            
        except ImportError:
            logger.info(f"Login Audit: {user.username if user else 'Unknown'} - {'Success' if success else 'Failed'} - {ip_address}")
        except Exception as e:
            logger.error(f"Error logging login event: {str(e)}")

    @staticmethod
    def log_autopilot_execution(user, action, results, metadata=None):
        """Log autopilot execution summary"""
        try:
            from audit.models import AuditLog

            results = results or {}
            metadata = AuditLogger._make_json_safe(metadata or {})

            actions_count = len(results.get('actions_taken', []))
            decisions_count = len(results.get('decisions_made', []))
            alerts_count = len(results.get('alerts_generated', []))
            success = bool(results.get('success', True))
            status = 'SUCCESS' if success else 'FAILED'
            severity = 'LOW' if success else 'HIGH'
            safe_action = action or 'RUN_ALL'

            description = (
                f"Autopilot execution ({safe_action}) - {status} "
                f"[actions={actions_count}, decisions={decisions_count}, alerts={alerts_count}]"
            )

            payload = AuditLogger._make_json_safe({
                'autopilot_action': safe_action,
                'status': status,
                'actions_count': actions_count,
                'decisions_count': decisions_count,
                'alerts_count': alerts_count,
                'results': results,
                **metadata,
            })

            AuditLog.objects.create(
                actor=user,
                action='AUTOPILOT_EXECUTION',
                description=description,
                severity=severity,
                ip_address=metadata.get('ip_address'),
                user_agent=metadata.get('user_agent'),
                metadata=payload
            )

            # Best-effort dedicated autopilot log entry if the app is present.
            try:
                from finnova_autopilot.models import AutopilotLog
                AutopilotLog.objects.create(
                    user=user,
                    action=str(safe_action)[:50],
                    message=description,
                    status=status,
                    metadata=payload
                )
            except ImportError:
                logger.debug('audit app not installed; skipping audit log')
            except Exception as e:
                logger.warning(f"Error creating AutopilotLog entry: {str(e)}")

        except ImportError:
            logger.info(
                f"Autopilot Audit: {user.username if user else 'Unknown'} - "
                f"{action} - {results.get('success', True) if isinstance(results, dict) else True}"
            )
        except Exception as e:
            logger.error(f"Error logging autopilot execution: {str(e)}")

    @staticmethod
    def log_report_generation(user, report_type, report_id, metadata=None):
        """Log report generation events"""
        try:
            from audit.models import AuditLog

            metadata = AuditLogger._make_json_safe(metadata or {})
            description = f"Generated {report_type} report ({report_id})"

            AuditLog.objects.create(
                actor=user,
                action='REPORT_GENERATION',
                description=description,
                severity='LOW',
                ip_address=metadata.get('ip_address'),
                user_agent=metadata.get('user_agent'),
                metadata={
                    'report_type': report_type,
                    'report_id': str(report_id),
                    **metadata,
                }
            )

        except ImportError:
            logger.info(
                f"Report Audit: {user.username if user else 'Unknown'} - "
                f"{report_type} - {report_id}"
            )
        except Exception as e:
            logger.error(f"Error logging report generation: {str(e)}")
