import argparse
import csv
import sys
from config.settings import DEPARTURES_FILE, ARRIVALS_FILE
from src.batch_runner import run_batch
from src.db import upsert_records, init_tables, get_db_connection
from analyze_delays import analyze

def sync_csv_to_neon():
    """Sync local CSV records into Neon PostgreSQL database."""
    print("Syncing local CSV files into Neon PostgreSQL...")
    conn = get_db_connection()
    if not conn:
        print("[!] Could not connect to Neon. Check DATABASE_URL.")
        return
    try:
        init_tables("departures", conn)
        init_tables("arrivals", conn)

        dep_count = 0
        if DEPARTURES_FILE.exists():
            with open(DEPARTURES_FILE, "r", encoding="utf-8-sig") as f:
                dep_records = list(csv.DictReader(f))
            dep_count = upsert_records("departures", dep_records, conn=conn)

        arr_count = 0
        if ARRIVALS_FILE.exists():
            with open(ARRIVALS_FILE, "r", encoding="utf-8-sig") as f:
                arr_records = list(csv.DictReader(f))
            arr_count = upsert_records("arrivals", arr_records, conn=conn)

        print(f"[✓] Successfully synced {dep_count:,} departures and {arr_count:,} arrivals into Neon!")
    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(
        description="Aviation Flight Delays & Weather Pipeline CLI",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--action",
        type=str,
        choices=["batch", "analyze", "all", "sync"],
        default="analyze",
        help="Action to perform:\n"
             "  batch:   Run a specific batch (requires --batch and --direction)\n"
             "  analyze: Run delay intelligence report\n"
             "  all:     Run all 6 batches sequentially\n"
             "  sync:    Sync local CSV flight files to Neon database"
    )
    parser.add_argument("--batch", type=int, choices=[1, 2, 3], help="Batch number (1, 2, or 3)")
    parser.add_argument("--direction", type=str, choices=["departures", "arrivals"], help="Flight direction")
    parser.add_argument("--country", type=str, default=None, help="Filter analysis by country")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")

    args = parser.parse_args()

    if args.action == "analyze":
        analyze(country_filter=args.country)
    elif args.action == "batch":
        if not args.batch or not args.direction:
            print("[!] Both --batch and --direction are required for action 'batch'.")
            sys.exit(1)
        run_batch(args.batch, args.direction, headless=args.headless)
    elif args.action == "sync":
        sync_csv_to_neon()
    elif args.action == "all":
        print("Running all 6 batches sequentially...")
        for direction in ["departures", "arrivals"]:
            for b in [1, 2, 3]:
                run_batch(b, direction, headless=args.headless)

if __name__ == "__main__":
    main()

