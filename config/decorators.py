from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


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
