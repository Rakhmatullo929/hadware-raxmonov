from django.conf import settings
from django.urls import translate_url


def navigation(request):
    """Expose `nav_section`, `is_admin`, and `language_switch_urls` to templates."""
    section = ''
    name = ''
    match = getattr(request, 'resolver_match', None)
    if match is not None:
        name = match.url_name or ''
    if name == 'dashboard':
        section = 'dashboard'
    elif name.startswith('product') or name.startswith('category'):
        section = 'products'
    elif name.startswith('customer'):
        section = 'customers'
    elif name.startswith('rental'):
        section = 'rentals'
    elif name.startswith('report'):
        section = 'reports'

    user = getattr(request, 'user', None)
    is_admin = bool(
        user
        and user.is_authenticated
        and (user.is_superuser or user.groups.filter(name='admin').exists())
    )

    current_path = request.get_full_path()
    language_switch_urls = []
    for code, label in settings.LANGUAGES:
        try:
            target = translate_url(current_path, code)
        except Exception:
            target = current_path
        if not target:
            target = '/'
        language_switch_urls.append({'code': code, 'label': label, 'url': target})

    return {
        'nav_section': section,
        'is_admin': is_admin,
        'language_switch_urls': language_switch_urls,
    }
