# Customer Data Pipeline

A small Python ETL pipeline that extracts customer CSV data, cleans and validates
records, and optionally loads valid customers into local PostgreSQL. It produces
cleaned data, rejected records with explanations, and a JSON data-quality report.

**Technologies:** Python, Pandas, PostgreSQL, Psycopg 3, SQL, and pytest.

## Workflow and features

**Extract → Transform → Load**

1. **Extract:** read CSV fields as strings and check required columns and structure.
2. **Transform:** trim whitespace, lowercase emails, validate records, and keep the
   first valid occurrence of each customer ID. Report invalid and duplicate rows.
3. **Load (optional):** upsert valid unique customers into PostgreSQL in one
   transaction. CSV-only mode requires no database.

IDs must be positive integers within PostgreSQL's INTEGER range (1–2147483647).
Names cannot be blank. Emails are optional; nonempty emails must pass a basic
format check. Invalid rows do not prevent later valid rows with the same ID
from being accepted. See [pipeline rules](docs/pipeline-rules.md) for details.

## Project structure

```text
customer-data-cleaner/
├── main.py                         # CLI and reporting
├── pipeline/
│   ├── __init__.py
│   ├── extract.py                  # CSV input and structural checks
│   ├── transform.py                # Cleaning, validation, and deduplication
│   └── load.py                     # Transactional PostgreSQL upserts
├── sql/
│   ├── schema.sql                  # Manual table initialization
│   └── analysis.sql                # Four read-only analysis queries
├── data/customers_expanded.csv     # Expanded synthetic input
├── customers.csv                   # Original six-row sample
├── cleaned_customers.csv           # Preserved legacy output
├── docs/pipeline-rules.md
├── tests/
│   ├── test_pipeline.py
│   ├── test_load.py
│   └── test_postgres_integration.py
├── requirements.txt
├── requirements-dev.txt
├── .env.example                    # Placeholders only
├── .gitignore
└── reports/                        # Generated, ignored by Git
```

## Installation

The pinned dependencies support the project's existing Python 3.9.6 environment.
Run these commands from the repository root; reuse `.venv` if it already exists:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Development requirements include runtime dependencies and pytest. For runtime
only, install `requirements.txt`. No additional framework is required.

## CSV-only mode

```sh
python main.py
python main.py data/customers_expanded.csv
```

The default input is `customers.csv` beside `main.py`, independent of the working
directory. Custom relative input paths are relative to the current directory.
Each run prints its results and writes a new `reports/run-.../` directory:

- `cleaned_customers.csv`: valid unique rows; missing emails are empty fields.
- `rejected_records.csv`: invalid and duplicate rows, original values, source
  record numbers, status, and reasons.
- `data_quality.json`: transformation counts and database load status.

Previous reports and both original root CSV files are never overwritten.
The root `cleaned_customers.csv` is a legacy example, not the new pipeline output.
Generated reports, caches, virtual environments, and `.env` are ignored by Git.

## Local PostgreSQL setup

Install and start PostgreSQL locally using your preferred installer if needed.
The project has been tested locally with PostgreSQL 17. It does not install or
manage PostgreSQL, create databases, or initialize tables automatically.

For a new setup, manually create a development database using a PostgreSQL role
with permission to create databases. Skip this command if it already exists:

```sh
createdb customer_pipeline
```

Set and export `DATABASE_URL` using your local connection details. The format is
shown in [.env.example](.env.example); never commit real credentials. A `.env`
file is **not loaded automatically**. To enter a URL privately in Bash or Zsh:

```sh
read -r -s DATABASE_URL
export DATABASE_URL
```

Type the connection URL when prompted by the waiting command, then press Enter.
Initialize the table manually against your chosen development database:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/schema.sql
```

[The schema](sql/schema.sql) creates `public.customers` with a positive integer
primary key, a nonblank name, and a nullable email. Repeating initialization is
safe, but it does not migrate or repair an incompatible existing table. The
loader's role needs SELECT, INSERT, and UPDATE permissions on the table.

## Database-loading mode

```sh
python main.py --load-db
python main.py data/customers_expanded.csv --load-db
```

`--load-db` requires `DATABASE_URL`. Only valid unique rows are submitted using
parameterized SQL. Existing customer IDs update their names and supplied emails.
Missing incoming emails preserve existing emails; new customers without emails
get SQL `NULL`. Intentionally clearing an existing email is not supported.
Reruns update the same IDs instead of creating duplicate customers.

The whole batch uses one transaction. Query errors roll back the batch, preserve
troubleshooting reports, record load failure, and return exit code 1. Raw database
errors and connection strings are not printed. An empty valid batch submits zero
rows without connecting, but still requires DATABASE_URL in database mode.

Load counts describe batch rows submitted and committed, **not newly inserted
customers**. A connection lost during commit can leave the outcome unknown;
failure reports use `null` for committed rows. Rerunning the same file reconciles
those customer IDs safely.

## Example quality results

Both sample files contain fictional demonstration data and example.com addresses.
The original six-row sample is preserved; the expanded sample adds invalid IDs,
blank names, malformed emails, whitespace, mixed-case emails, and duplicates.

| Input | Input rows | Valid unique | Invalid | Duplicates | Missing emails* |
| --- | ---: | ---: | ---: | ---: | ---: |
| Original sample | 6 | 5 | 0 | 1 | 2 |
| Expanded sample | 15 | 6 | 7 | 2 | 2 |

*Missing emails among valid unique records in the current input, not necessarily
the final database state. Counts satisfy:

`input rows = valid unique rows + rejected invalid rows + duplicate rows`

Example JSON report for the original sample in CSV-only mode:

```json
{
  "input_rows": 6,
  "valid_unique_rows": 5,
  "rejected_invalid_rows": 0,
  "duplicate_rows": 1,
  "missing_emails": 2,
  "transformation_status": "succeeded",
  "load_status": "not_attempted",
  "load_rows_submitted": 0,
  "load_rows_committed": 0
}
```

A successful transformation may include rejected rows. In database mode,
`load_status` reports success or failure separately from transformation status.

## SQL analysis

[sql/analysis.sql](sql/analysis.sql) contains four SELECT queries:

1. Total customers.
2. Missing-email count and percentage, including safe handling of an empty table.
3. Customer counts by email domain, excluding missing emails.
4. Email addresses shared by multiple customer IDs.

Run the analysis manually after loading data, using your configured database:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f sql/analysis.sql
```

These queries only read the current database table. They are never run by the
pipeline and do not analyze rejected rows. Casing and surrounding spaces are
normalized for grouping; both NULL and blank emails count as missing.

## Automated tests

Run all unit tests without database access:

```sh
python -m pytest tests/test_pipeline.py tests/test_load.py -q
```

Run the complete suite (real tests skip unless explicitly enabled):

```sh
python -m pytest -q -rs
```

Unit tests cover extraction, cleaning, validation, report counts, safe outputs,
CLI behavior, SQL parameters, and mocked database failures. Real tests cover
inserts, updates, missing emails, reruns, and transaction rollback.

For real tests, manually create a **separate disposable local database** if it
does not already exist:

```sh
createdb customer_pipeline_test
```

Privately enter and export its URL, checking that it selects local
`customer_pipeline_test`, never `customer_pipeline` or a shared database:

```sh
read -r -s TEST_DATABASE_URL
export TEST_DATABASE_URL
RUN_DATABASE_TESTS=1 python -m pytest -q -rs
```

Both a nonempty `TEST_DATABASE_URL` and the exact flag `RUN_DATABASE_TESTS=1`
are required. The fixture does not validate the database name: choosing a
safe test database is your responsibility. No URL means real tests are skipped.

Each real test temporarily overrides the loader URL and SQL target, creates a
unique `etl_test_...` schema, initializes its table twice, and drops that schema
in cleanup. Existing public tables are untouched. The role needs permission to
create schemas. An interrupted process may leave its test schema behind.
You do not need to initialize `public.customers` for these tests.

To run only real integration tests with the same exported test URL:

```sh
RUN_DATABASE_TESTS=1 python -m pytest tests/test_postgres_integration.py -v -rs
```

## Limitations and possible improvements

- Intended for small CSV files; input and output records are held in memory.
- Email validation checks basic format, not deliverability or every valid email
  syntax. Malformed CSV structure stops the run rather than rejecting one row.
- Duplicate resolution follows file order, without timestamps or record merging.
- Database commits and local report writes are separate: a disk failure after
  commit may leave an `in_progress` report. Fix the disk issue and rerun safely.
- Reports include customer field values; use fictional inputs for public examples.
- Dependency versions target the original Python environment; a future update
  could move to a newer Python version and refresh the pinned dependencies.

Possible small next steps include streaming larger files, recording run history,
and adding a timestamp-based update policy. The current project runs manually
on a local machine, with no scheduling or production deployment infrastructure.
