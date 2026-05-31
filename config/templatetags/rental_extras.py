import re

from django import template

register = template.Library()


@register.filter
def format_phone(value):
    """+998855363977 → +998 85 536 39 77 (best-effort, leaves anything weird alone)."""
    if not value:
        return ''
    digits = re.sub(r'\D', '', str(value))
    # Uzbek format: 12-digit number starting with 998
    if len(digits) == 12 and digits.startswith('998'):
        return f'+998 {digits[3:5]} {digits[5:8]} {digits[8:10]} {digits[10:12]}'
    # Generic 11-12 digit numbers: split into 3-3-2-2
    if 10 <= len(digits) <= 12:
        groups = []
        s = digits
        while s:
            groups.append(s[:3])
            s = s[3:]
        return '+' + ' '.join(groups)
    return value


@register.filter
def initial(value):
    """First character of a string, uppercased."""
    s = (value or '').strip()
    return s[:1].upper() if s else '?'


@register.filter
def dict_lookup(d, key):
    """`{{ mapping|dict_lookup:key }}` — обращение к ключу словаря
    из шаблона, когда ключ — переменная и не подставляется через точку."""
    if d is None:
        return ''
    try:
        return d.get(key, '')
    except AttributeError:
        return d[key] if key in d else ''
