from django.apps import AppConfig
from django.db.models.signals import post_migrate


def ensure_default_groups(sender, **kwargs):
    if sender.name != 'core':
        return
    from django.contrib.auth.models import Group
    for name in ('staff', 'admin'):
        Group.objects.get_or_create(name=name)


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Аренда — основное'

    def ready(self):
        post_migrate.connect(ensure_default_groups, sender=self)
