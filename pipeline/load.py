"""Transactional PostgreSQL upserts. Schema initialization is always manual."""

import os

import psycopg

UPSERT_SQL = """
INSERT INTO public.customers (customer_id, name, email)
VALUES (%s, %s, %s)
ON CONFLICT (customer_id) DO UPDATE
SET name = EXCLUDED.name,
    email = COALESCE(EXCLUDED.email, customers.email)
"""


class DatabaseLoadError(Exception):
    """A safe, user-facing error that never includes connection credentials."""

    def __init__(self, message, rows_submitted=0):
        super().__init__(message)
        self.rows_submitted = rows_submitted


def load_customers(records):
    """Commit all valid unique rows together; return rows submitted, not inserts."""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise DatabaseLoadError("DATABASE_URL is required for --load-db.")
    rows = list(records[["customer_id", "name", "email"]].itertuples(index=False, name=None))
    if not rows:
        return 0
    try:
        connection = psycopg.connect(database_url, connect_timeout=10, autocommit=False)
    except (psycopg.Error, ValueError):
        raise DatabaseLoadError(
            "Database connection failed. Check DATABASE_URL, server availability, and access permissions."
        ) from None
    submitted = 0
    try:
        # Psycopg commits on normal exit and rolls back when an exception escapes.
        with connection:
            with connection.cursor() as cursor:
                submitted = len(rows)
                cursor.executemany(UPSERT_SQL, rows)
    except (psycopg.Error, ValueError, OverflowError):
        raise DatabaseLoadError(
            "Database load failed; the transaction was not confirmed committed. "
            "Check the schema, permissions, and server availability. "
            "Uncommitted changes are rolled back; if the connection was lost during commit, "
            "the outcome may be unknown. Re-running the same input is safe.",
            rows_submitted=submitted,
        ) from None
    return len(rows)
