import json
import urllib.request
from datetime import datetime, timezone as dt_timezone
from config.settings import WEATHERAPI_KEY

def to_utc_epoch(dt):
    """Convert any naive (assumed GMT/UTC) or aware datetime to Unix UTC timestamp."""
    if dt is None:
        return 0
    if dt.tzinfo is None:
        return dt.replace(tzinfo=dt_timezone.utc).timestamp()
    return dt.astimezone(dt_timezone.utc).timestamp()

def fetch_aviation_metar(icao, hours=72):
    """Fetch official METAR reports from AviationWeather.gov (No key needed)."""
    if not icao:
        return []
    url = f"https://aviationweather.gov/api/data/metar?ids={icao}&format=json&hours={hours}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayPipeline/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return []

def find_prior_metar(metar_list, flight_dt_utc):
    """Select the latest METAR observation strictly at or prior to flight schedule (no data leakage)."""
    flight_ts = to_utc_epoch(flight_dt_utc)
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
    """Fetch hourly weather from WeatherAPI.com history endpoint."""
    if not api_key:
        return []
    hours_list = []
    for dt_str in date_set:
        url = f"http://api.weatherapi.com/v1/history.json?key={api_key}&q=iata:{iata}&dt={dt_str}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayPipeline/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                forecast_days = data.get("forecast", {}).get("forecastday", [])
                if forecast_days:
                    hours_list.extend(forecast_days[0].get("hour", []))
        except Exception:
            pass
    return hours_list

def find_prior_weatherapi(weatherapi_hours, flight_dt_gmt):
    """Select the latest WeatherAPI observation strictly at or prior to flight schedule."""
    flight_epoch = to_utc_epoch(flight_dt_gmt)
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

