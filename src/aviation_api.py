import json
import time
import urllib.request
import os
from datetime import datetime

OPENSKY_USER = os.environ.get("OPENSKY_USERNAME")
OPENSKY_PASS = os.environ.get("OPENSKY_PASSWORD")

def fetch_opensky_flights(icao_code, direction="departures", hours_back=4):
    """
    Fetch flights directly from The OpenSky Network REST API.
    Works seamlessly on cloud datacenters (GitHub Actions, AWS, Azure).
    """
    if not icao_code:
        return []

    now = int(time.time())
    begin = now - (hours_back * 3600)
    end = now

    api_endpoint = "departure" if direction == "departures" else "arrival"
    url = f"https://opensky-network.org/api/flights/{api_endpoint}?airport={icao_code}&begin={begin}&end={end}"

    req = urllib.request.Request(url, headers={"User-Agent": "AviationDelayPipeline/1.0"})
    
    # Optional basic auth if registered at opensky-network.org
    if OPENSKY_USER and OPENSKY_PASS:
        import base64
        auth = base64.b64encode(f"{OPENSKY_USER}:{OPENSKY_PASS}".encode()).decode()
        req.add_header("Authorization", f"Basic {auth}")

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
                    "delay_minutes": 0, # Live tracking timestamp baseline
                })

            print(f"     [OpenSky API] Retrieved {len(records)} {direction} for {icao_code}.")
            return records
    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"     [OpenSky API] No flights found for {icao_code} in the last {hours_back} hours.")
        elif e.code == 429:
            print(f"     [OpenSky API] Rate limit reached. Backing off...")
            time.sleep(3)
        else:
            print(f"     [OpenSky API] HTTP {e.code} for {icao_code}: {e.reason}")
        return []
    except Exception as e:
        print(f"     [OpenSky API] Error for {icao_code}: {e}")
        return []
