-- Run manually against your chosen local database; never run by the pipeline.
CREATE TABLE IF NOT EXISTS public.customers (
    customer_id INTEGER PRIMARY KEY CHECK (customer_id > 0),
    name TEXT NOT NULL CHECK (name ~ '[^[:space:]]'),
    email TEXT NULL
);
