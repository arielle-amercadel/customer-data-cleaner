import pandas as pd

# Step 1: Extract - Read the CSV file
df = pd.read_csv("customers.csv")

print("Original Data:")
print(df.head())

# Step 2: Check for missing values
print("\nMissing Values:")
print(df.isnull().sum())

# Step 3: Remove duplicate rows
df = df.drop_duplicates(subset=["customer_id"])

# Step 4: Fill missing emails
df["email"] = df["email"].fillna("unknown@example.com")

# Step 5: Save the cleaned data
df.to_csv("cleaned_customers.csv", index=False)

print("\nCleaned Data:")
print(df)