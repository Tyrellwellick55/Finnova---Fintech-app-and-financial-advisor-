from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
import threading

thread_local = threading.local()


class AuditMiddleware(MiddlewareMixin):
    """
    Middleware to track requests and associate them with audit logs.
    """
    
    def process_request(self, request):
        """Store request start time and request object"""
        thread_local.request = request
        thread_local.request_start_time = timezone.now()
        
        # Store request for use in signals
        if hasattr(request, 'user') and request.user.is_authenticated:
            request.user._request = request
    
    def process_response(self, request, response):
        """Clean up after request"""
        if hasattr(thread_local, 'request'):
            del thread_local.request
        if hasattr(thread_local, 'request_start_time'):
            del thread_local.request_start_time
        
        # Clean up request from user object
        if hasattr(request, 'user') and hasattr(request.user, '_request'):
            del request.user._request
        
        return response
    
    def process_exception(self, request, exception):
        """Log exceptions"""
        from .services import AuditService
        
        AuditService.log_audit_event(
            actor=request.user if hasattr(request, 'user') and request.user.is_authenticated else None,
            source='SYSTEM',
            action='SYSTEM_EVENT',
            severity='HIGH',
            description=f'Exception occurred: {str(exception)}',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT'),
            request=request,
            metadata={
                'exception_type': type(exception).__name__,
                'path': request.path,
                'method': request.method,
            }
        )
        
        return None


class RequestAuditMiddleware(MiddlewareMixin):
    """
    Middleware to audit all incoming requests for security monitoring.
    """
    
    def process_request(self, request):
        """Log all requests for security monitoring"""
        from .services import AuditService
        
        # Skip logging for static files and health checks
        if request.path.startswith('/static/') or request.path.startswith('/media/'):
            return
        
        if request.path == '/health/' or request.path == '/favicon.ico':
            return
        
        # Determine severity based on request
        severity = 'LOW'
        if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
            severity = 'MEDIUM'
        if '/admin/' in request.path or '/api/' in request.path:
            severity = 'MEDIUM'
        
        # Log the request
        AuditService.log_audit_event(
            actor=request.user if hasattr(request, 'user') and request.user.is_authenticated else None,
            source='SYSTEM',
            action='REQUEST',
            severity=severity,
            description=f'{request.method} request to {request.path}',
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT'),
            request=request,
            metadata={
                'path': request.path,
                'method': request.method,
                'query_params': dict(request.GET),
                'content_type': request.content_type,
            }
        )