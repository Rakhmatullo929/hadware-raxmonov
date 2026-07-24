"""Middleware, наполняющий контекст журнала аудита данными запроса."""

from . import audit


class AuditContextMiddleware:
    """Кладёт пользователя и IP запроса в thread-local для сигналов аудита.

    Должен идти в ``MIDDLEWARE`` после ``AuthenticationMiddleware`` — чтобы
    ``request.user`` уже был доступен.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        audit.set_current(
            getattr(request, 'user', None),
            audit.get_client_ip(request),
        )
        try:
            return self.get_response(request)
        finally:
            # Потоки в gunicorn переиспользуются — чужой контекст утекать не должен.
            audit.clear_current()
