from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def user_is_admin(user):
    """True, если пользователь — суперюзер или состоит в группе ``admin``.

    Единый источник правды для проверки «админ ли это» (раньше выражение
    ``is_superuser or groups.filter(name='admin')`` было размножено по
    views/context_processors)."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_superuser
             or user.groups.filter(name='admin').exists())
    )


def role_required(*role_names):
    """Allow access only to users in one of the given groups (or superusers)."""

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            user = request.user
            if user.is_superuser:
                return view_func(request, *args, **kwargs)
            if user.groups.filter(name__in=role_names).exists():
                return view_func(request, *args, **kwargs)
            raise PermissionDenied('Недостаточно прав для доступа.')

        return _wrapped

    return decorator
