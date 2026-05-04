from django import template

register = template.Library()


@register.filter(name='get')
def dict_get(obj, key):
    """
    Safely retrieve a value from a dict-like object by key.
    Usage: {{ mydict|get:key_variable }}
    Returns None (falsy) if the key is missing or obj is not a dict.
    """
    if obj is None:
        return None
    try:
        # Works for dicts, QueryDicts, and objects with a .get() method
        return obj.get(key)
    except (AttributeError, TypeError):
        try:
            return obj[key]
        except (KeyError, TypeError, IndexError):
            return None


@register.filter
def notification_icon(notification_type):
    """Return a FontAwesome icon class for a given notification type."""
    icons = {
        'PAYMENT': 'fas fa-credit-card',
        'BUDGET': 'fas fa-sliders',
        'SAVINGS': 'fas fa-piggy-bank',
        'SECURITY': 'fas fa-shield-halved',
        'SYSTEM': 'fas fa-gear',
        'INFO': 'fas fa-circle-info',
        'WARNING': 'fas fa-triangle-exclamation',
        'SUCCESS': 'fas fa-circle-check',
        'ERROR': 'fas fa-circle-xmark',
    }
    return icons.get(str(notification_type).upper(), 'fas fa-bell')


@register.filter
def notification_color(severity):
    """Return a CSS color var for a severity level."""
    colors = {
        'CRITICAL': 'var(--red)',
        'HIGH': '#F97316',
        'MEDIUM': 'var(--yellow)',
        'LOW': 'var(--brand)',
        'INFO': 'var(--brand)',
    }
    return colors.get(str(severity).upper(), 'var(--text-3)')
