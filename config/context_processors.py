from django.conf import settings
from django.db.models import F, IntegerField, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.urls import translate_url
from django.utils import timezone


def _count_overdue_rentals():
    """Сколько сейчас просроченных аренд с невыданным остатком.

    Логика совпадает с дашбордом: активные + due_date < сегодня +
    есть позиции, которые не вернули.
    """
    # Лениво — чтобы circular-импорт исключить и не платить за загрузку,
    # когда контекст-процессор вызывают на маршрутах вроде /static.
    from .models import Movement, Rental

    now = timezone.now()
    issued_sub = (
        Movement.objects
        .filter(rental_item__rental=OuterRef('pk'), kind=Movement.Kind.ISSUE)
        .values('rental_item__rental')
        .annotate(s=Sum('qty'))
        .values('s')
    )
    returned_sub = (
        Movement.objects
        .filter(rental_item__rental=OuterRef('pk'), kind=Movement.Kind.RETURN)
        .values('rental_item__rental')
        .annotate(s=Sum('qty'))
        .values('s')
    )
    return (
        Rental.objects
        .filter(status=Rental.Status.ACTIVE, due_date__lt=now)
        .annotate(
            _issued=Coalesce(Subquery(issued_sub, output_field=IntegerField()), 0),
            _returned=Coalesce(Subquery(returned_sub, output_field=IntegerField()), 0),
        )
        .annotate(_outstanding=F('_issued') - F('_returned'))
        .filter(_outstanding__gt=0)
        .count()
    )


def navigation(request):
    """Expose `nav_section`, `is_admin`, language switch and overdue count."""
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
    elif name.startswith('attendance') or name.startswith('worker'):
        section = 'attendance'
    elif name.startswith('salary'):
        section = 'salary'
    elif name.startswith('product_suspicion'):
        section = 'suspicions'

    from .decorators import user_is_admin

    user = getattr(request, 'user', None)
    is_authenticated = bool(user and user.is_authenticated)
    is_admin = user_is_admin(user)
    is_staff_or_admin = bool(
        is_authenticated
        and (user.is_superuser
             or user.groups.filter(name__in=('admin', 'staff')).exists())
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

    # Просрочки и подозрения считаем только для авторизованных
    # операторов/админов и только на полноразмерных страницах — htmx-фрагменты
    # не рендерят base.html, поэтому платить за лишние запросы смысла нет.
    overdue_count = 0
    suspicions_count = 0
    is_htmx = request.META.get('HTTP_HX_REQUEST') == 'true'
    if is_staff_or_admin and not is_htmx:
        try:
            overdue_count = _count_overdue_rentals()
        except Exception:
            # Падать из-за бейджа в base.html — недопустимо.
            overdue_count = 0
        try:
            suspicions_count = _count_product_suspicions_over()
        except Exception:
            suspicions_count = 0

    return {
        'nav_section': section,
        'is_admin': is_admin,
        'language_switch_urls': language_switch_urls,
        'overdue_count': overdue_count,
        'suspicions_count': suspicions_count,
        # Стабильный ключ для sessionStorage: меняется раз в сутки, поэтому
        # каждый новый день / новая вкладка показывает тост ещё один раз.
        'overdue_toast_key': timezone.localdate().isoformat(),
    }


def _count_product_suspicions_over(limit=200):
    """Сколько активных позиций уже сверх нормы проката (только ``over``).

    Считаем «потенциальных кандидатов» в БД, потом по выборке —
    в Python, чтобы переиспользовать ``RentalItem.expected_status``
    и не дублировать логику. Жёсткий лимит ``limit`` — оборона от
    разрастания: в норме подозрений десятки, не сотни.
    """
    from .models import Rental, RentalItem

    today = timezone.localdate()
    candidates = (
        RentalItem.objects
        .filter(
            rental__status__in=[Rental.Status.ACTIVE, Rental.Status.OVERDUE],
            product__expected_max_days__isnull=False,
        )
        .select_related('product')
        .prefetch_related('movements')[:limit]
    )
    return sum(1 for it in candidates if it.expected_status() == 'over')
