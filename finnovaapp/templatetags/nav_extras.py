from __future__ import annotations

from django import template

register = template.Library()


@register.filter
def startswith(value: str, prefix: str) -> bool:
    """Return True if string `value` starts with `prefix`."""
    try:
        return str(value).startswith(str(prefix))
    except Exception:
        return False


@register.filter
def split(value: str, sep: str = ",") -> list:
    """Split a string into a list. Usage: "a,b,c"|split:"," """
    try:
        return [item.strip() for item in str(value).split(sep)]
    except Exception:
        return []


@register.filter
def get(mapping, key):
    """Dict lookup: {{ my_dict|get:key }}"""
    try:
        return mapping.get(key)
    except (AttributeError, TypeError):
        return None


@register.filter
def intcomma(value):
    """Format number with thousands commas: 1234567 → 1,23,567 (Indian style)"""
    try:
        value = int(value)
        s = str(abs(value))
        if len(s) <= 3:
            result = s
        else:
            result = s[-3:]
            s = s[:-3]
            while s:
                result = s[-2:] + ',' + result if len(s) >= 2 else s + ',' + result
                s = s[:-2]
        return ('-' if value < 0 else '') + result
    except (ValueError, TypeError):
        return value


@register.filter
def replace_underscore(value):
    """Replace underscores with spaces and title-case: savings_rate → Savings Rate"""
    try:
        return str(value).replace('_', ' ').title()
    except Exception:
        return value


@register.filter
def typeof(value):
    """Return the Python type name of value."""
    return type(value).__name__
