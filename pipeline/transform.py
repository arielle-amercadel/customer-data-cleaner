"""Clean and validate customers before selecting the first valid ID."""

import re

import pandas as pd

from pipeline.extract import REQUIRED_COLUMNS

EMAIL_PATTERN = re.compile(r"[^\s@]+@[^\s@.]+(?:\.[^\s@.]+)+")


def transform_customers(records):
    """Return cleaned rows, excluded source rows with reasons, and quality counts."""
    valid = []
    rejected = []
    seen_ids = set()
    invalid_count = 0
    duplicate_count = 0
    for source_row, original in enumerate(records.to_dict("records"), start=2):
        customer_id = original["customer_id"].strip()
        name = original["name"].strip()
        email = original["email"].strip().lower()
        reasons = []
        if not re.fullmatch(r"[0-9]+", customer_id) or not customer_id.strip("0"):
            reasons.append("customer_id must be a positive integer")
        else:
            customer_id = customer_id.lstrip("0")
            if len(customer_id) > 10 or (len(customer_id) == 10 and customer_id > "2147483647"):
                reasons.append("customer_id exceeds PostgreSQL INTEGER maximum (2147483647)")
        if not name:
            reasons.append("name cannot be blank")
        if email and not EMAIL_PATTERN.fullmatch(email):
            reasons.append("email has invalid format")
        if reasons:
            status = "invalid"
            invalid_count += 1
        elif customer_id in seen_ids:
            status = "duplicate"
            reasons.append("duplicate customer_id; first valid occurrence kept")
            duplicate_count += 1
        else:
            seen_ids.add(customer_id)
            valid.append({"customer_id": customer_id, "name": name, "email": email or None})
            continue
        rejected.append({"source_row": source_row, **original,
                         "status": status, "reason": "; ".join(reasons)})

    report = {
        "input_rows": len(records),
        "valid_unique_rows": len(valid),
        "rejected_invalid_rows": invalid_count,
        "duplicate_rows": duplicate_count,
        "missing_emails": sum(row["email"] is None for row in valid),
        "transformation_status": "succeeded",
    }
    if len(records) != len(valid) + invalid_count + duplicate_count:
        raise ValueError("Quality report row counts do not balance")
    cleaned = pd.DataFrame(valid, columns=REQUIRED_COLUMNS)
    excluded = pd.DataFrame(rejected, columns=["source_row", *REQUIRED_COLUMNS, "status", "reason"])
    return cleaned, excluded, report
