# Customer pipeline rules

Stage 3 implements CSV extraction, transformation, reports, and optional
PostgreSQL loading with `--load-db`. CSV-only mode remains the default.

## Input and cleaning

- The CSV must contain `customer_id`, `name`, and `email` columns. Missing or
  repeated column names stop the run with an error. Extra columns are ignored.
- Read fields as strings, preserving values such as leading zeros and the
  literal name `NA`. Remove surrounding whitespace before validation.
- Customer IDs must contain only ASCII digits and represent a positive whole
  number. Missing IDs, zero, negatives, decimals, and signed values are invalid.
  IDs above PostgreSQL INTEGER maximum (2147483647) are also invalid.
  Leading zeros are removed, so `001` and `1` identify the same customer.
- Names cannot be blank after trimming whitespace. Preserve name casing.
- Emails are optional. Empty or whitespace-only emails remain missing and
  appear as empty fields in the cleaned CSV. Never invent a replacement email.
- Convert nonempty email addresses to lowercase.
- The basic email check requires exactly one `@`, nonempty text before it,
  and a domain with at least one dot and nonempty parts between dots.
  Whitespace is forbidden. This checks format only, not whether an address
  exists; it is not a complete email-address standard validator.
- Malformed CSV syntax or records with the wrong number of fields stop the
  run before reports are created. A header-only file is valid with zero rows.
  Blank records are structural errors. Source row numbers in reports are CSV
  record positions, starting at 2 after the header; quoted multiline fields
  can span more than one physical line.

## Invalid rows and duplicates

- Validate before deduplication. Invalid rows are rejected with explanations.
- Keep the first valid occurrence of each normalized customer ID in file
  order. An invalid earlier row does not prevent a later valid row from being
  accepted. Later valid rows with that ID are duplicates even if details differ.
- Invalid rows remain classified as invalid even if their ID was already seen.
- Save invalid and duplicate records together in `rejected_records.csv`, with
  a separate `status`, a `reason`, source record number, and original field
  values. This combined file replaces the Stage 1 proposal for separate files.

## PostgreSQL updates (Stage 3)

- Use customer ID for upserts: insert new customers and update existing ones
  without creating extra customer records when an input is run again.
- An incoming valid email updates the stored email.
- An incoming missing email preserves the existing email if one exists.
- A new customer with a missing email gets SQL `NULL` (no value).
- Intentionally clearing an existing email is not supported in this version.
- Load a run in one transaction. On failure, roll back all its database
  changes, with no partially loaded records.

## Reports and safe output

Each run creates a new `reports/run-.../` directory containing:

- `cleaned_customers.csv`: valid unique customers, with missing emails empty.
- `rejected_records.csv`: invalid and duplicate source records with reasons.
- `data_quality.json`: input rows, valid unique rows, rejected invalid rows,
  duplicates, missing emails, and transformation status.

`input rows = valid unique rows + rejected invalid rows + duplicate rows`

Missing-email counts describe valid unique records in the current input file,
not necessarily the final database state. A successful transformation can still
include rejected rows. Extraction or output errors stop with an unsuccessful
exit status; no success report is generated. Incomplete output files are removed
if writing fails. Existing runs and the original sample CSVs are never overwritten.
Reports include load status (`not_attempted`, `in_progress`, `succeeded`, or
`failed`), rows submitted as a batch, and rows confirmed committed. These are not
counts of newly inserted customers. Failed loads include a sanitized explanation
and null for committed rows, since connection loss during commit can make the
outcome unknown. The command exits unsuccessfully and retains troubleshooting
reports. Success is reported only after the transaction context commits.
Database errors do not change transformation success. Empty valid datasets load
zero rows without a connection; the load option still requires DATABASE_URL.
Schema initialization is manual and never part of a pipeline run.

Database and local report writes are separate operations. A disk error after a
commit can leave an `in_progress` report even though data committed; rerun safely
after addressing the disk problem.

## Setup

The project targets the existing Python 3.9.6 environment. Direct dependency
versions are pinned in the requirements files. Pandas handles tabular data;
Psycopg 3 with its binary extra loads PostgreSQL; pytest runs tests.

`.env.example` contains a placeholder connection URL. Real credentials belong
in a local ignored `.env` file or the shell environment. The example file is
not loaded automatically. Generated reports are ignored by Git.
