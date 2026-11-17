import os
import re
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import execute_values
from config.settings import DATABASE_URL

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

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
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uniq_{table_name}_flight_time UNIQUE (airport_iata, flight, scheduled_time)
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

def parse_flight_timestamp(date_str, time_str):
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
        return datetime(y, m, d, int(t_match.group(1)), int(t_match.group(2)))
    return None

def upsert_records(table_name, records):
    """Upsert records into Neon PostgreSQL without duplicating flights."""
    db_url = os.environ.get("DATABASE_URL") or DATABASE_URL
    if not db_url:
        print("[!] DATABASE_URL not configured. Skipping Neon push.")
        return 0

    if not records:
        return 0

    conn = psycopg2.connect(db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(table_name=table_name))

            tuples = []
            for r in records:
                sched_dt = parse_flight_timestamp(r.get("date"), r.get("scheduled"))
                if not sched_dt:
                    continue

                def to_f(v): return float(v) if v not in [None, ""] else None
                def to_i(v): return int(float(v)) if v not in [None, ""] else None

                t = (
                    r.get("airport_iata", "").strip().upper(),
                    sched_dt,
                    r.get("flight", "").strip(),
                    r.get("airline", "").strip(),
                    r.get("route_airport", "").strip(),
                    to_i(r.get("delay_minutes")),
                    r.get("metar_time", ""),
                    r.get("metar_flt_cat", ""),
                    to_f(r.get("metar_temp_c")),
                    to_f(r.get("metar_dewp_c")),
                    to_i(r.get("metar_wdir_deg")),
                    to_i(r.get("metar_wspd_kt")),
                    r.get("metar_visib_mi", ""),
                    to_i(r.get("metar_altim_hpa")),
                    r.get("metar_cover", ""),
                    to_i(r.get("metar_cloud_base_ft")),
                    to_f(r.get("wapi_temp_c")),
                    to_f(r.get("wapi_feelslike_c")),
                    to_i(r.get("wapi_rh_pct")),
                    to_f(r.get("wapi_precip_mm")),
                    to_f(r.get("wapi_pressure_hpa")),
                    to_i(r.get("wapi_cloud_pct")),
                    to_f(r.get("wapi_vis_km")),
                    to_f(r.get("wapi_wind_spd_kph")),
                    to_i(r.get("wapi_wind_dir_deg")),
                    to_f(r.get("wapi_wind_gust_kph")),
                    r.get("wapi_cond_text", ""),
                    to_i(r.get("wapi_cond_code")),
                    to_i(r.get("wapi_is_day"))
                )
                tuples.append(t)

            col_str = ", ".join(COLUMNS)
            query = f"""
            INSERT INTO {table_name} ({col_str}) VALUES %s
            ON CONFLICT (airport_iata, flight, scheduled_time) DO UPDATE SET
                delay_minutes = EXCLUDED.delay_minutes,
                metar_flt_cat = EXCLUDED.metar_flt_cat,
                wapi_temp_c = EXCLUDED.wapi_temp_c,
                wapi_cond_code = EXCLUDED.wapi_cond_code;
            """
            execute_values(cur, query, tuples, page_size=1000)

        conn.commit()
        print(f"[✓] Upserted {len(tuples):,} records into Neon '{table_name}'.")
        return len(tuples)
    finally:
        conn.close()

