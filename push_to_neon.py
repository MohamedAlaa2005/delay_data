import csv
import os
import re
import sys
from datetime import datetime
import psycopg2
from psycopg2.extras import execute_values

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

def parse_datetime(date_str, time_str):
    if not date_str or not time_str:
        return None
    d_parts = date_str.strip().split()
    y, m, d = 2026, 11, 17
    if len(d_parts) >= 4:
        try:
            d = int(d_parts[1])
            m = MONTH_MAP.get(d_parts[2].lower(), 11)
            y = int(d_parts[3])
        except Exception:
            pass

    t_match = re.search(r"(\d{1,2}):(\d{2})", time_str)
    if t_match:
        hr = int(t_match.group(1))
        mi = int(t_match.group(2))
        return datetime(y, m, d, hr, mi)
    return None

def to_float(val):
    try:
        return float(val) if val not in [None, ""] else None
    except (ValueError, TypeError):
        return None

def to_int(val):
    try:
        return int(float(val)) if val not in [None, ""] else None
    except (ValueError, TypeError):
        return None

def get_connection_string():
    # 1. Environment variable
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        return db_url

    # 2. Check .env.local
    for env_file in [".env.local", ".env"]:
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL=") or line.startswith("POSTGRES_URL="):
                        val = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if val:
                            return val

    # 3. Check neon.json / connection files
    return None

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id SERIAL PRIMARY KEY,
    airport_iata VARCHAR(3) NOT NULL,
    scheduled_time TIMESTAMP NOT NULL,
    flight VARCHAR(20),
    airline VARCHAR(60),
    route_airport VARCHAR(60),
    delay_minutes INT,
    
    -- Aviation Weather (METAR)
    metar_time VARCHAR(30),
    metar_flt_cat VARCHAR(10),
    metar_temp_c FLOAT,
    metar_dewp_c FLOAT,
    metar_wdir_deg INT,
    metar_wspd_kt INT,
    metar_visib_mi VARCHAR(10),
    metar_altim_hpa INT,
    metar_cover VARCHAR(10),
    metar_cloud_base_ft INT,
    
    -- Surface Weather (WeatherAPI)
    wapi_temp_c FLOAT,
    wapi_feelslike_c FLOAT,
    wapi_rh_pct INT,
    wapi_precip_mm FLOAT,
    wapi_pressure_hpa FLOAT,
    wapi_cloud_pct INT,
    wapi_vis_km FLOAT,
    wapi_wind_spd_kph FLOAT,
    wapi_wind_dir_deg INT,
    wapi_wind_gust_kph FLOAT,
    wapi_cond_text VARCHAR(60),
    wapi_cond_code INT,
    wapi_is_day INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_{table_name}_airport ON {table_name}(airport_iata);
CREATE INDEX IF NOT EXISTS idx_{table_name}_time ON {table_name}(scheduled_time);
"""

COLUMNS = [
    "airport_iata", "scheduled_time", "flight", "airline", "route_airport", "delay_minutes",
    "metar_time", "metar_flt_cat", "metar_temp_c", "metar_dewp_c", "metar_wdir_deg",
    "metar_wspd_kt", "metar_visib_mi", "metar_altim_hpa", "metar_cover", "metar_cloud_base_ft",
    "wapi_temp_c", "wapi_feelslike_c", "wapi_rh_pct", "wapi_precip_mm", "wapi_pressure_hpa",
    "wapi_cloud_pct", "wapi_vis_km", "wapi_wind_spd_kph", "wapi_wind_dir_deg", "wapi_wind_gust_kph",
    "wapi_cond_text", "wapi_cond_code", "wapi_is_day"
]

def load_and_transform_csv(csv_path):
    if not os.path.exists(csv_path):
        return []
    rows = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            dt = parse_datetime(r.get("date"), r.get("scheduled"))
            if not dt:
                continue
            row_tuple = (
                r.get("airport_iata", "").strip().upper(),
                dt,
                r.get("flight", "").strip(),
                r.get("airline", "").strip(),
                r.get("route_airport", "").strip(),
                to_int(r.get("delay_minutes")),
                r.get("metar_time", "").strip(),
                r.get("metar_flt_cat", "").strip(),
                to_float(r.get("metar_temp_c")),
                to_float(r.get("metar_dewp_c")),
                to_int(r.get("metar_wdir_deg")),
                to_int(r.get("metar_wspd_kt")),
                r.get("metar_visib_mi", "").strip(),
                to_int(r.get("metar_altim_hpa")),
                r.get("metar_cover", "").strip(),
                to_int(r.get("metar_cloud_base_ft")),
                to_float(r.get("wapi_temp_c")),
                to_float(r.get("wapi_feelslike_c")),
                to_int(r.get("wapi_rh_pct")),
                to_float(r.get("wapi_precip_mm")),
                to_float(r.get("wapi_pressure_hpa")),
                to_int(r.get("wapi_cloud_pct")),
                to_float(r.get("wapi_vis_km")),
                to_float(r.get("wapi_wind_spd_kph")),
                to_int(r.get("wapi_wind_dir_deg")),
                to_float(r.get("wapi_wind_gust_kph")),
                r.get("wapi_cond_text", "").strip(),
                to_int(r.get("wapi_cond_code")),
                to_int(r.get("wapi_is_day"))
            )
            rows.append(row_tuple)
    return rows

def push_table(conn, table_name, csv_path):
    data = load_and_transform_csv(csv_path)
    if not data:
        print(f"[!] No valid data found in {csv_path} to push.")
        return 0

    with conn.cursor() as cur:
        # Create table & indexes
        cur.execute(CREATE_TABLE_SQL.format(table_name=table_name))
        
        # Clear existing data to avoid duplicates on re-run
        cur.execute(f"TRUNCATE TABLE {table_name};")

        # High-performance batch insert
        col_names = ", ".join(COLUMNS)
        insert_query = f"INSERT INTO {table_name} ({col_names}) VALUES %s"
        execute_values(cur, insert_query, data, page_size=1000)

    conn.commit()
    print(f"[✓] Successfully inserted {len(data):,} records into Neon table '{table_name}'.")
    return len(data)

def main():
    conn_str = get_connection_string()
    if not conn_str:
        print("[!] ERROR: Neon connection string not found.")
        print("    Ensure `neon deploy` has written credentials to `.env.local` or set `DATABASE_URL`.")
        sys.exit(1)

    print("Connecting to Neon PostgreSQL database...")
    try:
        conn = psycopg2.connect(conn_str)
        print("[✓] Connected to Neon PostgreSQL successfully!")
        
        # 1. Push departures
        print("\nPushing departures table...")
        push_table(conn, "departures", "departures_with_weather.csv")

        # 2. Push arrivals
        print("\nPushing arrivals table...")
        push_table(conn, "arrivals", "arrivals_with_weather.csv")

        conn.close()
        print("\n[✓] All data pushed to Neon PostgreSQL successfully!")
    except Exception as e:
        print(f"[!] Database error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

