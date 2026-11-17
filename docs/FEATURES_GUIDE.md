# Features Guide & On-the-Fly Derivation Recipes

To save disk storage and bandwidth, **derivable, redundant, and composite features have been removed from the raw CSV datasets** (`flights_ml_dataset.csv`, `departures_with_weather.csv`, `arrivals_with_weather.csv`).

Instead, only **raw, irreducible measurements** are preserved. You can compute all derived features dynamically in memory (e.g., using `pandas` or `polars`) during your ML data pipeline.

---

## 1. Removed Features & How to Derive Them in Memory

| Removed Feature | Reason for Removal | Fast Python / Pandas On-the-Fly Recipe |
| :--- | :--- | :--- |
| **`scheduled_datetime`** | Redundant with `date` + `scheduled` | `df['scheduled_dt'] = pd.to_datetime(df['date'] + ' ' + df['scheduled'].str.split().str[0])` |
| **`scheduled_hour`** | Direct substring of `scheduled` | `df['scheduled_hour'] = df['scheduled'].str.split(':').str[0].astype(int)` |
| **`scheduled_minute`** | Direct substring of `scheduled` | `df['scheduled_minute'] = df['scheduled'].str.extract(r':(\d{2})')[0].astype(int)` |
| **`scheduled_day_of_week`** | Inherent in `date` | `df['day_of_week'] = pd.to_datetime(df['date']).dt.day_name()` |
| **`is_weekend`** | Boolean check on `day_of_week` | `df['is_weekend'] = pd.to_datetime(df['date']).dt.weekday.isin([4, 5]).astype(int) # Saudi (Fri/Sat)` |
| **`is_delayed`** (Target) | Threshold check on `delay_minutes` | `df['is_delayed'] = (df['delay_minutes'] >= 15).astype(int)` |
| **`is_cancelled`** | Direct string match on `status` | `df['is_cancelled'] = df['status'].str.contains('cancelled', case=False, na=False).astype(int)` |
| **`route_iata`** | 3-letter IATA code inside `route_airport` | `df['route_iata'] = df['route_airport'].str.extract(r'([A-Z]{3})$')[0]` |
| **`airline_icao`** | 3-letter ICAO code inside `airline` | `df['airline_icao'] = df['airline'].str.extract(r'([A-Z]{3})$')[0]` |
| **`om_dew_point_2m`** | Calculable via Magnus formula | Derived from `om_temp_c` and `om_rh_pct` (or already present in METAR `metar_dewp_c`) |
| **`metar_raw`** | Raw text duplicates parsed columns | Dropped (saves ~80 bytes per row) |
| **`Terminal`, `Gate`, `Baggage`**| >95% null / empty on regional flights | Dropped from standard schema |

---

## 2. Retained Irreducible Columns (Clean Schema)

These are the non-derivable ground-truth and sensor readings stored in the CSV files:

### Flight Identifiers & Schedule
* **`date`**: Flight calendar date (e.g. `Tuesday 17 November 2026`).
* **`scheduled`**: Scheduled local departure/arrival time (e.g. `13:35 +03`).
* **`flight`**: Flight callsign/number (e.g. `F3338`).
* **`airline`**: Airline name and ICAO code (e.g. `flyadeal FAD`).
* **`route_airport`**: Destination or origin airport and IATA code (e.g. `Jeddah JED`).
* **`type`**: `departure` or `arrival`.
* **`status`**: Actual gate status (e.g. `Departed 13:37`, `Landed 12:50`, `Cancelled`).
* **`delay_minutes`**: Continuous target variable (actual minutes delayed, negative = early).

### Aviation-Specific Weather (METAR from AviationWeather.gov)
* **`metar_time`**: ISO observation timestamp (strictly prior to scheduled flight time).
* **`metar_flt_cat`**: Aviation flight category: `VFR` (Visual), `MVFR` (Marginal), `IFR` (Instrument), `LIFR` (Low Instrument).
* **`metar_temp_c`**: Airport ambient temperature in °C.
* **`metar_dewp_c`**: Dew point in °C.
* **`metar_wdir_deg`**: Wind direction in degrees ($0^{\circ} - 360^{\circ}$).
* **`metar_wspd_kt`**: Wind speed in knots.
* **`metar_visib_mi`**: Horizontal visibility in statute miles.
* **`metar_altim_hpa`**: Barometric pressure / altimeter setting in hPa.
* **`metar_cover`**: Cloud cover code (`CAVOK`, `FEW`, `SCT`, `BKN`, `OVC`).
* **`metar_cloud_base_ft`**: Lowest cloud ceiling in feet AGL.

### Meteorological Weather (WeatherAPI.com - `wapi_*`)
* **`wapi_temp_c`**: Ambient 2-meter air temperature (°C).
* **`wapi_feelslike_c`**: Apparent temperature accounting for humidity/wind (°C).
* **`wapi_rh_pct`**: Relative humidity percentage (%).
* **`wapi_precip_mm`**: Hourly precipitation amount (mm).
* **`wapi_pressure_hpa`**: Barometric pressure (hPa / mb).
* **`wapi_cloud_pct`**: Sky cloud coverage percentage (%).
* **`wapi_vis_km`**: Horizontal visibility distance in kilometers.
* **`wapi_wind_spd_kph`**: Wind speed in km/h.
* **`wapi_wind_dir_deg`**: Wind direction in degrees ($0^{\circ} - 360^{\circ}$).
* **`wapi_wind_gust_kph`**: Wind gust speed in km/h.
* **`wapi_cond_text`**: Natural-language weather summary (e.g., `Sunny`, `Cloudy`, `Patchy rain nearby`).
* **`wapi_cond_code`**: WeatherAPI numeric condition code (e.g., `1000` = Clear, `1006` = Cloudy, `1183` = Light rain).
* **`wapi_is_day`**: Binary solar indicator (`1` = Day, `0` = Night).

---

## 3. Ready-to-Use Python / Pandas Feature Engineering Pipeline

Copy and run this snippet in your ML training script:

```python
import pandas as pd

def load_and_engineer_features(csv_path="flights_ml_dataset.csv"):
    df = pd.read_csv(csv_path)

    # 1. Parse Scheduled Datetime
    time_clean = df['scheduled'].str.extract(r'(\d{1,2}:\d{2})')[0]
    df['scheduled_dt'] = pd.to_datetime(df['date'] + ' ' + time_clean)

    # 2. Extract Temporal Features
    df['scheduled_hour'] = df['scheduled_dt'].dt.hour
    df['day_of_week'] = df['scheduled_dt'].dt.day_name()
    # Saudi weekend: Friday (4) and Saturday (5)
    df['is_weekend'] = df['scheduled_dt'].dt.weekday.isin([4, 5]).astype(int)

    # 3. Categorical Airport & Airline Codes
    df['route_iata'] = df['route_airport'].str.extract(r'([A-Z]{3})$')[0]
    df['airline_icao'] = df['airline'].str.extract(r'([A-Z]{3})$')[0]

    # 4. Target Classification Flag (15+ min threshold standard in FAA/Eurocontrol)
    df['is_delayed'] = (pd.to_numeric(df['delay_minutes'], errors='coerce') >= 15).astype(int)
    df['is_cancelled'] = df['status'].str.contains('cancelled', case=False, na=False).astype(int)

    # 5. Wind Crosswind / Headwind Approximation (Runway 15/33 in Abha OEAB)
    # Runway heading ~ 150 degrees
    import numpy as np
    wind_dir = pd.to_numeric(df['metar_wdir_deg'], errors='coerce').fillna(0)
    wind_spd = pd.to_numeric(df['metar_wspd_kt'], errors='coerce').fillna(0)
    angle_rad = np.radians(wind_dir - 150)
    df['crosswind_kt'] = np.abs(wind_spd * np.sin(angle_rad))
    df['headwind_kt'] = wind_spd * np.cos(angle_rad)

    return df

if __name__ == "__main__":
    df = load_and_engineer_features()
    print("Engineered dataset preview:")
    print(df[['flight', 'scheduled_hour', 'is_delayed', 'crosswind_kt', 'metar_flt_cat']].head())
## 4. Neon PostgreSQL Schema & SQL Derivation Guide

The data is structured into two clean tables in Neon:
* **`departures`**
* **`arrivals`**

### Redundant Columns Removed from the SQL Tables & How to Get Them:

| Removed Column | Why It Was Removed | How to Retrieve / Derive in SQL |
| :--- | :--- | :--- |
| **`airport_icao`** & **`country`** | Static 1:1 mapping with `airport_iata` | `JOIN airports_sample_100 a ON departures.airport_iata = a.iata_code` |
| **`type`** | Redundant (data is already split into `departures` and `arrivals` tables) | Implicit from the table name (`SELECT 'departure' AS type FROM departures`) |
| **`status` (raw text)** | Redundant with `delay_minutes` | Numerical delay in `delay_minutes` conveys full delay ground truth |
| **`date` & `scheduled` (strings)** | Combined into a single standard column | `scheduled_time TIMESTAMP` (enables time-series indexing and range queries) |

---

### Ready-to-Use SQL Feature Engineering Queries

#### 1. Add Delay Flags and Time Buckets On-the-Fly:
```sql
SELECT 
    airport_iata,
    flight,
    airline,
    route_airport,
    scheduled_time,
    delay_minutes,
    -- Target classification: 15+ min threshold
    CASE WHEN delay_minutes >= 15 THEN 1 ELSE 0 END AS is_delayed,
    -- Delay severity category
    CASE 
        WHEN delay_minutes < 0 THEN 'Early'
        WHEN delay_minutes < 15 THEN 'On-Time'
        WHEN delay_minutes < 45 THEN 'Minor Delay'
        ELSE 'Severe Delay'
    END AS delay_tier,
    -- Temporal features
    EXTRACT(HOUR FROM scheduled_time) AS scheduled_hour,
    TO_CHAR(scheduled_time, 'Day') AS day_of_week,
    -- Weather indicators
    metar_flt_cat,
    wapi_temp_c,
    wapi_wind_spd_kph,
    wapi_precip_mm,
    wapi_cond_text
FROM departures;
```

#### 2. Join Airport Master Metadata:
```sql
SELECT 
    d.flight,
    d.airport_iata,
    a.airport_name,
    a.country_name,
    d.scheduled_time,
    d.delay_minutes,
    d.wapi_cond_text
FROM departures d
JOIN airports_sample_100 a ON d.airport_iata = a.iata_code;
```

