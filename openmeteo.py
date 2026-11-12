import clickhouse_connect
import pandas as pd
import requests

url = "https://archive-api.open-meteo.com/v1/archive"
params = {
    "latitude": 38.5816,
    "longitude": -121.4944,
    "start_date": "2025-10-01",
    "end_date": "2025-10-31",
    "hourly": "temperature_2m",
}

response = requests.get(url, params=params)
data = response.json()

df = pd.DataFrame(
    {
        "timestamp": data["hourly"]["time"],
        "temperature": data["hourly"]["temperature_2m"],
    }
)
df["country"] = "United States"
df["timestamp"] = pd.to_datetime(df["timestamp"])

print(f"Extracted and transformed total rows: {len(df)}")  

client = clickhouse_connect.get_client(
    host="localhost", port=8123, username="admin", password="Admin123"
)

client.command("CREATE DATABASE IF NOT EXISTS weather_db")

client.command("""
    CREATE TABLE IF NOT EXISTS weather_db.october_weather (
        timestamp DateTime,
        temperature Float32,
        country String
    ) ENGINE = MergeTree() ORDER BY timestamp
""")

client.insert_df("weather_db.october_weather", df)
print("Hourly data loaded into 'october_weather'!")


client.command("""
    CREATE TABLE IF NOT EXISTS weather_db.daily_weather_summary (
        observation_date Date,
        country String,
        max_temp Float32,
        min_temp Float32
    ) ENGINE = MergeTree() ORDER BY observation_date
""")


client.command("""
    INSERT INTO weather_db.daily_weather_summary
    SELECT 
        toDate(timestamp) AS observation_date,
        country,
        MAX(temperature) AS max_temp,
        MIN(temperature) AS min_temp
    FROM weather_db.october_weather
    GROUP BY observation_date, country
""")
print("Daily summary calculated and loaded into 'daily_weather_summary'!")


print("\n--- Table 1: Hourly Weather Data (First 3 rows) ---")
print(client.query_df("SELECT * FROM weather_db.october_weather LIMIT 3"))

print("\n--- Table 2: Daily Min/Max Summary Table (First 3 rows) ---")
print(
    client.query_df("SELECT * FROM weather_db.daily_weather_summary LIMIT 3")
)