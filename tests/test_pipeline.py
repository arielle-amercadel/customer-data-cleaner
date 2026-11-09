import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

import main
from pipeline.extract import REQUIRED_COLUMNS, extract_customers
from pipeline.transform import transform_customers

ROOT = Path(__file__).resolve().parents[1]


def transform(rows):
    return transform_customers(pd.DataFrame(rows, columns=REQUIRED_COLUMNS))


def test_extract_preserves_strings(tmp_path):
    path = tmp_path / "input.csv"
    path.write_text("customer_id,name,email\n001,NA,\n", encoding="utf-8")
    assert extract_customers(path).iloc[0].to_dict() == {
        "customer_id": "001", "name": "NA", "email": ""}


@pytest.mark.parametrize("content", ["", "name,email\nA,a@example.com\n"])
def test_missing_columns(tmp_path, content):
    path = tmp_path / "bad.csv"
    path.write_text(content)
    with pytest.raises(ValueError, match="Missing required columns"):
        extract_customers(path)


@pytest.mark.parametrize("content", [
    "customer_id,name,email\n1,A,a@example.com,extra\n",
    "customer_id,name,email\n1,A\n",
    'customer_id,name,email\n1,"unterminated,email\n',
    "customer_id,name,email,email\n",
])
def test_bad_structure(tmp_path, content):
    path = tmp_path / "bad.csv"
    path.write_text(content)
    with pytest.raises(ValueError):
        extract_customers(path)


def test_cleaning():
    cleaned, rejected, report = transform([[" 001 ", " Avery Example ", " AVERY@EXAMPLE.COM "]])
    assert cleaned.iloc[0].to_dict() == {
        "customer_id": "1", "name": "Avery Example", "email": "avery@example.com"}
    assert rejected.empty
    assert report["valid_unique_rows"] == 1


@pytest.mark.parametrize("email", ["", "   ", "\t"])
def test_missing_email(email):
    cleaned, _, report = transform([["1", "A", email]])
    assert cleaned.iloc[0]["email"] is None
    assert report["missing_emails"] == 1


@pytest.mark.parametrize("customer_id", ["", "0", "000", "-1", "1.5", "abc", "+1", "1e2", "١"])
def test_invalid_ids(customer_id):
    cleaned, rejected, report = transform([[customer_id, "A", ""]])
    assert cleaned.empty
    assert "positive integer" in rejected.iloc[0]["reason"]
    assert report["rejected_invalid_rows"] == 1


@pytest.mark.parametrize("name", ["", "  ", "\t"])
def test_blank_names(name):
    assert "name cannot be blank" in transform([["1", name, ""]])[1].iloc[0]["reason"]


@pytest.mark.parametrize("email", ["bad", "a@b", "@example.com", "a@@example.com",
                                   "a b@example.com", "a@example.", "a@.com", "a@b..com"])
def test_bad_email(email):
    assert "email has invalid format" in transform([["1", "A", email]])[1].iloc[0]["reason"]


def test_duplicates_and_invalid_before_valid():
    cleaned, rejected, report = transform([
        ["1", "", ""], ["1", "First", "first@example.com"],
        ["01", "Conflict", "other@example.com"], ["1", "", ""],
    ])
    assert cleaned["name"].tolist() == ["First"]
    assert rejected["status"].tolist() == ["invalid", "duplicate", "invalid"]
    assert rejected["source_row"].tolist() == [2, 4, 5]
    assert rejected.iloc[1]["name"] == "Conflict"
    assert report["duplicate_rows"] == 1


@pytest.mark.parametrize("filename,expected", [
    ("customers.csv", (6, 5, 0, 1, 2)),
    ("data/customers_expanded.csv", (15, 6, 7, 2, 2)),
])
def test_sample_counts(filename, expected):
    _, _, report = transform_customers(extract_customers(ROOT / filename))
    keys = ["input_rows", "valid_unique_rows", "rejected_invalid_rows", "duplicate_rows", "missing_emails"]
    assert tuple(report[key] for key in keys) == expected
    assert report["input_rows"] == sum(report[key] for key in keys[1:4])
    assert report["transformation_status"] == "succeeded"


def test_empty_input_with_header(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("customer_id,name,email\n")
    cleaned, rejected, report = transform_customers(extract_customers(path))
    assert cleaned.empty and rejected.empty
    assert report["input_rows"] == 0


def test_safe_outputs_and_repeat_runs(tmp_path):
    source = tmp_path / "cleaned_customers.csv"
    source.write_bytes((ROOT / "customers.csv").read_bytes())
    before = source.read_bytes()
    first, report = main.run_pipeline(source, tmp_path)
    second, _ = main.run_pipeline(source, tmp_path)
    assert first != second
    assert source.read_bytes() == before
    assert json.loads((first / "data_quality.json").read_text()) == report
    cleaned = extract_customers(first / "cleaned_customers.csv")
    assert cleaned["email"].tolist().count("") == 2
    rejected = pd.read_csv(first / "rejected_records.csv")
    assert rejected["status"].tolist() == ["duplicate"]
    assert rejected["reason"].notna().all()


def test_custom_cli_path(tmp_path, monkeypatch):
    source = tmp_path / "custom.csv"
    source.write_text("customer_id,name,email\n99,Custom,\n")
    monkeypatch.setattr(main, "PROJECT_ROOT", tmp_path)
    assert main.main([str(source)]) == 0
    report_path = next((tmp_path / "reports").glob("run-*/data_quality.json"))
    assert json.loads(report_path.read_text())["valid_unique_rows"] == 1


def test_default_path_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output, report = main.run_pipeline(reports_root=tmp_path / "reports")
    assert report["input_rows"] == 6
    assert output.exists()


def test_failure_does_not_write_reports(tmp_path):
    with pytest.raises(FileNotFoundError):
        main.run_pipeline(tmp_path / "missing.csv", tmp_path / "reports")
    assert not (tmp_path / "reports").exists()


def test_write_failure_cleans_run_directory(tmp_path, monkeypatch):
    original_to_csv = pd.DataFrame.to_csv
    calls = []

    def fail(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise OSError("simulated disk failure")
        return original_to_csv(*args, **kwargs)
    monkeypatch.setattr(pd.DataFrame, "to_csv", fail)
    with pytest.raises(OSError, match="simulated disk failure"):
        main.run_pipeline(ROOT / "customers.csv", tmp_path / "reports")
    assert list((tmp_path / "reports").iterdir()) == []


def test_cli_failure(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "main.py"), str(tmp_path / "missing.csv")],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "Pipeline failed" in result.stderr


def test_imports_have_no_io(tmp_path):
    code = '''
import builtins
import pathlib
import pandas
import tempfile
from unittest.mock import patch
with patch.object(builtins, "open", side_effect=AssertionError("unexpected read")), \\
     patch.object(pathlib.Path, "mkdir", side_effect=AssertionError("unexpected mkdir")), \\
     patch.object(pandas.DataFrame, "to_csv", side_effect=AssertionError("unexpected write")), \\
     patch.object(tempfile, "mkdtemp", side_effect=AssertionError("unexpected output")):
    import main
    import pipeline.extract
    import pipeline.transform
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
