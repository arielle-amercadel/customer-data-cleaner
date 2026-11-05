# Customer Data Cleaner

A beginner-friendly ETL (Extract, Transform, Load) project built with Python and Pandas.

## Features

- Reads customer data from a CSV file.
- Identifies missing values.
- Removes duplicate customer IDs, keeping the first occurrence.
- Replaces missing email addresses with a placeholder.
- Exports cleaned data to a new CSV file.

## Technologies

- Python
- Pandas
- CSV

## How to Run

1. Create and activate a Python virtual environment.
2. Install Pandas:

   `python -m pip install pandas`

3. Run the program:

   `python main.py`

4. View the results in `cleaned_customers.csv`.

## Project Files

- `main.py` — ETL pipeline.
- `customers.csv` — Original customer data.
- `cleaned_customers.csv` — Cleaned output.

## What I Learned

This project helped me practice reading CSV files, working with Pandas DataFrames, handling missing values, removing duplicate records, and exporting cleaned data.