# Flight Delay Prediction Pipeline: 150 Top International Airports & Weather Intelligence

An automated, cloud-resilient end-to-end data pipeline that scrapes flight delay records across **150 top international commercial airports** (strictly international flights, max 2 airports per country across 107 sovereign countries), enriches each flight with strict anti-leakage pre-flight atmospheric observations (**WeatherAPI.com** + **AviationWeather.gov METAR**), and streams clean, non-redundant relational datasets into **Neon Serverless PostgreSQL**.

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
│   └── airports_150.csv            # 150 top international airports (107 countries, max 2 per country)
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

The **150 airports** are partitioned into **3 airport batches** (50 airports each), and each batch is split into **Departures** and **Arrivals**, creating **6 distinct batches**:

| Batch Name | Direction | Airports Covered | Typical Airfield Hubs |
| :--- | :--- | :---: | :--- |
| **Batch 1 - Departures** | Departures | Airports 1 &rarr; 50 | `ALG`, `LAD`, `AEP`, `EZE`, `EVN`, `AUA`, `BNE`, `SYD`, `VIE`, `GYD`, `NAS`, `BAH`, `DAC`, `MSQ`, `BRU`, `CRL`, `COO`, `GIG`, `GRU`, `YYZ` |
| **Batch 2 - Departures** | Departures | Airports 51 &rarr; 100 | `SCL`, `PEK`, `PVG`, `BOG`, `SJO`, `ZAG`, `HAV`, `LCA`, `PFO`, `PRG`, `CPH`, `PUJ`, `UIO`, `CAI`, `HBE`, `TLL`, `ADD`, `HEL`, `CDG`, `FRA` |
| **Batch 3 - Departures** | Departures | Airports 101 &rarr; 150 | `LHR`, `LGW`, `ATH`, `HKG`, `DEL`, `BOM`, `CGK`, `DPS`, `TLV`, `FCO`, `MXP`, `HND`, `NRT`, `RUH`, `JED`, `DXB`, `AUH`, `ATL`, `ORD` |
| **Batch 1 - Arrivals** | Arrivals | Airports 1 &rarr; 50 | Same 50 airports as Batch 1 |
| **Batch 2 - Arrivals** | Arrivals | Airports 51 &rarr; 100 | Same 50 airports as Batch 2 |
| **Batch 3 - Arrivals** | Arrivals | Airports 101 &rarr; 150 | Same 50 airports as Batch 3 |

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
