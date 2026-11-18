from django.apps import AppConfig


class HiringConfig(AppConfig):
    name = 'hiring'
    verbose_name = 'Car hire and tours'

    def ready(self):
        from . import signals  # noqa: F401  (register signal receivers)
