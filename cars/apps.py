from django.apps import AppConfig


class CarsConfig(AppConfig):
    name = 'cars'

    def ready(self):
        from . import signals  # noqa: F401  (register signal receivers)
