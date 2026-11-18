import os
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo
import psycopg2
from psycopg2.extras import execute_values
from config.settings import DATABASE_URL

TIMEZONE_ABBR_MAP = {
    "GMT": "UTC", "UTC": "UTC", "Z": "UTC",
    "WET": "UTC", "WEST": "UTC+1",
    "CET": "Europe/Paris", "CEST": "Europe/Paris",
    "EET": "Europe/Athens", "EEST": "Europe/Athens",
    "MSK": "Europe/Moscow",
    "AST": "Asia/Riyadh", "GST": "Asia/Dubai",
    "IST": "Asia/Kolkata",
    "ICT": "Asia/Bangkok", "WIB": "Asia/Jakarta", "WITA": "Asia/Makassar", "WIT": "Asia/Jayapura",
    "SGT": "Asia/Singapore", "MYT": "Asia/Kuala_Lumpur", "HKT": "Asia/Hong_Kong",
    "CST": "Asia/Shanghai", "KST": "Asia/Seoul", "JST": "Asia/Tokyo",
    "AEST": "Australia/Sydney", "AEDT": "Australia/Sydney",
    "ACST": "Australia/Adelaide", "ACDT": "Australia/Adelaide",
    "AWST": "Australia/Perth",
    "NZST": "Pacific/Auckland", "NZDT": "Pacific/Auckland",
    "EST": "America/New_York", "EDT": "America/New_York",
    "CDT": "America/Chicago",
    "MST": "America/Denver", "MDT": "America/Denver",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "AKST": "America/Anchorage", "AKDT": "America/Anchorage",
    "HST": "Pacific/Honolulu",
    "CAT": "Africa/Harare", "EAT": "Africa/Nairobi", "WAT": "Africa/Lagos",
    "BRT": "America/Sao_Paulo", "ART": "America/Argentina/Buenos_Aires", "CLT": "America/Santiago",
    "COT": "America/Bogota", "PET": "America/Lima"
}

MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12
}

def parse_date_components(date_str):
    """Safely extracts (year, month, day) from flight date strings."""
    if not date_str:
        return 2026, 11, 18
    m_iso = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", str(date_str))
    if m_iso:
        return int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
    clean_str = re.sub(r"[,\.]", " ", str(date_str)).strip()
    parts = clean_str.split()
    y, m, d = 2026, 11, 18
    for p in parts:
        p_lower = p.lower()
        if p_lower in MONTH_MAP:
            m = MONTH_MAP[p_lower]
        elif p.isdigit():
            val = int(p)
            if val > 1900:
                y = val
            elif 1 <= val <= 31:
                d = val
    return y, m, d

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
CREATE UNIQUE INDEX IF NOT EXISTS uniq_{table_name}_flight_time ON {table_name}(airport_iata, flight, scheduled_time);
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

def safe_float(v):
    """Safely parse float values, handling None, empty strings, and non-numeric strings (e.g. 'VRB')."""
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None

def safe_int(v):
    """Safely parse integer values, handling None, empty strings, and non-numeric strings (e.g. 'VRB', 'CALM')."""
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

def init_tables(table_name, conn=None):
    """Ensure table and unique indexes exist once before batch processing."""
    should_close = False
    if conn is None:
        conn = get_db_connection()
        if not conn:
            return False
        should_close = True

    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL.format(table_name=table_name))
        conn.commit()
        return True
    except Exception as e:
        print(f"[!] Error initializing table '{table_name}': {e}")
        return False
    finally:
        if should_close and conn:
            conn.close()

def parse_flight_timestamp(date_str, time_str, airport_tz="UTC"):
    """
    Parses a flight date and time string into a consistent GMT (UTC) datetime.
    Detects timezone abbreviations in the string or falls back to airport_tz.
    Returns naive UTC datetime matching database TIMESTAMP column.
    """
    if not date_str or not time_str:
        return None
    y, m, d = parse_date_components(date_str)

    t_match = re.search(r"(\d{1,2}):(\d{2})", str(time_str))
    if not t_match:
        return None
    sh, sm = int(t_match.group(1)), int(t_match.group(2))

    # Determine timezone: search tokens for known abbreviation, else fallback to airport_tz
    tokens = re.findall(r"[A-Za-z]+", str(time_str))
    tz_resolved = airport_tz or "UTC"
    for tok in reversed(tokens):
        tok_upper = tok.upper()
        if tok_upper in TIMEZONE_ABBR_MAP:
            tz_resolved = TIMEZONE_ABBR_MAP[tok_upper]
            break

    try:
        zi = ZoneInfo(tz_resolved)
    except Exception:
        zi = ZoneInfo("UTC")

    try:
        dt_local = datetime(y, m, d, sh, sm, tzinfo=zi)
        dt_gmt = dt_local.astimezone(dt_timezone.utc)
        return dt_gmt.replace(tzinfo=None)
    except Exception:
        return datetime(y, m, d, sh, sm)

def upsert_records(table_name, records, conn=None):
    """
    Optimized SQL Batch Upsert:
    Inserts a list of records in a single parameterized multi-row transaction using execute_values.
    Updates existing flights on conflict without generating duplicates.
    """
    if not records:
        return 0

    should_close = False
    if conn is None:
        conn = get_db_connection()
        if not conn:
            print("[!] DATABASE_URL not available. Skipping database upsert.")
            return 0
        should_close = True

    try:
        tuples = []
        for r in records:
            sched_dt = r.get("scheduled_gmt") or r.get("scheduled_time")
            if not isinstance(sched_dt, datetime):
                sched_dt = parse_flight_timestamp(r.get("date"), r.get("scheduled"), r.get("timezone", "UTC"))
            if not sched_dt:
                continue

            t = (
                r.get("airport_iata", "").strip().upper(),
                sched_dt,
                r.get("flight", "").strip(),
                r.get("airline", "").strip(),
                r.get("route_airport", "").strip(),
                safe_int(r.get("delay_minutes")),
                r.get("metar_time", ""),
                r.get("metar_flt_cat", ""),
                safe_float(r.get("metar_temp_c")),
                safe_float(r.get("metar_dewp_c")),
                safe_int(r.get("metar_wdir_deg")),
                safe_int(r.get("metar_wspd_kt")),
                r.get("metar_visib_mi", ""),
                safe_int(r.get("metar_altim_hpa")),
                r.get("metar_cover", ""),
                safe_int(r.get("metar_cloud_base_ft")),
                safe_float(r.get("wapi_temp_c")),
                safe_float(r.get("wapi_feelslike_c")),
                safe_int(r.get("wapi_rh_pct")),
                safe_float(r.get("wapi_precip_mm")),
                safe_float(r.get("wapi_pressure_hpa")),
                safe_int(r.get("wapi_cloud_pct")),
                safe_float(r.get("wapi_vis_km")),
                safe_float(r.get("wapi_wind_spd_kph")),
                safe_int(r.get("wapi_wind_dir_deg")),
                safe_float(r.get("wapi_wind_gust_kph")),
                r.get("wapi_cond_text", ""),
                safe_int(r.get("wapi_cond_code")),
                safe_int(r.get("wapi_is_day"))
            )
            tuples.append(t)

        if not tuples:
            return 0

        col_str = ", ".join(COLUMNS)
        update_set_clause = """
            delay_minutes = EXCLUDED.delay_minutes,
            airline = EXCLUDED.airline,
            route_airport = EXCLUDED.route_airport,
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
        INSERT INTO {table_name} ({col_str}) VALUES %s
        ON CONFLICT (airport_iata, flight, scheduled_time) DO UPDATE SET
            {update_set_clause};
        """

        with conn.cursor() as cur:
            execute_values(cur, upsert_query, tuples, page_size=2000)
        conn.commit()
        print(f"     [Neon DB] Upserted batch of {len(tuples)} records into '{table_name}'.")
        return len(tuples)
    except Exception as e:
        print(f"     [!] Neon DB upsert error: {e}")
        try:
            conn.rollback()
        except Exception:
            pass
        return 0
    finally:
        if should_close and conn:
            conn.close()
