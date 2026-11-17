import csv
import json
import re
import urllib.request
from datetime import datetime, timedelta

# =====================================================================
# CONFIGURATION
# =====================================================================
WEATHERAPI_KEY = "a0ba9f00b276465bbed141632261711"

AIRPORT_IATA = "AHB"
AIRPORT_ICAO = "OEAB"
AIRPORT_LAT = 18.2404
AIRPORT_LON = 42.6566

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12
}

def parse_flight_date(date_str):
    parts = date_str.strip().split()
    if len(parts) >= 4:
        day = int(parts[1])
        month = MONTH_MAP.get(parts[2].lower(), 11)
        year = int(parts[3])
        return year, month, day
    return 2026, 11, 17

def parse_time(time_str):
    m = re.search(r"(\d{1,2}):(\d{2})", time_str)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

# =====================================================================
# 1. AviationWeather.gov API (METAR - Official Airport Observations)
# =====================================================================
def fetch_aviation_metar(icao=AIRPORT_ICAO, hours=72):
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours={hours}"
    req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayML/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            print(f"[AviationWeather] Fetched {len(data)} METAR records for {icao}.")
            return data
    except Exception as e:
        print(f"[!] Error fetching METAR: {e}")
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

# =====================================================================
# 2. WeatherAPI.com API (History & Realtime)
# =====================================================================
def fetch_weatherapi_for_dates(api_key, date_set, query=f"iata:{AIRPORT_IATA}"):
    """Fetches hourly weather from WeatherAPI.com for each required flight date."""
    weatherapi_hours = []
    print(f"[WeatherAPI.com] Fetching weather for dates: {sorted(list(date_set))}...")

    for dt_str in sorted(list(date_set)):
        url = f"http://api.weatherapi.com/v1/history.json?key={api_key}&q={query}&dt={dt_str}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayML/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                forecast_days = data.get("forecast", {}).get("forecastday", [])
                if forecast_days:
                    hours = forecast_days[0].get("hour", [])
                    weatherapi_hours.extend(hours)
                    print(f"  -> {dt_str}: loaded {len(hours)} hourly records.")
        except Exception as e:
            print(f"  [!] WeatherAPI error for {dt_str}: {e}")

    return weatherapi_hours

def find_prior_weatherapi(weatherapi_hours, flight_dt_local):
    """Finds the WeatherAPI observation strictly at or prior to scheduled flight time."""
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
# 3. Open-Meteo Fallback
# =====================================================================
def fetch_open_meteo_weather(lat=AIRPORT_LAT, lon=AIRPORT_LON, past_days=4):
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&hourly=temperature_2m,relative_humidity_2m,precipitation,"
        f"surface_pressure,cloud_cover,visibility,wind_speed_10m,wind_direction_10m,wind_gusts_10m"
        f"&past_days={past_days}&forecast_days=1"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayML/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            hourly = data.get("hourly", {})
            return hourly
    except Exception as e:
        print(f"[!] Error fetching Open-Meteo: {e}")
        return {}

def find_prior_open_meteo(hourly, flight_dt_local):
    times = hourly.get("time", [])
    if not times:
        return {}
    flight_str = flight_dt_local.strftime("%Y-%m-%dT%H:00")
    best_idx = None
    for idx, t_str in enumerate(times):
        if t_str <= flight_str:
            best_idx = idx
        else:
            break
    if best_idx is not None:
        return {
            "wapi_temp_c": hourly.get("temperature_2m", [])[best_idx],
            "wapi_feelslike_c": hourly.get("temperature_2m", [])[best_idx],
            "wapi_rh_pct": hourly.get("relative_humidity_2m", [])[best_idx],
            "wapi_precip_mm": hourly.get("precipitation", [])[best_idx],
            "wapi_pressure_hpa": hourly.get("surface_pressure", [])[best_idx],
            "wapi_cloud_pct": hourly.get("cloud_cover", [])[best_idx],
            "wapi_vis_km": round(hourly.get("visibility", [])[best_idx] / 1000.0, 1),
            "wapi_wind_spd_kph": hourly.get("wind_speed_10m", [])[best_idx],
            "wapi_wind_dir_deg": hourly.get("wind_direction_10m", [])[best_idx],
            "wapi_wind_gust_kph": hourly.get("wind_gusts_10m", [])[best_idx],
            "wapi_cond_text": "Fair" if hourly.get("cloud_cover", [])[best_idx] < 50 else "Cloudy",
            "wapi_cond_code": 1000 if hourly.get("cloud_cover", [])[best_idx] < 50 else 1006,
            "wapi_is_day": 1 if 6 <= flight_dt_local.hour <= 18 else 0,
        }
    return {}

# =====================================================================
# 4. Pipeline Execution
# =====================================================================
def get_unique_dates(csv_paths):
    dates = set()
    for p in csv_paths:
        try:
            with open(p, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    y, m, d = parse_flight_date(r.get("Date", ""))
                    dates.add(f"{y:04d}-{m:02d}-{d:02d}")
        except Exception:
            pass
    return dates

def process_file(input_csv, output_csv, flight_direction, metar_records, weatherapi_data, open_meteo_hourly):
    rows_out = []
    
    with open(input_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        for row in reader:
            date_str = row.get("Date", "")
            sched_str = row.get("Scheduled", "")
            status_str = row.get("Status", "")

            y, m, d = parse_flight_date(date_str)
            sh, sm = parse_time(sched_str)
            if sh is None:
                continue

            sched_dt_local = datetime(y, m, d, sh, sm)
            sched_dt_utc = sched_dt_local - timedelta(hours=3)

            # Ground truth target: delay_minutes
            delay_minutes = ""
            is_cancelled = "cancelled" in status_str.lower()
            if not is_cancelled:
                act_h, act_m = parse_time(status_str)
                if act_h is not None:
                    actual_dt = datetime(y, m, d, act_h, act_m)
                    diff_sec = (actual_dt - sched_dt_local).total_seconds()
                    if diff_sec < -43200:
                        actual_dt += timedelta(days=1)
                    elif diff_sec > 43200:
                        actual_dt -= timedelta(days=1)
                    delay_minutes = round((actual_dt - sched_dt_local).total_seconds() / 60.0)

            # Strict prior weather matching
            prior_metar = find_prior_metar(metar_records, sched_dt_utc)

            if weatherapi_data:
                prior_weather = find_prior_weatherapi(weatherapi_data, sched_dt_local)
            else:
                prior_weather = find_prior_open_meteo(open_meteo_hourly, sched_dt_local)

            cloud_base = ""
            if prior_metar and prior_metar.get("clouds"):
                base = prior_metar["clouds"][0].get("base")
                cloud_base = base if base is not None else ""

            route_airport = row.get("Departing to") or row.get("Arriving from") or ""

            compact_row = {
                "date": date_str,
                "scheduled": sched_str,
                "flight": row.get("Flight", ""),
                "airline": row.get("Airline", ""),
                "route_airport": route_airport,
                "type": "departure" if flight_direction == "departure" else "arrival",
                "status": status_str,
                "delay_minutes": delay_minutes,
                # Aviation Weather (METAR)
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
            compact_row.update(prior_weather)
            rows_out.append(compact_row)

    if rows_out:
        fieldnames = list(rows_out[0].keys())
        with open(output_csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows_out)
        print(f"[✓] Saved compact dataset: {output_csv} ({len(rows_out)} rows)")
    return rows_out

def main():
    print("Initializing weather providers...")
    # 1. Aviation-specific METAR
    metar_records = fetch_aviation_metar(AIRPORT_ICAO, hours=72)

    # 2. WeatherAPI.com
    weatherapi_data = []
    open_meteo_hourly = {}

    if WEATHERAPI_KEY.strip():
        print(f"WeatherAPI.com key authenticated. Querying WeatherAPI for airport {AIRPORT_IATA}...")
        dates = get_unique_dates(["departures.csv", "arrivals.csv"])
        weatherapi_data = fetch_weatherapi_for_dates(WEATHERAPI_KEY.strip(), dates, query=f"iata:{AIRPORT_IATA}")
    else:
        print("No WeatherAPI key set. Falling back to Open-Meteo...")
        open_meteo_hourly = fetch_open_meteo_weather(AIRPORT_LAT, AIRPORT_LON, past_days=4)

    print("\nProcessing departures...")
    process_file("departures.csv", "departures_with_weather.csv", "departure", metar_records, weatherapi_data, open_meteo_hourly)

    print("\nProcessing arrivals...")
    process_file("arrivals.csv", "arrivals_with_weather.csv", "arrival", metar_records, weatherapi_data, open_meteo_hourly)

    print("\n[✓] Both split tables updated successfully!")

if __name__ == "__main__":
    main()
