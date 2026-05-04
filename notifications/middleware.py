import json
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponse
from notifications.services import NotificationManager

class NotificationMiddleware(MiddlewareMixin):
    """
    Middleware to add notification count to response
    """
    
    def process_template_response(self, request, response):
        """
        Add notification stats to context for templates
        """
        if hasattr(response, 'context_data') and request.user.is_authenticated:
            stats = NotificationManager.get_stats(request.user)
            response.context_data['notification_stats'] = stats
        
        return response
    
    def process_request(self, request):
        """
        Add notification data to AJAX requests
        """
        if request.user.is_authenticated and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            # Add notification header for AJAX requests
            unread_count = NotificationManager.get_stats(request.user)['unread']
            request.META['HTTP_X_UNREAD_NOTIFICATIONS'] = str(unread_count)
        
        return None