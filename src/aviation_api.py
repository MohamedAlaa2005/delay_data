import base64
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime

# OpenSky OAuth2 Credentials
OPENSKY_CLIENT_ID = os.environ.get("OPENSKY_CLIENT_ID", "mohamedalaa-api-client")
OPENSKY_CLIENT_SECRET = os.environ.get("OPENSKY_CLIENT_SECRET", "NPckxI5Jia3JIQEutBZ6mPrVZ4H6h4x2")

# Token Cache
_cached_token = None
_token_expiry = 0

def get_opensky_token():
    """Retrieve or refresh OpenSky Network OAuth2 Bearer token."""
    global _cached_token, _token_expiry
    if _cached_token and time.time() < _token_expiry - 60:
        return _cached_token

    if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
        return None

    token_url = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
    payload = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": OPENSKY_CLIENT_ID,
        "client_secret": OPENSKY_CLIENT_SECRET
    }).encode("utf-8")

    req = urllib.request.Request(token_url, data=payload, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "AviationDelayPipeline/1.0"
    })

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            _cached_token = data.get("access_token")
            expires_in = data.get("expires_in", 1800)
            _token_expiry = time.time() + expires_in
            return _cached_token
    except Exception as e:
        print(f"     [!] Failed to get OpenSky OAuth token: {e}")
        return None

def fetch_opensky_flights(icao_code, direction="departures", hours_back=14):
    """
    Fetch flights directly from The OpenSky Network REST API using OAuth2 authentication.
    """
    if not icao_code:
        return []

    now = int(time.time())
    begin = now - (hours_back * 3600)
    end = now

    api_endpoint = "departure" if direction == "departures" else "arrival"
    url = f"https://opensky-network.org/api/flights/{api_endpoint}?airport={icao_code}&begin={begin}&end={end}"

    req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayPipeline/1.0"})
    
    # Attach OAuth2 Bearer token
    token = get_opensky_token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
            records = []
            for item in data:
                callsign = (item.get("callsign") or "").strip()
                if not callsign:
                    continue

                ts = item.get("firstSeen") if direction == "departures" else item.get("lastSeen")
                dt = datetime.utcfromtimestamp(ts) if ts else datetime.utcnow()
                date_str = dt.strftime("%A %d November %Y")
                time_str = dt.strftime("%H:%M UTC")

                route_apt = item.get("estArrivalAirport") if direction == "departures" else item.get("estDepartureAirport")
                
                records.append({
                    "airport_iata": "",  # Filled by caller
                    "airport_icao": icao_code,
                    "country": "",
                    "date": date_str,
                    "scheduled": time_str,
                    "flight": callsign,
                    "airline": callsign[:3],
                    "route_airport": route_apt or "Unknown",
                    "type": direction[:-1] if direction.endswith("s") else direction,
                    "status": f"{'Departed' if direction == 'departures' else 'Landed'} {time_str[:5]}",
                    "delay_minutes": 0,
                })

            print(f"     [OpenSky Authenticated API] Retrieved {len(records)} {direction} for {icao_code}.")
            return records
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"     [OpenSky API] No flights found for {icao_code} in the last {hours_back} hours.")
        elif e.code == 429:
            print(f"     [OpenSky API] Rate limit reached. Retrying...")
            time.sleep(2)
        else:
            print(f"     [OpenSky API] HTTP {e.code} for {icao_code}: {e.reason}")
        return []
    except Exception as e:
        print(f"     [OpenSky API] Error for {icao_code}: {e}")
        return []
