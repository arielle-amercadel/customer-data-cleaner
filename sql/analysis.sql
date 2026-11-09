-- Analyze the loaded public.customers table. These queries only read data.

-- 1. Count all customers currently stored in PostgreSQL.
SELECT COUNT(*) AS total_customers
FROM public.customers;

-- 2. Count missing emails and their percentage; an empty table reports 0.00%.
-- NULL and blank values both count as missing (pipeline loads use NULL).
SELECT
    COUNT(*) AS total_customers,
    COUNT(*) FILTER (WHERE NULLIF(BTRIM(email), '') IS NULL) AS missing_email_count,
    COALESCE(
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE NULLIF(BTRIM(email), '') IS NULL)
            / NULLIF(COUNT(*), 0),
            2
        ),
        0.00
    ) AS missing_email_percentage
FROM public.customers;

-- 3. Group customers by email domain, excluding missing emails.
SELECT
    SPLIT_PART(LOWER(BTRIM(email)), '@', 2) AS email_domain,
    COUNT(*) AS customer_count
FROM public.customers
WHERE NULLIF(BTRIM(email), '') IS NOT NULL
GROUP BY SPLIT_PART(LOWER(BTRIM(email)), '@', 2)
ORDER BY customer_count DESC, email_domain;

-- 4. Find email addresses shared by multiple customer IDs.
-- Normalize casing and surrounding spaces before grouping.
SELECT
    LOWER(BTRIM(email)) AS shared_email,
    COUNT(DISTINCT customer_id) AS customer_count,
    ARRAY_AGG(DISTINCT customer_id ORDER BY customer_id) AS customer_ids
FROM public.customers
WHERE NULLIF(BTRIM(email), '') IS NOT NULL
GROUP BY LOWER(BTRIM(email))
HAVING COUNT(DISTINCT customer_id) > 1
ORDER BY customer_count DESC, shared_email;
