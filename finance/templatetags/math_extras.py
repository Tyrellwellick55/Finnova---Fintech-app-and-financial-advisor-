from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()

@register.filter
def percent(numerator, denominator):
    """Return numerator/denominator*100. Safe for invalid inputs."""
    try:
        num = float(numerator)
        den = float(denominator)
        if den == 0:
            return 0
        return (num / den) * 100
    except (TypeError, ValueError):
        return 0

@register.filter(name='div')
def div(value, arg):
    try:
        den = float(arg)
        if den == 0:
            return 0
        return float(value) / den
    except (TypeError, ValueError):
        return 0

@register.filter(name='divide')
def divide(value, arg):
    return div(value, arg)

@register.filter(name='mul')
def mul(value, arg):
    try:
        return float(value) * float(arg)
    except (TypeError, ValueError):
        return 0

@register.filter(name='multiply')
def multiply(value, arg):
    return mul(value, arg)

@register.filter(name='subtract')
def subtract(value, arg):
    try:
        return float(value) - float(arg)
    except (TypeError, ValueError):
        return 0

@register.filter(name='abs')
def absolute(value):
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return 0

@register.filter(name='sum')
def sum_attr(iterable, attr):
    """Sum attribute from list/queryset of objects/dicts."""
    if iterable is None:
        return 0
    total = Decimal('0')
    for item in iterable:
        try:
            if isinstance(item, dict):
                v = item.get(attr, 0)
            else:
                v = getattr(item, attr, 0)
            total += Decimal(str(v or 0))
        except (InvalidOperation, TypeError, ValueError):
            continue
    return total

@register.filter(name='split')
def split(value, sep=','):
    if value is None:
        return []
    return str(value).split(sep)

@register.filter(name='replace')
def replace(value, args):
    """Usage: value|replace:'old,new'"""
    if value is None:
        return ''
    try:
        old, new = str(args).split(',', 1)
    except ValueError:
        return value
    return str(value).replace(old, new)

@register.filter(name='ordinal')
def ordinal(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return value
    if 10 <= (n % 100) <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffix}"

@register.filter(name='total_plans')
def total_plans(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@register.filter(name='add_days')
def add_days(value, days):
    """Add integer days to a date/datetime value."""
    from datetime import timedelta
    if value in (None, ''):
        return value
    try:
        return value + timedelta(days=int(days))
    except Exception:
        return value
