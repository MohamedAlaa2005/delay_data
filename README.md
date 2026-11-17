# Flight Delay Prediction Pipeline: 100 Airports & Weather Intelligence

An automated end-to-end data pipeline that scrapes historical and live flight delay records across **100 global commercial airports** (max 2 airports per country), enriches each flight with strict anti-leakage pre-flight atmospheric observations (**WeatherAPI.com** + **AviationWeather.gov METAR**), and syncs clean, non-redundant relational tables into **Neon PostgreSQL**.

---

## 1. Project Structure

```text
delay_data/
├── .github/
│   └── workflows/
│       └── scrape_pipeline.yml     # Scheduled GitHub Actions (runs 12:00 UTC daily across 6 batches)
├── config/
│   ├── settings.py                 # Central configurations & environment loaders
│   └── neon.ts                     # Neon CLI project configuration
├── data/
│   ├── airports_sample_100.csv     # 100 curated international airports (60 countries)
│   ├── departures_with_weather.csv # Local cached departures with weather
│   └── arrivals_with_weather.csv   # Local cached arrivals with weather
├── docs/
│   └── FEATURES_GUIDE.md           # SQL derivation recipes & removed redundant columns guide
├── src/
│   ├── __init__.py
│   ├── scraper.py                  # Playwright Plane Finder scraper (with continuous earlier flight clicks)
│   ├── weather.py                  # WeatherAPI.com + AviationWeather METAR enrichment
│   ├── db.py                       # Neon PostgreSQL batch upsert and schema management
│   └── batch_runner.py             # CLI runner for the 6 batches
├── main.py                         # Top-level unified CLI
├── analyze_delays.py               # Delay analytics & weather benchmark report generator
├── push_to_neon.py                 # Standalone script to push local CSVs into Neon
├── requirements.txt                # Python dependencies
├── .env.example                    # Template for required environment variables
└── .gitignore                      # Safe ignore list (credentials, node_modules, logs)
```

---

## 2. The 6-Batch Architecture

The **100 airports** are partitioned into **3 airport batches**, and each batch is split into **Departures** and **Arrivals**, creating **6 distinct batches**:

| Batch Name | Direction | Airports Covered | Typical Airfield Hubs |
| :--- | :--- | :---: | :--- |
| **Batch 1 - Departures** | Departures | Airports 1 &rarr; 33 | `ALG`, `EZE`, `MEL`, `SYD`, `VIE`, `BAH`, `BRU`, `GIG`, `GRU`, `YYZ` |
| **Batch 2 - Departures** | Departures | Airports 34 &rarr; 66 | `SCL`, `PEK`, `PVG`, `BOG`, `PRG`, `CPH`, `CAI`, `HEL`, `CDG`, `FRA` |
| **Batch 3 - Departures** | Departures | Airports 67 &rarr; 100 | `LHR`, `ATH`, `HKG`, `DEL`, `BOM`, `CGK`, `FCO`, `HND`, `RUH`, `JED`, `DXB` |
| **Batch 1 - Arrivals** | Arrivals | Airports 1 &rarr; 33 | Same 33 airports as Batch 1 |
| **Batch 2 - Arrivals** | Arrivals | Airports 34 &rarr; 66 | Same 33 airports as Batch 2 |
| **Batch 3 - Arrivals** | Arrivals | Airports 67 &rarr; 100 | Same 34 airports as Batch 3 |

---

## 3. GitHub Actions (Automated Daily Run at 12 o'clock)

Workflow file: [`.github/workflows/scrape_pipeline.yml`](.github/workflows/scrape_pipeline.yml)

* **Schedule**: Runs automatically **every day at 12:00 UTC** (`cron: '0 12 * * *'`).
* **Matrix Concurrency**: Executes all 6 batches concurrently in parallel using GitHub Actions runners.
* **Manual Trigger**: Can also be executed manually anytime via the **Actions** tab in GitHub (**Run workflow** button).

### Required GitHub Repository Secrets
Under your GitHub repo's **Settings > Secrets and variables > Actions**, add:
1. `DATABASE_URL`: Your Neon PostgreSQL connection string (`postgresql://...`).
2. `WEATHERAPI_KEY`: Your WeatherAPI key (`a0ba9f00b276465...`).

---

## 4. Local Execution Commands

### Run a Specific Batch:
```powershell
# Run Batch 1 Departures:
python -m src.batch_runner --batch 1 --direction departures

# Run Batch 3 Arrivals:
python -m src.batch_runner --batch 3 --direction arrivals
```

### Run Delay Intelligence Analysis:
```powershell
# Full global report:
python analyze_delays.py

# Filter report by country:
python analyze_delays.py --country "Saudi Arabia"
python analyze_delays.py --country "Australia"
```

### Sync Local CSV Files to Neon:
```powershell
python push_to_neon.py
```

