import argparse
import csv
import os
import sys
import time
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from camoufox.sync_api import Camoufox
import urllib.request
import json
import re

# =====================================================================
# CONFIGURATION
# =====================================================================
WEATHERAPI_KEY = "a0ba9f00b276465bbed141632261711"
AIRPORTS_CSV = "airports_sample_100.csv"

DEPARTURES_CSV = "departures.csv"
ARRIVALS_CSV = "arrivals.csv"
DEPARTURES_WEATHER_CSV = "departures_with_weather.csv"
ARRIVALS_WEATHER_CSV = "arrivals_with_weather.csv"

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

def clean_cell_text(td):
    if not td:
        return ""
    return " ".join(td.get_text(separator=" ", strip=True).split())

def parse_flight_date(date_str):
    parts = date_str.strip().split()
    if len(parts) >= 4:
        try:
            day = int(parts[1])
            month = MONTH_MAP.get(parts[2].lower(), 11)
            year = int(parts[3])
            return year, month, day
        except Exception:
            pass
    return 2026, 11, 17

def parse_time(time_str):
    m = re.search(r"(\d{1,2}):(\d{2})", time_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

# =====================================================================
# 1. WEATHER ENRICHMENT FUNCTIONS
# =====================================================================
def fetch_aviation_metar(icao, hours=72):
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours={hours}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayML/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data
    except Exception:
        return []

def find_prior_metar(metar_list, flight_dt_utc):
    flight_ts = flight_dt_utc.timestamp()
    best_metar = None
    best_diff = float("inf")
    for m in metar_list:
        obs_ts = m.get("obsTime")
        if obs_ts is not None and obs_ts <= flight_ts:
            diff = flight_ts - obs_ts
            if diff < best_diff:
                best_diff = diff
                best_metar = m
    return best_metar

def fetch_weatherapi_history(api_key, iata, date_set):
    hours_list = []
    for dt_str in date_set:
        url = f"http://api.weatherapi.com/v1/history.json?key={api_key}&q=iata:{iata}&dt={dt_str}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayML/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                forecast_days = data.get("forecast", {}).get("forecastday", [])
                if forecast_days:
                    hours_list.extend(forecast_days[0].get("hour", []))
        except Exception:
            pass
    return hours_list

def find_prior_weatherapi(weatherapi_hours, flight_dt_local):
    flight_epoch = flight_dt_local.timestamp()
    best_hour = None
    best_diff = float("inf")
    for h in weatherapi_hours:
        epoch = h.get("time_epoch", 0)
        if epoch <= flight_epoch:
            diff = flight_epoch - epoch
            if diff < best_diff:
                best_diff = diff
                best_hour = h
    if best_hour:
        cond = best_hour.get("condition", {})
        return {
            "wapi_temp_c": best_hour.get("temp_c"),
            "wapi_feelslike_c": best_hour.get("feelslike_c"),
            "wapi_rh_pct": best_hour.get("humidity"),
            "wapi_precip_mm": best_hour.get("precip_mm"),
            "wapi_pressure_hpa": best_hour.get("pressure_mb"),
            "wapi_cloud_pct": best_hour.get("cloud"),
            "wapi_vis_km": best_hour.get("vis_km"),
            "wapi_wind_spd_kph": best_hour.get("wind_kph"),
            "wapi_wind_dir_deg": best_hour.get("wind_degree"),
            "wapi_wind_gust_kph": best_hour.get("gust_kph"),
            "wapi_cond_text": cond.get("text", ""),
            "wapi_cond_code": cond.get("code", ""),
            "wapi_is_day": best_hour.get("is_day", 1),
        }
    return {}

# =====================================================================
# 2. SCRAPING PER AIRPORT
# =====================================================================
def scrape_airport_direction(page, airport, direction="departures", max_clicks=8):
    iata = airport["iata_code"]
    url = f"https://planefinder.net/data/airport/{iata}/{direction}"
    print(f"\n--- Scraping {iata} ({airport['country_name']}) {direction.upper()} ---")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
    except Exception as e:
        print(f"[!] Navigation error for {iata}: {e}")
        return []

    # Check for empty / 404 or table
    try:
        page.wait_for_selector("table", timeout=8000)
    except Exception:
        print(f"[!] No table found for {iata} {direction}.")
        return []

    # Capture initial row IDs (offset 0) to separate later flights
    initial_ids = set(page.eval_on_selector_all("table tbody tr", "elements => elements.map(e => e.id).filter(id => id)"))

    # Continuous click on Earlier Flights using JS click to avoid ad overlays
    try:
        btn_present = page.eval_on_selector("button.earlier-flights", "btn => btn != null && !btn.disabled")
    except Exception:
        btn_present = False

    if btn_present:
        last_count = 0
        no_change = 0
        for i in range(1, max_clicks + 1):
            try:
                page.eval_on_selector("button.earlier-flights", "btn => btn.click()")
                page.wait_for_timeout(1500)
                cur_count = len(page.query_selector_all("table tbody tr"))
                if cur_count > last_count:
                    last_count = cur_count
                    no_change = 0
                else:
                    no_change += 1
                    if no_change >= 3:
                        break
            except Exception:
                break

    # Parse rendered HTML
    soup = BeautifulSoup(page.content(), "html.parser")
    table = soup.find("table")
    tbody = table.find("tbody") if table else None
    if not tbody:
        return []

    records = []
    current_date = ""

    for tr in tbody.find_all("tr"):
        separator = tr.find("td", colspan=True)
        if separator:
            current_date = separator.get_text(strip=True)
            continue

        row_id = tr.get("id", "")
        # Only take EARLIER flights (exclude initial offset 0 rows)
        if row_id and row_id in initial_ids:
            continue

        date_attr = tr.get("data-date", "").strip()
        row_date = date_attr if date_attr else current_date

        tds = tr.find_all("td")
        if not tds:
            continue

        raw_cells = [clean_cell_text(td) for td in tds]
        
        # Flight fields: Scheduled, Flight, Route, Airline, ..., Status
        sched = raw_cells[0] if len(raw_cells) > 0 else ""
        flight_no = raw_cells[1] if len(raw_cells) > 1 else ""
        route = raw_cells[2] if len(raw_cells) > 2 else ""
        airline = raw_cells[3] if len(raw_cells) > 3 else ""
        status = raw_cells[-1] if len(raw_cells) >= 5 else ""

        records.append({
            "airport_iata": iata,
            "airport_icao": airport["icao_code"],
            "country": airport["country_name"],
            "date": row_date,
            "scheduled": sched,
            "flight": flight_no,
            "airline": airline,
            "route_airport": route,
            "type": direction[:-1] if direction.endswith("s") else direction,
            "status": status,
        })

    print(f"[✓] Extracted {len(records)} earlier {direction} for {iata}.")
    return records

# =====================================================================
# 3. APPEND & ENRICH PIPELINE
# =====================================================================
def enrich_and_append_records(flight_records, weather_csv_path, airport):
    if not flight_records:
        return

    icao = airport["icao_code"]
    iata = airport["iata_code"]

    # 1. Fetch weather
    metar_data = fetch_aviation_metar(icao, hours=72)
    dates = {r["date"] for r in flight_records if r["date"]}
    iso_dates = set()
    for d_str in dates:
        y, m, d = parse_flight_date(d_str)
        iso_dates.add(f"{y:04d}-{m:02d}-{d:02d}")

    wapi_data = fetch_weatherapi_history(WEATHERAPI_KEY, iata, iso_dates) if WEATHERAPI_KEY else []

    enriched_rows = []
    for r in flight_records:
        y, m, d = parse_flight_date(r["date"])
        sh, sm = parse_time(r["scheduled"])
        if sh is None:
            sh, sm = 12, 0

        sched_dt_local = datetime(y, m, d, sh, sm)
        sched_dt_utc = sched_dt_local # approximation if timezone not parsed

        # Delay computation
        delay_minutes = ""
        is_cancelled = "cancelled" in r["status"].lower()
        if not is_cancelled:
            act_h, act_m = parse_time(r["status"])
            if act_h is not None:
                actual_dt = datetime(y, m, d, act_h, act_m)
                diff = (actual_dt - sched_dt_local).total_seconds()
                if diff < -43200: actual_dt += timedelta(days=1)
                elif diff > 43200: actual_dt -= timedelta(days=1)
                delay_minutes = round((actual_dt - sched_dt_local).total_seconds() / 60.0)

        # Weather lookup
        prior_metar = find_prior_metar(metar_data, sched_dt_utc)
        prior_wapi = find_prior_weatherapi(wapi_data, sched_dt_local)

        cloud_base = ""
        if prior_metar and prior_metar.get("clouds"):
            base = prior_metar["clouds"][0].get("base")
            cloud_base = base if base is not None else ""

        enriched = {
            "airport_iata": r["airport_iata"],
            "airport_icao": r["airport_icao"],
            "country": r["country"],
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
        }
        enriched.update(prior_wapi)
        enriched_rows.append(enriched)

    # Append to CSV
    file_exists = os.path.exists(weather_csv_path) and os.path.getsize(weather_csv_path) > 0
    fieldnames = list(enriched_rows[0].keys())

    with open(weather_csv_path, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerows(enriched_rows)

    print(f"[✓] Appended {len(enriched_rows)} rows to '{weather_csv_path}'.")

def get_already_scraped_airports():
    scraped = set()
    if os.path.exists(DEPARTURES_WEATHER_CSV):
        try:
            with open(DEPARTURES_WEATHER_CSV, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    iata = r.get("airport_iata", "").strip().upper()
                    if iata:
                        scraped.add(iata)
        except Exception:
            pass
    return scraped

def run_test(num_airports=100, country_filter=None):
    print(f"Loading airports from '{AIRPORTS_CSV}'...")
    if not os.path.exists(AIRPORTS_CSV):
        print(f"[!] File not found: {AIRPORTS_CSV}")
        return

    with open(AIRPORTS_CSV, "r", encoding="utf-8-sig") as f:
        airports = list(csv.DictReader(f))

    if country_filter:
        c_clean = country_filter.strip().lower()
        airports = [a for a in airports if c_clean in a["country_name"].lower() or c_clean == a["country_code"].lower()]
        print(f"Filtered for country matching '{country_filter}': found {len(airports)} airports.")

    already_done = get_already_scraped_airports()
    print(f"Found {len(already_done)} airports already scraped.")

    target_airports = airports[:num_airports]
    queue = [a for a in target_airports if a["iata_code"].strip().upper() not in already_done]

    print(f"Total target airports: {len(target_airports)} | Remaining to scrape: {len(queue)}")
    if not queue:
        print("[✓] All target airports are already scraped!")
        return

    print("Launching Camoufox (Stealth Firefox)...")
    with Camoufox(headless=False, canvas_noise=True, humanize=True, i_know_what_im_doing=True) as browser:
        context = browser.new_context()

        for idx, a in enumerate(queue, 1):
            iata = a["iata_code"]
            print(f"\n[{idx}/{len(queue)}] Processing airport: {iata} ({a['airport_name']}, {a['country_name']})...")
            
            page = None
            try:
                page = context.new_page()
                # 1. Departures
                dep_records = scrape_airport_direction(page, a, "departures")
                if dep_records:
                    enrich_and_append_records(dep_records, DEPARTURES_WEATHER_CSV, a)

                # 2. Arrivals
                arr_records = scrape_airport_direction(page, a, "arrivals")
                if arr_records:
                    enrich_and_append_records(arr_records, ARRIVALS_WEATHER_CSV, a)
            except Exception as err:
                print(f"[!] Error processing {iata}: {err}")
            finally:
                if page:
                    try:
                        page.close()
                    except Exception:
                        pass

        browser.close()

    print("\n==========================================")
    print("Scraping run completed!")
    print(f"Departures table: {DEPARTURES_WEATHER_CSV}")
    print(f"Arrivals table: {ARRIVALS_WEATHER_CSV}")
    print("==========================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100, help="Number of airports to process")
    parser.add_argument("--country", type=str, default=None, help="Filter to a specific country (e.g. 'Saudi Arabia' or 'SA')")
    args = parser.parse_args()
    run_test(num_airports=args.limit, country_filter=args.country)

