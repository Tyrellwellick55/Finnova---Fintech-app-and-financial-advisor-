import logging
import json
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Q, Count, Sum
from django.core.cache import cache
from django.conf import settings
from .models import AuditLog, SecurityAlert, ComplianceRecord, AuditTrail

User = get_user_model()
logger = logging.getLogger(__name__)


class AuditService:
    """
    Comprehensive audit service for logging and tracking
    """
    
    @staticmethod
    def log_audit_event(
        actor=None,
        target_user=None,
        source='SYSTEM',
        action='SYSTEM_EVENT',
        severity='MEDIUM',
        description='',
        ip_address=None,
        user_agent=None,
        session_id=None,
        metadata=None,
        parent_event=None,
        request=None
    ):
        """
        Creates an immutable audit log entry with comprehensive tracking.
        """
        try:
            # Extract info from request if provided
            if request:
                if not ip_address:
                    ip_address = request.META.get('REMOTE_ADDR')
                if not user_agent:
                    user_agent = request.META.get('HTTP_USER_AGENT', '')
                if not session_id and hasattr(request, 'session'):
                    session_id = request.session.session_key
            
            # Ensure metadata is a dict
            if metadata is None:
                metadata = {}
            
            # Add timestamp to metadata
            if 'timestamp' not in metadata:
                metadata['timestamp'] = timezone.now().isoformat()
            
            # Create audit log
            log = AuditLog.objects.create(
                actor=actor,
                target_user=target_user,
                source=source,
                action=action,
                severity=severity,
                description=description,
                actor_ip=ip_address,
                actor_user_agent=user_agent,
                metadata={**metadata, 'session_id': session_id} if session_id else metadata,
                parent_event=parent_event
            )
            
            # Check for suspicious patterns
            AuditService._check_for_suspicious_activity(log)
            
            # Update cache for dashboard
            cache_key = f"audit_stats_{timezone.now().date()}"
            cache.delete(cache_key)
            
            logger.info(f"Audit log created: {log}")
            return log
            
        except Exception as e:
            logger.error(f"Failed to create audit log: {str(e)}")
            # Fallback: Create minimal log
            try:
                return AuditLog.objects.create(
                    source='SYSTEM',
                    action='LOG_CREATION_FAILED',
                    severity='HIGH',
                    description=f"Failed to log event: {description}. Error: {str(e)}",
                    metadata={'error': str(e), 'original_data': metadata}
                )
            except:
                logger.critical("Complete audit logging failure")
                return None
    
    @staticmethod
    def _check_for_suspicious_activity(log):
        """
        Check log for suspicious patterns and create security alerts if needed.
        """
        try:
            # Check for multiple failed logins from same IP
            if log.action == 'LOGIN' and log.severity == 'HIGH':
                recent_failed_logins = AuditLog.objects.filter(
                    actor_ip=log.actor_ip,
                    action='LOGIN',
                    severity='HIGH',
                    created_at__gte=timezone.now() - timedelta(minutes=15)
                ).count()
                
                if recent_failed_logins >= 5:
                    # Create security alert for brute force attempt
                    SecurityAlert.objects.create(
                        alert_type='LOGIN_ATTEMPT',
                        title=f"Multiple Failed Login Attempts from {log.actor_ip}",
                        description=f"Detected {recent_failed_logins} failed login attempts in 15 minutes",
                        severity='HIGH',
                        ip_address=log.actor_ip,
                        device_info=log.metadata.get('device_info', {}),
                        evidence={'log_ids': [str(x) for x in list(
                            AuditLog.objects.filter(
                                actor_ip=log.actor_ip,
                                action='LOGIN',
                                severity='HIGH',
                                created_at__gte=timezone.now() - timedelta(minutes=15)
                            ).values_list('id', flat=True)
                        )]}
                    )
            
            # Check for sensitive operations
            sensitive_actions = ['DELETE', 'PERMISSION_CHANGE', 'DATA_EXPORT']
            if log.action in sensitive_actions and log.severity in ['HIGH', 'CRITICAL']:
                # Log to security monitoring
                logger.warning(f"Sensitive operation detected: {log.action} by {log.actor}")
                
        except Exception as e:
            logger.error(f"Error checking suspicious activity: {str(e)}")
    
    @staticmethod
    def create_security_alert(
        alert_type,
        title,
        description,
        user=None,
        severity='MEDIUM',
        ip_address=None,
        location=None,
        device_info=None,
        related_logs=None
    ):
        """
        Create a security alert with automatic severity calculation.
        """
        try:
            # Auto-escalate severity for certain conditions
            if alert_type in ['UNAUTHORIZED_ACCESS', 'DATA_BREACH']:
                severity = 'CRITICAL'
            
            alert = SecurityAlert.objects.create(
                alert_type=alert_type,
                title=title,
                description=description,
                user=user,
                severity=severity,
                ip_address=ip_address,
                location=location,
                device_info=device_info or {}
            )
            
            # Link related logs
            if related_logs:
                alert.related_logs.set(related_logs)
            
            # Send notifications if critical
            if severity in ['HIGH', 'CRITICAL']:
                AuditService._notify_security_team(alert)
            
            logger.warning(f"Security alert created: {alert}")
            return alert
            
        except Exception as e:
            logger.error(f"Failed to create security alert: {str(e)}")
            return None
    
    @staticmethod
    def _notify_security_team(alert):
        """
        Notify security team about critical alerts.
        In production, this would send emails/SMS/webhooks.
        """
        # Placeholder for notification logic
        logger.warning(f"SECURITY ALERT - {alert.alert_type}: {alert.title}")
    
    @staticmethod
    def log_data_change(
        object_type,
        object_id,
        operation,
        user,
        old_value=None,
        new_value=None,
        changes=None,
        ip_address=None,
        reason=None
    ):
        """
        Log data changes for complete audit trail.
        """
        try:
            trail = AuditTrail.objects.create(
                object_type=object_type,
                object_id=object_id,
                operation=operation,
                user=user,
                old_value=old_value,
                new_value=new_value,
                changes=changes or {},
                ip_address=ip_address,
                reason=reason
            )
            
            # Also create an audit log for significant changes
            if operation in ['DELETE', 'CREATE', 'UPDATE']:
                AuditService.log_audit_event(
                    actor=user,
                    source='SYSTEM',
                    action=f'DATA_{operation}',
                    severity='MEDIUM',
                    description=f"{operation}d {object_type} #{object_id}",
                    ip_address=ip_address,
                    metadata={
                        'object_type': object_type,
                        'object_id': object_id,
                        'operation': operation,
                        'trail_id': str(trail.id)
                    }
                )
            
            return trail
            
        except Exception as e:
            logger.error(f"Failed to log data change: {str(e)}")
            return None
    
    @staticmethod
    def get_audit_stats(time_period='today'):
        """
        Get audit statistics for dashboard.
        """
        latest_log_ts = AuditLog.objects.order_by('-created_at').values_list('created_at', flat=True).first()
        latest_alert_ts = SecurityAlert.objects.order_by('-detected_at').values_list('detected_at', flat=True).first()
        latest_log_marker = int(latest_log_ts.timestamp()) if latest_log_ts else 0
        latest_alert_marker = int(latest_alert_ts.timestamp()) if latest_alert_ts else 0
        cache_key = f"audit_stats_{time_period}_{latest_log_marker}_{latest_alert_marker}"
        if cached_stats := cache.get(cache_key):
            return cached_stats

        now = timezone.now()

        if time_period == 'today':
            start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_period == 'week':
            start_date = now - timedelta(days=7)
        elif time_period == 'month':
            start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=1)

        stats = {
            'total_logs': AuditLog.objects.filter(created_at__gte=start_date).count(),
            'by_severity': dict(AuditLog.objects.filter(
                created_at__gte=start_date
            ).values('severity').annotate(count=Count('id')).values_list('severity', 'count')),
            'by_source': dict(AuditLog.objects.filter(
                created_at__gte=start_date
            ).values('source').annotate(count=Count('id')).values_list('source', 'count')),
            'by_action': dict(AuditLog.objects.filter(
                created_at__gte=start_date
            ).values('action').annotate(count=Count('id')).values_list('action', 'count')),
            'security_alerts': SecurityAlert.objects.filter(
                detected_at__gte=start_date
            ).count(),
            'open_alerts': SecurityAlert.objects.filter(
                status__in=['OPEN', 'INVESTIGATING']
            ).count(),
            'top_actors': list(AuditLog.objects.filter(
                created_at__gte=start_date,
                actor__isnull=False
            ).values('actor__username').annotate(
                count=Count('id')
            ).order_by('-count')[:10]),
            'suspicious_ips': list(AuditLog.objects.filter(
                created_at__gte=start_date,
                severity__in=['HIGH', 'CRITICAL']
            ).exclude(actor_ip__isnull=True).values('actor_ip').annotate(
                count=Count('id')
            ).order_by('-count')[:10]),
        }

        # Cache for 5 minutes
        cache.set(cache_key, stats, 300)
        return stats
    
    @staticmethod
    def export_audit_logs(start_date, end_date, format='json'):
        """
        Export audit logs for a given date range.
        """
        logs = AuditLog.objects.filter(
            created_at__gte=start_date,
            created_at__lte=end_date
        ).order_by('created_at')

        if format == 'csv':
            import csv
            from io import StringIO

            output = StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow([
                'ID', 'Timestamp', 'Source', 'Action', 'Severity',
                'Actor', 'Target User', 'Description', 'IP Address',
                'Correlation ID'
            ])

            # Write data
            for log in logs:
                writer.writerow([
                    log.id,
                    log.created_at.isoformat(),
                    log.source,
                    log.action,
                    log.severity,
                    log.actor.username if log.actor else '',
                    log.target_user.username if log.target_user else '',
                    log.description[:100],  # Truncate for CSV
                    log.actor_ip or '',
                    str(log.correlation_id)
                ])

            return output.getvalue()

        elif format == 'json':
            data = [
                {
                    'id': log.id,
                    'timestamp': log.created_at.isoformat(),
                    'source': log.source,
                    'action': log.action,
                    'severity': log.severity,
                    'actor': log.actor.username if log.actor else None,
                    'target_user': (
                        log.target_user.username if log.target_user else None
                    ),
                    'description': log.description,
                    'ip_address': log.actor_ip,
                    'metadata': log.metadata,
                    'correlation_id': str(log.correlation_id),
                }
                for log in logs
            ]
            return json.dumps(data, indent=2)

        elif format == 'pdf':
            from io import BytesIO

            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.pdfgen import canvas

            buf = BytesIO()
            c = canvas.Canvas(buf, pagesize=A4)
            width, height = A4

            c.setFont('Helvetica-Bold', 16)
            c.drawString(18 * mm, height - 18 * mm, 'Finnovault — Audit Log Export')
            c.setFont('Helvetica', 10)
            c.drawString(
                18 * mm,
                height - 24 * mm,
                f"Range: {start_date.date().isoformat()} → {end_date.date().isoformat()}   Total: {logs.count()}",
            )

            y = height - 34 * mm
            c.setFont('Helvetica-Bold', 9)
            c.drawString(18 * mm, y, 'Time')
            c.drawString(45 * mm, y, 'Severity')
            c.drawString(70 * mm, y, 'Action')
            c.drawString(120 * mm, y, 'Source')
            c.drawString(150 * mm, y, 'Actor')
            y -= 6 * mm
            c.setFont('Helvetica', 8)

            for log in logs[:500]:
                if y < 18 * mm:
                    c.showPage()
                    y = height - 18 * mm
                    c.setFont('Helvetica', 8)
                ts = log.created_at.strftime('%Y-%m-%d %H:%M')
                c.drawString(18 * mm, y, ts)
                c.drawString(45 * mm, y, str(log.severity)[:12])
                c.drawString(70 * mm, y, str(log.action)[:28])
                c.drawString(120 * mm, y, str(log.source)[:16])
                actor = getattr(log.actor, 'username', '-') if log.actor else '-'
                c.drawString(150 * mm, y, actor[:18])
                y -= 5 * mm

            c.showPage()
            c.save()
            return buf.getvalue()

        elif format == 'pack':
            import zipfile
            from io import BytesIO

            csv_data = AuditService.export_audit_logs(start_date, end_date, format='csv').encode('utf-8')
            json_data = AuditService.export_audit_logs(start_date, end_date, format='json').encode('utf-8')
            pdf_data = AuditService.export_audit_logs(start_date, end_date, format='pdf')

            buf = BytesIO()
            with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('audit_logs.csv', csv_data)
                z.writestr('audit_logs.json', json_data)
                z.writestr('audit_logs.pdf', pdf_data)
            return buf.getvalue()

        return None
    
    @staticmethod
    def cleanup_old_logs(days_to_keep=90):
        """
        Archive or delete old audit logs.
        """
        cutoff_date = timezone.now() - timedelta(days=days_to_keep)
        old_logs = AuditLog.objects.filter(created_at__lt=cutoff_date)
        count = old_logs.count()
        
        # In production, you would archive to cold storage
        # For now, we just delete
        deleted_count, _ = old_logs.delete()
        
        logger.info(f"Cleaned up {deleted_count} audit logs older than {days_to_keep} days")
        return deleted_count
    
    @staticmethod
    def search_logs(
        search_query=None,
        start_date=None,
        end_date=None,
        sources=None,
        actions=None,
        severities=None,
        actor_id=None,
        target_id=None,
        limit=100
    ):
        """
        Advanced search for audit logs.
        """
        queryset = AuditLog.objects.all()
        
        # Date range filter
        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)
        
        # Source filter
        if sources:
            queryset = queryset.filter(source__in=sources)
        
        # Action filter
        if actions:
            queryset = queryset.filter(action__in=actions)
        
        # Severity filter
        if severities:
            queryset = queryset.filter(severity__in=severities)
        
        # User filters
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)
        if target_id:
            queryset = queryset.filter(target_user_id=target_id)
        
        # Text search
        if search_query:
            queryset = queryset.filter(
                Q(description__icontains=search_query) |
                Q(metadata__icontains=search_query) |
                Q(actor__username__icontains=search_query) |
                Q(target_user__username__icontains=search_query)
            )
        
        return queryset.order_by('-created_at')[:limit]


# Backward compatibility functions
def log_audit_event(
    actor=None,
    target_user=None,
    source='SYSTEM',
    action='SYSTEM_EVENT',
    severity='MEDIUM',
    description='',
    metadata=None
):
    """
    Legacy function for backward compatibility.
    """
    return AuditService.log_audit_event(
        actor=actor,
        target_user=target_user,
        source=source,
        action=action,
        severity=severity,
        description=description,
        metadata=metadata
    )


