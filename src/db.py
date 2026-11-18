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

# =====================================================================
# NORMALIZED DATABASE SCHEMAS & VIEWS
# =====================================================================

CREATE_WEATHER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS airport_weather (
    id SERIAL PRIMARY KEY,
    airport_iata VARCHAR(3) NOT NULL,
    observation_time TIMESTAMP NOT NULL,
    
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
CREATE UNIQUE INDEX IF NOT EXISTS uniq_weather_airport_time ON airport_weather(airport_iata, observation_time);
CREATE INDEX IF NOT EXISTS idx_weather_airport_time ON airport_weather(airport_iata, observation_time DESC);
"""

CREATE_FLIGHT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table_name} (
    id SERIAL PRIMARY KEY,
    airport_iata VARCHAR(3) NOT NULL,
    scheduled_time TIMESTAMP NOT NULL,
    flight VARCHAR(20),
    airline VARCHAR(60),
    route_airport VARCHAR(60),
    delay_minutes INT,
    status VARCHAR(60),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_{table_name}_flight_time ON {table_name}(airport_iata, flight, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_{table_name}_airport ON {table_name}(airport_iata);
CREATE INDEX IF NOT EXISTS idx_{table_name}_time ON {table_name}(scheduled_time);
CREATE INDEX IF NOT EXISTS idx_{table_name}_hour ON {table_name}(airport_iata, date_trunc('hour', scheduled_time));
"""

CREATE_VIEW_SQL = """
CREATE OR REPLACE VIEW v_{table_name} AS
SELECT 
    f.id,
    f.airport_iata,
    f.scheduled_time,
    f.flight,
    f.airline,
    f.route_airport,
    f.delay_minutes,
    f.status,
    '{table_type}' AS type,
    -- Normalized weather joined on hourly observation time (exactly 24 rows per airport/day)
    w.metar_time,
    w.metar_flt_cat,
    w.metar_temp_c,
    w.metar_dewp_c,
    w.metar_wdir_deg,
    w.metar_wspd_kt,
    w.metar_visib_mi,
    w.metar_altim_hpa,
    w.metar_cover,
    w.metar_cloud_base_ft,
    w.wapi_temp_c,
    w.wapi_feelslike_c,
    w.wapi_rh_pct,
    w.wapi_precip_mm,
    w.wapi_pressure_hpa,
    w.wapi_cloud_pct,
    w.wapi_vis_km,
    w.wapi_wind_spd_kph,
    w.wapi_wind_dir_deg,
    w.wapi_wind_gust_kph,
    w.wapi_cond_text,
    w.wapi_cond_code,
    w.wapi_is_day,
    f.created_at
FROM {table_name} f
LEFT JOIN airport_weather w 
    ON f.airport_iata = w.airport_iata 
   AND date_trunc('hour', f.scheduled_time) = w.observation_time;

CREATE OR REPLACE VIEW v_{table_name}_with_weather AS
SELECT * FROM v_{table_name};
"""

FLIGHT_COLUMNS = [
    "airport_iata", "scheduled_time", "flight", "airline", "route_airport", "delay_minutes", "status"
]

WEATHER_COLUMNS = [
    "airport_iata", "observation_time",
    "metar_time", "metar_flt_cat", "metar_temp_c", "metar_dewp_c", "metar_wdir_deg",
    "metar_wspd_kt", "metar_visib_mi", "metar_altim_hpa", "metar_cover", "metar_cloud_base_ft",
    "wapi_temp_c", "wapi_feelslike_c", "wapi_rh_pct", "wapi_precip_mm", "wapi_pressure_hpa",
    "wapi_cloud_pct", "wapi_vis_km", "wapi_wind_spd_kph", "wapi_wind_dir_deg", "wapi_wind_gust_kph",
    "wapi_cond_text", "wapi_cond_code", "wapi_is_day"
]

def safe_float(v):
    """Safely parse float values, handling None, empty strings, and non-numeric strings."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None

def safe_int(v):
    """Safely parse integer values, handling None, empty strings, and non-numeric strings."""
    if v in (None, ""):
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None

def get_db_connection():
    """Retrieve an active connection to Neon PostgreSQL."""
    db_url = os.environ.get("DATABASE_URL") or DATABASE_URL
    if not db_url:
        return None
    try:
        return psycopg2.connect(db_url)
    except Exception as e:
        print(f"[!] Failed to connect to Neon PostgreSQL: {e}")
        return None

def init_tables(table_name="departures", conn=None):
    """
    Ensure normalized tables (airport_weather, departures, arrivals)
    and SQL views (v_departures, v_arrivals) exist.
    """
    should_close = False
    if conn is None:
        conn = get_db_connection()
        if not conn:
            return False
        should_close = True

    try:
        with conn.cursor() as cur:
            # 1. Create hourly weather table
            cur.execute(CREATE_WEATHER_TABLE_SQL)
            
            # 2. Create departures table and view
            cur.execute(CREATE_FLIGHT_TABLE_SQL.format(table_name="departures"))
            cur.execute(CREATE_VIEW_SQL.format(table_name="departures", table_type="departure"))
            
            # 3. Create arrivals table and view
            cur.execute(CREATE_FLIGHT_TABLE_SQL.format(table_name="arrivals"))
            cur.execute(CREATE_VIEW_SQL.format(table_name="arrivals", table_type="arrival"))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"[!] Error initializing normalized schema: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return False
    finally:
        if should_close and conn:
            conn.close()

def parse_flight_timestamp(date_str, time_str):
    if not date_str or not time_str:
        return None
    d_parts = date_str.strip().split()
    y, m, d = 2026, 11, 18
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

def upsert_weather_records(weather_records, conn=None):
    """
    Insert or update hourly weather observations in the normalized 'airport_weather' table.
    Each airport stores exactly 24 rows per day, saving >90% storage over flight-duplicated weather.
    """
    if not weather_records:
        return 0

    should_close = False
    if conn is None:
        conn = get_db_connection()
        if not conn:
            return 0
        should_close = True

    try:
        tuples = []
        for w in weather_records:
            obs_time = w.get("observation_time")
            if isinstance(obs_time, str):
                try:
                    obs_time = datetime.strptime(obs_time[:16], "%Y-%m-%d %H:%M")
                except Exception:
                    continue
            if not obs_time:
                continue

            t = (
                w.get("airport_iata", "").strip().upper(),
                obs_time,
                w.get("metar_time", ""),
                w.get("metar_flt_cat", ""),
                safe_float(w.get("metar_temp_c")),
                safe_float(w.get("metar_dewp_c")),
                safe_int(w.get("metar_wdir_deg")),
                safe_int(w.get("metar_wspd_kt")),
                w.get("metar_visib_mi", ""),
                safe_int(w.get("metar_altim_hpa")),
                w.get("metar_cover", ""),
                safe_int(w.get("metar_cloud_base_ft")),
                safe_float(w.get("wapi_temp_c")),
                safe_float(w.get("wapi_feelslike_c")),
                safe_int(w.get("wapi_rh_pct")),
                safe_float(w.get("wapi_precip_mm")),
                safe_float(w.get("wapi_pressure_hpa")),
                safe_int(w.get("wapi_cloud_pct")),
                safe_float(w.get("wapi_vis_km")),
                safe_float(w.get("wapi_wind_spd_kph")),
                safe_int(w.get("wapi_wind_dir_deg")),
                safe_float(w.get("wapi_wind_gust_kph")),
                w.get("wapi_cond_text", ""),
                safe_int(w.get("wapi_cond_code")),
                safe_int(w.get("wapi_is_day"))
            )
            tuples.append(t)

        if not tuples:
            return 0

        col_str = ", ".join(WEATHER_COLUMNS)
        update_set_clause = """
            metar_time = EXCLUDED.metar_time,
            metar_flt_cat = EXCLUDED.metar_flt_cat,
            metar_temp_c = EXCLUDED.metar_temp_c,
            metar_dewp_c = EXCLUDED.metar_dewp_c,
            metar_wdir_deg = EXCLUDED.metar_wdir_deg,
            metar_wspd_kt = EXCLUDED.metar_wspd_kt,
            metar_visib_mi = EXCLUDED.metar_visib_mi,
            metar_altim_hpa = EXCLUDED.metar_altim_hpa,
            metar_cover = EXCLUDED.metar_cover,
            metar_cloud_base_ft = EXCLUDED.metar_cloud_base_ft,
            wapi_temp_c = EXCLUDED.wapi_temp_c,
            wapi_feelslike_c = EXCLUDED.wapi_feelslike_c,
            wapi_rh_pct = EXCLUDED.wapi_rh_pct,
            wapi_precip_mm = EXCLUDED.wapi_precip_mm,
            wapi_pressure_hpa = EXCLUDED.wapi_pressure_hpa,
            wapi_cloud_pct = EXCLUDED.wapi_cloud_pct,
            wapi_vis_km = EXCLUDED.wapi_vis_km,
            wapi_wind_spd_kph = EXCLUDED.wapi_wind_spd_kph,
            wapi_wind_dir_deg = EXCLUDED.wapi_wind_dir_deg,
            wapi_wind_gust_kph = EXCLUDED.wapi_wind_gust_kph,
            wapi_cond_text = EXCLUDED.wapi_cond_text,
            wapi_cond_code = EXCLUDED.wapi_cond_code,
            wapi_is_day = EXCLUDED.wapi_is_day
        """

        upsert_query = f"""
        INSERT INTO airport_weather ({col_str}) VALUES %s
        ON CONFLICT (airport_iata, observation_time) DO UPDATE SET
            {update_set_clause};
        """

        with conn.cursor() as cur:
            execute_values(cur, upsert_query, tuples, page_size=2000)
        conn.commit()
        return len(tuples)
    except Exception as e:
        print(f"     [!] Neon DB weather upsert error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        if should_close and conn:
            conn.close()

def upsert_flight_records(table_name, flight_records, conn=None):
    """
    Insert or update flight movements into the lean '{table_name}' table.
    Contains no redundant weather data, maximizing database throughput and minimizing disk usage.
    """
    if not flight_records:
        return 0

    should_close = False
    if conn is None:
        conn = get_db_connection()
        if not conn:
            return 0
        should_close = True

    try:
        tuples = []
        for r in flight_records:
            sched_dt = r.get("scheduled_time")
            if not isinstance(sched_dt, datetime):
                sched_dt = parse_flight_timestamp(r.get("date"), r.get("scheduled"))
            if not sched_dt:
                continue

            delay_min = safe_int(r.get("delay_minutes"))
            if delay_min is None:
                status_str = r.get("status", "")
                if "cancelled" not in status_str.lower():
                    act_m = re.search(r"(\d{1,2}):(\d{2})", status_str)
                    if act_m:
                        act_dt = datetime(sched_dt.year, sched_dt.month, sched_dt.day, int(act_m.group(1)), int(act_m.group(2)))
                        diff = (act_dt - sched_dt).total_seconds()
                        if diff < -43200: act_dt += timedelta(days=1)
                        elif diff > 43200: act_dt -= timedelta(days=1)
                        delay_min = round((act_dt - sched_dt).total_seconds() / 60.0)

            t = (
                r.get("airport_iata", "").strip().upper(),
                sched_dt,
                r.get("flight", "").strip(),
                r.get("airline", "").strip(),
                r.get("route_airport", "").strip(),
                delay_min,
                r.get("status", "").strip()
            )
            tuples.append(t)

        if not tuples:
            return 0

        col_str = ", ".join(FLIGHT_COLUMNS)
        update_set_clause = """
            delay_minutes = EXCLUDED.delay_minutes,
            airline = EXCLUDED.airline,
            route_airport = EXCLUDED.route_airport,
            status = EXCLUDED.status
        """

        upsert_query = f"""
        INSERT INTO {table_name} ({col_str}) VALUES %s
        ON CONFLICT (airport_iata, flight, scheduled_time) DO UPDATE SET
            {update_set_clause};
        """

        with conn.cursor() as cur:
            execute_values(cur, upsert_query, tuples, page_size=2000)
        conn.commit()
        return len(tuples)
    except Exception as e:
        print(f"     [!] Neon DB flight upsert error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        if should_close and conn:
            conn.close()

def upsert_records(table_name, records, conn=None):
    """
    Backward-compatible wrapper:
    Accepts full flight records with embedded weather, routes weather to 'airport_weather',
    and flight data to '{table_name}'.
    """
    if not records:
        return 0

    should_close = False
    if conn is None:
        conn = get_db_connection()
        if not conn:
            return 0
        should_close = True

    try:
        # 1. Upsert flights
        flight_count = upsert_flight_records(table_name, records, conn=conn)

        # 2. Extract unique hourly weather points from records and upsert to airport_weather
        weather_by_hour = {}
        for r in records:
            sched_dt = parse_flight_timestamp(r.get("date"), r.get("scheduled"))
            if not sched_dt:
                continue
            obs_hour = sched_dt.replace(minute=0, second=0, microsecond=0)
            key = (r.get("airport_iata", "").strip().upper(), obs_hour)
            if key not in weather_by_hour and (r.get("wapi_temp_c") or r.get("metar_temp_c")):
                weather_by_hour[key] = {
                    "airport_iata": key[0],
                    "observation_time": obs_hour,
                    "metar_time": r.get("metar_time", ""),
                    "metar_flt_cat": r.get("metar_flt_cat", ""),
                    "metar_temp_c": r.get("metar_temp_c"),
                    "metar_dewp_c": r.get("metar_dewp_c"),
                    "metar_wdir_deg": r.get("metar_wdir_deg"),
                    "metar_wspd_kt": r.get("metar_wspd_kt"),
                    "metar_visib_mi": r.get("metar_visib_mi", ""),
                    "metar_altim_hpa": r.get("metar_altim_hpa"),
                    "metar_cover": r.get("metar_cover", ""),
                    "metar_cloud_base_ft": r.get("metar_cloud_base_ft"),
                    "wapi_temp_c": r.get("wapi_temp_c"),
                    "wapi_feelslike_c": r.get("wapi_feelslike_c"),
                    "wapi_rh_pct": r.get("wapi_rh_pct"),
                    "wapi_precip_mm": r.get("wapi_precip_mm"),
                    "wapi_pressure_hpa": r.get("wapi_pressure_hpa"),
                    "wapi_cloud_pct": r.get("wapi_cloud_pct"),
                    "wapi_vis_km": r.get("wapi_vis_km"),
                    "wapi_wind_spd_kph": r.get("wapi_wind_spd_kph"),
                    "wapi_wind_dir_deg": r.get("wapi_wind_dir_deg"),
                    "wapi_wind_gust_kph": r.get("wapi_wind_gust_kph"),
                    "wapi_cond_text": r.get("wapi_cond_text", ""),
                    "wapi_cond_code": r.get("wapi_cond_code"),
                    "wapi_is_day": r.get("wapi_is_day"),
                }

        if weather_by_hour:
            upsert_weather_records(list(weather_by_hour.values()), conn=conn)

        return flight_count
    finally:
        if should_close and conn:
            conn.close()
