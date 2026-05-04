# audit/context_processors.py
from django.core.cache import cache
from .models import SecurityAlert

def audit_context(request):
    """Add audit-related context to all templates"""
    if request.user.is_authenticated:
        # Cache the count for 5 minutes
        cache_key = f'open_alerts_count_{request.user.id}'
        open_alerts_count = cache.get(cache_key)
        
        if open_alerts_count is None:
            open_alerts_count = SecurityAlert.objects.filter(
                status__in=['OPEN', 'INVESTIGATING']
            ).count()
            cache.set(cache_key, open_alerts_count, 300)  # 5 minutes
        
        return {
            'open_alerts_count': open_alerts_count,
        }
    return { }