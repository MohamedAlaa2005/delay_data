import argparse
import sys
from src.batch_runner import run_batch
from analyze_delays import analyze

def main():
    parser = argparse.ArgumentParser(
        description="Aviation Flight Delays & Weather Pipeline CLI (Database-Driven)",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--action",
        type=str,
        choices=["batch", "analyze", "all"],
        default="analyze",
        help="Action to perform:\n"
             "  analyze: Run delay & weather intelligence report directly from Neon PostgreSQL\n"
             "  batch:   Run a specific batch (requires --batch and --direction)\n"
             "  all:     Run all 6 batches sequentially"
    )
    parser.add_argument("--batch", type=int, choices=[1, 2, 3], help="Batch number (1, 2, or 3)")
    parser.add_argument("--direction", type=str, choices=["departures", "arrivals"], help="Flight direction")
    parser.add_argument("--headless", action="store_true", default=False, help="Run browser in headless mode")

    args = parser.parse_args()

    if args.action == "analyze":
        analyze()
    elif args.action == "batch":
        if not args.batch or not args.direction:
            print("[!] Both --batch and --direction are required for action 'batch'.")
            sys.exit(1)
        run_batch(args.batch, args.direction, headless=args.headless)
    elif args.action == "all":
        print("Running all 6 batches sequentially (streaming directly to Neon PostgreSQL)...")
        for direction in ["departures", "arrivals"]:
            for b in [1, 2, 3]:
                run_batch(b, direction, headless=args.headless)

if __name__ == "__main__":
    main()
