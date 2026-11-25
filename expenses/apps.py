from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _configure_sqlite(sender, connection, **kwargs):
    """Configures SQLite WAL mode, cache, and timeout for smooth multi-user concurrency."""
    if connection.vendor == 'sqlite':
        try:
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA journal_mode=WAL;')
                cursor.execute('PRAGMA synchronous=NORMAL;')
                cursor.execute('PRAGMA cache_size=-64000;')
                cursor.execute('PRAGMA temp_store=MEMORY;')
                cursor.execute('PRAGMA busy_timeout=20000;')
        except Exception:
            pass


class ExpensesConfig(AppConfig):
    name = 'expenses'

    def ready(self):
        connection_created.connect(_configure_sqlite)
