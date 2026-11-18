import argparse
import csv
import sys
from datetime import datetime
from config.settings import AIRPORTS_FILE, WEATHERAPI_KEY, BATCHES_COUNT
from src.weather import build_hourly_weather_records, LONDON_TZ
from src.db import init_tables, get_db_connection, upsert_weather_records

def load_airports(batch=None):
    if not AIRPORTS_FILE.exists():
        raise FileNotFoundError(f"Airports file not found: {AIRPORTS_FILE}")
    with open(AIRPORTS_FILE, "r", encoding="utf-8-sig") as f:
        airports = list(csv.DictReader(f))
    
    if batch is not None:
        chunk_size = (len(airports) + BATCHES_COUNT - 1) // BATCHES_COUNT
        start_idx = (batch - 1) * chunk_size
        end_idx = min(start_idx + chunk_size, len(airports))
        return airports[start_idx:end_idx]
    return airports

def run_weather_pipeline(batch=None, target_date=None):
    """
    Dedicated weather ingestion runner.
    Fetches exactly 24 hourly observations per day per airport in London Time (Europe/London),
    and upserts into 'airport_weather'.
    """
    airports = load_airports(batch)
    batch_label = f"BATCH {batch} ({len(airports)} airports)" if batch else f"ALL {len(airports)} AIRPORTS"
    
    if not target_date:
        target_date = datetime.now(LONDON_TZ).strftime("%Y-%m-%d")
    date_set = {target_date}

    print("=" * 70)
    print(f" DEDICATED HOURLY WEATHER RUNNER | {batch_label}")
    print(f" Target Date (London Time): {target_date} | London TZ: Europe/London")
    print("=" * 70)

    db_conn = get_db_connection()
    if not db_conn:
        print("[!] Error: Could not connect to Neon PostgreSQL database.")
        sys.exit(1)

    init_tables(conn=db_conn)
    total_upserted = 0

    try:
        for idx, apt in enumerate(airports, 1):
            iata = apt.get("iata_code", "").strip().upper()
            icao = apt.get("icao_code", "").strip().upper()
            name = apt.get("airport_name", "")

            print(f"[{idx}/{len(airports)}] Ingesting 24h weather for {iata} ({icao} - {name})...", end=" ")
            try:
                records = build_hourly_weather_records(iata, icao, date_set, WEATHERAPI_KEY)
                if records:
                    count = upsert_weather_records(records, conn=db_conn)
                    total_upserted += count
                    print(f"[✓] {count} hours upserted.")
                else:
                    print("[!] No records fetched.")
            except Exception as e:
                print(f"[!] Error: {e}")
    finally:
        db_conn.close()

    print("=" * 70)
    print(f"[✓] Weather sync finished: {total_upserted} hourly records saved to 'airport_weather'.")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dedicated 24-Hour Weather Pipeline (London Time)")
    parser.add_argument("--batch", type=int, choices=[1, 2, 3], default=None, help="Optional batch (1, 2, or 3). Default is all 150 airports.")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD in London time (default: today)")
    args = parser.parse_args()

    run_weather_pipeline(batch=args.batch, target_date=args.date)
