"""Process customer CSVs and reports, optionally loading PostgreSQL with --load-db."""

import argparse
import json
from pathlib import Path
import tempfile

from pipeline.extract import extract_customers
from pipeline.transform import transform_customers

PROJECT_ROOT = Path(__file__).resolve().parent


def write_quality_report(output_dir, report):
    """Replace the report only after its complete replacement is written."""
    temporary = output_dir / "data_quality.json.tmp"
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    temporary.replace(output_dir / "data_quality.json")


def run_pipeline(input_path=PROJECT_ROOT / "customers.csv", reports_root=None, load_db=False):
    """Write each successful transformation to a new, unique report directory."""
    records = extract_customers(input_path)
    cleaned, rejected, report = transform_customers(records)
    report.update(load_status="not_attempted", load_rows_submitted=0,
                  load_rows_committed=0)
    root = Path(reports_root) if reports_root is not None else PROJECT_ROOT / "reports"
    root.mkdir(parents=True, exist_ok=True)
    output_dir = Path(tempfile.mkdtemp(prefix="run-", dir=root))
    try:
        cleaned.to_csv(output_dir / "cleaned_customers.csv", index=False)
        rejected.to_csv(output_dir / "rejected_records.csv", index=False)
        write_quality_report(output_dir, report)
    except Exception:
        # Remove only files created by this run if reporting cannot finish.
        for path in output_dir.iterdir():
            path.unlink()
        output_dir.rmdir()
        raise
    if load_db:
        from pipeline.load import DatabaseLoadError, load_customers

        report["load_status"] = "in_progress"
        write_quality_report(output_dir, report)
        try:
            submitted = load_customers(cleaned)
        except DatabaseLoadError as error:
            report["load_status"] = "failed"
            report["load_error"] = str(error)
            report["load_rows_submitted"] = error.rows_submitted
            report["load_rows_committed"] = None
        else:
            report.update(load_status="succeeded", load_rows_submitted=submitted,
                          load_rows_committed=submitted)
        write_quality_report(output_dir, report)
    return output_dir, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_csv", nargs="?", type=Path,
                        default=PROJECT_ROOT / "customers.csv",
                        help="Input CSV (default: customers.csv beside main.py)")
    parser.add_argument("--load-db", action="store_true",
                        help="Upsert valid customers using DATABASE_URL")
    args = parser.parse_args(argv)
    try:
        output_dir, report = run_pipeline(args.input_csv, load_db=args.load_db)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Pipeline failed: {error}\n")
    print(json.dumps(report, indent=2))
    print(f"Reports saved to {output_dir}")
    return 1 if report["load_status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
