from django.apps import AppConfig


class TrafficConfig(AppConfig):
    name = 'traffic'
    verbose_name = 'Traffic Analytics'

    def ready(self):
        # Registers the SQLite WAL receiver. It lives here because the
        # per-request traffic write is what makes WAL worth turning on.
        from . import signals  # noqa: F401
