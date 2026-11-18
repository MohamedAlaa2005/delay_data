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

    subgraph Storage ["Persistent Cloud Storage"]
        NEON[("Neon PostgreSQL Cloud\nTables: departures | arrivals")]
    end

    CRON --> Matrix
    DISPATCH --> Matrix
    Matrix --> PF
    PF -->|Cloudflare Challenge / Block (Auto-retry once)| OS
    PF -->|Web Table Found| Enrichment
    OS -->|API Flight Records| Enrichment
    Enrichment --> METAR
    Enrichment --> WAPI
    METAR --> NEON
    WAPI --> NEON
```

---

## 2. Core Components

### A. Global Airports Dataset (`data/airports_150.csv`)
- **150 curated top international commercial airports** spanning **107 sovereign countries**.
- **Rule enforcement**: No single country has more than 2 airports (`max_per_country == 2`), preventing geographic bias.
- **International verification**: Exclusively airports operating international commercial routes (domestic/local-only airfields removed).
- Hub coverage includes high-volume airports across all continents (e.g., `ATL`, `ORD`, `PEK`, `PVG`, `LHR`, `LGW`, `CDG`, `FRA`, `MUC`, `AMS`, `HND`, `NRT`, `DXB`, `AUH`, `RUH`, `JED`, `EZE`, `GRU`, `YYZ`, `CAI`, `ADD`, `SYD`, `BNE`).

### B. Dual-Engine Flight Scraper (`src/scraper.py` & `src/aviation_api.py`)
- **Engine 1 (Plane Finder)**: Uses Playwright with stealth context to scrape airport arrival/departure boards, clicking *"Earlier flights"* continuously to capture preceding flight blocks.
- **Engine 2 (OpenSky Network OAuth2 Fallback)**: Datacenter IPs (such as GitHub Actions runners on Azure/Ubuntu) are challenged by Cloudflare. When a challenge (`Attention Required` / `Just a moment...`) or navigation timeout occurs, the system switches instantly to **The OpenSky Network REST API** using OAuth2 Client Credentials (`mohamedalaa-api-client`).

### C. Anti-Data Leakage Weather Enrichment (`src/weather.py`)
To prevent future data leakage in machine learning forecasting, weather observations are strictly filtered:
$$\text{Observation Timestamp} \le \text{Scheduled Flight Time}$$
- **Aviation Weather**: NOAA AviationWeather METAR (Flight Category `VFR`/`IFR`/`MVFR`/`LIFR`, Temperature, Dew point, Wind direction/speed, Visibility, Altimeter, Cloud cover, Cloud base).
- **Surface Weather**: WeatherAPI.com (Feels-like temperature, Humidity, Precipitation mm, Atmospheric pressure, Cloud cover %, Visibility km, Wind gust, Weather condition code).

### D. Streaming SQL Batch Loading (`src/db.py`)
- **Persistent Connection**: A single connection to Neon PostgreSQL is maintained throughout each batch.
- **Airport-by-Airport Streaming**: Records are committed to Neon immediately as each airport completes, ensuring zero data loss if a runner times out.
- **High-Performance Multi-Row Batching**: Uses `psycopg2.extras.execute_values` (`page_size=2000`).
- **Composite Unique Constraint & Idempotency**:
  ```sql
  CONSTRAINT uniq_{table}_flight_time UNIQUE (airport_iata, flight, scheduled_time)
  ```
  Flights are inserted via `ON CONFLICT (...) DO UPDATE SET`, updating existing delays without creating duplicate rows.

---

## 3. Database Schema (`departures` & `arrivals`)

Redundant derivable fields (`status`, `type`, `country`, `icao`) were eliminated to maintain 3NF database cleanliness:

| Column | Data Type | Source | Description |
|---|---|---|---|
| `id` | `SERIAL PRIMARY KEY` | Neon | Unique row identifier |
| `airport_iata` | `VARCHAR(3)` | Metadata | 3-letter IATA airfield code (e.g., `JED`, `SYD`) |
| `scheduled_time` | `TIMESTAMP` | Board / API | Scheduled UTC flight timestamp |
| `flight` | `VARCHAR(20)` | Board / API | Flight / Callsign (e.g., `SV1024`, `QF1`) |
| `airline` | `VARCHAR(60)` | Board / API | Operating carrier name or code |
| `route_airport` | `VARCHAR(60)` | Board / API | Destination (departures) or Origin (arrivals) |
| `delay_minutes` | `INT` | Derived | Delay relative to schedule ($>0$ late, $<0$ early, `NULL` cancelled) |
| `metar_time` | `VARCHAR(30)` | NOAA METAR | Timestamp of observation |
| `metar_flt_cat` | `VARCHAR(10)` | NOAA METAR | Flight category (`VFR`, `MVFR`, `IFR`, `LIFR`) |
| `metar_temp_c` | `FLOAT` | NOAA METAR | Air temperature in Celsius |
| `metar_dewp_c` | `FLOAT` | NOAA METAR | Dew point in Celsius |
| `metar_wdir_deg` | `INT` | NOAA METAR | Wind direction in degrees ($0^\circ-360^\circ$) |
| `metar_wspd_kt` | `INT` | NOAA METAR | Wind speed in knots |
| `metar_visib_mi` | `VARCHAR(10)` | NOAA METAR | Prevailing visibility in statute miles |
| `metar_altim_hpa` | `INT` | NOAA METAR | Altimeter setting in hectopascals |
| `metar_cover` | `VARCHAR(10)` | NOAA METAR | Sky cover (`SKC`, `FEW`, `SCT`, `BKN`, `OVC`) |
| `metar_cloud_base_ft` | `INT` | NOAA METAR | Base altitude of lowest cloud layer |
| `wapi_temp_c` | `FLOAT` | WeatherAPI | Surface ambient temperature |
| `wapi_feelslike_c` | `FLOAT` | WeatherAPI | Heat index / wind chill temperature |
| `wapi_rh_pct` | `INT` | WeatherAPI | Relative humidity percentage |
| `wapi_precip_mm` | `FLOAT` | WeatherAPI | Accumulated precipitation in millimeters |
| `wapi_pressure_hpa`| `FLOAT` | WeatherAPI | Barometric pressure in hPa |
| `wapi_cloud_pct` | `INT` | WeatherAPI | Cloud cover percentage ($0-100\%$) |
| `wapi_vis_km` | `FLOAT` | WeatherAPI | Surface visibility in kilometers |
| `wapi_wind_spd_kph` | `FLOAT` | WeatherAPI | Sustained wind speed in km/h |
| `wapi_wind_dir_deg` | `INT` | WeatherAPI | Wind direction in degrees |
| `wapi_wind_gust_kph`| `FLOAT` | WeatherAPI | Peak wind gust speed in km/h |
| `wapi_cond_text` | `VARCHAR(60)`| WeatherAPI | Atmospheric condition description |
| `wapi_cond_code` | `INT` | WeatherAPI | Standardized condition ID |
| `wapi_is_day` | `INT` | WeatherAPI | Solar illumination indicator (`1` day, `0` night) |
| `created_at` | `TIMESTAMP` | PostgreSQL | Ingestion timestamp (`CURRENT_TIMESTAMP`) |

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

