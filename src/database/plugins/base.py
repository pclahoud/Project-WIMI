"""WIMI Database Plugin base class.

Plugins extend the database layer by providing:
1. Schema migrations (tables, columns) via ``ensure_schema()``
2. A mixin class with database methods via ``get_mixin()``
"""


class DatabasePlugin:
    """Base class for database-layer plugins.

    Subclass this to create a plugin that adds tables and methods
    to the per-user database.

    Example::

        class SpacedRepetitionPlugin(DatabasePlugin):
            plugin_id = 'spaced-repetition'

            def ensure_schema(self, db):
                db.execute('''
                    CREATE TABLE IF NOT EXISTS sr_cards (
                        id INTEGER PRIMARY KEY,
                        ...
                    )
                ''')
                db.conn.commit()

            def get_mixin(self):
                return SpacedRepetitionMixin
    """

    plugin_id: str = ''  # e.g. "spaced-repetition"

    def ensure_schema(self, db) -> None:
        """Create or migrate plugin tables.

        Called during UserDatabase initialization, after core schema
        migrations have completed. Must be idempotent.

        Args:
            db: The UserDatabase instance (provides execute, fetchone, etc.)
        """
        raise NotImplementedError

    def get_mixin(self) -> type:
        """Return a mixin class containing the plugin's database methods.

        The returned class will be dynamically composed into UserDatabase
        so its methods become available via ``self.*``.

        Returns:
            A mixin class (not an instance)
        """
        raise NotImplementedError
