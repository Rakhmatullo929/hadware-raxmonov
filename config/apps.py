import re

from django.apps import AppConfig
from django.db.backends.signals import connection_created
from django.db.models.signals import post_migrate


def ensure_default_groups(sender, **kwargs):
    if sender.label != 'core':
        return
    from django.contrib.auth.models import Group
    for name in ('staff', 'admin'):
        Group.objects.get_or_create(name=name)


def _py_like(pattern, value, escape='\\'):
    """Unicode-aware LIKE for SQLite.

    Django's __icontains compiles to `LIKE %s ESCAPE '\\'`, which calls the
    SQLite `like(pattern, value, escape)` 3-arg function. The built-in
    implementation case-folds ASCII only, so "Алиев" doesn't match "алиев".
    This replacement uses Python regex with re.IGNORECASE, which handles
    full Unicode case folding.
    """
    if pattern is None or value is None:
        return False
    pat = str(pattern)
    esc = escape or '\\'
    out = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if c == esc and i + 1 < len(pat):
            out.append(re.escape(pat[i + 1]))
            i += 2
            continue
        if c == '%':
            out.append('.*')
        elif c == '_':
            out.append('.')
        else:
            out.append(re.escape(c))
        i += 1
    try:
        return re.match('^' + ''.join(out) + '$', str(value), re.IGNORECASE | re.DOTALL) is not None
    except re.error:
        return False


def _register_unicode_sqlite_functions(sender, connection, **kwargs):
    if connection.vendor != 'sqlite':
        return
    conn = connection.connection
    if conn is None:
        return
    conn.create_function('lower', 1, lambda v: v.lower() if isinstance(v, str) else v)
    conn.create_function('upper', 1, lambda v: v.upper() if isinstance(v, str) else v)
    # LIKE has both 2-arg (no ESCAPE) and 3-arg (with ESCAPE) signatures
    conn.create_function('like', 2, lambda p, v: _py_like(p, v))
    conn.create_function('like', 3, _py_like)


class ConfigAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'config'
    label = 'core'
    verbose_name = 'Аренда — основное'

    def ready(self):
        post_migrate.connect(ensure_default_groups, sender=self)
        connection_created.connect(_register_unicode_sqlite_functions)
