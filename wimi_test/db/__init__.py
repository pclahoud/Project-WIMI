"""Per-test database isolation primitives for the WIMI test infrastructure.

This subpackage owns the database-side test plumbing:

* :mod:`wimi_test.db.test_user` — :class:`TestUser`, the per-test user
  wrapper around :meth:`MasterDatabase.create_user`. See
  ``docs/planning/TEST_INFRASTRUCTURE.md`` Section 4 (``TestUser`` API
  contract).
* :mod:`wimi_test.db.seeders` — named seeder registry (lands in T2.5).
* :mod:`wimi_test.db.assertions` — DB-side assertion helpers (lands in
  T2.6).

The package layout itself is documented in ``TEST_INFRASTRUCTURE.md``
Section 3 (Module responsibility matrix).
"""
