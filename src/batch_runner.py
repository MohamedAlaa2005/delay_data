import argparse
import csv
import os
import re
import sys
from datetime import datetime, timedelta
from camoufox.sync_api import Camoufox

from config.settings import (
    AIRPORTS_FILE, WEATHERAPI_KEY, BATCHES_COUNT
)
from src.scraper import scrape_airport_board
from src.weather import (
    fetch_aviation_metar, find_prior_metar,
    fetch_weatherapi_history, find_prior_weatherapi
)
from src.db import (
    upsert_records, init_tables, get_db_connection,
    parse_flight_timestamp
)

def load_all_airports():
    if not AIRPORTS_FILE.exists():
        raise FileNotFoundError(f"Airports file not found: {AIRPORTS_FILE}")
    with open(AIRPORTS_FILE, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def get_airports_for_batch(batch_number):
    airports = load_all_airports()
    total = len(airports)
    # Split 150 airports into 3 batches: [0..50), [50..100), [100..150)
    chunk_size = (total + BATCHES_COUNT - 1) // BATCHES_COUNT
    start_idx = (batch_number - 1) * chunk_size
    end_idx = min(start_idx + chunk_size, total)
    return airports[start_idx:end_idx]

def enrich_flight_records(records, airport):
    if not records:
        return []

    icao = airport.get("icao_code", "")
    iata = airport.get("iata_code", "")
    apt_tz = airport.get("timezone", "UTC")

    metar_data = fetch_aviation_metar(icao, hours=72)

    # First pass: parse scheduled GMT time for all records and collect target UTC dates for WeatherAPI
    parsed_flights = []
    iso_dates = set()
    for r in records:
        sched_gmt = parse_flight_timestamp(r.get("date"), r.get("scheduled"), apt_tz)
        if sched_gmt:
            iso_dates.add(sched_gmt.strftime("%Y-%m-%d"))
        parsed_flights.append((r, sched_gmt))

    wapi_data = fetch_weatherapi_history(WEATHERAPI_KEY, iata, iso_dates) if (WEATHERAPI_KEY and iso_dates) else []

    enriched = []
    for r, sched_gmt in parsed_flights:
        if not sched_gmt:
            sched_gmt = parse_flight_timestamp(r.get("date"), "12:00", apt_tz) or datetime(2026, 11, 18, 12, 0)

        delay_minutes = ""
        is_canc = "cancelled" in r.get("status", "").lower()
        if not is_canc:
            act_m = re.search(r"(\d{1,2}):(\d{2})", r.get("status", ""))
            if act_m:
                act_gmt = parse_flight_timestamp(r.get("date"), r.get("status"), apt_tz)
                if act_gmt:
                    diff = (act_gmt - sched_gmt).total_seconds()
                    if diff < -43200: act_gmt += timedelta(days=1)
                    elif diff > 43200: act_gmt -= timedelta(days=1)
                    delay_minutes = round((act_gmt - sched_gmt).total_seconds() / 60.0)

        # Weather observation matching strictly prior to scheduled GMT time
        prior_metar = find_prior_metar(metar_data, sched_gmt)
        prior_wapi = find_prior_weatherapi(wapi_data, sched_gmt)

        cloud_base = ""
        if prior_metar and prior_metar.get("clouds"):
            base = prior_metar["clouds"][0].get("base")
            cloud_base = base if base is not None else ""

        row = {
            "airport_iata": r["airport_iata"],
            "airport_icao": r["airport_icao"],
            "country": r["country"],
            "timezone": apt_tz,
            "scheduled_time": sched_gmt,
            "date": r["date"],
            "scheduled": r["scheduled"],
            "flight": r["flight"],
            "airline": r["airline"],
            "route_airport": r["route_airport"],
            "type": r["type"],
            "status": r["status"],
            "delay_minutes": delay_minutes,
            # METAR
            "metar_time": prior_metar.get("reportTime", "") if prior_metar else "",
            "metar_flt_cat": prior_metar.get("fltCat", "") if prior_metar else "",
            "metar_temp_c": prior_metar.get("temp", "") if prior_metar else "",
            "metar_dewp_c": prior_metar.get("dewp", "") if prior_metar else "",
            "metar_wdir_deg": prior_metar.get("wdir", "") if prior_metar else "",
            "metar_wspd_kt": prior_metar.get("wspd", "") if prior_metar else "",
            "metar_visib_mi": prior_metar.get("visib", "") if prior_metar else "",
            "metar_altim_hpa": prior_metar.get("altim", "") if prior_metar else "",
            "metar_cover": prior_metar.get("cover", "") if prior_metar else "",
            "metar_cloud_base_ft": cloud_base,
            # Surface Weather (WeatherAPI) - initialized with empty string
            "wapi_temp_c": "",
            "wapi_feelslike_c": "",
            "wapi_rh_pct": "",
            "wapi_precip_mm": "",
            "wapi_pressure_hpa": "",
            "wapi_cloud_pct": "",
            "wapi_vis_km": "",
            "wapi_wind_spd_kph": "",
            "wapi_wind_dir_deg": "",
            "wapi_wind_gust_kph": "",
            "wapi_cond_text": "",
            "wapi_cond_code": "",
            "wapi_is_day": "",
        }
        if prior_wapi:
            row.update(prior_wapi)
        enriched.append(row)

    return enriched

def run_batch(batch_num, direction, headless=True):
    print("=" * 70)
    print(f" EXECUTING BATCH {batch_num}/3 | DIRECTION: {direction.upper()}")
    print("=" * 70)

    airports = get_airports_for_batch(batch_num)
    print(f"Airports in this batch ({len(airports)}): {[a['iata_code'] for a in airports]}")

    table_name = "departures" if direction == "departures" else "arrivals"
    
    # Initialize DB connection and tables once for high-performance batching
    db_conn = get_db_connection()
    if db_conn:
        print(f"[✓] Connected to Neon PostgreSQL. Ensuring '{table_name}' table schema is ready...")
        init_tables(table_name, conn=db_conn)

    all_batch_records = []
    total_upserted = 0

    try:
        print(f"Launching Camoufox (Stealth Firefox, headless={headless})...")
        with Camoufox(
            headless=headless,
            canvas_noise=True,
            humanize=True,
            i_know_what_im_doing=True
        ) as browser:
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="en-US"
            )

            for idx, apt in enumerate(airports, 1):
                iata = apt["iata_code"]
                print(f"\n[{idx}/{len(airports)}] Processing {iata} ({apt['airport_name']})...")
                page = None
                try:
                    page = context.new_page()
                    raw_records = scrape_airport_board(page, apt, direction=direction)
                    if raw_records:
                        enriched = enrich_flight_records(raw_records, apt)
                        all_batch_records.extend(enriched)
                        
                        # High-performance immediate SQL batch upsert per airport
                        if db_conn:
                            count = upsert_records(table_name, enriched, conn=db_conn)
                            total_upserted += count
                except Exception as e:
                    print(f"     [!] Error processing {iata}: {e}")
                finally:
                    if page:
                        try: page.close()
                        except Exception: pass

            browser.close()
    finally:
        if db_conn:
            try: db_conn.close()
            except Exception: pass

    print(f"\n[✓] Batch {batch_num} {direction} completed: {len(all_batch_records)} flights collected, {total_upserted} records synced to Neon '{table_name}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run 1 of the 6 Flight Delay Scraper Batches")
    parser.add_argument("--batch", type=int, required=True, choices=[1, 2, 3], help="Batch number (1, 2, or 3)")
    parser.add_argument("--direction", type=str, required=True, choices=["departures", "arrivals"], help="departures or arrivals")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")
    args = parser.parse_args()

    run_batch(args.batch, args.direction, headless=args.headless)

