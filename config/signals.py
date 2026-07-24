"""Автоматическая запись действий в журнал аудита.

Подключаемся к ``post_save`` / ``post_delete`` всех бизнес-моделей
приложения. Пользователь и IP берутся из :mod:`config.audit` (их туда
кладёт middleware). Изменённые поля для UPDATE вычисляются через сравнение
со старым состоянием строки, снятым в ``pre_save``.

Ограничение: массовые операции (``QuerySet.update()``,
``bulk_create()``, ``QuerySet.delete()``) сигналы не вызывают и в журнал
не попадают — это штатное поведение Django.
"""

from django.db.models.signals import post_delete, post_save, pre_save

from . import audit

# Поля, которые не несут смысла в диффе изменений.
_SKIP_FIELDS = {'updated_at', 'modified_at'}


def _tracked_models():
    """Все конкретные модели приложения, кроме самого журнала."""
    from django.apps import apps

    from .models import AuditLog

    for model in apps.get_app_config('core').get_models():
        if model is AuditLog:
            continue
        yield model


def _serialize(value):
    """Привести значение поля к JSON-совместимому виду."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _snapshot(instance):
    """Значения локальных полей объекта: {attname: value}."""
    snap = {}
    for field in instance._meta.concrete_fields:
        snap[field.attname] = _serialize(getattr(instance, field.attname, None))
    return snap


def _capture_old_state(sender, instance, **kwargs):
    """pre_save: снять предыдущее состояние строки для будущего диффа."""
    if not instance.pk:
        instance._audit_old_state = None
        return
    try:
        old = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._audit_old_state = None
        return
    instance._audit_old_state = _snapshot(old)


def _diff(old, new):
    """Изменённые поля: {attname: [старое, новое]}."""
    changes = {}
    for name, new_val in new.items():
        if name in _SKIP_FIELDS:
            continue
        old_val = old.get(name)
        if old_val != new_val:
            changes[name] = [old_val, new_val]
    return changes


def _write(instance, action, changes):
    from .models import AuditLog

    user = audit.get_current_user()
    AuditLog.objects.create(
        user=user,
        username=(user.get_username() if user else ''),
        ip_address=audit.get_current_ip(),
        action=action,
        model_name=instance._meta.verbose_name.title(),
        object_id=str(getattr(instance, 'pk', '') or ''),
        object_repr=str(instance)[:255],
        changes=changes,
    )


def _log_save(sender, instance, created, **kwargs):
    from .models import AuditLog

    if created:
        _write(instance, AuditLog.Action.CREATE, {})
        return
    old = getattr(instance, '_audit_old_state', None)
    changes = _diff(old, _snapshot(instance)) if old is not None else {}
    # Ничего значимого не поменялось (например, тронули только updated_at) —
    # не засоряем журнал пустой записью.
    if not changes:
        return
    _write(instance, AuditLog.Action.UPDATE, changes)


def _log_delete(sender, instance, **kwargs):
    from .models import AuditLog

    _write(instance, AuditLog.Action.DELETE, {})


def register():
    """Подключить обработчики ко всем отслеживаемым моделям."""
    for model in _tracked_models():
        key = model._meta.label
        pre_save.connect(
            _capture_old_state, sender=model,
            dispatch_uid=f'audit_pre_save_{key}',
        )
        post_save.connect(
            _log_save, sender=model,
            dispatch_uid=f'audit_post_save_{key}',
        )
        post_delete.connect(
            _log_delete, sender=model,
            dispatch_uid=f'audit_post_delete_{key}',
        )
