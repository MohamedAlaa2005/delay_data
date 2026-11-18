import csv
import io
import os
import urllib.request
from collections import defaultdict
from pathlib import Path

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"
COUNTRIES_URL = "https://davidmegginson.github.io/ourairports-data/countries.csv"
OPENFLIGHTS_AIRPORTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
OPENFLIGHTS_ROUTES_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat"

def generate_airport_sample(target_total=150, max_per_country=2):
    print("=" * 70)
    print(f" GENERATING TOP {target_total} INTERNATIONAL AIRPORTS (MAX {max_per_country} PER COUNTRY)")
    print("=" * 70)

    # 1. Fetch OurAirports Country Names
    print("\n[1/5] Downloading country reference data from OurAirports...")
    req = urllib.request.Request(COUNTRIES_URL, headers={"User-Agent": "AviationSampling/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        countries_txt = resp.read().decode("utf-8", errors="ignore")
    
    country_name_map = {}
    for r in csv.DictReader(io.StringIO(countries_txt)):
        code = r.get("code", "").strip().upper()
        name = r.get("name", "").strip()
        if code:
            country_name_map[code] = name

    # 2. Fetch OurAirports master airport records
    print("[2/5] Downloading global airport details from OurAirports...")
    req = urllib.request.Request(OURAIRPORTS_URL, headers={"User-Agent": "AviationSampling/1.0"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        airports_txt = resp.read().decode("utf-8", errors="ignore")

    ourairports_map = {}
    for r in csv.DictReader(io.StringIO(airports_txt)):
        iata = r.get("iata_code", "").strip().upper()
        if len(iata) == 3 and iata.isalpha():
            ourairports_map[iata] = r

    # 3. Fetch OpenFlights airports to map IATA -> Country
    print("[3/5] Downloading OpenFlights airports database...")
    req = urllib.request.Request(OPENFLIGHTS_AIRPORTS_URL, headers={"User-Agent": "AviationSampling/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        of_airports_txt = resp.read().decode("utf-8", errors="ignore")

    of_country_map = {}
    for r in csv.reader(io.StringIO(of_airports_txt)):
        if len(r) >= 5:
            iata = r[4].strip().upper()
            country = r[3].strip()
            if len(iata) == 3 and iata.isalpha():
                of_country_map[iata] = country

    # 4. Fetch OpenFlights routes to calculate total & international route traffic
    print("[4/5] Downloading OpenFlights flight routes database (67,000+ routes)...")
    req = urllib.request.Request(OPENFLIGHTS_ROUTES_URL, headers={"User-Agent": "AviationSampling/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        of_routes_txt = resp.read().decode("utf-8", errors="ignore")

    total_routes = defaultdict(int)
    intl_routes = defaultdict(int)

    for r in csv.reader(io.StringIO(of_routes_txt)):
        if len(r) >= 5:
            src = r[2].strip().upper()
            dst = r[4].strip().upper()
            if src in of_country_map:
                total_routes[src] += 1
                if dst in of_country_map and of_country_map[src] != of_country_map[dst]:
                    intl_routes[src] += 1

    # 5. Filter and Rank
    print("\n[5/5] Filtering: strictly international flights (intl_routes > 0, local-only excluded)...")
    candidates = []
    for iata, our_apt in ourairports_map.items():
        # Exclude if no international routes found in flight networks
        n_intl = intl_routes[iata]
        n_total = total_routes[iata]
        if n_intl <= 0:
            continue

        ccode = our_apt.get("iso_country", "").strip().upper()
        cname = country_name_map.get(ccode, ccode)

        candidates.append({
            "iata": iata,
            "total_routes": n_total,
            "intl_routes": n_intl,
            "country_code": ccode,
            "country_name": cname,
            "our_apt": our_apt
        })

    # Sort descending by total routes (busiest hubs first), tie-breaker by international routes
    candidates.sort(key=lambda x: (x["total_routes"], x["intl_routes"]), reverse=True)
    print(f"Total verified international airports found: {len(candidates)}")

    selected = []
    country_counts = defaultdict(int)

    for c in candidates:
        ccode = c["country_code"]
        if country_counts[ccode] < max_per_country:
            selected.append(c)
            country_counts[ccode] += 1
            if len(selected) >= target_total:
                break

    print(f"\n[✓] Successfully selected {len(selected)} top airports across {len(country_counts)} countries.")
    print(f"[✓] Constraint verification: Max airports per country = {max(country_counts.values())} (Allowed limit: {max_per_country})")
    print(f"[✓] International verification: Min international routes = {min(c['intl_routes'] for c in selected)} (0 local-only airports)")

    # Build standardized output format
    output_rows = []
    for item in selected:
        apt = item["our_apt"]
        iata = item["iata"]
        icao = apt.get("icao_code", "").strip().upper() or apt.get("ident", "").strip().upper()
        ccode = item["country_code"]
        cname = item["country_name"]

        output_rows.append({
            "iata_code": iata,
            "icao_code": icao,
            "airport_name": apt.get("name", "").strip(),
            "city": apt.get("municipality", "").strip(),
            "country_code": ccode,
            "country_name": cname,
            "continent": apt.get("continent", "").strip(),
            "latitude_deg": apt.get("latitude_deg", "").strip(),
            "longitude_deg": apt.get("longitude_deg", "").strip(),
            "elevation_ft": apt.get("elevation_ft", "").strip(),
            "airport_type": apt.get("type", "").strip(),
            "planefinder_departures_url": f"https://planefinder.net/data/airport/{iata}/departures",
            "planefinder_arrivals_url": f"https://planefinder.net/data/airport/{iata}/arrivals",
        })

    # Sort alphabetically by country name, then airport name
    output_rows.sort(key=lambda x: (x["country_name"], x["airport_name"]))

    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Write to primary target files
    target_files = [
        data_dir / "airports_150.csv",
        data_dir / "airports_sample_100.csv"
    ]

    for out_path in target_files:
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(output_rows[0].keys()))
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"[✓] Successfully wrote {len(output_rows)} airports to '{out_path.name}'")

    return output_rows

if __name__ == "__main__":
    generate_airport_sample(target_total=150, max_per_country=2)
