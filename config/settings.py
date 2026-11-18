import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "docs"

# Core Data Files
AIRPORTS_FILE = DATA_DIR / "airports_sample_100.csv"

def load_env():
    """Load environment variables from .env.local or .env if present."""
    for env_name in [".env.local", ".env"]:
        env_path = BASE_DIR / env_name
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v

load_env()

# API Keys & Secrets
WEATHERAPI_KEY = os.environ.get("WEATHERAPI_KEY", "a0ba9f00b276465bbed141632261711")
DATABASE_URL = os.environ.get("DATABASE_URL")

# Batching Configurations
TOTAL_AIRPORTS = 100
BATCHES_COUNT = 3  # 100 / 3 = ~33 airports per batch

