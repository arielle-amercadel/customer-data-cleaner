"""Read CSV fields as strings and validate the file structure."""

import csv

import pandas as pd

REQUIRED_COLUMNS = ["customer_id", "name", "email"]


def extract_customers(input_path):
    """Return string fields; fail clearly on missing columns or malformed rows."""
    try:
        with open(input_path, newline="", encoding="utf-8-sig") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader, [])
            missing = set(REQUIRED_COLUMNS) - set(header)
            if missing:
                raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")
            if len(header) != len(set(header)):
                raise ValueError("CSV column names must be unique")
            records = []
            for record_number, values in enumerate(reader, start=2):
                if len(values) != len(header):
                    raise ValueError(f"CSV record {record_number} has the wrong number of fields")
                records.append(values)
    except csv.Error as error:
        raise ValueError(f"Malformed CSV: {error}") from error
    return pd.DataFrame(records, columns=header, dtype=str)[REQUIRED_COLUMNS]
