"""Контекст текущего запроса для журнала аудита.

Сигналы ``post_save`` / ``post_delete`` не видят ``request``, поэтому
пользователя и IP-адрес мы кладём в thread-local из middleware
(:class:`config.middleware.AuditContextMiddleware`), а сигналы забирают их
отсюда.
"""

import threading

_state = threading.local()


def get_client_ip(request):
    """Реальный IP клиента с учётом обратного прокси (nginx).

    В проде приложение стоит за nginx, который передаёт цепочку в
    ``X-Forwarded-For`` (первый адрес — исходный клиент) и дублирует
    исходный IP в ``X-Real-IP``. Локально/в тестах их нет — падаем на
    ``REMOTE_ADDR``.
    """
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if forwarded:
        # "client, proxy1, proxy2" — исходный клиент идёт первым.
        return forwarded.split(',')[0].strip()
    real_ip = request.META.get('HTTP_X_REAL_IP', '').strip()
    if real_ip:
        return real_ip
    return request.META.get('REMOTE_ADDR') or None


def set_current(user, ip_address):
    """Запомнить пользователя и IP текущего запроса."""
    _state.user = user if (user and user.is_authenticated) else None
    _state.ip_address = ip_address


def clear_current():
    """Сбросить контекст в конце запроса (важно из-за переиспользования потоков)."""
    _state.user = None
    _state.ip_address = None


def get_current_user():
    return getattr(_state, 'user', None)


def get_current_ip():
    return getattr(_state, 'ip_address', None)
