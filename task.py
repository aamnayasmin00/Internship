import os
import requests
import pandas as pd
import clickhouse_connect

# =====================================================================
# FIXED CONFIGURATIONS
# =====================================================================
BASE = "https://jsonplaceholder.typicode.com"
WEATHER_BASE = "https://archive-api.open-meteo.com/v1/archive"

# Coordinates (Latitude & Longitude)
LATITUDE = 38.6275
LONGITUDE = -92.5666

# ClickHouse Client Setup
CH_HOST = "localhost"
CH_PORT = 8123
CH_USER = "admin"
CH_PASSWORD = "Admin123"


def title(text):
    """Helper function to print clean section headers."""
    print(f"\n{'='*10} {text} {'='*10}")


# =====================================================================
# EXAMPLE 1: The simplest GET request
# =====================================================================
title("1 - GET /users")

try:
    response = requests.get(f"{BASE}/users", timeout=10)
    print("status code:", response.status_code)
    print("content type:", response.headers.get("content-type"))

    users = response.json()
    print("users found:", len(users))
    if users and isinstance(users, list):
        print("first user:", users[0]["name"])
except Exception as e:
    print("Failed Example 1 Request:", e)


# =====================================================================
# EXAMPLE 2: Passing parameters (Filtering data)
# =====================================================================
title("2 - GET /posts?userId=1")

try:
    response = requests.get(f"{BASE}/posts", params={"userId": 1}, timeout=10)
    posts = response.json()

    print("posts of user 1:", len(posts))
    if posts and isinstance(posts, list):
        print("first title  :", posts[0]["title"])
except Exception as e:
    print("Failed Example 2 Request:", e)


# =====================================================================
# EXAMPLE 3 - Errors: status codes, raise_for_status(), timeout
# =====================================================================
title("3 - Handling errors")

try:
    response = requests.get(f"{BASE}/users/9999", timeout=10)
    print("status code:", response.status_code)
    response.raise_for_status()

except requests.exceptions.HTTPError as e:
    print("HTTP error :", e)
except requests.exceptions.Timeout:
    print("Timeout error")
except requests.exceptions.ConnectionError:
    print("No internet / wrong address")


# =====================================================================
# EXAMPLE 4 - Headers and API key (Authentication)
# =====================================================================
title("4 - Headers and API key")

API_KEY = os.getenv("MY_API_KEY", "demo-key-123")
print(f"Using API Key: {API_KEY}")

headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "User-Agent": "rizviz-training/1.0",
}

try:
    response = requests.get(f"{BASE}/users", headers=headers, timeout=10)
    print("status:", response.status_code)
    print("sent headers text:", response.request.headers.get("User-Agent"))
except Exception as e:
    print("Failed Example 4 Request:", e)


# =====================================================================
# EXAMPLE 5 - Fetch October Weather Data from Open-Meteo Archive
# =====================================================================
title("5 - Fetch October Weather Data from Open-Meteo")

weather_params = {
    "latitude": LATITUDE,
    "longitude": LONGITUDE,
    "start_date": "2025-10-01",  # Start of October
    "end_date": "2025-10-31",    # End of October (31 days * 24 hours = 744 rows)
    "hourly": "temperature_2m",
    "timezone": "UTC"
}

weather_data = None
try:
    response = requests.get(WEATHER_BASE, params=weather_params, timeout=15)
    print("status code:", response.status_code)
    response.raise_for_status()
    
    weather_data = response.json()
    print("Weather API payload received successfully")

except requests.exceptions.HTTPError as e:
    print("HTTP error fetching weather:", e)
except requests.exceptions.Timeout:
    print("Weather API timeout error")
except requests.exceptions.ConnectionError:
    print("Connection error: Please check your internet connection")


# =====================================================================
# EXAMPLE 6 - Read Data and Store in Dataframe (DF)
# =====================================================================
title("6 - Read Data into DataFrame")

if weather_data and "hourly" in weather_data:
    hourly_raw = weather_data["hourly"]

    # Build pandas dataframe mapping time and temperature strings with proper column names
    df = pd.DataFrame({
        "timestamp": pd.to_datetime(hourly_raw["time"]),
        "temperature": hourly_raw["temperature_2m"]
    })

    print("DataFrame constructed successfully")
    print("Total rows fetched (expecting 744 for October):", len(df))
    print(df.head(3))
else:
    print("Skipping Example 6: No weather data payload available.")


# =====================================================================
# EXAMPLE 7 - Store Table in ClickHouse
# =====================================================================
title("7 - Store Table in ClickHouse")

if 'df' in locals() and not df.empty:
    try:
        # Initialize connection client
        client = clickhouse_connect.get_client(host=CH_HOST, port=CH_PORT, username=CH_USER, password=CH_PASSWORD)
        
        # Create raw landing table structure
        client.command("""
            CREATE TABLE IF NOT EXISTS default.october_hourly_raw (
                timestamp DateTime,
                temperature Float32
            ) ENGINE = MergeTree()
            ORDER BY timestamp;
        """)
        
        # Clear old execution remnants 
        client.command("TRUNCATE TABLE default.october_hourly_raw")
        
        # Insert structured pandas dataframe explicitly
        client.insert_df("default.october_hourly_raw", df)
        print("Raw weather data successfully inserted into ClickHouse table: default.october_hourly_raw")

    except Exception as e:
        print("ClickHouse landing error:", e)
else:
    print("Skipping Example 7: DataFrame does not exist.")


# =====================================================================
# EXAMPLE 8 - Read from ClickHouse and Perform Daily Evaluation (Min/Max)
# =====================================================================
title("8 - Read from ClickHouse and Evaluate Daily Metrics")

if 'df' in locals() and not df.empty:
    try:
        # Extract data directly back out of database storage engine
        df_ch = client.query_df("SELECT timestamp, temperature FROM default.october_hourly_raw")
        print("Rows pulled back out of ClickHouse:", len(df_ch))
        
        # Create a helper column containing only the calendar date using pandas datetime accessor
        df_ch['date'] = df_ch['timestamp'].dt.date
        
        # Compute min and max temperature for each unique 24-hour daily block
        daily_stats = df_ch.groupby('date')['temperature'].agg(['max', 'min']).reset_index()
        daily_stats.rename(columns={'max': 'daily_max_temperature', 'min': 'daily_min_temperature'}, inplace=True)
        
        # Merge statistics back alongside original timestamps to maintain the 744 hourly rows structure
        df_evaluated = pd.merge(df_ch, daily_stats, on='date', how='left')
        
        # Strip temporary date column before loading
        df_evaluated.drop(columns=['date'], inplace=True)
        
        print("Evaluation matrix successfully calculated")
        print("Evaluated Dataframe Rows (expecting 744):", len(df_evaluated))
        print(df_evaluated.head(3))

    except Exception as e:
        print("Evaluation execution error:", e)
else:
    print("Skipping Example 8: ClickHouse database was not populated.")


# =====================================================================
# EXAMPLE 9 - Load Evaluated Table back to ClickHouse
# =====================================================================
title("9 - Load Evaluated Table back to ClickHouse")

if 'df_evaluated' in locals() and not df_evaluated.empty:
    try:
        # Create destination database structural mapping schema
        client.command("""
            CREATE TABLE IF NOT EXISTS default.october_daily_evaluations (
                timestamp DateTime,
                temperature Float32,
                daily_max_temperature Float32,
                daily_min_temperature Float32
            ) ENGINE = MergeTree()
            ORDER BY timestamp;
        """)
        
        # Empty destination rows to allow clean append sequence
        client.command("TRUNCATE TABLE default.october_daily_evaluations")
        
        # Push the enriched processed dataframe down to destination storage engine
        client.insert_df("default.october_daily_evaluations", df_evaluated)
        print("Processed evaluation tables successfully generated and finalized in ClickHouse!")
        
        # Verification read back check
        preview = client.query_df("SELECT * FROM default.october_daily_evaluations LIMIT 5")
        print("\n--- Final ClickHouse Table Sample Output ---")
        print(preview.to_string(index=False))

    except Exception as e:
        print("ClickHouse loading metrics error:", e)
else:
    print("Skipping Example 9: No evaluated data available to load.")