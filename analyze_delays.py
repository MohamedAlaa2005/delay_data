import argparse
from collections import defaultdict
import psycopg2
from psycopg2.extras import RealDictCursor
from config.settings import DATABASE_URL
from src.db import get_db_connection

def load_table_from_db(conn, table_name, country_filter=None):
    """Fetch flight records directly from Neon PostgreSQL database."""
    query = f"""
    SELECT 
        airport_iata, scheduled_time, flight, airline, route_airport, 
        delay_minutes, metar_time, metar_flt_cat, metar_temp_c, metar_dewp_c,
        metar_wdir_deg, metar_wspd_kt, metar_visib_mi, metar_altim_hpa,
        metar_cover, metar_cloud_base_ft, wapi_temp_c, wapi_feelslike_c,
        wapi_rh_pct, wapi_precip_mm, wapi_pressure_hpa, wapi_cloud_pct,
        wapi_vis_km, wapi_wind_spd_kph, wapi_wind_dir_deg, wapi_wind_gust_kph,
        wapi_cond_text, wapi_cond_code, wapi_is_day, '{table_name[:-1]}' AS type
    FROM {table_name}
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query)
        rows = cur.fetchall()
    return rows

def analyze(country_filter=None):
    conn = get_db_connection()
    if not conn:
        print("[!] Could not connect to Neon PostgreSQL database. Check DATABASE_URL.")
        return

    try:
        dep_rows = load_table_from_db(conn, "departures")
        arr_rows = load_table_from_db(conn, "arrivals")
    finally:
        conn.close()

    all_rows = dep_rows + arr_rows

    if not all_rows:
        print(f"[!] No flight records found in Neon database.")
        return

    print("=" * 70)
    print(f" NEON DATABASE FLIGHT DELAYS & WEATHER INTELLIGENCE REPORT")
    print("=" * 70)

    total_dep = len(dep_rows)
    total_arr = len(arr_rows)
    total_all = len(all_rows)

    # 1. Overall delay performance
    valid_delays = []
    delayed_15_count = 0
    delayed_45_count = 0
    cancelled_count = 0
    early_count = 0

    airport_delays = defaultdict(list)
    airport_counts = defaultdict(int)
    airline_delays = defaultdict(list)
    flt_cat_delays = defaultdict(list)
    weather_cond_delays = defaultdict(list)

    for r in all_rows:
        apt = r.get("airport_iata", "UNK")
        airport_counts[apt] += 1

        airline = (r.get("airline") or "Unknown").strip()
        delay_val = r.get("delay_minutes")

        if delay_val is None:
            cancelled_count += 1
            continue

        try:
            d = int(delay_val)
            valid_delays.append(d)
            airport_delays[apt].append(d)
            if airline:
                airline_delays[airline].append(d)

            if d >= 15:
                delayed_15_count += 1
            if d >= 45:
                delayed_45_count += 1
            if d < 0:
                early_count += 1

            cat = (r.get("metar_flt_cat") or "").strip().upper()
            if cat in ["VFR", "MVFR", "IFR", "LIFR"]:
                flt_cat_delays[cat].append(d)

            cond = (r.get("wapi_cond_text") or "").strip()
            if cond:
                weather_cond_delays[cond].append(d)
        except (ValueError, TypeError):
            continue

    n_valid = len(valid_delays)
    avg_delay = sum(valid_delays) / n_valid if n_valid else 0.0
    pct_15 = (delayed_15_count / n_valid * 100) if n_valid else 0.0
    pct_45 = (delayed_45_count / n_valid * 100) if n_valid else 0.0
    pct_early = (early_count / n_valid * 100) if n_valid else 0.0

    print(f"\n1. SUMMARY METRICS (Source: Neon PostgreSQL)")
    print(f"  Total Flights in Neon:      {total_all:,} (Departures: {total_dep:,} | Arrivals: {total_arr:,})")
    print(f"  Distinct Airports Monitored: {len(airport_counts)}")
    print(f"  Valid Completed Flights:    {n_valid:,}")
    print(f"  Average Flight Delay:       {avg_delay:+6.1f} minutes")
    print(f"  Flights Delayed >= 15 min:  {delayed_15_count:,} ({pct_15:5.1f}%)")
    print(f"  Flights Delayed >= 45 min:  {delayed_45_count:,} ({pct_45:5.1f}%)")
    print(f"  Flights Arrived Early (<0m):{early_count:,} ({pct_early:5.1f}%)")
    print(f"  Cancelled Flights (NULL):   {cancelled_count:,}")

    # 2. Airport Performance
    print(f"\n2. TOP AIRPORTS BY FLIGHT VOLUME & PERFORMANCE")
    print(f"  {'IATA':<6} {'Flights':<9} {'Avg Delay':<12} {'% Delayed (>=15m)':<20} {'Max Delay'}")
    print("  " + "-" * 65)

    sorted_airports = sorted(airport_counts.keys(), key=lambda a: airport_counts[a], reverse=True)
    for apt in sorted_airports[:15]:
        delays = airport_delays[apt]
        cnt = len(delays)
        if not cnt: continue
        avg_d = sum(delays) / cnt
        pct_d = sum(1 for d in delays if d >= 15) / cnt * 100
        max_d = max(delays)
        print(f"  {apt:<6} {cnt:<9} {avg_d:+6.1f} min   {pct_d:5.1f}%             {max_d:+.0f} min")

    # 3. Top Airlines Delay Performance
    print(f"\n3. TOP AIRLINES BY DELAY SEVERITY (min 15 flights)")
    print(f"  {'Airline':<32} {'Flights':<9} {'Avg Delay':<12} {'% Delayed (>=15m)'}")
    print("  " + "-" * 65)
    
    qualifying_airlines = [al for al in airline_delays if len(airline_delays[al]) >= 15]
    sorted_airlines = sorted(
        qualifying_airlines,
        key=lambda al: (sum(airline_delays[al]) / len(airline_delays[al])),
        reverse=True
    )
    for al in sorted_airlines[:10]:
        delays = airline_delays[al]
        cnt = len(delays)
        avg_d = sum(delays) / cnt
        pct_d = sum(1 for d in delays if d >= 15) / cnt * 100
        print(f"  {al[:30]:<32} {cnt:<9} {avg_d:+6.1f} min   {pct_d:5.1f}%")

    # 4. Weather Impact Analysis
    print(f"\n4. AVIATION FLIGHT CATEGORY (METAR) VS DELAY")
    print(f"  {'Flight Category':<20} {'Flights':<9} {'Avg Delay':<12} {'% Delayed (>=15m)'}")
    print("  " + "-" * 55)
    for cat in ["VFR", "MVFR", "IFR", "LIFR"]:
        if cat in flt_cat_delays and flt_cat_delays[cat]:
            delays = flt_cat_delays[cat]
            cnt = len(delays)
            avg_d = sum(delays) / cnt
            pct_d = sum(1 for d in delays if d >= 15) / cnt * 100
            print(f"  {cat:<20} {cnt:<9} {avg_d:+6.1f} min   {pct_d:5.1f}%")

    print(f"\n5. WEATHER CONDITIONS (WeatherAPI) VS DELAY")
    print(f"  {'Weather Condition':<25} {'Flights':<9} {'Avg Delay':<12} {'% Delayed (>=15m)'}")
    print("  " + "-" * 60)
    sorted_conds = sorted(
        weather_cond_delays.keys(),
        key=lambda c: len(weather_cond_delays[c]),
        reverse=True
    )
    for cond in sorted_conds[:6]:
        delays = weather_cond_delays[cond]
        cnt = len(delays)
        avg_d = sum(delays) / cnt
        pct_d = sum(1 for d in delays if d >= 15) / cnt * 100
        print(f"  {cond[:23]:<25} {cnt:<9} {avg_d:+6.1f} min   {pct_d:5.1f}%")

    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()
    analyze()
