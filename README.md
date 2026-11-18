# Flight Delay Prediction Pipeline: 100 Airports & Weather Intelligence

An automated, cloud-resilient end-to-end data pipeline that scrapes flight delay records across **100 global commercial airports** (max 2 airports per country), enriches each flight with strict anti-leakage pre-flight atmospheric observations (**WeatherAPI.com** + **AviationWeather.gov METAR**), and streams clean, non-redundant relational datasets into **Neon Serverless PostgreSQL**.

> **Detailed Technical Summary**: See [`PROJECT_SUMMARY.md`](PROJECT_SUMMARY.md) for the full architectural breakdown, data dictionary, and database design.

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
│   └── airports_sample_100.csv     # 100 curated international airports (60 countries)
├── docs/
│   └── FEATURES_GUIDE.md           # SQL derivation recipes & removed redundant columns guide
├── src/
│   ├── __init__.py
│   ├── aviation_api.py             # OpenSky Network OAuth2 REST API client
│   ├── batch_runner.py             # 6-batch runner with immediate SQL streaming
│   ├── db.py                       # Neon PostgreSQL batch upsert and schema management
│   ├── scraper.py                  # Playwright scraper with immediate fallback logic
│   └── weather.py                  # Aviation METAR + WeatherAPI historical fetcher
├── analyze_delays.py               # Delay analytics & weather benchmark report generator
├── main.py                         # Top-level unified CLI
├── requirements.txt                # Python dependencies
├── PROJECT_SUMMARY.md              # Full architectural documentation & data dictionary
└── README.md                       # Repository overview and quickstart guide
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

## 3. GitHub Actions (Automated Run Every 12 Hours: 00:00 & 12:00 UTC)

Workflow file: [`.github/workflows/scrape_pipeline.yml`](.github/workflows/scrape_pipeline.yml)

* **Schedule**: Runs automatically **every 12 hours at 00:00 and 12:00 UTC** (`cron: '0 0,12 * * *'`).
* **Matrix Concurrency**: Executes all 6 batches concurrently in parallel using GitHub Actions runners.
* **Dual-Engine Ingestion**: Uses Camoufox (a stealth Firefox hard fork spoofing fingerprint and behavioral leaks at the browser engine level with `xvfb-run`), and seamlessly falls back to **The OpenSky Network Authenticated API** when datacenter IPs encounter Cloudflare anti-bot challenges.
* **Manual Trigger**: Can also be executed manually anytime via the **Actions** tab in GitHub (**Run workflow** button).

### Required GitHub Environment Secrets (`DATABASE_URL` environment):
Under **Settings > Environments > DATABASE_URL > Environment secrets**:
1. `DATABASE_URL`: Your Neon PostgreSQL connection string.
2. `WEATHERAPI_KEY`: Your WeatherAPI key (`a0ba9f00b276465...`).
3. `OPENSKY_CLIENT_ID`: OpenSky OAuth2 client ID (`mohamedalaa-api-client`).
4. `OPENSKY_CLIENT_SECRET`: OpenSky OAuth2 client secret.

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
