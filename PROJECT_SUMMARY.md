# Flight Delay & Aviation Weather Intelligence Pipeline — Project Summary

An automated, cloud-resilient, production-ready data pipeline that tracks global commercial flight delays across **150 top international airports** (strictly international flights, max 2 airports per country across 107 sovereign countries), enriches flight movements with strictly prior atmospheric weather observations (**WeatherAPI.com** + **NOAA AviationWeather METAR**), and streams structured, non-redundant relational datasets into **Neon Serverless PostgreSQL**.

---

## 1. High-Level Architecture & Workflow

```mermaid
flowchart TD
    subgraph Scheduling ["Automated Trigger (Every 12 Hours: 00:00 & 12:00 UTC)"]
        CRON["GitHub Actions Cron Schedule: 0 0,12 * * *"]
        DISPATCH["Manual Trigger (workflow_dispatch)"]
    end

    subgraph Matrix ["6 Parallel Execution Batches"]
        B1D["Batch 1: Departures (Airports 1-50)"]
        B2D["Batch 2: Departures (Airports 51-100)"]
        B3D["Batch 3: Departures (Airports 101-150)"]
        B1A["Batch 1: Arrivals (Airports 1-50)"]
        B2A["Batch 2: Arrivals (Airports 51-100)"]
        B3A["Batch 3: Arrivals (Airports 101-150)"]
    end

    subgraph Ingestion ["Dual-Engine Flight Ingestion"]
        PF["Plane Finder Scraper (Camoufox Stealth Firefox / Playwright)"]
        OS["The OpenSky Network API (OAuth2 Authenticated Fallback)"]
    end

    subgraph Enrichment ["Anti-Data Leakage Atmospheric Enrichment"]
        METAR["NOAA AviationWeather.gov METAR (Aviation)"]
        WAPI["WeatherAPI.com Hourly History (Surface)"]
    end

    subgraph Storage ["Normalized Cloud Storage & SQL Views (Neon PostgreSQL)"]
        WDB[("airport_weather Table\n(24 Hourly Rows / Airport / Day)")]
        FDB[("departures | arrivals Tables\n(Lean Flight Movements)")]
        VIEW[["SQL Views:\nv_departures | v_arrivals\n(Equi-join on airport_iata + hour)"]]
    end

    CRON --> Matrix
    DISPATCH --> Matrix
    Matrix --> PF
    PF -->|Cloudflare Challenge / Block (Auto-retry once)| OS
    PF -->|Web Table Found| Enrichment
    OS -->|API Flight Records| Enrichment
    Enrichment --> METAR
    Enrichment --> WAPI
    METAR --> WDB
    WAPI --> WDB
    PF --> FDB
    OS --> FDB
    WDB --> VIEW
    FDB --> VIEW
```

---

## 2. Core Components

### A. Global Airports Dataset (`data/airports_150.csv`)
- **150 curated top international commercial airports** spanning **107 sovereign countries**.
- **Rule enforcement**: No single country has more than 2 airports (`max_per_country == 2`), preventing geographic bias.
- **International verification**: Exclusively airports operating international commercial routes (domestic/local-only airfields removed).
- Hub coverage includes high-volume airports across all continents (e.g., `ATL`, `ORD`, `PEK`, `PVG`, `LHR`, `LGW`, `CDG`, `FRA`, `MUC`, `AMS`, `HND`, `NRT`, `DXB`, `AUH`, `RUH`, `JED`, `EZE`, `GRU`, `YYZ`, `CAI`, `ADD`, `SYD`, `BNE`).

### B. Stealth Browser & OpenSky Fallback (`src/scraper.py` & `src/aviation_api.py`)
- **Engine 1 (Plane Finder via Camoufox)**: Uses Camoufox (a stealth Firefox hard fork spoofing fingerprint and behavioral leaks at the browser engine level) with automatic Cloudflare challenge detection and single-retry recovery.
- **Engine 2 (OpenSky Network OAuth2 Fallback)**: Datacenter IPs challenged by Cloudflare fall back seamlessly to **The OpenSky Network REST API** using OAuth2 Client Credentials (`mohamedalaa-api-client`).

### C. Dedicated 24-Hour Weather Pipeline (`src/weather_runner.py` & `src/weather.py`)
Rather than fetching weather inside each flight scraper batch (which causes duplicate API calls and slows down scrapers), weather ingestion runs in its own dedicated runner:
- Fetches **exactly 24 hourly observations per airport per day** strictly in **GMT (`UTC+0`)**.
- Stores in `airport_weather` (`(airport_iata, observation_time)` unique constraint).
- **Aviation Weather**: NOAA AviationWeather METAR (Flight Category `VFR`/`IFR`/`MVFR`/`LIFR`, Temperature, Dew point, Wind direction/speed, Visibility, Altimeter, Cloud cover, Cloud base).
- **Surface Weather**: WeatherAPI.com (Feels-like temperature, Humidity, Precipitation mm, Atmospheric pressure, Cloud cover %, Visibility km, Wind gust, Weather condition code).

### D. Timezone Standardization: Pure GMT (`UTC+0`, Zulu Time)
To guarantee consistency across all airports worldwide, all scheduled times in `departures` and `arrivals` and all observation times in `airport_weather` are standardized strictly to **pure GMT (`UTC+0`, without any daylight saving shifts)**:
- Local airport times scraped from boards are converted to GMT (`UTC+0`) using each airport's official IANA timezone.
- Hourly weather records are generated for hours `00:00` to `23:00` GMT.
- Views equi-join on `f.airport_iata = w.airport_iata AND date_trunc('hour', f.scheduled_time) = w.observation_time`.

### E. Streaming SQL Batch Loading (`src/db.py`)
- **Persistent Connection**: A single connection to Neon PostgreSQL is maintained throughout each batch.
- **Airport-by-Airport Streaming**: Records are committed to Neon immediately as each airport completes, ensuring zero data loss if a runner times out.
- **High-Performance Multi-Row Batching**: Uses `psycopg2.extras.execute_values` (`page_size=2000`).
- **Composite Unique Constraint & Idempotency**:
  - `airport_weather`: `(airport_iata, observation_time)`
  - `departures` / `arrivals`: `(airport_iata, flight, scheduled_time)`

---

## 3. Normalized Database Schema & SQL Views

Storing weather inside a dedicated table reduces weather storage footprint by **>90%** (e.g. 50,000 flights/day share 3,600 hourly weather rows instead of duplicating 23 weather columns 50,000 times).

### A. Hourly Weather Table (`airport_weather`)
Exactly **24 rows per airport per day**:

| Column | Data Type | Description |
|---|---|---|
| `airport_iata` | `VARCHAR(3)` | 3-letter IATA airfield code (e.g., `JED`, `SYD`) |
| `observation_time` | `TIMESTAMP` | Exact hourly observation timestamp (`YYYY-MM-DD HH:00:00`) |
| `metar_time` | `VARCHAR(30)` | Official METAR report timestamp |
| `metar_flt_cat` | `VARCHAR(10)` | Flight category (`VFR`, `MVFR`, `IFR`, `LIFR`) |
| `metar_temp_c` | `FLOAT` | Ambient air temperature in Celsius |
| `metar_dewp_c` | `FLOAT` | Dew point in Celsius |
| `metar_wdir_deg` | `INT` | Wind direction in degrees ($0^\circ-360^\circ$) |
| `metar_wspd_kt` | `INT` | Wind speed in knots |
| `metar_visib_mi` | `VARCHAR(10)` | Prevailing visibility in statute miles |
| `metar_altim_hpa` | `INT` | Altimeter setting in hectopascals |
| `metar_cover` | `VARCHAR(10)` | Sky cover (`SKC`, `FEW`, `SCT`, `BKN`, `OVC`) |
| `metar_cloud_base_ft` | `INT` | Lowest cloud ceiling base altitude in feet |
| `wapi_temp_c` | `FLOAT` | Surface ambient temperature |
| `wapi_feelslike_c` | `FLOAT` | Heat index / wind chill temperature |
| `wapi_rh_pct` | `INT` | Relative humidity percentage |
| `wapi_precip_mm` | `FLOAT` | Accumulated precipitation in millimeters |
| `wapi_pressure_hpa`| `FLOAT` | Barometric pressure in hPa |
| `wapi_cloud_pct` | `INT` | Cloud cover percentage ($0-100\%$) |
| `wapi_vis_km` | `FLOAT` | Surface visibility in kilometers |
| `wapi_wind_spd_kph` | `FLOAT` | Sustained wind speed in km/h |
| `wapi_wind_dir_deg` | `INT` | Wind direction in degrees |
| `wapi_wind_gust_kph`| `FLOAT` | Peak wind gust speed in km/h |
| `wapi_cond_text` | `VARCHAR(60)`| Atmospheric condition description |
| `wapi_cond_code` | `INT` | Standardized condition ID |
| `wapi_is_day` | `INT` | Solar illumination indicator (`1` day, `0` night) |
| `created_at` | `TIMESTAMP` | Record ingestion timestamp |

### B. Lean Flight Movement Tables (`departures` & `arrivals`)

| Column | Data Type | Description |
|---|---|---|
| `airport_iata` | `VARCHAR(3)` | 3-letter IATA airfield code |
| `scheduled_time` | `TIMESTAMP` | Scheduled flight timestamp |
| `flight` | `VARCHAR(20)` | Flight number / Callsign |
| `airline` | `VARCHAR(60)` | Operating carrier name or code |
| `route_airport` | `VARCHAR(60)` | Destination (departures) or Origin (arrivals) |
| `delay_minutes` | `INT` | Delay relative to schedule ($>0$ late, $<0$ early, `NULL` cancelled) |
| `status` | `VARCHAR(60)` | Raw operational status string |
| `created_at` | `TIMESTAMP` | Record ingestion timestamp |

### C. Unified SQL Views (`v_departures` & `v_arrivals`)
Enables direct SELECT queries that join flight movements with their corresponding hourly weather without any storage overhead:

```sql
CREATE OR REPLACE VIEW v_departures AS
SELECT 
    f.id, f.airport_iata, f.scheduled_time, f.flight, f.airline,
    f.route_airport, f.delay_minutes, f.status, 'departure' AS type,
    w.metar_time, w.metar_flt_cat, w.metar_temp_c, w.metar_dewp_c,
    w.metar_wdir_deg, w.metar_wspd_kt, w.metar_visib_mi, w.metar_altim_hpa,
    w.metar_cover, w.metar_cloud_base_ft, w.wapi_temp_c, w.wapi_feelslike_c,
    w.wapi_rh_pct, w.wapi_precip_mm, w.wapi_pressure_hpa, w.wapi_cloud_pct,
    w.wapi_vis_km, w.wapi_wind_spd_kph, w.wapi_wind_dir_deg, w.wapi_wind_gust_kph,
    w.wapi_cond_text, w.wapi_cond_code, w.wapi_is_day, f.created_at
FROM departures f
LEFT JOIN airport_weather w 
    ON f.airport_iata = w.airport_iata 
   AND date_trunc('hour', f.scheduled_time) = w.observation_time;
```

---

## 4. Current Neon Database Verification

As of the latest production verification:

| Neon Table | Total Records | Distinct Airports | Primary Verification |
|---|---|---|---|
| **`departures`** | **3,937** | 12 | Active & Indexed |
| **`arrivals`** | **3,850** | 12 | Active & Indexed |
| **Total Ingested** | **7,787** | — | Clean Relational Store |

---

## 5. Automated GitHub Actions (Every 12 Hours)

- **Schedule**: Twice a day at **00:00 and 12:00 UTC** (`cron: '0 0,12 * * *'`).
- **Matrix Configuration**:
  ```yaml
  strategy:
    max-parallel: 3
    matrix:
      batch: [1, 2, 3]
      direction: [departures, arrivals]
  ```
- **Environment**: Linked to GitHub Environment `DATABASE_URL` with encrypted secrets:
  - `DATABASE_URL`: Neon PostgreSQL connection URI.
  - `WEATHERAPI_KEY`: WeatherAPI.com access token.
  - `OPENSKY_CLIENT_ID`: OpenSky OAuth2 client ID.
  - `OPENSKY_CLIENT_SECRET`: OpenSky OAuth2 client secret.

---

## 6. Directory Structure

```text
delay_data/
├── .github/
│   └── workflows/
│       └── scrape_pipeline.yml     # 6-job matrix GitHub Actions workflow (12:00 UTC)
├── config/
│   ├── settings.py                 # Configuration manager & path resolutions
│   └── neon.ts                     # Neon CLI project configuration
├── data/
│   ├── airports_150.csv            # 150 top global international airports (max 2 per country)
│   ├── departures_with_weather.csv # Local cached departures with weather
│   └── arrivals_with_weather.csv   # Local cached arrivals with weather
├── docs/
│   └── FEATURES_GUIDE.md           # Guide for derived columns and SQL queries
├── src/
│   ├── __init__.py
│   ├── aviation_api.py             # OpenSky Network OAuth2 REST API client
│   ├── batch_runner.py             # 6-batch runner with immediate SQL streaming
│   ├── db.py                       # PostgreSQL schema manager and batch upsert engine
│   ├── scraper.py                  # Playwright scraper with immediate fallback logic
│   └── weather.py                  # Aviation METAR + WeatherAPI historical fetcher
├── analyze_delays.py               # Delay analytics and airport benchmarking tool
├── main.py                         # Top-level unified CLI interface
├── requirements.txt                # Production Python dependencies
├── PROJECT_SUMMARY.md              # Complete project documentation & summary
└── README.md                       # Repository overview and quickstart guide
```

---

## 7. How to Run Locally

### Run a Specific Batch:
```powershell
# Run Batch 1 Departures:
python -m src.batch_runner --batch 1 --direction departures

# Run Batch 2 Arrivals:
python -m src.batch_runner --batch 2 --direction arrivals
```

### Analyze Delays & Weather Correlation:
```powershell
# Global overview:
python analyze_delays.py

# Specific country filter:
python analyze_delays.py --country "Saudi Arabia"
python analyze_delays.py --country "Australia"
```

