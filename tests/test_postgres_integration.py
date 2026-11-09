"""Opt-in real tests: use a dedicated disposable database, never a shared one."""

import os
import uuid

import pandas as pd
import psycopg
import pytest
from psycopg import sql

from pipeline import load
from pipeline.extract import REQUIRED_COLUMNS


@pytest.fixture
def real_database(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url or os.getenv("RUN_DATABASE_TESTS") != "1":
        pytest.skip("Requires disposable TEST_DATABASE_URL and RUN_DATABASE_TESTS=1")
    # Only this randomly named schema is created/dropped. Existing tables are untouched.
    schema = "etl_test_" + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True, connect_timeout=10) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            from pathlib import Path
            schema_text = (Path(__file__).resolve().parents[1] / "sql/schema.sql").read_text()
            admin.execute(schema_text.replace("public.customers", f"{schema}.customers"))
            # Check repeatable initialization on the isolated schema too.
            admin.execute(schema_text.replace("public.customers", f"{schema}.customers"))
            monkeypatch.setenv("DATABASE_URL", url)
            monkeypatch.setattr(load, "UPSERT_SQL", load.UPSERT_SQL.replace(
                "public.customers", f"{schema}.customers"))
            yield admin, schema
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def batch(rows):
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


def test_real_inserts_updates_nulls_and_reruns(real_database):
    admin, schema = real_database
    original = batch([["1", "Original", "first@example.com"], ["2", "Missing", None]])
    assert load.load_customers(original) == 2
    assert load.load_customers(original) == 2
    load.load_customers(batch([["1", "Renamed", None]]))
    rows = admin.execute(sql.SQL("SELECT * FROM {}.customers ORDER BY customer_id").format(
        sql.Identifier(schema))).fetchall()
    assert rows == [(1, "Renamed", "first@example.com"), (2, "Missing", None)]
    load.load_customers(batch([["1", "Updated", "new@example.com"]]))
    assert admin.execute(sql.SQL("SELECT email FROM {}.customers WHERE customer_id = 1").format(
        sql.Identifier(schema))).fetchone() == ("new@example.com",)


def test_real_rollback(real_database):
    admin, schema = real_database
    load.load_customers(batch([["1", "Original", "original@example.com"]]))
    with pytest.raises(load.DatabaseLoadError):
        load.load_customers(batch([["1", "Must roll back", None], ["2", "", None]]))
    assert admin.execute(sql.SQL("SELECT * FROM {}.customers").format(
        sql.Identifier(schema))).fetchall() == [(1, "Original", "original@example.com")]
