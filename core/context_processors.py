def navigation(request):
    """Expose `nav_section` and `is_admin` to all templates for navbar/role UI."""
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

    return {'nav_section': section, 'is_admin': is_admin}
