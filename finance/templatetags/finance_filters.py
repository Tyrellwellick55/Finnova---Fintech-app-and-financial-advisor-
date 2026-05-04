# finance/templatetags/finance_filters.py
from django import template

register = template.Library()

@register.filter
def filter_by_type(categories, category_type):
    """Filter categories by type"""
    return [cat for cat in categories if cat.category_type == category_type]