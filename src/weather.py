import json
import urllib.request
import zoneinfo
from datetime import datetime, timezone
from config.settings import WEATHERAPI_KEY

LONDON_TZ = zoneinfo.ZoneInfo("Europe/London")

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

def find_prior_weatherapi(weatherapi_hours, flight_dt_local):
    """Select the latest WeatherAPI observation strictly at or prior to flight schedule."""
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

def build_hourly_weather_records(iata, icao, date_set=None, api_key=None):
    """
    Generate normalized 24 hourly weather observations per day for an airport,
    standardized strictly to London time (Europe/London).
    Combines AviationWeather METAR reports with WeatherAPI history.
    Stored in 'airport_weather' (only 24 rows per day per airport vs thousands of flights).
    """
    if not date_set:
        now_london = datetime.now(LONDON_TZ)
        date_set = {now_london.strftime("%Y-%m-%d")}

    metar_list = fetch_aviation_metar(icao, hours=72) if icao else []
    wapi_hours = fetch_weatherapi_history(api_key, iata, date_set) if (api_key and iata) else []

    # Map WeatherAPI by London (date_str, hour)
    wapi_map = {}
    for h in wapi_hours:
        epoch = h.get("time_epoch")
        if epoch:
            dt_london = datetime.fromtimestamp(epoch, tz=LONDON_TZ)
            wapi_map[(dt_london.strftime("%Y-%m-%d"), dt_london.hour)] = h
        else:
            time_str = h.get("time")  # Format: "YYYY-MM-DD HH:00"
            if time_str:
                try:
                    dt = datetime.strptime(time_str[:16], "%Y-%m-%d %H:%M")
                    wapi_map[(dt.strftime("%Y-%m-%d"), dt.hour)] = h
                except Exception:
                    pass

    records = []
    for dt_str in sorted(date_set):
        try:
            day_dt = datetime.strptime(dt_str, "%Y-%m-%d")
        except Exception:
            continue

        for hour in range(24):
            # London wall-clock observation time
            obs_dt_london = datetime(day_dt.year, day_dt.month, day_dt.day, hour, 0, 0)
            
            # 1. Aviation METAR observation (compared strictly via UTC)
            obs_dt_utc = obs_dt_london.replace(tzinfo=LONDON_TZ).astimezone(timezone.utc)
            prior_metar = find_prior_metar(metar_list, obs_dt_utc)
            cloud_base = None
            if prior_metar and prior_metar.get("clouds"):
                base = prior_metar["clouds"][0].get("base")
                cloud_base = base if base is not None else None

            # 2. WeatherAPI observation for this London hour
            wapi_h = wapi_map.get((dt_str, hour))
            if wapi_h:
                cond = wapi_h.get("condition", {})
                w_temp = wapi_h.get("temp_c")
                w_feels = wapi_h.get("feelslike_c")
                w_rh = wapi_h.get("humidity")
                w_precip = wapi_h.get("precip_mm")
                w_press = wapi_h.get("pressure_mb")
                w_cloud = wapi_h.get("cloud")
                w_vis = wapi_h.get("vis_km")
                w_wspd = wapi_h.get("wind_kph")
                w_wdir = wapi_h.get("wind_degree")
                w_gust = wapi_h.get("gust_kph")
                w_text = cond.get("text", "")
                w_code = cond.get("code")
                w_is_day = wapi_h.get("is_day", 1)
            else:
                prior_w = find_prior_weatherapi(wapi_hours, obs_dt_utc) if wapi_hours else {}
                w_temp = prior_w.get("wapi_temp_c")
                w_feels = prior_w.get("wapi_feelslike_c")
                w_rh = prior_w.get("wapi_rh_pct")
                w_precip = prior_w.get("wapi_precip_mm")
                w_press = prior_w.get("wapi_pressure_hpa")
                w_cloud = prior_w.get("wapi_cloud_pct")
                w_vis = prior_w.get("wapi_vis_km")
                w_wspd = prior_w.get("wapi_wind_spd_kph")
                w_wdir = prior_w.get("wapi_wind_dir_deg")
                w_gust = prior_w.get("wapi_wind_gust_kph")
                w_text = prior_w.get("wapi_cond_text", "")
                w_code = prior_w.get("wapi_cond_code")
                w_is_day = prior_w.get("wapi_is_day", 1)

            rec = {
                "airport_iata": iata.strip().upper(),
                "observation_time": obs_dt_london,
                # Aviation Weather (METAR)
                "metar_time": prior_metar.get("reportTime", "") if prior_metar else "",
                "metar_flt_cat": prior_metar.get("fltCat", "") if prior_metar else "",
                "metar_temp_c": prior_metar.get("temp") if prior_metar else None,
                "metar_dewp_c": prior_metar.get("dewp") if prior_metar else None,
                "metar_wdir_deg": prior_metar.get("wdir") if prior_metar else None,
                "metar_wspd_kt": prior_metar.get("wspd") if prior_metar else None,
                "metar_visib_mi": prior_metar.get("visib", "") if prior_metar else "",
                "metar_altim_hpa": prior_metar.get("altim") if prior_metar else None,
                "metar_cover": prior_metar.get("cover", "") if prior_metar else "",
                "metar_cloud_base_ft": cloud_base,
                # Surface Weather (WeatherAPI)
                "wapi_temp_c": w_temp,
                "wapi_feelslike_c": w_feels,
                "wapi_rh_pct": w_rh,
                "wapi_precip_mm": w_precip,
                "wapi_pressure_hpa": w_press,
                "wapi_cloud_pct": w_cloud,
                "wapi_vis_km": w_vis,
                "wapi_wind_spd_kph": w_wspd,
                "wapi_wind_dir_deg": w_wdir,
                "wapi_wind_gust_kph": w_gust,
                "wapi_cond_text": w_text,
                "wapi_cond_code": w_code,
                "wapi_is_day": w_is_day,
            }
            records.append(rec)

    return records

