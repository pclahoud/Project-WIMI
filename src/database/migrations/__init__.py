"""WIMI database migrations.

Migrations are organized into two parallel directories:

- ``user/`` — applied to per-user databases
- ``master/`` — applied to the master database (users, app settings)

Each migration is a Python module exposing ``VERSION``, ``NAME``, and a
``upgrade(conn)`` function. See :mod:`src.database.migration_runner` for
the runner that applies them.
"""
