"""Unit tests use mocks only: they never connect to PostgreSQL."""

import json
import os
import subprocess
import sys
from unittest.mock import MagicMock

import pandas as pd
import psycopg
import pytest

import main
from pipeline import load
from pipeline.extract import REQUIRED_COLUMNS
from pipeline.transform import transform_customers


def records(rows):
    return pd.DataFrame(rows, columns=REQUIRED_COLUMNS)


@pytest.fixture
def database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://placeholder:secret@localhost/test")
    connect = MagicMock()
    connection = connect.return_value
    connection.__enter__.return_value = connection
    cursor = connection.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(load.psycopg, "connect", connect)
    return connect, connection, cursor


def test_parameterized_batch_and_commit(database):
    connect, connection, cursor = database
    name = "Example'); DROP TABLE customers; --"
    data = records([["1", name, "one@example.com"], ["2", "New", None]])
    assert load.load_customers(data) == 2
    sql, parameters = cursor.executemany.call_args.args
    assert sql == load.UPSERT_SQL
    assert name not in sql
    assert parameters == [("1", name, "one@example.com"), ("2", "New", None)]
    assert "ON CONFLICT (customer_id) DO UPDATE" in sql
    assert "name = EXCLUDED.name" in sql
    assert "COALESCE(EXCLUDED.email, customers.email)" in sql
    connect.assert_called_once_with(
        "postgresql://placeholder:secret@localhost/test", connect_timeout=10, autocommit=False)
    connection.__exit__.assert_called_once_with(None, None, None)


def test_missing_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(load.DatabaseLoadError, match="DATABASE_URL is required"):
        load.load_customers(records([]))


def test_empty_batch(database):
    connect, _, _ = database
    assert load.load_customers(records([])) == 0
    connect.assert_not_called()


def test_connection_failure_is_sanitized(database):
    connect, _, _ = database
    connect.side_effect = psycopg.OperationalError("postgresql://user:secret@host/db")
    with pytest.raises(load.DatabaseLoadError, match="connection failed") as error:
        load.load_customers(records([["1", "A", None]]))
    assert "secret" not in str(error.value)
    assert error.value.rows_submitted == 0


def test_query_failure_requests_rollback(database):
    _, connection, cursor = database
    cursor.executemany.side_effect = psycopg.IntegrityError("secret row contents")
    with pytest.raises(load.DatabaseLoadError) as error:
        load.load_customers(records([["1", "A", None], ["2", "B", None]]))
    assert error.value.rows_submitted == 2
    assert "secret" not in str(error.value)
    assert connection.__exit__.call_args.args[0] is psycopg.IntegrityError


def test_commit_failure_not_reported_as_success(database):
    _, connection, _ = database
    connection.__exit__.side_effect = psycopg.OperationalError("secret connection")
    with pytest.raises(load.DatabaseLoadError, match="outcome may be unknown"):
        load.load_customers(records([["1", "A", None]]))


def test_csv_mode_never_connects(tmp_path, database):
    connect, _, _ = database
    _, report = main.run_pipeline(reports_root=tmp_path)
    assert report["load_status"] == "not_attempted"
    connect.assert_not_called()


def test_load_success_reports_only_valid_unique_rows(tmp_path, database):
    _, _, cursor = database
    output, report = main.run_pipeline(reports_root=tmp_path, load_db=True)
    assert report["load_status"] == "succeeded"
    assert report["load_rows_submitted"] == report["load_rows_committed"] == 5
    assert len(cursor.executemany.call_args.args[1]) == 5
    assert json.loads((output / "data_quality.json").read_text()) == report


@pytest.mark.parametrize("failure", ["missing_url", "connection", "query"])
def test_failure_reports_and_cli_exit(tmp_path, monkeypatch, database, capsys, failure):
    connect, _, cursor = database
    if failure == "missing_url":
        monkeypatch.delenv("DATABASE_URL")
    elif failure == "connection":
        connect.side_effect = psycopg.OperationalError("secret")
    else:
        cursor.executemany.side_effect = psycopg.IntegrityError("secret")
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    assert main.main([str(main.run_pipeline.__defaults__[0]), "--load-db"]) == 1
    directory = next((tmp_path / "reports").iterdir())
    report = json.loads((directory / "data_quality.json").read_text())
    assert report["transformation_status"] == "succeeded"
    assert report["load_status"] == "failed"
    assert report["load_rows_committed"] is None
    assert report["load_rows_submitted"] == (5 if failure == "query" else 0)
    assert (directory / "cleaned_customers.csv").exists()
    assert (directory / "rejected_records.csv").exists()
    assert "secret" not in capsys.readouterr().out


def test_postgres_integer_boundary():
    cleaned, rejected, report = transform_customers(records([
        ["2147483647", "Boundary", ""], ["2147483648", "Too large", ""],
        ["9" * 100, "Much too large", ""]]))
    assert cleaned["customer_id"].tolist() == ["2147483647"]
    assert report["rejected_invalid_rows"] == 2
    assert rejected["reason"].str.contains("maximum").all()


def test_real_cli_missing_url_exit(tmp_path):
    environment = os.environ.copy()
    environment.pop("DATABASE_URL", None)
    # Redirect reports through a wrapper; execute the actual CLI return code.
    code = (
        "import main; from pathlib import Path; "
        f"main.PROJECT_ROOT = Path({str(tmp_path)!r}); "
        f"raise SystemExit(main.main([{str(main.PROJECT_ROOT / 'customers.csv')!r}, '--load-db']))"
    )
    result = subprocess.run([sys.executable, "-c", code], env=environment,
                            cwd=main.PROJECT_ROOT, text=True, capture_output=True)
    assert result.returncode == 1
    assert "DATABASE_URL is required" in result.stdout
    assert "Reports saved to" in result.stdout


def test_successful_database_cli(tmp_path, monkeypatch, database):
    source = main.PROJECT_ROOT / "customers.csv"
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    assert main.main([str(source), "--load-db"]) == 0


def test_empty_database_run(tmp_path, database):
    source = tmp_path / "empty.csv"
    source.write_text("customer_id,name,email\n")
    _, report = main.run_pipeline(source, tmp_path / "reports", load_db=True)
    assert report["load_status"] == "succeeded"
    assert report["load_rows_submitted"] == report["load_rows_committed"] == 0
    database[0].assert_not_called()


def test_schema_is_repeatable_and_constrained():
    schema = (main.PROJECT_ROOT / "sql/schema.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.customers" in schema
    assert "INTEGER PRIMARY KEY" in schema
    assert "name TEXT NOT NULL CHECK" in schema
    assert "email TEXT NULL" in schema
