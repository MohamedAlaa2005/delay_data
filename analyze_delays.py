import argparse
import csv
import os
from collections import defaultdict

DEP_FILE = "departures_with_weather.csv"
ARR_FILE = "arrivals_with_weather.csv"

def load_rows(filepath):
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def analyze(country_filter=None):
    dep_rows = load_rows(DEP_FILE)
    arr_rows = load_rows(ARR_FILE)

    if country_filter:
        c_clean = country_filter.strip().lower()
        dep_rows = [r for r in dep_rows if c_clean in r.get("country", "").lower()]
        arr_rows = [r for r in arr_rows if c_clean in r.get("country", "").lower()]

    all_rows = dep_rows + arr_rows

    if not all_rows:
        print(f"[!] No flight data found{f' for country: {country_filter}' if country_filter else ''}.")
        return

    title_suffix = f" FOR [{country_filter.upper()}]" if country_filter else " ACROSS AIRPORTS"
    print("=" * 70)
    print(f" FLIGHT DELAYS & WEATHER INTELLIGENCE REPORT{title_suffix}")
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
    airport_countries = {}
    airline_delays = defaultdict(list)
    flt_cat_delays = defaultdict(list)
    weather_cond_delays = defaultdict(list)

    for r in all_rows:
        apt = r.get("airport_iata", "UNK")
        country = r.get("country", "")
        airport_countries[apt] = country
        airport_counts[apt] += 1

        airline = r.get("airline", "Unknown").strip()
        status = r.get("status", "").lower()
        flt_cat = r.get("metar_flt_cat", "").strip() or "VFR"
        cond = r.get("wapi_cond_text", "").strip() or "Clear"

        if "cancelled" in status:
            cancelled_count += 1
            continue

        d_str = r.get("delay_minutes", "")
        try:
            d_min = float(d_str)
            valid_delays.append(d_min)
            airport_delays[apt].append(d_min)
            if airline:
                airline_delays[airline].append(d_min)
            flt_cat_delays[flt_cat].append(d_min)
            weather_cond_delays[cond].append(d_min)

            if d_min >= 15:
                delayed_15_count += 1
            if d_min >= 45:
                delayed_45_count += 1
            if d_min < 0:
                early_count += 1
        except (ValueError, TypeError):
            pass

    n_valid = len(valid_delays)
    avg_delay = sum(valid_delays) / n_valid if n_valid else 0
    sorted_delays = sorted(valid_delays)
    median_delay = sorted_delays[n_valid // 2] if n_valid else 0

    pct_delayed_15 = (delayed_15_count / n_valid * 100) if n_valid else 0
    pct_delayed_45 = (delayed_45_count / n_valid * 100) if n_valid else 0
    pct_cancelled = (cancelled_count / total_all * 100) if total_all else 0
    pct_early = (early_count / n_valid * 100) if n_valid else 0

    print(f"\n1. DATASET OVERVIEW")
    print(f"  Total Flights Recorded : {total_all:,} ({total_dep:,} Departures, {total_arr:,} Arrivals)")
    print(f"  Distinct Airports      : {len(airport_counts)} across {len(set(airport_countries.values()))} countries")
    print(f"  Cancelled Flights      : {cancelled_count} ({pct_cancelled:.1f}%)")
    print(f"  Flights Evaluated      : {n_valid:,}")
    print(f"  Average Flight Delay   : {avg_delay:+.1f} minutes")
    print(f"  Median Flight Delay    : {median_delay:+.1f} minutes")
    print(f"  Departed / Landed Early: {early_count:,} ({pct_early:.1f}%)")
    print(f"  Delayed >= 15 min      : {delayed_15_count:,} ({pct_delayed_15:.1f}%) [Standard Aviation Metric]")
    print(f"  Severe Delay (>= 45m)  : {delayed_45_count:,} ({pct_delayed_45:.1f}%)")

    # 2. Airport Delay Rankings
    print(f"\n2. AIRPORT FLIGHT DELAY BENCHMARK")
    print(f"  {'IATA':<6} {'Country':<18} {'Flights':<9} {'Avg Delay':<12} {'% Delayed (>=15m)':<18} {'Max Delay'}")
    print("  " + "-" * 75)
    
    sorted_airports = sorted(
        airport_delays.keys(),
        key=lambda a: (sum(airport_delays[a]) / len(airport_delays[a]) if airport_delays[a] else 0),
        reverse=True
    )

    for apt in sorted_airports:
        delays = airport_delays[apt]
        cnt = len(delays)
        if not cnt: continue
        avg_d = sum(delays) / cnt
        pct_d = sum(1 for d in delays if d >= 15) / cnt * 100
        max_d = max(delays)
        c_name = airport_countries.get(apt, "")[:16]
        print(f"  {apt:<6} {c_name:<18} {cnt:<9} {avg_d:+6.1f} min   {pct_d:5.1f}%             {max_d:+.0f} min")

    # 3. Top Airlines Delay Performance
    print(f"\n3. TOP AIRLINES BY DELAY SEVERITY (min 10 flights)")
    print(f"  {'Airline':<32} {'Flights':<9} {'Avg Delay':<12} {'% Delayed (>=15m)'}")
    print("  " + "-" * 65)
    
    qualifying_airlines = [al for al in airline_delays if len(airline_delays[al]) >= 10]
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
    parser.add_argument("--country", type=str, default=None, help="Filter results by country (e.g. 'Australia' or 'Belgium')")
    args = parser.parse_args()
    analyze(country_filter=args.country)

