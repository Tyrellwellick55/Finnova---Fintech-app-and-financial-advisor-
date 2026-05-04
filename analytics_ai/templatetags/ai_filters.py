# analytics_ai/templatetags/ai_filters.py
from django import template
from django.template.defaultfilters import stringfilter
import re

register = template.Library()

@register.filter
def multiply(value, arg):
    """Multiply the value by the argument"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
def divide(value, arg):
    """Divide the value by the argument"""
    try:
        return float(value) / float(arg)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0

@register.filter
def subtract(value, arg):
    """Subtract arg from value"""
    try:
        return float(value) - float(arg)
    except (ValueError, TypeError):
        return 0

@register.filter
@stringfilter
def intcomma(value):
    """Format number with commas"""
    try:
        # Remove any non-numeric characters except decimal point
        clean_value = re.sub(r'[^\d.]', '', str(value))
        num = float(clean_value)
        return f"{num:,.2f}"
    except (ValueError, TypeError):
        return value

@register.filter
@stringfilter
def replace_underscore(value):
    """Replace underscores with spaces"""
    return value.replace('_', ' ')

@register.filter
@stringfilter
def split(value, sep=','):
    """Split string by separator. Usage: "a,b,c"|split:"," """
    try:
        return [item.strip() for item in value.split(sep)]
    except Exception:
        return []
